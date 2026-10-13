"""Package artifact-authored XLSX row batches without holding the whole workbook in memory.

The artifact tool remains the author of cells, formats, formulas and cached results.
This standard-library packager concatenates its worksheet rows, remaps shared
strings, and rebases relative formula references. It does not calculate or infer data.
"""
import hashlib,json,re,zipfile
from pathlib import Path
import xml.etree.ElementTree as ET

ROOT=Path(__file__).resolve().parents[1]/'output_fy27q2_20261012'
OUT=ROOT/'excel_exports'
NS='http://schemas.openxmlformats.org/spreadsheetml/2006/main'
ET.register_namespace('',NS)
Q=lambda tag:'{'+NS+'}'+tag
CELL_REF=re.compile(r'(?<![A-Za-z0-9_])(?P<col>\$?[A-Z]{1,3})(?P<absolute>\$?)(?P<row>[1-9][0-9]*)(?![A-Za-z0-9_])')

def rebase(text,offset):
    return CELL_REF.sub(lambda m:m.group(0) if m['absolute'] else m['col']+str(int(m['row'])+offset),text or '')

def main():
    model=json.loads((OUT/'workbook_model.json').read_text(encoding='utf-8'))
    count=len(model['rows']);del model
    chunks=sorted((OUT/'chunks').glob('chunk-*.xlsx'),key=lambda p:int(p.stem.split('-')[-1]))
    if not chunks:raise RuntimeError('No artifact chunks')
    strings=[];string_keys={};string_maps=[];styles=None
    for p in chunks:
        with zipfile.ZipFile(p) as z:
            current=z.read('xl/styles.xml')
            if styles is None:styles=current
            elif current!=styles:raise RuntimeError('Artifact chunk style IDs differ; safe assembly stopped')
            mapping={}
            if 'xl/sharedStrings.xml' in z.namelist():
                tree=ET.fromstring(z.read('xl/sharedStrings.xml'))
                for index,si in enumerate(tree):
                    key=ET.tostring(si,encoding='utf-8')
                    if key not in string_keys:string_keys[key]=len(strings);strings.append(si)
                    mapping[index]=string_keys[key]
            string_maps.append(mapping)
    with zipfile.ZipFile(chunks[0]) as first:
        sheet=first.read('xl/worksheets/sheet2.xml')
        match=re.search(rb'<(?P<prefix>[A-Za-z_][\w.-]*:)?sheetData(?:\s[^>]*)?>',sheet)
        if not match:raise RuntimeError('No sheetData')
        namespace_prefix=match.group('prefix') or b''
        close=sheet.index(b'</'+namespace_prefix+b'sheetData>',match.end())
        prefix=sheet[:match.end()];suffix=sheet[close:]
        dimension_pattern=rb'(<(?:[A-Za-z_][\w.-]*:)?dimension[^>]*\bref=")[^"]+("[^>]*/>)'
        if re.search(dimension_pattern,prefix):
            prefix=re.sub(dimension_pattern,lambda m:m[1]+f'A1:AM{count+1}'.encode()+m[2],prefix)
        else:
            dimension=b'<'+namespace_prefix+b'dimension ref="'+f'A1:AM{count+1}'.encode()+b'" />'
            prefix=re.sub(rb'(<(?:[A-Za-z_][\w.-]*:)?worksheet\b[^>]*>)',lambda m:m[1]+dimension,prefix,count=1)
        final=OUT/'CompraMX Tender FY27 Q2 Aug-Oct 2026 mapped.xlsx'
        temporary=OUT/'assembled_workbook.tmp.xlsx'
        with zipfile.ZipFile(temporary,'w',compression=zipfile.ZIP_DEFLATED,compresslevel=6,allowZip64=True) as target:
            for name in first.namelist():
                if name in {'xl/worksheets/sheet2.xml','xl/sharedStrings.xml','xl/calcChain.xml'}:continue
                target.writestr(name,first.read(name))
            total=0;string_references=0;formula_count=0;shared_formula_index=0
            with target.open('xl/worksheets/sheet2.xml','w',force_zip64=True) as stream:
                stream.write(prefix)
                for chunk_index,(p,mapping) in enumerate(zip(chunks,string_maps)):
                    offset=int(p.stem.split('-')[-1])
                    if offset!=total:raise RuntimeError(f'Noncontiguous chunks: {offset} != {total}')
                    shared_map={};chunk_rows=0
                    with zipfile.ZipFile(p) as z,z.open('xl/worksheets/sheet2.xml') as source:
                        for event,row in ET.iterparse(source,events=('end',)):
                            if row.tag!=Q('row'):continue
                            old_row=int(row.attrib['r'])
                            if old_row==1 and chunk_index:row.clear();continue
                            if old_row>1:total+=1;chunk_rows+=1
                            row.attrib['r']=str(old_row+offset)
                            for cell in row:
                                cell.attrib['r']=rebase(cell.attrib['r'],offset)
                                if cell.attrib.get('t')=='s':
                                    value=cell.find(Q('v'));value.text=str(mapping[int(value.text)]);string_references+=1
                                formula=cell.find(Q('f'))
                                if formula is not None:
                                    formula_count+=1;formula.text=rebase(formula.text,offset)
                                    if 'ref' in formula.attrib:formula.attrib['ref']=rebase(formula.attrib['ref'],offset)
                                    if 'si' in formula.attrib:
                                        local=formula.attrib['si']
                                        if local not in shared_map:shared_map[local]=shared_formula_index;shared_formula_index+=1
                                        formula.attrib['si']=str(shared_map[local])
                            stream.write(ET.tostring(row,encoding='utf-8'));row.clear()
                    print(f'ASSEMBLED {p.name} rows={chunk_rows} total={total}',flush=True)
                stream.write(suffix)
            if total!=count:raise RuntimeError(f'Expected {count} rows, got {total}')
            sst=ET.Element(Q('sst'),{'count':str(string_references),'uniqueCount':str(len(strings))})
            sst.extend(strings)
            target.writestr('xl/sharedStrings.xml',ET.tostring(sst,encoding='utf-8',xml_declaration=True))
    with zipfile.ZipFile(temporary) as check:
        if check.testzip() is not None:raise RuntimeError('XLSX CRC failure')
    temporary.replace(final)
    report={'rows':total,'columns':39,'chunks':len(chunks),'formulas_preserved':formula_count,'all_styles_identical':True,'sha256':hashlib.sha256(final.read_bytes()).hexdigest(),'method':'Artifact-authored row batches, streaming OOXML packaging with shared-string remapping and relative formula rebasing'}
    (OUT/'chunk_assembly_checks.json').write_text(json.dumps(report,indent=2),encoding='utf-8')
    print(json.dumps(report),flush=True)

if __name__=='__main__':main()

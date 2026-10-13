"""Read-only verification of final artifact cells, formula references and caches."""
import hashlib,json,math,sys
from collections import Counter
from datetime import date,datetime
from decimal import Decimal,ROUND_HALF_UP
from pathlib import Path
from openpyxl import load_workbook

ROOT=Path(__file__).resolve().parents[1]/'output_fy27q2_20261012'
OUT=ROOT/'excel_exports'
FORMULAS={27:'=IF(OR(Z{r}="",AA{r}="",AA{r}<Z{r}),"",DATEDIF(Z{r},AA{r},"m")+1)',32:'=IF(OR(AB{r}="",AND(V{r}="",W{r}="")),"",AVERAGE(V{r},W{r})*README!$B$11/AB{r})',33:'=IF(OR(AB{r}="",AND(T{r}="",U{r}="")),"",ROUND(AVERAGE(T{r},U{r})/AB{r},0))',34:'=IF(OR(AG{r}="",AM{r}=""),"",ROUND(AG{r}*AM{r},0))',35:'=IF(OR(AH{r}="",AM{r}=""),"",ROUND(AH{r}*AM{r},0))',36:'=IF(N{r}="","",N{r}*README!$B$11)',38:'=IF(OR(Z{r}="",AA{r}="",AA{r}<Z{r}),"",IF(OR(AA{r}<DATE(2026,8,1),Z{r}>DATE(2026,10,31)),0,DATEDIF(MAX(Z{r},DATE(2026,8,1)),MIN(AA{r},DATE(2026,10,31)),"m")+1))'}

def normalized(v):
    if isinstance(v,datetime):return (v.date()-date(1899,12,30)).days
    if isinstance(v,date):return (v-date(1899,12,30)).days
    return None if v=='' else v

def equivalent(a,b):
    a,b=normalized(a),normalized(b)
    if isinstance(a,(int,float,Decimal)) and isinstance(b,(int,float,Decimal)):
        return math.isclose(float(a),float(b),rel_tol=1e-10,abs_tol=1e-6)
    return a==b

def months(a,b):
    return (b.year-a.year)*12+b.month-a.month-(b.day<a.day)+1

def excel_round(v):return v.quantize(Decimal('1'),rounding=ROUND_HALF_UP)

def calculate(row):
    from datetime import timedelta
    a=date(1899,12,30)+timedelta(days=row[25]);b=date(1899,12,30)+timedelta(days=row[26])
    ab=months(a,b)
    am=0 if b<date(2026,8,1) or a>date(2026,10,31) else months(max(a,date(2026,8,1)),min(b,date(2026,10,31)))
    monetary=[Decimal(str(v)) for v in (row[21],row[22]) if isinstance(v,(int,float))]
    volume=[Decimal(str(v)) for v in (row[19],row[20]) if isinstance(v,(int,float))]
    ag=sum(monetary)/len(monetary)*Decimal('0.05')/ab if monetary else None
    ah=excel_round(sum(volume)/len(volume)/ab) if volume else None
    return {27:ab,32:ag,33:ah,34:excel_round(ag*am) if ag is not None else None,35:excel_round(ah*am) if ah is not None else None,36:Decimal(str(row[13]))*Decimal('0.05') if isinstance(row[13],(int,float)) else None,38:am}

def main():
    model=json.loads((OUT/'workbook_model.json').read_text(encoding='utf-8'))
    headers=json.loads((ROOT/'inputs/template_format.json').read_text(encoding='utf-8'))['headers']
    path=OUT/'CompraMX Tender FY27 Q2 Aug-Oct 2026 mapped.xlsx'
    values=load_workbook(path,read_only=True,data_only=True)
    formulas=load_workbook(path,read_only=True,data_only=False)
    errors=[];error_counts=Counter();zero_caches={};counts={'rows':0,'source_cells_checked':0,'formula_references_checked':0,'formula_caches_checked':0}
    def issue(kind,row,column,expected,actual):
        zero_only=kind=='formula_cache' and expected is not None and equivalent(expected,0) and normalized(actual) is None
        error_counts['zero_result_missing_cache' if zero_only else kind]+=1
        if zero_only:zero_caches.setdefault(row,[]).append(column)
        if len(errors)<100:errors.append({'kind':kind,'excel_row':row,'column':column+1,'expected':str(expected),'actual':str(actual)})
    actual_headers=list(next(values['Tenders'].iter_rows(min_row=1,max_row=1,values_only=True)))
    if actual_headers!=headers:issue('headers',1,0,headers,actual_headers)
    if not equivalent(values['README']['B11'].value,0.05):issue('fx',11,1,0.05,values['README']['B11'].value)
    if values['Tenders'].max_row!=len(model['rows'])+1 or values['Tenders'].max_column!=39:issue('dimensions',0,0,(len(model['rows'])+1,39),(values['Tenders'].max_row,values['Tenders'].max_column))
    for excel_row,(cached,formula_row,source) in enumerate(zip(values['Tenders'].iter_rows(min_row=2,values_only=True),formulas['Tenders'].iter_rows(min_row=2,values_only=True),model['rows']),start=2):
        counts['rows']+=1;expected=calculate(source)
        for c in range(39):
            if c in FORMULAS:
                counts['formula_references_checked']+=1
                text=FORMULAS[c].format(r=excel_row)
                if formula_row[c]!=text:issue('formula_reference',excel_row,c,text,formula_row[c])
                counts['formula_caches_checked']+=1
                if not equivalent(cached[c],expected[c]):issue('formula_cache',excel_row,c,expected[c],cached[c])
            else:
                counts['source_cells_checked']+=1
                if not equivalent(cached[c],source[c]):issue('source_cell',excel_row,c,source[c],cached[c])
        if counts['rows']%8000==0:print(f'CHECKED {counts["rows"]} rows issues={len(errors)}',flush=True)
    if counts['rows']!=77895:issue('row_count',0,0,77895,counts['rows'])
    values.close();formulas.close()
    report={'passed':not error_counts,**counts,'columns':39,'fx_mxn_to_usd':0.05,'error_counts':dict(error_counts),'errors':errors,'workbook_sha256':hashlib.sha256(path.read_bytes()).hexdigest(),'source_limitations':{'failed_notices':98,'english_missing_rows':11908,'october_through':'2026-10-10'},'complete_source_coverage':False,'method':'All source cells compared with corrected immutable model; every formula reference and cached result independently checked using the approved contract-month method'}
    (OUT/'final_workbook_verification.json').write_text(json.dumps(report,indent=2),encoding='utf-8')
    print(json.dumps(report),flush=True)
    if '--repair-zero-caches' in sys.argv and error_counts and set(error_counts)=={'zero_result_missing_cache'}:
        import re,shutil,zipfile
        import xml.etree.ElementTree as ET
        from openpyxl.utils.cell import get_column_letter
        ns='http://schemas.openxmlformats.org/spreadsheetml/2006/main'
        ET.register_namespace('',ns);q=lambda t:'{'+ns+'}'+t
        prior=ROOT/'review_snapshot_workbook_before_cache_repair.xlsx'
        if not prior.exists():shutil.copy2(path,prior)
        temporary=OUT/'zero_cache_corrected.tmp.xlsx';columns=Counter();repaired=0
        with zipfile.ZipFile(path) as original,zipfile.ZipFile(temporary,'w',compression=zipfile.ZIP_DEFLATED,compresslevel=6,allowZip64=True) as target:
            for name in original.namelist():
                if name!='xl/worksheets/sheet2.xml':target.writestr(name,original.read(name))
            # Preserve artifact-generated worksheet metadata verbatim.
            sheet=original.read('xl/worksheets/sheet2.xml')
            start=re.search(rb'<(?P<prefix>[A-Za-z_][\w.-]*:)?sheetData(?:\s[^>]*)?>',sheet)
            close=sheet.index(b'</'+(start.group('prefix') or b'')+b'sheetData>',start.end())
            prefix=sheet[:start.end()];suffix=sheet[close:];del sheet
            with original.open('xl/worksheets/sheet2.xml') as source,target.open('xl/worksheets/sheet2.xml','w',force_zip64=True) as stream:
                stream.write(prefix)
                for event,row in ET.iterparse(source,events=('end',)):
                    if row.tag!=q('row'):continue
                    row_number=int(row.attrib['r'])
                    addresses={get_column_letter(c+1)+str(row_number):c for c in zero_caches.get(row_number,[])}
                    for cell in row:
                        if cell.attrib.get('r') not in addresses:continue
                        if cell.find(q('f')) is None:raise RuntimeError('Repair target lost formula')
                        value=cell.find(q('v'))
                        if value is None:value=ET.SubElement(cell,q('v'))
                        if value.text not in (None,''):raise RuntimeError('Zero repair target cache is not blank')
                        cell.attrib['t']='n';value.text='0';repaired+=1;columns[get_column_letter(addresses[cell.attrib['r']]+1)]+=1
                    stream.write(ET.tostring(row,encoding='utf-8'));row.clear()
                stream.write(suffix)
        if repaired!=error_counts['zero_result_missing_cache']:raise RuntimeError('Cache repair count mismatch')
        with zipfile.ZipFile(temporary) as book:
            if book.testzip() is not None:raise RuntimeError('Cache repair ZIP CRC failure')
        temporary.replace(path)
        audit={'repaired_zero_caches':repaired,'by_column':dict(columns),'prior_sha256':report['workbook_sha256'],'corrected_sha256':hashlib.sha256(path.read_bytes()).hexdigest(),'formulas_and_source_cells_changed':False,'method':'Restore only independently verified numerical zero formula caches that artifact export saved blank. Actual formula text and all source values remain unchanged.'}
        (OUT/'zero_cache_repair_audit.json').write_text(json.dumps(audit,indent=2),encoding='utf-8')
        print('ZERO_CACHE_REPAIR '+json.dumps(audit),flush=True)
        return
    if errors:raise SystemExit(1)

if __name__=='__main__':main()

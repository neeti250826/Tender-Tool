"""Read frozen scraper evidence and prepare CANLAT models without editing XLSX files."""
import argparse,csv,hashlib,json,re,sys
from collections import Counter
from datetime import date,datetime
from pathlib import Path
import pandas as pd

BASE=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(BASE/'src'))
import step5_excel_export as export
import map_canlat_taxonomy as mapper
import finalize_canlat_mapped_workbook as canonical
import prepare_canlat_fy27_q1 as translations

def number(value):
    if value in (None,''):return None
    if isinstance(value,(int,float)):return value
    text=str(value).strip().replace('$','').replace(',','').replace('MXN','').strip()
    return float(text) if re.fullmatch(r'-?\d+(?:\.\d+)?',text) else str(value)

def date_number(value):
    parsed=translations.as_date(value)
    return (parsed-date(1899,12,30)).days if parsed else value or None

def write_csv(path,headers,rows):
    with path.open('w',encoding='utf-8-sig',newline='') as f:
        writer=csv.writer(f);writer.writerow(headers);writer.writerows(rows)

def main():
    parser=argparse.ArgumentParser();parser.add_argument('--root',type=Path,required=True);parser.add_argument('--store',type=Path);parser.add_argument('--skip-machine-translation',action='store_true');args=parser.parse_args()
    root=args.root.resolve();output=root/'excel_exports';output.mkdir(exist_ok=True)
    manifest=json.loads((root/'run_manifest.json').read_text(encoding='utf-8'))
    source=pd.read_csv(root/'inputs/selected_urls.csv',dtype=str,keep_default_na=False)
    source_index={row['URL']:row for row in source.to_dict('records')}
    store=args.store or root/'extraction/by_url/FY27Q2'
    payloads=[];corrupt=[]
    for path in sorted(store.glob('*.json')):
        try:
            payload=json.loads(path.read_text(encoding='utf-8'))
            if payload.get('url') in source_index:payloads.append(payload)
        except Exception as error:corrupt.append({'file':str(path),'error':str(error)})
    identity_mismatches=[];contract_count_mismatches=[];item_count_mismatches=[]
    for p in payloads:
        expected=source_index[p['url']].get('Código del expediente','').strip().upper()
        actual=str((p.get('page_kv') or {}).get('Código del expediente') or '').strip().upper()
        if p.get('ok') and expected and actual!=expected:
            identity_mismatches.append({'url':p['url'],'expected':expected,'observed':actual})
        evidence=(p.get('page_kv') or {}).get('_browser_observed_api') or {}
        detail=next((body.get('data') for endpoint,body in evidence.items() if '/expedientes/' in endpoint and '/anexos' not in endpoint and '/reqeconomicos' not in endpoint),None)
        if p.get('ok') and isinstance(detail,dict) and isinstance(detail.get('drc'),list):
            if len(detail['drc'])!=len(p.get('contracts') or []):contract_count_mismatches.append({'url':p['url'],'api_contracts':len(detail['drc']),'extracted_contracts':len(p.get('contracts') or [])})
            for api_contract,contract in zip(detail['drc'],p.get('contracts') or []):
                body=next((body for endpoint,body in evidence.items() if endpoint.endswith('/'+str(api_contract.get('cod_drc')))),None)
                if body is not None and isinstance(body.get('data'),list) and len(body['data'])!=len(contract.get('dialog_items') or []):item_count_mismatches.append({'url':p['url'],'contract':api_contract.get('cod_drc'),'api_items':len(body['data']),'extracted_items':len(contract.get('dialog_items') or [])})
    mismatched_urls={p['url'] for p in identity_mismatches+contract_count_mismatches+item_count_mismatches}
    success=[p for p in payloads if p.get('ok') is True and p['url'] not in mismatched_urls]
    raw_rows=[];row_currency=[];row_units=[];locators=[];warnings=[];notice_audit=[]
    seen_urls=set()
    for p in payloads:
        url=p['url'];seen_urls.add(url);s=source_index[url]
        items=sum(len(c.get('dialog_items') or []) for c in p.get('contracts') or [])
        accepted=bool(p.get('ok')) and url not in mismatched_urls
        notice_audit.append([s['Source CSV row'],url,s['Fecha publicación'],s['Estatus procedimiento'],accepted,len(p.get('contracts') or []),items,'source_reconciliation_mismatch' if url in mismatched_urls else p.get('error_kind'),p.get('error')])
        if not accepted:continue
        for ci,c in enumerate(p.get('contracts') or []):
            one=dict(p,contracts=[c]);rows=export.build_rows([one])
            for ii,row in enumerate(rows):
                raw_rows.append(row);row_currency.append((c.get('contract_row') or {}).get('Moneda',''))
                row_units.append(((c.get('dialog_items') or [])[ii].get('row') or {}).get('Unidad de medida',''))
                locators.append([url,ci,ii,s['Source CSV row'],s['Fecha publicación'],s['Estatus procedimiento']])
            for dialog in c.get('dialog_tables') or []:
                if dialog.get('pagination_warning'):warnings.append({'url':url,'contract':ci,'warning':dialog['pagination_warning']})
    for url,s in source_index.items():
        if url not in seen_urls:notice_audit.append([s['Source CSV row'],url,s['Fecha publicación'],s['Estatus procedimiento'],False,0,0,'unprocessed','No retained raw result'])
    write_csv(output/'notice_extraction_audit.csv',['Source CSV row','URL','Publication date','Source status','Parsed successfully','Contracts','Items','Error kind','Error'],notice_audit)
    write_csv(output/'raw_tender_data.csv',export.COLUMNS,[[r.get(c,'') for c in export.COLUMNS] for r in raw_rows])
    write_csv(output/'row_source_provenance.csv',['URL','Contract index','Item index','Source CSV row','Publication date','Source status'],locators)
    descriptions={translations.normalized_key(r['Detailed description (ESP)']):r['Detailed description (ESP)'] for r in raw_rows if r['Detailed description (ESP)']}
    reference_paths=[BASE/'output_apr2026plus/excel_exports/CompraMX Tender Extract_28072026_CANLAT_FY27_Q1_mapped.xlsx',BASE/'output_fy27q1_incremental_20260813/excel_exports/CompraMX Tender FY27 Q1 Batch 2 mapped.xlsx']
    known={};unit_labels={}
    for path in reference_paths:
        if path.exists():
            words,units=translations.collect_reference_translations(path);known.update(words);unit_labels.update(units)
    cache=translations.create_cache(output/'translation_cache.sqlite3')
    translations.write_cache(cache,[(key,text,'historical') for key,text in known.items() if key in descriptions])
    failures=0
    if not args.skip_machine_translation:
        _,failures=translations.translate_missing(cache,descriptions,6,3600)
    english=translations.read_cache(cache,descriptions);cache.close()
    records=[]
    for path in [BASE/'historical_references/CANLAT_Mexico_Tenders_File_v0.1.xlsx',BASE/'historical_references/CANLAT_Mexico_Tenders_Q1FY26.xlsx']:
        records.extend(mapper.iter_records(path))
    evidence=mapper.label_value_maps(records)
    company_map,family_map=canonical.canonical_evidence(BASE/'historical_references/CANLAT_Canonical_Taxonomy_Normalization_20260726_v1.xlsx')
    model=[];mapping_counts=Counter();mapping_basis=[];numeric_issues=[];foreign_currency=[];out_time=0;invalid_dates=0
    corrections_path=output/'manufacturer_corrections.json'
    reviewed=json.loads(corrections_path.read_text(encoding='utf-8')) if corrections_path.exists() else {}
    manufacturer_exclusions={(c['url'],c['spanish']) for c in reviewed.get('corrections',[])}
    family_exclusions={(c['url'],c['spanish']) for c in reviewed.get('family_corrections',[])}
    unit_glossary={'PIEZA':'Piece','SERVICIO':'Service','PAQUETE':'Package','LOTE':'Lot','KILOGRAMO':'Kilogram','LITRO':'Liter','JUEGO':'Set','METRO':'Meter','CAJA':'Box','UNIDAD':'Unit','PAR':'Pair','TONELADA':'Tonne'}
    money_indices={13,15,16,17,21,22,23,24};numeric_indices={12,13,15,16,17,19,20,21,22,23,24}
    for index,(raw,currency,unit,locator) in enumerate(zip(raw_rows,row_currency,row_units,locators),start=1):
        row=[index]+[raw.get(field,'') or None for field in export.COLUMNS]+[None]*12
        key=translations.normalized_key(raw['Detailed description (ESP)']);row[9]=translations.clean_translation(english[key]) if key in english else None;row[11]=unit_glossary.get(str(unit).strip().upper()) or unit_labels.get(key)
        for col in numeric_indices:
            row[col]=number(row[col])
            if isinstance(row[col],str):numeric_issues.append({'row':index+1,'column':col+1,'value':row[col],'url':raw['URL']})
        for col in (25,26):row[col]=date_number(row[col])
        start=translations.as_date(raw['Start Date']);end=translations.as_date(raw['End Date'])
        if not start or not end or end<start:invalid_dates+=1
        elif end<date(2026,8,1) or start>date(2026,10,31):row[10]='Out of time frame';out_time+=1
        row[37]='Q2 FY27'
        rec=mapper.TenderRecord(code=mapper.normalized_text(raw['Clave CUCoP+']),spanish=mapper.normalized_text(raw['Detailed description (ESP)']),english=mapper.normalized_text(row[9]),labels=('','','',''))
        exact,es=mapper.exact_labels(rec,evidence);phrase,ps=mapper.phrase_labels(rec,evidence,phrase_min_support=3,phrase_min_words=3);ident,ids=mapper.identifier_labels(rec,evidence,exact_manufacturer=exact[2]);labels,bases=mapper.merge_labels(exact,es,phrase,ps,ident,ids);labels=list(labels);bases=list(bases)
        family=canonical.canonical_family_labels(raw['Detailed description (ESP)'],family_map)
        if family and all(current in ('',None,expected) for current,expected in zip(labels,family)):
            for i,expected in enumerate(family):
                if not labels[i]:labels[i]=expected;bases[i]='audited_canonical_family'
        if not labels[2]:
            company=canonical.canonical_manufacturer(raw['Detailed description (ESP)'],company_map)
            if company:labels[2]=company;bases[2]='explicit_canonical_brand'
        # Broad extraction also includes stationery and generic clinical terms.
        # These two historical one-word identifiers do not establish an OEM.
        required_company={'Cardinal Health':r'\bcardinal\s+health\b','Lanceta HG':r'\blanceta\s+hg\b'}
        if labels[2] in required_company and not re.search(required_company[labels[2]],raw['Detailed description (ESP)'],re.I):
            labels[2]='';bases[2]='cleared_unsupported_bare_identifier'
        evidence_key=(raw['URL'],raw['Detailed description (ESP)'])
        if evidence_key in manufacturer_exclusions:labels[2]='';bases[2]='cleared_reviewed_source_ambiguity'
        if evidence_key in family_exclusions:labels[3]='';bases[3]='cleared_primary_product_mismatch'
        row[28:32]=[v or None for v in labels]
        for field,value in zip(mapper.LABEL_FIELD_NAMES,labels):
            if value:mapping_counts[field]+=1
        mapping_basis.append([index+1,raw['URL'],*labels,*bases])
        if currency and currency.upper() not in {'MXN','PESO MEXICANO','PESOS MEXICANOS'}:
            foreign_currency.append({'row':index+1,'url':raw['URL'],'currency':currency,'action':'Monetary cells withheld from MXN-based calculation; source retained in raw data'})
            for col in money_indices:row[col]=None
        model.append(row)
    qc={'selected_notices':len(source_index),'parsed_notices':len(success),'failed_notices':len(payloads)-len(success),'unprocessed_notices':len(source_index)-len(seen_urls),'notices_with_items':sum(bool(p.get('contracts')) and any(c.get('dialog_items') for c in p['contracts']) for p in success),'item_rows':len(raw_rows),'no_item_notices':sum(not any(c.get('dialog_items') for c in p.get('contracts') or []) for p in success),'corrupt_raw_files':corrupt,'identity_mismatches':identity_mismatches,'pagination_warnings':warnings,'invalid_or_reversed_contract_dates':invalid_dates,'out_of_time_frame_rows':out_time,'english_missing_rows':sum(r[9] is None for r in model),'translation_failures':failures,'mapping_coverage':dict(mapping_counts),'numeric_issues':numeric_issues,'non_mxn_rows':foreign_currency,'october_complete':False,'complete_row_certification':False}
    qc['all_urls_attempted']=qc['unprocessed_notices']==0 and not corrupt
    qc['contract_count_mismatches']=contract_count_mismatches
    qc['item_count_mismatches']=item_count_mismatches
    qc['extraction_complete']=qc['all_urls_attempted'] and qc['failed_notices']==0 and not warnings
    (output/'qc_findings.json').write_text(json.dumps(qc,indent=2,ensure_ascii=False),encoding='utf-8')
    (output/'workbook_model.json').write_text(json.dumps({'rows':model,'qc':qc},ensure_ascii=False),encoding='utf-8')
    headers=json.loads((root/'inputs/template_format.json').read_text(encoding='utf-8'))['headers']
    write_csv(output/'mapped_tender_data.csv',headers,model)
    write_csv(output/'unit_source_audit.csv',['Excel row','URL','Source unit','English unit'],[[i+2,raw['URL'],unit,row[11]] for i,(raw,unit,row) in enumerate(zip(raw_rows,row_units,model))])
    write_csv(output/'mapping_row_audit.csv',['Excel row','URL',*mapper.LABEL_HEADERS,'Sub OU basis','Category basis','Manufacturer basis','Family basis'],mapping_basis)
    print(json.dumps({k:v for k,v in qc.items() if k not in ('numeric_issues','non_mxn_rows','corrupt_raw_files','pagination_warnings')},ensure_ascii=True))

if __name__=='__main__':main()

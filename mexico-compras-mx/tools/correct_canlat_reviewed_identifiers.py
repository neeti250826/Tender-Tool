"""Apply the reviewed, scoped manufacturer exclusions without changing source data."""
import csv,hashlib,json,shutil
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]/'output_fy27q2_20261012'
OUT=ROOT/'excel_exports'
SNAPSHOT=ROOT/'review_snapshot_candidate_v2'

def main():
    SNAPSHOT.mkdir(exist_ok=True)
    for name in ['workbook_model.json','qc_findings.json','mapping_row_audit.csv','mapped_tender_data.csv']:
        target=SNAPSHOT/name
        if not target.exists():shutil.copy2(OUT/name,target)
    model=json.loads((OUT/'workbook_model.json').read_text(encoding='utf-8'))
    groups={'Siemens':[58273],'Stryker':[70144]}
    reasons={'Siemens':'Source lists multiple alternative compatible brands; no unique item OEM','Stryker':'Source names conflicting Stryker and Zimmer brands; no unique item OEM'}
    corrections=[]
    for company,rows in groups.items():
        for excel_row in rows:
            row=model['rows'][excel_row-2]
            if row[30]!=company:raise RuntimeError(f'Unexpected manufacturer at row {excel_row}')
            corrections.append({'excel_row':excel_row,'url':row[5],'spanish':row[8],'prior_manufacturer':company,'new_manufacturer':None,'reason':reasons[company],'reviewer':'mexico_preflight_review'})
            row[30]=None
    qc=model['qc'];qc['mapping_coverage']['manufacturer_name']-=len(corrections)
    qc['reviewed_manufacturer_exclusions']=qc.get('reviewed_manufacturer_exclusions',0)+len(corrections)
    qc['manufacturer_corrections_audit']='manufacturer_corrections.json'
    family_row=model['rows'][2027-2]
    if family_row[31]!='Aerogen Solo':raise RuntimeError('Unexpected family at row2027')
    family_correction={'excel_row':2027,'url':family_row[5],'spanish':family_row[8],'prior_family':'Aerogen Solo','new_family':None,'reason':'Primary item is Aerogen Pro-X; Solo appears as a required companion, not the item family','reviewer':'mexico_preflight_review'}
    family_row[31]=None
    qc['mapping_coverage']['family_name']-=1
    qc['reviewed_family_exclusions']=1
    temp=OUT/'workbook_model.corrected.tmp.json';temp.write_text(json.dumps(model,ensure_ascii=False),encoding='utf-8');temp.replace(OUT/'workbook_model.json')
    (OUT/'qc_findings.json').write_text(json.dumps(qc,indent=2,ensure_ascii=False),encoding='utf-8')
    with (OUT/'mapping_row_audit.csv').open(encoding='utf-8-sig',newline='') as stream:records=list(csv.reader(stream))
    corrected={c['excel_row'] for c in corrections}
    for record in records[1:]:
        if int(record[0]) in corrected:record[4]='';record[8]='cleared_unsupported_bare_identifier'
        if int(record[0])==2027:record[5]='';record[9]='cleared_primary_product_mismatch'
    with (OUT/'mapping_row_audit.csv').open('w',encoding='utf-8-sig',newline='') as stream:csv.writer(stream).writerows(records)
    headers=json.loads((ROOT/'inputs/template_format.json').read_text(encoding='utf-8'))['headers']
    with (OUT/'mapped_tender_data.csv').open('w',encoding='utf-8-sig',newline='') as stream:
        writer=csv.writer(stream);writer.writerow(headers);writer.writerows(model['rows'])
    archive=ROOT/'invalidated_workbook_chunks_v2';archive.mkdir(exist_ok=True)
    # Every currently generated batch was built before the reviewed correction.
    for path in (OUT/'chunks').glob('*'):shutil.move(str(path),str(archive/path.name))
    prior=json.loads((OUT/'manufacturer_corrections.json').read_text(encoding='utf-8'))
    audit={'corrections':prior['corrections']+corrections,'family_corrections':[family_correction],'original_model_sha256':prior['prior_model_sha256'],'prior_model_sha256':hashlib.sha256((SNAPSHOT/'workbook_model.json').read_bytes()).hexdigest(),'corrected_model_sha256':hashlib.sha256((OUT/'workbook_model.json').read_bytes()).hexdigest(),'item_rows_unchanged':len(model['rows']),'columns_unchanged':39,'source_values_changed':False,'manufacturer_coverage':qc['mapping_coverage']['manufacturer_name']}
    (OUT/'manufacturer_corrections.json').write_text(json.dumps(audit,indent=2,ensure_ascii=False),encoding='utf-8')
    print(json.dumps({k:v for k,v in audit.items() if k!='corrections'}))

if __name__=='__main__':main()

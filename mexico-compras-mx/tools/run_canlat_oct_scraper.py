"""Run the established parser with bounded direct-detail navigation.

The original scraper is unchanged. Direct navigation avoids its slow homepage
identity scan; every notice is checked against the procedure code before parsing.
"""
import csv,re,sys,time
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'src'))
import scrape_step3 as legacy
original_kv=legacy.extract_kv_fields
original_scrape=legacy.scrape_one
original_context=legacy._new_context_page
source_path=Path(__file__).resolve().parents[1]/'output_fy27q2_20261012/inputs/selected_urls.csv'
with source_path.open(encoding='utf-8-sig',newline='') as source:
    expected_codes={row['URL']:row['Código del expediente'].strip().upper() for row in csv.DictReader(source)}

def fast_identity(page):
    try:
        text=page.locator('body').inner_text(timeout=3000)
        match=re.search(r'\b[EP]-\d{4}-\d{5,}\b',text,re.I)
        return match.group(0).upper() if match else ''
    except Exception:
        return ''

def navigate(page,url,prev_exp,fast_timeout_ms=35000):
    # A hash-only page.goto is a same-document navigation and can expose the
    # previous tender's data. Leave the SPA before each new detail URL.
    page._canlat_observed_api={}
    page.goto('about:blank',wait_until='domcontentloaded',timeout=10000)
    page.goto(url,wait_until='domcontentloaded',timeout=90000)
    legacy.wait_for_route_hash(page,url,timeout_ms=10000)
    page.wait_for_function("() => /[EP][-–]\\s*20\\d{2}[-–]\\s*\\d{5,}/.test(document.body.innerText)",timeout=60000)
    page.wait_for_function("() => !Array.from(document.querySelectorAll('body *')).some(e => e.children.length === 0 && e.innerText === 'En proceso')",timeout=60000)
    actual=fast_identity(page)
    expected=expected_codes.get(url)
    if expected and actual!=expected:
        raise RuntimeError(f'Notice identity mismatch: expected {expected}, observed {actual}')
    return actual

def evidence_context(browser,block_resources,block_service_workers):
    ctx,page=original_context(browser,block_resources,block_service_workers)
    page._canlat_observed_api={}
    def record(response):
        if response.status!=200:return
        url=response.url
        if '/whitney/sitiopublico/' not in url:return
        if not re.search(r'/expedientes/[0-9a-f]+\?|/detallepartidas/[0-9a-f]+/',url):return
        try:
            body=response.json()
            if body.get('success') is True:page._canlat_observed_api[url]=body
        except Exception:pass
    page.on('response',record)
    return ctx,page

def current_kv(page):
    result=original_kv(page)
    lines=[line.strip() for line in page.locator('body').inner_text(timeout=5000).splitlines() if line.strip()]
    for i,line in enumerate(lines[:-1]):
        if line.endswith(':') and '\t' not in line:
            value=lines[i+1]
            if not value.endswith(':') and '\t' not in value:
                result.setdefault(line[:-1].strip(),value)
    identity=fast_identity(page)
    if not identity:raise RuntimeError('Notice identity missing after detail page load')
    result['Código del expediente']=identity
    if not result.get('Dependencia o Entidad'):
        raise RuntimeError('Buyer missing: refuse successful notice with incomplete parser identity')
    return result

def complete_contract_pages(page,url,fast_timeout_ms=35000,max_tables=0,extract_all=True):
    result=original_scrape(page,url,fast_timeout_ms,max_tables,extract_all)
    detail=None
    for endpoint,body in page._canlat_observed_api.items():
        if re.search(r'/expedientes/'+re.escape(legacy.url_route_key(url))+r'\?',endpoint):detail=body.get('data')
    api_total=len(detail['drc']) if isinstance(detail,dict) and isinstance(detail.get('drc'),list) else None
    result.page_kv['_browser_observed_api']=page._canlat_observed_api
    table=legacy.find_contracts_table(page)
    if not table.count():
        if api_total:raise RuntimeError(f'Contract table missing although browser response reports {api_total} contracts')
        result.page_kv['_reported_contract_total']=api_total
        result.page_kv['_contract_pages_visited']=0
        return result
    container=table.locator('xpath=ancestor::p-table[1]')
    if not container.count():container=table.locator('xpath=ancestor::div[contains(@class,"p-datatable")][1]')
    if not container.count():
        if api_total is not None and len(result.contracts)!=api_total:raise RuntimeError('Contract container missing and API count not reconciled')
        result.page_kv['_reported_contract_total']=api_total
        result.page_kv['_contract_pages_visited']=1
        return result
    reported=re.findall(r'Total\s*:\s*([\d,]+)',container.inner_text())
    expected=int(reported[-1].replace(',','')) if reported else None
    if api_total is not None:expected=api_total
    next_button=container.locator('button.p-paginator-next').first
    pages=1
    while next_button.count() and not legacy.is_disabled(next_button):
        if pages>=200:raise RuntimeError('Contract pagination safety limit reached')
        before=legacy.table_fingerprint_first_row(table);next_button.click()
        deadline=time.monotonic()+30
        while time.monotonic()<deadline:
            if legacy.table_fingerprint_first_row(table)!=before:break
            page.wait_for_timeout(200)
        else:raise RuntimeError('Contract pagination did not advance')
        rows=legacy.extract_html_table(table)['rows'];trs=table.locator('tbody tr')
        for i in range(trs.count()):
            cell=trs.nth(i).locator(legacy.CONTRACT_CELL_SEL).first
            if not cell.count():continue
            contract_number=legacy.norm(cell.inner_text())
            legacy.open_dialog_for_contract_cell(page,cell)
            dialog_tables,items=legacy.extract_dialog_tables_with_pagination(page)
            legacy.close_dialog(page)
            result.contracts.append({'contract_index':len(result.contracts),'contract_number_clicked':contract_number,'contract_row':rows[i] if i<len(rows) else {},'dialog_tables':dialog_tables,'dialog_items_count':len(items),'dialog_items':items})
        pages+=1
    result.page_kv['_contract_pages_visited']=pages
    result.page_kv['_reported_contract_total']=expected
    if expected is not None and len(result.contracts)!=expected:
        raise RuntimeError(f'Contract count mismatch: portal reports {expected}, extracted {len(result.contracts)}')
    # Retain only responses already observed during normal public UI navigation.
    # No tokens, request headers, or additional API requests are copied or made.
    result.page_kv['_browser_observed_api']=page._canlat_observed_api
    if isinstance(detail,dict):
        fields={'Cantidad mínima':'cantidad_minima','Cantidad máxima':'cantidad_maxima','Monto total cantidad mínima':'monto_minimo','Monto total cantidad máxima':'monto_maximo'}
        controls=[]
        for i,contract in enumerate(result.contracts):
            api_contract=detail['drc'][i]
            if api_contract.get('ref_interno')!=contract['contract_row'].get('Número de contrato'):
                raise RuntimeError('Browser API and contract table order do not match')
            api_items=[];observed_items=False
            for endpoint,body in page._canlat_observed_api.items():
                if endpoint.endswith('/'+str(api_contract.get('cod_drc'))):api_items=body.get('data') or [];observed_items=True
            controls.append({'contract_code':api_contract.get('cod_drc'),'api_items':len(api_items) if observed_items else None,'extracted_items':len(contract['dialog_items'])})
            if observed_items and len(api_items)!=len(contract['dialog_items']):
                raise RuntimeError(f'Item count mismatch for {api_contract.get("cod_drc")}: API {len(api_items)}, extracted {len(contract["dialog_items"])}')
            for item in contract['dialog_items']:
                row=item['row']
                matches=[x for x in api_items if legacy.norm(x.get('descripcion'))==legacy.norm(row.get('Descripción detallada')) and str(x.get('cve_cucop'))==str(row.get('Clave CUCoP+'))]
                if len(matches)!=1:continue
                for field,key in fields.items():
                    if row.get(field) in (None,'') and matches[0].get(key) is not None:row[field]=str(matches[0][key])
        result.page_kv['_item_completeness_controls']=controls
    return result

legacy.read_expediente_value=fast_identity
legacy.navigate_to_tender=navigate
legacy.extract_kv_fields=current_kv
legacy.scrape_one=complete_contract_pages
legacy._new_context_page=evidence_context
if __name__=='__main__':
    legacy.main()

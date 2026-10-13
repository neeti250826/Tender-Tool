"""Record the independent final pass and check the live handoff in a browser."""
import hashlib,json
from pathlib import Path
import supervise_canlat_oct_pipeline as pipeline
ROOT=pipeline.ROOT

def main():
    review=json.loads((ROOT/'review_final_workbook.json').read_text(encoding='utf-8'))
    checks=json.loads((ROOT/'release_checks.json').read_text(encoding='utf-8'))
    if not review['passed'] or review['workbook_sha256']!=checks['final_workbook_sha256']:raise RuntimeError('Independent review did not pass current workbook')
    checks['independent_final_review']='passed_for_best_available_delivery'
    checks['review_report']='review_final_workbook.json'
    (ROOT/'release_checks.json').write_text(json.dumps(checks,indent=2),encoding='utf-8')
    old=(ROOT/'handoff.html').read_text(encoding='utf-8')
    note=old[old.index('<h2>Workbook checks</h2>'):old.index('</body>')]
    note+='<p><a href="review_final_workbook.json">Independent final workbook review: passed</a></p>'
    pipeline.update('best_available_workbook_ready')
    handoff=ROOT/'handoff.html';body=handoff.read_text(encoding='utf-8');handoff.write_text(body.replace('</body>',note+'</body>'),encoding='utf-8')
    manifest=json.loads((ROOT/'deliverables_manifest.json').read_text(encoding='utf-8'))
    for name in ['release_checks.json','review_full_candidate.json','review_final_workbook.json','handoff.html']:
        p=ROOT/name;manifest['../'+name]={'bytes':p.stat().st_size,'sha256':hashlib.sha256(p.read_bytes()).hexdigest()}
    (ROOT/'deliverables_manifest.json').write_text(json.dumps(manifest,indent=2),encoding='utf-8')
    from playwright.sync_api import sync_playwright
    with sync_playwright() as driver:
        browser=driver.chromium.launch(headless=True)
        page=browser.new_page(viewport={'width':1250,'height':1000})
        page.goto(handoff.as_uri())
        text=page.locator('body').inner_text()
        for expected in ['77,895','11,908','best_available_workbook_ready','545,265']:
            if expected not in text:raise RuntimeError('Missing handoff text '+expected)
        missing=[]
        for href in page.locator('a').evaluate_all('(links)=>links.map(a=>a.getAttribute("href"))'):
            if not (ROOT/href).resolve().exists():missing.append(href)
        if missing:raise RuntimeError('Broken handoff links '+str(missing))
        page.screenshot(path=str(ROOT/'handoff_final.png'),full_page=True)
        browser.close()
    (ROOT/'handoff_browser_verification.json').write_text(json.dumps({'passed':True,'missing_links':[],'headings_and_counts_present':True},indent=2),encoding='utf-8')
    print('DELIVERY_READY best_available_workbook_ready',flush=True)

if __name__=='__main__':main()

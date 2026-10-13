"""Trusted reviewed-source Transparency adapter; user capture schema is primary.

The reviewed_snapshot mode reproduces complete frozen signed schedules and register
scopes with explicit parent replacement. Source HTTP discovery/extraction is in
scripts/crawl.py, reports.py, details.py, download_*.py and extract_tables.py.
New live-source rows require independent review and are not silently substituted.
"""
import json,pathlib,hashlib,urllib.parse,copy,collections
ROOT=pathlib.Path(__file__).resolve().parent
CANONICAL='source country country_code publication_date title title_english description description_english buyer buyer_english classification status currency amount awarding_agency_name awarding_agency_name_english supplier_name supplier_name_english awarded_date contract_period contract_period_english item_no item_description item_description_english item_uom item_uom_english quantity notice_id notice_url _source_workbook _duplicate_rows_removed _dedupe_key medtech_filter_basis mapped_oem mapped_oem_basis mapped_oem_match_term likely_oem likely_oem_score oem_match_terms oem_match_basis medtech_confidence'.split()
class Adapter:
 def __init__(self,url):
  if urllib.parse.urlparse(url).hostname not in ['www.transparencia.gob.sv','transparencia.gob.sv']:raise ValueError('Unexpected source host')
  self.url=url
 def extract(self,source=None):
  source=source or {};mode=source.get('mode','reviewed_snapshot')
  if mode!='reviewed_snapshot':raise RuntimeError('New live snapshots must be extracted and independently reviewed before this frozen adapter returns them')
  m=json.loads((ROOT/'final_batches_manifest.json').read_text(encoding='utf-8'));rows=[]
  for b in ['batch1','batch2']:
   x=m[b];p=ROOT/x['file']
   if hashlib.sha256(p.read_bytes()).hexdigest()!=x['sha256']:raise RuntimeError('Reviewed candidate hash changed')
   rows+=json.loads(p.read_text(encoding='utf-8'))
  rep=json.loads((ROOT/'batch2_replacement_manifest_final.json').read_text(encoding='utf-8'));replaced={k for a in rep['replacement_sets'] for k in a['replace_parent_keys']};rows=[r for r in rows if r['_evidence']['key'] not in replaced]
  if source.get('priced_only'):rows=[r for r in rows if r['_evidence'].get('document_id') in {a['document_id'] for a in rep['replacement_sets']}]
  elif source.get('include_hospital_reports',True):
   h=json.loads((ROOT/'batch3_final_revision_manifest.json').read_text(encoding='utf-8'));p=pathlib.Path(h['final_file'])
   if hashlib.sha256(p.read_bytes()).hexdigest()!=h['final_sha256']:raise RuntimeError('Reviewed hospital batch hash changed')
   review=json.loads((ROOT.parent/'review/isss_batch3_final_independent.json').read_text(encoding='utf-8'))
   if 'pass' not in str(review.get('verdict','')).lower():raise RuntimeError('Hospital batch independent review missing')
   rows+=json.loads(p.read_text(encoding='utf-8'))
  if source.get('canonical'):
   out=[];seq=collections.Counter()
   for r in rows:
    e=r['_evidence'];notice=e.get('document_id') or e['key'];seq[notice]+=1;c=dict.fromkeys(CANONICAL,'');c.update(source=r['Source portal'],country=r['Country'],country_code='SV',title=r['Tender title / description'],description=r['Product / test'],buyer=r['Buying institution / hospital'],classification=r['Indicator code'],status=r['Status'],currency=r['Currency'],amount=r['Total awarded'],awarding_agency_name=r['Buying institution / hospital'],supplier_name=r['Awarded supplier (distributor)'],awarded_date=r['Award date'],contract_period=r['Contract duration & extensions'],item_no=seq[notice],item_description=r['Product / test'],item_uom=r['Unit'],quantity=r['Quantity'],notice_id=notice,notice_url=r['Source link'],_dedupe_key=e['key'],_duplicate_rows_removed=len(e.get('alternate_source_rows',[])),medtech_filter_basis=e.get('mapping_reason',e.get('indicator_reason','Primary signed clinical diagnostic item schedule')),medtech_confidence='high' if e.get('item_code') else 'medium');c['_evidence']=copy.deepcopy(e);out.append(c)
   return out
  return copy.deepcopy(rows)
def create_adapter(url):return Adapter(url)

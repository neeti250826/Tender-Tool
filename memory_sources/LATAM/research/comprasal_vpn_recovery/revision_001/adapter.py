"""COMPRASAL public adapter: unallocated contract inventory only, never item sizing.

Frozen extraction verifies revision001. Live extraction delegates bounded official
unauthenticated registry/detail recovery, then applies documented source corrections.
Every live rerun still requires independent semantic review before inventory release.
"""
import copy,hashlib,importlib.util,json,pathlib,urllib.parse
ROOT=pathlib.Path(__file__).resolve().parent
class Adapter:
    def __init__(self,url):
        if urllib.parse.urlparse(url).hostname not in ('comprasal.gob.sv','www.comprasal.gob.sv'):
            raise ValueError('Unexpected source host')
        self.url=url
    def extract(self,source=None):
        source=source or {}
        manifest=json.loads((ROOT/'candidate_manifest.json').read_text(encoding='utf8'))
        if source.get('frozen_snapshot'):
            f=ROOT/'rows.json'
            if hashlib.sha256(f.read_bytes()).hexdigest()!=manifest['candidate_sha256']:
                raise RuntimeError('Frozen corrected inventory hash changed')
            rows=json.loads(f.read_text(encoding='utf8'))
        else:
            spec=importlib.util.spec_from_file_location('comprasal_public_recovery',ROOT.parent/'adapter.py')
            mod=importlib.util.module_from_spec(spec);spec.loader.exec_module(mod)
            raw=mod.create_adapter(self.url).extract(source)
            audit=json.loads((ROOT/'repair_audit.json').read_text(encoding='utf8'))
            fixes={x['row_id']:x for x in audit}
            names={x['Indicator code']:x['Segment name'] for x in json.loads((ROOT/'rows.json').read_text(encoding='utf8'))}
            rows=[]
            for original in raw:
                fix=fixes.get(original['_row_id'])
                if fix and fix['new_decision'] in ('held','excluded'):
                    continue
                r=copy.deepcopy(original)
                if fix:
                    r['Indicator code']=fix['new_indicator'];r['Segment name']=names[fix['new_indicator']]
                    r['_evidence']['source_review_correction']=fix
                r['Product / test']='Whole-procedure contract scope: '+r['Tender title / description']
                r['_evidence'].update(capture_record_type='unallocated_procedure_commitment_inventory',item_sizing_eligible=False,supplier_sizing_eligible=False,child_indicator_sizing_eligible=False,review_status='live_rerun_requires_independent_review',currency_basis='Official public USD formatter chain recorded in revision001 currency_evidence.json',pricing_hold='No priced item schedule; whole-procedure commitment only.')
                if fix and fix['action']=='remap_and_mark_ceiling':r['_evidence']['amount_kind']='awarded_commitment_or_ceiling_for_monthly_consumption'
                r['Comments']+=' Unallocated whole-procedure inventory only; not product/supplier sizing. Live rerun requires independent source review.'
                rows.append(r)
        headers=manifest['capture_headers']
        for r in rows:
            if set(r)!=set(headers+['_row_id','_evidence']):raise RuntimeError('Capture schema changed')
            if r['_evidence'].get('item_sizing_eligible') is not False or r['_evidence'].get('supplier_sizing_eligible') is not False:
                raise RuntimeError('Unallocated scope guard missing')
            if not r['_evidence']['amount_reconciles']:raise RuntimeError('Source amount reconciliation failed')
        return rows
def create_adapter(url):return Adapter(url)

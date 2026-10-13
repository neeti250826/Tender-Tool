"""Trusted public COMPRASAL snapshot/recovery adapter. No authentication state."""
import datetime,hashlib,json,pathlib,shutil,subprocess,sys,urllib.parse
ROOT=pathlib.Path(__file__).resolve().parent
SCRIPTS=['download_registry.py','scan_registry.py','prepare_processes.py','fetch_process_details.py','classify_candidates.py','build_rows.py']
class Adapter:
    def __init__(self,url):
        if urllib.parse.urlparse(url).hostname not in ('comprasal.gob.sv','www.comprasal.gob.sv'):raise ValueError('Unexpected source host')
        self.url=url
    def extract(self,source=None):
        source=source or {}
        if source.get('frozen_snapshot'):
            path=ROOT/'rows.json'; manifest=json.loads((ROOT/'candidate_manifest.json').read_text(encoding='utf8'))
            if hashlib.sha256(path.read_bytes()).hexdigest()!=manifest['sha256']:raise RuntimeError('Frozen candidate hash changed')
        else:
            # Separate run preserves the reviewed snapshot and all original evidence.
            stamp=datetime.datetime.now(datetime.timezone.utc).strftime('%Y%m%dT%H%M%S%fZ')
            parent=ROOT/'runs'; folder=parent/stamp; (folder/'raw').mkdir(parents=True)
            (parent/'inputs').mkdir(exist_ok=True);shutil.copy2(ROOT.parent/'inputs/keyword_map.json',parent/'inputs/keyword_map.json')
            for name in SCRIPTS:
                shutil.copy2(ROOT/name,folder/name)
                subprocess.run([sys.executable,str(folder/name)],check=True,timeout=10800)
            path=folder/'rows.json'
        rows=json.loads(path.read_text(encoding='utf8'))
        headers=json.loads((ROOT.parent/'inputs/keyword_map.json').read_text(encoding='utf8'))['Capture template'][0]
        for row in rows:
            if set(row)!=set(headers+['_row_id','_evidence']):raise RuntimeError('Capture schema changed')
            if not row['_evidence']['amount_reconciles']:raise RuntimeError('Award total fails reconciliation')
        return rows
def create_adapter(url):return Adapter(url)

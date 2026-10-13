from common import *
import pypdf,logging
logging.getLogger('pypdf').setLevel(logging.ERROR)
cards=json.loads((ROOT/'report_candidates.json').read_text(encoding='utf-8'))
cards=[r for r in cards if r['year'].isdigit() and 2019<=int(r['year'])<=2026 and not has(norm(r['title']),r'justific|plan.*(?:compra|adquisicion)|programa|manual|politica|resolucion|acta|nota aclaratoria|presupuesto|sin contrat|sin procesos|licitaciones.*plan')]
dump('reports_selected.json',cards)
def process(c):
 urls=[u for u in c['downloads'] if u.startswith('https://www.transparencia.gob.sv/descarga_archivo')]
 if not urls:return dict(id=c['id'],error='No direct public download observed')
 url=urls[0];path=RAW/f'report_{c["id"]}.bin';r={'url':url,'cache':True,'path':str(path)} if path.exists() else get(url,path.name)
 r.update(id=c['id'],institution_id=c['institution_id'],title=c['title'],year=c['year'])
 if 'error' in r:return r
 b=path.read_bytes();r.update(sha256=hashlib.sha256(b).hexdigest(),bytes=len(b))
 if b[:4]==b'%PDF':
  try:
   reader=pypdf.PdfReader(path);text='\n'.join(p.extract_text() or '' for p in reader.pages);tp=path.with_suffix('.txt');tp.write_text(text,encoding='utf-8');r.update(format='PDF',pages=len(reader.pages),text_chars=len(text),text_file=str(tp))
  except Exception as e:r.update(format='PDF',text_error=str(e))
 elif b[:2]==b'PK':r['format']='OOXML'
 elif b[:4]==bytes.fromhex('D0CF11E0'):r['format']='OLE XLS/DOC'
 else:r['format']='Other / HTML response'
 return r
out=[]
with concurrent.futures.ThreadPoolExecutor(max_workers=6) as pool:
 for n,r in enumerate(pool.map(process,cards),1):
  out.append(r)
  if n%25==0:dump('report_downloads.json',out);print('REPORT PDF',n,'/',len(cards),flush=True)
dump('report_downloads.json',out);log(out);print('REPORT DOWNLOAD DONE',len(out),flush=True)

from common import *
import pypdf,pdfplumber,logging
logging.getLogger('pypdf').setLevel(logging.ERROR)
mode=__import__('sys').argv[1];items=json.loads((ROOT/('contract_details.json' if mode=='contract' else 'reports_selected.json')).read_text(encoding='utf-8'))
td=ROOT/'raw_tables';td.mkdir(exist_ok=True)
def process(c):
 p=RAW/f'{mode}_{c["id"]}.bin';out=td/f'{mode}_{c["id"]}.json'
 if not p.exists() or p.read_bytes()[:4]!=b'%PDF':return None
 if out.exists():return {'id':c['id'],'cache':True}
 try:
  rd=pypdf.PdfReader(p);interesting=[];texts=[]
  for i,page in enumerate(rd.pages):
   if mode=='contract' and i>12:break
   t=page.extract_text() or '';texts.append({'page':i+1,'text':t})
   if mode=='contract':
    if has(norm(t),r'precio.*unitario|unitario.*precio') and has(norm(t),r'cantidad|contratad'):interesting.append(i)
   elif has(norm(t),r'reactivo|glucom|lanceta|tira.*glucos|laboratorio|histopat|molecular|pcr|secuenc|citometr|coagula'):interesting.append(i)
  tables=[]
  with pdfplumber.open(p) as pdf:
   for i in interesting:
    pg=pdf.pages[i];ts=pg.extract_tables();tables.append({'page':i+1,'width':pg.width,'height':pg.height,'tables':ts,'words':pg.extract_words() if mode=='contract' else [],'text':texts[i]['text']})
  result={'id':c['id'],'source_file':str(p),'sha256':hashlib.sha256(p.read_bytes()).hexdigest(),'source_metadata':c,'pages':len(rd.pages),'table_pages':tables,'all_examined_text':texts if mode=='report' else []}
  out.write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf-8');return {'id':c['id'],'interesting_pages':len(interesting),'tables':sum(len(x['tables']) for x in tables),'file':str(out)}
 except Exception as e:return {'id':c['id'],'error':str(e)}
out=[]
with concurrent.futures.ThreadPoolExecutor(max_workers=2) as pool:
 for n,r in enumerate(pool.map(process,items),1):
  if r:out.append(r)
  if n%25==0:dump(f'{mode}_table_log.json',out);print(mode,'TABLES',n,'/',len(items),flush=True)
dump(f'{mode}_table_log.json',out);print(mode,'TABLES DONE',len(out),flush=True)

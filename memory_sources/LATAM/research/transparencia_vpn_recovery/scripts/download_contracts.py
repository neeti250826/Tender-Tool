from common import *
import pypdf,logging
logging.getLogger('pypdf').setLevel(logging.ERROR)
cs=json.loads((ROOT/'contract_details.json').read_text(encoding='utf-8'))
def process(c):
    if not c.get('download'):return {'id':c['id'],'error':'No published attachment download'}
    name='contract_'+c['id']+'.bin';path=RAW/name
    r={'url':c['download'],'cache':True,'path':str(path)} if path.exists() else get(c['download'],name)
    r['id']=c['id']
    if 'error' in r:return r
    b=path.read_bytes();r['sha256']=hashlib.sha256(b).hexdigest();r['bytes']=len(b)
    if b[:4]==b'%PDF':
        try:
            reader=pypdf.PdfReader(path);text='\n'.join(x.extract_text() or '' for x in reader.pages);tp=path.with_suffix('.txt');tp.write_text(text,encoding='utf-8');r.update(format='PDF',pages=len(reader.pages),text_chars=len(text),text_file=str(tp))
        except Exception as e:r.update(format='PDF',text_error=str(e))
    elif b[:2]==b'PK':r['format']='ZIP / OOXML'
    else:r['format']='Unrecognized download / may be error page'
    return r
out=[]
with concurrent.futures.ThreadPoolExecutor(max_workers=4) as pool:
    for n,r in enumerate(pool.map(process,cs),1):
        out.append(r)
        if n%30==0:dump('contract_downloads.json',out);print('PDFS',n,'/',len(cs),flush=True)
dump('contract_downloads.json',out);log(out);print('PDFS DONE',len(out),flush=True)

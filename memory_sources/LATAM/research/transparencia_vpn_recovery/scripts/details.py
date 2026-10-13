from common import *
items=json.loads((ROOT/'classified_listing_candidates.json').read_text(encoding='utf-8'))
def process(c):
    name=f'detail_{c["id"]}.html';p=RAW/name
    if p.exists():record={'cache':True,'path':str(p)}
    else:record=get('https://www.transparencia.gob.sv/mostrarDocContratacionesDetalle.php',name,urllib.parse.urlencode(dict(id=c['id'],id_institucion=c['institution_id'])).encode())
    if 'error' in record:return c,record
    s=decode(p.read_bytes());f=fields(s)
    if not f:raise ValueError('No expected contract detail fields')
    title=re.search(r'<h5 class="func-name">(.*?)</h5>',s,re.S)
    c.update(detail_title=tidy(title[1]) if title else c['title'],fields=f,detail_file=str(p),detail_sha256=hashlib.sha256(p.read_bytes()).hexdigest())
    c['download']=next((html.unescape(u) for u in re.findall(r'href="([^"]+)"',s) if 'mostrarDocContratacionesDescarga' in u),c['download'])
    c['attachment_name']=tidy(re.search(r'<p class="doc-file-name">(.*?)</p>',s,re.S)[1]) if re.search(r'<p class="doc-file-name">(.*?)</p>',s,re.S) else ''
    return c,record
records=[];out=[]
with concurrent.futures.ThreadPoolExecutor(max_workers=4) as pool:
    for n,(c,r) in enumerate(pool.map(process,items),1):
        records.append(r);out.append(c)
        if n%40==0:dump('contract_details.json',out);print('DETAILS',n,'/',len(items),flush=True)
log(records);dump('contract_details.json',out);print('DONE',len(out),flush=True)

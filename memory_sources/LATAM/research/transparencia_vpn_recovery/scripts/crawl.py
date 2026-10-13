from access import *
import html,unicodedata
BASE='https://www.transparencia.gob.sv/'
def text(s):return html.unescape(re.sub('<[^>]*>',' ',s)).strip()
def tidy(s):return re.sub(r'\s+',' ',text(s)).strip()
def decode(b):
    try:return b.decode('utf-8')
    except UnicodeDecodeError:return b.decode('latin1')
def dump(name,obj):(ROOT/name).write_text(json.dumps(obj,ensure_ascii=False,indent=2,default=str),encoding='utf-8')
directory=json.loads((RAW/'hospital_directory.json').read_text())['data']
institutions={x['id_institucion']:x['nombre_institucion'] for x in directory}
institutions.update({20:'Ministerio de Salud (MINSAL)',27:'Instituto Salvadoreño del Seguro Social (ISSS)'})
queries=['reactiv','laborator','prueba','diagnost','gluc','lanceta','tira','comodato']
extras=['por prueba','segun demanda','contrato abierto','solucion integral','analiz','inmun','coagul','hemato','microbio','patolog','histolog','secuenc','molecular','genet','ELISA','PCR','cobas','sysmex','mindray','architect','accu','freestyle','dexcom','xpert','NGS','cartuch','sensor','sangre']
def parsecards(h,inst,path,query):
    out=[]
    for c in re.split(r'<div class="col-12 mt-3 doc-card-wrap">',h)[1:]:
        match=re.search(r"abrirDatosPaginaXLPortal\([^,]+,\s*'([^']+)'",c)
        if not match:continue
        title=re.search(r'<h6 class="doc-card-name">(.*?)</h6>',c,re.S)
        yr=re.search(r'<span class="doc-card-year">(.*?)</span>',c,re.S)
        if not title:raise ValueError('Missing contract title layout')
        links=re.findall(r'href="([^"]+)"',c)
        download=next((html.unescape(u) for u in links if 'mostrarDocContratacionesDescarga' in u),'')
        out.append({'id':match[1],'institution_id':inst,'institution':institutions[inst],'title':tidy(title[1]),'year':tidy(yr[1]) if yr else '', 'download':download,'raw_listing_file':str(path),'query':query})
    return out
def requestpage(job):
    inst,query,page=job;token=re.sub('[^a-zA-Z0-9]','_',query);name=f'listing_{inst}_{token}_p{page}.json';path=RAW/name
    if path.exists():
        j=json.loads(path.read_text(encoding='utf-8'));record={'cache':True,'path':str(path)}
    else:
        data=urllib.parse.urlencode({'id_institucion':inst,'id_estandar':16,'page':page,'busqueda':query,'year':''}).encode()
        record=get(BASE+'contratacionesListar.php',name,data);record.update(request_parameters={'id_institucion':inst,'id_estandar':16,'page':page,'busqueda':query,'year':''})
        if 'error' in record:return job,record,None,[]
        j=json.loads(path.read_text(encoding='utf-8'));time.sleep(.12)
    if not {'html','page','pages','total','count'}.issubset(j):raise ValueError('Unexpected listing response schema')
    return job,record,{k:v for k,v in j.items() if k!='html'},parsecards(j['html'],inst,path,query)
jobs=[(i,q,1) for i in institutions for q in queries]+[(i,q,1) for i in [20,27] for q in extras]
allcards={};searchlog=[];logs=[];follows=[]
with concurrent.futures.ThreadPoolExecutor(max_workers=4) as pool:
    for n,(job,record,meta,cards) in enumerate(pool.map(requestpage,jobs),1):
        logs.append(record);searchlog.append({'institution_id':job[0],'institution':institutions[job[0]],'query':job[1],'page':job[2],'response':meta,'error':record.get('error')})
        for c in cards:allcards[(c['institution_id'],c['id'])]=c
        if meta:
            if meta['pages']>200:searchlog[-1]['pagination_cap']=200
            follows.extend((job[0],job[1],p) for p in range(2,min(meta['pages'],200)+1))
        if n%40==0:dump('listing_candidates.json',list(allcards.values()));dump('search_log.json',searchlog);print('FIRST',n,'/',len(jobs),'unique',len(allcards),'followpages',len(follows),flush=True)
    log(logs);logs=[]
    for n,(job,record,meta,cards) in enumerate(pool.map(requestpage,follows),1):
        logs.append(record);searchlog.append({'institution_id':job[0],'institution':institutions[job[0]],'query':job[1],'page':job[2],'response':meta,'error':record.get('error')})
        for c in cards:allcards[(c['institution_id'],c['id'])]=c
        if n%40==0:dump('listing_candidates.json',list(allcards.values()));dump('search_log.json',searchlog);print('FOLLOW',n,'/',len(follows),'unique',len(allcards),flush=True)
    log(logs)
dump('listing_candidates.json',list(allcards.values()));dump('search_log.json',searchlog);dump('institutions.json',institutions)
print('DONE unique',len(allcards),'requests',len(searchlog),flush=True)

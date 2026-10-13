from common import *
directory=json.loads((RAW/'hospital_directory.json').read_text())['data'];names={x['id_institucion']:x['nombre_institucion'] for x in directory};names.update({20:'Ministerio de Salud (MINSAL)',27:'Instituto Salvadoreño del Seguro Social (ISSS)'})
queries=['consolidado','contrataciones','procesos de compra','listado de compras']
jobs=[(i,q,1) for i in names if i not in [20,27] for q in queries]+[(27,q,1) for q in ['reactiv','laborator','gluc','molecular','histolog','secuenc']]
def page(job):
    i,q,p=job;name=f'reports_{i}_{re.sub("[^a-zA-Z0-9]","_",q)}_p{p}.json';path=RAW/name
    record={'cache':True,'path':str(path)} if path.exists() else get('https://www.transparencia.gob.sv/documentosListar.php',name,urllib.parse.urlencode(dict(id_institucion=i,id_estandar=16,page=p,busqueda=q,year='')).encode())
    if 'error' in record:return job,record,None,[]
    j=json.loads(path.read_text(encoding='utf-8'));out=[]
    for c in re.split(r'<div class="col-12 mt-3 doc-card-wrap">',j['html'])[1:]:
        m=re.search(r"abrirDatosPaginaXLPortalDocumento\([^,]+,\s*'([^']+)'",c);title=re.search(r'<h6 class="doc-card-name">(.*?)</h6>',c,re.S);yr=re.search(r'<span class="doc-card-year">(.*?)</span>',c,re.S)
        if not m or not title:continue
        out.append({'id':m[1],'institution_id':i,'institution':names[i],'title':tidy(title[1]),'year':tidy(yr[1]) if yr else '', 'raw_listing_file':str(path),'query':q,'downloads':list(dict.fromkeys(html.unescape(x) for x in re.findall(r'href="([^"]+)"',c) if 'descarga_archivo' in x))})
    return job,record,{k:v for k,v in j.items() if k!='html'},out
allcards={};logs=[];search=[];follow=[]
with concurrent.futures.ThreadPoolExecutor(max_workers=4) as pool:
    for n,(job,r,m,cards) in enumerate(pool.map(page,jobs),1):
        logs.append(r);search.append({'institution_id':job[0],'query':job[1],'page':job[2],'metadata':m,'error':r.get('error')})
        for c in cards:allcards[(c['institution_id'],c['id'])]=c
        if m:follow.extend((job[0],job[1],p) for p in range(2,min(m['pages'],100)+1))
        if n%40==0:dump('report_candidates.json',list(allcards.values()));dump('report_search_log.json',search);print('REPORT FIRST',n,'/',len(jobs),'unique',len(allcards),'follow',len(follow),flush=True)
    log(logs);logs=[]
    for n,(job,r,m,cards) in enumerate(pool.map(page,follow),1):
        logs.append(r);search.append({'institution_id':job[0],'query':job[1],'page':job[2],'metadata':m,'error':r.get('error')})
        for c in cards:allcards[(c['institution_id'],c['id'])]=c
        if n%40==0:dump('report_candidates.json',list(allcards.values()));dump('report_search_log.json',search);print('REPORT FOLLOW',n,'/',len(follow),'unique',len(allcards),flush=True)
    log(logs)
dump('report_candidates.json',list(allcards.values()));dump('report_search_log.json',search)
print('REPORTS DONE',len(allcards),'requests',len(search),flush=True)

import urllib.request,urllib.parse,pathlib,json,time,hashlib,datetime,concurrent.futures
P=pathlib.Path(__file__).resolve().parent
(P/'raw'/'process_details').mkdir(exist_ok=True)
groups=json.loads((P/'process_candidates.json').read_text(encoding='utf-8'))
targets=[g for g in groups if g['scope_class']!='exclude_or_ambiguous']
def fetch(g):
 pid=g['process_id'];rid=g['records'][0]['id'];results=[]
 paths={'process_'+str(pid):'/api/v1/publico/obtener/detalle/procesos/publicos/'+str(pid),'award_'+str(rid):'/api/v1/publico/obtener/informe-adjudicacion/'+str(rid)}
 for name,path in paths.items():
  file=P/'raw'/'process_details'/(name+'.json');meta=P/'raw'/'process_details'/(name+'.meta.json');url='https://www.comprasal.gob.sv'+path
  if file.exists() and meta.exists():results.append(json.loads(meta.read_text()));continue
  for attempt in range(3):
   try:
    r=urllib.request.urlopen(urllib.request.Request(url,headers={'User-Agent':'Mozilla/5.0','Accept':'application/json'}),timeout=35);body=r.read();data=json.loads(body)
    if not isinstance(data.get('data'),dict):raise ValueError('Unexpected detail schema')
    info={'url':url,'status':r.status,'retrieved_utc':datetime.datetime.now(datetime.timezone.utc).isoformat(),'bytes':len(body),'sha256':hashlib.sha256(body).hexdigest(),'raw_file':str(file.relative_to(P))}
    file.write_bytes(body);meta.write_text(json.dumps(info,indent=2),encoding='utf-8');results.append(info);time.sleep(.2);break
   except Exception as exc:
    if attempt==2:results.append({'url':url,'error':str(exc)})
    else:time.sleep(2*(attempt+1))
 return results
log=[]
print('Target processes',len(targets),flush=True)
with concurrent.futures.ThreadPoolExecutor(max_workers=4) as pool:
 for n,infos in enumerate(pool.map(fetch,targets),1):
  log.extend(infos)
  if n%20==0:print('Completed',n,'/',len(targets),flush=True)
(P/'process_detail_fetch_log.json').write_text(json.dumps(log,indent=2),encoding='utf-8')
print('Done',len(targets),'errors',len([l for l in log if 'error' in l]),flush=True)

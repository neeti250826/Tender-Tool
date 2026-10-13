import urllib.request,re,json,pathlib,concurrent.futures,time,hashlib
ROOT=pathlib.Path(__file__).resolve().parents[1]
def get(url,name):
    try:
        req=urllib.request.Request(url,headers={'User-Agent':'Mozilla/5.0 tender research'})
        r=urllib.request.urlopen(req,timeout=50)
        data=r.read()
        (ROOT/'raw'/name).write_bytes(data)
        return {'url':url,'status':r.status,'path':str(ROOT/'raw'/name),'size':len(data),'sha256':hashlib.sha256(data).hexdigest()}
    except Exception as e: return {'url':url,'error':str(e)}
if __name__=='__main__':
    jobs=[('https://oncae.gob.hn/datos-abiertos/','oncae_index.html'),('https://datosabiertos.oncae.gob.hn/datosabiertos/HC1/HC1_datos_2025.json','HC1_2025.json'),('https://fastly.data.open-contracting.org/downloads/honduras_oncae/4176/2026.jsonl.gz','OCP_2026.jsonl.gz'),('https://honducompras.gob.hn/','honducompras.html'),('https://h2.honducompras.gob.hn','h2.html'),('https://portalunico.iaip.gob.hn/363/13/','iaip_heu.html'),('https://www.ihss.hn','ihss.html'),('https://www.salud.gob.hn','sesal.html')]
    with concurrent.futures.ThreadPoolExecutor(max_workers=4) as ex: results=list(ex.map(lambda v:get(*v),jobs))
    (ROOT/'access_log.json').write_text(json.dumps(results,ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps(results,indent=2))
    for p in ['oncae_index.html','honducompras.html']:
        f=ROOT/'raw'/p
        if f.exists():print(p, '\n'.join(x for x in re.findall(r'href=[\"\x27]([^\"\x27]+)',f.read_text(encoding='utf-8')) if any(z in x for z in ['datos','202','json','zip','sicc','h1','h2'])))

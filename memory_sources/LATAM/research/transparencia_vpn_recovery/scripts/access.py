import urllib.request,urllib.parse,pathlib,json,hashlib,re,concurrent.futures,time
ROOT=pathlib.Path(__file__).resolve().parents[1]; RAW=ROOT/'raw'; LOG=ROOT/'access_log.json'
def get(url,name,data=None):
    try:
        RAW.mkdir(parents=True, exist_ok=True)
        q=urllib.request.Request(url,data=data,headers={'User-Agent':'Mozilla/5.0','Content-Type':'application/x-www-form-urlencoded'} if data else {'User-Agent':'Mozilla/5.0'})
        r=urllib.request.urlopen(q,timeout=45);b=r.read();(RAW/name).write_bytes(b)
        return {'url':url,'final_url':r.url,'status':r.status,'response_type':r.headers.get('Content-Type'),'path':str(RAW/name),'bytes':len(b),'sha256':hashlib.sha256(b).hexdigest()}
    except Exception as e:return {'url':url,'error':str(e)}
def log(records):
    old=json.loads(LOG.read_text()) if LOG.exists() else [];LOG.write_text(json.dumps(old+records,ensure_ascii=False,indent=2),encoding='utf-8')
if __name__=='__main__':
    urls=[('https://www.transparencia.gob.sv/contracts/27-16','isss_contracts.html'),('https://www.transparencia.gob.sv/contracts/20-16','minsal_contracts.html'),('https://www.transparencia.gob.sv/app-js/transparencia.v3.js','transparencia.v3.js')]
    with concurrent.futures.ThreadPoolExecutor(max_workers=3) as e:rs=list(e.map(lambda x:get(*x),urls))
    log(rs);print(json.dumps(rs,indent=2))

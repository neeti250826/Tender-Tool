from discover import *
import gzip,unicodedata,collections
def norm(x):return ''.join(c for c in unicodedata.normalize('NFKD',str(x)).lower() if not unicodedata.combining(c))
if __name__=='__main__':
    result=get('https://data.open-contracting.org/en/publication/122','ocp_index.html'); print(result,flush=True)
    html=(ROOT/'raw/ocp_index.html').read_text(encoding='utf-8')
    links=re.findall(r'href=[\"\x27]([^\"\x27]+)',html)
    jobs=[]
    for y in range(2019,2027):
        matches=[u for u in links if f'{y}.jsonl.gz' in u]
        if matches:
            u=urllib.parse.urljoin('https://data.open-contracting.org',matches[0]);jobs.append((u,f'OCP_{y}.jsonl.gz'))
    logs=[]
    with concurrent.futures.ThreadPoolExecutor(max_workers=4) as ex:
        for r in ex.map(lambda v: {'url':v[0],'path':str(ROOT/'raw'/v[1]),'cached':True} if (ROOT/'raw'/v[1]).exists() else get(*v),jobs): logs.append(r); print(r,flush=True)
    (ROOT/'bulk_access_log.json').write_text(json.dumps(logs,ensure_ascii=False,indent=2),encoding='utf-8')
    candidates=[]; stats={}
    for p in sorted((ROOT/'raw').glob('OCP_*.jsonl.gz')):
        n=0;c=0
        with gzip.open(p,'rt',encoding='utf-8') as f:
            for line in f:
                n+=1
                r=json.loads(line); t=norm(json.dumps(r,ensure_ascii=False))
                if any(w in t for w in ['reactiv','glucomet','glucosa','lanceta','inmuno','hematolog','coagul','quimica clinica','secuenci','molecular','genexpert','pcr','microbiolog','histopat','inmunohisto','sangre oculta','gasometr','prueba rapida','pruebas rapidas','elisa','cobas','sysmex','alinity','architect','accu-chek','diabetes']):
                    candidates.append({'file':p.name,'line':n,'record':r});c+=1
        stats[p.name]={'processes_scanned':n,'broad_candidates':c}
        print(p.name,n,c,flush=True)
    (ROOT/'raw/broad_candidates.json').write_text(json.dumps(candidates,ensure_ascii=False),encoding='utf-8')
    (ROOT/'bulk_stats.json').write_text(json.dumps(stats,indent=2),encoding='utf-8')
    print(json.dumps(candidates[:1],ensure_ascii=False,indent=2)[:18000])

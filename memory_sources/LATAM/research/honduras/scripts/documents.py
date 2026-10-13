from discover import *
import urllib.parse
a=json.loads((ROOT/'raw/item_candidates.json').read_text(encoding='utf-8'));jobs=[]
for year in range(2019,2027):
    found=[]
    for c in a:
        if str(year) not in c['file']:continue
        docs=[d for co in c['record'].get('contracts',[]) for d in co.get('documents',[])]
        docs += [d for d in c['record'].get('tender',{}).get('documents',[]) if 'Adjudicacion' in d.get('url','')]
        for d in docs:
            u=d.get('url')
            if u and u not in found:found.append(u)
        if len(found)>=3:break
    jobs += [(u,urllib.parse.unquote(urllib.parse.urlparse(u).path.split('/')[-1])) for u in found[:3]]
with concurrent.futures.ThreadPoolExecutor(max_workers=3) as ex:
    results=list(ex.map(lambda v:get(*v),jobs))
(ROOT/'document_access_log.json').write_text(json.dumps(results,ensure_ascii=False,indent=2),encoding='utf-8')
print(json.dumps(results,ensure_ascii=False,indent=2))

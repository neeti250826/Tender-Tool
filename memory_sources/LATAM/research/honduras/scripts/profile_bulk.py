import pathlib,json,gzip,re,collections,unicodedata
ROOT=pathlib.Path(__file__).resolve().parents[1]
def norm(x):return ''.join(c for c in unicodedata.normalize('NFKD',str(x)).lower() if not unicodedata.combining(c))
def records():
    for p in sorted((ROOT/'raw').glob('OCP_*.jsonl.gz')):
        with gzip.open(p,'rt',encoding='utf-8') as f:
            for n,l in enumerate(f,1):
                low=l.lower()
                if not any(w in low for w in ['reactiv','glucom','lancet','inmun','hemat','coagul','cl\u00ednica','clinica','secuenci','molecular','genexpert','pcr','microbiolog','histopat','gasometr','prueba','pruebas','elisa','cobas','sysmex','alinity','architect','accu','tiras','hba1c','hemoglob','comodato']):continue
                yield p.name,n,json.loads(l)
if __name__=='__main__':
    candidates=[];descs=collections.Counter();stats=collections.Counter()
    pattern=re.compile(r'reactiv|glucomet|lanceta|inmuno|hematolog|coagul|quimica clinica|secuenci|molecular|genexpert|\bpcr\b|microbiolog|histopat|gasometr|prueba[s]? rapida|elisa|cobas|sysmex|alinity|architect|accu.chek|tiras.*gluc|gluc.*tiras|[hc]ba1c|hemoglobina gli|prueba.*vih|prueba.*dengue|prueba.*covid|prueba.*hepatitis')
    for file,n,r in records():
        t=r.get('tender',{}); status=t.get('statusDetails','');items=[(typ,a,i) for typ in ['contracts','awards'] for a in r.get(typ,[]) for i in a.get('items',[])];
        for typ,a,i in items:
            d=i.get('description','');txt=norm(d)
            if not pattern.search(txt):continue
            buyer=r.get('buyer',{}).get('name','');parties=[p.get('name','') for p in r.get('parties',[]) if 'buyer' in p.get('roles',[])]
            if not any(w in norm(' '.join([buyer]+parties)) for w in ['salud','hospital','seguro social','penitenci','medicina','forense','universidad','sanitari','cruz roja','univ']):continue
            candidates.append({'file':file,'line':n,'type':typ,'ocid':r.get('ocid'),'tender':t.get('title'),'buyer':buyer,'status':status,'item':i,'award':{k:v for k,v in a.items() if k!='items'},'record':r});descs[d]+=1;stats[(file,typ,status)]+=1
    (ROOT/'raw/item_candidates.json').write_text(json.dumps(candidates,ensure_ascii=False),encoding='utf-8')
    (ROOT/'raw/descriptions.txt').write_text('\n\n'.join(f'{n}\t{d}' for d,n in descs.most_common()),encoding='utf-8')
    print('candidates',len(candidates),'unique descriptions',len(descs),flush=True);print(stats);print('\n'.join(f'{n}\t{d[:200]}' for d,n in descs.most_common(100)))

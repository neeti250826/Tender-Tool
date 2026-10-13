import urllib.request,urllib.parse,urllib.error,pathlib,json,hashlib,time,concurrent.futures,math,datetime,collections
P=pathlib.Path(__file__).resolve().parent
BASE='https://www.comprasal.gob.sv'
ENDPOINT='/api/v1/publico/obtener/procesos/publicos'
PER_PAGE=2000
def fetch_page(page):
 params={'pagination':'true','page':page,'per_page':PER_PAGE}
 url=BASE+ENDPOINT+'?'+urllib.parse.urlencode(params)
 dest=P/'raw'/('registry_page_%04d.json'%page)
 meta=P/'raw'/('registry_page_%04d.meta.json'%page)
 if dest.exists() and meta.exists():return json.loads(meta.read_text(encoding='utf-8')),json.loads(dest.read_text(encoding='utf-8'))
 for attempt in range(4):
  try:
   r=urllib.request.urlopen(urllib.request.Request(url,headers={'User-Agent':'Mozilla/5.0','Accept':'application/json'}),timeout=120);data=r.read();result=json.loads(data)
   if not isinstance(result.get('data'),list):raise ValueError('Unexpected listing schema')
   info={'url':url,'status':r.status,'retrieved_utc':datetime.datetime.now(datetime.timezone.utc).isoformat(),'page':int(r.headers.get('page','0')),'per_page':int(r.headers.get('per_page','0')),'total_rows':int(r.headers.get('total_rows','0')),'rows':len(result['data']),'sha256':hashlib.sha256(data).hexdigest(),'raw_file':str(dest.relative_to(P))}
   if info['page']!=page or info['per_page']!=PER_PAGE or not info['total_rows']:raise ValueError('Pagination headers unexpected '+str(info))
   dest.write_bytes(data);meta.write_text(json.dumps(info,indent=2),encoding='utf-8');time.sleep(.3);return info,result
  except Exception as exc:
   if attempt==3:raise RuntimeError('Failed page '+str(page)+': '+str(exc))
   time.sleep(2*(attempt+1))
first,raw=fetch_page(1); count=math.ceil(first['total_rows']/PER_PAGE);print('Total',first['total_rows'],'pages',count,flush=True)
with concurrent.futures.ThreadPoolExecutor(max_workers=3) as pool:
 futures={pool.submit(fetch_page,p):p for p in range(2,count+1)}
 for future in concurrent.futures.as_completed(futures):
  info,_=future.result();print('Page',info['page'],'rows',info['rows'],flush=True)
records=[];metas=[]
for page in range(1,count+1):
 info,result=fetch_page(page);metas.append(info);records.extend(result['data'])
ids=[str(r['id']) for r in records];dates=[str(r.get('proceso_compra',{}).get('fecha_adjudicacion') or '') for r in records]
summary={'scope':'Entire current public award registry, all institutions/methods, no title filter','total_header_first':first['total_rows'],'expected_pages':count,'pages_completed':len(metas),'fetched_rows':len(records),'unique_record_ids':len(set(ids)),'duplicate_ids':len(ids)-len(set(ids)),'totals_observed':sorted(set(m['total_rows'] for m in metas)),'minimum_nonblank_award_date':min(d for d in dates if d),'maximum_nonblank_award_date':max(d for d in dates if d),'award_date_year_counts':dict(sorted(collections.Counter(d[:4] or 'blank' for d in dates).items())),'server_date_filter':'None exposed in observed public listing component; date window applied locally.','requested_award_date_window':['2019-01-01','2026-10-06'],'page_size':PER_PAGE,'requests':metas}
(P/'registry_download_summary.json').write_text(json.dumps(summary,ensure_ascii=False,indent=2),encoding='utf-8')
(P/'registry_all.json').write_text(json.dumps(records,ensure_ascii=False),encoding='utf-8')
print(json.dumps({k:v for k,v in summary.items() if k!='requests'},ensure_ascii=False,indent=2),flush=True)

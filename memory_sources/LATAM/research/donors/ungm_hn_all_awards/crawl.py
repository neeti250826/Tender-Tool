import pathlib,json,urllib.request,urllib.error,time,hashlib,re,datetime
from html.parser import HTMLParser
p=pathlib.Path(__file__).parent;p.mkdir(exist_ok=True,parents=True);root=p.parents[2];raw=p/'raw';raw.mkdir(exist_ok=True)
f=root/'research/ungm_full_recovery/honduras_all_listings.json';allrows=json.loads(f.read_text(encoding='utf-8'));rows=[r for r in allrows if r['listed_beneficiary']=='Honduras'];assert len(rows)==2854 and len({r['award_id'] for r in rows})==2854
class Txt(HTMLParser):
 def __init__(self):super().__init__();self.a=[]
 def handle_data(self,d):self.a.append(d)
def txt(x):h=Txt();h.feed(x);return ' '.join(' '.join(h.a).split())
def parse(s):
 if '<div class="awardDetail">' not in s:raise ValueError('Expected awardDetail source layout unavailable')
 s=s[s.index('<div class="awardDetail">'):]
 out={}
 for tag in ['Title','AgencyId','Reference','AwardDate','ContractValue']:
  m=re.search(r'<label for="'+tag+r'">(.*?)</label>\s*<span[^>]*>(.*?)</span>',s,re.S)
  if not m:raise ValueError('Field unavailable: '+tag)
  out[tag]=txt(m[2])
 out['country']=txt(re.search(r'<legend>Countries or territories</legend>\s*<div[^>]*>(.*?)</div>',s,re.S)[1])
 vendor=s[s.index('id="contractAwardVendorsContainer"'):s.index('id="Contacts-tab"')];out['suppliers']=list(map(txt,re.findall(r'<label>(.*?)</label>',vendor,re.S)));out['supplier']='; '.join(out['suppliers'])
 out['description']=txt(re.search(r'<div class="raw clear">(.*?)</div>',s,re.S)[1])
 out['USD_label_observed']='Contract value (USD)' in s
 return out
log=[];details=[]
for i,r in enumerate(rows):
 dest=raw/(r['award_id']+'.html');e={'index':i,'award_id':r['award_id'],'url':r['source_url'],'listing':r,'started_UTC':datetime.datetime.now(datetime.timezone.utc).isoformat()}
 try:
  if dest.exists() and dest.stat().st_size>0:b=dest.read_bytes();e['cache_reused']=True
  else:
   req=urllib.request.Request(r['source_url'],headers={'User-Agent':'Mozilla/5.0','Accept':'text/html'})
   for attempt in range(3):
    try:
     with urllib.request.urlopen(req,timeout=40) as res:b=res.read();e['http_status']=res.status;e['final_url']=res.url
     dest.write_bytes(b);break
    except urllib.error.HTTPError as er:
     if er.code!=429:raise
     retry=er.headers.get('Retry-After','60');delay=int(retry) if retry.isdigit() else 60;delay=min(300,max(60,delay));e.setdefault('rate_limit_waits',[]).append(delay);time.sleep(delay)
   else:raise ValueError('Bounded429 retries exhausted')
  e.update({'raw_path':str(dest.resolve()),'raw_sha256':hashlib.sha256(b).hexdigest(),'bytes':len(b)});fields=parse(b.decode('utf-8'));e['parsed']=True
  details.append({'listing':r,'fields':fields,'raw_path':str(dest.resolve()),'raw_sha256':e['raw_sha256']});(raw/(r['award_id']+'.txt')).write_text(json.dumps(fields,ensure_ascii=False,indent=2),encoding='utf-8')
 except Exception as er:e['error']=str(er);print('ERROR',r['award_id'],str(er),flush=True)
 log.append(e);(p/'retrieval_log.json').write_text(json.dumps(log,ensure_ascii=False,indent=2),encoding='utf-8');(p/'parsed_details.json').write_text(json.dumps(details,ensure_ascii=False,indent=2),encoding='utf-8')
 print(i+1,'/',len(rows),r['award_id'],'OK' if e.get('parsed') else 'failed',flush=True);time.sleep(5)
(p/'coverage.json').write_text(json.dumps({'listing_sha256':hashlib.sha256(f.read_bytes()).hexdigest(),'single_country_listings':2854,'retrieved_and_parsed':len(details),'errors':len(log)-len(details),'all_titles_requested':True,'global_multiple_destinations_not_allocated':3080,'period':'2019-01-01 through2026-10-06','mapping_status':'Pending full description classification and independent review; no admission from title alone'},indent=2),encoding='utf-8')

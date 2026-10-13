"""Cached official public UNGM single-lot award adapter; no network/authentication."""
import json,hashlib,re,datetime,copy
from pathlib import Path
from html.parser import HTMLParser
class _T(HTMLParser):
 def __init__(self):super().__init__();self.parts=[]
 def handle_data(self,d):self.parts.append(d)
def text(s):
 t=_T();t.feed(s);return ' '.join(' '.join(t.parts).split())
class Adapter:
 def __init__(self,url):
  rows=json.loads((Path(__file__).parent/'rows.json').read_text(encoding='utf-8'))
  matches=[r for r in rows if r['Source link']==url]
  if len(matches)!=1:raise ValueError('Only frozen observed awardURL supported')
  self.row=matches[0]
 def extract(self,source):
  path=Path(source['raw_path'] if isinstance(source,dict) else source);raw=path.read_bytes()
  if hashlib.sha256(raw).hexdigest()!=self.row['_evidence']['raw_sha256']:raise ValueError('Source changed; new review required')
  html=raw.decode('utf-8');html=html[html.index('<div class="awardDetail">'):]
  def field(tag):
   m=re.search('<label for="'+tag+r'">(.*?)</label>\s*<span[^>]*>(.*?)</span>',html,re.S)
   if not m:raise ValueError('Public source layout changed')
   return text(m[2])
  country=text(re.search(r'<legend>Countries or territories</legend>\s*<div[^>]*>(.*?)</div>',html,re.S)[1])
  desc=text(re.search(r'<div class="raw clear">(.*?)</div>',html,re.S)[1])
  vendors=html[html.index('id="contractAwardVendorsContainer"'):html.index('id="Contacts-tab"')]
  suppliers=list(map(text,re.findall('<label>(.*?)</label>',vendors,re.S)))
  if country!='Honduras' or field('Reference')!='ITB/2022/40544' or suppliers!=[self.row['Awarded supplier (distributor)']] or 'Contract value (USD)' not in html:raise ValueError('Country/procedure/supplier/currency changed')
  r=copy.deepcopy(self.row)
  r.update({'Country':country,'Tender / procedure no.':field('Reference'),'Tender title / description':field('Title'),'Product / test':desc,'Awarded supplier (distributor)':suppliers[0],'Total awarded':float(field('ContractValue')),'Currency':'USD','Award date':datetime.datetime.strptime(field('AwardDate'),'%d-%b-%Y').date().isoformat()})
  if desc!='Lot 95 - BOLSA PEDIATRICA COLECTORA DE ORINA':raise ValueError('Lot scope changed')
  return [r]
 def get_repair_targets(self):return []
def create_adapter(url):return Adapter(url)

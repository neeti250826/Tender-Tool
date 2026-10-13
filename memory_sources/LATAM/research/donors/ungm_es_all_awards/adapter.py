"""Cached source adapter for independently reviewable new UNGM award109150.
All118country details were classified separately; this adapter emits only the
new mapped candidate, not existing aliases, unknown scopes or excluded goods.
"""
from pathlib import Path
import re,json,hashlib,datetime
from html.parser import HTMLParser
class _T(HTMLParser):
 def __init__(self):super().__init__();self.a=[]
 def handle_data(self,d):self.a.append(d)
def text(s):p=_T();p.feed(s);return ' '.join(' '.join(p.a).split())
class Adapter:
 def __init__(self,url):
  if url!='https://www.ungm.org/Public/ContractAward/109150':raise ValueError('Only source-observed new eligible award109150 configured')
  self.url=url
 def extract(self,source):
  p=Path(source['raw_path'] if isinstance(source,dict) else source);b=p.read_bytes();s=b.decode('utf-8');s=s[s.index('<div class="awardDetail">'):]
  def field(tag):
   m=re.search('<label for="'+tag+r'">(.*?)</label>\s*<span[^>]*>(.*?)</span>',s,re.S)
   if not m:raise ValueError('Source field layout changed: '+tag)
   return text(m[2])
  title,org,ref,date,value=[field(t) for t in ['Title','AgencyId','Reference','AwardDate','ContractValue']]
  country=text(re.search(r'<legend>Countries or territories</legend>\s*<div[^>]*>(.*?)</div>',s,re.S)[1]);desc=text(re.search('<div class="raw clear">(.*?)</div>',s,re.S)[1]);v=s[s.index('id="contractAwardVendorsContainer"'):s.index('id="Contacts-tab"')];sup=list(map(text,re.findall('<label>(.*?)</label>',v,re.S)))
  if country!='El Salvador' or 'CENTRÍFUGA MICROHEMATOCRITO' not in desc or 'Contract value (USD)' not in s or len(sup)!=1:raise ValueError('Source country/product/currency/supplier scope changed')
  config=json.loads((Path(__file__).parent/'rows.json').read_text(encoding='utf-8'))[0]
  if hashlib.sha256(b).hexdigest()!=config['_evidence']['raw_sha256']:raise ValueError('Frozen source changed; requires new review')
  x={k:v for k,v in config.items() if not k.startswith('_')};x.update({'Country':country,'Buying institution / hospital':org+' / MINSAL, Unidad Comunitaria de Salud Familiar Especializada de Soyapango','Tender / procedure no.':ref,'Tender title / description':title,'Product / test':desc,'Awarded supplier (distributor)':sup[0],'Total awarded':float(value),'Currency':'USD','Award date':datetime.datetime.strptime(date,'%d-%b-%Y').date().isoformat()})
  for k in ['Quantity','Unit','Unit price','Brand / analyser','Publication date','Funding (national / World Bank / IDB / Global Fund / PAHO)','Contract duration & extensions']:x[k]=''
  x['_row_id']='UNGM-AWARD-109150';x['_evidence']={'raw_path':str(p.resolve()),'raw_sha256':hashlib.sha256(b).hexdigest(),'source_url':self.url,'mapping':'Literal hematocrit-purpose centrifuge; HMCBC. Instrument observation, no test/reagent/instrument quantity inferred.','lot_reference':2};return [x]
 def get_repair_targets(self):return []
def create_adapter(url):return Adapter(url)

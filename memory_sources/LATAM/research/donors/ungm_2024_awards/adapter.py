"""Public UNGM award detail adapter for two observed URLs. No authenticated endpoints.
Extract(source) accepts a cached HTML path or {'raw_path': path}; it does not call the
network. Detail URLs must be supplied from observed official listing records.
"""
from pathlib import Path
from html.parser import HTMLParser
import re,json,hashlib,datetime
class _Text(HTMLParser):
    def __init__(self): super().__init__(); self.parts=[]
    def handle_data(self, data): self.parts.append(data)
def _text(s):
    p=_Text();p.feed(s);return ' '.join(' '.join(p.parts).split())
class Adapter:
    def __init__(self,url):
        if url not in ['https://www.ungm.org/Public/ContractAward/144350','https://www.ungm.org/Public/ContractAward/142775']:
            raise ValueError('URL must be one of the two observed public listing award details')
        self.url=url
    def extract(self,source):
        path=Path(source['raw_path'] if isinstance(source,dict) else source)
        b=path.read_bytes();s=b.decode('utf-8');s=s[s.index('<div class="awardDetail">'):]
        def field(tag):
            p=re.search(r'<label for="'+tag+r'">(.*?)</label>\s*<span[^>]*>(.*?)</span>',s,re.S)
            if not p:raise ValueError('UNGM field layout changed: '+tag)
            return _text(p[2])
        title,org,reference,date,value=[field(t) for t in ['Title','AgencyId','Reference','AwardDate','ContractValue']]
        if 'Contract value (USD)' not in s:raise ValueError('Currency label unavailable')
        country=_text(re.search(r'<legend>Countries or territories</legend>\s*<div[^>]*>(.*?)</div>',s,re.S)[1])
        supplier=_text(re.search(r'<div id="contractAwardVendorsContainer">.*?<label>(.*?)</label>',s,re.S)[1])
        product=_text(re.search(r'<div class="raw clear">(.*?)</div>',s,re.S)[1])
        if country!='El Salvador':raise ValueError('Observed country scope changed')
        root=Path(__file__).resolve().parents[2]
        mapping=json.loads((root/'inputs/keyword_map.json').read_text(encoding='utf-8'))
        # The two public award scopes have no item-level schedule or priced target split.
        code='FLOWC' if self.url.endswith('/144350') else 'MSTDZ'
        name=next(x[2] for x in mapping['Keyword map'] if x[0]==code)
        row={h:'' for h in mapping['Capture template'][0]}
        row.update({'Country':country,'Source portal':'UNGM','Buying institution / hospital':org,'Tender / procedure no.':reference,'Tender title / description':title,'Indicator code':code,'Segment name':name,'Product / test':product,'Awarded supplier (distributor)':supplier,'Total awarded':float(value),'Currency':'USD','Award date':datetime.datetime.strptime(date,'%d-%b-%Y').date().isoformat(),'Status':'Awarded','Source link':self.url})
        row['_row_id']='UNGM-AWARD-'+self.url.rsplit('/',1)[-1]
        row['_evidence']={'raw_path':str(path.resolve()),'raw_sha256':hashlib.sha256(b).hexdigest(),'source_url':self.url,'unreported_fields_policy':'Blank quantity/unitprice/brand/tax/funding/duration/publication; awardlevel diagnostic scope only, no target allocation.'}
        return [row]
def create_adapter(url):return Adapter(url)


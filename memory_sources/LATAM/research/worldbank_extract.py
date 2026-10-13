import json,pathlib,urllib.request,urllib.parse,time,re,html,hashlib
root=pathlib.Path(__file__).parent/'international'
allrows=[];log=[]
for key,ctry in [('hn','Honduras'),('es','El Salvador')]:
 first=json.loads((root/('wb_'+key+'_search.json')).read_text(encoding='utf-8'))
 rows=first['procnotices']; total=int(first['total'])
 for off in range(1000,total,1000):
  url='https://search.worldbank.org/api/v2/procnotices?'+urllib.parse.urlencode({'format':'json','qterm':ctry,'rows':1000,'os':off})
  try:
   data=urllib.request.urlopen(url,timeout=60).read();(root/f'wb_{key}_{off}.json').write_bytes(data); part=json.loads(data);rows+=part['procnotices']
   log.append({'url':url,'bytes':len(data),'sha256':hashlib.sha256(data).hexdigest()})
  except Exception as e: log.append({'url':url,'error':str(e)})
  time.sleep(.5)
 countryrows=[r for r in rows if r.get('project_ctry_name')==ctry]
 for r in countryrows:
  desc=r.get('bid_description','');text=html.unescape(re.sub('<[^>]*>',' ',r.get('notice_text','')))
  if re.search(r'labora|reactiv|diagn[oó]st|hematol|gluc[oó]|PCR|secuenci|citogen|sangre|molecular|immun|inmun|analiz|GeneXpert|VIH|HIV|tuberc',desc,re.I):
   r['_clean_text']=re.sub(r'\s+',' ',text).strip();allrows.append(r)
 print(ctry,'retrieved',len(rows),'exact country',len(countryrows),'relevant',sum(r['project_ctry_name']==ctry for r in allrows))
(root/'wb_candidates.json').write_text(json.dumps(allrows,ensure_ascii=False,indent=2),encoding='utf-8')
(root/'wb_fetch_log.json').write_text(json.dumps(log,indent=2),encoding='utf-8')
for r in allrows: print(r['id'],r.get('noticedate'),r.get('notice_type'),r.get('project_ctry_name'),r.get('bid_description'),r.get('bid_reference_no'))

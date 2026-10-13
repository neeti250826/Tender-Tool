import urllib.request, urllib.error, pathlib, json, hashlib, time, re
root=pathlib.Path(__file__).parent/'international'
root.mkdir(parents=True,exist_ok=True)
urls={
 'ungm_awards':'https://www.ungm.org/Public/ContractAward/Index/ContractAwards',
 'ungm_hematology':'https://www.ungm.org/Public/ContractAward/150792',
 'wb_hn_document_api':'https://search.worldbank.org/api/v2/wds?format=json&docid=099091926083023302',
 'wb_contracts':'https://search.worldbank.org/api/v2/procnotices?format=json&country=Honduras&rows=100',
 'idb_procurement':'https://www.iadb.org/en/how-we-can-work-together/procurement',
 'paho_fund':'https://www.paho.org/en/paho-strategic-fund',
 'global_fund':'https://data.theglobalfund.org',
}
logs=[]
for key,url in urls.items():
 try:
  try: r=urllib.request.urlopen(urllib.request.Request(url,headers={'User-Agent':'Mozilla/5.0'}),timeout=35)
  except urllib.error.HTTPError as e: r=e
  content=r.read(); status=r.code
  (root/(key+'.raw')).write_bytes(content)
  txt=re.sub('<[^>]+>',' ',content.decode('utf-8',errors='replace')) if 'html' in r.headers.get('Content-Type','') else content.decode('utf-8',errors='replace')
  (root/(key+'.txt')).write_text(txt,encoding='utf-8')
  logs.append({'key':key,'url':url,'status':status,'bytes':len(content),'sha256':hashlib.sha256(content).hexdigest(),'retrieved':'2026-10-06'})
  print(key,status,len(content),re.sub(r'\s+',' ',txt)[:700])
 except Exception as e: logs.append({'key':key,'url':url,'error':str(e)}); print(key,str(e))
 time.sleep(.4)
(root/'fetch_log.json').write_text(json.dumps(logs,indent=2),encoding='utf-8')

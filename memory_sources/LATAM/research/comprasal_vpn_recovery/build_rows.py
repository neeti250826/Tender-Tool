import pathlib,json,hashlib,datetime,collections,re
from decimal import Decimal
P=pathlib.Path(__file__).resolve().parent
MAP=json.loads((P.parent/'inputs'/'keyword_map.json').read_text(encoding='utf-8'));HEAD=MAP['Capture template'][0];NAMES={r[0]:r[2] for r in MAP['Keyword map'] if r and r[0]}
groups=json.loads((P/'classified_processes.json').read_text(encoding='utf-8'))
def load(file):
 if file.exists():return json.loads(file.read_text(encoding='utf-8')).get('data',{})
 return {}
def safe_date(raw):
 if not raw:return ''
 try:return datetime.datetime.fromisoformat(raw.replace('Z','+00:00')).astimezone(datetime.timezone(datetime.timedelta(hours=-6))).date().isoformat()
 except:return raw[:10]
accepted=[];held=[];excluded=[];overlap=[]
for g in groups:
 cl=g['classification'];rec=g['records'][0];pid=g['process_id'];rid=rec['id'];pf=P/'raw'/'process_details'/('process_'+str(pid)+'.json');af=P/'raw'/'process_details'/('award_'+str(rid)+'.json');proc=load(pf);awd=load(af).get('adjudicacion') or {}
 indicator=cl['indicator'] or '';row={h:'' for h in HEAD};suppliers=sorted(set((r.get('proveedor',{}).get('nombre_comercial') or r.get('proveedor',{}).get('nombre') or '').strip() for r in g['records']));suppliers=[s for s in suppliers if s]
 process_total=proc.get('monto_adjudicado');sum_records=sum(Decimal(str(r.get('monto') or 0)) for r in g['records']);record_values=[{'award_record_id':r['id'],'supplier':(r.get('proveedor',{}).get('nombre_comercial') or r.get('proveedor',{}).get('nombre') or '').strip(),'amount_usd':r['monto']} for r in g['records']]
 title=g['title'];contract=[]
 for term,pat in [('Comodato',r'comodato'),('Pago según consumo mensual',r'consumo mensual'),('Según demanda',r'seg.n demanda'),('Pago por prueba',r'pago por prueba'),('Contrato abierto',r'contrato abierto'),('Solución integral',r'soluci.n integral')]:
  if re.search(pat,title,re.I):contract.append(term)
 reason=cl['reason'];decision=cl['decision'];value=process_total if process_total is not None else ''
 amount_ok=process_total is not None and abs(Decimal(str(process_total))-sum_records)<=Decimal('.02')
 if decision=='candidate' and not amount_ok:decision='held';reason+='; process award total missing or does not reconcile to full registry entries'
 if decision=='candidate' and not proc:decision='held';reason+='; official process detail not recovered'
 status=proc.get('SeguimientoProceso',{}).get('nombre') or rec['proceso_compra'].get('sp',{}).get('nombre') or ''
 if decision=='candidate' and status.lower() not in ['contratación','contratacion','seguimiento contractual','liquidado','adjudicado','contrato finalizado','cerrado']:
  decision='held';reason+='; current process status not unambiguous awarded/contracted: '+status
 if decision=='candidate' and (not suppliers or not g['award_date']):decision='held';reason+='; supplier or award date missing'
 if value!='':value=float(Decimal(str(value)).quantize(Decimal('.01')))
 row.update({'Country':'El Salvador','Source portal':'COMPRASAL / DINAC','Buying institution / hospital':g['buyer'],'Tender / procedure no.':g['procedure'],'Procedure type':proc.get('FormaContratacion',{}).get('nombre') or awd.get('forma_contratacion',''),'Tender title / description':title,'Indicator code':indicator,'Segment name':NAMES.get(indicator,''),'Product / test':title,'Awarded supplier (distributor)':'; '.join(suppliers),'Total awarded':value,'Currency':'USD','Contract type (comodato, por prueba, según demanda…)':'; '.join(contract),'Publication date':safe_date(proc.get('fecha_publicacion')),'Award date':g['award_date'],'Status':'Adjudicado' if decision=='candidate' else status,'Source link':'https://www.comprasal.gob.sv/procesos-publicos/'+str(rid),'Comments':reason+'. One procedure-level official award total, not a priced product-line amount; suppliers shown collectively with no supplier/item allocation. Quantity, unit price, brand and duration unreported at this aggregate scope. Original raw timestamp preserved; publication date normalized to El Salvador UTC-06:00.'})
 if len(g['records'])==1 and awd.get('plazo_contractual') is not None:row['Contract duration & extensions']=str(awd['plazo_contractual'])+' días'
 row['_row_id']='ES-COMPRASAL-PROC-'+str(pid)
 row['_evidence']={'source_process_id':pid,'representative_award_record_id':rid,'full_registry_record_ids':[r['id'] for r in g['records']],'record_values':record_values,'official_process_total_field':'data.monto_adjudicado','official_process_total':process_total,'full_registry_amount_sum':float(sum_records),'amount_reconciles':amount_ok,'granularity':'official_whole_procedure_award_total','product_allocation_available':False,'supplier_allocation_available':len(suppliers)==1,'classification_basis':reason,'decision':decision,'current_status_source':status,'publication_raw_utc':proc.get('fecha_publicacion'),'contract_signature_representative_raw':awd.get('fecha_firma'),'representative_contract_metadata_not_shared_across_other_records':True,'raw_files':[{'path':str(f),'sha256':hashlib.sha256(f.read_bytes()).hexdigest()} for f in [pf,af] if f.exists()],'api_process_url':'https://www.comprasal.gob.sv/api/v1/publico/obtener/detalle/procesos/publicos/'+str(pid),'api_representative_award_url':'https://www.comprasal.gob.sv/api/v1/publico/obtener/informe-adjudicacion/'+str(rid),'sizing_caveat':'Awarded commitment, not evidence of realized payments or test volumes. Parent buckets are not allocatable across most-specific indicators without product schedule.'}
 if decision=='candidate':accepted.append(row)
 elif decision=='excluded':excluded.append(row)
 elif decision=='existing_main':overlap.append(row)
 else:held.append(row)
for name,data in [('rows.json',accepted),('held_rows.json',held),('excluded_rows.json',excluded),('existing_main_overlap.json',overlap)]:
 (P/name).write_text(json.dumps(data,ensure_ascii=False,indent=2),encoding='utf-8')
summary={'candidate_rows':len(accepted),'held_rows':len(held),'excluded_rows':len(excluded),'existing_overlap_rows':len(overlap),'candidate_indicators':dict(collections.Counter(r['Indicator code'] for r in accepted)),'candidate_whole_procedure_commitments_usd':sum(r['Total awarded'] for r in accepted),'pricing_fields_note':'Whole-procedure totals only; no quantities or unit prices invented','sha256':hashlib.sha256((P/'rows.json').read_bytes()).hexdigest()}
(P/'candidate_manifest.json').write_text(json.dumps(summary,indent=2),encoding='utf-8');print(json.dumps(summary,indent=2))

import pathlib,json,re,collections,unicodedata,csv
P=pathlib.Path(__file__).resolve().parent
def norm(s):return ''.join(c for c in unicodedata.normalize('NFKD',str(s or '').lower()) if not unicodedata.combining(c))
clinical=re.compile(r'reactiv|laborator|diagnostic|quimica clinica|hematolog|microbiolog|bacteriolog|inmunodiag|uroanal|citolog|histolog|patologia|gluco(?:sa|metro)|lanceta|tira.{0,20}reactiv|comodato|pago por prueba|segun demanda|contrato abierto|solucion integral|biologia molecular|secuenci|genetica|citogen|coagul|antibiograma|gasometr|electrolito|prueba(?:s)? rapida|test rapido|hemocultivo|banco de sangre|tipificacion sanguin|hba1c|cobas|vitros|sysmex|bio-rad|biomerieux|genexpert|carga viral|tamizaje|microarreglo|microarray|inmunohisto|tincion|test de embarazo|prueba(?:s)? de embarazo|elisa|qpcr|pcr|citometr|nextseq|miseq|novaseq|minion|illumina|nanopore|freestyle|dexcom|monitor(?:eo|izacion) continuo.{0,20}glucosa|antigeno|sifilis|hepatitis|dengue|prueba.{0,20}vih')
nonclinical=re.compile(r'agua|suelos|(?:control de calidad|calidad).{0,30}(?:srs|superintendencia)|(?:alimento|lacteos|carnicos|veterinar|pesticida|ambiental|dental|odontolog|geotecn|asfalt|agricul|ganad|avic|botan|semilla|alergeno|radiofarmaco|fluordesoxiglucosa|fluodeoxiglucosa|medicina nuclear|aires acondicionados|gases? (?:medic|propano)|papel (?:toalla|higien)|bomba de infusion)|mantenimiento.{0,30}(?:vehicul|infraestructura|instalaciones|aires acondicionado)|reactivacion')
healthbuyer=re.compile(r'hospital|salud|seguro social|fosalud|comando de sanidad|medicina|cruz roja|cruz verde')
groups={};out=[]
for f in sorted((P/'raw').glob('registry_page_*.json')):
 if '.meta.' in f.name:continue
 for r in json.loads(f.read_text(encoding='utf-8'))['data']:
  p=r['proceso_compra']; title=norm(p.get('nombre_proceso')); buyer=norm(r.get('institucion',{}).get('nombre')); d=str(p.get('fecha_adjudicacion') or '')[:10]
  if not '2019-01-01'<=d<='2026-10-06':continue
  if not clinical.search(title):continue
  group=groups.setdefault(str(p['id']),{'process_id':p['id'],'title':p.get('nombre_proceso'),'buyer':r.get('institucion',{}).get('nombre'),'procedure':p.get('codigo_proceso'),'award_date':d,'records':[],'scope_class':None,'scope_reason':None})
  group['records'].append(r)
  if nonclinical.search(title):group['scope_class']='exclude_or_ambiguous';group['scope_reason']='Nonclinical or non-IVD phrase: '+nonclinical.search(title).group()
  elif healthbuyer.search(buyer) or re.search(r'laboratorio clinico|laboratorio de patologia|hematologia|microbiologia|bacteriologia|glucosa en sangre|banco de sangre|analizador de|carga viral|genexpert|prueba rapida',title):group['scope_class']='potential_human_ivd';group['scope_reason']='Clinical laboratory or diagnostic subject with human health buyer/context'
  else:group['scope_class']='held_human_use_unconfirmed';group['scope_reason']='Laboratory/contract term without confirmed human IVD product or buyer'
result=sorted(groups.values(),key=lambda g:(g['award_date'],g['process_id']))
(P/'process_candidates.json').write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf-8')
with (P/'process_title_review.tsv').open('w',encoding='utf-8',newline='') as f:
 w=csv.writer(f,delimiter='\t');w.writerow(['process_id','scope_class','award_date','procedure','buyer','title','records'])
 for g in result:w.writerow([g['process_id'],g['scope_class'],g['award_date'],g['procedure'],g['buyer'],g['title'],len(g['records'])])
print('Unique candidate processes',len(result),collections.Counter(g['scope_class'] for g in result))
print('Clinical records',sum(len(g['records']) for g in result if g['scope_class']=='potential_human_ivd'))

import pathlib,json,re,collections,unicodedata
P=pathlib.Path(__file__).resolve().parent
def norm(s):return ''.join(c for c in unicodedata.normalize('NFKD',str(s or '').lower()) if not unicodedata.combining(c))
def classify(g):
 t=norm(g['title']);b=norm(g['buyer'])
 outscope=re.search(r'agua|suelo|(?:filtro|cartucho).{0,20}bacteriologic|jaula|ratones|radiofarm|radiologic|rayos x|radiografia|electrodo de coagulacion|alta frecuencia|oftalmolog|audiometro|ferreter|mobiliario|aires acondicionado|recoleccion|disposicion final|residuo|tratamiento.{0,15}medicamento|alimento|lacteo|carnico|veterin|banco de leche|gas(?:es)? (?:medic|propano)|recarga de gases|papel toalla|bomba de infusion|virtualizacion',t)
 if outscope:return {'decision':'excluded','reason':'Non-IVD/user exclusion context: '+outscope.group(),'indicator':None}
 if re.search(r'anda\b|aguas residuales|superintendencia de regulacion sanitaria',b) and not re.search(r'diagnostic|clinico',t):return {'decision':'excluded','reason':'Water/industrial or pharmaceutical quality-control laboratory, no human diagnostic purpose evidenced','indicator':None}
 if 'potential_human_ivd'!=g['scope_class']:return {'decision':'held','reason':g['scope_reason'],'indicator':None}
 if g['process_id']==139195:return {'decision':'existing_main','reason':'Existing award record 501779 in main; whole-procedure amount would overlap. New official process total preserved for controlled replacement if requested.','indicator':'MICRO'}
 if re.search(r'citometr|cd4cd8|cd4.{0,4}cd8',t):return {'decision':'candidate','reason':'Flow cytometry CD-marker tests explicitly described; ignore broad molecular wording in title','indicator':'FLOWC'}
 if re.search(r'inmunohistoquim',t):return {'decision':'candidate','reason':'IHC reagent kit with equipment in comodato, method/model unspecified; no instrument allocation','indicator':'ADIHC'}
 if re.search(r'formalina',t) and re.search(r'patolog',t):return {'decision':'candidate','reason':'Tissue fixation formalin, pre-analytical tissue diagnostics','indicator':'TDPRE'}
 if re.search(r'tira(?:s)?(?: reactivas)?.{0,35}glucosa|tiras de glucosa',t):
  if re.search(r'insumos medicos varios|insumos y|material',t):return {'decision':'held','reason':'Glucose strips mixed with other medical supplies; amount cannot be allocated to BGM','indicator':'DBSPU'}
  return {'decision':'candidate','reason':'Blood-glucose strips purchased by public health institution; no retail/private allocation','indicator':'DBSPU'}
 if re.search(r'lanceta',t):return {'decision':'held','reason':'Lancets for diagnostic sampling, glucose-specific purpose unconfirmed','indicator':None}
 if re.search(r'panel',t):
  if re.search(r'biologia molecular',t):return {'decision':'held','reason':'Multiple molecular panel products/targets bundled, source lot allocation absent','indicator':'MPANL'}
  return {'decision':'held','reason':'Panel assay method and targets unreported; cannot assume molecular or POC','indicator':None}
 if re.search(r'biologia molecular|determinacion molecular',t):
  if re.search(r'sifilis',t):return {'decision':'held','reason':'Molecular HIV viral load plus combined HIV/syphilis detection tests; different modalities and no item allocation','indicator':None}
  return {'decision':'held','reason':'Per-consumption molecular reagent/instrument bundle without item quantity/unit price or target allocation','indicator':'MDXZZ'}
 if re.search(r'\bpcr\b',t):return {'decision':'held','reason':'PCR in Spanish ambiguous between CRP and molecular; bundled coagulation/culture does not resolve description','indicator':None}
 if re.search(r'pruebas rapidas',t):return {'decision':'held','reason':'Rapid pregnancy/hepatitis or multi-infection products bundled; no award item allocation or target breakdown','indicator':'POCZZ'}
 if re.search(r'gases (?:arteriales|sanguineos)|analizador de gases',t):
  if re.search(r'insumos reactivos y|reactivos.{0,30}laboratorio.{0,30}y',t):return {'decision':'held','reason':'Blood gas tests bundled with other laboratory products','indicator':None}
  return {'decision':'candidate','reason':'Explicit blood gas assays or analyzer cartridges; no general medical-gas purchase','indicator':'BGEZZ'}
 if re.search(r'hemocultivo',t) and not re.search(r'coagulacion|\bpcr\b',t):
  return {'decision':'candidate','reason':'Automated blood culture explicitly described' if 'automatiz' in t else 'Blood culture method unspecified','indicator':'ABDCL' if 'automatiz' in t else 'MICRO'}
 if re.search(r'microbiolog|bacteriolog',t):
  if re.search(r'reactivo|prueba',t):return {'decision':'candidate','reason':'Human clinical microbiology reagents, exact test and manual/automated method unspecified','indicator':'MICRO'}
  return {'decision':'held','reason':'Microbiology context without established diagnostic product type','indicator':None}
 if re.search(r'identificacion y susceptibilidad|susceptibilidad antimicrobiana',t) and 'automatiz' in t:return {'decision':'held','reason':'Automated ID/AST per-consumption contract: published ceiling not realized spending; no quantity/unit price','indicator':'AIDST'}
 if re.search(r'hematologia',t) and re.search(r'pruebas de hematologia',t) and not re.search(r'quimica|inmuno|uroanal|citogen',t):return {'decision':'candidate','reason':'Hematology tests supported, CBC-specific test unreported','indicator':'HEMEZ'}
 if re.search(r'patologia|anatomia patologica|citologia',t):
  if re.search(r'banco de sangre|laboratorio clinico.{0,30}(?:citologia|patologia)',t):return {'decision':'held','reason':'Tissue and central-laboratory or blood-bank products bundled; no item allocation','indicator':None}
  if re.search(r'reactivo|productos quimicos',t):return {'decision':'candidate','reason':'Tissue diagnostics reagent/chemical bundle; workflow/stain/brand not reported','indicator':'TDXZZ'}
  return {'decision':'held','reason':'Tissue diagnostics equipment/consumable scope unresolved; cannot select specific equipment class','indicator':'TDXZZ'}
 if re.search(r'tiroidea|\bpsa\b|inmunoensayo|inmunodiagnostico',t):return {'decision':'held','reason':'Multiple immunoassay or chemistry products bundled; no assay-level award allocation','indicator':'IAZZZ' if not re.search(r'bioquimica|quimica|hematologia|uroanalisis',t) else 'CDXZZ'}
 if re.search(r'citogenetica',t):return {'decision':'held','reason':'Cytogenetics title may cover microscopes, cell culture, stains or molecular equipment; specific product unreported','indicator':None}
 if re.search(r'consumo mensual|consumo|pago por prueba|segun demanda|contrato abierto',t):return {'decision':'held','reason':'Consumption/open contract scope; ceiling/amount cannot establish actual volume or unit price','indicator':'CDXZZ' if re.search(r'laboratorio clinico|quimica clinica|analisis de orina',t) else None}
 if re.search(r'reactiv|prueba.{0,20}laboratorio|pruebas clinicas|examenes de laboratorio',t):
  if re.search(r'radiologi|imageneolog|imagenologi|enfermeria|anestesiologi|equipo medico|medicament|uso medico|banco de sangre|banco de leche',t):return {'decision':'held','reason':'Diagnostic products mixed with other laboratory, blood-bank or medical products; exact allocation unavailable','indicator':None}
  if re.search(r'laboratorio clinico|hospital|pruebas clinicas',t) or re.search(r'hospital|salud|sanidad|seguro social',b):return {'decision':'candidate','reason':'Clinical laboratory reagent/testing bundle; source supports centralized diagnostics parent only; item allocation absent','indicator':'CDXZZ'}
 return {'decision':'held','reason':'General laboratory supplies, service or equipment; diagnostic product and most specific indicator not established','indicator':None}
groups=json.loads((P/'process_candidates.json').read_text(encoding='utf-8'))
results=[]
for g in groups:g['classification']=classify(g);results.append(g)
(P/'classified_processes.json').write_text(json.dumps(results,ensure_ascii=False,indent=2),encoding='utf-8')
print(collections.Counter(g['classification']['decision'] for g in results))
print(collections.Counter(g['classification']['indicator'] for g in results if g['classification']['decision']=='candidate'))

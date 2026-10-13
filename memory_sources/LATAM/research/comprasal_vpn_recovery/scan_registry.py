import pathlib,json,re,unicodedata,collections
P=pathlib.Path(__file__).resolve().parent
MAP=json.loads((P.parent/'inputs'/'keyword_map.json').read_text(encoding='utf-8'))
def norm(s):return ''.join(c for c in unicodedata.normalize('NFKD',str(s or '').lower()) if not unicodedata.combining(c))
terms=[]
for row in MAP['Keyword map']:
 if len(row)<7 or not row[0] or not re.fullmatch('[A-Z0-9]{4,8}',str(row[0])):continue
 for val in row[3:6]:
  if not val:continue
  for term in re.split(r';|\n',val):
   term=norm(term.strip())
   if len(term)>2 and not term.startswith('as ') and term not in ['isss','minsal','sesal','ihss','public','private','hospital nacional']:terms.append((row[0],term))
term_map=collections.defaultdict(set)
for code,term in terms:term_map[term].add(code)
pattern=re.compile(r'(?<![a-z0-9])(?:'+'|'.join(re.escape(t) for t in sorted(term_map,key=len,reverse=True))+r')(?![a-z0-9])')
extra=re.compile(r'reactiv|laborator|diagnostic|quimica clinica|hematolog|microbiolog|bacteriolog|inmunolog|patolog|glucosa|glucom|lanceta|tira.{0,15}reactiv|comodato|pago por prueba|segun demanda|contrato abierto|solucion integral|biologia molecular|secuenci|genetica|citogen|coagul|cultivo|antibiograma|gasometr|electrolito|prueba rapida|test rapido|hormona|hemostasia|hemocultivo|sangre|diabetes|hba1c|cobas|vitros|abbott|mindray|siemens|sysmex|roche|bio-rad')
excluded=re.compile(r'veterinar|alimento|agua (?:potable|residual)|(?:calidad|analisis|muestreo).{0,30}agua|gas(?:es)? medicinal|construccion|construccion|obra civil|mantenimiento.{0,30}(?:edificio|infraestructura)|agro|agricul|piscicul|ganader')
matches=[];outside=[];allrows=[]
for f in sorted((P/'raw').glob('registry_page_*.json')):
 if '.meta.' in f.name:continue
 allrows.extend(json.loads(f.read_text(encoding='utf-8'))['data'])
for r in allrows:
 p=r['proceso_compra'];title=norm(p.get('nombre_proceso'));found=pattern.findall(title)
 if not(found or extra.search(title)):continue
 item={'record':r,'raw_title':p.get('nombre_proceso'),'award_date':p.get('fecha_adjudicacion'),'matched_terms':sorted(set(found)),'indicator_candidates':sorted(set(c for t in found for c in term_map[t]))}
 if excluded.search(title):item['exclusion_match']=excluded.search(title).group();outside.append(item);continue
 date=str(p.get('fecha_adjudicacion') or '')[:10]
 if date and '2019-01-01'<=date<='2026-10-06':matches.append(item)
 else:item['date_scope']='outside_or_missing';outside.append(item)
(P/'title_candidates.json').write_text(json.dumps(matches,ensure_ascii=False,indent=2),encoding='utf-8')
(P/'title_excluded_or_out_of_window.json').write_text(json.dumps(outside,ensure_ascii=False,indent=2),encoding='utf-8')
titles=collections.Counter(m['raw_title'] for m in matches)
(P/'title_counts.json').write_text(json.dumps(titles.most_common(),ensure_ascii=False,indent=2),encoding='utf-8')
codes=sorted(set(r[0] for r in MAP['Keyword map'] if r and re.fullmatch('[A-Z0-9]{4,8}',str(r[0] or ''))))
(P/'keyword_scan_definition.json').write_text(json.dumps({'indicator_codes_loaded':len(codes),'codes':codes,'distinct_phrase_terms':len(term_map),'search_fields':['proceso_compra.nombre_proceso'],'general_lab_contract_terms_regex':extra.pattern,'exclusions_regex':excluded.pattern,'period':['2019-01-01','2026-10-06'],'note':'Phrase matches discover candidates; they do not establish a final indicator or purchase of every mapped subsegment. Retail terms are searched for discovery but no retail-row allocation is allowed.'},indent=2),encoding='utf-8')
print('Registry rows so far',len(allrows),'matching in-window',len(matches),'distinct titles',len(titles),'excluded/outside',len(outside))
for title,count in titles.most_common(40):print(count,title)

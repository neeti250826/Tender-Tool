from access import *
import html,unicodedata,datetime,decimal,collections
KM=json.loads((ROOT.parent/'inputs/keyword_map.json').read_text(encoding='utf-8'));CODES={x[0]:x for x in KM['Keyword map'][1:]};HEADERS=KM['Capture template'][0]
def tidy(s):return re.sub(r'\s+',' ',html.unescape(re.sub('<[^>]*>',' ',str(s or '')))).strip()
def decode(b):
    try:return b.decode('utf-8')
    except UnicodeDecodeError:return b.decode('latin1')
def norm(x):return ''.join(c for c in unicodedata.normalize('NFKD',str(x or '')).lower() if not unicodedata.combining(c)).replace('\ufffd','')
def has(t,p):return bool(re.search(p,t,re.I))
_old_source=(ROOT.parent/'honduras/scripts/extract.py').read_text(encoding='utf-8')
_func=_old_source[_old_source.index('def classify('):_old_source.index('\ndef date(')]
_func=_func.replace('def classify(','def baseclassify(').replace("r'tsh|", "r'\\btsh\\b|").replace("lisante|lizante", "\\blisante\\b|\\blizante\\b").replace("r'anti[- ]?(?:a|b|ab|d)\\b|grupo sanguine|tipaje|hemoclasific'", "r'\\banti[- ](?:ab|a|b|d)(?=[\\s,;.:()\\d]|$)|grupo sanguine|tipaje|hemoclasific'")
exec(_func,globals())
def dump(name,obj):(ROOT/name).write_text(json.dumps(obj,ensure_ascii=False,indent=2,default=str),encoding='utf-8')
def date(s):
    if isinstance(s,datetime.datetime):return s.date().isoformat()
    if not s:return ''
    x=norm(s);months={'ene':1,'feb':2,'mar':3,'abr':4,'may':5,'jun':6,'jul':7,'ago':8,'sep':9,'sept':9,'oct':10,'nov':11,'dic':12}
    m=re.search(r'(\d{1,2})-([a-z]+)-(\d{4})',x)
    if m and m[2] in months:return f'{m[3]}-{months[m[2]]:02d}-{int(m[1]):02d}'
    m=re.match(r'(\d{1,2})/(\d{1,2})/(\d{4})',x)
    if m:return f'{m[3]}-{int(m[2]):02d}-{int(m[1]):02d}'
    if re.match(r'^20\d\d-\d\d-\d\d',x):return x[:10]
    return ''
def fields(s):
    return {tidy(a):tidy(b) for a,b in re.findall(r'<p class="func-field-label">(.*?)</p>\s*<p class="func-field-value"[^>]*>(.*?)</p>',s,re.S)}
def classify(title):
    t=norm(title)
    if has(t,r'embolizan|gastroscop|cateter|balon.*dilat|toma de muestra|sellador.*bolsa|alergenos.*vacuna|microbiolog.*ambient|\badec\b|adecuacion|bano de parafina'):
        return '', 'Non-IVD therapeutic/collection/building/environmental scope or paraffin bath clinical use unconfirmed'
    if has(t,r'17.?oh.?progesterona|17.hidroxiprogesterona'):return 'IAADH','Adrenocortical hormone; not fertility progesterone'
    if has(t,r'carga viral.*(?:vih|inmunodeficiencia|hiv)') and not has(t,r'hepatitis|papiloma'):
        return 'MHIVV','HIV viral load quantitative test/service'
    if has(t,r'laboratorio clinico,? banco de sangre y patolog'):
        return 'CDXZZ','Cross-subsegment diagnostic equipment bundle; individual item allocation unavailable'
    if has(t,r'pruebas rapidas diagnosticas'):
        return 'POCZZ','Rapid diagnostic test bundle; individual targets unreported'
    if has(t,r'construcc|remodel|edificio|infraestruct|gases medicinal|gas medico|agua.*(?:potable|calidad)|veterinar|alimento|medicamento|mobiliario|impresion|toner|fotocopi|seguridad|anestesia|anestesiolog|dental|odontolog|endoscop|laparoscop|electrocardio|cardiolog|radiolog|radiacion|tomograf|rayos x|ultrason|ventilador|oxigeno|dialisis|audiometr|terapia|fisioter|cirugia|quirurgico.*(?:instrument|material)|calibracion.*balanza'):
        return '', 'Excluded non-IVD clinical/general goods or requested scope exclusion'
    if has(t,r'comodato|pago por prueba|segun demanda|solucion integral') and not has(t,r'labora|reactiv|diagnost|analiz|prueba'):
        return '', 'Contract-type word without diagnostic scope'
    if has(t,r'control de calidad.*medicamento|laboratorio.*medicamento|\bimpres|papel|formulario|talonario|construcc|climatiz|aire acondicionado'):
        return '', 'Non-human-IVD laboratory / printed forms / building scope'
    if has(t,r'\bcd4\b|citometro|citometria'):return 'FLOWC','Flow cytometry/CD4; not molecular despite loose biology wording'
    if has(t,r'(?:carga viral|molecular).*vih.*hepatitis'):return 'MDXZZ','Molecular multi-target bundle; target amounts not allocated'
    if has(t,r'analizador.*hemato|equipo.*hematolog'):return 'HMISR','Hematology instrument'
    if has(t,r'analizador.*(?:quimica clinica|bioquimic)'):return 'CCINS','Clinical chemistry instrument'
    if has(t,r'freestyle libre|dexcom|monitoreo continuo|glucosa intersticial|sensor.*glucosa'):return 'DICPU','Public institutional CGM'
    bg=has(t,r'gluco(?:metro|metria)|tira.*glucos|glucos.*tira|lanceta')
    if bg and has(t,r'gluco(?:metro|metria)') and has(t,r'lanceta|tira|cinta'):return 'DIBGM','BGM bundle; meter/strip/lancet component amounts unavailable'
    if has(t,r'lanceta'):return 'DBLPU','Public institutional lancets'
    if has(t,r'(?:tira|cinta).*(?:gluc|glucomet)|(?:gluc|glucomet).*(?:tira|cinta)'):return 'DBSPU','Public glucose monitoring strips'
    if has(t,r'glucometro|gluc.metr'):return 'DIBGM','Public glucose meter'
    if has(t,r'(?:tira|cinta).*(?:orina|urinari)'):return 'URQUA','Urine strip; not glucose strip'
    if has(t,r'gasometr|gases (?:arteriales|sanguine)|\bi.stat\b'):return 'BGEZZ','Blood gas/electrolyte diagnostic system'
    if has(t,r'reactiv.*(?:inmunolog|inmunoensay)|laboratorio.*inmunolog'):return 'IARRR','Immunoassay reagents; target not published in registry title'
    if has(t,r'reactiv.*(?:hematol|hemogram)|hemograma|biometria hematica'):return 'HMCBC','Hematology/cell-count analyzer reagent'
    if has(t,r'banco.*sangre|inmunohemat|tipaje|grupo sanguine|coombs|anti[- ](?:ab|a|b|d)(?=[\s,.]|$)'):return 'IMMHM','Immunohematology/blood grouping; component target allocation unavailable'
    if has(t,r'microbiolog|bacteriolog'):return 'MICRO','Microbiology; automation/manual method unspecified'
    if has(t,r'\bagar\b|medio.*cultivo|disco.*antibiot'):return 'MIDCL','Manual clinical culture/AST medium/reagent'
    if has(t,r'rt.?pcr|molecular|genexpert|\bxpert\b|carga viral|acidos nucleicos'):
        if has(t,r'covid|sars.?cov'):return 'MCOVD','Molecular SARS-CoV-2'
        if has(t,r'vih|hiv'):return 'MHIVZ','Molecular HIV; quantitative method unspecified'
        if has(t,r'tuberculosis|\bmtb\b'):return 'MTBZZ','Molecular tuberculosis'
        return 'MDXZZ','Molecular diagnostic scope; target unspecified'
    if has(t,r'\bpcr\b') and not has(t,r'proteina c reactiva|latex'):return '', 'Ambiguous Spanish PCR; attachment required'
    if has(t,r'proteina.?c.?reactiva|\bcrp\b'):return 'IACRP','CRP protein description explicit'
    if has(t,r'covid|sars.?cov') and has(t,r'rapid|antigen|anticuerpo'):return 'PCOVH','Public hospital rapid SARS-CoV-2 test'
    if has(t,r'vih|\bhiv\b') and has(t,r'prueba|reactiv|ensayo'):return ('PHIVS' if has(t,r'rapid') else 'IAHIV'),'HIV diagnostic test'
    if has(t,r'hepatitis b|hbsag|anti.?hbs'):return 'IAHBV','HBV diagnostic serology'
    if has(t,r'hepatitis c|\bhcv\b'):return 'IAHCV','HCV diagnostic serology'
    if has(t,r'dengue') and has(t,r'prueba|reactiv|ensayo'):return ('PDENG' if 'rapid' in t else 'IADEN'),'Dengue diagnostic test'
    if has(t,r'embarazo|\bhcg\b') and has(t,r'prueba|reactiv|ensayo|tira'):return 'PHCGT','Qualitative/rapid pregnancy test'
    if has(t,r'protrombina|tromboplastina|tiempo.*coagulacion|fibrinogeno'):return 'COTRA','Traditional coagulation assay'
    if has(t,r'coagulacion|coagulometro'):return 'LCOAG','Coagulation; test/instrument split unspecified'
    if has(t,r'histopat|anatomia patolog|inmunohisto|citolog|diagnostico.*tisular'):return 'TDXZZ','Tissue diagnostic scope; method/target unspecified'
    if has(t,r'parafina|microtomo|formol|formalina|xilol'):return 'TDPRE','Tissue preparation reagent/equipment'
    if has(t,r'secuenc|exoma|\bngs\b|miseq|novaseq|nextseq'):return 'SEQZZ','Sequencing scope; workflow split unspecified'
    if has(t,r'quimica clinica|quimica sanguinea|bioquimic') and has(t,r'reactiv|prueba|analiz'):return 'CCRRR','Clinical chemistry; target unspecified'
    if has(t,r'reactivo') and has(t,r'glucosa|creatinin|colesterol|triglicerid|urea|bilirrubin'):return 'CCROU','Routine chemistry assay'
    if has(t,r'lector.*elisa|lavador.*microplaca|analizador.*inmuno'):return 'IAINS','Immunoassay instrument'
    if has(t,r'reactivo|prueba|kit|ensayo|control|calibrador|elisa|albumina|hematoxilina'):
        c,b=baseclassify(title,'Public hospital')
        if c and c not in ['CDXZZ']:return c,b
    if has(t,r'reactivo|diagnostico.*laboratorio|laboratorio.*diagnostico'):return 'CDXZZ','Clinical diagnostic bundle; subsegment/item allocation unavailable'
    return '', 'Diagnostic IVD product not established by registry title; supporting document needed'

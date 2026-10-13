import pathlib,json,re,gzip,unicodedata,collections,hashlib,decimal
ROOT=pathlib.Path(__file__).resolve().parents[1]; INPUT=ROOT.parent/'inputs/keyword_map.json'
km=json.loads(INPUT.read_text(encoding='utf-8'));codes={v[0]:v for v in km['Keyword map'][1:]};headers=km['Capture template'][0]
def norm(x):return ''.join(c for c in unicodedata.normalize('NFKD',str(x or '')).lower() if not unicodedata.combining(c)).replace('\ufffd','')
def has(t,p):return bool(re.search(p,t,re.I))
terms=set()
skip={'isss','sesal','ihss','hospital nacional','unidad de salud','mantenimiento','insulina','paracetamol','vancomicina','cloro','calcio','sodio','potasio','heparina','oxigeno','hierro','alcohol','transmisor','lector de glucosa','cultivo','control de diabetes','medicina legal','trasplante','genetica','genomica','software','tira','cartucho','casete','equipo portatil','analizador portatil','pruebas especiales'}
for v in codes.values():
    if v[0] in ['DICEC','DICRP','DBSEC','DBSRP','DBLEC','DBLRP','DICPR','DBSPR','DBLPR']:continue
    for term in str(v[3] or '').split(';'):
        n=norm(term.strip())
        if len(n)>3 and n not in skip:terms.add(n)
search=re.compile('|'.join(sorted((re.escape(t) for t in terms),key=len,reverse=True)))
rawsearch=re.compile(r'reactiv|glucom|lancet|inmun|hemat|coagul|secuenc|molecular|genexpert|\bpcr\b|microbiol|histopat|gasometr|prueba|elisa|\bcobas\b|sysmex|alinity|architect|accu|tiras|hemoglobin|comodato|bioqu|creatinin|colesterol|urea|quimica|qu.mica|dengue|hepatitis|vih|hiv|tsh|\bt3\b|\bt4\b|sangre|orina|pylori|analizador|antigen|anticuerpo|agar|formol|xilol|parafina|cortisol|ferritina|troponin|gen.tic|patolog|toxoplasm|chagas|\bngs\b|qubit|miseq|novaseq|nextseq',re.I)
excluded=re.compile(r'construcc|remodel|mantenimiento de edificio|gases medicinal|agua potable|calidad de agua|veterinar|alimento.*laboratorio|laboratorio de suelo|laboratorio de comput|psicologic')
def classify(desc,buyer=''):
    t=norm(desc)
    if has(t,r'desaduan|aduanero|servicio.*mudanza|servicio.*traslado|pasaje.*aereo|consentimiento informado|registro de pruebas|impresion|\blibro:|isbn|agendas de pasta|sistema de audio|consola de luces|lapiz de cauterio|electrobistur|surfactante|inmunoglobulina.*(?:inyect|vial|ampolla)|vacuna|mascarilla.*(?:quirurgica|kn95)|factor.*coagulacion.*(?:infusion|intravenosa)|laboratorio.*(?:alimentos|agua)|inocuidad|deteccion.*3m'):
        return '', 'Non-diagnostic goods/logistics/printed forms/pharmaceutical/excluded testing scope'
    # Equipment specifications often list every supported assay after the actual purchased assay.
    t=re.split(r'requerimientos(?: minimos)? (?:equipos?|para)|su cotizacion debera|solicitar formato|entregar cotizaciones|presentar cotizaciones',t)[0]
    rapid=has(t,r'rapid|casset|inmunocrom|oro.?col|oraquick|determine');molecular=has(t,r'rt.?pcr|qpcr|polimerasa|molecular|acidos nucleicos|master.?mix|genexpert|\bxpert\b|carga viral|\barn\b|\badn\b')
    # A published award line sometimes contains an entire shopping list; no invented item allocation.
    bundle=len(re.findall(r'(?:\n|\*|\r)\s*\d+[,.]?\d*\s*(?:set|kit|caja|frasco|fco|unidad|c/u|prueba|galon|\t)',t))>1 or has(t,r'pda\s*2\s*:|partida\s*2\s*:|\b2\)\s*\d|\n\s*2\.\s*')
    if not bundle:
        # Several numbered tests can be printed in one single public award item.
        bundle=len(set(re.findall(r'\b(?:hepatitis [abc]|(?:hiv|vih)|tsh|t4 libre|creatinina|glucosa|hemograma|lancetas|tiras (?:para|de) orina)\b',t)))>2
    if bundle and has(t,r'reactivo|prueba.*(?:hepatitis|vih|embarazo|dengue)|hemato|bioquim|\belisa\b|tira.*orina|cinta.*gluco|lanceta|\bpcr\b'):return 'CDXZZ','Published line is a mixed laboratory bundle; component pricing/quantities not allocated.'
    if has(t,r'inmunoglobulina.*(?:inyect|vial|ampolla)|inmunizacion|vacuna|\bmedicamento\b|jarabe|tableta|capsula|inyectable') and not has(t,r'reactivo|prueba|kit|ensayo'):return '', 'Pharmaceutical/non-diagnostic exclusion'
    if has(t,r'monitoreo continuo|monitor continuo|glucosa intersticial|freestyle libre|dexcom|sensor.*glucosa'):return 'DICPU','CGM for public institutional buyer'
    if has(t,r'lanceta|lancetero'):return 'DBLPU','Lancets for public institutional buyer'
    if has(t,r'(tira|cinta).*(gluc|true test|accu)|gluc.*(tira|cinta)'):return 'DBSPU','Glucose strips, distinct from urine strips'
    if has(t,r'glucometr|glucometro|gluc.metr'):
        return ('HGCZZ' if has(t,r'conectiv|\blis\b|inform ii') else 'DIBGM'),'Glucose meter / meter-specific quality control'
    if has(t,r'(cinta|tira).*(orina|urinari)|quimica urinaria'):return 'URQUA','Urine strips, distinct from glucose strips'
    if has(t,r'\banalizador\b.*orina|\blector\b.*orina'):return 'URISR','Urine analyzer'
    if has(t,r'i.stat|gasometr|gases arteriales|gases sanguine|cartucho.*(?:cg4|cg8|eg7)'):return 'BGEZZ','Blood gas/electrolyte diagnostic system'
    if molecular and has(t,r'^tubo.*carga viral'):return '', 'Sample collection tube; not a molecular diagnostic test'
    if molecular:
        if has(t,r'covid|sars.?cov'):return 'MCOVD','Molecular SARS-CoV-2, lab/POC setting not established'
        if has(t,r'mtb|tuberculosis|rifampicina'):return 'MTBZZ','Molecular tuberculosis'
        if has(t,r'vih|hiv'):return ('MHIVV' if 'carga viral' in t else 'MHIVZ'),'Molecular HIV'
        if has(t,r'hepatitis b|vhb|hbv'):return ('MHBVV' if 'carga viral' in t else 'MHBVZ'),'Molecular HBV'
        if has(t,r'hepatitis c|vhc|hcv'):return ('MHCVV' if 'carga viral' in t else 'MHCVZ'),'Molecular HCV'
        if 'dengue' in t:return 'MDENG','Molecular dengue'
        if has(t,r'panel.*respirator|filmarray.*respirator'):return 'PRESP','Respiratory molecular panel'
        if has(t,r'termocic|extractor.*automat|equipo.*pcr|equipo.*genexpert'):return 'MDXIZ','Molecular instrument'
        if has(t,r'master.?mix|extraccion|primer|sonda|reactivo'):return 'MLDTZ','Molecular preparation/LDT reagents'
        return 'MDXZZ','Molecular description; deeper target unsupported'
    if has(t,r'\bpcr\b|proteina.?c.?reactiva|\bcrp\b'):
        if has(t,r'latex|human.*(?:100|ml)|proteina.?c.?reactiva'):return ('PCCRP' if rapid or 'semicuantit' in t else 'IACRP'),'CRP supported by latex/protein C reactive description'
        return '', 'Ambiguous PCR without CRP or molecular context'
    if has(t,r'hemograma|hematologi|hematologico|celldyn|diluyente.*(?:wl|hemat)|lisante|lizante'):
        if has(t,r'analizador|contador') and not has(t,r'reactivo|diluyente|lisante|control'):return 'HMISR','Hematology instrument'
        return 'HMCBC','CBC analyzer reagent/control'
    if has(t,r'protrombina|tromboplast|\btpt\b|\bttp\b|\baptt\b|\btp\b|fibrinogeno|plasma control|control.*tiempos'):return 'COTRA','Traditional coagulation assay/control'
    if has(t,r'dimero.?d|d.dimer'):return 'CODMR','D-dimer'
    if has(t,r'coagulomet|equipo.*coagulacion|analizador.*coagulacion'):return 'COISR','Coagulation instrument/accessory'
    if has(t,r'coagulacion'):return 'LCOAG','Coagulation scope; assay not identified'
    if has(t,r'\bcd4\b|citometria de flujo'):return 'FLOWC','Flow cytometry / CD4'
    if has(t,r'anti.?globulina|coombs'):return 'IMGLO','Antiglobulin testing'
    if has(t,r'anti[- ]?(?:a|b|ab|d)\b|grupo sanguine|tipaje|hemoclasific'):return 'BGNTZ','Blood grouping/typing'
    if has(t,r'prueba cruzada|compatibilidad transf'):return 'IMCCY','Crossmatch'
    if has(t,r'solucion.*liss|inmunohematolog|tarjeta.*gel'):return 'IMMHM','Immunohematology reagent'
    if has(t,r'hemocultivo|\bbactec\b|bac.t.alert|\bmgit\b'):return 'ABDCL','Automated blood-culture medium/system'
    if has(t,r'vitek|phoenix|micro.?scan|tarjeta.*suscept|tarjeta.*identif|maldi'):return 'AIDST','Automated microbiology ID/AST'
    if has(t,r'\bagar\b|medio.*cultivo|kovac|\bgram\b|ziehl|baciloscop|disco.*(?:antib|sensibilidad)|microbiolog|bacteriolog|lowenstein'):return 'MIDCL','Manual microbiology reagent/culture'
    if has(t,r'hba1c|hemoglobina glic|hemoglobina gluc|glicohemoglobina'):
        return ('CHPLC' if 'hplc' in t else 'COHBA' if has(t,r'turbid|enzimat|boronato') else 'POCHZ' if rapid else 'CCHBA'),'HbA1c; method only tagged when observed'
    if has(t,r'tsh|\bt3\b|\bt4\b|tiroidea|ft4|ft3'):return 'IATHY','Thyroid assay'
    if has(t,r'\bpsa\b|\bcea\b|ca.?125|ca.?15.?3|ca.?19.?9|alfafetoproteina'):return 'IAONC','Tumor-marker immunoassay'
    if has(t,r'ferritina|vitamina.?b12|folato'):return 'IAANE','Anemia immunoassay'
    if has(t,r'cortisol|acth|aldosterona|dhea'):return 'IAADH','Adrenal hormone'
    if has(t,r'troponin'):return ('PCART' if rapid else 'IATRO'),'Troponin'
    if 'procalciton' in t:return ('PCPCT' if rapid else 'IAPCT'),'Procalcitonin'
    if has(t,r'vitamina.?d|paratohormona|\bpth\b'):return 'IABON','Bone-health immunoassay'
    if has(t,r'reumatoide|\baso\b|\basto\b|antiestreptolis|\biga\b|complemento|cistatina'):return 'CCSPE','Specific protein assay'
    if has(t,r'embarazo|\bhcg\b'):
        return ('PHCGT' if rapid or has(t,r'latex|cualit|orina|prueba.*embarazo') else 'IAFER'),'Pregnancy test / reproductive hormone'
    if has(t,r'fsh|prolactina|progesterona|estradiol|testosterona'):return 'IAFER','Reproductive hormone assay'
    if has(t,r'covid|sars.?cov') and has(t,r'prueba|kit|reactivo|antigen|anticuerpo'):
        return ('PCOVH' if rapid and 'hospital' in norm(buyer) else 'PCOVD' if rapid else 'IACOV'),'SARS-CoV-2 immunoassay/rapid test'
    if has(t,r'vih|\bhiv\b') and has(t,r'prueba|kit|reactivo|elisa|determine|oraquick|ag/|ac/'):return ('PHIVS' if rapid else 'IAHIV'),'HIV serology/rapid test'
    if has(t,r'hepatitis.?b|hbsag|antihbc|anti.?hbc'):return ('PHBVZ' if rapid else 'IAHBV'),'HBV serology/rapid test'
    if has(t,r'hepatitis.?c|\bhcv\b|\bvhc\b'):return ('PHCVZ' if rapid else 'IAHCV'),'HCV serology/rapid test'
    if has(t,r'hepatitis.?[ae]'):return ('PHAVZ' if rapid else 'IAIOT'),'HAV/HEV serology/rapid test'
    if has(t,r'dengue'):return ('PDENG' if rapid else 'IADEN'),'Dengue serology/rapid test'
    if has(t,r'\brpr\b|vdrl|sifilis|treponema'):return ('PSYPH' if rapid else 'IASTI'),'Syphilis serology'
    if has(t,r'toxoplasm|rubeola|citomegalov|\btoxo\b'):return ('POTXX' if rapid else 'TORCH'),'TORCH assay'
    if has(t,r'rotavirus|adenovirus|helicobacter|pylori|sangre oculta|guayaco'):
        return ('PGASZ' if rapid or has(t,r'heces|guayaco|sangre oculta') else 'IAIOT'),'GI infectious/occult blood test'
    if has(t,r'chagas|chagat|leptospir|brucel|rosa de bengala|antigenos febriles|htlv'):return ('PVBDX' if rapid and not 'htlv' in t else 'IAIOT'),'Other infectious serology'
    if has(t,r'hiv|vih') and has(t,r'examen.*pcr'):return 'MHIVZ','PCR-HIV testing service'
    if has(t,r'glucosa|creatinina|colesterol|triglicerido|bilirrubina|transaminasa|urea|acido urico|fosfatasa|amilasa|lipasa|proteinas totales') and has(t,r'reactivo|kit|set|prueba|calibr|control|human|labtest|spinreact|wiener'):return 'CCROU','Routine clinical chemistry assay'
    if has(t,r'quimica clinica|quimica sanguinea|bioquim|qu.mica clinica'):
        return ('CCINS' if has(t,r'analizador|equipo') and not has(t,r'reactivo|kit|control') else 'CCRRR'),'Clinical chemistry scope'
    if has(t,r'hematoxilina|eosina|papanicolaou'):return 'HNERZ','H&E / Pap staining reagent'
    if has(t,r'formol|formalina|xilol|parafina|microtomo'):return 'TDPRE','Tissue preparation'
    if has(t,r'inmunohisto|anticuerpo.*(?:ki.67|her2|pdl1)'):return ('IHCMA' if 'concentrad' in t else 'IHCAU' if has(t,r'listo para usar|prediluid|\brtu\b') else 'ADIHC'),'IHC reagent; concentrated/manual or ready-to-use only when observed'
    if has(t,r'histopat|anatomia patolog|patologia|citologia'):return 'TDXZZ','Tissue diagnostics'
    if has(t,r'exoma|genoma completo|panel.*genes|secuenciacion.*sanger'):return 'SGENE','Diagnostic exome/genome/genetics sequencing service'
    if has(t,r'secuenciador|miseq|nextseq|novaseq'):return 'SEQIN','Sequencing instrument'
    if has(t,r'flow cell|libreri|qubit|covidseq|secuenciacion.*reactivo'):return 'SEQPR','NGS preparation/consumable'
    if has(t,r'secuenciacion|\bngs\b|genomica'):return 'SEQZZ','Sequencing scope'
    if has(t,r'lector.*elisa|lavador.*microplaca|analizador.*inmuno'):return 'IAINS','Immunoassay instrument'
    if has(t,r'elisa|quimiolumin|inmunoensayo|reactivo.*inmunolog'):return 'IARRR','Immunoassay reagent; target not identified'
    if has(t,r'reactivo.*laboratorio|insumo.*laboratorio|suministro de reactivos|solucion integral|equipo en comodato'):return 'CDXZZ','Laboratory scope; subsegment not observed'
    return '', 'No supported diagnostic indicator'

def date(x):return str(x or '')[:10]
def dumps(path,data):path.write_text(json.dumps(data,ensure_ascii=False,indent=2),encoding='utf-8')
def extract():
    rows=[];leads=[];rej=[];seen=set();stats={};rawdir=ROOT/'raw/records';rawdir.mkdir(exist_ok=True)
    for p in sorted((ROOT/'raw').glob('OCP_*.jsonl.gz')):
        stats[p.name]={'scanned':0,'keyword_candidate_records':0,'awarded_rows':0,'unverified_leads':0}
        with gzip.open(p,'rt',encoding='utf-8') as f:
            for n,line in enumerate(f,1):
                stats[p.name]['scanned']+=1
                low=line.lower()
                if not any(w in low for w in ['reactiv','glucom','lancet','inmun','hemat','coagul','secuenc','molecular','genexpert','pcr','microbiol','histopat','gasometr','prueba','elisa','cobas','sysmex','alinity','architect','accu','tiras','hemoglobin','comodato','bioqu','creatinin','colesterol','urea','quimica','qu\u00edmica','dengue','hepatitis','vih','hiv','tsh','sangre','orina','pylori','analizador','antigen','anticuerpo','agar','formol','xilol','parafina','cortisol','ferritina','troponin','patolog','toxoplasm','chagas','ngs','qubit','miseq','nextseq']):continue
                r=json.loads(line);t=r.get('tender',{});buyer=r.get('buyer',{}).get('name','');parties=r.get('parties',[]);fullbuyer=' / '.join(dict.fromkeys([x.get('name','') for x in parties if 'buyer' in x.get('roles',[])]+[buyer]))
                if not has(norm(fullbuyer),r'salud|hospital|seguro social|penitenci|medicina|forense|universidad|sanitari|cruz roja|univ'):continue
                allitems=[i for stage in ['awards','contracts'] for a in r.get(stage,[]) for i in a.get('items',[])]+t.get('items',[])
                if not any(search.search(norm(i.get('description','')+' '+i.get('classification',{}).get('description',''))) for i in allitems) and not search.search(norm(t.get('description',''))):continue
                stats[p.name]['keyword_candidate_records']+=1
                status=t.get('statusDetails','');contracts=r.get('contracts',[]);awards=r.get('awards',[]);ocid=r['ocid'];docs=[d for a in contracts+awards+[t] for d in a.get('documents',[])]
                recordpath=rawdir/(re.sub(r'[^A-Za-z0-9_.-]','_',ocid)+'.json');dumps(recordpath,r)
                awarddoc=[d for d in docs if has(norm(d.get('documentType','')+' '+d.get('title','')),r'awardnotice|contractsigned|resolucion.*adjudic|contrato.*orden')]
                for stage,groups in [('awards',awards),('contracts',contracts)]:
                    for a in groups:
                        linked=[c for c in contracts if c.get('awardID')==a.get('id')] if stage=='awards' else [a]
                        signed=[c for c in linked if c.get('dateSigned')]
                        isawarded=status=='Adjudicado' or (stage=='contracts' and bool(signed)) or a.get('status')=='active'
                        for idx,i in enumerate(a.get('items',[])):
                            desc=i.get('description','');ct=norm(i.get('classification',{}).get('description',''))
                            if excluded.search(norm(desc)):rej.append({'ocid':ocid,'item_id':i.get('id'),'reason':'Excluded scope','description':desc});continue
                            code,basis=classify(desc,fullbuyer)
                            if not code and has(ct,r'reactivo.*hematolog'):code,basis='HMCBC','Official UNSPSC description identifies hematology reagent; item description generic'
                            if not code:rej.append({'ocid':ocid,'item_id':i.get('id'),'reason':basis,'description':desc});continue
                            key=(ocid,str(i.get('id')),tuple(s.get('name','') for s in a.get('suppliers',[])),desc)
                            if key in seen:continue
                            seen.add(key)
                            pub=date(t.get('datePublished'));awarddate=date(a.get('date'));signeddate=date(signed[0].get('dateSigned')) if len(signed)==1 else ''
                            checkdate=awarddate or signeddate or pub
                            if not ('2019-01-01'<=checkdate<='2026-10-06'):rej.append({'ocid':ocid,'reason':'No date in requested scope','date':checkdate});continue
                            cur=i.get('unit',{}).get('value',{}).get('currency','') or a.get('value',{}).get('currency','')
                            currencies={c.get('value',{}).get('currency') for c in linked if c.get('value',{}).get('currency')}
                            if not cur and len(currencies)==1:cur=next(iter(currencies))
                            q=i.get('quantity','');price=i.get('unit',{}).get('value',{}).get('amount','');total='';comment=[f'ONCAE compiled OCDS retained via OCP mirror; OCID {ocid}; {stage} item {i.get("id")}.',basis]
                            if q!='' and price!='':total=float(decimal.Decimal(str(q))*decimal.Decimal(str(price)));comment.append('Total derived from published award-item quantity × unit price.')
                            if not awarddate and signeddate:comment.append(f'Contract signed {signeddate}; award date unavailable.')
                            if not cur:comment.append('Currency absent from item and linked contract; left blank.')
                            if not awarddoc:comment.append('No individual award/contract-document URL in compiled record; annual download plus retained OCID record supplies evidence.')
                            uom=i.get('unit',{}).get('name','')
                            if uom.lower() in ['kilogramo','metro','litro'] and has(norm(desc),r'\bkit\b|\bset\b|pruebas|tiras|cintas'):comment.append('Published OCDS unit appears inconsistent with product description; preserved, needs source verification.')
                            supplier='; '.join(s.get('name','') for s in a.get('suppliers',[]))
                            if not supplier and len(linked)==1:supplier='; '.join(s.get('name','') for s in linked[0].get('suppliers',[]))
                            funds='; '.join(dict.fromkeys(b.get('description','') for b in r.get('planning',{}).get('budget',{}).get('budgetBreakdown',[])))
                            ctypes='; '.join(w for w in ['comodato','pago por prueba','precio por prueba','segun demanda','contrato abierto','solucion integral','consignacion','arrendamiento','pruebas efectivamente realizadas'] if w in norm(desc))
                            brands='; '.join(dict.fromkeys(m.group() for m in re.finditer(r'\b(?:Roche|cobas|Abbott|Alinity|Architect|Sysmex|Mindray|Wiener|Human|Labtest|Spinreact|BioSystems|Bio-?Rad|bioM.rieux|Vitek|Beckman|Siemens|Accu-Chek|True Test|i-STAT|Celldyn|Counter 19|OraQuick|Determine|GeneXpert|Xpert|Illumina|MiSeq|Qubit|FilmArray|Biobase)\b',desc,re.I)))
                            link=awarddoc[0].get('url') if awarddoc else f'https://data.open-contracting.org/en/publication/122/download?name={p.name[4:]}'
                            row=dict.fromkeys(headers,'');row.update(dict(zip(headers,['Honduras','ONCAE / HonduCompras 1 (OCP mirror)',fullbuyer,t.get('title') or t.get('id'),t.get('procurementMethodDetails',''),t.get('description') or t.get('title'),'{}'.format(code),codes[code][2],desc,brands,supplier,q,uom,price,total,cur,ctypes,'',pub,awarddate,'Contratado' if signed else 'Adjudicado' if isawarded else status,funds,link,' '.join(comment)])))
                            row['_evidence']={'ocid':ocid,'source_download':f'https://data.open-contracting.org/en/publication/122/download?name={p.name[4:]}','raw_file':str(p),'jsonl_line':n,'record_file':str(recordpath),'record_sha256':hashlib.sha256(recordpath.read_bytes()).hexdigest(),'json_path':f'{stage}/{a.get("id")}/items/{i.get("id")}','status_observed':status,'contract_signed':signeddate,'indicator_basis':basis,'documents':docs,'date_filter_basis':'award date' if awarddate else 'contract signature' if signeddate else 'source tender publication; award date unavailable','currency_basis':'item/award currency' if i.get('unit',{}).get('value',{}).get('currency') or a.get('value',{}).get('currency') else 'linked contract currency' if cur else 'unavailable'}
                            if isawarded:rows.append(row);stats[p.name]['awarded_rows']+=1
                            else:row['Comments']+=' Award-item object conflicts with non-awarded portal status; excluded from award totals.';leads.append(row);stats[p.name]['unverified_leads']+=1
                # Generic awarded records without an explicit priced item remain leads for PDF extraction.
                if not any(a.get('items') for a in awards+contracts):
                    for i in t.get('items',[]):
                        desc=i.get('description','');code,basis=classify(desc,fullbuyer)
                        if not code:
                            cd=i.get('classification',{}).get('description','');code,basis=classify(cd,fullbuyer)
                        if not code:continue
                        pub=date(t.get('datePublished'));end=date(t.get('tenderPeriod',{}).get('endDate'))
                        if not ('2019-01-01'<=pub<='2026-10-06'):continue
                        row=dict.fromkeys(headers,'');row.update({'Country':'Honduras','Source portal':'ONCAE / HonduCompras 1 (OCP mirror)','Buying institution / hospital':fullbuyer,'Tender / procedure no.':t.get('title'),'Procedure type':t.get('procurementMethodDetails'),'Tender title / description':t.get('description') or t.get('title'),'Indicator code':code,'Segment name':codes[code][2],'Product / test':desc,'Publication date':pub,'Status':status or t.get('status'),'Source link':awarddoc[0].get('url') if awarddoc else docs[0].get('url') if docs else f'https://data.open-contracting.org/en/publication/122/download?name={p.name[4:]}','Comments':f'No awarded item details in OCDS. Portal status: {status}. Needs attachment verification. {basis}'})
                        row['_evidence']={'ocid':ocid,'record_file':str(recordpath),'jsonl_line':n,'documents':docs,'portal_status':status,'closing_date':end};leads.append(row);stats[p.name]['unverified_leads']+=1
        print(p.name,stats[p.name],flush=True)
    dumps(ROOT/'rows.json',rows);dumps(ROOT/'historical_status_unverified.json',leads);dumps(ROOT/'rejections.json',rej);dumps(ROOT/'extraction_stats.json',stats)
    print('TOTAL',len(rows),'LEADS',len(leads),'REJECT',len(rej));print(collections.Counter(x['Indicator code'] for x in rows))
if __name__=='__main__':extract()

"""Tag a tender line with the most specific indicator code from the ES/HN keyword map.

tag(item, title, buyer, unspsc) -> dict(code, codes, confidence, basis) or None (out of scope).

Rules run on accent-free lower-case text. A line can hit several codes; ancestors of
other hits are dropped, and if more than one leaf remains inside the same top-level
segment the nearest common parent is returned (the leaves are kept in `codes`).
"""
import json
import os
import re
import unicodedata

HERE = os.path.dirname(os.path.abspath(__file__))
KMAP = json.load(open(os.path.join(HERE, "keyword_map.json"), encoding="utf-8"))
SEG = {r["Indicator code"]: str(r["Segment code"]) for r in KMAP}
NAME = {r["Indicator code"]: r["Segment name"] for r in KMAP}
CODE_BY_SEG = {v: k for k, v in SEG.items()}


def norm(s):
    s = unicodedata.normalize("NFKD", str(s or "")).encode("ascii", "ignore").decode().lower()
    return re.sub(r"\s+", " ", s)


def R(p):
    return re.compile(p)


# ---------------------------------------------------------------- scope gates
EXCLUDE = R(r"construcci|remodelaci|alquiler de local|arrendamiento de inmueble|mantenimiento de edificio"
            r"|aire acondicionado|gases? medicinal|\boxigeno\b|analisis de agua|agua potable|calidad del agua"
            r"|laboratorio de suelos|suelos|control de calidad de alimentos|inocuidad|veterinari|sanidad animal"
            r"|\bmag\b|psicolog|laboratorio escolar|centros? escolar|laboratorio de comput|computacion"
            r"|prueba de esfuerzo|prueba hidrostatica|pruebas? de carga|concreto|asfalto|vehicul|llanta"
            r"|uniforme|pintura|combustible|fumigaci|plaguicid|insecticid|larvicid|abate|mosquitero"
            r"|bromatolog|leche|carne|lacteo|semilla|fertiliz|ganad|bovino|porcino|aviar|pecuari|acuicol"
            r"|forense de suelo|balistic|odontolog|audiometr|auditiv|otoacustic|audiolog|incendio"
            r"|desechos|residuos|recoleccion,? transporte|disposicion final|subsidio"
            r"|calderas|emision de gases|microscopio|electrodo|electrocauter|alta frecuencia|bisturi|cuartos? frios?|morgue|repuestos"
            r"|municion|filtros? (bacteriolog|antibacteria|hepa)|frascos? (de )?plastico|recoleccion y transporte de muestras"
            r"|servicios? de (laboratorio clinico|examenes)|examenes de laboratorio|toma de examenes|laboratorio radiologico|mamografia")
# Words that mean the line is a medicine / IV fluid, not a reagent
DRUG = R(r"\b\d+(\.\d+)? ?(mg|mcg|ug|ui|u\.i\.|meq)\b|tableta|capsula|comprimido|inyectable|ampolla|jarabe"
         r"|suspension oral|frasco ampolla|solucion (salina|glucosada|dextrosa|inyectable|oral)|dextrosa"
         r"|crema|unguento|gotas (oftalm|otic)|\bgel topico|sobre (oral|granulado)|polvo (para|liofilizado para) (solucion|suspension) (inyectable|oral)"
         r"|lactato de ringer|ringer|hartman|vial (de|con) \d|pluma|insulina (nph|cristalina|glargina|humana|rapida|lispro|aspart|detemir|degludec)")
REAGENT = R(r"reactiv|\bkits?\b|prueba|determinaci|\btest\b|ensayo|calibrador|\bcontrol(es)? (de calidad|normal|patologic|nivel|alto|bajo|positivo|negativo)"
            r"|cartucho|cassette|casete|\btiras?\b|elisa|\bclia\b|quimiolumin|electroquimiolumin|inmunoturbid|turbidim"
            r"|para (el )?(analizador|equipo)|latex|enzimatic|colorimetr|cuantitativ|cualitativ|semicuantitativ"
            r"|estandar|multicalibrador|suero control|\br[12]\b|reagent|\bdiluyente|\blisante|\bpanel\b|anticuerpo"
            r"|antigeno|\bigg\b|\bigm\b|serolog|inmunoensayo|inmunologi|\bpcr\b|\bmetodo\b|\bdet\b|\bdeterm")
# UNSPSC classes that are unambiguously clinical diagnostics (generic chemical, food, environmental,
# amino-acid, DNA-sequencer and "chemical assay kit" classes are excluded: they are misused for pool
# chemicals, water kits and research reagents in HonduCompras)
DIAG_UNSPSC = R(r"^(4111600[2-57-9]|411160(1[0-5])|411161(0[1-3]|0[7-9]|1[2-3]|2[0-8]|3[0-8]|4[0-8])|411162|4111580[2-9]"
                r"|411158(1[0-05-6]|19|2[0-3]|30)|41104102)")
RAPID = R(r"prueba(s)? rapida|test rapido|pruebas? de diagnostico rapido|\bpdr\b|inmunocromatogr|casete|cassette"
          r"|dispositivo|autoprueba|auto ?test|determine|bioline|\bsd\b|standard q|panbio|oraquick|uni-?gold|first response"
          r"|carestart|wondfo|one step|un paso|oro coloidal|colloidal gold|cualitativ|rapid[ao]s?\b|tira rapida|tarjeta|card\b|dual|duo\b|combo\b|pruebas? de antigeno|biocredit|flowflex|clinitest|ag rapid|antigen rapid")
LABIA = R(r"elisa|\bclia\b|quimiolumin|electroquimiolumin|\beclia\b|microelisa|inmunoensayo|western|inmunoblot"
          r"|cuarta generacion|ag/ac|ag-ac|p24|geenius|confirmator|architect|alinity|cobas e|elecsys|vidas|liaison|maglumi"
          r"|immulite|access|vitros|para analizador|para equipo|calibrador|\bcuantitativ")
MOLEC = R(r"molecular|tiempo real|rt-?pcr|pcr-?rt|microarreglo|microarray|variantes? de(l)? (sars|covid|virus)|\bqpcr|amplificacion|acidos? nucleic|\barn\b|\badn\b|\bdna\b|\brna\b|genexpert|xpert"
          r"|carga viral|genotip|extraccion de|termociclador|master ?mix|primers?|sondas?|oligonucleot|cobas (4800|5800|6800|8800|liat|z)"
          r"|m2000|alinity m|panther|aptima|biofire|filmarray|truenat|id now|seegene|allplex|altona|realstar|sansure|taqpath|\bnat\b|captura hibrida")
POCMOL = R(r"xpert|genexpert|cartucho|id now|liat|spotfire|m-?pima|punto de atencion|prueba rapida molecular|truenat")
BLOODBANK = R(r"banco de sangre|donante|hemocentro|transfusi|cruz roja|programa nacional de sangre|centro nacional de sangre|tamizaje serolog|tamizaje de (sangre|unidades)")
HOSPITAL = R(r"hospital|\bisss\b|\bihss\b|seguro social|seguridad social")
PRIMARY = R(r"unidad(es)? comunitari|ucsf|\buaps\b|\bcis\b|cesamo|cesar|centro de salud|region(al)? (departamental|metropolitana|sanitaria|de salud)|clinica comunal|primer nivel|establecimiento")
NONHC = R(r"aeropuerto|\bcepa\b|migraci|frontera|proteccion civil|copeco|alcaldia|municipalidad|municipio|ministerio de (trabajo|educacion|seguridad|defensa|gobernacion)|policia|centro penal|penitenciari|asamblea|universidad|ong\b|empresa")
PATIENT = R(r"pacientes? diabetic|autocontrol|automonitoreo|programa (de|nacional de) diabetes|entrega a pacientes|uso domiciliar|clinica de diabetes|insumos para diabetic")
WARD = R(r"uso hospitalario|hospitalari[oa]|sala|\buci\b|\buti\b|emergencia|cuidados intensivos|glucometro hospitalario")

LABCUE = R(r"reactiv|prueba|laborat|diagnost|analizador|banco de sangre|patolog|citolog|histolog|tamizaje (neonatal|metabolic|de banco|serolog)|gases (arteriales|sanguineos)"
           r"|gasometr|glucometr|glucosa|tiras|lancet|cultivo|microbiolog|bacteriolog|hematolog|inmuno|serolog|molecular|\bpcr\b|\bvih\b|covid|sars|dengue"
           r"|ensayo|determinac|anticuerpo|antisuero|antigeno|hemoglobina|coagulac|orina|urian|uroan|secuenc|genetic|\bkits?\b|cartucho|hemocultivo|agar"
           r"|citometr|\bcd4\b|carga viral|baciloscop|glucemi|insulin|sensor de glucosa|biologia molecular|termociclador|hematoxilina|parafina|microtomo|ihq")
MEDS_ONLY = R(r"medicamento|farmaco|vacuna|biologicos para vacun")
# Item-level: services, generic lab gear and non-IVD consumables (dropped unless a clear IVD word is present)
EXCLUDE_ITEM = R(r"desaduanaje|almacenaje|\bflete|transporte de|servicios? de (mantenimiento|transporte|publicacion|consultoria|vigilancia|limpieza)"
                 r"|publicacion|aviso de|expresion de interes|talonario|formulario|papeleria|impres|repuesto|motocicleta|toyota|ford|nissan|retrovisor"
                 r"|esparadrapo|autoclave|microscopio|balanza|refrigerad|congelador|bano maria|destilador|horno|estufa|agitador|termometro|esfigmo"
                 r"|tubos? (de ensayo|vacutainer|tapon|para (toma|recoleccion)|capilares?|de hemolisis|al vacio|con (edta|heparina|citrato|gel))"
                 r"|bolsas? (para|de) (sangre|recoleccion)|bolsas triples|jeringa|aguja|guante|\bgasa|algodon|alcohol (etilico|isopropilico|al \d|\d)|plastilina"
                 r"|leuco ?r?reduccion|filtros? para leuco|aferesis|bolsas? (cuadruple|doble|triple|simple)"
                 r"|kits? de (alimentos|tratamiento|higiene|limpieza|proteccion)|alimentos|tratamiento (para|del?) covid|mascarilla|careta|\bbata")
STRONG_IVD = R(r"reactiv|pruebas? (rapida|de (embarazo|vih|sifilis|dengue|covid|antigeno|hepatitis|malaria|glucosa))|\bkits? (de|para) (deteccion|diagnost|determinac|elisa|pcr|extraccion|tincion|gram|citologia)"
               r"|antisuero|\banti ?-?(a|b|d|ab)\b|\bagar\b|medios? de cultivo|discos? (de )?sensibilidad|tiras? reactiva|glucometr|lanceta|hematoxilina|eosina|parafina|\belisa"
               r"|\bvih\b|sifilis|treponem|antigeno|anticuerpo|tincion|colorante|giemsa|\bwright\b|\bgram\b|coombs|hemocultivo|cartucho|calibrador|control(es)? (normal|patolog|de calidad)"
               r"|\bdetermine\b|\bigg\b|\bigm\b|hbsag|dengue|\bpcr\b|carga viral|termociclador|analizador|lisante|tromboplastina|fibrinogeno|dimero|uroanalisis|urianalisis"
               r"|tiras? (de|para) orina|baciloscop|ziehl|quimica clinica|banco de sangre|inmunoensayo|serolog|citometr|\bcd4\b|xpert|biologia molecular|kligler|macconkey|sabouraud"
               r"|mueller|chagas|toxoplasm|rubeola|sarampion|\bhcg\b|embarazo|troponina|procalcitonina|ferritina|\btsh\b|\bpsa\b|hemoglobina glic|hba1c|gases arteriales"
               r"|cassette|casete|inmunocromat|(pcr|aso|fr|reactivo|kit|prueba)s? (de )?latex|latex (pcr|aso|fr|reactivo)|\bvdrl\b|\brpr\b|widal|febriles|\baso\b|factor reumat|proteina c reactiva|diluyente (para|de) (equipo|hematol|analiz)"
               r"|hemoglobina|hematocrito|grupo sanguineo|tipificacion|qiaamp|extraccion de (arn|adn)|sensor de glucosa|tiras? (de|para) glucosa|tincion especial|\bp\.a\.s")

# ---------------------------------------------------------------- rules
# (code, pattern, gate) gate: None = no extra gate; "R" = needs reagent context and no drug words;
# "S" = strict (explicit assay word required, any drug word blocks)
ANALYTE_ROUTINE = (r"glucosa|\burea\b|nitrogeno ureico|\bbun\b|creatinina|acido urico|colesterol|triglicerid|\bhdl\b|\bldl\b"
                   r"|transaminasa|\btgo\b|\btgp\b|\bast\b|\balt\b|bilirrubina|fosfatasa alcalina|\bggt\b|gamma ?glutamil"
                   r"|amilasa|lipasa|proteinas? totales|albumina|\bcalcio\b|fosforo|magnesio|\bsodio\b|potasio|\bcloro\b|cloruros?"
                   r"|electrolito|\bldh\b|deshidrogenasa lactica|\bcpk\b|\bck\b|creatin ?(fosfo)?kinasa|ck-?mb(?! masa)|hierro serico|\bhierro\b"
                   r"|capacidad de fijacion|microalbumin|depuracion de creatinina|lactato|amonio|colinesterasa|\bcO2\b|bicarbonato")
RULES = [
    # --- Clinical chemistry
    ("CCIAS", r"sistema integrado (de )?(quimica|inmuno)|plataforma consolidada|cobas (6000|8000|pro)\b|architect ci|alinity ci|atellica solution|serum work area", None),
    ("CCSAI", r"analizador(es)? (automatizado |semiautomatizado |semi-automatizado |automatico |semiautomatico )?(de |para )?(quimica|bioquimica)|equipo (automatizado )?de (quimica|bioquimica)|espectrofotometro|fotometro|humastar|cobas c ?111|\bbs-?(120|200|240|380|480|800)\b|\bba ?200\b", None),
    ("CCRRR", r"reactivos? (de|para) (quimica|bioquimica)|kits? de (quimica|bioquimica)|suero control|multicalibrador|control(es)? de calidad (para |de )?(quimica|bioquimica)|calibrador(es)? (para |de )?(quimica|bioquimica)", None),
    ("CCROU", ANALYTE_ROUTINE, "CHEM"),
    ("CCDOA", r"drogas? de abuso|toxicologic|cannabin|\bthc\b|cocaina|anfetamin|metanfetamin|opiaceo|benzodiacep|barbitur|etanol|alcohol en sangre|alcoholemia", "R"),
    ("CCTDM", r"digoxina|vancomicina|gentamicina|amikacina|fenitoina|carbamazepina|acido valproico|valproato|fenobarbital|\blitio\b|teofilina|metotrexato|paracetamol|acetaminofen|salicilato", "S"),
    ("CCHBA", r"hemoglobina glic|hemoglobina glucosilad|glicohemoglobina|hba1c|hb a1c|\ba1c\b|glicosilada", None),
    ("CCSPE", r"inmunoglobulina (a|g|m|e)\b|\biga\b|complemento c?3|complemento c?4|factor reumatoid|\bfr\b|\brf\b.{0,20}latex|latex.{0,20}\brf\b|antiestreptolisin|\baso\b|\baslo\b|prealbumina|haptoglobina|ceruloplasmina|cadenas? ligeras|beta ?2 ?microglob|ige total|transferrina", "S"),
    # --- Immunoassay
    ("IAINS", r"analizador(es)? (automatizado )?(de |para )?(inmunoensayo|quimioluminiscencia|inmunologia|hormonas)|lector(es)? (de )?(elisa|microplaca)|lavador(es)? (de )?(elisa|microplaca)|procesador de elisa|\bmini ?vidas\b|maglumi \d|liaison xl|immulite \d|cobas e ?(411|601|801)|architect i ?(1000|2000)", None),
    ("IARRR", r"reactivos? (de|para) (inmunologia|inmunoensayo|quimioluminiscencia|hormonas)|kits? (de )?elisa", None),
    ("IATHY", r"\btsh\b|\bt3\b|\bt4\b|tiroxina|triyodotironina|tiroglobulina|anti-?tpo|peroxidasa tiroid|perfil tiroideo|tiroide(a|o)s|hormona estimulante de (la )?tiroides|tamizaje neonatal|tamizaje metabolico neonatal", "S"),
    ("IAANE", r"ferritina|vitamina b ?12|cianocobalamina|acido folico|folato|eritropoyetina|receptor soluble de transferrina", "S"),
    ("IAGRH", r"hormona de(l)? crecimiento|somatotrop|igf-?1|somatomedina", "S"),
    ("IADBT", r"\binsulina\b|peptido c\b|proinsulina|anti-?gad|antiislote", "S"),
    ("IAADH", r"\bcortisol|\bacth\b|adrenocorticotrop|aldosterona|\brenina\b|\bdhea|17-?(oh|hidroxi) ?progesterona|androstenediona", "S"),
    ("IAONC", r"\bpsa\b|antigeno prostatico|\bcea\b|carcinoembrionario|\bca ?-?125\b|\bca ?-?15[ .-]?3\b|\bca ?-?19[ .-]?9\b|\bca ?-?72[ .-]?4|alfa ?-?feto|\bafp\b|\bhe4\b|cyfra|(?<!pro)calcitonina|\bscc\b|pivka|progrp|enolasa|\bnse\b|marcador(es)? tumoral", "S"),
    ("IAHIV", r"\bvih\b|\bhiv\b|inmunodeficiencia humana", "R"),
    ("IASTI", r"sifilis|treponem|\btpha\b|\btppa\b|fta-?abs|\brpr\b|\bvdrl\b|clamidia|chlamydia|herpes simple", "R"),
    ("IAHBV", r"hepatitis b\b|\bhbsag\b|anti-?hbs\b|anti-?hbc|\bhbeag|anti-?hbe\b|\bvhb\b|\bhbv\b|antigeno de superficie", "R"),
    ("IAHCV", r"hepatitis c\b|anti-?vhc|anti-?hcv|\bvhc\b|\bhcv\b", "R"),
    ("IAMTB", r"quantiferon|\bigra\b|interferon gamma|t-?spot|\blam\b", "R"),
    ("IADEN", r"dengue|\bns1\b|arbovirus|\bzika\b|chikungu", "R"),
    ("TORCH", r"\btorch\b|toxoplasm|rubeola|citomegalovirus|\bcmv\b", "R"),
    ("IAIOT", r"epstein|\bebv\b|mononucleosis|sarampion|paperas|varicela|helicobacter|brucel|leptospir|rickettsi|hepatitis a\b|anti-?vha|\bvha\b|\bhav\b|hepatitis e\b|chagas|trypanosoma|tripanosoma|amebiasis|entamoeba|leishman|mycoplasma|legionella|aspergill|cryptococ|criptococ|histoplasm|strongyl|cisticerc|toxocara", "R"),
    ("IAFER", r"beta ?-?hcg|b-?hcg|\bhcg\b|gonadotropina corionica|\bfsh\b|\blh\b(?! ?-?lyse)|hormona luteinizante|foliculo ?estimulante|prolactina|estradiol|progesterona|testosterona|\bshbg\b|antimulleriana|\bamh\b", "S"),
    ("PHCGT", r"prueba(s)? de embarazo|test de embarazo|embarazo (en orina|rapida|tira|casete|cassette)|hcg (en orina|urinari|cualitativ)|deteccion de embarazo", None),
    ("IATRO", r"troponina|\bctni\b|\bctnt\b|hs-?tn", "R"),
    ("IABNN", r"\bbnp\b(?!.*pro)|peptido natriuretico (tipo b|cerebral)(?!.*pro)", "R"),
    ("IABPP", r"nt-?pro ?-?bnp|pro-?bnp|probnp", "R"),
    ("IACOT", r"mioglobina|ck-?mb masa|galectina|\bst2\b|homocisteina", "R"),
    ("IACRP", r"proteina c reactiva|\bcrp\b|hs-?crp|\bpcr (cuantitativ|ultrasensible|hs\b|alta sensibilidad|turbidim|latex|semicuant|cualitativ)|\bpcr\b.*(latex|turbidim|aglutinaci)", None),
    ("IAPCT", r"procalcitonina|\bpct\b", "R"),
    ("IAIAO", r"interleucina ?-?6|interleuquina ?-?6|\bil-?6\b|presepsina", "R"),
    ("IABON", r"vitamina d\b|25 ?-?(oh|hidroxi)|paratohormona|hormona paratiroidea|\bpth\b|osteocalcina|crosslaps|\bctx\b|\bp1np\b", "S"),
    ("IAAUI", r"antinuclear|\bana\b|anti-?dna|dsdna|\bena\b|anti-?sm\b|anti-?rnp|anti-?ro\b|anti-?la\b|anti-?ccp|citrulin|\banca\b|anticardiolipin|beta ?2 glicoprot|transglutaminasa|celiaq|hep-?2|autoinmun", "R"),
    ("IACOV", r"(covid|sars-?cov|coronavirus).{0,80}(prueba|reactiv|antigen|anticuerp|diagnost|\btest|deteccion|\bigg\b|\bigm\b|elisa|serolog)|(prueba|reactiv|antigen|anticuerp|diagnost|\btest|deteccion|\bigg\b|\bigm\b|elisa|serolog).{0,80}(covid|sars-?cov|coronavirus)", "R"),
    ("IAALG", r"ige especifica|panel de alergenos|alergenos (alimentarios|respiratorios|inhalantes)|pruebas? de alergia|immunocap", "R"),
    ("IAISD", r"tacrolimus|ciclosporina|sirolimus|everolimus|micofenol", "S"),
    ("IANEU", r"\bs100\b|neurofilamento|beta amiloide|proteina tau", "R"),
    ("IALFB", r"acido hialuronico.*fibrosis|fibrosis hepatica|\belf\b", "R"),
    ("IAOTH", r"gastrina|pepsinogeno|calprotectina|elastasa fecal", "R"),
    ("IAZZZ", r"inmunoensayo|quimioluminis|electroquimiolumin|(kit|prueba|test|placa|lector|reactivo|tecnica|metodo)s? (de |por |para )?elisa|elisa (kit|test|para|de|igg|igm|vih|\d)|inmunologia|inmunofluoresc|marcadores? virales", None),
    # --- Coagulation
    ("COISR", r"coagulometro|analizador(es)? (automatizado )?de (coagulacion|hemostasia)|equipo de coagulacion|\bsta (compact|r max|satellite)|acl (top|elite)|\bcs-?(2500|5100)\b|\bca-?600\b", None),
    ("COTRA", r"tiempo de protrombina|(?<!sifilis )(?<!syphilis )(?<!anti-)(?<!anti )\btp\b(?! determine)|\binr\b|tromboplastina|\bttpa?\b|\btpt\b|\bptt\b|aptt|cefalina|fibrinogeno|tiempo de trombina|plasma control|neoplastine|actin|pathromtin|thromborel|innovin", "R"),
    ("COOTH", r"factor (ii|v|vii|viii|ix|x|xi|xii)\b (deficiente|reactivo|plasma|ensayo|determinacion)|(determinacion|dosificacion|prueba) (de|del) factor (ii|v|vii|viii|ix|x|xi|xii)\b|plasma deficiente|von willebrand.*(reactivo|ensayo|antigeno|actividad)|antitrombina (iii )?(reactivo|ensayo|determinacion|kit)|proteina c\b(?! reactiva)|proteina s\b|anti-?xa|anticoagulante lupico|plasminogeno|agregacion plaquetaria|tromboelastogr|tromboelastom|\brotem\b|\bteg\b", "R"),
    ("CODMR", r"dimero|d-?dimer|productos de degradacion del fibrin", "R"),
    # --- Urinalysis
    ("URISR", r"analizador(es)? (de |para )?(orina|uroanalisis|urianalisis|tiras de orina|sedimento)|lector(es)? de tiras (reactivas )?(de|para) orina|clinitek|urisys|uriscan|aution|cobas u ?(411|601|701)|\buf-?(1000|1500|5000)\b|iq ?200|\bdirui\b.*(analiz|equipo)", None),
    ("URQUA", r"cintas? (reactivas? )?(para |de )?(orina|uroanalisis)|tiras? (reactivas? )?(para |de )?(orina|uroanalisis|urianalisis|urinalisis|examen general de orina)|multistix|combur|uritest|(tiras?|tira reactiva).*(\b1[01] parametros|\b\d+ parametros|urobilin|nitrito|leucocit|cetona)|uroanalisis|urianalisis", None),
    ("URSED", r"sedimento urinario|microscopia de orina|camara (de recuento|kova)|\bkova\b", None),
    # --- Haematology
    ("HMISR", r"analizador(es)? (automatizado )?(hematologic|de hematologia)|contador(es)? hematologic|equipo (automatizado )?de hematologia|hematology analy|\bxn-?\d|\bxs-?\d|\bxp-?300|\bkx-?21|\bbc-?\d{4}|\bbc-?\d{2}s?\b|cell-?dyn|\bdxh\b|yumizen|pentra|micros 60|\b(3|5) (partes|diferenciales)\b", None),
    ("HMCIA", r"cellavision|morfologia digital|diferencial digital|extendedor y tenidor", None),
    ("HMCBC", r"reactivos? (de|para) hematologia|reactivo hematologic|diluyente.{0,30}(hematol|equipo|analizador|celular|isoton|cell)|(hematol|equipo|analizador|cell).{0,30}diluyente|lisante|\blyse|lysercell|stromatolyser|sulfolyser|cellpack|cell pack|cellclean|cell clean|fluorocell|e-?z ?cleaner|limpiador (enzimatico|hematolog)|control(es)? hematologic|sangre control|hemograma|hematimetr|eritrosedimentacion|velocidad de sedimentacion|\bves\b|\bvsg\b|reticulocit|azul de cresil", "R"),
    # --- Flow
    ("FLOWC", r"citometr|citometro|\bcd4\b|\bcd8\b|inmunofenotip|\bfacs|subpoblaciones linfocitarias|pima cd4", None),
    # --- Immunohaematology
    ("IHISR", r"centrifuga.{0,40}(banco de sangre|serolog|sero ?fuge|tarjetas|gel)|centrifuga (para|de) (tarjetas|gel)|incubador(a)? (para|de) (tarjetas|gel)|lector de tarjetas|erytra|wadiana|ih-?(1000|500)\b|ortho vision|neo iris|\becho lumena|equipo (automatizado )?(de )?inmunohematolog", None),
    ("IMGLO", r"coombs|antiglobulina", None),
    ("IMCCY", r"prueba(s)? cruzada|pruebas? de compatibilidad|compatibilidad (transfusional|sanguinea)", None),
    ("IMABS", r"rastreo de anticuerpos|deteccion de anticuerpos irregulares|anticuerpos irregulares|identificacion de anticuerpos|celulas (panel|de panel|pantalla|de pantalla|de screening|identificadoras)|panel (de )?celulas|serascan|panocell|resolve panel|identisera", None),
    ("IMATY", r"fenotipo eritrocitario|fenotipaje|fenotipo.{0,25}(rh|kell|cece)|\banti-?(kell|k\b|cw|fya|fyb|jka|jkb|lea|leb|m\b|n\b|s\b)|antisueros? raros", None),
    ("ATITR", r"titulacion de anticuerpos|titulo anti-?d|isohemaglutinin", None),
    ("BGNTZ", r"antisuero|\banti ?-?a\b|\banti ?-?b\b|\banti ?-?d\b|\banti ?-?ab\b|\banti ?-?a1\b|lectina|grupo sanguineo|grupos sanguineos|tipificacion sangu|tipaje|hemoclasificacion|\babo\b|factor rh|anti ?-?rh|abo ?(/|y) ?rh|grupo y rh|\brhd\b|rh ?\(d\)|celulas a1|globulos rojos (a|b) |hematies (a1|b)|tarjetas? abo", None),
    ("IMMHM", r"tarjetas? (de )?gel|(tarjeta|cassette)s? o (tarjeta|cassette)s? de gel|gel card|dg gel|diamed|biovue|bio-?vue|inmunohematolog|microtubos de gel|columnas? de aglutinacion|tarjetas? (para )?(tipaje|banco de sangre)", None),
    # --- Microbiology
    ("AIDST", r"vitek|phoenix|microscan|maldi|pruebas? bioquimicas? para (la )?identificacion.{0,60}(automatizad|equipo)|identificacion de (levaduras?|microorganismos?|bacterias?|gram).{0,60}(automatizad|equipo)|"
              r"(susceptibilidad|sensibilidad) antimicrobiana.{0,40}(automatizad|equipo)|tarjetas? (de )?(identificacion|susceptibilidad|sensibilidad|\bast\b|\bgn\b|\bgp\b|\bnh\b|\byst\b)|paneles? (de )?(identificacion|combo) (bacteriana|microbiologica)|sensititre|walkaway|identificacion y (susceptibilidad|sensibilidad) automatizada", None),
    ("ABDCL", r"hemocultivo|botellas? (de|para) (hemocultivo|cultivo)|frascos? (de|para) (hemocultivo|cultivo)|bact ?/?alert|bactec|\bmgit\b|virtuo", None),
    ("MIDCL", r"\bagar\b|medios? de cultivo|medio de transporte|\bcaldo\b|discos? (de )?(sensibilidad|antibiotico|antibiograma|antimicrob|sensidisco)|sensidisco|api ?20|galeria(s)? (de )?identificacion|tincion de gram|coloracion de gram|kit (de )?gram|\bgram\b|ziehl|baciloscop|lowenstein|ogawa|stuart|cary ?blair|kligler|\btsi\b|citrato de simmons|\bsim\b|cristal violeta|safranina|fucsina|carbol|azul de metileno|lugol|giemsa|wright|kinyoun|tinta china|hidroxido de potasio|\bkoh\b|antibiograma|urocultivo|coprocultivo|cultivo (bacteri|de micobacterias|de hongos)|hisopos? con medio|identificacion bacteriana|pruebas bioquimicas (para identificacion|bacterianas)|sabouraud|mueller|hinton|macconkey|thayer|chromagar|cromogenico", None),
    ("DGSOL", r"sistema de informacion de laboratorio|\blis\b|middleware|interfaz (de|para|con) (los )?(equipos|analizadores)|software (de|para) laboratorio|sistema informatico de laboratorio|conectividad de laboratorio", None),
    ("PPRTN", r"electroforesis (de proteinas|capilar|de hemoglobina|de lipoproteinas)|inmunofijacion|proteinograma|bandas monoclonales|hydrasys|capillarys", None),
    ("MASSP", r"espectrometr(o|ia) de masas|\blc-?ms|\bgc-?ms|cromatografia liquida acoplada", None),
    ("LABAU", r"automatizacion (del|de) laboratorio|cadena de automatizacion|linea automatizada (de laboratorio|de muestras)|sistema preanalitico|destapador (de tubos|automatico)|alicuotador|clasificador de (tubos|muestras)|sistema de transporte de muestras|cobas (8100|p ?512|p ?612)|aptio|accelerator a3600|flexlab", None),
    # --- POC
    ("BGEZZ", r"gases (arteriales|sanguineos|en sangre|venosos)|gasometr|analizador(es)? de gases|cartuchos? (de|para) (gases|gasometr)|sensor(es)? de gases|gem premier|\babl ?(80|90|800|9)\b|cobas b ?(121|221|123)|\bepoc\b|i-?stat.*(cg|e3|ec8|chem8|cartucho)|rapidpoint|jeringas? (para|de) gases|co-?oximetr|calcio ionico", None),
    ("CHPLC", r"hemoglobinopatia|variantes de hemoglobina|electroforesis de hemoglobina", None),
    ("POCCZ", r"hemoglobinometro|tamizaje de anemia|hemocue|cardiochek|cholestech|tiras? (reactivas? )?(de|para) colesterol|lipidocare|piccolo|statsensor|hemoglobina portatil|medidor de hemoglobina|mission hb|hb ?201|hb ?301", None),
    ("PCHIZ", r"afinion 2|analizador combinado hba1c|a1ccare", None),
    ("PCOAG", r"coaguchek|inr portatil|tiras? (de|para) inr|tiempo de coagulacion activad|\bact\b(?! de)|hemochron|xprecia|i-?stat.*(pt|inr|act)|tromboelastografia en quirofano", None),
    ("PHIVS", r"\bvih\b|\bhiv\b|inmunodeficiencia humana", "RAPID"),
    ("PSYPH", r"sifilis|treponem|\btp\b", "RAPID"),
    ("PCTNZ", r"clamidia|chlamydia|gonorrea|gonorrhoeae", "RAPID"),
    ("PHAVZ", r"hepatitis a\b|\bvha\b|\bhav\b|hepatitis e\b", "RAPID"),
    ("PHBVZ", r"hepatitis b\b|\bhbsag\b|\bvhb\b|\bhbv\b|antigeno de superficie", "RAPID"),
    ("PHCVZ", r"hepatitis c\b|\bvhc\b|\bhcv\b", "RAPID"),
    ("PDENG", r"dengue|\bns1\b", "RAPID"),
    ("PMALA", r"malaria|paludismo|plasmodium|\bhrp2\b|\bpldh\b", "RAPID"),
    ("PVBDX", r"chikungu|\bzika\b|leptospir|leishman|chagas|trypanosoma|tripanosoma", "RAPID"),
    ("PGASZ", r"rotavirus|adenovirus.*(heces|fecal)|helicobacter.*(heces|fecal|antigeno)|sangre oculta|guayaco|\bfob\b|\bfit\b|norovirus|giardia|cryptospor|clostridi.*difficile", "RAPID"),
    ("PRESX", r"influenza|\bvsr\b|sincitial|\brsv\b|estreptococo (del )?(grupo )?a\b|strep ?a\b|streptococcus pyogenes|neumococo|legionella|mycoplasma", "RAPID"),
    ("PCOVD", r"covid|sars-?cov|coronavirus", "RAPID"),
    ("PCART", r"troponina", "RAPID"),
    ("PCARP", r"\bbnp\b(?!.*pro)", "RAPID"),
    ("PCABN", r"nt-?pro ?-?bnp|probnp", "RAPID"),
    ("PCARX", r"mioglobina|ck-?mb|panel cardiaco|triple marcador", "RAPID"),
    ("PCCRP", r"proteina c reactiva|\bcrp\b|\bpcr\b", "RAPIDCRP"),
    ("PCPCT", r"procalcitonina|\bpct\b", "RAPID"),
    ("PDOAB", r"drogas? de abuso|multidroga|cannabin|\bthc\b|cocaina|anfetamin|opiaceo|benzodiacep|alcohol en (saliva|aliento)", "RAPID"),
    ("POTXX", r"toxoplasm|tuberculosis|\btb\b|leptospir|brucel|tifoidea|salmonella|widal|febriles|\bh\. ?pylori|helicobacter|mononucleosis|epstein", "RAPID"),
    # --- Molecular
    ("MDXIZ", r"termociclador|equipo (de|para) pcr|equipamiento (de|para) pcr|extractor (automatizado )?de acidos nucleicos|extractor automatizado|plataforma molecular|analizador molecular|genexpert (iv|xvi|infinity|edge|\d+ modulos)|modulos? (de )?genexpert|equipo genexpert|quantstudio|cfx ?96|cfx opus|rotor-?gene|cobas (5800|6800|8800|z 480)\b(?!.*(kit|reactiv|prueba))|m2000(sp|rt)|alinity m (sistema|equipo)|lightcycler|abi 7500|7500 fast|magna ?pure|qiacube|kingfisher|maxwell", None),
    ("NATZZ", r"\bnat\b|tamizaje molecular|procleix|cobas mpx|acidos nucleicos.*donante", None),
    ("HPVCZ", r"genotipificacion de (vph|hpv)|genotipos? (vph|hpv)|vph 16|hpv 16|16 ?/ ?18", None),
    ("HPVSZ", r"\bvph\b|\bhpv\b|papiloma|captura hibrida|carehpv|hybrid capture", "HPV"),
    ("MTBZZ", r"tuberculosis|\bmtb\b|mycobacterium|micobacteri|rifampicina|xpert mtb|mtb/?rif|truenat|line probe|\blpa\b|genotype mtbdr|mtbdrplus", "MOL"),
    ("MCTNZ", r"clamidia|chlamydia|gonorrea|gonorrhoeae|ct/?ng", "MOL"),
    ("MSTDX", r"trichomonas|mycoplasma genitalium|vaginosis", "MOL"),
    ("CDIFF", r"difficile", "MOL"),
    ("HAIXX", r"carbapenemasa|\bkpc\b|\bndm\b|\bvim\b|oxa-?48|carba-?r|\bvre\b|vana|candida auris", "MOL"),
    ("MMRSA", r"\bmrsa\b|\bsarm\b|meticilina|sa nasal", "MOL"),
    ("MGABS", r"\bgbs\b|grupo b|agalactiae|strep a\b|grupo a\b", "MOL"),
    ("MHCVZ", r"hepatitis c\b|\bvhc\b|\bhcv\b", "MOL"),
    ("MHBVZ", r"hepatitis b\b|\bvhb\b|\bhbv\b", "MOL"),
    ("MHIVZ", r"\bvih\b|\bhiv\b", "MOL"),
    ("MFLUA", r"influenza|h1n1|h3n2|h5n1|flu\b", "MOL"),
    ("MRSVZ", r"\bvsr\b|\brsv\b|sincitial", "MOL"),
    ("MADNZ", r"adenovirus", "MOL"),
    ("MCOVD", r"covid|sars-?cov|coronavirus", "MOL"),
    ("MCOVD", r"medio de transporte (universal |viral )?(para )?virus|medio de transporte viral|hisopos? (con|y) medio de transporte viral", None),
    ("MHERP", r"herpes|\bvhs\b|\bhsv\b|varicela|\bvzv\b", "MOL"),
    ("PTRAN", r"citomegalovirus|\bcmv\b|\bbk ?virus|\bbkv\b|epstein|\bebv\b|trasplante", "MOL"),
    ("MDENG", r"dengue|denv", "MOL"),
    ("MVIRF", r"zika|chikungu|fiebre amarilla|trioplex|leptospir|oropouche|arbovirus", "MOL"),
    ("MGAST", r"norovirus|rotavirus|salmonella|shigella|campylobacter|e\.? ?coli|vibrio|colera", "MOL"),
    ("PMENI", r"meningitis|encefalitis|\bme panel|panel me\b", "MOL"),
    ("PGAST", r"panel gastrointestinal|panel gi\b|panel (de )?diarrea", "MOL"),
    ("PRESP", r"panel respiratorio|panel (para (la )?determinacion de |de )?virus respiratorios|rp2|panel (de )?neumonia|respiratory panel", "MOL"),
    ("PSTDP", r"panel (de )?(its|ets|infecciones de transmision sexual)|sti panel", "MOL"),
    ("PBCID", r"bcid|identificacion (rapida )?de hemocultivo", "MOL"),
    ("MPANL", r"panel sindromico|multiplex|filmarray|biofire|qiastat|eplex|nxtag", "MOL"),
    ("MKRAS", r"\bkras\b|\bnras\b", "MOL"),
    ("MEGFR", r"\begfr\b", "MOL"),
    ("MBRAF", r"\bbraf\b", "MOL"),
    ("MONCX", r"bcr-?abl|filadelfia|jak2|flt3|npm1|pml-?rara|\balk\b|ros1|pik3ca|brca", "MOL"),
    ("MCOAG", r"factor v leiden|protrombina g20210|mthfr|trombofilia", "MOL"),
    ("MGENZ", r"genetic|\bhla\b|fibrosis quistica|x fragil|hereditari", "MOL"),
    ("MNAPZ", r"\blamp\b|isoterm|id now|\btma\b|nasba", None),
    ("MLDTZ", r"master ?mix|\bprimers\b|primers? (para|de) (pcr|amplificacion)|cebadores|sondas? (taqman|de hidrolisis)|oligonucleot|transcriptasa reversa|taq (adn )?polimerasa|polimerasa|kits? de extraccion|extraccion de (arn|adn|acidos nucleicos)|purificacion de (arn|adn)|dntp|qiaamp|viral rna", None),
    ("MDXZZ", r"biologia molecular|diagnostico molecular|reaccion en cadena de la polimerasa|pcr en tiempo real|rt-?pcr|\bqpcr\b|amplificacion de acidos nucleicos|\bnaat\b|carga viral", None),
    # --- Tissue
    ("ADSTI", r"inmunotenidor|equipo automatizado de inmunohistoquimica|benchmark (ultra|xt|gx)|dako omnis|autostainer|bond-?(iii|rx|max)|intellipath", None),
    ("ADISH", r"\bfish\b|\bcish\b|\bsish\b|hibridacion in situ|\beber\b|vysis", None),
    ("ADIHC", r"inmunohistoquim|\bihq\b|\bihc\b|receptor(es)? de estrogeno|receptor(es)? de progesterona|her-?2|ki-?67|pd-?l1|citoqueratina|\bck ?(7|20)\b|\bp16\b|\bp53\b|anticuerpos? (primario|monoclonal|policlonal)?.{0,40}\bcd ?(20|3|45|30|15|34|117|10|5|23|68|99)\b|cromogeno dab|polimero (hrp|de deteccion)|sistema de deteccion (ihq|para inmunohisto|polimer)|recuperacion antigenica|ultraview|optiview|envision", None),
    ("HNEIZ", r"tenidor(es)? automatico|coloreador(es)? automatico|tenidor y montador|montador de (laminas|cubreobjetos)|cubreobjetos automatico|histocore spectra|tissue-?tek (prisma|film)", None),
    ("HNERZ", r"hematoxilina|eosina|papanicol|orange g|\bog-?6\b|\bea-?(36|50|65)\b|medio de montaje|resina de montaje|balsamo|entellan|permount", None),
    ("TDXSS", r"tinciones? especiales|tincion especial|coloraciones? especiales|\bpas\b|\bp\.a\.s|tricromico|masson|grocott|metenamina|reticulina|perls|azul alcian|rojo congo|warthin", None),
    ("TDPRE", r"procesador(es)? (automatico )?de tejidos|cuchillas para cortar tejidos|procesamiento de tejidos|inclusion en parafina|centro de inclusion|parafina|microtomo|criostato|cuchillas? (desechables )?(de|para) microtomo|casetes? (de|para) (inclusion|biopsia|tejido)|cassettes? (de|para) (inclusion|biopsia|tejido)", None),
    ("TDDGP", r"patologia digital|escaner de (laminas|portaobjetos)|telepatologia|digitalizacion de laminas", None),
    ("TDWFS", r"rotulador de casetes|impresora de (casetes|portaobjetos)|trazabilidad de muestras (de )?patologia", None),
    ("TDXZZ", r"anatomia patologica|histopatolog|histotecnolog|citologia|laboratorio de patologia|biopsia|equipo de patologia", None),
    # --- NGS
    ("SEQIN", r"secuenciador|miseq\b(?!.*reagent)|iseq|nextseq|novaseq|ion torrent|genexus|minion|gridion|dnbseq|seqstudio|analizador genetico|abi 3500", None),
    ("SEQPR", r"preparacion de librerias|librerias|flow ?cell|celdas? de flujo|qubit|covidseq|ampliseq|kits? (de )?secuenciacion|miseq reagent|nextera|illumina dna prep", None),
    ("SINFD", r"vigilancia genomica|secuenciacion (de|del) (sars|virus|influenza|dengue|genoma viral)|metagenomic", None),
    ("SONCO", r"panel oncologico|perfil genomico tumoral|oncomine|secuenciacion tumoral", None),
    ("SGENE", r"\bexoma\b|genoma completo|panel de genes", None),
    ("SNIPT", r"\bnipt\b|adn fetal libre|prenatal no invasiv", None),
    ("SEQZZ", r"secuenciacion|\bngs\b|genomica", None),
    # --- Diabetes
    ("DICPU", r"monitoreo continuo de glucosa|monitor continuo de glucosa|sensor(es)? de glucosa|freestyle libre|dexcom|guardian (sensor|connect)|monitoreo flash", None),
    ("HGCZZ", r"accu-?chek inform|precision pro|statstrip|glucometro (hospitalario )?(conectado|con conectividad|con interfaz)", None),
    ("DBSPU", r"tiras? (reactivas? )?(para |de )?(medicion de )?(glucosa|glucemia|glicemia|glucometro)|tiras? reactivas?.*gluc|glucometr|glucosimetr|accu-?chek|freestyle (optium|freedom)|contour|onetouch|one touch|on call|bionime|sinocare|caresens|medidor de glucosa|monitor de glucosa", None),
    ("DBLPU", r"lancetas?|lancetero|dispositivo de puncion|softclix|fastclix|unistik|safe-?t-?pro|microlet", None),
    # --- generic parents (only used if nothing more specific)
    ("CDXZZ", r"reactivos? (de|para) (el )?laboratorio( clinico)?|insumos? (de|para) (el )?laboratorio( clinico)?|equipo de laboratorio clinico|analizador automatizado|pago por prueba|precio por prueba|costo por prueba|pruebas efectivamente realizadas|reactivos (e|y) insumos|examenes de laboratorio|pruebas de laboratorio|servicios? de laboratorio clinico", None),
    ("POCZZ", r"prueba(s)? rapida|pruebas de diagnostico rapido|inmunocromatogr", None),
    ("MICRO", r"microbiolog|bacteriolog", None),
    ("HEMEZ", r"hematolog", None),
    ("CCHEM", r"quimica clinica|quimica sanguinea|bioquimica", None),
    ("LCOAG", r"coagulacion|hemostasia", None),
    ("IMMHM", r"banco de sangre|medicina transfusional", None),
]
RULES = [(c, re.compile(p), g) for c, p, g in RULES]
GENERIC = {"CDXZZ", "POCZZ", "MICRO", "HEMEZ", "CCHEM", "LCOAG", "IAZZZ", "MDXZZ", "SEQZZ", "TDXZZ", "IMMHM"}
PCR_CRP = re.compile(r"proteina c reactiva|\bpcr\b.*(latex|turbidim|aglutinaci|cuantitativ|ultrasensible|semicuant|hs\b)|\bcrp\b")
CONTRACT_WORDS = re.compile(r"comodato|pago por prueba|precio por prueba|costo por prueba|pruebas efectivamente realizadas|segun demanda|suministro segun|contrato abierto|solucion integral|consignaci|arrendamiento de equipo|contrato marco")


HAS_CHILD = {c: any(o != c and SEG[o].startswith(SEG[c] + ".") for o in SEG) for c in SEG}


def depth(code):
    return len(SEG[code].split("."))


def is_anc(a, b):
    """a is a strict ancestor of b"""
    return SEG[b].startswith(SEG[a] + ".")


def lca(codes):
    parts = [SEG[c].split(".") for c in codes]
    common = []
    for xs in zip(*parts):
        if len(set(xs)) == 1:
            common.append(xs[0])
        else:
            break
    while common:
        s = ".".join(common)
        if s in CODE_BY_SEG:
            return CODE_BY_SEG[s]
        common.pop()
    return None


def refine(code, t, buyer):
    """Push a hit down to the deepest child the text supports."""
    mol_poc = bool(POCMOL.search(t))
    if code == "CCHBA":
        if re.search(r"afinion|\bdca\b|cobas b ?101|a1cnow|quo-?lab|ichroma|punto de atencion|cartucho", t):
            return "POCHZ"
        if re.search(r"hplc|\bd-?10\b|d-?100|variant|tosoh|\bg8\b|\bg11\b|adams|ha-?8180|intercambio ionico|cromatograf", t):
            return "CHPLC"
        if re.search(r"inmunoturbid|turbidimetr|tina-?quant|enzimatic|boronato|capillarys", t):
            return "COHBA"
    if code == "HNERZ":
        return "HNERA" if re.search(r"automatiz|para tenidor|para equipo|prisma|spectra|ventana|he 600", t) else "HNERM"
    if code == "TDXSS":
        if re.search(r"equipo|tenidor|instrumento|artisan", t):
            return "TDXSI"
        return "TDXSR"
    if code == "ADIHC":
        return "IHCAU" if re.search(r"comodato|con equipo|listo para usar|\brtu\b|prediluido|ventana|benchmark|bond|omnis|autostainer|para equipo|automatiz", t) else "IHCMA"
    if code == "ADISH":
        return "ISHAU" if re.search(r"automatiz|ventana|bond|para equipo|dual ish", t) else "ISHMA"
    if code == "TDDGP":
        return "TDDPS" if re.search(r"software|licencia|sistema de gestion|algoritmo", t) else "TDDPI"
    if code in ("MTBZZ", "MCTNZ", "MSTDX"):
        sub = {"MTBZZ": ("MTBPZ", "MTBLZ"), "MCTNZ": ("MCTNP", "MCTNL"), "MSTDX": ("MSTXP", "MSTXL")}[code]
        return sub[0] if mol_poc else sub[1]
    if code == "MHIVZ":
        if re.search(r"genotip|resistencia", t):
            return "MHIVG"
        if re.search(r"carga viral|cuantitativ|cuantificacion|\bvl\b|viral load", t):
            return "HIVVP" if mol_poc else "HIVVL"
        if re.search(r"cualitativ|\bqual|diagnostico (infantil )?temprano|\bdit\b|lactante|recien nacido|proviral|eid\b", t):
            return "HIVQP" if mol_poc else "HIVQL"
        return code
    if code in ("MHCVZ", "MHBVZ"):
        q, v, g = ("MHCVQ", "MHCVV", "MHCVG") if code == "MHCVZ" else ("MHBVQ", "MHBVV", "MHBVG")
        if re.search(r"genotip|resistencia", t):
            return g
        if re.search(r"carga viral|cuantitativ|cuantificacion|\bvl\b|viral load", t):
            return v
        if re.search(r"cualitativ|\bqual", t):
            return q
        return code
    for parent, lab, poc in (("MFLUA", "MFLUL", "MFLUP"), ("MRSVZ", "MRSVL", "MRSVP"),
                             ("MADNZ", "MADNL", "MADNP"), ("MCOVD", "MCOVL", "MCOVP")):
        if code == parent:
            return poc if mol_poc else lab
    if code == "PCOVD":
        b = norm(buyer)
        if NONHC.search(b):
            return "PCOVN"
        if PRIMARY.search(b) or re.search(r"unidad(es)? de salud|primer nivel", t):
            return "PCOVC"
        if HOSPITAL.search(b) or re.search(r"hospital", t):
            return "PCOVH"
        return code
    if code == "DBSPU":
        b = norm(buyer)
        if PATIENT.search(t):
            return "DBSPU"
        if WARD.search(t) or (re.search(r"^hospital|\bhospital\b", b) and not re.search(r"isss|ihss|seguro social|seguridad social", b)):
            return "HGNZZ"
        return "DBSPU"
    return code


def gate_ok(gate, t, unspsc, item_text):
    diag_code = bool(DIAG_UNSPSC.search(unspsc or ""))
    drug_code = (unspsc or "").startswith("51")
    if gate is None:
        return True
    if gate == "R":
        return (diag_code or REAGENT.search(t)) and not drug_code and not (DRUG.search(item_text) and not diag_code)
    if gate == "S":
        strong = re.search(r"reactiv|\bkits?\b|determinaci|prueba|ensayo|calibrador|\bcontrol(es)?\b|elisa|\bclia\b|quimiolumin|"
                           r"cuantificaci|cartucho|test\b|inmunoensayo|para analizador|para equipo|\bpruebas\b|\bdet\b", t)
        return (diag_code or strong) and not drug_code and not DRUG.search(item_text)
    if gate == "RAPID":
        return bool(RAPID.search(t)) and not MOLEC.search(t) and not LABIA.search(t)
    if gate == "RAPIDCRP":
        return bool(re.search(r"prueba rapida|rapida|semicuantitativ|cualitativ|punto de atencion|quikread|nycocard|ichroma|afinion", t)) \
            and not MOLEC.search(t) and not re.search(r"turbidim|para analizador|cuantitativa|ultrasensible", t)
    if gate == "CHEM":
        strong = re.search(r"reactiv|enzimatic|colorimetr|cinetic|determinaci|para (el )?(analizador|equipo)|calibrador|liquicolor|monoreactivo|bireactivo"
                           r"|\bmetodo\b|\buv\b|test (de|para)|\bkits? (de|para) (glucosa|urea|creatinina|colesterol|trigli|acido urico|bilirrub|transamin"
                           r"|proteinas|albumina|calcio|fosforo|magnesio|amilasa|lipasa|hierro|ldh|cpk|fosfatasa)|\bdet\b|\bcontrol(es)? (normal|patolog|nivel)", t)
        industrial = re.search(r"\bsacos?\b|\blibras?\b|\blbs?\b|granulado|\bcas\b|n. ?cas|bidon|piscina|tratamiento de agua|detergente|desinfectante"
                               r"|limpieza|soda ash|carbonato de sodio|sulfato de (aluminio|sodio)|hidroxido|grado reactivo|para analisis\b|\bp\.a\.|hach\b"
                               r"|perlas|\bar\b|alumbre|\bacs\b|grado analitico|xilol|xileno|metanol|alcohol metilico|acetona|acido (clorhidrico|sulfurico|nitrico|acetico)", t)
        real = diag_code and not str(unspsc).endswith("P")
        return (real or strong) and not industrial and not drug_code and not DRUG.search(item_text)
    if gate == "MOL":
        return bool(MOLEC.search(t))
    if gate == "HPV":
        return bool(MOLEC.search(t) or re.search(r"tamizaje|deteccion|prueba|genotip|alto riesgo", t))
    return True


def tag(item="", title="", buyer="", unspsc="", contract_text="", lab_context=False):
    """Return dict or None. `item` drives the segment when present; `title` is context.
    lab_context=True: the line comes from a lab/diagnostics tender (gates treat it as a diagnostic
    class), but a title-only fallback still needs a real UNSPSC class or an IVD word in the item."""
    real_diag = bool(DIAG_UNSPSC.search(unspsc or ""))
    if lab_context and not unspsc:
        unspsc = "41116010P"  # "P" = inferred from the tender, not a published class
    ti, tt = norm(item), norm(title)
    t = ti if ti.strip() else tt
    ctx = (ti + " | " + tt).strip(" |")
    if EXCLUDE.search(t) and not real_diag:
        return None
    if ti.strip() and re.match(r"^\W*(se solicita:?\s*)?(\d[\d,.]*\s*[a-z.]*\s*(de\s+)?)?(papel )?(parafilm|plastilina)", ti):
        return None
    # Reagent-grade lab chemicals: only histology fixatives/clearing agents for pathology count (TDPRE)
    if ti.strip() and re.search(r"grado (reactivo|analitico)|\bacs\b|\bar\b|reactivo acs|cristal ar|perlas", ti):
        if re.search(r"xilol|xileno|formol|formalina|parafina|alcohol (etilico|absoluto)", ti) and re.search(r"patolog|histolog|citolog", ctx):
            return {"code": "TDPRE", "codes": "TDPRE", "confidence": "Medium", "basis": "item", "contract_type": ""}
        return None
    if ti.strip():
        diag = bool(DIAG_UNSPSC.search(unspsc or ""))
        if not STRONG_IVD.search(ti) and (EXCLUDE_ITEM.search(ti) or not diag):
            return None
        if re.search(r"aduan|adauan|desad|dead?uan|almacenaje|parafina terap|subsidio|bibliografia|\blibros?\b|talonario|boletas?\b|papel quimico|papel parafina|formularios?\b|\bflete|kits? de (alimentos|tratamiento)|tratamiento (para|del?) covid|pasajes?\b|boletos?\b|viatico|hospedaje"
                     r"|\bvuelo|etiquetas?\b|espatula|parafina terapeut|cloruro de sodio en polvo", ti):
            return None
        # General lab equipment named first (autoclave "for culture media" is still an autoclave)
        if re.match(r"^\W*(\d+[\s.,]*(c/u|unidad(es)?|und|u)?\s*(de\s+)?)?(autoclave|microscopio|balanza|refrigerad|congelador|bano maria|destilador|horno|estufa"
                    r"|agitador|termometro|incubadora(?!.*(tarjeta|gel|hemocult))|centrifuga(?!.*(banco de sangre|gel|tarjeta|serolog))"
                    r"|\*?tubos?\b|laminas|portaobjetos|cubreobjetos|pipetas?|micropipetas?|puntas|gradillas?|frascos? (recolector|esteril|plastic)|vasos)", ti):
            return None
    if not ti.strip():
        # Title-only line: must look like a lab / diagnostics purchase
        if not LABCUE.search(tt) or (MEDS_ONLY.search(tt) and not re.search(r"reactiv|insumos de laboratorio|pruebas? rapidas?", tt)):
            return None
    if (unspsc or "").startswith("51") and not re.search(r"reactiv|prueba|kit|test", t):
        return None
    hits = []
    for code, rx, gate in RULES:
        if rx.search(t) and gate_ok(gate, ctx if gate in ("RAPID", "RAPIDCRP", "MOL") else t, unspsc, ti or tt):
            hits.append(code)
    if not hits and ti and tt and (real_diag or STRONG_IVD.search(ti)):
        # Item text too terse (e.g. a brand code): fall back to the tender title for parents only
        for code, rx, gate in RULES:
            if code in GENERIC and rx.search(tt):
                hits.append(code)
    if not hits:
        return None
    hits = list(dict.fromkeys(hits))
    # PCR disambiguation: molecular vs C-reactive protein
    if "IACRP" in hits or "PCCRP" in hits:
        if MOLEC.search(t) and not PCR_CRP.search(t):
            hits = [h for h in hits if h not in ("IACRP", "PCCRP")]
        elif "PCCRP" in hits:
            hits = [h for h in hits if h != "IACRP"]
    # Rapid version beats the lab version of the same analyte; molecular beats both
    pairs = [("PHIVS", "IAHIV"), ("PSYPH", "IASTI"), ("PHBVZ", "IAHBV"), ("PHCVZ", "IAHCV"), ("PDENG", "IADEN"),
             ("PCOVD", "IACOV"), ("PCART", "IATRO"), ("PCARP", "IABNN"), ("PCABN", "IABPP"), ("PCPCT", "IAPCT"),
             ("PDOAB", "CCDOA"), ("PHCGT", "IAFER"), ("PVBDX", "IAIOT"), ("PHAVZ", "IAIOT"), ("PGASZ", "IAIOT"),
             ("POTXX", "TORCH"), ("POTXX", "IAIOT"), ("PCTNZ", "IASTI"), ("PRESX", "IAIOT"), ("PCARX", "IACOT"),
             ("PCARX", "CCROU"), ("PMALA", "IAIOT")]
    pairs += [("PGASZ", "POTXX")]
    for keep, drop in pairs:
        if keep in hits and drop in hits:
            hits.remove(drop)
    mol = [h for h in hits if SEG[h].startswith("3.")]
    if mol:
        hits = [h for h in hits if SEG[h].startswith("3.") or not (SEG[h].startswith("1.2.") or SEG[h].startswith("2.")) or h in ("IAINS",)]
        if any(SEG[h].startswith("3.") and h not in ("MDXZZ", "MLDTZ", "MDXIZ") for h in hits):
            hits = [h for h in hits if h not in ("MDXZZ",)]
    # Blood-bank screening context
    if BLOODBANK.search(ctx + " " + norm(buyer)) and any(h in hits for h in ("IAHIV", "IAHBV", "IAHCV", "IASTI", "IAIOT", "IAINF")):
        hits = [h for h in hits if h not in ("IAHIV", "IAHBV", "IAHCV", "IASTI", "IAIOT", "IAINF")] + ["IABSC"]
    if any(h in hits for h in ("NATZZ",)) and any(SEG[h].startswith("3.6") for h in hits):
        hits = [h for h in hits if not SEG[h].startswith("3.6")]
    # Histopathology lists: stain words (Gram, Giemsa, amonio...) belong to tissue staining, not micro / chemistry
    if any(SEG[h].startswith("4") for h in hits) and re.search(r"histo|patolog|tincion(es)? especial|microtomo|parafina|hematoxilina|inmunohisto|citolog", t):
        hits = [h for h in hits if SEG[h].startswith("4")]
    # HbA1c is not routine glucose
    if "CCHBA" in hits and "CCROU" in hits:
        hits.remove("CCROU")
    # Strips: glucose vs urine
    if "DBSPU" in hits and "URQUA" in hits:
        if re.search(r"orina|uroanalisis|urianalisis|parametros|nitrito|leucocit|urobilin", t):
            hits.remove("DBSPU")
        else:
            hits.remove("URQUA")
    if "DBSPU" in hits and "CCROU" in hits:
        hits.remove("CCROU")
    # Analyser lent on comodato alongside reagents/tests: the purchase is the reagents
    INSTR = ("CCSAI", "CCIAS", "IAINS", "HMISR", "COISR", "URISR", "IHISR", "MDXIZ", "ADSTI", "HNEIZ", "TDXSI")
    if re.search(r"comodato|se ofrece (instalar|equipo)|equipo en prestamo", t) and any(h not in INSTR for h in hits):
        hits = [h for h in hits if h not in INSTR]
    if "AIDST" in hits and "MIDCL" in hits and re.search(r"automatiz|para equipo", t):
        hits.remove("MIDCL")
    if "CCHEM" in hits and any(SEG[h].startswith("1.8.") for h in hits):
        hits.remove("CCHEM")
    if "IABSC" in hits and "IMMHM" in hits:
        hits.remove("IMMHM")
    if "FLOWC" in hits and re.search(r"citometr", t):
        hits = [h for h in hits if not SEG[h].startswith("4")]
    if "ABDCL" in hits and "MIDCL" in hits and re.search(r"hemocultivo", t):
        hits.remove("MIDCL")
    if "CDXZZ" in hits and any(h in hits for h in ("MDXZZ", "SEQZZ", "TDXZZ")):
        hits.remove("CDXZZ")
    if "MIDCL" in hits and any(SEG[h].startswith("3.6.4.4") for h in hits) and re.search(r"virus|viral", t):
        hits.remove("MIDCL")
    if "POCCZ" in hits and "DBLPU" in hits:
        hits.remove("DBLPU")
    if "MDXIZ" in hits and "CCSAI" in hits:
        hits.remove("CCSAI")
    if "POCCZ" in hits and "CCROU" in hits:
        hits.remove("CCROU")
    if "BGEZZ" in hits and "CCROU" in hits:
        hits.remove("CCROU")
    if "COTRA" in hits and "PCOAG" in hits:
        hits.remove("COTRA")
    if "IMGLO" in hits and "BGNTZ" in hits and not re.search(r"anti ?-?(a|b|d|ab)\b", t):
        hits.remove("BGNTZ")
    # Specific hits make generic parents redundant
    # A generic parent is redundant only when a more specific hit sits underneath it; a generic
    # top-level root ("pruebas de laboratorio", "prueba rapida") is dropped when anything specific exists
    hits = [h for h in hits if not (h in GENERIC and any(o != h and is_anc(h, o) for o in hits))]
    if any(h not in GENERIC for h in hits):
        hits = [h for h in hits if not (h in GENERIC and depth(h) == 1)]
    hits = [refine(h, ctx, buyer) for h in hits]
    hits = list(dict.fromkeys(hits))
    hits = [h for h in hits if not any(is_anc(h, o) for o in hits if o != h)]
    conf = "High"
    if len(hits) == 1:
        code = hits[0]
    else:
        code = lca(hits)
        conf = "Medium"
        if code is None:  # spans top-level segments
            code = sorted(hits, key=lambda c: (-depth(c), c))[0]
            conf = "Low"
    if HAS_CHILD.get(code) and conf == "High":
        conf = "Medium"
    basis = "item" if ti.strip() else "title"
    return {"code": code, "codes": ";".join(sorted(hits)), "confidence": conf, "basis": basis,
            "contract_type": ", ".join(sorted(set(m.group(0) for m in CONTRACT_WORDS.finditer(ctx))))}


if __name__ == "__main__":
    tests = [
        ("Reactivo PCR latex", "", "Hospital Escuela", "41116004"),
        ("Prueba rapida VIH 1/2 cassette", "", "Region de Salud", "41116010"),
        ("KIT RT-PCR SARS-COV-2 tiempo real", "", "Laboratorio Nacional", ""),
        ("Tiras reactivas para glucometro", "", "Hospital Mario Catarino Rivas", "41116004"),
        ("Tiras reactivas para orina 10 parametros", "", "Hospital", "41116004"),
        ("Insulina NPH 100 UI/ml frasco", "", "SESAL", "51183603"),
        ("Glucosa enzimatica reactivo 4x125 ml", "", "Hospital", "41116004"),
        ("Antisuero anti A", "", "Hospital", "41116002"),
        ("Hematoxilina de Harris 1 litro", "", "Hospital Escuela", ""),
        ("Cartuchos Xpert MTB/RIF", "", "SESAL", ""),
        ("Suministro de reactivos de hematologia y quimica clinica con equipo en comodato", "", "ISSS", ""),
        ("Prueba rapida de antigeno COVID-19", "", "Hospital Rosales", ""),
        ("Dextrosa al 5% solucion inyectable", "", "Hospital", "51191905"),
        ("Hemoglobina glicosilada HbA1c Afinion cartucho", "", "Hospital", ""),
        ("Agar sangre deshidratado 500 g", "", "Hospital", "41116011"),
        ("Lancetas esteriles", "", "Hospital", "41104102"),
    ]
    for a in tests:
        print(a[0][:60].ljust(62), tag(*a))

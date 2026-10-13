"""
TURMECA vocabulary layer (English + Turkish + Arabic) in front of the VN keyword/fuzzy matcher.

Product Category / Sub-OU / OU come from the LINE ITEM text only (rule hit = precision-first).
Company comes from the MANUFACTURER text only (alias table, then exact taxonomy name, then a
strict fuzzy match) - never from the distributor/supplier.
Family = a taxonomy family of that Company + Product Category whose distinctive tokens appear in
model / catalogue / description text.

All values returned are exact strings from Mapping_Taxonomy.xlsx (asserted at load).
"""
from __future__ import annotations

import re
import unicodedata
from collections import defaultdict

import openpyxl
from rapidfuzz import fuzz, process

TAX_PATH = r"<DOWNLOADS>/Mapping_Taxonomy.xlsx"

ACM = "Acute Care & Monitoring"; CVS = "CardioVascular Surgery"; CST = "Cranial and Spinal Technologies"
ENT = "Ear Nose Throat"; EPT = "Electrophysiology Therapies (EPT)"; ENDO = "Endoscopy"
ICT = "Interventional Cardiology Therapies (ICT)"; NM = "Neuromodulation"; NV = "Neurovascular"
PH = "Pelvic Health"; PVH = "Peripheral Vascular Health"; SI = "Surgical Innovations"; SR = "Surgical Robotics"

_TR = str.maketrans({"ı": "i", "İ": "i", "ş": "s", "Ş": "s", "ğ": "g", "Ğ": "g", "ç": "c", "Ç": "c", "ö": "o", "Ö": "o", "ü": "u", "Ü": "u"})
_AR = str.maketrans({"أ": "ا", "إ": "ا", "آ": "ا", "ة": "ه", "ى": "ي"})


def fold(s) -> str:
    """lower-case; Turkish letters -> ASCII; Arabic alef/ta-marbuta normalised; punctuation -> space."""
    if s is None:
        return ""
    s = str(s).translate(_TR).translate(_AR).lower()
    s = "".join(ch for ch in unicodedata.normalize("NFKD", s) if not unicodedata.combining(ch))
    s = re.sub(r"[^\w\u0600-\u06ff&+/.-]+", " ", s)
    return " " + re.sub(r"\s+", " ", s).strip() + " "


def A(*terms):
    """Order-independent AND: every term must appear somewhere (tender text often reads 'THING, FOR THERAPY')."""
    # anchored at ^ : unanchored lookaheads are retried from every position (quadratic on long tender texts)
    return "^" + "".join(f"(?=.*(?:{t}))" for t in terms)


# Order-independent rules for wording seen in NUPCO lists; evaluated BEFORE the main list R.
R0 = [
    # Neuromodulation - DBS
    (NM, "Neuromodulation - Brain Modulation", "DBS - Extensions", [A(r"\bextension", r"deep brain|\bdbs\b")], []),
    (NM, "Neuromodulation - Brain Modulation", "DBS - Recharger", [A(r"recharg\w* (system|unit|device)|recharger", r"deep brain|\bdbs\b")], []),
    (NM, "Neuromodulation - Brain Modulation", "DBS - Programmer", [A(r"programmer|patient controller", r"deep brain|\bdbs\b")], []),
    (NM, "Neuromodulation - Brain Modulation", "DBS - Accessories", [A(r"trial cable|tunnel+ers?|burr hole|external pulse generator|for testing|anchor", r"deep brain|\bdbs\b")], []),
    (NM, "Neuromodulation - Brain Modulation", "DBS - Neurostimulator (Rechargeable)", [A(r"pulse generator|neurostimulator|\bipg\b", r"(?<!non )rechargeable", r"deep brain|\bdbs\b")], [r"non[- ]?rechargeable|external|testing"]),
    (NM, "Neuromodulation - Brain Modulation", "DBS - Neurostimulator (Non-rechargeable)", [A(r"pulse generator|neurostimulator|\bipg\b", r"deep brain|\bdbs\b")], [r"(?<!non )(?<!non-)rechargeable|external|testing"]),
    (NM, "Neuromodulation - Brain Modulation", "DBS - Leads", [A(r"\bleads?\b", r"deep brain|\bdbs\b")], [r"extension|trial"]),
    # Neuromodulation - SCS
    (NM, "Neuromodulation - Pain", "SCS Extensions", [A(r"\bextension", r"spinal cord stim|\bscs\b")], []),
    (NM, "Neuromodulation - Pain", "SCS Trial System - External Neurostimulator", [A(r"external pulse generator|for testing|trial (stimulator|system)", r"spinal cord stim|\bscs\b")], []),
    (NM, "Neuromodulation - Pain", "SCS Rechargeable", [A(r"pulse generator|neurostimulator|\bipg\b", r"(?<!non )rechargeable", r"spinal cord stim|\bscs\b")], [r"non[- ]?rechargeable|external|testing"]),
    (NM, "Neuromodulation - Pain", "SCS Non rechargeable", [A(r"pulse generator|neurostimulator|\bipg\b", r"spinal cord stim|\bscs\b")], [r"(?<!non )(?<!non-)rechargeable|external|testing"]),
    (NM, "Neuromodulation - Pain", "SCS Recharger", [A(r"recharg\w* (system|unit|device)|recharger", r"spinal cord stim|\bscs\b")], [r"deep brain"]),
    # ACM monitoring wording 'MONITOR CEREBRAL OXIMETRY', 'SENSOR ... RELATED TO MONITOR ...'
    (ACM, "Cerebral Compromise", "Sensors, NIRS", [A(r"\bsensors?\b", r"cerebral oximet|regional oximet|\bnirs\b|\binvos\b")], []),
    (ACM, "Cerebral Compromise", "Monitors, NIRS", [A(r"\bmonitor\b", r"cerebral oximet|regional oximet|\bnirs\b|\binvos\b")], [r"related to|sensor|cable|stand|docking"]),
    (ACM, "Cerebral Compromise", "Sensors, LoC", [A(r"\bsensors?\b", r"\bbis\b|bispectral")], []),
    (ACM, "Cerebral Compromise", "Monitors, LoC", [A(r"\bmonitor\b|\bmodule\b", r"\bbis\b|bispectral")], [r"related to|sensor|cable"]),
    (ACM, "Respiratory Compromise", "Consumable CO2 (Disposable)", [A(r"sample line|sampling line|filter ?line|nasal cannula|airway adapter", r"capnograph|\bco2\b|etco2|microstream")], []),
    # vascular / navigation
    (PVH, "Peripheral Vascular", "Carotid SX Stent", [A(r"\bstent\b", r"\bcarotid\b|karotis|karotid")], [r"covered|graft"]),
    (CST, "Large Capital", "Core Navigation - Disposables", [r"\bnavigated (biopsy|shunt|needle|stylet|probe|pointer)", A(r"navigat", r"(biopsy|shunt placement) needle")], []),
    (CST, "Large Capital", "Imaging Devices - Capital", [A(r"imaging system|radiography|\bct\b", r"intra ?operative", r"\b(2d ?/ ?3d|3d)\b")], [r"related to"]),
    # capital systems written 'DRILL SYSTEM NEURO ELECTRICAL', 'NAVIGATION SYSTEM ENT' + their RELATED TO lines
    (CST, "Small Capital", "Powered Surgical Instruments - Disposable", [A(r"\bburr?s?\b|\bblades?\b|\bbits?\b|attachment tip", r"drill system (neuro|spine|cranial)")], []),
    (CST, "Small Capital", "Powered Surgical Instruments - Capital", [r"^ drill system (neuro|spine|cranial)\w* electric", r"related to drill system (neuro|spine|cranial)"], [r"training"]),
    (ENT, "ENT", "ENT Drills - Disposables", [A(r"\bburr?s?\b|\bbits?\b", r"drill system ent|drill otology")], []),
    (ENT, "ENT", "ENT Drills - Capital", [r"^ drill system ent\w* electric", r"related to drill system ent"], [r"training"]),
    (ENT, "ENT", "ENT Microdebriders - Blade Disposables", [A(r"\bblades?\b", r"ent debrider|microdebrider")], []),
    (ENT, "ENT", "ENT Microdebriders - Capital Equipment", [r"^ advanced ent debrider", r"related to advanced ent debrider"], [r"training|\bburr?s?\b"]),
    (ENT, "ENT", "Core Navigation - Disposables", [A(r"disposable|sterile|single use|marker|tracker", r"navigation system ent")], []),
    (ENT, "ENT", "Core Navigation - Capital", [r"^ navigation system ent", r"related to navigation system ent"], [r"training"]),
    (CST, "Large Capital", "Core Navigation - Disposables", [A(r"disposable|sterile|single use|marker|sphere|tracker", r"navigation system (neuro|spine|cranial)")], []),
    (CST, "Large Capital", "Core Navigation - Capital", [r"^ navigation system (neuro|spine|cranial)", r"related to navigation system (neuro|spine|cranial)"], [r"training"]),
    (SI, "Hardware - COT", "HW - Advanced", [r"^ electrosurgical unit (bipolar|monopolar|vessel)", r"(vessel sealing|tissue fusion)( and vessel sealing)? (system|generator|unit)"], [r"related to"]),
    (ACM, "Airway Management", "Airway Access - Consumables", [A(r"\bblades?\b", r"laryngoscope video|video ?laryngoscope")], []),
    (ACM, "Airway Management", "Airway Access", [r"^ laryngoscope video", r"related to laryngoscope video"], [r"training"]),
    (ENDO, "GI - Esophageal", "Motility System - Disposables", [r"\bpill capsule smart\b|\bsmartpill\b|wireless motility capsule"], []),
    (CST, "Small Capital", "Nerve Monitoring Devices - Capital", [r"^ monitor nerve integr", r"nerve integrity monitor"], [r"related to"]),
    (CST, "Small Capital", "Nerve Monitoring Devices - Disposable", [A(r"electrode|probe|sensor|tube", r"monitor nerve integr")], []),
    (CST, "Small Capital", "Nerve Monitoring Devices - Disposable", [A(r"endotracheal", r"nerve (stimulation|monitoring)|\bemg\b|electrodes")], []),
    (ACM, "Airway Management", "Endotracheal Tubes", [A(r"\btubes?\b", r"endotracheal")], [r"related to|holder|stylet|exchanger|introducer"]),
    (ACM, "Respiratory Compromise", "Sensors, Reusable", [A(r"pulse oximet\w* sensor|spo2 sensor", r"reusable|continu")], [r"disposable"]),
    (ACM, "Respiratory Compromise", "Bedside Monitors, Pulse Oximeter", [r"^ oximeter pulse (desktop|bedside|tabletop)"], []),
    # cath lab wording 'THING, FOR USE'
    (ICT, "PCI Non Stents", "Guide Extension Catheters", [A(r"extension", r"guide catheter|guiding catheter")], []),
    (ICT, "PCI Stents", "DES", [A(r"\bstents?\b", r"\bcoronary\b", r"drug[- ]eluting|sirolimus|everolimus|zotarolimus")], [r"balloon|peripheral"]),
    (EPT, "Defibrillation Solutions", "Absorbable Antibacterial Envelope", [r"anti(microbial|bacterial) envelop"], []),
    (EPT, "Defibrillation Solutions", "EV ICD / SubQ", [A(r"subcutaneous|extravascular", r"defibrillator|\bicd\b")], []),
    (EPT, "Cardiac Pacing Therapies", "IPG DC", [A(r"\bpacemaker\b", r"\bdual\b")], [r"leadless|external|temporary|crt|resynchron"]),
    (EPT, "Cardiac Pacing Therapies", "IPG SC", [A(r"\bpacemaker\b", r"\bsingle\b")], [r"leadless|external|temporary|crt|resynchron|dual"]),
    (EPT, "Cardiac Pacing Therapies", "Leads", [A(r"\bleads?\b", r"cardiac electrophysiology|pacing|pacemaker|epicardial|endocardial")], [r"delivery|extension|ecg|temporary"]),
    (EPT, "Patient Management", "Remote Monitoring Services", [A(r"home monitoring|remote monitoring", r"cardiac|pacemaker|\bicd\b|electrophysiology")], []),
    (CVS, "Aortic", "TEVAR Thoracic Stent Grafts", [A(r"stent", r"aortic dissection|thoracic aort")], [r"abdominal"]),
    (CVS, "Aortic", "EVAR Abdominal Stent Grafts", [A(r"stent[- ]?graft|endograft", r"abdominal|aorto|iliac")], []),
    (CVS, "Aortic", "Introducer Sheath", [A(r"introducer sheath", r"aortic|aneurysm|evar|tevar")], []),
    (CVS, "Aortic", "Balloon Catheter / Stent Graft Balloon Catheter", [A(r"occlusion balloon|molding balloon|moulding balloon", r"\baort")], []),
    (PVH, "Peripheral Vascular", "Guidewires", [A(r"guide ?wire", r"peripheral")], [r"coronary|neuro"]),
    (PVH, "Peripheral Vascular", "Infusion Catheter", [A(r"infusion catheter", r"infusion length|thromboly|peripheral")], []),
    (PVH, "Peripheral Vascular", "Drug Coated Balloons", [A(r"balloon", r"drug[- ](eluting|coated)|paclitaxel", r"fistula|peripheral|femoral|popliteal|below the knee|\bbtk\b|\bsfa\b")], [r"coronary"]),
    (PVH, "EndoVenous", "Venous Stents", [A(r"\bstents?\b", r"\bvenous\b|\bvein\b")], [r"covered|graft"]),
    (ENDO, "GI - Hepatopancreatobiliary (HPB)", "Ablation Microwave - Disposable", [A(r"microwave", r"ablation", r"probe|antenna|needle")], []),
    (NV, "Acute Ischemic Stroke", "Access Products - Micro Catheters", [A(r"micro ?catheter", r"revasculari|stent retriever|thrombectomy|clot")], []),
    # robotic surgery platform (NUPCO 'ROBOTIC SURGERY MODULAR' + its RELATED TO lines)
    (SR, "Robotic Surgical Technologies", "System", [r"^ robotic surgery (modular|system)\b(?!.*related to)"], []),
    (SR, "Robotic Surgical Technologies", "Robotic Surgery Accessories - Sterile Drapes", [A(r"\bdrapes?\b", r"related to robotic surgery")], []),
    (SR, "Robotic Surgical Technologies", "System", [A(r"console|tower|bed side unit|robotic arm|camera head|recorder|glasses", r"related to robotic surgery (modular|system)")], [r"training|simulator"]),
    (SR, "Robotic Surgical Technologies", "Robotic Surgery Accessories", [r"related to robotic surgery (modular|system)"], [r"training|simulator"]),
]

# (OU, Sub-OU, Product Category, [include regexes], [exclude regexes])
# Regexes run on fold(text) -> lower-case ASCII Turkish, padded with spaces. \b works for EN/TR.
R = [
    # ---------------- Interventional Cardiology Therapies
    (ICT, "PCI Stents", "DES", [r"\bdrug[- ]?eluting (coronary )?stent", r"\bcoronary\b.*\bstent\b.*\b(sirolimus|everolimus|zotarolimus|biolimus|drug)", r"\bdes\b.*\bcoronary",
                                 r"ilac (salinimli|salan|kapli) (koroner )?stent", r"koroner stent", r"دعامه (تاجيه|الشريان التاجي)"],
     [r"peripheral|periferik|biliary|safra|ureter|esophag|ozofag|tracheal|carotid|renal|iliac|femoral|venous|aort"]),
    (ICT, "PCI Non Stents", "Drug Coated Balloons", [r"\b(drug|paclitaxel|sirolimus)[- ]coated (coronary )?balloon.*\b(coronary|ptca)", r"\bcoronary\b.*\bdrug[- ]coated balloon", r"koroner.*ilac kapli balon", r"ilac kapli koroner balon"], [r"peripheral|periferik"]),
    (ICT, "PCI Non Stents", "PTCA Balloons", [r"\bptca\b", r"\bcoronary (dilatation|angioplasty|balloon)", r"\bballoon\b.*\bcoronary\b", r"\bnc balloon\b.*coronary", r"koroner (anjiyoplasti |dilatasyon )?balon", r"balon kateter.*koroner"], [r"peripheral|periferik|drug[- ]coated|ilac kapli|guide ?wire|kilavuz tel|inflation|indeflator|syringe"]),
    (ICT, "PCI Non Stents", "Guide Extension Catheters", [r"guide (extension|extender) catheter", r"guide catheter extension", r"kilavuz uzatma"], []),
    (ICT, "PCI Non Stents", "Guiding Catheters", [r"\bguiding catheter\b.*\b(coronary|cardiac|judkins|amplatz|ebu|xb)\b", r"\bcoronary guiding catheter", r"koroner kilavuz kateter", r"kilavuz kateter.*koroner"], [r"neuro|noro|balloon guide|peripheral"]),
    (ICT, "Catheter Based Therapy", "TCV Aortic", [r"\btavi\b", r"\btavr\b", r"transcatheter aortic valve", r"transkateter aort", r"perkutan aort kapak"], []),
    (ICT, "Catheter Based Therapy", "TEER Mitral", [r"\bteer\b", r"mitral (valve )?(clip|repair system)", r"\bmitraclip\b", r"edge[- ]to[- ]edge", r"mitral klip"], []),
    (ICT, "Catheter Based Therapy", "TCV Pulmonary", [r"transcatheter pulmon", r"\bmelody\b.*valve", r"perkutan pulmoner kapak"], []),
    (ICT, "Renal Denervation (RDN)", "Ablation Catheter", [r"renal denervation", r"renal denervasyon"], []),
    # ---------------- Electrophysiology Therapies
    (EPT, "Defibrillation Solutions", "CRT-D", [r"\bcrt[- ]?d\b", r"(cardiac )?resynchroni[sz]ation.*defibrillat", r"resenkronizasyon.*defibrilat"], []),
    (EPT, "Defibrillation Solutions", "EV ICD / SubQ", [r"subcutaneous (icd|implantable cardioverter|defibrillator)", r"\bs[- ]icd\b", r"extravascular icd", r"subkutan (icd|defibrilat)"], []),
    (EPT, "Defibrillation Solutions", "ICD - DR", [r"\bicd\b.*\bdual chamber", r"dual chamber.*\b(icd|cardioverter|defibrillator)", r"implantable cardioverter.*dual", r"cift odacikli.*(icd|defibrilat)", r"(icd|defibrilat).*cift odacik"], [r"\bcrt"]),
    (EPT, "Defibrillation Solutions", "ICD - VR", [r"\bicd\b.*\bsingle chamber", r"single chamber.*\b(icd|cardioverter|defibrillator)", r"implantable cardioverter.*single", r"tek odacikli.*(icd|defibrilat)", r"(icd|defibrilat).*tek odacik"], [r"\bcrt"]),
    (EPT, "Defibrillation Solutions", "Absorbable Antibacterial Envelope", [r"antibacterial envelope", r"\btyrx\b", r"antibakteriyel (zarf|kilif)"], []),
    (EPT, "Cardiac Pacing Therapies", "CRT-P", [r"\bcrt[- ]?p\b", r"resynchroni[sz]ation pacemaker", r"biventricular pace", r"resenkronizasyon (pili|pacemaker)"], []),
    (EPT, "Cardiac Pacing Therapies", "Leadless Pacemaker", [r"leadless pace", r"\bmicra\b", r"\baveir\b", r"kablosuz (kalp )?pil", r"leadless"], []),
    (EPT, "Cardiac Pacing Therapies", "IPG DC", [r"pacemaker\b.*\bdual chamber", r"dual chamber\b.*\bpacemaker", r"\b(ddd|dddr)\b.*pace", r"cift odacikli.*(kalp pili|pacemaker)", r"(kalp pili|pacemaker).*cift odacik"], [r"external|temporary|gecici|harici|\bcrt"]),
    (EPT, "Cardiac Pacing Therapies", "IPG SC", [r"pacemaker\b.*\bsingle chamber", r"single chamber\b.*\bpacemaker", r"\b(vvi|vvir)\b.*pace", r"tek odacikli.*(kalp pili|pacemaker)", r"(kalp pili|pacemaker).*tek odacik"], [r"external|temporary|gecici|harici"]),
    (EPT, "Cardiac Pacing Therapies", "External IPGs", [r"(external|temporary) (cardiac )?pace(maker|r)\b", r"(harici|gecici) (kalp )?pil"], []),
    (EPT, "Cardiac Pacing Therapies", "Leads", [r"pacing lead", r"pacemaker lead", r"(endocardial|bipolar).*lead.*pac", r"kalp pili (elektrodu|lead)", r"pace elektrod"], [r"temporary|gecici|ecg|ekg|eeg"]),
    (EPT, "Cardiovascular Diagnostics and Services", "Insertable Cardiac Monitor", [r"insertable cardiac monitor", r"implantable (loop recorder|cardiac monitor)", r"\bloop recorder\b", r"\bicm\b.*cardiac", r"implante edilebilir.*(kardiyak monit|ritim)", r"loop kaydedici"], []),
    (EPT, "CAS - Cryo", "Cryoballoon Ablation Catheter", [r"cryo ?balloon", r"kriyo ?balon"], []),
    (EPT, "CAS - Cryo", "Focal Cryoablation Catheter", [r"(focal )?cryo ?ablation catheter", r"kriyoablasyon kateter"], [r"balloon|balon"]),
    (EPT, "CAS - PFA", "PFA - Catheter", [r"pulsed field", r"\bpfa\b", r"pulsatil alan ablasyon"], []),
    (EPT, "CAS - Other", "Conventional RF Focal Ablation Catheter", [r"(cardiac|ep|electrophysiology).*(rf|radiofrequency) ablation catheter", r"ablation catheter.*(irrigated|contact force|cardiac)", r"(kardiyak|elektrofizyoloji).*ablasyon kateter"], [r"renal|venous|varis|tumou?r|liver|thyroid"]),
    (EPT, "CAS - Other", "EP Diagnostics / Recording / Mapping Adjuncts - Diagnostic EP Catheter", [r"diagnostic (ep|electrophysiology) catheter", r"(quadripolar|decapolar|coronary sinus) (diagnostic )?catheter", r"elektrofizyoloji tani kateter", r"tanisal ep kateter"], []),
    (EPT, "CAS - Other", "Transseptal Needles", [r"trans ?septal (access )?(needle|system)", r"transseptal igne"], []),
    (EPT, "CAS - Other", "Long Introducer Sheath", [r"(long|steerable) (introduc\w+|transseptal) sheath", r"transseptal sheath"], []),
    (EPT, "CAS - Other", "Mapping System", [r"(3d|electroanatomic\w*) mapping system", r"elektroanatomik haritalama"], []),
    # ---------------- CardioVascular Surgery
    (CVS, "Aortic", "TEVAR Thoracic Stent Grafts", [r"thoracic (aortic )?(endo)?(stent[- ]?graft|endoprosthesis)", r"\btevar\b", r"torasik (aort )?stent greft"], []),
    (CVS, "Aortic", "EVAR Abdominal Stent Grafts", [r"abdominal (aortic )?(endo)?(stent[- ]?graft|endoprosthesis)", r"\bevar\b", r"endovascular aortic", r"abdominal (aort )?stent greft", r"aort.*stent greft", r"aortic/iliac extension"], [r"thoracic|torasik"]),
    (CVS, "Aortic", "ESAR / HeliFX Endoanchor", [r"endoanchor", r"helifx"], []),
    (CVS, "ECT and Revasc", "Cardiopulmonary/Oxygenators - CPB Oxygenator", [r"\boxygenator\b", r"oksijenator"], [r"ecmo|ecls|extracorporeal life"]),
    (CVS, "ECT and Revasc", "Cardiopulmonary/Oxygenators - ECLS Oxygenator", [r"(ecmo|ecls).*oxygenator", r"oxygenator.*(ecmo|ecls)", r"ecmo.*oksijenator"], []),
    (CVS, "ECT and Revasc", "Cardiopulmonary/Oxygenators - Heart-Lung Machine", [r"heart[- ]lung (machine|bypass unit)", r"kalp akciger makine"], [r"related to|warranty|garanti"]),
    (CVS, "ECT and Revasc", "Cannulae - Arterial", [r"arterial (perfusion )?cannula", r"aortic (perfusion |arch )?cannula", r"arteriyel kanul", r"aortik kanul"], []),
    (CVS, "ECT and Revasc", "Cannulae - Venous", [r"venous (drainage |return )?cannula", r"(two|three)[- ]stage .*cannula", r"venoz kanul"], [r"peripheral iv|intravenous"]),
    (CVS, "ECT and Revasc", "Cannulae - Cardioplegia", [r"cardioplegia (cannula|catheter|needle)", r"kardiyopleji"], []),
    (CVS, "ECT and Revasc", "Cannulae - Femoral", [r"femoral (arterial |venous )?(perfusion )?cannula", r"femoral kanul"], []),
    (CVS, "ECT and Revasc", "Autotransfusion Disposables", [r"autotransfusion", r"cell saver", r"otransfuzyon"], []),
    (CVS, "ECT and Revasc", "Revascularization - Heart Positioners", [r"(heart|cardiac) positioner", r"tissue stabili[sz]er", r"off[- ]pump", r"kalp pozisyon"], []),
    (CVS, "Surgical Ablation & Valve Therapies - Surgical Valve Therapies (SVT)", "Mechanical Heart Valves (Aortic)", [r"mechanical (heart )?valve.*aortic", r"aortic.*mechanical (heart )?valve", r"mekanik kalp kapag\w*.*aort", r"mekanik.*aort kapak"], []),
    (CVS, "Surgical Ablation & Valve Therapies - Surgical Valve Therapies (SVT)", "Mechanical Heart Valves (Mitral)", [r"mechanical (heart )?valve.*mitral", r"mitral.*mechanical (heart )?valve", r"mekanik kalp kapag\w*.*mitral"], []),
    (CVS, "Surgical Ablation & Valve Therapies - Surgical Valve Therapies (SVT)", "Tissue Heart Valves (Aortic)", [r"(tissue|bioprosthe\w+|biological|pericardial|porcine) (heart )?valve.*aortic", r"aortic.*(tissue|bioprosthe\w+|biological) valve", r"biyolojik (kalp )?kapak.*aort"], [r"transcatheter|tavi"]),
    (CVS, "Surgical Ablation & Valve Therapies - Surgical Valve Therapies (SVT)", "Tissue Heart Valves (Mitral)", [r"(tissue|bioprosthe\w+|biological|pericardial|porcine) (heart )?valve.*mitral", r"biyolojik (kalp )?kapak.*mitral"], [r"transcatheter"]),
    (CVS, "Surgical Ablation & Valve Therapies - Surgical Valve Therapies (SVT)", "Annuloplasty Rings/Bands", [r"annuloplasty", r"anuloplasti"], []),
    (CVS, "Surgical Ablation & Valve Therapies - Surgical Ablation (SA)", "Surgical RF Ablation - RF Ablation Device", [r"surgical (rf |radiofrequency )?ablation", r"(bipolar|rf) ablation clamp", r"cerrahi ablasyon"], []),
    (CVS, "Surgical Ablation & Valve Therapies - Surgical Ablation (SA)", "Surgical Cryoablation - Cryo Probe", [r"(cardiac )?surgical cryo ?(ablation )?probe", r"cryoablation probe.*(cardiac|surgical)"], []),
    # ---------------- Peripheral Vascular Health
    (PVH, "Peripheral Vascular", "Drug Coated Balloons", [r"(drug|paclitaxel|sirolimus)[- ]coated (pta |peripheral )?balloon", r"periferik.*ilac kapli balon", r"ilac kapli (periferik )?balon"], [r"coronary|koroner"]),
    (PVH, "Peripheral Vascular", "Drug Eluting Peripheral Stents", [r"drug[- ]eluting (peripheral|femoral|sfa)", r"peripheral.*drug[- ]eluting stent", r"periferik ilac salinimli stent"], []),
    (PVH, "Peripheral Vascular", "Carotid SX Stent", [r"carotid stent", r"karotis stent", r"karotid stent"], []),
    (PVH, "Peripheral Vascular", "Embolic Protection Devices", [r"embolic protection", r"distal protection (device|filter)", r"emboli koruma"], []),
    (PVH, "Peripheral Vascular", "Atherectomy", [r"atherectomy", r"aterektomi"], []),
    (PVH, "Peripheral Vascular", "CTO (Support) Catheters", [r"\bcto\b.*catheter", r"(support|crossing) catheter", r"destek kateter"], [r"coronary|koroner|neuro"]),
    (PVH, "Peripheral Vascular", "Standard PTA Balloons", [r"\bpta\b.*balloon", r"peripheral.*(angioplasty|dilatation) balloon", r"balloon.*peripheral", r"periferik (anjiyoplasti |dilatasyon )?balon", r"\bpta balon"], [r"coronary|koroner|drug|ilac|high pressure"]),
    (PVH, "Peripheral Vascular", "High Pressure PTA Balloons", [r"high[- ]pressure.*(pta|peripheral|dialysis|fistula).*balloon", r"yuksek basincli.*balon"], [r"coronary|koroner"]),
    (PVH, "Peripheral Vascular", "BMS SX Stent", [r"self[- ]expand\w*.*(peripheral|iliac|femoral|sfa|popliteal).*stent", r"(peripheral|iliac|femoral|sfa|popliteal).*self[- ]expand\w*.*stent", r"periferik.*kendiliginden acilan stent", r"periferik stent"], [r"drug|ilac|coronary|koroner|carotid|venous|biliary|safra"]),
    (PVH, "Peripheral Vascular", "BMS BX Stent", [r"balloon[- ]expand\w*.*(peripheral|iliac|renal).*stent", r"(peripheral|iliac|renal).*balloon[- ]expand\w*.*stent", r"balonla acilan.*periferik stent"], [r"drug|ilac|coronary|koroner|covered"]),
    (PVH, "EndoVenous", "Superficial Venous - RFA Catheter", [r"(endovenous|venous|varicose|saphenous).*radiofrequency", r"radiofrequency.*(vein|venous|varicose)", r"closurefast", r"(varis|venoz).*radyofrekans", r"radyofrekans.*(varis|ven)"], []),
    (PVH, "EndoVenous", "Superficial Venous - EVLA", [r"endovenous laser", r"\bevla\b", r"\bevlt\b", r"endovenoz lazer"], []),
    (PVH, "EndoVenous", "Superficial Venous - CAC / Glue Ablation", [r"cyanoacrylate.*(vein|venous)", r"venaseal", r"venous (closure )?(glue|adhesive)", r"siyanoakrilat"], []),
    (PVH, "EndoVenous", "Superficial Venous - MOCA", [r"mechanochemical", r"clarivein", r"flebogrif"], []),
    (PVH, "EndoVenous", "Venous Stents", [r"venous stent", r"venoz stent", r"\bvici\b|\babre\b"], []),
    (PVH, "EndoVenous", "Embolic Coils - Pushable", [r"pushable (embol\w+ )?coil", r"(peripheral|vascular) (embol\w+ )?coil.*push", r"itilebilir koil"], [r"neuro|intracran|aneurysm|anevriz"]),
    (PVH, "EndoVenous", "Embolic Coils - Detachable", [r"(peripheral|vascular).*detachable (embol\w+ )?coil", r"detachable coil.*peripheral"], [r"neuro|intracran"]),
    (PVH, "EndoVenous", "Microvascular Plugs", [r"vascular plug", r"\bmvp\b.*plug", r"vaskuler tikac"], []),
    # ---------------- Neurovascular (micro catheters first: they are often "compatible with" coils/devices)
    (NV, "Hemorrhagic Stroke", "Access Products - Micro Catheters", [r"(neuro\w*|intracranial).*micro ?catheter", r"micro ?catheter.*(neuro|intracranial|aneurysm|embol)", r"(noro|intrakranial).*mikrokateter"], []),
    (NV, "Acute Ischemic Stroke", "Stent Retrievers", [r"stent retriever", r"(clot|thrombus) retriev\w+ (device|stent)", r"\bsolitaire\b|\btrevo\b", r"stent retriver|trombektomi stent"], []),
    (NV, "Acute Ischemic Stroke", "Aspiration Catheters", [r"(neuro|intracranial|stroke).*aspiration catheter", r"aspiration catheter.*(neuro|stroke|intracranial|thrombectomy)", r"(noro|inme).*aspirasyon kateter", r"aspirasyon kateteri.*(inme|trombektomi)"], []),
    (NV, "Acute Ischemic Stroke", "Access Products - Balloon Guide Catheters", [r"balloon guid(e|ing) catheter", r"balon kilavuz kateter"], []),
    (NV, "Acute Ischemic Stroke", "Aspiration Pumps", [r"(neuro|stroke|clot).*aspiration (pump|system)", r"aspiration pump.*(neuro|stroke)"], []),
    (NV, "Hemorrhagic Stroke", "Flow Diverters", [r"flow divert", r"\bpipeline\b.*(embol|flex)", r"akim yonlendirici|akim cevirici|flow diverter"], []),
    (NV, "Hemorrhagic Stroke", "Intrasaccular Devices", [r"intrasaccular", r"\bweb\b.*aneurysm", r"intrasakkuler"], []),
    (NV, "Hemorrhagic Stroke", "INR Embolization Coils", [r"(neuro\w*|intracranial|aneurysm).*(embol\w+ )?coil", r"coil.*(neuro\w*|intracranial|aneurysm)", r"anevrizma koil", r"(noro|intrakranial).*koil"], []),
    (NV, "Hemorrhagic Stroke", "Liquid Embolics", [r"liquid embol", r"\bonyx\b.*(embol|liquid)", r"\bsquid\b|\bphil\b.*embol", r"sivi embol"], []),
    (NV, "Hemorrhagic Stroke", "Accessory Products - Occlusion Balloon Systems", [r"(neuro|remodel\w*|intracranial).*occlusion balloon", r"remodeling balloon"], []),
    # ---------------- Neuromodulation / Pelvic Health
    (NM, "Neuromodulation - Brain Modulation", "DBS - Leads", [r"deep brain stim\w*.*lead", r"\bdbs\b.*lead", r"derin beyin stim\w*.*(elektrot|lead)"], [r"trial cable"]),
    (NM, "Neuromodulation - Brain Modulation", "DBS - Neurostimulator (Rechargeable)", [r"deep brain stim\w*.*rechargeable", r"\bdbs\b.*rechargeable", r"derin beyin.*sarj edilebilir"], [r"non[- ]?rechargeable"]),
    (NM, "Neuromodulation - Brain Modulation", "DBS - Neurostimulator (Non-rechargeable)", [r"deep brain stim\w*.*(neurostimulator|generator|ipg)", r"\bdbs\b.*(neurostimulator|generator|ipg)", r"derin beyin stim\w*.*(jenerator|pil)"], [r"(?<!non[- ])rechargeable"]),
    (NM, "Neuromodulation - Brain Modulation", "DBS - Extensions", [r"(deep brain|dbs).*extension", r"derin beyin.*uzatma"], []),
    (NM, "Neuromodulation - Brain Modulation", "DBS - Accessories", [r"(deep brain|dbs).*(accessor|trial cable|burr hole cover)", r"burr hole (cap|cover).*(lead|dbs)"], []),
    (NM, "Neuromodulation - Pain", "SCS Rechargeable", [r"spinal cord stim\w*.*rechargeable", r"\bscs\b.*rechargeable", r"spinal kord stim\w*.*sarj"], [r"non[- ]?rechargeable"]),
    (NM, "Neuromodulation - Pain", "SCS Non rechargeable", [r"spinal cord stim\w*.*(neurostimulator|generator|ipg)", r"\bscs\b.*(neurostimulator|generator|ipg)", r"spinal kord stim\w*.*(jenerator|pil)", r"spinal kord stimulator"], [r"(?<!non[- ])rechargeable|trial|lead|extension"]),
    (NM, "Neuromodulation - Pain", "SCS Trial System - External Neurostimulator", [r"(spinal cord|scs).*trial", r"trial (stimulator|neurostimulator)"], []),
    (NM, "Neuromodulation - Pain", "SCS Extensions", [r"(spinal cord|scs).*extension"], []),
    (NM, "Neuromodulation - Pain", "TDD Pumps", [r"(implantable|intrathecal) (drug )?(infusion )?pump", r"intratekal (ilac )?pompa", r"implante edilebilir.*pompa"], [r"insulin"]),
    (NM, "Neuromodulation - Pain", "TDD Catheter", [r"intrathecal catheter", r"intratekal kateter"], []),
    (NM, "Neuromodulation - Pain", "OsteoCool Ablation - Standard RF Ablation Probes", [r"(bone|vertebral|spinal) (tumou?r )?(rf|radiofrequency) ablation", r"osteocool", r"kemik.*radyofrekans ablasyon"], []),
    (NM, "Neuromodulation - Pain", "Cooled RFA - RF Ablation Capital System", [r"cooled (rf|radiofrequency)", r"radiofrequency generator.*pain", r"(rf|radiofrequency) generator.*(pain|facet)", r"agri.*radyofrekans jenerator"], []),
    (NM, "Neuromodulation - Pain", "Bone Cement", [r"(vertebro|kypho)plasty.*cement", r"bone cement.*(vertebr|kypho)", r"kifoplasti.*cimento", r"vertebroplasti.*cimento"], []),
    (PH, "Pelvic Health", "Sacral Neuromodulation (SNM) - Implants", [r"sacral (nerve )?(neuro)?(stimulat|modulat)", r"\binterstim\b", r"sakral (sinir )?(stim|noromod)"], [r"evaluation|test|programmer"]),
    (PH, "Pelvic Health", "Sacral Neuromodulation (SNM) - Evaluation Systems", [r"sacral.*(evaluation|test stim\w*|pne)", r"sakral.*(test|deneme)"], []),
    (PH, "Pelvic Health", "Percutaneous Tibial Neuromodulation (PTNM) Systems", [r"tibial nerve stim", r"\bptns\b", r"\bptnm\b", r"tibial sinir stim"], []),
    # ---------------- Cranial & Spinal Technologies
    (CST, "Total Spinal", "Vertebral Augmentation / Balloon Kyphoplasty", [r"kyphoplasty", r"vertebral augmentation", r"kifoplasti", r"\bkyphon\b"], [r"cement|cimento"]),
    (CST, "Total Spinal", "Cervical Artificial Discs", [r"(cervical )?(artificial|disc) (disc )?(prosthesis|replacement|arthroplasty)", r"cervical disc arthroplasty", r"servikal (disk|disc) protez", r"yapay disk"], [r"lumbar|lomber"]),
    (CST, "Total Spinal", "Interbody Device - Cervical", [r"cervical.*(cage|interbody|spacer)", r"(cage|interbody|spacer).*cervical", r"\bacdf\b", r"servikal.*(kafes|cage)", r"(kafes|cage).*servikal"], []),
    (CST, "Total Spinal", "Interbody Device - Thoracolumbar", [r"(lumbar|thoracolumbar|tlif|plif|alif|xlif|olif).*(cage|interbody|spacer)", r"(cage|interbody|spacer).*(lumbar|tlif|plif|alif)", r"(lomber|torakolomber).*(kafes|cage)", r"(kafes|cage).*(lomber|torakolomber)"], []),
    (CST, "Total Spinal", "Spinal Fusion Fixation - Cervical", [r"cervical.*(plate|screw|rod|fixation)", r"(anterior|posterior) cervical (plate|fixation|system)", r"occipito[- ]?cervical", r"servikal.*(plak|vida|rod|fiksasyon)"], [r"cage|interbody|disc"]),
    (CST, "Total Spinal", "Spinal Fusion Fixation - Thoracolumbar", [r"pedicle screw", r"(thoracolumbar|lumbar|spinal).*\b(rods?|screws?|fixation system|set screw|cross ?links?)\b", r"(polyaxial|monoaxial).*screw.*(spin|pedic)", r"pedikul vida", r"transpedikuler", r"(torakolomber|lomber|spinal).*(rod|vida|fiksasyon)"], [r"cervical|servikal|cage|kafes|cranial|kranial|needle|igne|anesthe|anaesthe|puncture|instrument(ation)? set"]),
    (CST, "Total Spinal", "SI Joint Fusion System", [r"sacroiliac.*(fusion|joint)", r"\bsi joint\b", r"sakroiliak"], []),
    (CST, "Total Spinal", "DBM", [r"demineral\w* bone matrix", r"\bdbm\b", r"demineralize kemik"], []),
    (CST, "Total Spinal", "BMP / Growth Factor", [r"bone morphogenetic", r"\brhbmp", r"\bbmp[- ]?2\b"], []),
    (CST, "Total Spinal", "Synthetics", [r"(synthetic|tricalcium|hydroxyapatite|bioactive glass|calcium phosphate) bone (graft|substitute)", r"bone (graft )?substitute", r"sentetik kemik (grefti|yerine)", r"kemik grefti.*(sentetik|trikalsiyum)"], [r"dental|dis\b"]),
    (CST, "CSF & CC", "Hydrocephalus - shunt kits", [r"(ventriculo|lumbo)[- ]?(peritoneal|atrial) shunt", r"\bshunt (valve|system|kit)\b", r"hydroceph\w+", r"cerebrospinal fluid shunt", r"hidrosefali", r"(vp|lp) sant", r"\bsant (valf|sistem|kit)"], [r"dialysis|arteriovenous|portosystemic"]),
    (CST, "CSF & CC", "EDMS - Kits", [r"external (ventricular |lumbar )?drain\w*", r"\bevd\b", r"(ventricular|lumbar) drainage (set|kit|system)", r"eksternal (ventrikuler |lomber )?drenaj", r"ventrikuler drenaj"], []),
    (CST, "CSF & CC", "Cranial Access and Repair", [r"cranial (plate|flap|mesh|fixation|clamp)", r"(burr hole|skull) (cover|plate|clamp)", r"cranioplasty", r"kranial (plak|fiksasyon)", r"kranioplasti"], [r"custom made|dental"]),
    (CST, "Large Capital", "Core Navigation - Capital", [r"navigation system\b(?!.*related to)", r"(surgical|neuro|spine|ent|optical|electromagnetic) navigation (system|unit|station)", r"noronavigasyon", r"navigasyon sistemi"], [r"lung|bronch|related to|warranty|garanti|instrument(ation)? set|compatible with|for use with"]),
    (CST, "Large Capital", "Core Navigation - Disposables", [r"navigation.*(tracker|reference|marker|sphere|patient tracker|disposable)", r"(reflective )?marker spheres", r"navigasyon.*(isaretci|marker|sarf)"], [r"lung|bronch"]),
    (CST, "Large Capital", "Imaging Devices - Capital", [r"intra[- ]?operative (cone beam |3d )?(ct|imaging system)", r"\bo[- ]arm\b", r"mobile (cone beam )?ct.*(intraop|surgical)"], [r"related to|warranty"]),
    (CST, "Large Capital", "Spinal Robotics - Capital", [r"spin\w* (surgical )?robot", r"robot\w*.*spine surgery", r"\bmazor\b", r"spinal robot"], [r"related to|warranty"]),
    (CST, "Small Capital", "Nerve Monitoring Devices - Disposable", [r"(nerve|neuro)[- ]?monitor\w*.*(electrode|probe|tube|disposable)", r"\bnim\b.*(electrode|tube|probe)", r"emg endotracheal tube", r"(intra[- ]?operative )?neuro ?monitoring electrode", r"sinir monitor\w*.*(elektrod|prob)", r"noromonitorizasyon.*(elektrod|prob|sarf)"], []),
    (CST, "Small Capital", "Nerve Monitoring Devices - Capital", [r"(nerve|neuro)[- ]?(integrity )?monitor(ing)? (system|unit|device)", r"intra[- ]?operative (neuro)?monitoring (system|unit)", r"\bnim\b.*(system|monitor)", r"sinir monitor\w* (sistem|cihaz)", r"noromonitorizasyon (sistem|cihaz)"], [r"related to|warranty"]),
    (CST, "Small Capital", "Powered Surgical Instruments - Disposable", [r"(drill|craniotome|high[- ]speed|bur)\b.*\b(bur|burr|bit|blade|attachment)s?\b.*\b(disposable|sterile|single use)", r"(neuro|spine|ent|otology|cranial).*\bburr?s?\b", r"\bburr?\b.*(neuro|spine|otology|cranial|diamond|fluted|matchstick)", r"(motor|drill).*tek kullanimlik (frez|uc)", r"(kranial|kraniotom|noro|spinal|omurga|kbb|otoloji|beyin cerrahi).*\bfrez\b", r"\bfrez\b.*(kranial|kraniotom|noro|spinal|omurga|kbb|otoloji|beyin cerrahi)"], [r"dental|dis\b|orthodont|\bfg\b|friction grip|\biso\s?#?\s?\d{3}|carbide|inverted cone|fissure|handpiece|adhesive residue|\bra\b|composite|polish|prophy|aerat|anguldurva|angldruva|anguldruva|piyasemen|turbin|firca|protez|akril|laboratuvar"]),
    (CST, "Small Capital", "Powered Surgical Instruments - Capital", [r"(high[- ]speed|neuro|cranial|spine|ent|otology) (drill|motor) (system|unit|console)", r"craniotome\b(?!.*related to)", r"powered (surgical )?(drill|instrument) system", r"(yuksek devirli|motorlu).*(drill|motor) sistem"], [r"related to|warranty|garanti|dental|orthopedic modular"]),
    (CST, "Small Capital", "Advanced Energy - Disposable", [r"aquamantys", r"(bipolar )?sealer.*(saline|fluid)", r"\bplasmablade\b"], []),
    (CST, "Trauma", "Intramedullary Nails", [r"intramedullary (nail|rod)", r"(femoral|tibial|humeral) (interlocking |im )?nail", r"intramedulle?r civi", r"kilitli civi"], []),
    (CST, "Trauma", "Plates & Screws", [r"(locking|compression|reconstruction|lcp|dcp)\b.*\bplate", r"bone (plate|screw)", r"(cortical|cancellous|locking) screw", r"(kilitli|kompresyon|rekonstruksiyon) plak", r"(kortikal|spongioz|kilitli) vida", r"kemik (plagi|vidasi)"], [r"spin|pedic|cervical|cranial|maxillo|mandib|dental|servikal|kranial"]),
    (CST, "Trauma", "Cannulated Screws", [r"cannulated screw", r"kanullu vida"], []),
    (CST, "Trauma", "External Fixator", [r"external fixat\w+", r"ilizarov", r"eksternal fiksator", r"harici fiksator"], []),
    # ---------------- Ear Nose Throat
    (ENT, "ENT", "Balloon Sinus Dilation", [r"(balloon )?sinus (balloon|dilat\w+)", r"sinuplasty", r"eustachian tube balloon", r"sinus balon"], []),
    (ENT, "ENT", "ENT Microdebriders - Blade Disposables", [r"microdebrider blade", r"(sinus|nasal|laryngeal|adenoid)\b.*\bblade\b.*(rotat|serrat|tricut|debrid|shaver|straightshot|\d(\.\d)? ?mm\b(?!.*reusable))", r"(debrider|shaver|straightshot).*\bblades?\b", r"mikrodebrider bicag"], [r"scalpel|surgical blade no|bisturi|laryngoscope|raspator|speculum|scissor|knife|osteotome|elevator|forceps|stainless|reusable"]),
    (ENT, "ENT", "ENT Microdebriders - Capital Equipment", [r"microdebrider (system|console|unit|handpiece)", r"mikrodebrider (sistem|konsol|el)"], [r"related to|warranty"]),
    (ENT, "ENT", "ENT Drills - Disposables", [r"\b(otology|otologic|skeeter|ent)\b.*\bburr?s?\b", r"\bburr?s?\b.*\b(otology|otologic|ent|sinus)\b"], []),
    (ENT, "ENT", "Nasal Packing/Splints", [r"nasal (pack\w*|splint|tampon|dressing)", r"(intranasal|septal) splint", r"\bmerocel\b", r"burun (tamponu|splinti)", r"nazal (tampon|splint)"], []),
    (ENT, "ENT", "Nerve Monitoring Devices - Disposables", [r"(facial|recurrent laryngeal|laryngeal) nerve monitor", r"(thyroid|parotid).*nerve monitor"], []),
    (ENT, "ENT", "Injectable Implants / Vocal Fold Augmentation", [r"vocal (fold|cord) (augmentation|injection|implant)", r"ses teli (enjeksiyon|dolgu)"], []),
    (ENT, "ENT", "Local Drug Delivery (LDD)", [r"(sinus|steroid)[- ]eluting (implant|stent)", r"propel"], []),
    # ---------------- Endoscopy
    (ENDO, "GI - Chronic and Colorectal", "SB Capsule", [r"(small bowel|small intestine) capsule", r"capsule endoscop\w*(?!.*(colon|recorder|workstation|patency|crohn))", r"ince barsak kapsul", r"kapsul endoskopi"], [r"colon|kolon|recorder|workstation|patency|crohn|related to|warranty"]),
    (ENDO, "GI - Chronic and Colorectal", "Colon Capsule", [r"colon capsule", r"kolon kapsul"], []),
    (ENDO, "GI - Chronic and Colorectal", "Patency Capsule", [r"patency capsule"], []),
    (ENDO, "GI - Chronic and Colorectal", "Capsule Endoscopy - Recorder", [r"capsule.*(recorder|data logger|sensor belt)"], []),
    (ENDO, "GI - Chronic and Colorectal", "Capsule Endoscopy - Workstation", [r"capsule.*(workstation|software|reader)"], []),
    (ENDO, "GI - Chronic and Colorectal", "Endoscopic Hemostasis - Disposables", [A(r"\bclips?\b", r"working channel"),r"(endoscopic )?hemo(stasis )?clips?\b.*endoscop", r"endoscopic (hemostatic |hemostasis )?clip", r"\b(hemo|resolution|instinct) ?clip\b", r"endoskopik (hemostaz )?klip"], []),
    (ENDO, "GI - Esophageal", "Motility System - Disposables", [r"(manometry|motility) (catheter|probe)", r"high[- ]resolution manometry", r"manometri (kateter|prob)"], []),
    (ENDO, "GI - Esophageal", "Motility System - Capital", [r"(manometry|motility) (system|unit)", r"manometri (sistem|cihaz)"], [r"related to|warranty"]),
    (ENDO, "GI - Esophageal", "Reflux System - Disposables", [r"(ph|impedance)[- ](and[- ])?(ph )?(probe|catheter|capsule)", r"\bbravo\b", r"wireless ph (capsule|monitor|recorder|system)", r"(ph metre|empedans).*(prob|kateter|kapsul)"], []),
    (ENDO, "GI - Esophageal", "Reflux System - Capital", [r"(ph|impedance)[- ](monitoring )?(recorder|system)", r"ph[- ]metry (system|unit)"], [r"related to|warranty"]),
    (ENDO, "GI - Esophageal", "Barrett Esophagus - Catheters", [A(r"barrett", r"esophag|oesophag|ablation|catheter"), r"(radiofrequency|rf) ablation.*(esophag|oesophag)", r"\bbarrx\b"], [r"hodgson|tablet|\btab\b|injection|\binj\b|syrup|capsule"]),
    (ENDO, "GI - Hepatopancreatobiliary (HPB)", "EUS - FNB", [r"\beus\b.*(fnb|biopsy needle)", r"(endoscopic ultrasound|\beus\b).*fine needle biopsy", r"\bfnb\b.*needle"], []),
    (ENDO, "GI - Hepatopancreatobiliary (HPB)", "EUS - FNA", [r"\beus\b.*(fna|aspiration needle)", r"(endoscopic ultrasound|\beus\b).*(fine needle aspiration|needle)", r"\bfna\b.*needle.*(eus|endoscop)", r"eus igne"], [r"fnb|biopsy"]),
    (ENDO, "GI - Hepatopancreatobiliary (HPB)", "Ablation Microwave - Disposable", [r"microwave ablation (antenna|probe|needle)", r"mikrodalga ablasyon (anten|prob|igne)"], []),
    (ENDO, "GI - Hepatopancreatobiliary (HPB)", "Ablation RFA - Disposable", [r"(liver|tumou?r|hepatic|thyroid).*(rf|radiofrequency) ablation (needle|electrode|probe)", r"radiofrequency ablation needle", r"(karaciger|tumor|tiroid).*radyofrekans ablasyon"], []),
    (NM, "GI - Hepatopancreatobiliary (HPB)", "Ablation Microwave - Capital", [r"microwave ablation (system|generator)", r"mikrodalga ablasyon (sistem|jenerator)"], [r"related to|warranty"]),
    # ---------------- Acute Care & Monitoring
    (ACM, "Respiratory Compromise", "Adult Sensors (Disposable)", [r"(pulse ox\w*|spo2|oximetry) (sensor|probe)\b.*(disposable|adult|adhesive|single)", r"disposable.*(spo2|oximet\w*) sensor", r"tek kullanimlik.*(spo2|oksimetre) (sensor|prob)", r"(spo2|saturasyon) (probu|sensoru)"], [r"reusable|tekrar kullanilabilir|pediatric|neonat|infant"]),
    (ACM, "Respiratory Compromise", "Specialty Sensors (Disposable)", [r"(pulse ox\w*|spo2|oximetry) (sensor|probe).*(pediatric|neonat|infant)", r"(pediatric|neonat|infant).*(spo2|oximet\w*) sensor"], [r"reusable"]),
    (ACM, "Respiratory Compromise", "Sensors, Reusable", [r"reusable.*(spo2|oximet\w*) (sensor|probe)", r"(spo2|oximet\w*) (sensor|probe).*reusable"], []),
    (ACM, "Respiratory Compromise", "Handheld Monitors, Pulse Oximeter", [r"(handheld|portable|hand[- ]held) pulse oximeter", r"el tipi pulse oksimetre"], [r"related to"]),
    (ACM, "Respiratory Compromise", "Bedside Monitors, Pulse Oximeter", [r"(bedside|tabletop|table top) pulse oximeter", r"pulse oximeter\b(?!.*(handheld|portable|finger|sensor|probe|related to))", r"pulse oksimetre (cihaz|monitor)"], [r"related to|finger|parmak"]),
    (ACM, "Respiratory Compromise", "Consumable CO2 (Disposable)", [r"(capnograph\w*|etco2|co2|microstream).*(sampling line|filter line|cannula|adapter)", r"(sampling line|filter ?line).*(co2|capno)", r"kapnografi.*(hat|kanul|adaptor)"], []),
    (ACM, "Respiratory Compromise", "Monitors, Capnography", [r"capnograph\w* (monitor|unit|device)", r"(handheld|portable) capnograph", r"kapnograf (cihaz|monitor)"], [r"related to|module"]),
    (ACM, "Respiratory Compromise", "Capnography Module", [r"(capnograph\w*|etco2|co2) module", r"kapnografi modul"], []),
    (ACM, "Cerebral Compromise", "Sensors, LoC", [r"\bbis\b.*sensor", r"(bispectral|depth of anaesthe\w*|depth of anesthe\w*|consciousness).*sensor", r"anestezi derinligi.*sensor", r"bis sensoru"], []),
    (ACM, "Cerebral Compromise", "Monitors, LoC", [r"\bbis\b.*(monitor|module)", r"(bispectral|depth of anaesthe\w*|depth of anesthe\w*) (monitor|module)", r"anestezi derinligi (monitor|modul)"], [r"related to|sensor"]),
    (ACM, "Cerebral Compromise", "Sensors, NIRS", [r"(nirs|cerebral oximet\w*|regional oximet\w*|somatic oximet\w*).*sensor", r"\binvos\b.*sensor", r"serebral oksimetre sensor"], []),
    (ACM, "Cerebral Compromise", "Monitors, NIRS", [r"(nirs|cerebral oximet\w*|regional oximet\w*) (monitor|system|module)", r"\binvos\b.*(monitor|system)", r"serebral oksimetre (monitor|cihaz)"], [r"related to|sensor"]),
    (ACM, "Airway Management", "Endotracheal Tubes", [r"endotracheal tube", r"\bett\b.*cuff", r"endotrakeal tup", r"entubasyon tupu", r"انبوب.*الرغامي"], [r"related to|emg|nerve|nim|holder|stylet"]),
    (ACM, "Airway Management", "Tracheostomy Tubes", [r"tracheostomy tube", r"trakeostomi (kanulu|tupu)", r"انبوب.*القصبه"], [r"related to|cup|holder|ribbon|tie|speaking valve|brush"]),
    (ACM, "Airway Management", "Intubation Accessory - Stylet", [r"(intubat\w*|endotracheal) stylet", r"\bstylet\b.*(intubat|tube)", r"entubasyon stilesi", r"\bstile\b"], []),
    (ACM, "Airway Management", "Airway Access", [r"video ?laryngoscope", r"videolaringoskop"], [r"related to|warranty"]),
    (ACM, "Airway Management", "Airway Access - Consumables", [r"(video ?laryngoscope|laryngoscope) (disposable )?blade", r"videolaringoskop bicag"], []),
    (ACM, "Breathing Systems", "Breathing Circuits", [r"(breathing|anaesthe\w*|anesthe\w*|ventilator|patient) circuit", r"solunum devresi", r"anestezi devresi", r"ventilator devresi"], [r"related to|warranty"]),
    (ACM, "Breathing Systems", "Breathing System Filters / HME Filters", [r"\bhmef?\b", r"heat (and )?moisture exchang", r"(breathing|bacterial|viral|electrostatic).*(filter)", r"(bakteri|viral|solunum).*filtre", r"\bhme filtre"], [r"suction unit|canister|iv filter|infusion|blood|related to|water|air inlet|pulmonary function|spirometr"]),
    (ACM, "Breathing Systems", "Pulmonary Function Testing Filters", [r"(pulmonary function|spirometr\w*|pft).*filter", r"spirometri filtre"], []),
    (ACM, "Breathing Systems", "Closed Suction Systems", [r"closed (tracheal )?suction", r"kapali (sistem )?aspirasyon"], []),
    (ACM, "Breathing Systems", "Inhalation Therapy - Incentive Spirometers", [r"incentive spirometer", r"(three|3)[- ]ball.*(exerciser|spirometer)", r"respiratory exerciser", r"triflo", r"solunum egzersiz"], []),
    (ACM, "Breathing Systems", "Inhalation Therapy - Mesh Nebulizers", [r"(vibrating )?mesh nebuli[sz]er", r"\baerogen\b"], []),
    (ACM, "Breathing Systems", "Inhalation Therapy - Oxygen & Aerosol Therapy Consumables", [r"(oxygen|aerosol|nebuli[sz]er|venturi|non[- ]rebreather) mask", r"nasal (oxygen )?cannula", r"(oksijen|nebulizator|venturi) maske", r"nazal (oksijen )?kanul"], [r"related to|cpap|bipap|niv|anaesthe|anesthe"]),
    (ACM, "Breathing Systems", "Cuff Pressure Management - Capital", [r"cuff pressure (manometer|controller|gauge)", r"kaf basinc (olcer|monitor)"], []),
    (ACM, "Temperature", "Forced Air Warming", [r"forced[- ]air (warming|warmer)", r"(patient|convective) warming (system|unit|blanket)", r"(hasta )?isitma battaniye", r"sicak hava.*isitma"], [r"related to|blood|fluid|infant|incubator"]),
    (ACM, "Temperature", "Temperature Monitoring Probe", [r"(temperature|esophageal|rectal|skin) (temperature )?probe", r"isi probu", r"sicaklik probu"], [r"related to"]),
    # ---------------- Surgical Innovations
    (SI, "Stapling", "Endo - Reload", [r"(endo\w*|laparoscop\w*|linear cutter|articulat\w*).*(reload|cartridge)", r"(reload|cartridge).*(endo|linear cutter|articulat|laparoscop)", r"(endo|laparoskopik).*(kartus|yukleme)", r"stapler kartus"], [r"skin|circular"]),
    (SI, "Stapling", "Endo - Stapling Device", [r"endo\w* (linear )?(cutter|stapler)", r"(articulat\w*|laparoscop\w*) (linear )?(cutter|stapler)", r"(endostapler|endo stapler)", r"laparoskopik stapler"], [r"reload|cartridge|kartus|circular|skin"]),
    (SI, "Stapling", "Open - Stapling Device (Benign Circular)", [r"(hemorrhoid\w*|haemorrhoid\w*|\bpph\b|prolapse).*(stapler|circular)", r"(stapler|circular).*(hemorrhoid|haemorrhoid|\bpph\b)", r"hemoroid.*stapler"], [r"skin"]),
    (SI, "Stapling", "Open - Stapling Device (Oncologic Circular)", [r"circular (stapler|anastomo\w+)", r"\beea\b", r"sirkuler stapler"], [r"skin|hemorrhoid|haemorrhoid|\bpph\b"]),
    (SI, "Stapling", "Open - Reload", [r"\b(linear|ta|transverse anastomosis|gia)\b.*\b(reload|cartridge|loading unit)", r"lineer.*(kartus|yukleme)"], [r"endo|laparoscop|articulat|assay|reagent|igm|igg|test|kit\b"]),
    (SI, "Stapling", "Open - Stapling Device (Skin Stapler)", [r"skin stapler", r"deri stapleri", r"cilt zimba"], [r"remover"]),
    # Open linear / TA staplers: no matching taxonomy category -> left unmapped on purpose.
    (SI, "Vessel Sealing", "Vessel Sealing Devices - Advanced Bipolar Energy", [r"vessel seal\w*", r"\bligasure\b", r"(advanced )?bipolar (energy )?(sealer|sealing)", r"\benseal\b", r"damar muhurleme", r"damar kapama"], [r"ultrason|related to|pencil|resectoscope|forceps|(sealing|fusion) (system|generator|unit)|generator|\bmodel\s*:"]),
    (SI, "Vessel Sealing", "Vessel Sealing Devices - Ultrasonic Energy", [r"ultrasonic (shears|scalpel|dissector|energy|coagulat\w*)", r"harmonic (scalpel|ace|focus|shears)", r"\bsonicision\b", r"ultrasonik (makas|disektor|bistuar)"], [r"aspirator|cusa|bone|lipo|dental|scaler"]),
    (SI, "Electrosurgery", "Electrosurgical Devices (Grounding Pads/Return Electrodes)", [r"(return|grounding|dispersive|neutral|patient) (electrode|pad|plate)", r"(notr|hasta) (elektrot|plak)", r"topraklama plag"], [r"related to|ecg|ekg"]),
    (SI, "Electrosurgery", "Electrosurgical Accessories", [r"(electrosurgical|cautery|diathermy|esu) (pencil|electrode|blade|ball|needle|tip)", r"(cautery|bovie) pencil", r"koter (kalemi|ucu|elektrod)", r"elektrokoter kalem"], [r"related to|smoke"]),
    (SI, "Electrosurgery", "Smoke Evac - Pencils", [r"smoke evacuat\w* pencil", r"duman tahliye.*kalem"], []),
    (SI, "Electrosurgery", "Smoke Evac", [r"smoke evacuat\w*", r"duman tahliye"], [r"pencil|filter|related to"]),
    (SI, "Electrosurgery", "Argon Hand Instruments / Consumables", [r"argon (plasma|beam|coagulat\w*).*(probe|handpiece|electrode|catheter)", r"argon.*(prob|el aleti)"], []),
    (SI, "Hardware - COT", "HW - Advanced", [r"(electrosurgical|diathermy|cautery|esu) (unit|generator)\b(?!.*related to)", r"elektrocerrahi (unitesi|jenerator)", r"koter (cihazi|unitesi|jenerator)"], [r"related to|warranty|pencil|pad"]),
    (SI, "Hardware - COT", "Argon Generator", [r"argon (plasma |beam )?(coagulat\w* )?(unit|generator)"], [r"related to"]),
    (SI, "Hernia", "Synthetic Mesh", [r"(hernia|polypropylene|polyester|composite|parietex|prolene) mesh", r"\bmesh\b.*(hernia|inguinal|ventral|polypropylene)", r"(fitik )?yamasi", r"\b(prolen|polipropilen) yama", r"fitik meshi"], [r"biologic|biyolojik|nebuli|stent"]),
    (SI, "Hernia", "Biologic Mesh", [r"biologic\w* mesh", r"(acellular|porcine|bovine).*(dermal|tissue) (matrix|graft).*hernia", r"biyolojik yama"], []),
    (SI, "Hernia", "Soft Tissue Mechanics - Mesh Fixation Tacker", [r"mesh fixation (device|tacker)", r"hernia.*fixation (device|tacker)", r"\btack(er|s)\b.*(hernia|mesh|absorbable)", r"\bprotack\b|\babsorbatack\b|\bsecurestrap\b", r"(fitik|yama).*(sabitleyici|zimba|tacker)"], []),
    (SI, "Hernia", "Soft Tissue Mechanics - Balloon Dissection Device", [r"(balloon|spacemaker).*dissect\w*", r"preperitoneal.*balloon"], []),
    (SI, "Instruments and Access", "Trocars", [r"\btrocar", r"\btrokar", r"laparoscopic (access )?port\b", r"\bport\b.*(laparoscop|optical|bladeless)"], [r"related to|thoracic drain|toracic|gogus|chest|transanal|single port|drain|biopsy|breast|catheter|paracentes|cystostomy|nephrostomy|pericardio|kateter|dren"]),
    (SI, "Instruments and Access", "Access Kits", [r"single[- ](incision|port) (access|platform|device)", r"transanal.*(port|platform)", r"hand[- ]access", r"gel ?port"], []),
    (SI, "Instruments and Access", "Endo Clip Appliers", [r"(endo\w*|laparoscop\w*) clip (applier|applicator)", r"(endoklip|laparoskopik klip) (aplikator|uygulayici)"], [r"reload|cartridge"]),
    (SI, "Instruments and Access", "Open Clip Appliers", [r"(ligat\w*|hemostatic|surgical) clip (applier|applicator)", r"clip applier\b(?!.*(endo|laparo))", r"klip aplikator"], [r"endo|laparo|reload|vascular closure|closure system|femoral|arteriotomy"]),
    (SI, "Instruments and Access", "Clip Applier Reloads", [r"(ligat\w*|hemostatic|polymer|titanium|hem-o-lok) clips?\b", r"\bligating clip", r"\bklip\b.*(titanyum|polimer|ligasyon)", r"(titanyum|polimer|ligasyon) klip"], [r"endoscopic|hemostasis|gi |aneurysm|towel|cranial|skin|hair|umbilical|nose|working channel|endoscop"]),
    (SI, "Instruments and Access", "Retrieval Bags", [r"(specimen|tissue|retrieval|endo) (retrieval )?(bag|pouch)", r"(doku|numune) (torbasi|cantasi)", r"endobag"], []),
    (SI, "Instruments and Access", "Suction/Irrigation Devices", [r"(laparoscopic )?suction[/ -]?irrigation", r"irrigation[/ -]suction", r"aspirasyon[/ -]irrigasyon"], [r"related to"]),
    (SI, "Instruments and Access", "Wound Retractors", [r"wound (protector|retractor)", r"alexis", r"yara (koruyucu|ekartoru)"], []),
    (SI, "Instruments and Access", "Endosuturing Devices", [r"(endoscopic|laparoscopic) sutur\w* device", r"\bendo ?stitch\b", r"endo sutur"], []),
    (SI, "Wound Management", "Barbed Sutures - Absorbable", [r"\b(barbed|knotless|unidirectional|bidirectional|v-?loc|stratafix|quill)\b.*\babsorbable", r"absorbable.*\b(barbed|knotless|v-?loc|stratafix)", r"(dikenli|barbed).*emilebilir"], [r"non[- ]?absorbable"]),
    (SI, "Wound Management", "Barbed Sutures - Non-Absorbable", [r"\b(barbed|knotless|v-?loc|stratafix|quill)\b.*non[- ]?absorbable", r"(dikenli|barbed).*emilmeyen"], []),
    (SI, "Wound Management", "Conventional Sutures - Absorbable Antibacterial", [r"sutur\w*.*(triclosan|antibacterial|antimicrobial).*absorbable", r"(triclosan|antibacterial).*absorbable.*sutur", r"sutur.*(triklosan|antibakteriyel).*emilebilir", r"(triklosan|antibakteriyel).*emilebilir.*sutur"], [r"non[- ]?absorbable|barbed|knotless"]),
    (SI, "Wound Management", "Conventional Sutures - Absorbable", [r"\bsutur\w*\b.*\babsorbable\b", r"\b(polyglactin|polyglycolic|polydioxanone|pds|poliglecaprone|polyglyconate|polyglytone|glycomer|catgut|chromic|vicryl|monocryl|caprosyn|biosyn|maxon|dexon|velosorb)\b", r"\bsutur\b.*\bemilebilir\b", r"emilebilir.*(sutur|cerrahi iplik)", r"(poliglaktin|poliglikolik|polidioksanon|katgut)"], [r"non[- ]?absorbable|barbed|knotless|triclosan|antibacterial|v-?loc|stratafix|emilmeyen|dikenli"]),
    (SI, "Wound Management", "Conventional Sutures - Non-Absorbable", [r"\bsutur\w*\b.*non[- ]?absorbable", r"\b(polypropylene|polyester|nylon|polyamide|silk|ptfe|stainless steel|polybutester)\b.*\bsutur", r"\bsutur\w*\b.*\b(polypropylene|polyester|nylon|polyamide|silk|sternal wire)\b", r"\b(prolene|ethibond|ethilon|surgipro|ti-?cron|monosof|dermalon|surgilon|mersilene|sofsilk)\b", r"(sutur|cerrahi iplik).*(emilmeyen|polipropilen|ipek|naylon|poliester)", r"(emilmeyen|polipropilen|ipek|naylon|poliester).*(sutur|cerrahi iplik)"], [r"barbed|knotless|v-?loc|stratafix|dikenli|mesh|yama"]),
    (SI, "Wound Management", "Hemostats", [r"(absorbable )?hemosta(t|tic)\b.*(gauze|sponge|powder|matrix|fibrillar|oxidi[sz]ed|gelatin|collagen|patch|flowable)", r"oxidi[sz]ed (regenerated )?cellulose", r"\b(surgicel|gelfoam|spongostan|floseal|surgiflo|arista|tachosil|veriset)\b", r"(emilebilir )?hemostatik (gaz|sunger|toz|matris|yama)", r"oksitlenmis selulo"], [r"dental|nasal"]),
    (SI, "Wound Management", "Surgical Adhesives", [r"(tissue|skin|topical|surgical) (adhesive|glue|sealant)", r"\b(dermabond|histoacryl|indermil|bioglue|coseal|progel)\b", r"(doku|cilt|cerrahi) yapistirici"], [r"venous|vein|venaseal|tape|drape|dressing"]),
    (SI, "GYN Health", "Hysteroscopic Tissue Removal System - Disposables", [r"hysteroscop\w*.*(morcellat\w*|tissue removal).*(disposable|device|blade)", r"(morcellat\w*|tissue removal).*hysteroscop", r"\bmyosure\b", r"\btruclear\b", r"histeroskopik doku"], [r"system\b(?!.*disposable)|generator|related to"]),
    (SI, "GYN Health", "Hysteroscopic Tissue Removal System", [r"hysteroscop\w* (morcellat\w*|tissue removal) system", r"morcellator generator.*hysteroscop"], [r"related to"]),
    (SI, "GYN Health", "Fluid Management System", [r"(hysteroscop\w*|uterine).*(fluid management|distension)", r"fluid management system.*hysteroscop", r"fluid management system, inflow"], []),
    (SI, "GYN Health", "Hysteroscopes", [r"\bhysteroscope\b", r"\bhisteroskop\b"], [r"related to|morcellat|sheath only|specimen|collection set"]),
    (SI, "Lung Health & Visualization", "Lung Navigation Kits", [r"(electromagnetic|em) navigation bronchoscopy", r"(lung|bronch\w*) navigation (kit|catheter|system)", r"superdimension|\billumisite\b", r"akciger navigasyon"], []),
    # ---------------- Surgical Robotics
    (SR, "Robotic Surgical Technologies", "Robotic Assisted Surgery Instruments - Shears", [r"robot\w*.*(shears|scissors)", r"(shears|scissors).*robot", r"robotik.*makas"], []),
    (SR, "Robotic Surgical Technologies", "Robotic Assisted Surgery Instruments - Graspers", [r"robot\w*.*(grasper|forceps|needle driver|dissector)", r"(grasper|forceps|needle driver).*robot", r"robotik.*(tutucu|forseps|portegu)"], []),
    (SR, "Robotic Surgical Technologies", "Robotic Surgery Accessories - Sterile Drapes", [r"robot\w*.*(drape|cover)", r"(drape|cover).*robot\w*", r"robot.*(ortu|kilif)"], []),
    (SR, "Robotic Surgical Technologies", "Robotic Surgery Accessories", [r"robot\w* (surgery |surgical )?(accessor|cannula|seal|obturator|trocar|reducer|tip cover)", r"robotik cerrahi.*(aksesuar|kanul)"], []),
    (SR, "Robotic Surgical Technologies", "System", [r"robot\w*[- ]assisted surgical system", r"surgical robot(ic)? system", r"robotic surgery system", r"\bda vinci\b.*system", r"\bhugo\b.*ras", r"robotik cerrahi sistem"], [r"spin|related to|warranty|garanti|orthop|knee|hip"]),
]

# ---------------- Company aliases (manufacturer text -> taxonomy Company). Regex on fold(manufacturer).
CO_ALIAS = [
    (r"medtronic|covidien|nellcor|kyphon|mazor|given imaging|oridion|puritan bennett|\bev3\b|\bxomed\b|\bbarrx\b|\binvos\b|\bnewport medical\b|aspect medical|intersect ent|medtronic", "Medtronic"),
    (r"ethicon|johnson ?(&|and) ?johnson|\bj ?& ?j\b|depuy|synthes|biosense webster|cerenovus|acclarent|mentor|codman(?! integra)|auris health|\bverb surgical\b|abiomed|shockwave", "Johnson & Johnson"),
    (r"boston scientific|\bbsc\b|cameron health|\bbtg\b|lumenis surgical|baylis", "Boston Scientific"),
    (r"abbott|st\.? ?jude|\bsjm\b|cardiovascular systems inc|\bcsi\b atherectomy|tendyne|thoratec", "Abbott"),
    (r"\bstryker\b|\bk2m\b|wright medical|\bconcentric medical\b|\btarget therapeutics\b|vertos", "Stryker"),
    (r"b\.? ?braun|aesculap", "B. Braun"),
    (r"\bterumo\b|bolton medical|vascutek|microvention|sequent medical", "Terumo"),
    (r"edwards lifesciences|\bedwards\b", "Edwards Lifesciences"),
    (r"biotronik", "BIOTRONIK"),
    (r"olympus|gyrus acmi", "Olympus"),
    (r"cook (medical|incorporated|inc|ireland|endoscopy)|william cook|\bcook\b", "Cook Medical"),
    (r"karl storz|\bstorz\b", "KARL STORZ"),
    (r"globus medical", "Globus Medical"),
    (r"microport (ep|electrophysiology)", "MicroPort EP"),
    (r"microport|endovastec", "MicroPort"),
    (r"becton|\bbd\b|c\.? ?r\.? ?bard|\bbard\b|carefusion", "BD"),
    (r"intuitive surgical|\bintuitive\b", "Intuitive Surgical"),
    (r"penumbra", "Penumbra"),
    (r"masimo", "Masimo"),
    (r"getinge|maquet|datascope|atrium medical", "Getinge"),
    (r"cordis", "Cordis"),
    (r"teleflex|arrow international|vascular solutions|\brusch\b|lma ", "Teleflex"),
    (r"philips|spectranetics|volcano", "Philips"),
    (r"applied medical", "Applied Medical"),
    (r"ge health|general electric|\bge medical|datex", "GE HealthCare"),
    (r"livanova|sorin", "LivaNova"),
    (r"mindray", "Mindray"),
    (r"conmed|linvatec", "CONMED"),
    (r"\bbalt\b", "Balt"),
    (r"icu medical|smiths medical|portex", "ICU Medical"),
    (r"merit medical", "Merit Medical"),
    (r"nihon kohden", "Nihon Kohden"),
    (r"drager|draeger|dräger", "Dräger"),
    (r"w\.? ?l\.? ?gore|\bgore\b", "W. L. Gore"),
    (r"asahi intecc|\basahi\b", "Asahi Intecc"),
    (r"integra", "Integra LifeSciences"),
    (r"smith ?(&|and) ?nephew", "Smith & Nephew"),
    (r"lepu", "Lepu Medical"),
    (r"lifetech", "Lifetech Scientific"),
    (r"\bambu\b", "Ambu"),
    (r"zimmer|biomet", "Zimmer Biomet"),
    (r"\bnatus\b", "Natus"),
    (r"arthrex", "Arthrex"),
    (r"pentax", "PENTAX Medical"),
    (r"fujifilm|fuji film", "Fujifilm"),
    (r"nuvasive", "NuVasive"),
    (r"med-?el\b", "MED-EL"),
]


class Vocab:
    def __init__(self, path=TAX_PATH):
        ws = openpyxl.load_workbook(path, read_only=True)["Taxonomy"]
        self.rows = [r for r in ws.iter_rows(min_row=2, values_only=True) if r[0]]
        sub_ou = {(r[0], r[2]) for r in self.rows}
        pc = {(r[0], r[2], r[3]) for r in self.rows}
        self.companies = sorted({r[4] for r in self.rows if r[4]})
        for ou, s, p, inc, exc in R0 + R:
            assert (ou, s) in sub_ou, (ou, s)
            assert (ou, s, p) in pc, (ou, s, p)
        for _, c in CO_ALIAS:
            assert c in self.companies, c
        self.rules = [(ou, s, p, [re.compile(x) for x in inc], [re.compile(x) for x in exc]) for ou, s, p, inc, exc in R0 + R]
        self.alias = [(re.compile(x), c) for x, c in CO_ALIAS]
        self.co_fold = {fold(c).strip(): c for c in self.companies}
        # families per (company, product category): distinctive tokens
        self.fam = defaultdict(list)
        for r in self.rows:
            if r[4] and r[5]:
                toks = [t for t in fold(r[5]).split() if len(t) >= 3 and not t.isdigit() and t not in FAM_STOP]
                if toks:
                    self.fam[(r[4], r[3])].append((r[5], toks))

    # ---- Product category from the line item only
    def _match(self, t):
        for ou, s, p, inc, exc in self.rules:
            if any(x.search(t) for x in inc) and not any(x.search(t) for x in exc):
                return {"ou": ou, "sub_ou": s, "product_category": p}
        return None

    def product(self, item_text):
        """NUPCO accessory lines read '<item> RELATED TO <parent unit>': match the item part first,
        then the full text (rules with a 'related to' exclusion still block parent-unit hits)."""
        t = fold(item_text)
        if len(t.strip()) < 4:
            return None
        head = t.split(" related to ")[0] + " "
        if head != t and len(head.split()) >= 2:
            m = self._match(head)
            if m:
                return {**m, "method": "vocab_rule_item"}
        m = self._match(t)
        return {**m, "method": "vocab_rule"} if m else None

    # ---- Company from the manufacturer only
    def company(self, manufacturer_text):
        t = fold(manufacturer_text)
        if len(t.strip()) < 2:
            return None
        for rx, c in self.alias:
            if rx.search(t):
                return {"company": c, "method": "alias"}
        k = t.strip()
        if k in self.co_fold:
            return {"company": self.co_fold[k], "method": "exact"}
        m = process.extractOne(k, list(self.co_fold.keys()), scorer=fuzz.token_set_ratio, score_cutoff=95)
        if m and len(m[0]) >= 5:
            return {"company": self.co_fold[m[0]], "method": f"fuzzy{int(m[1])}"}
        return None

    # ---- Family: a taxonomy family of (company, product category) whose distinctive tokens all appear
    def family(self, company, product_category, *texts):
        cands = self.fam.get((company, product_category)) or []
        t = fold(" ".join(x or "" for x in texts))
        best = None
        for name, toks in cands:
            if all(re.search(r"\b" + re.escape(tok) + r"\b", t) for tok in toks):
                if best is None or len(toks) > len(best[1]):
                    best = (name, toks)
        return best[0] if best else None


FAM_STOP = {"and", "the", "with", "for", "system", "systems", "series", "family", "plus", "pro", "new", "kit", "set",
            "disposable", "reusable", "catheter", "stent", "balloon", "sensor", "sensors", "monitor", "device", "devices",
            "generator", "pump", "console", "lead", "leads", "others", "other", "generic", "range", "line", "models"}

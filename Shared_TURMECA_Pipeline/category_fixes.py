"""
Category corrections found in the 2026-10-08 audit of the mapped TURMECA data.

fix(row_id, cat, text_orig, text_en) -> None (no change) | ("SET", category, note) | ("EXCLUDE", None, reason)
Applied on top of vocab_rules output. Every rule here was written from rows reviewed by hand; see README.
"""
import re

EX = "EXCLUDE"


def _t(*xs):
    s = " ".join(str(x or "") for x in xs)
    return s.translate(str.maketrans("İIıŞşĞğÇçÖöÜü", "iiissggccoouu")).lower()


# (category regex, text regex, action, target category or reason)
RULES = [
    # ---------------- not a medical-device purchase in scope (lab, dental, veterinary, service, generic items)
    (r".", r"\bpfa-?100\b|innovanc pfa|pfa (collag|col\.|startl|cleaning|trigger)|pfa- (collagen|trigger|spare|cleaning)|agilent pfa|pfa-st3", EX, "Laboratory item (PFA-100 platelet analyser / lab PFA tubing), not a pulsed-field ablation catheter"),
    (r".", r"^(?!.*(esophag|ozofag|manometr|impedan|empedans|capsule|kapsul|kateter|catheter)).*(ph metre|ph meter|ph prob[u]? (saklama|dolum)|iletkenlik|conductivity|^\s*(cam )?ph prob|hanna|hach|ohaus|wtw multi)", EX, "Laboratory pH-meter probe/solution, not a reflux-monitoring catheter"),
    (r".", r"radyo ?vizyo|radiovisio|\brvg\b", EX, "Dental radiography (RVG) sensor sleeve"),
    (r".", r"corometrics", EX, "Fetal-monitor spare part"),
    (r".", r"immunohisto|immunohisto|immünohisto|boyama ?sistemi|staining system", EX, "Laboratory staining system"),
    (r".", r"trifloxystrobin", EX, "Laboratory reference standard (pesticide), not a spirometer"),
    (r".", r"veteriner|veterinary", EX, "Veterinary equipment"),
    (r".", r"hasta alti pedi|patient underpad", EX, "Patient underpad (incontinence pad)"),
    (r".", r"service training|factory level service", EX, "Service / training line, not a device"),
    (r"EVAR", r"evar software", EX, "Angiography software option, not a stent graft"),
    (r"TCV Aortic", r"related to ultrasound cardiac", EX, "TAVI software/package for an ultrasound system, not a valve"),
    (r"External IPGs", r"analy[sz]er", EX, "Pacing system analyser (test equipment)"),
    (r".", r"\bfrez\b|frezi|aerotor|piyasemen|interproximal|porselen|endodonti|anguldurva|diş üniti|dis uniti|bur, sintered diamond", EX, "Dental bur / dental handpiece item"),
    (r".", r"alet ve frez|frez dezenfekt", EX, "Instrument cleaning brush / disinfectant"),
    (r"ENT Microdebriders - Blade", r"tiras|traş|tras bicag|tıraş|jilet|clipper|razor|pet tras|shaving blade for surgical shaver", EX, "Hair clipper / razor blade, not an ENT microdebrider blade"),
    (r"Breathing System Filters", r"aspirat|suction|su aritma|water treatment|serum bakteri|saline bacteria|sisel|bottle-top|0[.,]2[02] ?(mikron|micron|um)", EX, "Suction-unit / IV / water / laboratory filter, not a breathing-system filter"),
    (r"Clip Applier Reloads", r"timsah|alligator|aligator", EX, "Alligator-clip cable / EMG electrode, not a ligation clip"),
    (r"Endo - Reload", r"picc|endoglide|dsaek|dmek|endodont|anguldurva", EX, "Not a stapler reload (PICC / ophthalmic graft cartridge / dental cartridge)"),
    (r"Electrosurgical Devices \(Grounding", r"underpad|alti pedi", EX, "Patient underpad"),
    (r"Endotracheal Tubes", r"sabitley|tutucu|holder|fixation device", EX, "Endotracheal-tube holder - no taxonomy category"),
    (r"Sutures", r"anchor|ankor|suture passer|tasiyici sutur|geçirici|gecirici", EX, "Suture anchor / suture passer (sports-medicine fixation) - no taxonomy category"),
    (r"Conventional Sutures", r"forceps, suturing|pigtail probe", EX, "Surgical instrument, not a suture"),
    (r"Leads", r"lead extraction|lead locking|lead cutter|bridge occlusion", EX, "Lead-extraction tool - no taxonomy category"),
    (r"Microvascular Plugs", r"turnike|turnstile", EX, "Vascular tourniquet/snare kit, not a vascular plug"),
    (r"Trocars", r"kirschner|kirsner|kırşner|steinman|k-?wire|stell wire|celik tel", EX, "Kirschner wire / Steinmann pin with trocar tip (orthopaedic)"),
    (r"Trocars", r"chandelier", EX, "Ophthalmic chandelier light"),
    (r"Plates & Screws", r"speculum", EX, "Eye speculum (instrument)"),
    (r"Nasal Packing", r"forceps", EX, "Nasal tampon forceps (instrument)"),
    (r"Drug Coated Balloons", r"urethr|uretr", EX, "Urethral drug-coated balloon (urology) - not in the vascular taxonomy categories"),
    (r"PTCA Balloons", r"valve hemostatic|hemostatic valve", EX, "Haemostasis valve accessory - no taxonomy category"),
    (r"PTCA Balloons", r"greft stent|graft stent", EX, "Coronary covered (graft) stent - no taxonomy category"),
    (r"Standard PTA Balloons", r"greft kapli|graft-covered|ptfe", EX, "Peripheral covered stent - no taxonomy category"),
    # ---------------- wrong category inside the taxonomy -> correct category
    (r"Sutures - Absorbable|Barbed Sutures - Absorbable", r"non[- ]+absorb|emilemeyen", "SET", "Conventional Sutures - Non-Absorbable"),
    (r"PTCA Balloons", r"stent.{0,40}(ilac|drug)|(ilac|drug).{0,40}stent", "SET", "DES"),
    (r"PTCA Balloons", r"ilac|drug[- ]?(eluting|coated|release)|limus release|ilacli", "SET", "Drug Coated Balloons|ICT"),
    (r"High Pressure PTA", r"ilac|drug", "SET", "Drug Coated Balloons|PVH"),
    (r"Standard PTA Balloons", r"balona yuklenmemis|not balloon-mounted", "SET", "BMS SX Stent"),
    (r"Standard PTA Balloons", r"stent", "SET", "BMS BX Stent"),
    (r"Standard PTA Balloons", r"constraining cage|scoring", "SET", "Specialty PTA Balloons"),
    (r"Endo - Reload", r"yuklemesiz|unloaded|non-preloaded|hemokl|haemocl|hemocl", "SET", "Endoscopic Hemostasis - Disposables"),
    (r"Endo - Reload", r"^(?!.*(endosk|endosc|lapar|artik|articul|endo |echelon|endopath)).*(lineer|linear|liner|kavisli|curved|konveks|convex|gia|tcr)", "SET", "Open - Reload"),
    (r"Access Products - Micro Catheters", r"revascularization device", "SET", "Stent Retrievers"),
    (r"Liquid Embolics", r"occlusion balloon", "SET", "Accessory Products - Occlusion Balloon Systems"),
    (r"Fluid Management System", r"morcellat|tissue removal", "SET", "Hysteroscopic Tissue Removal System"),
    (r"Superficial Venous - CAC", r"cilt|skin", "SET", "Surgical Adhesives"),
    (r"Grounding Pads", r"radiofrequency ablation|\brfa\b", "SET", "Ablation RFA - Disposable"),
    (r"TCV Aortic", r"cerebral protection", "SET", "Embolic Protection Devices"),
    (r"Cannulae - Arterial", r"kardiyopleji|cardioplegia", "SET", "Cannulae - Cardioplegia"),
    (r"Monitors, Capnography", r"agizlig|mouthpiece|adapt", "SET", "Consumable CO2 (Disposable)"),
    (r"Bedside Monitors, Pulse Oximeter", r"prob|sensor|sensör", "SET", "Sensors, Reusable"),
    (r"Adult Sensors \(Disposable\)", r"cok kullanim|reusable", "SET", "Sensors, Reusable"),
    (r"Synthetic Mesh", r"mesh fixation", "SET", "Soft Tissue Mechanics - Mesh Fixation Tacker"),
]
RULES = [(re.compile(c), re.compile(t, re.I), a, x) for c, t, a, x in RULES]
PREV_SPLIT = re.compile(r"\s(?:itmz|itemized|itimized|itemised)\b", re.I)


def fix(row_id, cat, text_orig, text_en, vocab=None):
    txt = _t(text_orig, text_en)
    # previous KSA extraction: description is this item + the next items glued on; classify this item's own text only
    if str(row_id).startswith("SA-NUPCO-PREV") and vocab is not None:
        src = str(text_en or text_orig or "")
        head = PREV_SPLIT.split(src)[0]
        if head != src:
            m = vocab.product(head)
            if not m:
                return (EX, None, "Previous-extraction row: its own item text (before the merged next item) maps to no taxonomy category")
            if m["product_category"] != cat:
                return ("SET", m["product_category"], "Previous-extraction row re-mapped on its own item text (merged next item removed)")
            txt = _t(head)
    for c, t, a, x in RULES:
        if c.search(cat or "") and t.search(txt):
            if a == EX:
                return (EX, None, x)
            return ("SET", x, "Category corrected in 2026-10-08 audit")
    return None

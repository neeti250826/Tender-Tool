from __future__ import annotations

import re
from datetime import date, datetime, timedelta
from typing import Iterable

from harness.shared.normalize import normalize_text


WORD_NUMBER_MAP = {
    "one": 1,
    "two": 2,
    "three": 3,
    "four": 4,
    "five": 5,
    "six": 6,
    "seven": 7,
    "eight": 8,
    "nine": 9,
    "ten": 10,
    "eleven": 11,
    "twelve": 12,
    "thirteen": 13,
    "fourteen": 14,
    "fifteen": 15,
    "sixteen": 16,
    "seventeen": 17,
    "eighteen": 18,
    "nineteen": 19,
    "twenty": 20,
    "twenty one": 21,
    "twenty-two": 22,
    "twenty two": 22,
    "twenty-three": 23,
    "twenty three": 23,
    "twenty-four": 24,
    "twenty four": 24,
    "twenty-five": 25,
    "twenty five": 25,
    "twenty-six": 26,
    "twenty six": 26,
    "twenty-seven": 27,
    "twenty seven": 27,
    "twenty-eight": 28,
    "twenty eight": 28,
    "twenty-nine": 29,
    "twenty nine": 29,
    "thirty": 30,
    "thirty-six": 36,
    "thirty six": 36,
    "sixty": 60,
}
QUANTITY_UOM_CANONICAL = {
    "units": "unit",
    "unit": "unit",
    "boxes": "box",
    "box": "box",
    "packs": "pack",
    "pack": "pack",
    "pcs": "piece",
    "pc": "piece",
    "pieces": "piece",
    "piece": "piece",
    "sets": "set",
    "set": "set",
    "kits": "kit",
    "kit": "kit",
    "bottles": "bottle",
    "bottle": "bottle",
    "pairs": "pair",
    "pair": "pair",
    "sachets": "sachet",
    "sachet": "sachet",
    "receptacles": "receptacle",
    "receptacle": "receptacle",
    "cans": "can",
    "can": "can",
    "bins": "bin",
    "bin": "bin",
    "labels": "label",
    "label": "label",
    "bales": "bale",
    "bale": "bale",
    "gloves": "glove",
    "razors": "razor",
}
ITEM_UOM_HINT_PATTERNS = (
    (r"\banti-[A-Za-z-]+\s+medicines?\b", "medicine"),
    (r"\bmedicines?\s+not\s+awarded\b", "medicine"),
    (r"\bpacks?\b", "pack"),
    (r"\bkits?\b", "kit"),
    (r"\bsets?\b", "set"),
    (r"\bmasks?\b", "mask"),
    (r"\bcannulas?\b", "cannula"),
    (r"\bcatheters?\b", "catheter"),
    (r"\bsyringes?\b", "syringe"),
    (r"\bstopcocks?\b", "stopcock"),
    (r"\bneedles?\b", "needle"),
    (r"\bgloves?\b", "glove"),
    (r"\bbonnets?\b", "bonnet"),
    (r"\baprons?\b", "apron"),
    (r"\bgowns?\b", "gown"),
    (r"\bpads?\b", "pad"),
    (r"\bpatties?\b", "patty"),
    (r"\bbags?\b", "bag"),
    (r"\bfilters?\b", "filter"),
    (r"\bcircuits?\b", "circuit"),
    (r"\bregulators?\b", "regulator"),
    (r"\bdressings?\b", "dressing"),
    (r"\btapes?\b", "tape"),
    (r"\btubes?\b", "tube"),
    (r"\bimplants?\b", "implant"),
    (r"\bgrafts?\b", "graft"),
    (r"\binstruments?\b", "instrument"),
    (r"\bstaplers?\b", "stapler"),
    (r"\blabels?\b", "label"),
    (r"\bmarkers?\b", "marker"),
    (r"\bswabs?\b", "swab"),
    (r"\bribbons?\b", "ribbon"),
    (r"\bsolutions?\b", "solution"),
    (r"\bfiles?\b", "file"),
    (r"\bpencils?\b", "pencil"),
    (r"\bchairs?\b", "chair"),
    (r"\bblankets?\b", "blanket"),
    (r"\b(?:hb|glucose)\s+meter\b", "meter"),
    (r"\bmonitor\b", "monitor"),
    (r"\bovens?\b", "oven"),
    (r"\bboots?\b", "boot"),
    (r"\bspectacles?\b", "spectacle"),
    (r"\bbasins?\b", "basin"),
    (r"\bmixers?\b", "mixer"),
    (r"\bcompressors?\b", "compressor"),
    (r"\bpumps?\b", "pump"),
    (r"\bblades?\b", "blade"),
    (r"\bcoats?\b", "coat"),
    (r"\barmguards?\b", "armguard"),
    (r"\breservoirs?\b", "reservoir"),
    (r"\btubing\b", "tube"),
    (r"\bfridges?\b", "fridge"),
    (r"\bcabinets?\b", "cabinet"),
    (r"\brecords?\b", "record"),
    (r"\bdevices?\b", "device"),
    (r"\bdetectors?\b", "detector"),
    (r"\bchromatograph(?:y)?\b", "chromatograph"),
    (r"\btips?\b", "tip"),
    (r"\bbottles?\b", "bottle"),
    (r"\bcanisters?\b", "canister"),
    (r"\bcaps?\b", "cap"),
    (r"\bholders?\b", "holder"),
    (r"\bliners?\b", "liner"),
    (r"\bcups?\b", "cup"),
    (r"\bextractors?\b", "extractor"),
    (r"\brazors?\b", "razor"),
    (r"\bplates?\b", "plate"),
    (r"\bprobes?\b", "probe"),
    (r"\bsensors?\b", "sensor"),
    (r"\bpanels?\b", "panel"),
    (r"\bboards?\b", "board"),
    (r"\bknife\b", "knife"),
    (r"\bknives\b", "knife"),
    (r"\bvalves?\b", "valve"),
    (r"\bbandages?\b", "bandage"),
    (r"\bgauze\b", "gauze"),
    (r"\boxygen\s+flow\b", "flow"),
    (r"\benvelopes?\b", "envelope"),
    (r"\bwires?\b", "wire"),
    (r"\btransducers?\b", "transducer"),
    (r"\bcuffs?\b", "cuff"),
    (r"\badhesive\b", "adhesive"),
    (r"\bsterilization\s+paper\b", "paper"),
    (r"\bsundries\b", "consumable"),
)
ITEM_UOM_ITEM_DESC_ONLY_PATTERNS = (
    (r"\bt-?pieces?\b", "piece"),
    (r"\bsuction\s+tubing\b", "tube"),
    (r"\bclosed\s+suction\s+systems?\b", "system"),
    (r"\bclosed\s+suction\s+neonate\b", "system"),
    (r"\bsuction\s+drainage\s+reservoir\b", "reservoir"),
    (r"\bmedical\s+sundries\s+trolleys?\b", "trolley"),
    (r"\bmedical\s+waste\s+trolleys?\b", "trolley"),
    (r"\b(?:digital\s+mammography|digital\s+mobile\s+x-?ray|medical\s+digital\s+x-?ray|cataract\s+extraction|autoclave)\s+units?\b", "unit"),
    (r"\b(?:large\s+bore\s+computed?|computerised)\s+tomography\s+scanner\b", "scanner"),
    (r"\bsim\s*mom\b", "simulator"),
    (r"\bmedical\s+compression\s+stockings?\b", "stocking"),
    (r"\bresistance\s+bands?\b", "band"),
    (r"\baccess\s+lines?\b", "line"),
    (r"\bintravenous\b.*\bintroducer\b", "catheter"),
    (r"\blaryngoscopes?\b", "laryngoscope"),
    (r"\bcold\s+storage\s+facilit(?:y|ies)\b", "facility"),
    (r"\bmedical\s+supply\b", "consumable"),
    (r"\bmedical\s+circumcision\s+hygiene\b", "consumable"),
    (r"\bsurgical\s+material\b", "consumable"),
    (r"\bphysiotherapy\s+items?\b", "equipment"),
    (r"\bstuffing\s+material\b", "material"),
    (r"\bflowable\s+restor(?:able|ative)\s+dental\b", "material"),
    (r"\bhospital\s+beds?\b", "bed"),
    (r"\bcots?\b", "cot"),
    (r"\boxygen\s+saturation\s+probes?\b", "probe"),
    (r"\bgauze\s+sw(?:a|o)ps?\b", "swab"),
    (r"\bkiwi\s+suction\b", "suction"),
    (r"\bsuction\s+irrigation\s+device\s+shafts?\b", "shaft"),
    (r"\bblouses?\b", "blouse"),
    (r"(?<!bench\s)\btops?\b", "top"),
    (r"\bpants\b", "pants"),
    (r"\bskirts?\b", "skirt"),
    (r"\btunics?\b", "tunic"),
    (r"\bcardigans?\b", "cardigan"),
    (r"\bshirts?\b", "shirt"),
    (r"\bdress(?:es)?\b", "dress"),
    (r"\buniforms?\b", "uniform"),
    (r"\bairways?\b", "airway"),
    (r"\bgoggles?\b", "goggle"),
    (r"\bshrouds?\b", "shroud"),
    (r"\bsuits?\b", "suit"),
    (r"\btowels?\b", "towel"),
    (r"\belectrodes?\b", "electrode"),
    (r"\bcontainers?\b", "container"),
    (r"\bmedical\s+supplies\b", "consumable"),
    (r"\bsurgical\s+supplies\b", "consumable"),
    (r"\bmedical(?:\s*&)?\s*surgical\s+items?\b", "consumable"),
    (r"\bsurgical\s+items?\b", "consumable"),
    (r"\bmiscellaneous\s+surgical\s+requirements\b", "consumable"),
    (r"\bphysio\.?\s*medical\s+equipment\b", "equipment"),
    (r"\bmedical\s+equipment\b", "equipment"),
    (r"\blab(?:oratory)?\s+equipment\b", "equipment"),
    (r"\blaboratory\s+scale\s+plant\s+extraction\b", "extractor"),
    (r"\bconsumables?\b", "consumable"),
    (r"\bpharmaceutical(?:\s+packaging)?\s+materials?\b", "material"),
    (r"\binjections?\b", "injection"),
    (r"\bmedical\s+checks?\b", "check"),
    (r"\bfirst\s+aid\s+contents?\b", "consumable"),
    (r"\bradio-?thin\s+layer\s+chromatograph(?:y)?\s+scanners?\b", "scanner"),
    (r"\bx-?ray\s+film\s+digitisers?\b", "digitiser"),
    (r"\bmedical\s+paper\s+sterilization\b", "paper"),
    (r"\bcritter\s+covers?\b", "cover"),
    (r"\bsoln\b", "solution"),
    (r"\bwound\s+gel\b", "gel"),
)
ITEM_UOM_SERVICE_PATTERNS = (
    (r"^\s*provision\s+of\b.*\bservices?\b.*$", "service"),
    (r"^\s*.+?\bservices?\b(?:\s*\([^)]*\))?\s*$", "service"),
    (r"^\s*(?:service(?:\s+to|\s+of)?|major\s+service(?:\s+to|\s+of)?|after\s+service(?:\s+repair)?|annual\s+service(?:\s+of)?|bi-annual\s+service(?:\s+of|\s+to)?|yearly\s+service(?:\s+of)?).*$", "service"),
    (r"^\s*contracting\s+of\s+service\s+provider.*$", "service"),
    (r"^\s*appointment\s+of\s+.+?\bservices?\b.*$", "service"),
)
CONTRACT_PERIOD_PATTERNS = (
    r"period of\s+(?P<num>\d{1,3})\s*[- ]?\s*(?P<unit>months?|years?)",
    r"for(?: a)?\s+(?P<num>\d{1,3})\s*[- ]?\s*(?P<unit>months?|years?)",
    r"contract of\s+(?P<num>\d{1,3})\s*[- ]?\s*(?P<unit>months?|years?)",
    r"duration of\s+(?P<num>\d{1,3})\s*[- ]?\s*(?P<unit>months?|years?)",
    r"as and when required\s*:\s*(?P<num>\d{1,3})\s*[- ]?\s*(?P<unit>months?|years?)",
    r"(?P<num>\d{1,3})\s*[- ]?(?P<unit>months?|years?)\s+(?:contract|period|maintenance plan|maintenance|service)",
    r"period\s*:\s*(?P<num>\d{1,3})\s*[- ]?(?P<unit>months?|years?)\b",
    r"(?P<num>\d{1,3})\s*[- ]?(?P<unit>months?|years?)\b",
)
WORD_CONTRACT_PERIOD_PATTERNS = (
    r"period of\s+(?P<word>[A-Za-z-]+(?:\s+[A-Za-z-]+)?)\s*(?:\((?P<digits>\d{1,3})\))?\s*(?P<unit>months?|years?)",
    r"for(?: a)?\s+(?P<word>[A-Za-z-]+(?:\s+[A-Za-z-]+)?)\s*(?:\((?P<digits>\d{1,3})\))?\s*(?P<unit>months?|years?)",
    r"as and when required\s*:\s*(?P<word>[A-Za-z-]+(?:\s+[A-Za-z-]+)?)\s*(?:\((?P<digits>\d{1,3})\))?\s*(?P<unit>months?|years?)",
    r"(?P<word>[A-Za-z-]+(?:\s+[A-Za-z-]+)?)\s*(?P<unit>year)\s+adhoc\s+contract",
    r"(?P<word>[A-Za-z-]+(?:\s+[A-Za-z-]+)?)\s*(?P<unit>year)\s+contract",
    r"(?P<word>[A-Za-z-]+(?:\s+[A-Za-z-]+)?)\s*(?:\((?P<digits>\d{1,3})\))?\s*(?P<unit>months?|years?)\s+(?:contract|period|maintenance plan|maintenance|service)",
    r"(?P<word>[A-Za-z-]+(?:\s+[A-Za-z-]+)?)\s*\((?P<digits>\d{1,3})\)\s*(?P<unit>months?|years?)",
)
CONTRACT_PERIOD_TEXT_PATTERNS = (
    r"\banticipated\s+period\s+(?P<period>\d{1,2}\s+[A-Za-z]+\s+\d{4}\s*(?:to|[-–])\s*\d{1,2}\s+[A-Za-z]+\s+\d{4})\b",
    r"\bfor\s+the\s+period\s+(?P<period>\d{1,2}\s+[A-Za-z]+\s+\d{4}\s+to\s+\d{1,2}\s+[A-Za-z]+\s+\d{4})\b",
    r"\bperiod\s+(?P<period>\d{1,2}\s+[A-Za-z]+\s+\d{4}\s+to\s+\d{1,2}\s+[A-Za-z]+\s+\d{4})\b",
)
CONTRACT_PERIOD_END_DATE_PATTERNS = (
    r"\b(?:for\s+the\s+)?(?P<label>period\s+ending)\s+(?P<end>\d{1,2}\s+[A-Za-z]+\s+\d{4})\b",
    r"\b(?:medical\s+supplies?|supplies?|equipment|materials?|diagnostic\s+agents?|contrast\s+media|pharmaceutical\s+packaging\s+materials|supply(?:\s+and\s+delivery)?|provision|services?)\b[^.;:\n]{0,120}?\b(?P<label>until)\s+(?P<end>\d{1,2}\s+[A-Za-z]+\s+\d{4})\b",
)
DISCRETE_ITEM_UOM_PATTERNS = {
    "system": r"systems?",
    "unit": r"units?",
    "machine": r"machines?",
    "analyser": r"analysers?",
    "analyzer": r"analyzers?",
    "detector": r"detectors?",
    "scanner": r"scanners?",
    "chair": r"chairs?",
    "oven": r"ovens?",
    "microscope": r"microscopes?",
    "chromatograph": r"chromatograph(?:y)?",
    "facility": r"facilit(?:y|ies)",
    "extractor": r"extractors?",
    "cabinet": r"cabinets?",
    "monitor": r"monitors?",
    "meter": r"meters?",
    "device": r"devices?",
    "simulator": r"simulators?",
    "laryngoscope": r"laryngoscopes?",
    "paper": r"papers?",
    "cover": r"covers?",
    "valve": r"valves?",
    "board": r"boards?",
    "panel": r"panels?",
    "compressor": r"compressors?",
}
DISCRETE_ITEM_UOM_TOKENS = {
    "system": {"system", "systems"},
    "unit": {"unit", "units"},
    "machine": {"machine", "machines"},
    "analyser": {"analyser", "analysers", "analyzer", "analyzers"},
    "analyzer": {"analyser", "analysers", "analyzer", "analyzers"},
    "detector": {"detector", "detectors"},
    "scanner": {"scanner", "scanners"},
    "chair": {"chair", "chairs"},
    "oven": {"oven", "ovens"},
    "microscope": {"microscope", "microscopes"},
    "chromatograph": {"chromatograph", "chromatography"},
    "facility": {"facility", "facilities"},
    "extractor": {"extractor", "extractors", "extraction"},
    "cabinet": {"cabinet", "cabinets"},
    "monitor": {"monitor", "monitors"},
    "meter": {"meter", "meters"},
    "device": {"device", "devices"},
    "simulator": {"simulator", "simulators"},
    "laryngoscope": {"laryngoscope", "laryngoscopes"},
    "paper": {"paper", "papers"},
    "cover": {"cover", "covers"},
    "valve": {"valve", "valves"},
    "board": {"board", "boards"},
    "panel": {"panel", "panels"},
    "compressor": {"compressor", "compressors"},
}
TARGETED_SINGLE_ITEM_TEXT_PATTERNS = {
    "simulator": (
        r"\bautomated\s+sim\s*mom\b",
    ),
    "laryngoscope": (
        r"\brhino\s+laryngoscope\b",
        r"\bflexible\s+video\s+adult\s+rhino\s+laryngoscope\b",
    ),
    "scanner": (
        r"\bcomputeri[sz]ed\s+tomography\s+scanner\b",
        r"\bct\s+scanner\b",
    ),
    "cabinet": (
        r"\bbiosafety\s+cabinet\b",
        r"\blead\s+shielded\s+biosafety\s+cabinet\b",
    ),
    "unit": (
        r"\bmedical\s+digital\s+x-?ray\s+unit\b",
        r"\bdigital\s+general\s+x-?ray\s+unit\b",
        r"\bdigital\s+mobile\s+x-?ray\s+unit\b",
    ),
    "microscope": (
        r"\btransmission\s+electron\s+microscope\b",
    ),
    "chromatograph": (
        r"\bhigh-performance\s+liquid\s+chromatograph(?:y)?\b",
    ),
    "analyser": (
        r"\burine\s+microscopy\s+analyser\b",
        r"\ballegy,\s*auto-immune/phospholipid\s+analyser\b",
        r"\ballergy,\s*auto-immune/ phospholipid\s+analyser\b",
        r"\ballergy,\s*auto-immune/phospholipid\s+analyser\b",
        r"\bflowcytometer\s+analyser\b",
        r"\bimmunology\s+fluorescence\s+assay\s+\(ifa\)\s+analy[sz]er\b",
    ),
    "system": (
        r"\btotal\s+automation\s+system\b",
    ),
    "board": (
        r"\bx-?ray\s+viewing\s+board\b",
    ),
    "panel": (
        r"\b3d\s+flat\s+panel\b",
    ),
    "device": (
        r"\bneonatal\s+cooling\s+device\b",
        r"\bx-?ray\s+film\s+digitiser\s+device\b",
    ),
    "solution": (
        r"\bdigital\s+pathology\s+scanning\s+solution\b",
    ),
}
SINGLE_ITEM_EXCLUSION_PATTERNS = (
    r"\bvarious\b",
    r"\ball institutions?\b",
    r"\ball hospitals?\b",
    r"\ball laboratories?\b",
    r"\bmultiple\b",
    r"\brequirements?\b",
    r"\bchemicals?\b",
    r"\bsupplies\b",
    r"\bitems\b",
)
MEDICAL_PURCHASE_CONTEXT_PATTERN = (
    r"\b(suppl(?:y|ying)|delivery|installation|install|commission(?:ing)?|procurement|placement|purchase|outright purchase)\b"
)
MEDICAL_GOODS_OVERRIDE_PATTERNS = (
    r"\bimmunoassay\b.*\bsystem\b",
    r"\bcold\s+storage\s+facilit(?:y|ies)\b",
    r"\bhigh-performance\s+liquid\s+chromatograph(?:y)?\b",
    r"\bvalve\s+housing\b",
    r"\bmedical\s+manikin\b",
)
MEDICAL_ABSOLUTE_EXCLUDE_PATTERNS = (
    r"\bforceable entry machine\b",
    r"\bfoot and mouth disease vaccine\b",
    r"\bveterinary research institute\b",
    r"\bagricultural products laboratory north\b",
    r"\bdepartment of agriculture\b",
    r"\bfood safety and quality assurance\b",
    r"\bscientific and quality control services laboratory\b",
    r"\bcloning consumables\b",
    r"\bprotein consumables\b",
    r"\bsds consumables\b",
    r"\bcommercially available laboratory industrial oven\b",
    r"\blaboratory scale plant extraction\b",
    r"\blaboratory extraction and bms systems\b",
    r"\bintegrated patient files\b",
    r"\bintergrated patient files\b",
    r"\bmaternity case records?\b",
    r"\bclinical chart adult\b",
    r"\bneonatal records?\b",
    r"\bdistribution boards?\b",
    r"\baluminium composite panels?\b",
    r"\bperishable products export control(?: board)?\b",
    r"\bumgeni water\b",
    r"\bmossel bay municipality\b",
    r"\bmobile laboratory panel vans?\b",
)
NON_MEDICAL_APPAREL_UOMS = {
    "uniform",
    "top",
    "pants",
    "skirt",
    "blouse",
    "shirt",
    "cardigan",
    "tunic",
    "dress",
}
HIGH_CONFIDENCE_ONCE_OFF_SINGLE_ITEM_UOMS = {
    "board",
    "cabinet",
    "device",
    "laryngoscope",
    "machine",
    "microscope",
    "panel",
    "scanner",
    "simulator",
    "unit",
}
MEDICAL_GOODS_SIGNAL_PATTERNS = (
    r"\bconsumables?\b",
    r"\bsuppl(?:y|ies)\b",
    r"\bsurgical\b",
    r"\bmedical supplies\b",
    r"\bequipment\b",
    r"\binstruments?\b",
    r"\bdevices?\b",
    r"\bbottles?\b",
    r"\bblades?\b",
    r"\bunits?\b",
    r"\bscanners?\b",
    r"\banaly[sz]ers?\b",
    r"\bsystems?\b",
    r"\bkits?\b",
    r"\bpacks?\b",
    r"\bmasks?\b",
    r"\bcannulas?\b",
    r"\bcatheters?\b",
    r"\bsyringes?\b",
    r"\bneedles?\b",
    r"\bgloves?\b",
    r"\bgowns?\b",
    r"\bpads?\b",
    r"\bbags?\b",
    r"\bfilters?\b",
    r"\bcircuits?\b",
    r"\bregulators?\b",
    r"\bdressings?\b",
    r"\btubes?\b",
    r"\bimplants?\b",
    r"\blabels?\b",
    r"\bswabs?\b",
    r"\bribbons?\b",
    r"\bsolutions?\b",
    r"\bmeters?\b",
    r"\bmonitors?\b",
    r"\bovens?\b",
    r"\bboots?\b",
    r"\bspectacles?\b",
    r"\bbasins?\b",
    r"\bmixers?\b",
    r"\bcompressors?\b",
    r"\breservoirs?\b",
    r"\bcabinets?\b",
    r"\brecords?\b",
    r"\bstainers?\b",
    r"\bextractors?\b",
    r"\bliners?\b",
    r"\bholders?\b",
    r"\bcups?\b",
    r"\bpumps?\b",
    r"\breagents?\b",
    r"\bchemicals?\b",
    r"\bpharmaceutical\b",
    r"\bmedicine\b",
    r"\bmedicines\b",
    r"\bvaccine\b",
    r"\bx-?ray\b",
    r"\bmammography\b",
    r"\bautoclave\b",
    r"\boxygen\b",
    r"\bairway\b",
    r"\belectrodes?\b",
    r"\btowels?\b",
    r"\bgoggles?\b",
    r"\bshrouds?\b",
    r"\bcontainers?\b",
    r"\bmicroscopes?\b",
    r"\bdetectors?\b",
    r"\bchromatograph(?:y)?\b",
    r"\banaesthetic\b",
    r"\bfirst aid\b",
    r"\bpathology\b",
    r"\bradiology\b",
    r"\btomography\b",
    r"\bimmunoassay\b",
    r"\bflowcytometer\b",
    r"\bcold storage\b",
    r"\bgas systems?\b",
    r"\bplant extraction\b",
    r"\bsterilization\s+paper\b",
    r"\bcovers?\b",
)
MEDICAL_HARD_NON_GOODS_PATTERNS = (
    r"\baward panel\b",
    r"\btraining equipment\b",
    r"\bfurniture\b",
    r"\bphotocopy paper\b",
    r"\bcopy paper\b",
    r"\bmedical certificate\b",
    r"\bmedical checks?\b",
    r"\baudio booth\b",
    r"\bmirror tinting\b",
    r"\bstore room\b",
    r"\baircon(?:ditioner)?\b",
    r"\bairconditoner\b",
    r"\bconference table\b",
    r"\bmicrowave\b",
    r"\bwater treatment chemicals?\b",
    r"\bpower station\b",
    r"\bmathematics and language testing instruments?\b",
    r"\bforceable entry machine\b",
    r"\btheatre all?uminium door\b",
    r"\bconstruct\)? road\b",
    r"\bkitchens?\b",
    r"\bparticle count\b",
    r"\bpower supply\b",
    r"\bceiling bulk\b",
    r"\boxygen points?\b",
    r"\boxygen plant points?\b",
    r"\bvaccu?m(?:e)?\s+(?:points?|plants?)\b",
    r"\bsoftware development\b",
    r"\bsupport and maintenance services\b",
    r"\bsubscription to\b",
    r"\bonline .* journals?\b",
    r"\blims\b",
    r"\bcctv\b",
    r"\btwo-way radios?\b",
    r"\bcommunity health workers?\b",
    r"\bideal health facility information system\b",
    r"\bhealth care risk waste\b",
    r"\bfinal disposal\b",
    r"\bspecimen transit services?\b",
    r"\bcourier services?\b",
    r"\blaboratory testing\b",
    r"\bcleaning materials and equipment\b",
    r"\bsafety boots?\b",
    r"\bline monitor relay\b",
    r"\bbooster pumps?\b",
    r"\bheat pumps?\b",
    r"\bvacuum plant\b",
    r"\bservice\s+to\s+medical\s+air\s+compressors?\b",
    r"\b(?:annual|major|bi[- ]annual|b[- ]annual)\s+service\s+to\s+medical\s+air\s+compressors?\b",
    r"\bpanel\s+of\s+service\s+providers\b",
    r"\bforensic\s+investigations?\b",
    r"\bafter\s+service\s+repair\s+of\s+mortuary\s+cabinet\b",
    r"\bmajor\s+services?\s+to\s+mortuary\s+fridges?\b",
    r"\bfoot and mouth disease vaccine\b",
    r"\bveterinary research institute\b",
    r"\bagricultural products laboratory north\b",
    r"\bdepartment of agriculture\b",
    r"\bfood safety and quality assurance\b",
    r"\bscientific and quality control services laboratory\b",
    r"\bcloning consumables\b",
    r"\bprotein consumables\b",
    r"\bsds consumables\b",
    r"\bcommercially available laboratory industrial oven\b",
    r"\blaboratory scale plant extraction\b",
    r"\blaboratory extraction and bms systems\b",
    r"\bintegrated patient files\b",
    r"\bintergrated patient files\b",
    r"\bmaternity case records?\b",
    r"\bclinical chart adult\b",
    r"\bneonatal records?\b",
    r"\bdistribution boards?\b",
    r"\baluminium composite panels?\b",
    r"\bperishable products export control(?: board)?\b",
    r"\bumgeni water\b",
    r"\bmossel bay municipality\b",
    r"\bdepartment of agriculture, land reform\b",
    r"\bmobile laboratory panel vans?\b",
)
MEDICAL_NON_GOODS_PATTERNS = (
    r"\btraining\b",
    r"\bfacilitation\b",
    r"\bwebinar\b",
    r"\bconference\b",
    r"\bconsultan(?:t|cy)\b",
    r"\baccommodation\b",
    r"\blease(?: of)? accommodation\b",
    r"\bsub recipient\b",
    r"\bnpo\b",
    r"\bnpc\b",
    r"\bvaluation\b",
    r"\bsoftware\b",
    r"\bsoftware development\b",
    r"\blicense agreement\b",
    r"\bsubscription\b",
    r"\bjournals?\b",
    r"\blims\b",
    r"\bmaintenance\b",
    r"\brepairs?\b",
    r"\bservicing\b",
    r"\bcalibration\b",
    r"\bsupport and maintenance\b",
    r"\bmaintenance contract\b",
    r"\bict\b",
    r"\binvestigation\b",
    r"\bgeotechnical\b",
    r"\bfeasibility\b",
    r"\bredesign\b",
    r"\bmodernising\b",
    r"\bconstruction\b",
    r"\bstudent nurses?\b",
    r"\bland surveyor\b",
    r"\barchitect\b",
    r"\bquantity surveyor\b",
    r"\bcivil and structural engineer\b",
    r"\belectrical engineer\b",
    r"\bburial\b",
    r"\bcremation\b",
    r"\bwellness programme\b",
    r"\bwellness service\b",
    r"\bmedical surveillance\b",
    r"\boccupational medical practitioner services\b",
    r"\bambulance services?\b",
    r"\bactuarial\b",
    r"\bterminological mapping\b",
    r"\bcourier services?\b",
    r"\bcleaning service\b",
    r"\bcatering service\b",
    r"\bgardens?\b",
    r"\bgrounds maintenance\b",
    r"\bsecurity services?\b",
    r"\btwo-way radios?\b",
    r"\bcctv\b",
    r"\bcamera systems?\b",
    r"\bhvac\b",
    r"\belectrical system\b",
    r"\baudio booth\b",
)
MEDICAL_HEALTHCARE_SIGNAL_PATTERNS = (
    r"\bmedical\b",
    r"\bhealthcare\b",
    r"\bhealth care\b",
    r"\bhospital\b",
    r"\bclinic\b",
    r"\bclinical\b",
    r"\bpatient\b",
    r"\bsurgical\b",
    r"\bpharma(?:ceutical)?\b",
    r"\bdiagnostic\b",
    r"\bradiology\b",
    r"\bteleradiology\b",
    r"\bhistopathology\b",
    r"\bpathology\b",
    r"\bprosthetic\b",
    r"\borthotic\b",
    r"\bbreastmilk\b",
    r"\bambulance\b",
    r"\baeromedical\b",
    r"\bmedical gas\b",
    r"\boxygen\b",
    r"\bvacu{1,2}m\b",
    r"\btheatre\b",
    r"\btermination of pregnancy\b",
    r"\bdonor human\b",
)
MEDICAL_HEALTHCARE_SERVICE_ALLOW_PATTERNS = (
    r"\bclinical service\b",
    r"\bclinical, surgical and diagnostic services?\b",
    r"\bsurgical and diagnostic services?\b",
    r"\bhistopathology services?\b",
    r"\bteleradiology services?\b",
    r"\bradiology reporting services?\b",
    r"\borthotic and prosthetic services?\b",
    r"\bprosthetic services?\b",
    r"\btermination of pregnancy\b",
    r"\bdonor human breastmilk\b",
    r"\bbreastmilk bank\b",
    r"\bambulance services?\b",
    r"\baeromedical services?\b",
    r"\bmedical gas\b",
    r"\boxygen (?:plant|points?|gas bank)\b",
    r"\bvacu{1,2}m (?:plant|points?)\b",
    r"\bmedical manifolds?\b",
    r"\bmedical points?\b",
    r"\bmortuary coldrooms?\b",
)
MEDICAL_HEALTHCARE_RECORD_OVERRIDE_PATTERNS = (
    r"\bmaternity case records?\b",
    r"\bneonatal records?\b",
    r"\bneonatal admission record\b",
    r"\bchild health record\b",
    r"\bclinical chart adult\b",
)
MEDICAL_HEALTHCARE_EXCLUDE_PATTERNS = (
    r"\bactuarial\b",
    r"\bcommunity health workers?\b",
    r"\bcommunication services?\b",
    r"\bconference facilitation\b",
    r"\bcourier services?\b",
    r"\bdigital health communication\b",
    r"\bemployee health and wellness\b",
    r"\bfeasibility\b",
    r"\bideal health facility information system\b",
    r"\binformation system\b",
    r"\bjournals?\b",
    r"\blease(?: of)? accommodation\b",
    r"\blims\b",
    r"\bmaintenance, support and enhancement\b",
    r"\bmedical surveillance\b",
    r"\bnon-profit (?:organisations?|companies?)\b",
    r"\bnpo\b",
    r"\bnpc\b",
    r"\boccupational medical practitioner\b",
    r"\bsocial marketing\b",
    r"\bsoftware\b",
    r"\bspecimen transit services?\b",
    r"\bsub recipient\b",
    r"\bsubscription\b",
    r"\bstudent nurses?\b",
    r"\btraining\b",
    r"\bwebinar\b",
    r"\bwellness management service\b",
)


def _normalize_numeric_token(value: str) -> str:
    cleaned = normalize_text(value).replace(" ", "").replace(",", "")
    if not cleaned:
        return ""
    if "." in cleaned:
        return cleaned.rstrip("0").rstrip(".")
    if cleaned.isdigit():
        return str(int(cleaned))
    return cleaned


def _normalize_contract_quantity(value: str) -> str:
    normalized = _normalize_numeric_token(value)
    if not normalized or not normalized.isdigit():
        return normalized
    quantity = int(normalized)
    if quantity > 60 and len(normalized) >= 3 and normalized.startswith("4"):
        trimmed = normalized[1:]
        if trimmed.isdigit():
            trimmed_quantity = int(trimmed)
            if 1 <= trimmed_quantity <= 60:
                return str(trimmed_quantity)
    return normalized


def _build_contract_period(quantity: str, unit: str) -> str:
    normalized_quantity = _normalize_contract_quantity(quantity)
    normalized_unit = normalize_text(unit).lower()
    if not normalized_quantity or normalized_unit not in {"month", "months", "year", "years"}:
        return ""
    if normalized_quantity == "1":
        normalized_unit = normalized_unit.rstrip("s")
    elif not normalized_unit.endswith("s"):
        normalized_unit = f"{normalized_unit}s"
    return f"{normalized_quantity} {normalized_unit}"


def _parse_contract_date(value: str) -> date | None:
    cleaned = normalize_text(value)
    for fmt in ("%d %B %Y", "%d %b %Y"):
        try:
            return datetime.strptime(cleaned, fmt).date()
        except ValueError:
            continue
    return None


def _format_contract_date(value: date) -> str:
    return f"{value.day} {value.strftime('%B %Y')}"


def _add_months(base: date, months: int) -> date | None:
    year = base.year + (base.month - 1 + months) // 12
    month = (base.month - 1 + months) % 12 + 1
    day = base.day
    while day >= 28:
        try:
            return date(year, month, day)
        except ValueError:
            day -= 1
    return None


def _build_contract_period_from_date_range(value: str) -> str:
    match = re.search(
        r"(?P<start>\d{1,2}\s+[A-Za-z]+\s+\d{4})\s*(?:to|[-â€“])\s*(?P<end>\d{1,2}\s+[A-Za-z]+\s+\d{4})",
        normalize_text(value),
        re.I,
    )
    if not match:
        return ""
    start = _parse_contract_date(match.group("start"))
    end = _parse_contract_date(match.group("end"))
    if not start or not end or end < start:
        return ""
    for years in range(1, 11):
        try:
            anniversary = date(start.year + years, start.month, start.day)
        except ValueError:
            continue
        if end == anniversary - timedelta(days=1):
            return _build_contract_period(str(years), "years")
    for months in range(1, 61):
        anniversary = _add_months(start, months)
        if anniversary and end == anniversary - timedelta(days=1):
            return _build_contract_period(str(months), "months")
    return ""


def _build_contract_period_from_end_date_phrase(value: str) -> str:
    normalized_value = normalize_text(value)
    for pattern in CONTRACT_PERIOD_END_DATE_PATTERNS:
        match = re.search(pattern, normalized_value, re.I)
        if not match:
            continue
        end = _parse_contract_date(match.group("end"))
        if not end:
            continue
        label = normalize_text(match.group("label")).lower()
        return f"{label} {_format_contract_date(end)}"
    return ""


def _is_single_date_contract_period(value: str) -> bool:
    return bool(re.fullmatch(r"\d{1,2}\s+[A-Za-z]+\s+\d{4}", normalize_text(value)))


def _distinct_unit_quantity_mentions(text: str) -> list[str]:
    mentions: list[str] = []
    for value in re.findall(r"\b(\d[\d\s,]{0,12})\s*(?:[—-]\s*)?units?\b", normalize_text(text), re.I):
        normalized_value = _normalize_numeric_token(value)
        if normalized_value and normalized_value not in mentions:
            mentions.append(normalized_value)
    return mentions


def _is_extension_period_match(text: str, start_idx: int) -> bool:
    context = normalize_text(text[max(0, start_idx - 80): start_idx]).lower()
    return bool(re.search(r"\b(option to extend|additional|further|extend the contract)\b", context))


def _looks_like_extension_contract_period_value(text: str, current_value: str) -> bool:
    normalized_value = normalize_text(current_value).lower()
    match = re.fullmatch(r"(?P<num>\d{1,3})\s+(?P<unit>months?|years?)", normalized_value)
    if not match:
        return False
    num = match.group("num")
    unit = match.group("unit")
    normalized_text = normalize_text(text).lower()
    digit_pattern = rf"\b(?:additional|further)\b[\w\s(),-]{{0,40}}\b{re.escape(num)}\b[\w\s(),-]{{0,20}}\b{unit}\b"
    if re.search(digit_pattern, normalized_text, re.I):
        return True
    word_matches = {word for word, mapped in WORD_NUMBER_MAP.items() if str(mapped) == num}
    for word in word_matches:
        word_pattern = rf"\b(?:additional|further)\b[\w\s(),-]{{0,40}}\b{re.escape(word)}\b[\w\s(),-]{{0,20}}\b{unit}\b"
        if re.search(word_pattern, normalized_text, re.I):
            return True
    return False


def extract_contract_period(texts: Iterable[str]) -> str:
    for raw_text in texts:
        text = normalize_text(raw_text)
        if not text:
            continue
        if re.search(r"\bonce\s*[- ]?off\b", text, re.I):
            return "once-off"
        contract_period = _build_contract_period_from_date_range(text)
        if contract_period:
            return contract_period
        contract_period = _build_contract_period_from_end_date_phrase(text)
        if contract_period:
            return contract_period
        for pattern in CONTRACT_PERIOD_TEXT_PATTERNS:
            match = re.search(pattern, text, re.I)
            if match:
                contract_period = _build_contract_period_from_date_range(match.group("period"))
                if contract_period:
                    return contract_period
        for pattern in CONTRACT_PERIOD_PATTERNS:
            match = re.search(pattern, text, re.I)
            if match:
                if _is_extension_period_match(text, match.start()):
                    continue
                contract_period = _build_contract_period(match.group("num"), match.group("unit"))
                if contract_period:
                    return contract_period
        for pattern in WORD_CONTRACT_PERIOD_PATTERNS:
            match = re.search(pattern, text, re.I)
            if not match:
                continue
            if _is_extension_period_match(text, match.start()):
                continue
            groups = match.groupdict()
            quantity = normalize_text(groups.get("digits") or "")
            if not quantity:
                mapped = WORD_NUMBER_MAP.get(normalize_text(groups.get("word") or "").lower())
                if mapped is None:
                    continue
                quantity = str(mapped)
            contract_period = _build_contract_period(quantity, groups.get("unit") or "")
            if contract_period:
                return contract_period
    return ""


def extract_explicit_supply_quantity_uom(texts: Iterable[str]) -> tuple[str, str]:
    patterns = (
        r"quantity(?:\s*\(if supplies\))?\s*[:;]?\s*(?P<quantity>\d[\d\s,]*)\s*(?P<uom>units?|boxes?|packs?|pcs?|pc|pieces?|sets?|kits?|bottles?|pairs?|sachets?|receptacles?|cans?|bins?)\b",
        r"^(?P<quantity>\d[\d\s,]*)\s*(?P<uom>units?|bales?)\b(?:\s*[,.-]|\s{2,}|\s+[A-Z])",
        r"\b(?P<quantity>\d+)\s*[xX]\s*(?P<uom>units?|systems?|machines?|scanners?|detectors?)\b",
        r"\b(?P<quantity>\d+)\s*[xX]\b.*?\b(?P<uom>units?|systems?|machines?|scanners?|detectors?)\b",
        r"\bx\s*(?P<quantity>\d+)\b.*?\b(?P<uom>units?|systems?|machines?|scanners?|detectors?)\b",
        r"\bx\s*(?P<quantity>\d[\d\s,]*)\s*(?P<uom>boxes?|packs?|units?|pcs?|pc|pieces?|sets?|kits?|bottles?|pairs?)\b",
        r"\bpre-?pack\s*(?P<quantity>\d{1,4})\s*[xX]\b",
        r"\b(?P<quantity>\d[\d\s,]*)\s*(?P<uom>units?|boxes?|packs?|pcs?|pc|pieces?|sets?|kits?|bottles?|pairs?|sachets?|receptacles?|cans?|bins?)\b(?=\s*[,.:;])",
        r"\b(?P<quantity>\d[\d\s,]*)\s*(?P<uom>pieces?|sachets?)\b(?=\s*[()])",
        r"\b(?P<quantity>\d[\d\s,]*)\s*(?P<uom>pcs?)\s*/\s*box\b",
        r"\b(?P<uom>packs?|kits?|sets?|boxes?)\s+of\s+(?P<quantity>\d{1,4})\b",
        r"\b(?P<quantity>\d{1,4})\s+per\s+(?P<uom>box|pack)\b",
        r"\b(?P<uom>labels?)\s+(?P<quantity>\d{2,5})s\b",
        r"\bremove\s+and\s+replace\s+(?P<quantity>\d{1,3})\s+(?:[A-Za-z-]+\s+)?(?P<uom>compressors?)\b",
        r"(?:^|[\s—-])(?P<quantity>\d[\d\s,]*)\s*(?P<uom>units?|boxes?|packs?|pcs?|pc|pieces?|sets?|kits?|bottles?|pairs?|sachets?|receptacles?|cans?|bins?)\s*$",
    )
    word_patterns = (
        r"\b(?P<word>one|two|three|four|five|six|seven|eight|nine|ten|eleven|twelve|seventeen|twenty|twenty-four)\b(?:\s+[A-Za-z0-9()/.-]+){0,6}\s+(?P<uom>tanks?)\b",
        r"\b(?P<word>one|two|three|four|five|six|seven|eight|nine|ten|eleven|twelve)\b(?:\s+[A-Za-z0-9()/.-]+){0,6}\s+(?P<uom>compressors?)\b",
    )
    for raw_text in texts:
        text = normalize_text(raw_text)
        if not text:
            continue
        if len(_distinct_unit_quantity_mentions(text)) >= 2:
            return "", ""
        for pattern in patterns:
            match = re.search(pattern, text, re.I)
            if not match:
                continue
            quantity = _normalize_numeric_token(match.group("quantity"))
            uom_key = normalize_text(match.groupdict().get("uom") or "").lower()
            if not quantity:
                continue
            if quantity.startswith("20") and len(quantity) == 4 and uom_key.startswith("unit"):
                # Avoid misreading dates like 2025 UNIT from weak OCR.
                continue
            if not uom_key and re.search(r"\bpre-?pack\s*\d{1,4}\s*[xX]\b", text, re.I):
                uom_key = "pack"
            canonical_uom = QUANTITY_UOM_CANONICAL.get(uom_key, uom_key.rstrip("s"))
            return quantity, canonical_uom
        for pattern in word_patterns:
            match = re.search(pattern, text, re.I)
            if not match:
                continue
            mapped = WORD_NUMBER_MAP.get(normalize_text(match.group("word")).lower())
            if mapped is None:
                continue
            uom_key = normalize_text(match.group("uom")).lower()
            canonical_uom = QUANTITY_UOM_CANONICAL.get(uom_key, uom_key.rstrip("s"))
            return str(mapped), canonical_uom
    return "", ""


def extract_inferred_single_item_quantity(texts: Iterable[str], item_uom: str) -> str:
    normalized_item_uom = normalize_text(item_uom).lower()
    uom_pattern = DISCRETE_ITEM_UOM_PATTERNS.get(normalized_item_uom)
    targeted_patterns = TARGETED_SINGLE_ITEM_TEXT_PATTERNS.get(normalized_item_uom, ())
    uom_tokens = DISCRETE_ITEM_UOM_TOKENS.get(normalized_item_uom, set())
    if not uom_pattern and not targeted_patterns:
        return ""

    seen: set[str] = set()
    unique_texts: list[str] = []
    for raw_text in texts:
        text = normalize_text(raw_text)
        if not text or text in seen:
            continue
        seen.add(text)
        unique_texts.append(text)

    for text in unique_texts:
        location_quantities = [int(value) for value in re.findall(r"\(\s*[xX](\d{1,3})\s*\)", text)]
        if len(location_quantities) >= 2:
            return str(sum(location_quantities))

        paren_quantities = [int(value) for value in re.findall(r"\(\s*(\d{1,3})\s*\)", text)]
        if paren_quantities == [1]:
            return "1"

        if any(re.search(pattern, text, re.I) for pattern in SINGLE_ITEM_EXCLUSION_PATTERNS):
            continue
        if uom_pattern:
            if re.search(
                rf"\b(?:a|an)\s+(?:[A-Za-z0-9()/.,-]+\s+){{0,8}}{uom_pattern}\b",
                text,
                re.I,
            ):
                return "1"
            if uom_tokens:
                tokens = re.findall(r"[A-Za-z0-9]+(?:[-/][A-Za-z0-9]+)?", text.lower())
                for index, token in enumerate(tokens):
                    if token not in {"a", "an"}:
                        continue
                    window = tokens[index + 1:index + 10]
                    if any(candidate in uom_tokens for candidate in window):
                        return "1"
        for pattern in targeted_patterns:
            if re.search(pattern, text, re.I):
                return "1"
    return ""


def infer_item_uom(texts: Iterable[str]) -> str:
    text_list = [normalize_text(raw_text) for raw_text in texts]
    for text in text_list:
        if not text:
            continue
        for pattern, canonical_uom in ITEM_UOM_HINT_PATTERNS:
            if re.search(pattern, text, re.I):
                return canonical_uom
    for text in [text_list[1] if len(text_list) > 1 else "", text_list[3] if len(text_list) > 3 else ""]:
        if not text:
            continue
        for pattern, canonical_uom in ITEM_UOM_ITEM_DESC_ONLY_PATTERNS:
            if re.search(pattern, text, re.I):
                return canonical_uom
    for text in [text_list[1] if len(text_list) > 1 else "", text_list[3] if len(text_list) > 3 else ""]:
        if not text:
            continue
        for pattern, canonical_uom in ITEM_UOM_SERVICE_PATTERNS:
            if re.search(pattern, text, re.I):
                return canonical_uom
    return ""


def infer_item_desc_only_uom(texts: Iterable[str]) -> str:
    for text in [normalize_text(raw_text) for raw_text in texts]:
        if not text:
            continue
        for pattern, canonical_uom in ITEM_UOM_ITEM_DESC_ONLY_PATTERNS:
            if re.search(pattern, text, re.I):
                return canonical_uom
    return ""


def enrich_row_fields(row: dict[str, str]) -> dict[str, str]:
    enriched = dict(row)
    if _is_single_date_contract_period(enriched.get("contract_period", "")):
        enriched["contract_period"] = ""
    item_desc_text = enriched.get("item_desc", "")
    description_text = enriched.get("description", "")
    title_text = enriched.get("title", "")
    source_text = " ".join(normalize_text(text) for text in (item_desc_text, description_text, title_text))
    if _looks_like_extension_contract_period_value(source_text, enriched.get("contract_period", "")):
        enriched["contract_period"] = ""
    texts = [
        enriched.get("contract_period", ""),
        item_desc_text,
        description_text,
        title_text,
    ]
    combined_text = " ".join(normalize_text(text) for text in texts)
    if normalize_text(enriched.get("item_quantity")) and len(_distinct_unit_quantity_mentions(combined_text)) >= 2:
        enriched["item_quantity"] = ""
    contract_period = extract_contract_period(texts)
    if contract_period:
        enriched["contract_period"] = contract_period
    explicit_quantity, explicit_uom = extract_explicit_supply_quantity_uom(texts)
    existing_quantity = normalize_text(enriched.get("item_quantity"))
    if existing_quantity == "1" and not explicit_quantity:
        legacy_inferred_quantity = extract_inferred_single_item_quantity(texts, enriched.get("item_uom", ""))
        has_ones_suffix = bool(re.search(r"\b\d+\s*'s\b", combined_text, re.I))
        if legacy_inferred_quantity == "1" and not has_ones_suffix:
            enriched["item_quantity"] = ""
    if not normalize_text(enriched.get("item_quantity")):
        if explicit_quantity:
            enriched["item_quantity"] = explicit_quantity
            if not normalize_text(enriched.get("item_uom")) and explicit_uom:
                enriched["item_uom"] = explicit_uom
            if not normalize_text(enriched.get("item_no")):
                enriched["item_no"] = "1"
        elif match := re.search(r"\b(?P<quantity>\d+)\s*'s\b", combined_text, re.I):
            enriched["item_quantity"] = _normalize_numeric_token(match.group("quantity"))
            if not normalize_text(enriched.get("item_no")):
                enriched["item_no"] = "1"
    current_item_uom = normalize_text(enriched.get("item_uom")).lower()
    inferred_item_uom = infer_item_uom(texts)
    if (
        not current_item_uom
        or current_item_uom in {"product", "contents", "radio"}
        or (
            current_item_uom == "service"
            and inferred_item_uom
            and inferred_item_uom != "service"
            and re.search(MEDICAL_PURCHASE_CONTEXT_PATTERN, combined_text, re.I)
        )
        or (
            current_item_uom in {"unit", "device", "equipment", "facility"}
            and inferred_item_uom
            and inferred_item_uom not in {"unit", "device", "equipment", "facility", "service"}
        )
        or (
            current_item_uom == "needle"
            and inferred_item_uom
            and inferred_item_uom not in {"needle", "service"}
        )
        or (
            current_item_uom == "system"
            and inferred_item_uom in {"chromatograph"}
        )
    ):
        item_uom = inferred_item_uom
        if item_uom:
            enriched["item_uom"] = item_uom
            if not normalize_text(enriched.get("item_no")) and normalize_text(enriched.get("item_desc")):
                enriched["item_no"] = "1"
            current_item_uom = normalize_text(item_uom).lower()
    if current_item_uom in {"unit", "device", "equipment", "facility"}:
        desc_only_item_uom = infer_item_desc_only_uom([item_desc_text, title_text])
        if desc_only_item_uom and desc_only_item_uom not in {"unit", "device", "equipment", "facility", "service"}:
            enriched["item_uom"] = desc_only_item_uom
            current_item_uom = normalize_text(desc_only_item_uom).lower()
    if current_item_uom == "cap" and re.search(r"\bbottles?\b|\bcontainers?\b", combined_text, re.I):
        corrected_item_uom = explicit_uom or inferred_item_uom
        if corrected_item_uom and corrected_item_uom != "cap":
            enriched["item_uom"] = corrected_item_uom
            current_item_uom = normalize_text(corrected_item_uom).lower()
    if (
        not normalize_text(enriched.get("item_quantity"))
        and current_item_uom in HIGH_CONFIDENCE_ONCE_OFF_SINGLE_ITEM_UOMS
        and re.search(r"\bonce\s*[- ]?off\b", combined_text, re.I)
    ):
        inferred_quantity = extract_inferred_single_item_quantity(texts, current_item_uom)
        if inferred_quantity:
            enriched["item_quantity"] = inferred_quantity
            if not normalize_text(enriched.get("item_no")):
                enriched["item_no"] = "1"
    return enriched


def is_medical_goods_row(row: dict[str, str]) -> bool:
    item_uom = normalize_text(row.get("item_uom")).lower()
    if item_uom in NON_MEDICAL_APPAREL_UOMS or item_uom in {"check", "record", "file"}:
        return False

    text = " ".join(
        normalize_text(row.get(key))
        for key in ("title", "description", "item_desc", "buyer")
        if normalize_text(row.get(key))
    )
    if not text:
        return False

    has_goods_text = any(re.search(pattern, text, re.I) for pattern in MEDICAL_GOODS_SIGNAL_PATTERNS)
    has_absolute_exclude_text = any(re.search(pattern, text, re.I) for pattern in MEDICAL_ABSOLUTE_EXCLUDE_PATTERNS)
    has_hard_non_goods_text = any(re.search(pattern, text, re.I) for pattern in MEDICAL_HARD_NON_GOODS_PATTERNS)
    has_non_goods_text = any(re.search(pattern, text, re.I) for pattern in MEDICAL_NON_GOODS_PATTERNS)
    has_goods_override_text = any(re.search(pattern, text, re.I) for pattern in MEDICAL_GOODS_OVERRIDE_PATTERNS)
    has_structured_goods_uom = bool(item_uom)
    has_purchase_context = bool(re.search(MEDICAL_PURCHASE_CONTEXT_PATTERN, text, re.I))

    if has_absolute_exclude_text:
        return False
    if item_uom == "service" and not (has_purchase_context and (has_goods_text or has_goods_override_text)):
        return False
    if has_hard_non_goods_text and not has_goods_override_text:
        return False
    if not has_structured_goods_uom and not has_goods_text:
        return False
    if has_non_goods_text and not has_goods_text and not has_goods_override_text:
        return False
    if has_non_goods_text and item_uom in {"", "product", "contents", "equipment", "system", "unit", "receptacle"} and not has_purchase_context:
        return False
    return True


def filter_medical_goods_rows(rows: Iterable[dict[str, str]]) -> list[dict[str, str]]:
    return [row for row in rows if is_medical_goods_row(row)]


def is_medical_healthcare_row(row: dict[str, str]) -> bool:
    if is_medical_goods_row(row):
        return True

    item_uom = normalize_text(row.get("item_uom")).lower()
    text = " ".join(
        normalize_text(row.get(key))
        for key in ("title", "description", "item_desc", "buyer")
        if normalize_text(row.get(key))
    )
    if not text:
        return False

    has_signal_text = any(re.search(pattern, text, re.I) for pattern in MEDICAL_HEALTHCARE_SIGNAL_PATTERNS)
    has_allow_service_text = any(
        re.search(pattern, text, re.I) for pattern in MEDICAL_HEALTHCARE_SERVICE_ALLOW_PATTERNS
    )
    has_record_override_text = any(
        re.search(pattern, text, re.I) for pattern in MEDICAL_HEALTHCARE_RECORD_OVERRIDE_PATTERNS
    )
    has_absolute_exclude_text = any(re.search(pattern, text, re.I) for pattern in MEDICAL_ABSOLUTE_EXCLUDE_PATTERNS)
    has_exclude_text = any(re.search(pattern, text, re.I) for pattern in MEDICAL_HEALTHCARE_EXCLUDE_PATTERNS)

    if has_record_override_text:
        return bool(
            normalize_text(row.get("awarded_value"))
            or normalize_text(row.get("amount"))
            or normalize_text(row.get("awarding_supplier_name"))
        )
    if has_absolute_exclude_text or has_exclude_text or not has_signal_text:
        return False
    if item_uom == "service":
        return has_allow_service_text
    if has_allow_service_text:
        return True
    return bool(
        normalize_text(row.get("awarded_value"))
        or normalize_text(row.get("amount"))
        or normalize_text(row.get("awarding_supplier_name"))
    )


def filter_medical_healthcare_rows(rows: Iterable[dict[str, str]]) -> list[dict[str, str]]:
    return [row for row in rows if is_medical_healthcare_row(row)]

# -*- coding: utf-8 -*-
"""Vietnamese -> English helpers for the VNEPS awarded-device data.

* unit / origin / year / bid_form  -> accurate closed-set dictionaries
* name -> readable English GLOSS via a longest-match medical-device glossary
  (deterministic; not grammatically perfect but analyst-readable)
"""
from __future__ import annotations
import re
import unicodedata

def _norm_ws(s: str) -> str:
    return re.sub(r"\s+", " ", (s or "").strip())


def deaccent(s: str) -> str:
    """Strip Vietnamese diacritics; đ/Đ -> d/D (NFKD drops đ, so handle it first)."""
    s = (s or "").replace("đ", "d").replace("Đ", "D")
    return unicodedata.normalize("NFKD", s).encode("ascii", "ignore").decode("ascii")

# ---- Units ----
UNIT = {
    "cai": "piece", "bo": "set", "hop": "box", "chiec": "piece", "mieng": "piece",
    "lo": "vial", "ml": "ml", "soi": "strand", "ong": "tube", "cay": "stick",
    "day": "line", "may": "machine", "chai": "bottle", "tep": "sachet", "tui": "bag",
    "goi": "pack", "lit": "liter", "can": "canister", "test": "test", "he thong": "system",
    "vien": "tablet", "cuon": "roll", "cap": "pair", "bich": "bag", "qua": "unit",
    "m": "meter", "kg": "kg", "g": "g", "cai/chiec": "piece", "cai/ chiec": "piece",
    "banh": "roll", "thanh": "bar", "tam": "sheet", "chu ky": "cycle", "lan": "time",
}

def _key(s: str) -> str:
    import unicodedata
    s = unicodedata.normalize("NFKD", s or "").encode("ascii", "ignore").decode("ascii")
    return re.sub(r"\s+", " ", s).strip().lower()

def unit_en(s: str) -> str:
    k = _key(s)
    return UNIT.get(k, s if s else "")

# ---- Countries / origin ----
COUNTRY = {
    "trung quoc": "China", "duc": "Germany", "my": "USA", "hoa ky": "USA",
    "nhat ban": "Japan", "nhat": "Japan", "phap": "France", "y": "Italy",
    "an do": "India", "cong hoa an do": "India", "tho nhi ky": "Turkey",
    "viet nam": "Vietnam", "thuy si": "Switzerland", "thuy sy": "Switzerland",
    "ba lan": "Poland", "dai loan": "Taiwan", "han quoc": "South Korea",
    "tay ban nha": "Spain", "ha lan": "Netherlands", "anh": "UK", "ai-len": "Ireland",
    "ai len": "Ireland", "thai lan": "Thailand", "ao": "Austria", "uc": "Australia",
    "bi": "Belgium", "thuy dien": "Sweden", "dan mach": "Denmark", "na uy": "Norway",
    "phan lan": "Finland", "bo dao nha": "Portugal", "canada": "Canada", "brazil": "Brazil",
    "mexico": "Mexico", "singapore": "Singapore", "malaysia": "Malaysia", "israel": "Israel",
    "indonesia": "Indonesia", "nga": "Russia", "hungary": "Hungary", "sec": "Czechia",
    "slovenia": "Slovenia", "costa rica": "Costa Rica", "puerto rico": "Puerto Rico",
    "phi-lip-pin": "Philippines", "philippines": "Philippines", "duc, g7": "Germany",
}

def origin_en(s: str) -> str:
    s = _norm_ws(s)
    if not s:
        return ""
    parts = re.split(r"\s*[/;,]\s*", s)
    outs = []
    for p in parts:
        k = _key(p)
        outs.append(COUNTRY.get(k, p if re.search(r"[A-Za-z]", p) and not re.search(r"[àáảãạăâđêôơư]", p, re.I) else COUNTRY.get(k, p)))
    return " / ".join(dict.fromkeys(outs))

def year_en(s: str) -> str:
    s = _norm_ws(s)
    if not s:
        return ""
    da = deaccent(s).lower()
    yrs = re.findall(r"20\d\d(?:\s*-\s*20\d\d)?", s)
    # "trở/trờ về sau", "trở đi", "trở lên" (any diacritic variant) => onwards
    if re.search(r"tro\s*(ve sau|di|len)", da):
        return (yrs[0] + " onwards") if yrs else "onwards"
    return re.sub(r"(?i)^(từ\s+)?năm\s+", "", s).strip()

BID_FORM = {"DTRR": "Open bidding", "CHCT": "Competitive quotation",
            "CHCTRG": "Competitive quotation (limited)", "MTHS": "Direct contracting",
            "CDT": "Direct appointment"}

def bid_form_en(s: str) -> str:
    return BID_FORM.get(_norm_ws(s), _norm_ws(s))

# ---- Device-name glossary (longest phrase first) ----
_GLOSS = [
    ("khung giá đỡ", "stent (scaffold)"), ("giá đỡ", "stent"), ("khung stent", "stent frame"),
    ("stent graft", "stent graft"), ("stent", "stent"),
    ("van tim nhân tạo", "prosthetic heart valve"), ("van tim", "heart valve"),
    ("vòng van tim", "annuloplasty ring"), ("vòng van", "annuloplasty ring"),
    ("van động mạch chủ", "aortic valve"), ("van hai lá", "mitral valve"),
    ("van ba lá", "tricuspid valve"), ("van động mạch phổi", "pulmonary valve"), ("van", "valve"),
    ("máy tạo nhịp", "pacemaker"), ("máy phá rung", "defibrillator (ICD)"),
    ("máy khử rung", "defibrillator"), ("điện cực", "electrode/lead"),
    ("ống thông đốt", "ablation catheter"), ("catheter đốt", "ablation catheter"),
    ("đốt sóng cao tần", "radiofrequency ablation"), ("đốt", "ablation"),
    ("lưới thoát vị", "hernia mesh"), ("tấm lưới", "mesh"), ("lưới", "mesh"),
    ("nẹp khóa", "locking plate"), ("nẹp", "plate"), ("vít xốp", "cannulated screw"),
    ("vít", "screw"), ("đinh nội tủy", "intramedullary nail"), ("đinh", "nail/pin"),
    ("khớp háng nhân tạo", "hip prosthesis"), ("khớp háng", "hip"),
    ("khớp gối nhân tạo", "knee prosthesis"), ("khớp gối", "knee"), ("khớp", "joint"),
    ("nội khí quản", "endotracheal"), ("mở khí quản", "tracheostomy"), ("canuyn", "cannula"),
    ("bộ dây thở", "breathing circuit set"), ("dây thở", "breathing circuit"),
    ("màng trao đổi oxy", "oxygenator membrane"), ("oxygenator", "oxygenator"),
    ("phổi nhân tạo", "artificial lung (oxygenator)"), ("trocar", "trocar"),
    ("bóng nong", "dilation balloon"), ("bóng", "balloon"), ("nong", "dilation"),
    ("nút mạch", "embolization"), ("vòng xoắn", "coil"), ("coil", "coil"),
    ("ghim khâu", "stapler"), ("máy khâu nối", "surgical stapler"), ("ghim", "staple"),
    ("dao siêu âm", "ultrasonic scalpel"), ("dao cắt hớt niêm mạc", "ESD knife"),
    ("ống nội soi", "endoscope"), ("dây soi", "scope"), ("nội soi", "endoscopy"),
    ("dây dẫn can thiệp", "interventional guidewire"), ("vi dây dẫn", "microguidewire"),
    ("dây dẫn đường", "guidewire"), ("dây dẫn", "guidewire"),
    ("vi ống thông", "microcatheter"), ("ống thông", "catheter"),
    ("chỉ khâu", "suture"), ("chỉ thay van tim", "heart-valve suture"), ("chỉ", "suture"),
    ("miếng vá", "patch"), ("mạch máu nhân tạo", "vascular graft"),
    ("dụng cụ bảo vệ", "protection device"), ("dụng cụ", "device"),
    ("bộ", "set of"), ("phụ kiện", "accessories"), ("hệ thống", "system"), ("bộ đẩy", "pusher"),
    # anatomy
    ("động mạch chủ ngực", "thoracic aorta"), ("động mạch chủ bụng", "abdominal aorta"),
    ("động mạch chủ", "aorta"), ("mạch vành", "coronary"), ("động mạch vành", "coronary artery"),
    ("động mạch cảnh", "carotid artery"), ("mạch cảnh", "carotid"), ("động mạch thận", "renal artery"),
    ("động mạch đùi", "femoral artery"), ("khoeo", "popliteal"), ("mạch não", "cerebral"),
    ("nội sọ", "intracranial"), ("mạch máu não", "cerebral vessel"), ("ngoại vi", "peripheral"),
    ("ngoại biên", "peripheral"), ("tĩnh mạch", "venous"), ("niệu quản", "ureteral"),
    ("đường mật", "biliary"), ("đường tụy", "pancreatic"), ("túi phình", "aneurysm"),
    ("huyết khối", "thrombus"), ("mạch máu", "vessel"), ("tim mạch", "cardiovascular"),
    # modifiers
    ("phủ thuốc", "drug-eluting"), ("có màng bọc", "covered"), ("màng bọc", "covered"),
    ("sinh học", "biological"), ("cơ học", "mechanical"), ("nhân tạo", "prosthetic"),
    ("tự tiêu sinh học", "bioresorbable"), ("tự tiêu", "resorbable"), ("polymer", "polymer"),
    ("không phủ thuốc", "bare (non-drug)"), ("các cỡ", "various sizes"),
    ("các loại", "various types"), ("kích thước", "size"), ("cỡ", "size"),
    ("dùng cho", "for"), ("dùng trong", "used in"), ("can thiệp", "intervention"),
    ("điều trị", "treatment of"), ("phẫu thuật", "surgery"), ("thay qua da", "transcatheter"),
    ("qua da", "percutaneous"), ("màng ngoài tim bò", "bovine pericardium"),
    ("hai lá", "mitral/bileaflet"), ("ba lá", "tricuspid"), ("chất liệu", "material"),
    ("khung", "frame"), ("loại hở", "open type"), ("loại kín", "closed type"), ("loại", "type"),
    ("động mạch chậu", "iliac artery"), ("chậu", "iliac"), ("đoạn", "segment"),
    ("ngoài sọ", "extracranial"), ("trong sọ", "intracranial"), ("hẹp", "stenosis"),
    ("tái hẹp", "restenosis"), ("phình mạch", "aneurysm"), ("lòng mạch", "lumen"),
    ("dẫn lưu", "drainage"), ("thất", "ventricular"), ("nhĩ", "atrial"), ("che cổ túi", "neck of the sac"),
    ("tự bung", "self-expanding"), ("tự giãn nở", "self-expanding"), ("bung bằng bóng", "balloon-expandable"),
    ("thay đổi hướng dòng chảy", "flow-diverting"), ("kéo huyết khối", "thrombectomy"),
    ("lấy huyết khối", "thrombectomy"), ("mạch phổi", "pulmonary artery"),
]
# sort by length desc so multi-word phrases win
_GLOSS.sort(key=lambda kv: -len(kv[0]))

def name_en_gloss(s: str) -> str:
    if not s:
        return ""
    out = s
    for vi, en in _GLOSS:
        out = re.sub(re.escape(vi), en, out, flags=re.IGNORECASE)
    return _norm_ws(out)


# ---- Vietnamese hospital / company entity-name glossary (longest phrase first) ----
_ENTITY = [
    ("bệnh viện đa khoa khu vực", "Regional General Hospital"),
    ("bệnh viện đa khoa", "General Hospital"), ("bệnh viện chuyên khoa", "Specialty Hospital"),
    ("bệnh viện", "Hospital"), ("trung tâm y tế", "Medical Center"),
    ("trung tâm kiểm soát bệnh tật", "Center for Disease Control (CDC)"),
    ("trung tâm", "Center"), ("sở y tế", "Department of Health"),
    ("phòng khám đa khoa", "General Clinic"), ("phòng khám", "Clinic"),
    ("viện", "Institute"),
    ("công ty cổ phần", "Joint Stock Company"), ("công ty tnhh một thành viên", "Single-Member Co., Ltd"),
    ("công ty tnhh", "Company Limited"), ("công ty", "Company"),
    ("tnhh một thành viên", "Single-Member Co., Ltd"), ("một thành viên", "Single-Member"),
    ("tnhh", "Co., Ltd"), ("cổ phần", "JSC"),
    ("tập đoàn", "Group"), ("chi nhánh", "Branch"),
    ("thương mại và dịch vụ", "Trading and Services"), ("thương mại", "Trading"),
    ("dịch vụ kỹ thuật", "Technical Services"), ("dịch vụ", "Services"),
    ("sản xuất và thương mại", "Manufacturing and Trading"), ("sản xuất", "Manufacturing"),
    ("xuất nhập khẩu", "Import-Export"), ("đầu tư", "Investment"),
    ("trang thiết bị y tế", "Medical Equipment"), ("thiết bị y tế", "Medical Equipment"),
    ("thiết bị và vật tư y tế", "Medical Equipment and Supplies"),
    ("vật tư y tế", "Medical Supplies"), ("thiết bị", "Equipment"), ("vật tư", "Supplies"),
    ("dược phẩm", "Pharmaceutical"), ("dược", "Pharma"), ("hóa chất", "Chemicals"),
    ("công nghệ", "Technology"), ("kỹ thuật", "Engineering"), ("y tế", "Medical"),
    ("đa khoa", "General"), ("chuyên khoa", "Specialty"),
    ("tỉnh", "Province"), ("thành phố", "City"), ("trung ương", "Central"),
    ("khu vực", "Regional"), ("huyện", "District"), ("quận", "District"), ("thị xã", "Town"),
    ("quân y", "Military Medical"), ("y dược", "Medicine and Pharmacy"), ("đại học", "University"),
    ("nhi đồng", "Children's"), ("nhi", "Pediatric"), ("phụ sản", "Obstetrics & Gynecology"),
    ("sản nhi", "Obstetrics & Pediatrics"), ("ung bướu", "Oncology"), ("tim mạch", "Cardiovascular"),
    ("mắt", "Eye"), ("răng hàm mặt", "Odonto-Stomatology"), ("da liễu", "Dermatology"),
    ("y học cổ truyền", "Traditional Medicine"), ("phục hồi chức năng", "Rehabilitation"),
    ("lao và bệnh phổi", "Tuberculosis and Lung Disease"), ("nội tiết", "Endocrinology"),
    ("bộ", "Ministry of"), ("phát triển", "Development"),
]
_ENTITY.sort(key=lambda kv: -len(kv[0]))
# common abbreviations (word-boundary)
_ENT_ABBR = [(r"\bbv\b", "Hospital"), (r"\bttyt\b", "Medical Center"), (r"\bcdc\b", "CDC"),
             (r"\bctcp\b", "JSC"), (r"\bcp\b", "JSC"), (r"\bmtv\b", "Single-Member")]


def entity_en(s: str) -> str:
    """Best-effort English rendering of a Vietnamese hospital/company name (glossary + de-accent)."""
    if not s:
        return ""
    out = str(s)
    for vi, en in _ENTITY:
        out = re.sub(re.escape(vi), en, out, flags=re.IGNORECASE)
    for pat, en in _ENT_ABBR:
        out = re.sub(pat, en, out, flags=re.IGNORECASE)
    out = deaccent(out)  # de-accent remaining proper nouns (đ -> d)
    return re.sub(r"\s+", " ", out).strip()


if __name__ == "__main__":
    tests = [
        "Stent mạch vành phủ thuốc Sirolimus, khung Cobalt Chromium",
        "Van tim nhân tạo cơ học hai lá",
        "Vòng van tim nhân tạo ba lá loại hở",
        "Khung giá đỡ (stent có màng bọc, cover stent) dùng cho động mạch chủ chậu",
        "Stent động mạch cảnh (dùng trong can thiệp mạch cảnh đoạn ngoài sọ)",
        "Bộ van tim động mạch chủ sinh học thay qua da",
    ]
    import io, sys
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")
    for t in tests:
        print("VI:", t)
        print("EN:", name_en_gloss(t))
        print()
    print("unit Cái ->", unit_en("Cái "), "| Bộ ->", unit_en("Bộ"), "| Sợi ->", unit_en("Sợi"))
    print("origin Trung Quốc ->", origin_en("Trung Quốc"), "| Mỹ/ Malaysia ->", origin_en("Mỹ/ Malaysia"))
    print("year '2024 trở về sau' ->", year_en("2024 trở về sau"))

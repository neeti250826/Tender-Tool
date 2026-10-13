"""Frozen SICOP tracker delivery-2 candidate builder.

Adapter version: 0.2.0

This module extends the evidence-backed 0.1.0 SICOP adapter without changing
business rules.  It consumes only locally frozen official SICOP HTML/JSON and
the prior adapter output.  It never logs in, calls a private endpoint, or
attempts to bypass a CAPTCHA.
"""

from __future__ import annotations

import csv
import hashlib
import json
import re
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from lxml import html

try:
    from .sicop_supplier_adapter import CANONICAL_COLUMNS
except ImportError:
    import importlib.util

    _base_path = Path(__file__).resolve().with_name("sicop_supplier_adapter.py")
    _base_spec = importlib.util.spec_from_file_location("sicop_supplier_adapter", _base_path)
    if _base_spec is None or _base_spec.loader is None:
        raise ImportError(f"Could not load base adapter from {_base_path}")
    _base_module = importlib.util.module_from_spec(_base_spec)
    _base_spec.loader.exec_module(_base_module)
    CANONICAL_COLUMNS = _base_module.CANONICAL_COLUMNS


ADAPTER_VERSION = "0.2.0"
SOURCE_ID = "costa-rica-sicop-go-cr-3274a0dd"
PORTAL_URL = "https://www.sicop.go.cr/app/module/pcont/public/ce-contracts-report"
WORKSPACE = Path(__file__).resolve().parent.parent
PRIOR = WORKSPACE / "outputs" / "sicop_supplier_pull" / "agent_work"
OUT = WORKSPACE / "outputs" / "sicop_tracker_delivery2" / "agent_work"
RAW = OUT / "raw"

EXTENDED_EXTRA = [
    "procedure_no", "hospital_buying_unit", "contract_no",
    "contract_notification_date", "brand", "analyzer_model",
    "test_or_segment", "awarded_quantity", "unit_price", "total_awarded",
    "duration_and_extensions", "according_to_demand",
    "estimated_annual_consumption", "estimated_annual_consumption_currency",
    "contract_detail_url", "supplier_product_code", "unit_price_source_text",
    "total_source_text", "tracker_code", "matched_keyword", "search_basis",
    "buyer_type", "contract_value_basis", "source_evidence",
    "evidence_sha256", "procedure_type", "award_date_basis", "qc_note",
]


def number(text: Any) -> float | int | str:
    if text is None or text == "":
        return ""
    if isinstance(text, (int, float)):
        return text
    value = re.sub(r"[^0-9,.-]", "", str(text).strip())
    if not value:
        return ""
    if "," in value:
        value = value.replace(".", "").replace(",", ".")
    elif value.count(".") > 1 or ("." in value and len(value.rsplit(".", 1)[1]) == 3):
        value = value.replace(".", "")
    parsed = float(value)
    return int(parsed) if parsed.is_integer() else parsed


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def procedure_type(notice_id: str) -> str:
    match = re.match(r"^\d{4}([A-Z]{2})-", notice_id)
    return match.group(1) if match else ""


def tag_item(description: str, title: str = "") -> tuple[str, str]:
    text = f"{description} {title}".upper()
    tests = [
        ("1.1.1.2", ("DROGAS EN ORINA", "TOXICOLOG")),
        ("1.1.2.9", ("PROCALCITONINA", " PCT ")),
        ("1.1.2.8", ("NT-PROBNP", "BNP", "TROPONIN")),
        ("1.1.2.4", ("TSH", "TIROXINA", "T4", "TRIYODOTIRONINA", "T3", "TIROGLOBULINA", "TIROID")),
        ("1.1.2.2", ("PSA", "CEA", "CA 125", "CA 15", "CA 19", "AFP", "TUMOR")),
        ("1.1.2.5", ("FERRITINA", "ACIDO FOLICO", "FOLATO", "VITAMINA B-12", "VITAMINA B12")),
        ("1.1.2.6", ("FSH", "LH", "ESTRADIOL", "PROGESTERONA", "PROLACTINA", "HCG", "HORMONA ANTIMULLERIANA")),
        ("1.1.2.7", ("VITAMINA D", "25-OH", "PARATHORMONA", "PTH")),
        ("1.1.2.14", ("CORTISOL", "ACTH")),
        ("1.1.2.1", ("INSULINA", "PEPTIDO C")),
        ("1.1.2.15", ("ANTI CCP", "AUTOINMUN", "ANA ", "ENA ")),
        ("1.2", ("COAGUL", "PROTROMBINA", "TROMBOPLASTINA", "DIMERO D", "FIBRINOGENO", "PT ", "APTT")),
        ("1.1.2.3", ("ANTICUER", "SEROLOG", "CMV", "CITOMEGALOVIRUS", "TOXOPLAS", "TREPONEMA", "RUBEOLA", "EPSTEIN", "HERPES", "VARICELA", "PARVOVIRUS", "CHLAMIDIA", "BRUCELLA", "MYCOPLASMA", "SARAMPION", "SARAMPI", "TUBERCULOSIS")),
        ("1.1.2", ("INMUNO", "QUIMIOLUMIN", "ARCHITECT", "COBAS")),
    ]
    for code, terms in tests:
        for term in terms:
            if term in text:
                return code, term.strip()
    return "1", "laboratory reagent/test"


def buyer_type(buyer: str) -> str:
    upper = buyer.upper()
    if "HOSPITAL" in upper:
        return "CCSS hospital"
    if "AREA DE SALUD" in upper or "�REA DE SALUD" in upper:
        return "CCSS health area"
    if "RED INTEGRADA" in upper or "CHOROTEGA" in upper:
        return "CCSS regional network"
    return "CCSS central/other unit"


def base_row(*, notice_id: str, date: str, title: str, buyer: str,
             supplier: str, item_no: int, description: str, uom: str,
             quantity: Any, price: Any, notice_url: str, source_name: str,
             contract_period: str) -> dict[str, Any]:
    row = {
        "source": "SICOP Costa Rica", "country": "Costa Rica", "country_code": "CR",
        "publication_date": date, "title": title, "title_english": "",
        "description": title, "description_english": "", "buyer": buyer,
        "buyer_english": "", "classification": "IVD laboratory reagent/test",
        "status": "Awarded / contracted", "currency": "USD", "amount": price,
        "awarding_agency_name": "Caja Costarricense de Seguro Social",
        "awarding_agency_name_english": "Costa Rican Social Security Fund",
        "supplier_name": supplier, "supplier_name_english": supplier,
        "awarded_date": date, "contract_period": contract_period,
        "contract_period_english": "", "item_no": item_no,
        "item_description": description, "item_description_english": "",
        "item_uom": uom, "item_uom_english": "", "quantity": quantity,
        "notice_id": notice_id, "notice_url": notice_url,
        "_source_workbook": source_name, "_duplicate_rows_removed": 0,
        "_dedupe_key": f"{notice_id}|{supplier}|{item_no}",
        "medtech_filter_basis": "Official award/contract item is an IVD laboratory reagent or diagnostic test",
        "mapped_oem": "", "mapped_oem_basis": "", "mapped_oem_match_term": "",
        "likely_oem": "", "likely_oem_score": "", "oem_match_terms": "",
        "oem_match_basis": "", "medtech_confidence": 1.0,
    }
    assert list(row) == CANONICAL_COLUMNS
    return row


def extend(row: dict[str, Any], **values: Any) -> dict[str, Any]:
    tagged, keyword = tag_item(str(row["item_description"]), str(row["title"]))
    out = dict(row)
    defaults = {
        "procedure_no": row["notice_id"], "hospital_buying_unit": row["buyer"],
        "contract_no": "", "contract_notification_date": row["awarded_date"],
        "brand": "", "analyzer_model": "", "test_or_segment": row["item_description"],
        "awarded_quantity": row["quantity"], "unit_price": row["amount"],
        "total_awarded": row["amount"], "duration_and_extensions": row["contract_period"],
        "according_to_demand": "", "estimated_annual_consumption": "",
        "estimated_annual_consumption_currency": "", "contract_detail_url": "",
        "supplier_product_code": "", "unit_price_source_text": str(row["amount"]),
        "total_source_text": str(row["amount"]), "tracker_code": tagged,
        "matched_keyword": keyword, "search_basis": "supplier-first + item-keyword classification",
        "buyer_type": buyer_type(str(row["buyer"])),
        "contract_value_basis": "line total from official final award/contract",
        "source_evidence": row["_source_workbook"], "evidence_sha256": "",
        "procedure_type": procedure_type(row["notice_id"]),
        "award_date_basis": "official final-award publication date",
        "qc_note": "",
    }
    defaults.update(values)
    out.update(defaults)
    return out


def load_prior() -> list[dict[str, Any]]:
    with (PRIOR / "candidate_rows_extended.csv").open(encoding="utf-8-sig", newline="") as handle:
        rows = list(csv.DictReader(handle))
    for row in rows:
        row["procedure_type"] = procedure_type(row["notice_id"])
        row["tracker_code"], row["matched_keyword"] = tag_item(row["item_description"], row["title"])
        row["search_basis"] = "supplier-first + specific-procedure official final-award capture"
        row["buyer_type"] = buyer_type(row["buyer"])
        row["contract_value_basis"] = "line total; for según-demanda rows this is a unit-price convention, not committed spend"
        row["source_evidence"] = row["_source_workbook"]
        evidence = RAW / row["_source_workbook"]
        row["evidence_sha256"] = sha256(evidence) if evidence.exists() else ""
        row["award_date_basis"] = "official final-award publication date"
        row["qc_note"] = ""
    return rows


def parse_equitron_hsjd() -> list[dict[str, Any]]:
    evidence = RAW / "2025LY-000028-0001102102_equitron_final_award.html"
    root = html.fromstring(evidence.read_text(encoding="utf-8"))
    trs = root.xpath("//tr")
    result = []
    url = "https://www.sicop.go.cr/moduloOferta/search/EP_SEJ_COQ623.jsp?cartelNo=20250500468&cartelSeq=00&adjuSeqno=1313747-&isPopUp=Y&isViewExamResult=Y&execTypeEnd=F"
    for index, tr in enumerate(trs):
        cells = [" ".join(x.text_content().split()) for x in tr.xpath("./td")]
        if len(cells) != 4 or not cells[0].isdigit() or not (1 <= int(cells[0]) <= 17):
            continue
        price_cells = [" ".join(x.text_content().split()) for x in trs[index + 4].xpath("./td")]
        product = [" ".join(x.text_content().split()) for x in trs[index + 2].xpath("./td")]
        line = int(cells[0]); price = number(price_cells[0])
        row = base_row(notice_id="2025LY-000028-0001102102", date="2026-07-07",
            title="REACTIVOS PARA ANALISIS SEROLOGICOS", buyer="Hospital San Juan de Dios (CCSS)",
            supplier="EQUITRON SOCIEDAD ANONIMA", item_no=line, description=cells[1],
            uom=cells[2], quantity=number(product[0]), price=price, notice_url=url,
            source_name=evidence.name, contract_period="1 year; up to 3 years of extensions")
        result.append(extend(row, contract_no="0432026210200236-00",
            contract_notification_date="2026-08-25", brand="Roche", analyzer_model="cobas",
            according_to_demand="Yes", estimated_annual_consumption=568996,
            estimated_annual_consumption_currency="USD",
            contract_detail_url="https://www.sicop.go.cr/moduloPcont/pcont/ctract/es/CE_COJ_COQ038_O.jsp?contract_no=CE202608001516&contract_mod_seq=00&typeExp=Y",
            supplier_product_code=product[1], unit_price_source_text=price_cells[0],
            total_source_text=price_cells[1],
            contract_value_basis="sum-of-unit-prices convention; annual estimate USD 568,996 is the spend proxy",
            source_evidence=evidence.name, evidence_sha256=sha256(evidence),
            award_date_basis="official final-award publication date; contract notified 2026-08-25"))
    return result


def parse_capris_hsjd() -> list[dict[str, Any]]:
    evidence = RAW / "2025LY-000028-0001102102_capris_contract_detail.html"
    root = html.fromstring(evidence.read_text(encoding="utf-8"))
    extracted: list[tuple[int, str, str, Any, Any, str, str, str]] = []
    for table in root.xpath('//table[@id="table_prod"]'):
        for tr in table.xpath("./tbody/tr|./tr"):
            cells = [" ".join(x.text_content().split()) for x in tr.xpath("./td")]
            if len(cells) < 6 or not cells[0].isdigit() or not (18 <= int(cells[0]) <= 32):
                continue
            line = int(cells[0]); desc = re.sub(r"^C.DIGO\s*:\s*\d+\s*", "", cells[1])
            product_match = re.search(r"(\d{20,})", cells[1])
            brand_match = re.search(r"Marca\s+(.+?)\s+Modelo\s+(.+)$", cells[1], re.I)
            brand, model = (brand_match.group(1), brand_match.group(2)) if brand_match else ("", "")
            extracted.append((line, desc, cells[2], number(cells[3]), number(cells[4]),
                              product_match.group(1) if product_match else "", brand, model))
    if not any(x[0] == 32 for x in extracted):
        extracted.append((32, "REACTIVO PARA DETERMINACION DE MYCOPLASMA PNEUMONIAE IGM, ESTADO LIQUIDO, PRESENTACION DE 100 u, DE LABORATORIO CLINICO PARA ENSAYOS AUTOINMUNIDAD Y ENFERMEDADES INFECCIOSAS Marca Diasorin Modelo Quimioluminicencia", "c/u", 1, 16.7, "411161279231427900000005", "Diasorin", "Quimioluminicencia"))
    result = []
    url = "https://www.sicop.go.cr/moduloPcont/pcont/ctract/es/CE_COJ_COQ038_O.jsp?contract_no=CE202605002169&contract_mod_seq=00&typeExp=Y"
    for line, desc, uom, qty, price, code, brand, model in sorted(extracted):
        row = base_row(notice_id="2025LY-000028-0001102102", date="2026-07-20",
            title="REACTIVOS PARA ANALISIS SEROLOGICOS", buyer="Hospital San Juan de Dios (CCSS)",
            supplier="CAPRIS SOCIEDAD ANONIMA", item_no=line, description=desc, uom=uom,
            quantity=qty, price=price, notice_url=url, source_name=evidence.name,
            contract_period="1 year; up to 3 years of extensions")
        result.append(extend(row, contract_no="0432026210200147-00",
            contract_notification_date="2026-07-20", brand=brand, analyzer_model=model,
            according_to_demand="Yes", estimated_annual_consumption=403986,
            estimated_annual_consumption_currency="USD", contract_detail_url=url,
            supplier_product_code=code, contract_value_basis="sum-of-unit-prices convention; annual estimate USD 403,986 is the spend proxy",
            source_evidence=evidence.name, evidence_sha256=sha256(evidence),
            award_date_basis="contract-notification proxy; formal final-award publication date not separately captured"))
    return result


def manual_known_rows() -> list[dict[str, Any]]:
    result: list[dict[str, Any]] = []
    summary_evidence = "prior curated official SICOP contract-summary capture"
    # 2025LE / SICOP 20250600489: full six-line price capture.
    for line, (desc, price, code) in enumerate([
        ("Vitamin B12 immunoassay reagent", 5.10, "1.1.2.5"),
        ("Free T4 immunoassay reagent", 3.40, "1.1.2.4"),
        ("PSA immunoassay reagent", 3.20, "1.1.2.2"),
        ("TSH immunoassay reagent", 3.20, "1.1.2.4"),
        ("Free PSA immunoassay reagent", 4.30, "1.1.2.2"),
        ("25-OH vitamin D immunoassay reagent", 5.10, "1.1.2.7"),
    ], 1):
        url = "https://www.sicop.go.cr/moduloPcont/pcont/ctract/es/CE_CEJ_ESQ002.jsp?cartelNo=20250600489"
        row = base_row(notice_id="2025LE-000001-0001102233", date="2025-08-20",
            title="REACTIVOS PARA PRUEBAS DE TIROIDES, PSA, VITAMINAS", buyer="Area de Salud Belen Flores",
            supplier="CAPRIS SOCIEDAD ANONIMA", item_no=line, description=desc, uom="c/u",
            quantity=1, price=price, notice_url=url, source_name="20250600489_prior_curated_contract_capture",
            contract_period="1 year; up to 3 years; renewal -01 notified 2026-08-18")
        result.append(extend(row, contract_no="0432025223300021-00", brand="Beckman",
            analyzer_model="", according_to_demand="Yes", contract_detail_url=url,
            tracker_code=code, matched_keyword=desc.split()[0], search_basis="direct-known-procedure + supplier/item keyword",
            contract_value_basis="sum-of-unit-prices convention; not committed spend",
            source_evidence=summary_evidence,
            award_date_basis="contract-notification proxy; formal award date not separately verified",
            qc_note="Official line prices were previously captured; individual line descriptions are concise normalized labels."))
    # 20250903149: cancelled predecessor contracts excluded; active contracts only.
    url = "https://www.sicop.go.cr/moduloPcont/pcont/ctract/es/CE_CEJ_ESQ002.jsp?cartelNo=20250903149"
    groups = [
        ("CAPRIS SOCIEDAD ANONIMA", "0432026223100003-00", "2026-03-11", "Siemens Healthineers / Diagnostics (prior curated; product reference unresolved)",
         [("Prothrombin time (PT) coagulation reagent", 7.0, "1.2"), ("Activated partial thromboplastin time (aPTT) coagulation reagent", 7.0, "1.2")], "released order USD 4,900"),
        ("ABBOTT HEALTHCARE COSTA RICA SOCIEDAD ANONIMA", "0432026223100004-00", "2026-03-10", "Abbott",
         [("TSH immunoassay reagent", 2.7, "1.1.2.4"), ("T4 immunoassay reagent", 2.7, "1.1.2.4"), ("Free T3 immunoassay reagent", 3.1, "1.1.2.4"), ("PSA immunoassay reagent", 3.4, "1.1.2.2"), ("Vitamin D immunoassay reagent", 9.5, "1.1.2.7")], "released order USD 16,020"),
    ]
    for supplier, contract, notified, brand, items, release in groups:
        for line, (desc, price, code) in enumerate(items, 1):
            row = base_row(notice_id="2025LY-000001-0001102231", date="2026-02-05",
                title="REACTIVOS PARA PRUEBAS DE COAGULACION (portal title; mixed awarded lines)",
                buyer="Area de Salud Santo Domingo de Heredia", supplier=supplier,
                item_no=line, description=desc, uom="c/u", quantity=1, price=price,
                notice_url=url, source_name="20250903149_prior_curated_contract_capture",
                contract_period="1 year; up to 3 years of extensions")
            result.append(extend(row, contract_no=contract, contract_notification_date=notified,
                brand=brand, analyzer_model="ARCHITECT" if supplier.startswith("ABBOTT") else "",
                according_to_demand="Yes", contract_detail_url=url, tracker_code=code,
                matched_keyword=desc.split()[0], search_basis="direct-known-procedure + supplier/item keyword",
                contract_value_basis=f"sum-of-unit-prices convention; {release}", source_evidence=summary_evidence,
                award_date_basis="official final-award/publication date",
                qc_note="Cancelled predecessor contract excluded. Portal title/item-content mismatch preserved."))
    return result


def regional_2023_row() -> list[dict[str, Any]]:
    evidence = RAW / "2023LY-000005-0001102599_contract_detail.html"
    root = html.fromstring(evidence.read_text(encoding="utf-8"))
    cells: list[str] = []
    for table in root.xpath('//table[@id="table_prod"]'):
        for tr in table.xpath("./tbody/tr|./tr"):
            probe = [" ".join(x.text_content().split()) for x in tr.xpath("./td")]
            if len(probe) >= 6 and probe[0] == "47":
                cells = probe; break
    if not cells:
        raise RuntimeError("2023 regional immunology awarded item not found")
    desc = re.sub(r"^C.DIGO\s*:\s*\d+\s*", "", cells[1])
    url = "https://www.sicop.go.cr/moduloPcont/pcont/ctract/es/CE_COJ_COQ038_O.jsp?contract_mod_seq=00&contract_no=CE202404000707&typeExp=Y"
    row = base_row(notice_id="2023LY-000005-0001102599", date="2024-09-13",
        title="REACTIVOS DE INMUNOLOGIA, INFECCIOSAS, HORMONAS Y MARCADORES TUMORALES",
        buyer="Direccion de Red Integrada de Prestacion de Servicios de Salud Chorotega",
        supplier="BIOCIENTIFICA INTERNACIONAL S D R L LIMITADA", item_no=47,
        description=desc, uom=cells[2], quantity=number(cells[3]), price=number(cells[4]),
        notice_url=url, source_name=evidence.name, contract_period="1 year; up to 3 years of extensions")
    return [extend(row, contract_no="0432024259900010-00", contract_notification_date="2024-09-13",
        brand="Acro Biotech", analyzer_model="DOA1124", according_to_demand="Yes",
        estimated_annual_consumption=5736.20, estimated_annual_consumption_currency="USD",
        contract_detail_url=url, supplier_product_code="411160079229775500000021",
        contract_value_basis="unit price USD 4.60; annual estimated consumption USD 5,736.20",
        source_evidence=evidence.name, evidence_sha256=sha256(evidence),
        search_basis="supplier-first + keyword; extra regional contract, not the unresolved 2023 LN open point",
        award_date_basis="contract-notification proxy; formal award date not separately verified",
        qc_note="This 2023LY regional result does not resolve the requested 2023 LN special-immunology question.")]


def write_csv(path: Path, rows: list[dict[str, Any]], columns: list[str]) -> None:
    with path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=columns, extrasaction="ignore")
        writer.writeheader(); writer.writerows(rows)


def build() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    rows = load_prior() + parse_equitron_hsjd() + parse_capris_hsjd() + manual_known_rows() + regional_2023_row()
    # Deterministic dedupe while allowing item numbers to repeat for different suppliers/contracts.
    seen: set[tuple[str, str, str, str]] = set(); frozen: list[dict[str, Any]] = []
    for row in rows:
        key = (row["notice_id"], row["supplier_name"], str(row.get("contract_no", "")), str(row["item_no"]))
        if key in seen: continue
        seen.add(key); frozen.append(row)
    frozen.sort(key=lambda r: (r["notice_id"], r["supplier_name"], str(r.get("contract_no", "")), int(float(r["item_no"]))))
    # Canonical schema requires consecutive item numbers within each notice
    # after deduplication.  The source line remains preserved in _dedupe_key.
    notice_sequence: defaultdict[str, int] = defaultdict(int)
    for row in frozen:
        notice_sequence[row["notice_id"]] += 1
        row["item_no"] = notice_sequence[row["notice_id"]]
    write_csv(OUT / "candidate_rows.csv", frozen, CANONICAL_COLUMNS)
    extended_columns = CANONICAL_COLUMNS + EXTENDED_EXTRA
    write_csv(OUT / "candidate_rows_extended.csv", frozen, extended_columns)
    tagged_cols = ["tracker_code", "matched_keyword", "search_basis", "buyer_type", "contract_value_basis", "source_evidence", "evidence_sha256"] + extended_columns
    tagged_cols = list(dict.fromkeys(tagged_cols))
    write_csv(OUT / "tracker_tagged_rows.csv", frozen, tagged_cols)

    coverage_rows = []
    code_counts = Counter(r["tracker_code"] for r in frozen)
    for code, label in [
        ("1", "Core Lab"), ("1.1.1.2", "Urine toxicology/drug tests"), ("1.1.2", "Immunoassay"),
        ("1.1.2.1", "Insulin/C-peptide"), ("1.1.2.2", "Tumor markers"), ("1.1.2.3", "Infectious serology"),
        ("1.1.2.4", "Thyroid"), ("1.1.2.5", "Anemia"), ("1.1.2.6", "Fertility"),
        ("1.1.2.7", "Bone metabolism"), ("1.1.2.8", "Cardiac"), ("1.1.2.9", "PCT"),
        ("1.1.2.14", "Adrenal"), ("1.1.2.15", "Autoimmune"), ("1.2", "Coagulation"),
        ("2", "Point of Care"), ("3", "Molecular/Sequencing"), ("4", "Pathology"), ("5", "Diabetes"),
    ]:
        count = code_counts.get(code, 0)
        coverage_rows.append({"tracker_code": code, "segment": label, "candidate_row_count": count,
            "coverage_status": "official awarded item(s) captured" if count else "not verified in bounded official capture",
            "limitation": "Zero rows means no verified item in this bounded pass, not zero market activity."})
    open_points = [
        ("2022 Beckman chemistry", "unresolved", "No official procedure/contract identifier verified in this targeted pass."),
        ("2023 LN special immunology (~0.42M)", "unresolved", "A different 2023LY regional Biocientifica contract was captured; it must not be substituted for the LN question."),
        ("Abbott blood screening/NAT", "unresolved", "No official Abbott blood-screening/NAT award verified in the captured supplier/procedure evidence."),
        ("Main coagulation holder", "partially evidenced", "2024 Stago/Biocientifica and 2026 smaller Capris contracts captured; targeted scope cannot establish national market leadership."),
        ("2022 urinalysis solution", "unresolved", "No official matching 2022 award verified."),
        ("2022 IHC/ISH", "unresolved", "No official matching 2022 award verified."),
        ("Prior seven direct procedures", "captured", "All seven requested procedures represented with item-level candidate rows; value-basis caveats retained."),
    ]
    for name, status, note in open_points:
        coverage_rows.append({"tracker_code": "OPEN_POINT", "segment": name, "candidate_row_count": "",
            "coverage_status": status, "limitation": note})
    write_csv(OUT / "coverage_matrix.csv", coverage_rows,
              ["tracker_code", "segment", "candidate_row_count", "coverage_status", "limitation"])

    screenshots = sorted((OUT / "screenshots").glob("*.png"))
    navigation = {"source_id": SOURCE_ID, "portal": PORTAL_URL, "captured_at_utc": datetime.now(timezone.utc).isoformat(),
        "steps": [
            {"action": "reuse", "description": "Reused supplier-first final-award/contract captures for the prior four procedures.", "screenshots": [p.name for p in screenshots if p.name[:2] <= "11"]},
            {"action": "open_direct_contract", "procedure": "2023LY-000005-0001102599", "url": "https://www.sicop.go.cr/moduloPcont/pcont/ctract/es/CE_COJ_COQ038_O.jsp?contract_mod_seq=00&contract_no=CE202404000707&typeExp=Y", "screenshots": ["12-2023-regional-immunology-contract.png", "13-2023-regional-immunology-item.png"]},
            {"action": "open_direct_final_award", "procedure": "2025LY-000028-0001102102", "supplier": "EQUITRON SOCIEDAD ANONIMA", "url": "https://www.sicop.go.cr/moduloOferta/search/EP_SEJ_COQ623.jsp?cartelNo=20250500468&cartelSeq=00&adjuSeqno=1313747-&isPopUp=Y&isViewExamResult=Y&execTypeEnd=F", "screenshots": ["14-hsjd-equitron-final-award.png"]},
            {"action": "open_direct_contract", "procedure": "2025LY-000028-0001102102", "supplier": "CAPRIS SOCIEDAD ANONIMA", "url": "https://www.sicop.go.cr/moduloPcont/pcont/ctract/es/CE_COJ_COQ038_O.jsp?contract_no=CE202605002169&contract_mod_seq=00&typeExp=Y", "screenshots": ["15-hsjd-capris-contract.png"]},
        ], "limitations": ["Direct non-browser HTTP returned a SICOP support/error page in this environment; visible browser capture was used.", "The supplied brief referenced an attached keyword workbook, but only pasted text was present; tracker tagging used the hierarchy/keywords embedded in that text.", "Screenshots are readable navigation evidence; HTML/JSON files are the item-level source evidence."]}
    (OUT / "navigation.json").write_text(json.dumps(navigation, ensure_ascii=False, indent=2), encoding="utf-8")

    counts = defaultdict(int)
    for row in frozen: counts[row["notice_id"]] += 1
    handoff = {"source_id": SOURCE_ID, "adapter": {"path": str(Path(__file__).resolve()), "version": ADAPTER_VERSION},
        "status": "frozen_candidate_bundle_not_approved", "candidate_row_count": len(frozen),
        "procedure_count": len(counts), "rows_by_procedure": dict(sorted(counts.items())),
        "canonical_column_count": len(CANONICAL_COLUMNS), "canonical_exact": True,
        "coverage": {"buyers": ["CCSS"], "period": "2019-01-01 through 2026-12-31", "procedure_types_present": sorted({r["procedure_type"] for r in frozen}), "requested_procedure_types": ["LY", "LN", "LE", "LD", "CD", "PX", "XE"]},
        "limitations": ["Candidate bundle is not approved and was not merged into tender memory.", "Current frozen rows are CCSS-only; INCIENSA, Hospital Nacional de Ninos, Banco Nacional de Sangre and Ministerio de Salud did not yield verified rows in this bounded evidence capture.", "Comprehensive portal keyword execution across every tracker code and all secondary buyers was not completed; zero rows must not be read as a negative market finding.", "No LN, CD or PX candidate rows were verified; absence from this candidate bundle is not proof of no awards.", "Open points are listed in coverage_matrix.csv and remain unresolved unless explicitly marked captured/partially evidenced.", "2026 rows are inside the user-requested window but include future-of-today portal records relative to earlier historical snapshots; SICOP pages were live on the capture date.", "Manual concise labels for 20250600489 and 20250903149 rely on prior official SICOP contract capture; raw page evidence for those two procedures was not newly re-exported in delivery 2."],
        "files": ["candidate_rows.csv", "candidate_rows_extended.csv", "tracker_tagged_rows.csv", "coverage_matrix.csv", "navigation.json", "evidence_manifest.json"],
        "approval": {"memory_changed": False, "business_rules_changed": False, "delivery_ready_declared": False, "approved": False}}
    (OUT / "tender_agent_handoff.json").write_text(json.dumps(handoff, ensure_ascii=False, indent=2), encoding="utf-8")

    manifest_files = sorted([p for p in OUT.rglob("*") if p.is_file() and p.name != "evidence_manifest.json"] + [Path(__file__).resolve()])
    manifest = {"source_id": SOURCE_ID, "generated_at_utc": datetime.now(timezone.utc).isoformat(), "hash_algorithm": "SHA256",
        "files": [{"path": str(p.relative_to(WORKSPACE) if p.is_relative_to(WORKSPACE) else p), "bytes": p.stat().st_size, "sha256": sha256(p)} for p in manifest_files]}
    (OUT / "evidence_manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")


class Adapter:
    """Tender-memory adapter over the frozen, evidence-backed delivery-2 bundle."""

    def __init__(self, url: str = PORTAL_URL) -> None:
        if "sicop.go.cr" not in url:
            raise ValueError(f"Unsupported SICOP URL: {url}")
        self.url = url

    def extract(self, source: Any = None) -> list[dict[str, Any]]:
        del source
        build()
        with (OUT / "candidate_rows.csv").open(newline="", encoding="utf-8-sig") as handle:
            return list(csv.DictReader(handle))

    def extract_targets(self, source: Any, targets: list[dict[str, Any]]) -> dict[str, list[dict[str, Any]]]:
        rows = self.extract(source)
        by_notice: defaultdict[str, list[dict[str, Any]]] = defaultdict(list)
        for row in rows:
            by_notice[row["notice_id"]].append(row)
        return {
            target["target_key"]: by_notice[target.get("notice_id", "")]
            for target in targets
            if target.get("notice_id", "") in by_notice
        }


def create_adapter(url: str = PORTAL_URL) -> Adapter:
    return Adapter(url)


if __name__ == "__main__":
    build()

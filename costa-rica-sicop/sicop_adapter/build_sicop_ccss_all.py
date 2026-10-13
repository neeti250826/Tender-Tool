#!/usr/bin/env python3
"""Build the isolated CCSS SICOP contract index and broad laboratory candidate set.

Adapter version: 0.1.0
Source: SICOP public Contracts report API (official prod-api.sicop.go.cr).
The script intentionally does not touch the prior tracker delivery.
"""

from __future__ import annotations

import csv
import hashlib
import json
import re
import shutil
import unicodedata
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path


VERSION = "0.1.0"
ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "outputs" / "sicop_ccss_all_2019_2026" / "tender_agent"
RAW = OUT / "raw"
SCREENSHOTS = OUT / "screenshots"
API_URL = "https://prod-api.sicop.go.cr/pcont/api/v1/public/ceContractsReport/listPage"
REPORT_URL = "https://www.sicop.go.cr/app/module/pcont/public/ce-contracts-report"
INSTITUTION_ID = "4000042147"
INSTITUTION_NAME = "CAJA COSTARRICENSE DE SEGURO SOCIAL"

SLICE_REQUESTS = {
    "2019": ("2018-12-31T18:30:00.000Z", "2019-12-31T18:30:00.000Z"),
    "2020": ("2019-12-31T18:30:00.000Z", "2020-12-31T18:30:00.000Z"),
    "2021": ("2020-12-31T18:30:00.000Z", "2021-12-31T18:30:00.000Z"),
    "2022": ("2021-12-31T18:30:00.000Z", "2022-12-31T18:30:00.000Z"),
    "2023": ("2022-12-31T18:30:00.000Z", "2023-12-31T18:30:00.000Z"),
    "2024": ("2023-12-31T18:30:00.000Z", "2024-12-31T18:30:00.000Z"),
    "2025": ("2024-12-31T18:30:00.000Z", "2025-12-31T18:30:00.000Z"),
    "2026_ytd": ("2025-12-31T18:30:00.000Z", "2026-09-29T18:29:59.999Z"),
}

ALLOWED_TYPES = {"LY", "LN", "LE", "LD", "CD", "PX", "XE"}

# High-recall laboratory/IVD terms. Matching is accent/case/spacing insensitive.
POSITIVE_TERMS = [
    "reactivo", "laboratorio", "diagnostic", "prueba", "test", "ensayo",
    "analizador", "coagul", "hematolog", "quimica clinica", "serolog",
    "virolog", "microbiolog", "cultivo", "molecular", " pcr ", "genetic",
    "citometr", "histolog", "patolog", "inmunohisto", "hibridacion",
    "anatomia patologica", "glucosa", "diabetes", "hemoglobina glicosilada",
    "hba1c", "uroanal", "orina", "tamizaje", "nat", "point of care",
    "poct", "i-stat", "hormon", "marcador", "ferritina", "vitamina",
    "tiroid", "troponin", "bnp", "procalciton", "electroforesis",
    "gasometr", "gases sanguineos", "cartucho", "cartridge", "calibrador",
    "control de calidad", "microscop", "centrifug", "espectrofot",
    "inmunoensayo", "elisa", "inmunologia", "parasitolog", "bacteriolog",
    "tubo para muestra", "medio de transporte", "medio de cultivo",
    "placa petri", "lamina portaobjeto", "material de laboratorio",
    "insumo de laboratorio", "insumos varios de laboratorio",
]

# Obvious out-of-scope categories. Applied only after a positive term match.
NEGATIVE_TERMS = [
    "mantenimiento", "reparacion", "arrendamiento", "alquiler", "construccion",
    "remodelacion", "obra civil", "pintura", "aseo", "limpieza", "fumigacion",
    "agua potable", "analisis de agua", "gas lp", "oxigeno medicinal",
    "alimento", "alimentacion", "nutricion", "senasa", "veterinari",
    "psicolog", "servicio de jardineria", "servicio de lavanderia",
]

KNOWN_COUNTEREXAMPLES = {
    "0432023210300050": "Abbott i-STAT POCT cartridges",
    "0432023220200047": "Hormones/infection-marker reagents",
    "0432024210500063": "Laboratory reagents/supplies",
    "0432024210500064": "Laboratory reagents/supplies",
    "0432024210500065": "Laboratory reagents/supplies",
    "0432025233100010": "Culture media/laboratory reagents",
    "0432025233100011": "Culture media/laboratory reagents",
    "0432025221700013": "Laboratory inputs/reagents",
}


def norm(value: object) -> str:
    text = unicodedata.normalize("NFKD", str(value or ""))
    text = "".join(c for c in text if not unicodedata.combining(c)).lower()
    text = text.replace("\xa0", " ")
    return " " + re.sub(r"\s+", " ", text).strip() + " "


def sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def parse_cli_capture(path: Path) -> dict:
    text = path.read_text(encoding="utf-8")
    marker = text.split("### Result", 1)[1].split("### Ran Playwright code", 1)[0]
    return json.loads(marker.strip())


def request_body(start: str, end: str, page_number: int) -> dict:
    return {
        "pageNumber": page_number,
        "pageSize": 10000,
        "tableSorter": {"sorter": "", "order": "desc"},
        "tableFilters": [],
        "formFilters": [
            {"field": "instRegNo", "value": INSTITUTION_ID},
            {"field": "startDt", "value": start},
            {"field": "endDt", "value": end},
        ],
    }


def write_csv(path: Path, rows: list[dict], fields: list[str]) -> None:
    with path.open("w", encoding="utf-8-sig", newline="") as fh:
        writer = csv.DictWriter(fh, fieldnames=fields, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)


def main() -> None:
    RAW.mkdir(parents=True, exist_ok=True)
    SCREENSHOTS.mkdir(parents=True, exist_ok=True)
    adapter_out = OUT / "adapter"
    adapter_out.mkdir(parents=True, exist_ok=True)
    generated_at = datetime.now(timezone.utc).isoformat()

    adapter_sources = [
        ROOT / "sicop_adapter" / "build_sicop_ccss_all.py",
        ROOT / "sicop_adapter" / "fetch_sicop_all_slices.js",
        ROOT / "sicop_adapter" / "fetch_sicop_2026_page2.js",
    ]
    copied_adapters: list[Path] = []
    for source in adapter_sources:
        target = adapter_out / source.name
        shutil.copy2(source, target)
        copied_adapters.append(target)

    capture = parse_cli_capture(RAW / "all_slices_playwright_capture.txt")
    page2 = parse_cli_capture(RAW / "ccss_contract_report_2026_ytd_page2_capture.txt")
    slice_map = {s["label"]: s for s in capture["slices"]}

    all_rows: list[dict] = []
    annual_summary: list[dict] = []
    raw_files: list[Path] = []

    for label, (start, end) in SLICE_REQUESTS.items():
        first = slice_map[label]
        pages = [{
            "status": first["status"],
            "request": request_body(start, end, 0),
            "response": first["payload"],
        }]
        if label == "2026_ytd":
            pages.append({
                "status": page2["status"],
                "request": page2["request"],
                "response": page2["payload"],
            })

        expected = int(pages[0]["response"]["totalElements"])
        expected_pages = int(pages[0]["response"]["totalPages"])
        observed = sum(len(p["response"].get("content", [])) for p in pages)
        page_numbers = [p["response"].get("number") for p in pages]
        complete = (
            all(p["status"] == 200 for p in pages)
            and len(pages) == expected_pages
            and observed == expected
            and page_numbers == list(range(expected_pages))
        ) if expected_pages else observed == expected == 0
        if not complete:
            raise RuntimeError(f"Incomplete slice {label}: expected {expected}, observed {observed}")

        annual_doc = {
            "source_url": API_URL,
            "report_url": REPORT_URL,
            "institution_id": INSTITUTION_ID,
            "institution_name": INSTITUTION_NAME,
            "slice_label": label,
            "slice_start": start,
            "slice_end": end,
            "captured_at_utc": generated_at,
            "pages": pages,
            "validation": {
                "expected_total_elements": expected,
                "expected_total_pages": expected_pages,
                "observed_records": observed,
                "observed_page_numbers": page_numbers,
                "complete_against_api_pagination": complete,
            },
        }
        raw_path = RAW / f"ccss_contract_report_{label}.json"
        raw_path.write_text(json.dumps(annual_doc, ensure_ascii=False, indent=2), encoding="utf-8")
        raw_files.append(raw_path)
        annual_summary.append({
            "slice_label": label,
            "slice_start": start,
            "slice_end": end,
            "record_count": observed,
            "page_count": len(pages),
            "api_total_elements": expected,
            "pagination_validated": complete,
            "raw_file": str(raw_path.relative_to(ROOT)),
        })

        for page in pages:
            for rec in page["response"].get("content", []):
                row = dict(rec)
                row["slice_label"] = label
                row["slice_start"] = start
                row["slice_end"] = end
                all_rows.append(row)

    index_rows: list[dict] = []
    for rec in all_rows:
        contract_no = str(rec.get("contractNo") or "")
        mod_seq = str(rec.get("contractModSeq") or "")
        cartel_no = str(rec.get("cartelNo") or "")
        index_rows.append({
            "record_key": f"{contract_no}|{mod_seq}",
            "slice_label": rec["slice_label"],
            "notification_slice_start": rec["slice_start"],
            "notification_slice_end": rec["slice_end"],
            "contract_no": contract_no,
            "contract_mod_seq": mod_seq,
            "contract_mod_code": rec.get("contractModCd") or "",
            "contract_modification_name": rec.get("contractModCdNm") or "",
            "contract_name": str(rec.get("contractNm") or "").replace("\xa0", " "),
            "total_contract_amount": rec.get("totContractAmt"),
            "currency": rec.get("currencyType") or "",
            "procedure_type": rec.get("proceType") or "",
            "procedure_type_name": rec.get("proceNm") or "",
            "institution_id": rec.get("instRegNo") or "",
            "institution_name": rec.get("instNm") or "",
            "cartel_no": cartel_no,
            "procedure_report_url": (
                "https://www.sicop.go.cr/moduloPcont/pcont/ctract/es/CE_CEJ_ESQ002.jsp?cartelNo="
                + cartel_no if cartel_no else ""
            ),
            "contracts_report_url": REPORT_URL,
            "source_api_url": API_URL,
        })

    index_fields = [
        "record_key", "slice_label", "notification_slice_start", "notification_slice_end",
        "contract_no", "contract_mod_seq", "contract_mod_code", "contract_modification_name",
        "contract_name", "total_contract_amount", "currency", "procedure_type",
        "procedure_type_name", "institution_id", "institution_name", "cartel_no",
        "procedure_report_url", "contracts_report_url", "source_api_url",
    ]
    write_csv(OUT / "all_contract_index.csv", index_rows, index_fields)

    candidate_rows: list[dict] = []
    for row in index_rows:
        text = norm(row["contract_name"])
        positives = sorted({term.strip() for term in POSITIVE_TERMS if norm(term).strip() in text})
        negatives = sorted({term for term in NEGATIVE_TERMS if norm(term).strip() in text})
        known = row["contract_no"] in KNOWN_COUNTEREXAMPLES
        allowed_type = row["procedure_type"] in ALLOWED_TYPES
        include = allowed_type and ((bool(positives) and not negatives) or known)
        if not include:
            continue
        out = dict(row)
        out.update({
            "matched_keywords": "; ".join(positives),
            "selection_basis": "known_counterexample_allowlist" if known else "inclusive_keyword",
            "known_counterexample": "yes" if known else "no",
            "known_counterexample_description": KNOWN_COUNTEREXAMPLES.get(row["contract_no"], ""),
            "negative_terms_overridden": "; ".join(negatives) if known else "",
            "possible_modification_record": "yes" if row["contract_mod_seq"] not in ("", "00") else "no",
            "scope_note": (
                "High-recall contract-title candidate; supplier, item lines, quantities, unit prices, "
                "brands and exact notification date require contract-detail extraction."
            ),
        })
        candidate_rows.append(out)

    candidate_fields = index_fields + [
        "matched_keywords", "selection_basis", "known_counterexample",
        "known_counterexample_description", "negative_terms_overridden",
        "possible_modification_record", "scope_note",
    ]
    write_csv(OUT / "lab_candidate_contracts.csv", candidate_rows, candidate_fields)

    # Preserve readable UI evidence from the prior read-only completeness run without changing it.
    prior_shots = ROOT / "outputs" / "sicop_tracker_delivery2" / "completeness_recheck" / "screenshots"
    copied_shots: list[Path] = []
    if prior_shots.exists():
        for source in sorted(prior_shots.glob("*.png")):
            target = SCREENSHOTS / source.name
            shutil.copy2(source, target)
            copied_shots.append(target)

    navigation = {
        "generated_at_utc": generated_at,
        "adapter_version": VERSION,
        "report_url": REPORT_URL,
        "api_url": API_URL,
        "request_schema": request_body(SLICE_REQUESTS["2023"][0], SLICE_REQUESTS["2023"][1], 0),
        "institution_lookup": {"name": INSTITUTION_NAME, "instRegNo": INSTITUTION_ID},
        "annual_slices": annual_summary,
        "material_actions": [
            {
                "action": "Opened the official SICOP contracts report and selected CCSS",
                "evidence": [str(p.relative_to(ROOT)) for p in copied_shots],
            },
            {
                "action": "Observed the official POST request schema in the browser network log",
                "endpoint": API_URL,
                "evidence": str((RAW / "all_slices_playwright_capture.txt").relative_to(ROOT)),
            },
            {
                "action": "Executed eight bounded annual requests; fetched the second 2026 page",
                "evidence": [str(p.relative_to(ROOT)) for p in raw_files],
            },
        ],
        "portal_constraint": (
            "The UI rejects notification-date ranges greater than one year; annual slices were used. "
            "2019 returned zero and 2020 returned only 31 rows, which may reflect historical coverage."
        ),
    }
    (OUT / "navigation.json").write_text(json.dumps(navigation, ensure_ascii=False, indent=2), encoding="utf-8")

    found_known = sorted({r["contract_no"] for r in candidate_rows} & set(KNOWN_COUNTEREXAMPLES))
    missing_known = sorted(set(KNOWN_COUNTEREXAMPLES) - set(found_known))
    handoff = {
        "status": "candidate_bundle_not_approved",
        "adapter": {
            "version": VERSION,
            "bundle_path": str(adapter_out.relative_to(ROOT)).replace("\\", "/"),
            "builder": str((adapter_out / "build_sicop_ccss_all.py").relative_to(ROOT)).replace("\\", "/"),
            "fetch_scripts": [
                str((adapter_out / "fetch_sicop_all_slices.js").relative_to(ROOT)).replace("\\", "/"),
                str((adapter_out / "fetch_sicop_2026_page2.js").relative_to(ROOT)).replace("\\", "/"),
            ],
        },
        "scope": {
            "buyer": INSTITUTION_NAME,
            "institution_id": INSTITUTION_ID,
            "notification_window": "2019-01-01 through 2026-09-29 local reporting boundaries",
            "candidate_procedure_types": sorted(ALLOWED_TYPES),
        },
        "counts": {
            "all_contract_modification_records": len(index_rows),
            "unique_record_keys": len({r["record_key"] for r in index_rows}),
            "unique_contract_numbers": len({r["contract_no"] for r in index_rows}),
            "lab_ivd_title_candidates": len(candidate_rows),
            "known_counterexamples_found": len(found_known),
            "known_counterexamples_expected": len(KNOWN_COUNTEREXAMPLES),
            "by_slice": {x["slice_label"]: x["record_count"] for x in annual_summary},
            "candidate_by_type": dict(sorted(Counter(r["procedure_type"] for r in candidate_rows).items())),
        },
        "known_counterexamples": {
            "found": found_known,
            "missing": missing_known,
        },
        "completeness_verdict": (
            "API pagination is complete for the eight bounded CCSS report slices captured, but the "
            "bundle must not be called exhaustive for all CCSS laboratory awards. Historical API "
            "coverage is anomalously sparse in 2019-2020, candidate selection is title-keyword based, "
            "and contract-detail/item/supplier fields were not available in the report index response."
        ),
        "limitations": [
            "The contracts-report API response has no supplier, brand/analyzer, item lines, quantity, unit price, exact notification date, duration, extensions or CE contract identifier.",
            "Rows are contracts and modifications, not one awarded supplier/item per row; detail-page extraction remains required for canonical tender memory.",
            "The report returns one current row per contract number with a contractModSeq value; it does not expose every historical version of the same contract in these slices.",
            "Annual filtering is by contract notification date, inferred from the report UI field and request schema.",
            "The 2019 API slice returned zero rows and 2020 returned 31; the dataset cannot prove that SICOP exposes all historical CCSS records for those years.",
            "Inclusive title keywords trade precision for recall and can still miss relevant contracts with generic titles or create false positives.",
            "Supplier-first search is not possible from this API response because supplier is absent.",
            "This bundle covers the CCSS contracts report only through 2026-09-29; it does not index separate adjudication-stage-only records.",
            "No business rules or prior delivery files were modified; this candidate bundle is not approved memory output.",
        ],
        "outputs": {
            "all_contract_index": "outputs/sicop_ccss_all_2019_2026/tender_agent/all_contract_index.csv",
            "lab_candidates": "outputs/sicop_ccss_all_2019_2026/tender_agent/lab_candidate_contracts.csv",
            "navigation": "outputs/sicop_ccss_all_2019_2026/tender_agent/navigation.json",
            "evidence_manifest": "outputs/sicop_ccss_all_2019_2026/tender_agent/evidence_manifest.json",
            "annual_raw_files": [str(p.relative_to(ROOT)).replace("\\", "/") for p in raw_files],
        },
    }
    (OUT / "handoff.json").write_text(json.dumps(handoff, ensure_ascii=False, indent=2), encoding="utf-8")

    manifest_paths = raw_files + [
        RAW / "all_slices_playwright_capture.txt",
        RAW / "ccss_contract_report_2026_ytd_page2_capture.txt",
        OUT / "all_contract_index.csv",
        OUT / "lab_candidate_contracts.csv",
        OUT / "navigation.json",
        OUT / "handoff.json",
    ] + copied_adapters + copied_shots
    manifest = {
        "generated_at_utc": generated_at,
        "source": "SICOP official public contracts-report API",
        "files": [
            {
                "path": str(p.relative_to(ROOT)).replace("\\", "/"),
                "bytes": p.stat().st_size,
                "sha256": sha256(p),
            }
            for p in manifest_paths if p.exists()
        ],
    }
    (OUT / "evidence_manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8"
    )

    if missing_known:
        raise RuntimeError(f"Known counterexamples missing from candidates: {missing_known}")
    print(json.dumps(handoff["counts"], ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()

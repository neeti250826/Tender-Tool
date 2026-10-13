import argparse
import base64
import csv
import json
import os
import re
import shutil
import subprocess
import time
import urllib.error
import urllib.request
import uuid
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import pandas as pd

try:
    from cryptography.hazmat.primitives import padding
    from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes
except ImportError:  # Fall back to the prior Node implementation if unavailable.
    padding = None
    Cipher = algorithms = modes = None


API_BASE = "https://ekapv2.kik.gov.tr/b_ihalearama"
LIST_ENDPOINT = f"{API_BASE}/api/Ihale/GetListByParameters"
DETAIL_ENDPOINT = f"{API_BASE}/api/IhaleDetay/GetByIhaleIdIhaleDetay"
API_VERSION = "v1"
EKAP_R8FACT = "Qm2LtXR0aByP69vZNKef4wMJ"


@dataclass(frozen=True)
class CpvRecord:
    code: str
    description: str
    status: str
    segment: str
    item_type: str


def iso_start(year: int) -> str:
    return f"{year}-01-01T00:00:00.000Z"


def iso_end(year: int) -> str:
    return f"{year}-12-31T23:59:59.999Z"


def compact_json(value: Any) -> str:
    if value in (None, "", [], {}):
        return ""
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"), default=str)


def first_present(data: dict[str, Any], candidates: list[str]) -> Any:
    lowered = {str(k).lower(): v for k, v in data.items()}
    for candidate in candidates:
        if candidate in data and data[candidate] not in (None, ""):
            return data[candidate]
        value = lowered.get(candidate.lower())
        if value not in (None, ""):
            return value
    return ""


def find_by_key_fragment(data: Any, fragments: list[str]) -> Any:
    if isinstance(data, dict):
        for key, value in data.items():
            key_l = str(key).lower()
            if any(fragment in key_l for fragment in fragments) and value not in (None, "", [], {}):
                return value
        for value in data.values():
            nested = find_by_key_fragment(value, fragments)
            if nested not in (None, ""):
                return nested
    elif isinstance(data, list):
        for value in data:
            nested = find_by_key_fragment(value, fragments)
            if nested not in (None, ""):
                return nested
    return ""


def normalize_amount(value: Any) -> str:
    if value in (None, ""):
        return ""
    if isinstance(value, (int, float)):
        return str(value)
    text = str(value).strip()
    if not text:
        return ""
    text = re.sub(r"\s*(TL|TRY|₺)\s*$", "", text, flags=re.IGNORECASE)
    return text.strip()


def load_cpvs(path: Path, statuses: set[str]) -> list[CpvRecord]:
    df = pd.read_excel(path, sheet_name="IVD_CPV_Master", dtype={"CPV code": str})
    df["CPV code"] = df["CPV code"].astype(str).str.replace(r"\.0$", "", regex=True).str.strip()
    df["Use status"] = df["Use status"].fillna("").astype(str).str.strip()
    filtered = df[df["Use status"].str.lower().isin({s.lower() for s in statuses})]
    return [
        CpvRecord(
            code=str(row["CPV code"]).strip(),
            description=str(row.get("English CPV description", "") or ""),
            status=str(row.get("Use status", "") or ""),
            segment=str(row.get("IVD segment relevance", "") or ""),
            item_type=str(row.get("Procurement item type", "") or ""),
        )
        for _, row in filtered.iterrows()
        if str(row["CPV code"]).strip()
    ]


def auth_headers() -> dict[str, str]:
    token = os.environ.get("EKAP_ACCESS_TOKEN", "").strip()
    headers_json = os.environ.get("EKAP_HEADERS_JSON", "").strip()
    headers_path = os.environ.get("EKAP_HEADERS_FILE", "").strip()

    headers = {
        "Accept": "application/json",
        "Content-Type": "application/json",
        "api-version": API_VERSION,
        "Origin": "https://ekapv2.kik.gov.tr",
        "Referer": "https://ekapv2.kik.gov.tr/ekap/search",
    }
    if headers_path:
        loaded = json.loads(Path(headers_path).read_text(encoding="utf-8"))
        headers.update({str(k): str(v) for k, v in loaded.items()})
    if headers_json:
        loaded = json.loads(headers_json)
        headers.update({str(k): str(v) for k, v in loaded.items()})
    if token:
        headers["Authorization"] = token if token.lower().startswith("bearer ") else f"Bearer {token}"
    return headers


def ekap_security_headers() -> dict[str, str]:
    guid = str(uuid.uuid4())
    timestamp_ms = str(int(time.time() * 1000))
    if Cipher is not None and algorithms is not None and modes is not None and padding is not None:
        key = EKAP_R8FACT.encode("utf-8")
        iv = os.urandom(16)

        def encrypt(value: str) -> str:
            padder = padding.PKCS7(128).padder()
            padded = padder.update(value.encode("utf-8")) + padder.finalize()
            encryptor = Cipher(algorithms.AES(key), modes.CBC(iv)).encryptor()
            encrypted = encryptor.update(padded) + encryptor.finalize()
            return base64.b64encode(encrypted).decode("ascii")

        return {
            "X-Custom-Request-Ts": encrypt(timestamp_ms),
            "X-Custom-Request-Siv": base64.b64encode(iv).decode("ascii"),
            "X-Custom-Request-R8id": encrypt(guid),
            "X-Custom-Request-Guid": guid,
        }

    # Retain the known-compatible Node fallback for environments without cryptography.
    node_path = shutil.which("node")
    if not node_path:
        raise RuntimeError("Node.js is required to generate EKAP encrypted request headers.")
    script = r"""
const crypto = require('node:crypto');
const [keyText, guid, timestamp] = process.argv.slice(1);
const key = Buffer.from(keyText, 'utf8');
const iv = crypto.randomBytes(16);
function enc(value) {
  const cipher = crypto.createCipheriv('aes-192-cbc', key, iv);
  return Buffer.concat([cipher.update(value, 'utf8'), cipher.final()]).toString('base64');
}
process.stdout.write(JSON.stringify({
  guid,
  siv: iv.toString('base64'),
  r8id: enc(guid),
  ts: enc(timestamp)
}));
"""
    completed = subprocess.run(
        [node_path, "-e", script, EKAP_R8FACT, guid, timestamp_ms],
        text=True,
        capture_output=True,
        check=False,
        encoding="utf-8",
    )
    if completed.returncode != 0:
        raise RuntimeError(f"Node crypto failed: {completed.stderr.strip()}")
    encrypted = json.loads(completed.stdout)
    return {
        "X-Custom-Request-Ts": encrypted["ts"],
        "X-Custom-Request-Siv": encrypted["siv"],
        "X-Custom-Request-R8id": encrypted["r8id"],
        "X-Custom-Request-Guid": encrypted["guid"],
    }


def post_json_with_curl(headers: dict[str, str], url: str, payload: dict[str, Any]) -> tuple[int, str]:
    curl_path = shutil.which("curl.exe") or shutil.which("curl")
    if not curl_path:
        raise FileNotFoundError("curl is not available")
    body = json.dumps(payload, ensure_ascii=False)
    command = [
        curl_path,
        "--silent",
        "--show-error",
        "--location",
        "--connect-timeout",
        "15",
        "--max-time",
        "60",
        "--request",
        "POST",
        "--data-binary",
        "@-",
        "--write-out",
        "\n%{http_code}",
    ]
    for key, value in headers.items():
        command.extend(["--header", f"{key}: {value}"])
    command.append(url)
    completed = subprocess.run(
        command,
        input=body,
        text=True,
        capture_output=True,
        check=False,
        encoding="utf-8",
    )
    if completed.returncode != 0:
        raise RuntimeError(f"curl failed: {completed.stderr.strip()}")
    text = completed.stdout
    response_text, _, status_text = text.rpartition("\n")
    try:
        status_code = int(status_text.strip())
    except ValueError:
        status_code = 0
        response_text = text
    return status_code, response_text


def post_json_with_urllib(headers: dict[str, str], url: str, payload: dict[str, Any]) -> tuple[int, str]:
    body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    request = urllib.request.Request(url, data=body, headers=headers, method="POST")
    with urllib.request.urlopen(request, timeout=60) as response:
        return response.status, response.read().decode("utf-8")


def post_json(headers: dict[str, str], url: str, payload: dict[str, Any], retries: int = 3) -> dict[str, Any]:
    for attempt in range(1, retries + 1):
        try:
            request_headers = {**headers, **ekap_security_headers()}
            try:
                status_code, text = post_json_with_curl(request_headers, url, payload)
            except FileNotFoundError:
                status_code, text = post_json_with_urllib(request_headers, url, payload)
            if status_code == 0:
                raise RuntimeError(f"EKAP request failed without HTTP status: {text[:500]}")
            if status_code == 401:
                raise RuntimeError(
                    f"EKAP returned 401 Unauthorized: {text[:500]}"
                )
            if status_code in {429, 500, 502, 503, 504} and attempt < retries:
                time.sleep(2 * attempt)
                continue
            if status_code < 200 or status_code >= 300:
                raise RuntimeError(f"EKAP HTTP {status_code}: {text[:500]}")
            return json.loads(text) if text.strip() else {}
        except urllib.error.HTTPError as error:
            if error.code == 401:
                raise RuntimeError(
                    f"EKAP returned 401 Unauthorized: {error.read().decode('utf-8', errors='replace')[:500]}"
                ) from error
            if error.code in {429, 500, 502, 503, 504} and attempt < retries:
                time.sleep(2 * attempt)
                continue
            detail = error.read().decode("utf-8", errors="replace")
            raise RuntimeError(f"EKAP HTTP {error.code}: {detail[:500]}") from error
        except urllib.error.URLError:
            if attempt < retries:
                time.sleep(2 * attempt)
                continue
            raise
        except RuntimeError as error:
            message = str(error)
            if message.startswith("curl failed:") and attempt < retries:
                time.sleep(2 * attempt)
                continue
            raise
    return {}


def list_payload(cpv: CpvRecord, year: int, skip: int, take: int, date_field: str) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "paginationSkip": skip,
        "paginationTake": take,
        "orderBy": "ihaleTarihi",
        "siralamaTipi": "desc",
        "yasaKapsami4734List": [1],
        "ihaleTuruIdList": [1],
        "okasBransKodList": [cpv.code],
    }
    if date_field == "notice":
        payload["ilanTarihSaatBaslangic"] = iso_start(year)
        payload["ilanTarihSaatBitis"] = iso_end(year)
    else:
        payload["ihaleTarihSaatBaslangic"] = iso_start(year)
        payload["ihaleTarihSaatBitis"] = iso_end(year)
    return payload


def fetch_tender_list(
    headers: dict[str, str],
    cpv: CpvRecord,
    year: int,
    take: int,
    max_pages: int | None,
    date_field: str,
) -> list[dict[str, Any]]:
    all_items: list[dict[str, Any]] = []
    skip = 0
    pages = 0
    while True:
        payload = list_payload(cpv, year, skip, take, date_field)
        data = post_json(headers, LIST_ENDPOINT, payload)
        items = data.get("list") or data.get("items") or []
        total = int(data.get("totalCount") or len(items) or 0)
        all_items.extend(items)
        pages += 1
        if not items or len(all_items) >= total:
            break
        if max_pages is not None and pages >= max_pages:
            break
        skip += take
    return all_items


def fetch_detail(headers: dict[str, str], tender_id: Any) -> dict[str, Any]:
    if tender_id in (None, ""):
        return {}
    data = post_json(headers, DETAIL_ENDPOINT, {"ihaleId": tender_id})
    item = data.get("item")
    return item if isinstance(item, dict) else data


def summarize_notices(detail: dict[str, Any]) -> str:
    notices = detail.get("ilanList") or []
    if not isinstance(notices, list):
        return compact_json(notices)
    parts = []
    for notice in notices:
        if not isinstance(notice, dict):
            continue
        notice_type = first_present(notice, ["ilanTipAciklama", "ilanTip", "ilanTuruAciklama"])
        notice_date = first_present(notice, ["ilanTarihi", "tarih", "yayimTarihi"])
        parts.append(" | ".join(str(x) for x in [notice_type, notice_date] if x not in (None, "")))
    return "; ".join(parts)


def summarize_items(detail: dict[str, Any]) -> str:
    items = detail.get("ihtiyacKalemiOkasList") or detail.get("okasList") or []
    if not isinstance(items, list):
        return compact_json(items)
    parts = []
    for item in items:
        if not isinstance(item, dict):
            continue
        code = first_present(item, ["kodu", "okasKodu", "kod"])
        name = first_present(item, ["adi", "okasAdi", "ad"])
        parts.append(" - ".join(str(x) for x in [code, name] if x not in (None, "")))
    return "; ".join(parts)


def contract_rows(
    cpv: CpvRecord,
    year: int,
    tender: dict[str, Any],
    detail: dict[str, Any],
    source_url: str,
) -> list[dict[str, Any]]:
    contracts = detail.get("sozlesmeBilgiList") or []
    if not isinstance(contracts, list) or not contracts:
        contracts = [{}]

    rows = []
    for index, contract in enumerate(contracts, start=1):
        contract = contract if isinstance(contract, dict) else {}
        combined = {**tender, **detail, **contract}
        tender_id = first_present(tender, ["id", "ihaleId"]) or first_present(detail, ["id", "ihaleId"])
        ikn = first_present(combined, ["ikn", "ihaleKayitNumarasi", "ihaleKayitNumarası"])
        authority = first_present(combined, ["idareAdi", "idare"])
        winner = (
            first_present(contract, ["yukleniciAdi", "yuklenicininAdi", "istekliAdi", "kazananIstekliAdi"])
            or find_by_key_fragment(contract, ["yuklenici", "kazanan", "istekli"])
        )
        price = (
            first_present(contract, ["sozlesmeBedeli", "sozlesmeBedel", "teklifTutar", "ihaleBedeli"])
            or find_by_key_fragment(contract, ["sozlesmebedel", "bedel", "tutar", "price"])
        )
        row = {
            "source_cpv_code": cpv.code,
            "source_cpv_description": cpv.description,
            "source_cpv_status": cpv.status,
            "source_ivd_segment": cpv.segment,
            "source_procurement_item_type": cpv.item_type,
            "search_year": year,
            "tender_id": tender_id,
            "ikn": ikn,
            "tender_name": first_present(combined, ["ihaleAdi", "isinAdi", "ad"]),
            "contracting_authority": authority,
            "authority_city": first_present(combined, ["ihaleIlAdi", "il", "ilAdi"]),
            "tender_type": first_present(combined, ["ihaleTipAciklama", "ihaleTip"]),
            "procedure": first_present(combined, ["ihaleUsulAciklama", "ihaleUsul", "ihaleUsuluAltMaddeAciklama"]),
            "tender_status": first_present(combined, ["ihaleDurumAciklama", "ihaleDurum"]),
            "tender_datetime": first_present(combined, ["ihaleTarihSaat", "ihaleTarihi"]),
            "notice_summary": summarize_notices(detail),
            "item_summary": summarize_items(detail),
            "award_index": index if contract else "",
            "winner_company": winner,
            "contract_price": normalize_amount(price),
            "contract_date": first_present(contract, ["sozlesmeTarihi", "sozlesmeTarih"]),
            "contract_currency": first_present(contract, ["paraBirimi", "paraBirimiAdi", "currency"]),
            "contract_lot_or_part": first_present(contract, ["kisimAdi", "kalemKisimAdi", "sozlesmeKisimAdi"]),
            "source_url": source_url,
            "tender_list_json": compact_json(tender),
            "detail_json": compact_json(detail),
            "contract_json": compact_json(contract),
        }
        rows.append(row)
    return rows


def write_outputs(rows: list[dict[str, Any]], out_dir: Path) -> tuple[Path, Path]:
    out_dir.mkdir(parents=True, exist_ok=True)
    json_path = out_dir / "ekap_tender_extract_rows.json"
    csv_path = out_dir / "ekap_tender_extract_rows.csv"
    json_path.write_text(json.dumps(rows, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
    fieldnames = list(rows[0].keys()) if rows else [
        "source_cpv_code",
        "search_year",
        "tender_id",
        "ikn",
        "tender_name",
        "contracting_authority",
        "winner_company",
        "contract_price",
        "source_url",
    ]
    with csv_path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)
    return json_path, csv_path


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Extract EKAP tender award rows for CPV codes and years.")
    parser.add_argument("--cpv-workbook", default="Turkey_IVD_CPV_Master_Codebook.xlsx")
    parser.add_argument("--years", nargs="+", type=int, default=[2024, 2025])
    parser.add_argument("--statuses", nargs="+", default=["Include", "Optional"])
    parser.add_argument("--date-field", choices=["tender", "notice"], default="tender")
    parser.add_argument("--page-size", type=int, default=100)
    parser.add_argument("--max-pages", type=int, default=None)
    parser.add_argument("--limit-cpvs", type=int, default=None)
    parser.add_argument("--out-dir", default="outputs/ekap_extract")
    parser.add_argument("--sleep", type=float, default=0.2)
    parser.add_argument("--detail-workers", type=int, default=8)
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    cpvs = load_cpvs(Path(args.cpv_workbook), set(args.statuses))
    if args.limit_cpvs:
        cpvs = cpvs[: args.limit_cpvs]

    headers = auth_headers()

    rows: list[dict[str, Any]] = []
    seen_details: dict[Any, dict[str, Any]] = {}
    out_dir = Path(args.out_dir)
    for year in args.years:
        for cpv in cpvs:
            tenders = fetch_tender_list(headers, cpv, year, args.page_size, args.max_pages, args.date_field)
            print(f"{year} {cpv.code}: {len(tenders)} tender list rows")

            missing_ids = []
            for tender in tenders:
                tender_id = first_present(tender, ["id", "ihaleId"])
                if tender_id not in (None, "") and tender_id not in seen_details:
                    missing_ids.append(tender_id)
            missing_ids = list(dict.fromkeys(missing_ids))

            def detail_task(tender_id: Any) -> tuple[Any, dict[str, Any]]:
                try:
                    return tender_id, fetch_detail(headers, tender_id)
                except Exception as error:
                    return tender_id, {"_detail_error": str(error)}

            if missing_ids:
                workers = max(1, min(args.detail_workers, len(missing_ids)))
                with ThreadPoolExecutor(max_workers=workers) as executor:
                    futures = [executor.submit(detail_task, tender_id) for tender_id in missing_ids]
                    for future in as_completed(futures):
                        tender_id, detail = future.result()
                        seen_details[tender_id] = detail
                        if args.sleep:
                            time.sleep(args.sleep)

            for tender in tenders:
                tender_id = first_present(tender, ["id", "ihaleId"])
                if tender_id not in seen_details:
                    try:
                        seen_details[tender_id] = fetch_detail(headers, tender_id)
                    except Exception as error:
                        seen_details[tender_id] = {"_detail_error": str(error)}
                source_url = f"https://ekapv2.kik.gov.tr/ekap/search/{tender_id}" if tender_id else "https://ekapv2.kik.gov.tr/ekap/search"
                rows.extend(contract_rows(cpv, year, tender, seen_details[tender_id], source_url))
            time.sleep(args.sleep)
            write_outputs(rows, out_dir)

    json_path, csv_path = write_outputs(rows, out_dir)
    run_info = {
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "years": args.years,
        "statuses": args.statuses,
        "date_field": args.date_field,
        "cpv_count": len(cpvs),
        "row_count": len(rows),
        "json_path": str(json_path),
        "csv_path": str(csv_path),
    }
    (Path(args.out_dir) / "ekap_extract_run_info.json").write_text(
        json.dumps(run_info, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    print(json.dumps(run_info, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()

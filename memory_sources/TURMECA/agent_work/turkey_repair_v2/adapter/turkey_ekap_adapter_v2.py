"""Turkey EKAP targeted repair adapter using the official KIK/e-Devlet fallback.

Adapter version: 0.2.0

EKAP v2 search is protected by Cloudflare Turnstile. This adapter never
automates or bypasses that control. Given a known IKN, it reads the public
official KIK service on e-Devlet and preserves complete source notice groups.
"""

from __future__ import annotations

import gzip
import hashlib
import json
import re
import threading
import time
import unicodedata
from copy import deepcopy
from datetime import datetime
from pathlib import Path
from typing import Any
from urllib.parse import quote, urljoin
from urllib.request import Request, build_opener

from lxml import html as lxml_html


ADAPTER_VERSION = "0.2.0"
BASE_URL = "https://www.turkiye.gov.tr/"
CANONICAL_FIELDS = [
    "source", "country", "country_code", "publication_date", "title",
    "title_english", "description", "description_english", "buyer",
    "buyer_english", "classification", "status", "currency", "amount",
    "awarding_agency_name", "awarding_agency_name_english", "supplier_name",
    "supplier_name_english", "awarded_date", "contract_period",
    "contract_period_english", "item_no", "item_description",
    "item_description_english", "item_uom", "item_uom_english", "quantity",
    "notice_id", "notice_url", "_source_workbook", "_duplicate_rows_removed",
    "_dedupe_key", "medtech_filter_basis", "mapped_oem", "mapped_oem_basis",
    "mapped_oem_match_term", "likely_oem", "likely_oem_score",
    "oem_match_terms", "oem_match_basis", "medtech_confidence",
]


def text(value: Any) -> str:
    if value is None:
        return ""
    value = str(value).strip()
    return "" if value.casefold() in {"nan", "none", "null", "nat"} else value


def norm(value: Any) -> str:
    value = unicodedata.normalize("NFKD", text(value)).casefold()
    value = "".join(ch for ch in value if not unicodedata.combining(ch))
    return re.sub(r"[^a-z0-9]+", " ", value).strip()


def iso_date(value: Any) -> str:
    value = text(value)
    for fmt in ("%d/%m/%Y", "%d.%m.%Y", "%Y-%m-%d", "%d-%m-%Y"):
        try:
            return datetime.strptime(value[:10], fmt).date().isoformat()
        except ValueError:
            pass
    return ""


def money(value: Any) -> tuple[float | None, str]:
    raw = text(value)
    currency = "TRY" if "TRY" in raw.upper() or "TL" in raw.upper() else ""
    cleaned = re.sub(r"[^0-9,.-]", "", raw)
    if not cleaned or cleaned in {"-", ".", ","}:
        return None, currency
    if "," in cleaned and "." in cleaned:
        if cleaned.rfind(",") > cleaned.rfind("."):
            cleaned = cleaned.replace(".", "").replace(",", ".")
        else:
            cleaned = cleaned.replace(",", "")
    elif "," in cleaned:
        parts = cleaned.split(",")
        cleaned = "".join(parts[:-1]) + "." + parts[-1] if len(parts[-1]) in {1, 2} else "".join(parts)
    elif cleaned.count(".") > 1:
        parts = cleaned.split(".")
        cleaned = "".join(parts[:-1]) + "." + parts[-1] if len(parts[-1]) in {1, 2} else "".join(parts)
    elif cleaned.count(".") == 1:
        left, right = cleaned.split(".")
        if len(right) == 3 and len(left) >= 1:
            cleaned = left + right
    try:
        return float(cleaned), currency
    except ValueError:
        return None, currency


def node_text(node) -> str:
    return " ".join(part.strip() for part in node.itertext() if part.strip())


def table_rows(table) -> list[dict[str, str]]:
    if table is None:
        return []
    headers = [node_text(c) for c in table.xpath(".//thead//th")]
    if not headers:
        first = table.xpath(".//tr[1]")
        headers = [node_text(c) for c in first[0].xpath("./th|./td")] if first else []
    result = []
    for tr in table.xpath(".//tbody/tr"):
        cells = [node_text(c) for c in tr.xpath("./td")]
        if cells and headers:
            result.append(dict(zip(headers, cells)))
    return result


class Adapter:
    def __init__(self, url: str, output_root: str | Path | None = None):
        self.url = url
        self.output_root = Path(output_root) if output_root else Path(__file__).resolve().parents[1]
        self.raw_dir = self.output_root / "raw_evidence" / "edevlet"
        self.raw_dir.mkdir(parents=True, exist_ok=True)
        self.headers = {
            "User-Agent": "Mozilla/5.0 (compatible; ClearstateTenderAudit/0.2; official-source-verification)",
            "Accept-Language": "tr-TR,tr;q=0.9,en;q=0.7",
        }
        self.local = threading.local()
        self.fetch_log: list[dict[str, Any]] = []
        self.fetch_lock = threading.Lock()

    def notice_url(self, notice_id: str) -> str:
        return f"{BASE_URL}kik-ihale-sorgula?asama=detay&kayitNo={quote(notice_id, safe='')}"

    def _opener(self):
        if not hasattr(self.local, "opener"):
            self.local.opener = build_opener()
        return self.local.opener

    def _get(self, url: str, evidence_name: str, retries: int = 3) -> str:
        target = self.raw_dir / f"{evidence_name}.gz"
        if target.exists() and target.stat().st_size > 300:
            body = gzip.decompress(target.read_bytes())
            self._log(url, target, body, True, 200, 0, "")
            return body.decode("utf-8", errors="replace")
        last_error = ""
        for attempt in range(1, retries + 1):
            try:
                request = Request(url, headers=self.headers)
                response = self._opener().open(request, timeout=35)
                body = response.read()
                status = int(getattr(response, "status", 200))
                if status >= 400:
                    raise RuntimeError(f"HTTP {status}")
                if b"Kamu" not in body or b"Ihale" not in unicodedata.normalize("NFKD", body.decode("utf-8", errors="replace")).encode("ascii", errors="ignore"):
                    raise RuntimeError("unexpected KIK/e-Devlet response schema")
                compressed = gzip.compress(body, compresslevel=6)
                target.write_bytes(compressed)
                self._log(response.geturl(), target, body, False, status, attempt, "")
                return body.decode("utf-8", errors="replace")
            except Exception as exc:
                last_error = f"{type(exc).__name__}: {exc}"
                if attempt < retries:
                    time.sleep(0.8 * attempt)
        self._log(url, target, b"", False, 0, retries, last_error)
        raise RuntimeError(last_error)

    def _log(self, url, path, body, cache, status, attempt, error):
        item = {
            "url": url, "path": str(path), "raw_sha256": hashlib.sha256(body).hexdigest() if body else "",
            "raw_bytes": len(body), "stored_sha256": hashlib.sha256(path.read_bytes()).hexdigest() if path.exists() else "",
            "stored_bytes": path.stat().st_size if path.exists() else 0, "from_cache": cache,
            "http_status": status, "attempt": attempt, "error": error,
        }
        with self.fetch_lock:
            self.fetch_log.append(item)

    def parse_notice_page(self, page: str) -> dict[str, Any]:
        root = lxml_html.fromstring(page)
        labels = {}
        for term in root.xpath("//dt"):
            definition = term.xpath("following-sibling::dd[1]")
            if definition:
                labels[node_text(term)] = node_text(definition[0])
        tables = {}
        for table in root.xpath("//table"):
            caption = table.xpath(".//caption[1]")
            if caption:
                tables[node_text(caption[0])] = table
        announcements = []
        table = tables.get("İlan Bilgileri")
        if table is not None:
            headers = [node_text(h) for h in table.xpath(".//thead//th")]
            if not headers:
                first = table.xpath(".//tr[1]")
                headers = [node_text(c) for c in first[0].xpath("./th|./td")] if first else []
            for pos, tr in enumerate(table.xpath(".//tbody/tr")):
                cells = tr.xpath("./td")
                if not cells:
                    continue
                row = dict(zip(headers, [node_text(c) for c in cells]))
                links = tr.xpath(".//a[@href]")
                if links:
                    href = links[0].get("href")
                    row["url"] = urljoin(BASE_URL, href)
                    match = re.search(r"(?:^|[?&])index=(\d+)", href)
                    row["index"] = int(match.group(1)) if match else pos
                row["publication_date"] = iso_date(row.get("İlan Tarihi"))
                row["is_result"] = "sonuc ilan" in norm(row.get("İlan Tipi"))
                announcements.append(row)
        return {"labels": labels, "announcements": announcements, "contracts": table_rows(tables.get("Sözleşme Bilgileri"))}

    def parse_result_page(self, page: str, source_url: str, publication_date: str) -> dict[str, Any]:
        root = lxml_html.fromstring(page)
        pairs = {}
        ordered = []
        for tr in root.xpath("//tr"):
            cells = [node_text(c) for c in tr.xpath("./th|./td")]
            if len(cells) >= 3 and cells[1] == ":":
                ordered.append((cells[0], cells[2]))
                pairs[cells[0]] = cells[2]
        amount, currency = money(pairs.get("b) Bedeli"))
        contract_dates = [iso_date(v) for k, v in ordered if k == "a) Tarihi" and iso_date(v)]
        return {
            "notice_id": pairs.get("İhale kayıt numarası", ""),
            "publication_date": publication_date,
            "title": pairs.get("a) Adı", ""),
            "description": pairs.get("c) Teslim tarihi", ""),
            "classification": pairs.get("b) Türü", ""),
            "currency": currency or "TRY", "amount": amount,
            "supplier_name": pairs.get("d) Yüklenicisi", ""),
            "awarded_date": contract_dates[-1] if contract_dates else "",
            "contract_period": pairs.get("c) Süresi", ""),
            "official_result_url": source_url,
        }

    def fetch_notice_summary(self, notice_id: str) -> dict[str, Any]:
        safe = notice_id.replace("/", "_")
        url = self.notice_url(notice_id)
        page = self._get(url, f"edevlet_{safe}_notice.html")
        parsed = self.parse_notice_page(page)
        parsed["notice_id"] = notice_id
        parsed["notice_url"] = url
        return parsed

    def fetch_results(self, notice: dict[str, Any]) -> list[dict[str, Any]]:
        safe = notice["notice_id"].replace("/", "_")
        results = []
        for pos, ann in enumerate(notice.get("announcements", [])):
            if not ann.get("is_result") or not ann.get("url"):
                continue
            page = self._get(ann["url"], f"edevlet_{safe}_result_{ann.get('index', pos)}.html")
            results.append(self.parse_result_page(page, ann["url"], ann.get("publication_date", "")))
        return results

    @staticmethod
    def select_result(row: dict[str, Any], results: list[dict[str, Any]]) -> dict[str, Any] | None:
        src_supplier = norm(row.get("supplier_name") or row.get("supplier_name_en"))
        src_amount, _ = money(row.get("contract_fee"))
        scored = []
        for result in results:
            score = 0
            rs = norm(result.get("supplier_name"))
            if src_supplier and rs and src_supplier == rs:
                score += 10
            elif src_supplier and rs and (src_supplier in rs or rs in src_supplier):
                score += 5
            ra = result.get("amount")
            if src_amount is not None and ra is not None and abs(src_amount - ra) <= max(0.01, abs(ra) * 1e-8):
                score += 10
            scored.append((score, result))
        scored.sort(key=lambda x: x[0], reverse=True)
        if scored and scored[0][0] >= 10 and (len(scored) == 1 or scored[0][0] > scored[1][0]):
            return scored[0][1]
        return results[0] if len(results) == 1 else None

    def canonical_row(self, row: dict[str, Any], official: dict[str, Any], item_no: int) -> dict[str, Any]:
        result = {field: "" for field in CANONICAL_FIELDS}
        notice_id = text(row.get("notice_id"))
        amount, fee_currency = money(row.get("contract_fee"))
        if amount is None:
            amount, _ = money(row.get("amount"))
        period = text(official.get("contract_period"))
        if not period and text(row.get("start_date")) and text(row.get("end_date")):
            period = f"{text(row.get('start_date'))} - {text(row.get('end_date'))}"
        supplier = text(official.get("supplier_name") or row.get("supplier_name"))
        item_desc = text(row.get("item_description"))
        pub = text(official.get("publication_date"))
        dedupe = "|".join([notice_id, str(item_no), supplier, item_desc, text(row.get("item_quantity")), str(amount)])
        buyer = text(row.get("buyer") or row.get("awarding_agency_name"))
        buyer_en = text(row.get("awarding_agency_name_en"))
        result.update({
            "source": "EKAP / e-Devlet KIK", "country": "Turkey", "country_code": "TR",
            "publication_date": pub, "title": text(row.get("title") or official.get("title")),
            "title_english": text(row.get("title_en")), "description": text(row.get("description")),
            "description_english": text(row.get("description_en")), "buyer": buyer,
            "buyer_english": buyer_en, "classification": text(row.get("source_cpv_code")),
            "status": text(row.get("status_en")), "currency": fee_currency or text(row.get("currency")) or "TRY",
            "amount": amount if amount is not None else "", "awarding_agency_name": buyer,
            "awarding_agency_name_english": buyer_en, "supplier_name": supplier,
            "supplier_name_english": text(row.get("supplier_name_en")),
            "awarded_date": text(official.get("awarded_date") or pub), "contract_period": period,
            "contract_period_english": period, "item_no": item_no, "item_description": item_desc,
            "item_description_english": text(row.get("item_description_en")), "item_uom": text(row.get("item_uom")),
            "item_uom_english": "", "quantity": text(row.get("item_quantity")), "notice_id": notice_id,
            "notice_url": text(official.get("official_result_url") or self.notice_url(notice_id)),
            "_source_workbook": "Turkey_EKAP_Contracts_Ending_2024_2026_EN_Corrected.xlsx",
            "_duplicate_rows_removed": 0, "_dedupe_key": hashlib.sha1(dedupe.encode("utf-8")).hexdigest(),
            "medtech_filter_basis": text(row.get("query_text") or row.get("source_cpv_description") or row.get("title")),
            "medtech_confidence": "source_keyword_or_cpv",
        })
        return result

    def extract_targets(self, source: dict[str, Any], targets: list[dict[str, Any]]) -> dict[str, list[dict[str, Any]]]:
        output = {}
        for target in targets:
            target_key, notice_id = text(target.get("target_key")), text(target.get("notice_id"))
            rows = [deepcopy(r) for r in target.get("source_rows", [])]
            if not target_key or not notice_id or not rows:
                continue
            notice = self.fetch_notice_summary(notice_id)
            results = self.fetch_results(notice)
            repaired = []
            for index, row in enumerate(rows, 1):
                match = self.select_result(row, results)
                if match is None:
                    repaired = []
                    break
                repaired.append(self.canonical_row(row, match, index))
            if len(repaired) == len(rows):
                output[target_key] = repaired
        self.write_manifest()
        return output

    def extract(self, source: dict[str, Any]) -> list[dict[str, Any]]:
        raise RuntimeError("EKAP v2 listing is Turnstile-gated; use extract_targets with known notice IDs. CAPTCHA is never bypassed.")

    def write_manifest(self):
        path = self.output_root / "hashes" / "raw_evidence_manifest.json"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps({"adapter_version": ADAPTER_VERSION, "generated_at": datetime.now().astimezone().isoformat(), "files": self.fetch_log}, ensure_ascii=False, indent=2), encoding="utf-8")


def create_adapter(url: str) -> Adapter:
    return Adapter(url)

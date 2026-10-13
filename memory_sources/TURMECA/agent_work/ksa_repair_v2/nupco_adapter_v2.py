from __future__ import annotations

import argparse
import csv
import hashlib
import json
import re
import shutil
import time
import urllib.parse
import urllib.request
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import asdict, dataclass
from datetime import date, datetime
from pathlib import Path
from typing import Any

from lxml import etree, html
from pypdf import PdfReader


ADAPTER_VERSION = "2.0.0-repair"
LISTING_URL = "https://www.nupco.com/tenders/tenders-list/"
FINAL_URL = LISTING_URL + "?e-filter-3085e1f-tender-status=final-results"
DIRECT_URL = LISTING_URL + "?e-filter-3085e1f-tender-status=direct-purchase"
SITEMAP_URL = "https://www.nupco.com/tender-sitemap.xml"
MIN_DATE = date(2024, 1, 1)
MAX_DATE = date(2026, 9, 30)
CANONICAL_COLUMNS = [
    "source", "country", "country_code", "publication_date", "title", "title_english",
    "description", "description_english", "buyer", "buyer_english", "classification",
    "status", "currency", "amount", "awarding_agency_name", "awarding_agency_name_english",
    "supplier_name", "supplier_name_english", "awarded_date", "contract_period",
    "contract_period_english", "item_no", "item_description", "item_description_english",
    "item_uom", "item_uom_english", "quantity", "notice_id", "notice_url",
    "_source_workbook", "_duplicate_rows_removed", "_dedupe_key", "medtech_filter_basis",
    "mapped_oem", "mapped_oem_basis", "mapped_oem_match_term", "likely_oem",
    "likely_oem_score", "oem_match_terms", "oem_match_basis", "medtech_confidence",
]


@dataclass
class Notice:
    notice_id: str
    layer: str
    title: str
    notice_url: str
    status_text: str = ""
    detail_lastmod: str = ""
    final_result_url: str = ""
    publication_date: str = ""
    publication_date_basis: str = ""
    explicit_amount: str = ""
    explicit_currency: str = ""
    explicit_awarded_quantity: str = ""
    explicit_contract_period: str = ""
    field_search_notes: str = ""


class Adapter:
    """Bounded evidence-first adapter for NUPCO result repair.

    NPT and NDP are independent layers. The adapter never maps a tender booklet
    price, generic requested QTY, bid-opening date, or inferred currency/period
    into canonical award fields. Unknown layouts remain unresolved.
    """

    def __init__(self, url: str = LISTING_URL, output_root: str | Path | None = None):
        self.url = url or LISTING_URL
        self.output_root = Path(output_root or Path(__file__).resolve().parent)
        self.raw_root = self.output_root / "raw_evidence"
        self.listing_root = self.raw_root / "listings"
        self.detail_root = self.raw_root / "details"
        self.result_root = self.raw_root / "final_results"
        for path in (self.raw_root, self.listing_root, self.detail_root, self.result_root):
            path.mkdir(parents=True, exist_ok=True)
        self.user_agent = "Mozilla/5.0 (compatible; NUPCO-repair-adapter/2.0; +https://www.nupco.com/)"

    @staticmethod
    def _clean(value: Any) -> str:
        return " ".join(str(value or "").split())

    @staticmethod
    def _slug(value: str) -> str:
        return re.sub(r"[^A-Za-z0-9._-]+", "_", value).strip("_") or "unknown"

    @staticmethod
    def _sha256(path: Path) -> str:
        return hashlib.sha256(path.read_bytes()).hexdigest()

    def _fetch(self, url: str, retries: int = 3) -> bytes:
        last: Exception | None = None
        for attempt in range(retries):
            try:
                req = urllib.request.Request(url, headers={"User-Agent": self.user_agent, "Accept": "*/*"})
                with urllib.request.urlopen(req, timeout=35) as response:
                    return response.read()
            except Exception as exc:
                last = exc
                time.sleep(1 + attempt)
        raise RuntimeError(f"fetch failed: {url}: {last}")

    def capture_entry_pages(self) -> None:
        for name, url in (("all", LISTING_URL), ("npt-final-results", FINAL_URL), ("ndp-direct-purchase", DIRECT_URL)):
            (self.listing_root / f"{name}.html").write_bytes(self._fetch(url))
        (self.listing_root / "tender-sitemap.xml").write_bytes(self._fetch(SITEMAP_URL))

    def _sitemap_urls(self) -> list[tuple[str, str]]:
        sitemap = self.listing_root / "tender-sitemap.xml"
        raw = sitemap.read_bytes() if sitemap.exists() else self._fetch(SITEMAP_URL)
        root = etree.fromstring(raw)
        ns = {"s": "http://www.sitemaps.org/schemas/sitemap/0.9"}
        values = []
        for node in root.xpath("//s:url", namespaces=ns):
            loc = node.xpath("string(s:loc)", namespaces=ns)
            lastmod = node.xpath("string(s:lastmod)", namespaces=ns)
            if loc:
                values.append((loc, lastmod))
        if len(values) > 1000:
            raise RuntimeError(f"sitemap bound exceeded: {len(values)}")
        return values

    @staticmethod
    def _attachment_links(doc, base: str) -> list[tuple[str, str]]:
        links = []
        for anchor in doc.xpath('//a[@href]'):
            href = urllib.parse.urljoin(base, anchor.get("href") or "")
            label = " ".join(anchor.text_content().split())
            if href:
                links.append((label, href))
        return links

    @staticmethod
    def _printed_result_date(pdf: Path) -> tuple[str, str]:
        try:
            reader = PdfReader(pdf)
            text = "\n".join((reader.pages[i].extract_text() or "") for i in sorted(set([0, len(reader.pages) - 1])))
        except Exception as exc:
            return "", f"PDF text unavailable: {exc}"
        match = re.search(r"\b(January|February|March|April|May|June|July|August|September|October|November|December)\s+(\d{1,2}),\s+(20\d{2})\b", text, re.I)
        if match:
            value = datetime.strptime(match.group(0).title(), "%B %d, %Y").date().isoformat()
            return value, f"printed_in_final_result_pdf:{match.group(0)}"
        return "", "no explicit result-publication date found in first/last PDF page"

    @staticmethod
    def _explicit_fields(text: str) -> dict[str, str]:
        normalized = " ".join(text.split())
        fields = {"amount": "", "currency": "", "quantity": "", "period": "", "notes": ""}
        amount = re.search(r"(?:AWARD(?:ED)?|CONTRACT|WINNING)\s+(?:TOTAL\s+)?(?:VALUE|AMOUNT|PRICE)\s*[:\-]?\s*((?:SAR|USD|EUR)\s*[0-9][0-9,]*(?:\.\d+)?)", normalized, re.I)
        qty = re.search(r"(?:AWARD(?:ED)?\s+Q(?:UANTI)?TY|QUANTITY\s+AWARDED)\s*[:\-]?\s*([0-9][0-9,.]*)", normalized, re.I)
        period = re.search(r"(?:CONTRACT\s+(?:PERIOD|DURATION))\s*[:\-]?\s*([0-9]+\s*(?:DAYS?|MONTHS?|YEARS?))", normalized, re.I)
        if amount:
            fields["amount"] = amount.group(1)
            fields["currency"] = amount.group(1).split()[0].upper()
        if qty:
            fields["quantity"] = qty.group(1)
        if period:
            fields["period"] = period.group(1)
        fields["notes"] = "Only explicit award-labelled fields matched; tender booklet price and generic QTY excluded."
        return fields

    def _parse_detail(self, url: str, lastmod: str, raw: bytes) -> Notice | None:
        doc = html.fromstring(raw)
        visible = self._clean(doc.text_content())
        match = re.search(r"\b(NPT|NDP)\s*([0-9]{4})[-/]([0-9]{2})\b", visible, re.I)
        if not match:
            return None
        notice_id = f"{match.group(1).upper()}{match.group(2)}/{match.group(3)}"
        title_nodes = doc.xpath("//h1|//h2")
        title = self._clean(title_nodes[0].text_content()) if title_nodes else notice_id
        result_url = ""
        for label, href in self._attachment_links(doc, url):
            key = (label + " " + href).lower()
            if "final" in key and "result" in key and (".pdf" in key or "uploads" in key):
                result_url = href
                break
        return Notice(
            notice_id=notice_id,
            layer="NDP" if notice_id.startswith("NDP") else "NPT",
            title=title,
            notice_url=url,
            status_text="Final Result attachment present" if result_url else "No Final Result attachment found",
            detail_lastmod=lastmod,
            final_result_url=result_url,
        )

    def crawl_sitemap(self) -> list[Notice]:
        entries = self._sitemap_urls()
        notices = []
        errors = []

        def fetch_one(entry: tuple[str, str]):
            url, lastmod = entry
            raw = self._fetch(url)
            return url, lastmod, raw

        with ThreadPoolExecutor(max_workers=8) as pool:
            futures = {pool.submit(fetch_one, entry): entry for entry in entries}
            for future in as_completed(futures):
                url, lastmod = futures[future]
                try:
                    resolved_url, resolved_lastmod, raw = future.result()
                    notice = self._parse_detail(resolved_url, resolved_lastmod, raw)
                    if not notice:
                        continue
                    detail_path = self.detail_root / notice.layer.lower() / f"{self._slug(notice.notice_id)}.html"
                    detail_path.parent.mkdir(parents=True, exist_ok=True)
                    detail_path.write_bytes(raw)
                    notices.append(notice)
                except Exception as exc:
                    errors.append({"url": url, "error": str(exc)})
        (self.output_root / "sitemap_crawl_errors.json").write_text(json.dumps(errors, indent=2), encoding="utf-8")
        return sorted({notice.notice_id: notice for notice in notices}.values(), key=lambda value: value.notice_id)

    def enrich_result_evidence(self, notices: list[Notice]) -> None:
        for notice in notices:
            if not notice.final_result_url:
                continue
            layer_root = self.result_root / notice.layer.lower()
            layer_root.mkdir(parents=True, exist_ok=True)
            path = layer_root / f"{self._slug(notice.notice_id)}-final-result.pdf"
            try:
                if not path.exists():
                    path.write_bytes(self._fetch(notice.final_result_url))
                notice.publication_date, notice.publication_date_basis = self._printed_result_date(path)
                reader = PdfReader(path)
                sample = "\n".join((reader.pages[i].extract_text() or "") for i in sorted(set([0, len(reader.pages) - 1])))
                fields = self._explicit_fields(sample)
                notice.explicit_amount = fields["amount"]
                notice.explicit_currency = fields["currency"]
                notice.explicit_awarded_quantity = fields["quantity"]
                notice.explicit_contract_period = fields["period"]
                notice.field_search_notes = fields["notes"]
            except Exception as exc:
                notice.field_search_notes = f"result evidence error: {exc}"

    def extract(self, source: Any = None) -> list[dict[str, Any]]:
        path = self.output_root / "npt_candidate_rows.csv"
        if not path.exists():
            raise FileNotFoundError(
                f"Reviewed candidate input is missing: {path}. "
                "Restore the evidence-run CSV; a missing snapshot is not a zero-award result."
            )
        with path.open(encoding="utf-8-sig", newline="") as handle:
            return list(csv.DictReader(handle))

    def extract_targets(self, source: Any, targets: list[dict[str, Any]]) -> dict[str, list[dict[str, Any]]]:
        rows = self.extract(source)
        by_notice: dict[str, list[dict[str, Any]]] = {}
        for row in rows:
            by_notice.setdefault(row.get("notice_id", ""), []).append(row)
        result = {}
        for target in targets:
            key = str(target.get("target_key", ""))
            notice_id = str(target.get("notice_id", ""))
            if key and notice_id in by_notice:
                result[key] = by_notice[notice_id]
        return result

    def write_inventory(self) -> None:
        self.capture_entry_pages()
        notices = self.crawl_sitemap()
        self.enrich_result_evidence(notices)
        npt = [asdict(n) for n in notices if n.layer == "NPT"]
        ndp = [asdict(n) for n in notices if n.layer == "NDP"]
        (self.output_root / "official_npt_inventory.json").write_text(json.dumps(npt, indent=2, ensure_ascii=False), encoding="utf-8")
        (self.output_root / "official_ndp_inventory.json").write_text(json.dumps(ndp, indent=2, ensure_ascii=False), encoding="utf-8")
        ndp_final = [row for row in ndp if row["final_result_url"]]
        (self.output_root / "official_ndp_final_results.json").write_text(json.dumps(ndp_final, indent=2, ensure_ascii=False), encoding="utf-8")
        print(json.dumps({"adapter_version": ADAPTER_VERSION, "sitemap_notices": len(notices), "npt": len(npt), "ndp": len(ndp), "ndp_with_final_result_attachment": len(ndp_final)}))


def create_adapter(url: str) -> Adapter:
    return Adapter(url=url)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--url", default=LISTING_URL)
    parser.add_argument("--output", default=str(Path(__file__).resolve().parent))
    args = parser.parse_args()
    Adapter(args.url, args.output).write_inventory()


if __name__ == "__main__":
    main()

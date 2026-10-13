from __future__ import annotations

import io
import json
import re
import subprocess
from datetime import date, datetime
from pathlib import Path
from typing import Dict, List
from urllib.parse import urlencode

import requests
from requests import RequestException

from harness.shared.normalize import normalize_text, repair_mojibake, utc_now_iso
from harness.shared.schema import OutputRow
from harness.sources.base import SmokeProbeResult
from harness.sources.registry import SOURCES

CONFIG = SOURCES["hungary_ekr"]
EVIDENCE_PATH = Path("evidence") / "hungary_notice_8803469030747.json"
LIVE_LIST_URL = "https://ekr.gov.hu/api/publikus/kozbeszerzesi-hirdetmenyek"
LIVE_DETAIL_URL = "https://ekr.gov.hu/api/publikus/kozbeszerzesi-hirdetmenyek/{notice_id}"
LIVE_DOC_URL = "https://ekr.gov.hu/api/publikus/kozbeszerzesi-hirdetmenyek/{notice_id}/dokumentum-letoltes"
NOTICE_URL = "https://ekr.gov.hu/portal/kozbeszerzes/hirdetmenyek/{notice_id}/reszletek"
REQUEST_TIMEOUT_SECONDS = 30
RESULT_NOTICE_PATTERNS = (
    "eredmenyerol",
    "eredményéről",
    "eredmenyrol",
    "eredményről",
    "eljárás eredményéről",
)
MEDICAL_KEYWORDS = (
    "orvosi",
    "egeszseg",
    "egészség",
    "korhaz",
    "kórház",
    "klinika",
    "labor",
    "diagnoszt",
    "hemodinamik",
    "gyogyszer",
    "gyógyszer",
    "steril",
    "ultrahang",
    "ultrazv",
    "rontgen",
    "röntgen",
    "ekg",
    "defibrill",
    "beteg",
    "sziv",
    "szív",
    "egyetemi klinika",
    "surgossegi",
    "sürgősségi",
    "medical",
    "hospital",
    "clinic",
    "laboratory",
    "diagnostic",
    "monitor",
)
MEDICAL_BUYER_KEYWORDS = (
    "egyetem",
    "egészség",
    "korhaz",
    "kórház",
    "klinika",
    "centrumkórház",
    "centrumkorhaz",
    "semmelweis",
)
NON_MEDICAL_KEYWORDS = (
    "utepites",
    "útépítés",
    "informatikai uzemeltetes",
    "parkfenntartás",
    "parkfenntartas",
    "villamos energia",
    "gázbeszerzés",
    "gazbeszerzes",
)
QUERY_TERMS = (
    "hemodinamikai",
    "orvosi",
    "diagnosztikai",
    "röntgen",
    "ultrahang",
    "steril",
    "defibrillátor",
    "laboratóriumi",
)


def _load_fixture_notice() -> Dict[str, object]:
    return json.loads(EVIDENCE_PATH.read_text(encoding="utf-8"))


def _normalized(value: object) -> str:
    return normalize_text(repair_mojibake(value))


def _simplified(value: object) -> str:
    text = _normalized(value).lower()
    replacements = str.maketrans(
        {
            "á": "a",
            "é": "e",
            "í": "i",
            "ó": "o",
            "ö": "o",
            "ő": "o",
            "ú": "u",
            "ü": "u",
            "ű": "u",
        }
    )
    return text.translate(replacements)


def _request_json(url: str, *, params: Dict[str, object] | None = None) -> Dict[str, object]:
    try:
        response = requests.get(
            url,
            params=params,
            headers={"User-Agent": "Mozilla/5.0"},
            timeout=REQUEST_TIMEOUT_SECONDS,
        )
        response.raise_for_status()
        return response.json()
    except RequestException:
        payload = _curl_fetch_bytes(url, params=params)
        return json.loads(payload.decode("utf-8"))


def _curl_fetch_bytes(url: str, *, params: Dict[str, object] | None = None) -> bytes:
    full_url = url
    if params:
        query = urlencode({key: value for key, value in params.items() if value is not None})
        separator = "&" if "?" in url else "?"
        full_url = f"{url}{separator}{query}"

    result = subprocess.run(
        ["curl.exe", "-L", full_url],
        check=True,
        capture_output=True,
        timeout=max(REQUEST_TIMEOUT_SECONDS, 60),
    )
    return result.stdout


def _fetch_list_page(query_text: str, page_number: int, page_size: int) -> Dict[str, object]:
    params = {
        "oldal": page_number,
        "elemszam": page_size,
        "rendezes": "hirdetmenyKozzetetelDatuma",
        "novekvo": "false",
        "eljarasTargya": query_text,
    }
    return _request_json(LIVE_LIST_URL, params=params)


def _fetch_notice_detail(notice_id: str) -> Dict[str, object]:
    return _request_json(LIVE_DETAIL_URL.format(notice_id=notice_id))


def _download_notice_pdf(notice_id: str) -> bytes:
    url = LIVE_DOC_URL.format(notice_id=notice_id)
    try:
        response = requests.get(
            url,
            headers={"User-Agent": "Mozilla/5.0"},
            timeout=REQUEST_TIMEOUT_SECONDS,
        )
        response.raise_for_status()
        return response.content
    except RequestException:
        return _curl_fetch_bytes(url)


def _extract_pdf_text(pdf_bytes: bytes) -> str:
    try:
        from pypdf import PdfReader
    except ImportError as exc:
        raise RuntimeError("pypdf is required for Hungary live PDF parsing") from exc

    reader = PdfReader(io.BytesIO(pdf_bytes))
    parts = []
    for page in reader.pages:
        try:
            parts.append(page.extract_text() or "")
        except Exception:
            continue
    return _normalized("\n".join(parts))


def _parse_display_date(value: object) -> str:
    text = _normalized(value)
    if not text:
        return ""
    for fmt in ("%Y-%m-%dT%H:%M:%S", "%Y-%m-%d", "%Y.%m.%d.", "%Y.%m.%d"):
        try:
            parsed = datetime.strptime(text, fmt)
            return parsed.date().isoformat()
        except ValueError:
            continue
    match = re.search(r"(\d{4})[.-](\d{2})[.-](\d{2})", text)
    if match:
        return f"{match.group(1)}-{match.group(2)}-{match.group(3)}"
    return text


def _within_window(value: object, date_from: str, date_to: str) -> bool:
    parsed_text = _parse_display_date(value)
    if not parsed_text:
        return False
    try:
        parsed = datetime.strptime(parsed_text, "%Y-%m-%d").date()
    except ValueError:
        return False
    start = datetime.strptime(date_from, "%Y-%m-%d").date()
    end = datetime.strptime(date_to, "%Y-%m-%d").date()
    return start <= parsed <= end


def _is_awarded_notice(notice: Dict[str, object]) -> bool:
    notice_type = _simplified(notice.get("hirdetmenyTipusa"))
    return any(pattern in notice_type for pattern in RESULT_NOTICE_PATTERNS)


def _is_medical_notice(notice: Dict[str, object], pdf_text: str = "") -> bool:
    title_text = _simplified(notice.get("eljarasTargya"))
    buyer_text = _simplified(notice.get("ajanlatkeroNeve"))
    activity_text = _simplified(notice.get("ajanlatkeroKlasszikusTevekenysegiKor"))
    pdf_simple = _simplified(pdf_text)
    joined = " ".join([title_text, buyer_text, activity_text, _simplified(notice.get("eljarasBeszerzesTargya")), pdf_simple])

    title_is_medical = any(keyword in title_text for keyword in MEDICAL_KEYWORDS)
    buyer_is_medical = any(keyword in buyer_text or keyword in activity_text for keyword in MEDICAL_BUYER_KEYWORDS)
    pdf_is_medical = any(keyword in pdf_simple for keyword in MEDICAL_KEYWORDS)
    has_non_medical = any(keyword in joined for keyword in NON_MEDICAL_KEYWORDS)

    if title_is_medical or buyer_is_medical:
        return True
    if pdf_is_medical and not has_non_medical:
        return True
    return False


def _extract_awarded_value_currency(pdf_text: str) -> tuple[str, str]:
    compact = _normalized(pdf_text)
    simple = _simplified(pdf_text)
    currency = "HUF" if "huf" in simple else ""

    label_index = simple.find("a hirdetmenyben odaitelt szerzodesek erteke")
    if label_index >= 0:
        prefix = compact[max(0, label_index - 120):label_index]
        amounts = re.findall(r"(\d[\d\s.]*,\d{2})", prefix)
        if amounts:
            return currency, _normalized(amounts[-1])

    money_match = re.search(r"(\d[\d\s.]*,\d{2})", compact)
    if money_match:
        return currency, _normalized(money_match.group(1))
    return currency, ""


def _extract_contract_period(pdf_text: str) -> str:
    compact = _normalized(pdf_text)
    match = re.search(r"\b(\d{1,3})\s*(H[oó]nap|Nap|[ÉE]v)\b", compact, re.I)
    if match:
        return f"{_normalized(match.group(1))} {_normalized(match.group(2))}"
    return ""


def _extract_contract_date(pdf_text: str) -> str:
    compact = _normalized(pdf_text)
    simple = _simplified(pdf_text)
    label_index = simple.find("a szerzodes megkotesenek datuma")
    if label_index >= 0:
        prefix = compact[max(0, label_index - 40):label_index]
        matches = re.findall(r"([0-9]{4}\.[0-9]{2}\.[0-9]{2})", prefix)
        if matches:
            return _parse_display_date(matches[-1])
    match = re.search(r"([0-9]{4}\.[0-9]{2}\.[0-9]{2})", compact)
    if match:
        return _parse_display_date(match.group(1))
    return ""


def _extract_description(notice: Dict[str, object], pdf_text: str) -> str:
    title = _normalized(notice.get("eljarasTargya"))
    compact = _normalized(pdf_text)
    match = re.search(
        r"II\.1\.4\)\s*K[oö]zbeszerz[eé]s le[ií]r[aá]sa.*?:\s*(.+?)(?:II\.2\.4\)|II\.2\.3\)|V\.2\.|Nyertes ajánlattevő)",
        compact,
        re.I | re.S,
    )
    if match:
        candidate = _normalized(match.group(1))
        if len(candidate) >= len(title) and "BT-" not in candidate[:200]:
            return candidate[:4000]
    return title


def _extract_item_desc(notice: Dict[str, object], pdf_text: str) -> str:
    title = _normalized(notice.get("eljarasTargya"))
    compact = _normalized(pdf_text)
    match = re.search(
        r"II\.2\.4\)\s*K[oö]zbeszerz[eé]s le[ií]r[aá]sa.*?:\s*(.+?)(?:Teljesítési hely|Teljesites helye|II\.2\.3\)|II\.2\.5\)|II\.2\.7\)|V\.2\.)",
        compact,
        re.I | re.S,
    )
    if match:
        candidate = _normalized(match.group(1))
        if 5 <= len(candidate) <= 250 and "BT-" not in candidate:
            return candidate
    return title


def _extract_item_fields(notice: Dict[str, object], pdf_text: str) -> tuple[str, str, str, str]:
    compact = _normalized(pdf_text)
    item_desc = _extract_item_desc(notice, pdf_text)

    quantity = ""
    item_uom = ""
    quantity_match = re.search(r"\b(\d+)\s*\((?:egy|kett[oő]|h[aá]rom)?\)\s*(darab|db|k[ée]szlet|csomag)\b", compact, re.I)
    if not quantity_match:
        quantity_match = re.search(r"\b(\d+)\s*(darab|db|k[ée]szlet|csomag)\b", compact, re.I)
    if quantity_match:
        quantity = _normalized(quantity_match.group(1))
        item_uom = _normalized(quantity_match.group(2))

    item_no = "1" if item_desc else ""
    return item_no, item_desc, item_uom, quantity


def _build_classification(notice: Dict[str, object]) -> str:
    parts = [
        _normalized(notice.get("eljarasBeszerzesTargya")),
        _normalized(notice.get("ajanlatkeroKlasszikusTevekenysegiKor")),
    ]
    return " | ".join(part for part in parts if part)


def _build_notice_url(notice_id: str, detail: Dict[str, object]) -> str:
    return NOTICE_URL.format(notice_id=notice_id)


def _map_fixture_notice_to_rows(payload: Dict[str, object], query_text: str) -> List[Dict[str, str]]:
    fields = payload.get("mapped_fields") or {}
    notice_id = _normalized(payload.get("notice_id"))
    row = OutputRow(
        source=CONFIG.source,
        country=CONFIG.country,
        country_cc=CONFIG.country_cc,
        publication_date=_parse_display_date(fields.get("publication_date")),
        closing_date=_parse_display_date(fields.get("closing_date")),
        title=_normalized(fields.get("title")),
        description=_normalized(fields.get("description")),
        buyer=_normalized(fields.get("buyer")),
        classification=_normalized(fields.get("classification")),
        status=_normalized(fields.get("status")) or "Published",
        currency=_normalized(fields.get("currency")),
        amount=_normalized(fields.get("amount")),
        awarding_supplier_name=_normalized(fields.get("awarding_supplier_name")),
        awarded_currency=_normalized(fields.get("awarded_currency")),
        awarded_value=_normalized(fields.get("awarded_value")),
        contract_period=_normalized(fields.get("contract_period")),
        item_no=_normalized(fields.get("item_no")),
        item_desc=_normalized(fields.get("item_desc")),
        item_uom=_normalized(fields.get("item_uom")),
        item_quantity=_normalized(fields.get("item_quantity")),
        item_unit_price=_normalized(fields.get("item_unit_price")),
        item_award=_normalized(fields.get("item_award")),
        notice_id=notice_id,
        notice_url=_normalized(payload.get("notice_url")),
        query_text=query_text,
        scraped_at=utc_now_iso(),
        dedup_key="|".join(part for part in [CONFIG.key, notice_id, _normalized(fields.get("item_no")) or ""] if part),
    )
    return [row.to_dict()]


def _map_notice_to_rows(
    notice: Dict[str, object],
    *,
    pdf_text: str = "",
    query_text: str = "",
) -> List[Dict[str, str]]:
    notice_id = _normalized(notice.get("hirdetmenyEKRazonosito"))
    internal_id = _normalized(notice.get("id"))
    awarded_currency, awarded_value = _extract_awarded_value_currency(pdf_text)
    item_no, item_desc, item_uom, item_quantity = _extract_item_fields(notice, pdf_text)
    contract_period = _extract_contract_period(pdf_text)
    closing_date = _parse_display_date(notice.get("eljarasAjanlatteteliHatarido"))
    publication_date = _parse_display_date(notice.get("hirdetmenyKozzetetelDatuma"))
    contract_date = _extract_contract_date(pdf_text)
    description = _extract_description(notice, pdf_text) if pdf_text else _normalized(notice.get("eljarasTargya"))

    item_unit_price = ""
    item_award = ""
    if item_quantity == "1" and awarded_value:
        item_unit_price = awarded_value
        item_award = awarded_value

    row = OutputRow(
        source=CONFIG.source,
        country=CONFIG.country,
        country_cc=CONFIG.country_cc,
        publication_date=publication_date,
        closing_date=closing_date,
        title=_normalized(notice.get("eljarasTargya")),
        description=description,
        buyer=_normalized(notice.get("ajanlatkeroNeve")),
        classification=_build_classification(notice),
        status="Awarded",
        currency=awarded_currency,
        amount="",
        awarding_supplier_name=_normalized(notice.get("eljarasNyertesAjanlattevoNeve")),
        awarded_currency=awarded_currency,
        awarded_value=awarded_value,
        contract_period=contract_period or contract_date,
        item_no=item_no,
        item_desc=item_desc,
        item_uom=item_uom,
        item_quantity=item_quantity,
        item_unit_price=item_unit_price,
        item_award=item_award,
        notice_id=notice_id or internal_id,
        notice_url=_build_notice_url(internal_id, notice),
        query_text=query_text,
        scraped_at=utc_now_iso(),
        dedup_key="|".join(part for part in [CONFIG.key, notice_id or internal_id, item_no or ""] if part),
    )
    return [row.to_dict()]


def map_notice_to_rows(query_text: str = "") -> List[Dict[str, str]]:
    payload = _load_fixture_notice()
    if payload.get("mapped_fields"):
        return _map_fixture_notice_to_rows(payload, query_text or "fixture")

    pdf_text = ""
    pdf_hint_path = Path("evidence") / "hungary_notice_8803469030747.pdf"
    if pdf_hint_path.exists():
        try:
            pdf_text = _extract_pdf_text(pdf_hint_path.read_bytes())
        except Exception:
            pdf_text = ""
    return _map_notice_to_rows(payload, pdf_text=pdf_text, query_text=query_text or "fixture")


def smoke_probe() -> SmokeProbeResult:
    rows = map_notice_to_rows(query_text="fixture:public_notice_pdf")
    row = rows[0]
    ok = all(
        [
            row["notice_id"],
            row["title"],
            row["buyer"],
            row["currency"],
            row["contract_period"],
        ]
    )
    return SmokeProbeResult(
        source_key=CONFIG.key,
        ok=ok,
        mode="fixture",
        detail="Mapped one public Hungary notice sample with PDF-backed currency and contract-period fields.",
        sample_rows=rows,
    )


def live_medical_awarded_rows(date_from: str, date_to: str, page_size: int = 10) -> List[Dict[str, str]]:
    rows: List[Dict[str, str]] = []
    seen_notice_ids: set[str] = set()

    for query_text in QUERY_TERMS:
        for page_number in range(1, 6):
            try:
                payload = _fetch_list_page(query_text, page_number=page_number, page_size=page_size)
            except RequestException:
                break
            notice_list = payload.get("lista") or []
            if not notice_list:
                break

            new_ids = 0
            for summary in notice_list:
                notice_id = _normalized(summary.get("id"))
                if not notice_id or notice_id in seen_notice_ids:
                    continue
                if not _within_window(summary.get("hirdetmenyKozzetetelDatuma"), date_from, date_to):
                    continue
                seen_notice_ids.add(notice_id)
                new_ids += 1
                try:
                    detail = _fetch_notice_detail(notice_id)
                except RequestException:
                    continue
                if not _is_awarded_notice(detail):
                    continue
                try:
                    pdf_text = _extract_pdf_text(_download_notice_pdf(notice_id))
                except Exception:
                    pdf_text = ""
                if not _is_medical_notice(detail, pdf_text):
                    continue
                rows.extend(
                    _map_notice_to_rows(
                        detail,
                        pdf_text=pdf_text,
                        query_text=f"live-medical-awarded:{query_text}:page={page_number}",
                    )
                )
            if new_ids == 0:
                break
    return rows

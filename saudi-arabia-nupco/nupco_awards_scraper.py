import argparse
import re
import time
from dataclasses import dataclass
from datetime import date, datetime, timezone
from io import BytesIO
from typing import Dict, Iterable, List, Optional, Tuple
from urllib.parse import urljoin

import requests
from bs4 import BeautifulSoup, Tag
from award_io import ensure_parent_dir, validate_rows, write_csv, write_jsonl
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

try:
    from pypdf import PdfReader
except ImportError as exc:  # pragma: no cover
    raise SystemExit("Missing dependency: pypdf") from exc

try:
    from playwright.sync_api import sync_playwright
except ImportError as exc:  # pragma: no cover
    raise SystemExit("Missing dependency: playwright") from exc


LISTING_URL = "https://www.nupco.com/en/tenders/"
USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36"
)
PDF_TIMEOUT = 60
HTTP_TIMEOUT = 60
HTTP_CONNECT_TIMEOUT = 20
HTTP_READ_TIMEOUT = 60
HTTP_RETRY_ATTEMPTS = 5
HTTP_RETRY_BACKOFF_BASE_SECONDS = 1.5
DEFAULT_CURRENCY = "SAR"
DATE_WINDOW_START = date(2024, 1, 1)
DATE_WINDOW_END = date(2026, 5, 19)
RESULT_KEYWORDS = ("result", "announcement", "preliminary", "final")
ITEM_KEYWORDS = ("item list", "items list", "items", "list")
PRELIMINARY_KEYWORDS = ("preliminary",)
TERMS_KEYWORDS = ("terms", "condition", "conditions", "term and condition", "terms and conditions")
DATE_RE = re.compile(r"\b\d{1,2}[/-]\d{1,2}[/-]\d{2,4}\b|\b\d{4}-\d{2}-\d{2}\b")
AMOUNT_RE = re.compile(r"([0-9]+(?:,[0-9]{3})*(?:\.[0-9]+)?)")
VENDOR_SPLIT_RE = re.compile(r"^(?P<item_no>\d+)\s+(?P<nupco_code>\d+)\s+(?P<description>.+?)\s+ITEMIZED\s+(?P<vendor_no>\d{5,6})\s*(?P<rest>.*)$")
GENERIC_ROW_RE = re.compile(r"^(?P<item_no>\d{1,4})\s+(?P<nupco_code>\d{10,13})\s+(?P<rest>.+)$")
DATE_SUFFIX_RE = re.compile(r"(?P<date>\b(?:\d{1,2}[/-]\d{1,2}[/-]\d{2,4}|[A-Z][a-z]{2,8}\s+\d{1,2}\s+\d{4})\b)$")
ITEM_LIST_START_RE = re.compile(r"^(?P<item_no>\d{1,4})\s+(?P<nupco_code>\d{10,13})\s+(?P<rest>.+)$")
ITEM_LIST_PAGE_RE = re.compile(r"^www\.nupco\.com\b|^page\s+\d+\b", re.I)
ITEM_LIST_ROW_START_RE = re.compile(r"^(?P<item_no>\d{1,4})\s+(?P<code>\d{10,13})\s+(?P<rest>.+)$")


@dataclass
class TenderCard:
    title: str
    status: Optional[str]
    notice_url: str


@dataclass
class AwardRow:
    source: str
    country: str
    country_code: str
    publication_date: Optional[str]
    closing_date: Optional[str]
    title: Optional[str]
    description: Optional[str]
    buyer: Optional[str]
    classification: Optional[str]
    status: Optional[str]
    currency: Optional[str]
    amount: Optional[str]
    awarding_agency_name: Optional[str]
    supplier_name: Optional[str]
    awarded_date: Optional[str]
    awarded_value_detail: Optional[str]
    contract_period: Optional[str]
    item_no: Optional[str]
    item_description: Optional[str]
    item_uom: Optional[str]
    item_quantity: Optional[str]
    item_unit_price: Optional[str]
    item_awarded_value: Optional[str]
    notice_id: Optional[str]
    notice_url: str
    query_text: str
    scraped_at_utc: str
    dedup_key: str


def build_session() -> requests.Session:
    session = requests.Session()
    session.headers.update({"User-Agent": USER_AGENT})
    retry = Retry(
        total=HTTP_RETRY_ATTEMPTS,
        connect=HTTP_RETRY_ATTEMPTS,
        read=HTTP_RETRY_ATTEMPTS,
        status=HTTP_RETRY_ATTEMPTS,
        backoff_factor=1,
        status_forcelist=(429, 500, 502, 503, 504),
        allowed_methods=frozenset({"GET"}),
        raise_on_status=False,
    )
    adapter = HTTPAdapter(max_retries=retry)
    session.mount("https://", adapter)
    session.mount("http://", adapter)
    return session


def log_debug(message: str) -> None:
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    safe_message = message.encode("ascii", errors="backslashreplace").decode("ascii")
    print(f"[nupco {timestamp}] {safe_message}", flush=True)


def clean_text(value: Optional[str]) -> Optional[str]:
    if value is None:
        return None
    cleaned = re.sub(r"\s+", " ", value).strip()
    return cleaned or None


def normalize_searchable_text(value: Optional[str]) -> Optional[str]:
    if value is None:
        return None
    translated = value.translate(
        str.maketrans(
            "٠١٢٣٤٥٦٧٨٩۰۱۲۳۴۵۶۷۸۹",
            "01234567890123456789",
        )
    )
    translated = translated.replace("\u00a0", " ")
    translated = re.sub(r"[\u200f\u200e]", "", translated)
    translated = re.sub(r"[,:;|]+", " ", translated)
    return clean_text(translated)


def looks_like_noise_description(text: Optional[str]) -> bool:
    if not text:
        return True
    lowered = text.lower()
    noise_markers = (
        "all rights reserved",
        "nupco",
        "copyright",
        "privacy policy",
        "terms and conditions",
    )
    if any(marker in lowered for marker in noise_markers):
        return True
    if len(text) < 30:
        return True
    return False


def normalize_date(raw: Optional[str]) -> Optional[str]:
    if not raw:
        return None
    raw = clean_text(raw)
    for fmt in ("%d/%m/%Y", "%d-%m-%Y", "%Y-%m-%d", "%m/%d/%Y"):
        try:
            return datetime.strptime(raw, fmt).strftime("%Y-%m-%d")
        except ValueError:
            continue
    match = DATE_RE.search(raw)
    if not match:
        return raw
    matched = match.group(0)
    if matched == raw:
        return raw
    return normalize_date(matched) or raw


def parse_iso_date(raw: Optional[str]) -> Optional[date]:
    normalized = normalize_date(raw)
    if not normalized:
        return None
    try:
        return datetime.strptime(normalized, "%Y-%m-%d").date()
    except ValueError:
        return None


def normalize_amount(raw: Optional[str]) -> Optional[str]:
    if not raw:
        return None
    match = AMOUNT_RE.search(raw.replace("SAR", "").replace("ريال", ""))
    if not match:
        return clean_text(raw)
    return match.group(1).replace(",", "")


def normalize_contract_period(raw: Optional[str]) -> Optional[str]:
    if not raw:
        return None
    text = clean_text(raw)
    if not text:
        return None
    label_match = re.search(r"(?:Contract Period|Contract Duration|مدة العقد|مدة التعاقد)", text, re.I)
    search_text = text
    if label_match:
        search_text = text[label_match.end():]
        stop_match = re.search(
            r"(?:Tender Item List|ITEM LIST|Final Total|Section\s*\d+|Classification|Customer|Supplier|Award|Page\s+\d+)",
            search_text,
            re.I,
        )
        if stop_match:
            search_text = search_text[:stop_match.start()]
    match = re.search(r"\b(\d+(?:\.\d+)?)\s*(Years?|Year|Months?|Month|Days?|Day)\b", search_text, re.I)
    if match:
        amount = match.group(1)
        unit = match.group(2).lower()
        if unit.startswith("year"):
            unit = "Years"
        elif unit.startswith("month"):
            unit = "Months"
        elif unit.startswith("day"):
            unit = "Days"
        else:
            unit = clean_text(match.group(2)) or match.group(2)
        return f"{amount} {unit}"
    arabic_match = re.search(r"(?:لمدة|لمد[هة])\s*\(?\s*(\d+(?:\.\d+)?)\s*\)?\s*(يوما|يوماً|يوم|أيام|ايام|شهرا|شهراً|شهر|سنوات|سنة|عام)", search_text, re.I)
    if arabic_match:
        amount = arabic_match.group(1)
        unit = arabic_match.group(2)
        if "يوم" in unit or "ايام" in unit or "أيام" in unit:
            return f"{amount} Days"
        if "شهر" in unit:
            return f"{amount} Months"
        if "سنة" in unit or "سنوات" in unit or "عام" in unit:
            return f"{amount} Years"
    return None


def extract_contract_period_from_text(raw: Optional[str]) -> Optional[str]:
    if not raw:
        return None
    text = clean_text(raw)
    if not text:
        return None

    def extract_duration(search_text: str) -> Optional[str]:
        direct = normalize_contract_period(search_text)
        if direct:
            return direct
        match = re.search(
            r"\b(\d+(?:\.\d+)?)\s*(?:calendar\s+)?(Years?|Year|Months?|Month|Days?|Day)\b",
            search_text,
            re.I,
        )
        if not match:
            return None
        amount = match.group(1)
        unit = match.group(2).lower()
        if unit.startswith("year"):
            return f"{amount} Years"
        if unit.startswith("month"):
            return f"{amount} Months"
        if unit.startswith("day"):
            return f"{amount} Days"
        return f"{amount} {clean_text(match.group(2)) or match.group(2)}"

    label_patterns = [
        r"Contract Period",
        r"Contract Duration",
        r"Offer Validity(?: Period)?",
        r"Bid Validity(?: Period)?",
        r"Validity Period",
        r"صلاحية العروض",
        r"مدة سريان العروض",
        r"مدة العقد",
        r"مدة التعاقد",
    ]
    stop_pattern = r"(?:Tender Item List|ITEM LIST|Final Total|Section\s*\d+|Classification|Customer|Supplier|Award|Page\s+\d+)"

    for pattern in label_patterns:
        for label_match in re.finditer(pattern, text, re.I):
            search_text = text[label_match.end():]
            stop_match = re.search(stop_pattern, search_text, re.I)
            if stop_match:
                search_text = search_text[:stop_match.start()]
            duration = extract_duration(search_text[:500])
            if duration:
                return duration

    lines = [clean_text(line) for line in text.splitlines()]
    lines = [line for line in lines if line]
    for line in lines:
        lowered = line.lower()
        if any(
            token in lowered
            for token in (
                "contract period",
                "contract duration",
                "offer validity",
                "bid validity",
                "validity period",
                "صلاحية العروض",
                "مدة سريان العروض",
            )
        ):
            duration = extract_duration(line)
            if duration:
                return duration
    for index, line in enumerate(lines):
        if any(token in line for token in ("صلاحية العروض", "مدة سريان العروض")):
            window_text = " ".join(lines[index : index + 4])
            duration = extract_duration(window_text)
            if duration:
                return duration

    return extract_duration(text[:2000])


def normalize_contract_period(raw: Optional[str]) -> Optional[str]:
    if not raw:
        return None
    text = normalize_searchable_text(raw)
    if not text:
        return None

    english_match = re.search(
        r"\b(\d+(?:\.\d+)?)\s*(?:calendar\s+)?(Years?|Year|Months?|Month|Days?|Day)\b",
        text,
        re.I,
    )
    if english_match:
        amount = english_match.group(1)
        unit = english_match.group(2).lower()
        if unit.startswith("year"):
            return f"{amount} Years"
        if unit.startswith("month"):
            return f"{amount} Months"
        return f"{amount} Days"

    arabic_match = re.search(
        r"(?:\u0635\u0644\u0627\u062d\u064a\u0629\s+\u0627\u0644\u0639\u0631\u0648\u0636|\u0639\u0631\u0636(?:\s+\u0627\u0644\u0639\u0637\u0627\u0621)?|\u0645\u062f\u0629\s+\u0633\u0631\u064a\u0627\u0646\s+\u0627\u0644\u0639\u0631\u0648\u0636|\u0645\u062f\u0629\s+\u0627\u0644\u0639\u0642\u062f|\u0645\u062f\u0629\s+\u0627\u0644\u062a\u0639\u0627\u0642\u062f|\u0633\u0627\u0631\u064a\s+\u0627\u0644\u0645\u0641\u0639\u0648\u0644\s+\u0644\u0645\u062f\u0629|\u0633\u0627\u0631\u064a\u0629\s+\u0644\u0645\u062f\u0629|\u0644\u0645\u062f\u0629)[^\d]{0,120}\(?\s*(\d+(?:\.\d+)?)\s*\)?(?:\s*[\u0621-\u064a]+){0,6}\s*(\u064a\u0648\u0645(?:\u0627|\u0627\u064b|\u064b\u0627)?|\u0623\u064a\u0627\u0645|\u0627\u064a\u0627\u0645|\u0634\u0647\u0631(?:\u0627|\u0627\u064b|\u064b\u0627)?|\u0623\u0634\u0647\u0631|\u0633\u0646\u0629|\u0633\u0646\u0647|\u0633\u0646\u0648\u0627\u062a|\u0639\u0627\u0645)",
        text,
        re.I,
    )
    if not arabic_match:
        return None

    amount = arabic_match.group(1)
    unit = arabic_match.group(2)
    if "\u064a\u0648\u0645" in unit or "\u0627\u064a\u0627\u0645" in unit or "\u0623\u064a\u0627\u0645" in unit:
        return f"{amount} Days"
    if "\u0634\u0647\u0631" in unit or "\u0623\u0634\u0647\u0631" in unit:
        return f"{amount} Months"
    return f"{amount} Years"


def extract_contract_period_from_text(raw: Optional[str]) -> Optional[str]:
    if not raw:
        return None
    text = normalize_searchable_text(raw)
    if not text:
        return None

    direct = normalize_contract_period(text)
    if direct:
        return direct

    label_patterns = [
        r"Contract Period",
        r"Contract Duration",
        r"Offer Validity(?: Period)?",
        r"Bid Validity(?: Period)?",
        r"Validity Period",
        r"\u0635\u0644\u0627\u062d\u064a\u0629\s+\u0627\u0644\u0639\u0631\u0648\u0636",
        r"\u0645\u062f\u0629\s+\u0633\u0631\u064a\u0627\u0646\s+\u0627\u0644\u0639\u0631\u0648\u0636",
        r"\u0645\u062f\u0629\s+\u0627\u0644\u0639\u0642\u062f",
        r"\u0645\u062f\u0629\s+\u0627\u0644\u062a\u0639\u0627\u0642\u062f",
        r"\u0633\u0627\u0631\u064a\s+\u0627\u0644\u0645\u0641\u0639\u0648\u0644\s+\u0644\u0645\u062f\u0629",
    ]
    for pattern in label_patterns:
        for match in re.finditer(pattern, text, re.I):
            window_text = text[match.start() : match.start() + 300]
            duration = normalize_contract_period(window_text)
            if duration:
                return duration

    lines = [line for line in (normalize_searchable_text(part) for part in text.splitlines()) if line]
    for index in range(len(lines)):
        window_text = " ".join(lines[index : index + 6])
        duration = normalize_contract_period(window_text)
        if duration:
            return duration

    return None


def extract_explicit_contract_period_from_text(raw: Optional[str]) -> Optional[str]:
    if not raw:
        return None
    text = normalize_searchable_text(raw)
    if not text:
        return None

    label_patterns = [
        r"Contract Period",
        r"Contract Duration",
        r"\u0645\u062f\u0629\s+\u0627\u0644\u0639\u0642\u062f",
        r"\u0645\u062f\u0629\s+\u0627\u0644\u062a\u0639\u0627\u0642\u062f",
    ]
    for pattern in label_patterns:
        for match in re.finditer(pattern, text, re.I):
            window_text = text[match.start() : match.start() + 300]
            duration = normalize_contract_period(window_text)
            if duration:
                return duration

    lines = [line for line in (normalize_searchable_text(part) for part in text.splitlines()) if line]
    for index, line in enumerate(lines):
        if any(
            token in line.lower()
            for token in (
                "contract period",
                "contract duration",
            )
        ) or any(
            token in line
            for token in (
                "\u0645\u062f\u0629 \u0627\u0644\u0639\u0642\u062f",
                "\u0645\u062f\u0629 \u0627\u0644\u062a\u0639\u0627\u0642\u062f",
            )
        ):
            window_text = " ".join(lines[index : index + 4])
            duration = normalize_contract_period(window_text)
            if duration:
                return duration
    return None


def fetch_with_retries(session: requests.Session, url: str, timeout: Tuple[int, int]) -> requests.Response:
    last_error: Optional[Exception] = None
    for attempt in range(1, HTTP_RETRY_ATTEMPTS + 1):
        try:
            log_debug(f"GET attempt {attempt}/{HTTP_RETRY_ATTEMPTS}: {url}")
            response = session.get(url, timeout=timeout)
            response.raise_for_status()
            return response
        except requests.exceptions.RequestException as exc:
            last_error = exc
            log_debug(f"GET failed on attempt {attempt}/{HTTP_RETRY_ATTEMPTS}: {url} :: {exc}")
            if attempt == HTTP_RETRY_ATTEMPTS:
                break
            time.sleep(HTTP_RETRY_BACKOFF_BASE_SECONDS * (2 ** (attempt - 1)))
    if last_error is None:  # pragma: no cover
        raise RuntimeError(f"GET failed without an exception for {url}")
    raise last_error


def fetch_html(session: requests.Session, url: str) -> str:
    response = fetch_with_retries(session, url, timeout=(HTTP_CONNECT_TIMEOUT, HTTP_READ_TIMEOUT))
    response.encoding = response.apparent_encoding or response.encoding or "utf-8"
    return response.text


def fetch_pdf_text(session: requests.Session, url: str) -> Optional[str]:
    response = fetch_with_retries(session, url, timeout=(HTTP_CONNECT_TIMEOUT, PDF_TIMEOUT))
    content_type = (response.headers.get("content-type") or "").lower()
    if "pdf" not in content_type and not response.content.startswith(b"%PDF"):
        return None
    reader = PdfReader(BytesIO(response.content))
    pages = []
    for page in reader.pages:
        pages.append(page.extract_text() or "")
    return "\n".join(pages)


def extract_cards_with_scroll(max_tenders: Optional[int], headless: bool) -> List[TenderCard]:
    cards: Dict[str, TenderCard] = {}
    order: List[str] = []
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=headless)
        page = browser.new_page()
        log_debug(f"Opening NUPCO listing page: {LISTING_URL}")
        page.goto(LISTING_URL, wait_until="networkidle", timeout=120000)
        stable_rounds = 0
        previous_count = 0

        while stable_rounds < 3:
            anchors = page.locator("a[href*='/en/tenders_post/']")
            count = anchors.count()
            for i in range(count):
                anchor = anchors.nth(i)
                href = anchor.get_attribute("href")
                title = clean_text(anchor.inner_text())
                if not href or not title:
                    continue
                url = urljoin(LISTING_URL, href)
                card_box = anchor.locator("xpath=ancestor::div[contains(@class,'mix')][1]")
                status = None
                try:
                    card_text = clean_text(card_box.inner_text(timeout=2000))
                except Exception:
                    card_text = None
                if card_text:
                    status_match = re.search(r"(First Result|Final Result)", card_text, re.I)
                    status = status_match.group(1) if status_match else None
                if status:
                    if url not in cards:
                        order.append(url)
                    cards[url] = TenderCard(title=title, status=status, notice_url=url)
            log_debug(f"Listing scan saw {len(cards)} tender cards with result statuses so far.")

            page.mouse.wheel(0, 5000)
            page.wait_for_timeout(1500)
            if len(cards) == previous_count:
                stable_rounds += 1
            else:
                stable_rounds = 0
                previous_count = len(cards)
            if max_tenders and len(cards) >= max_tenders:
                break
        browser.close()

    rows = [cards[url] for url in order]
    if max_tenders:
        rows = rows[:max_tenders]
    return rows


def all_text_near(node: Tag) -> List[str]:
    values = []
    if node.parent:
        values.extend(list(node.parent.stripped_strings))
    if isinstance(node.next_sibling, str):
        values.append(node.next_sibling.strip())
    elif isinstance(node.next_sibling, Tag):
        values.extend(list(node.next_sibling.stripped_strings))
    return [clean_text(v) for v in values if clean_text(v)]


def find_labeled_value(soup: BeautifulSoup, labels: Iterable[str]) -> Optional[str]:
    label_set = tuple(label.lower() for label in labels)
    for text_node in soup.find_all(string=True):
        text = clean_text(str(text_node))
        if not text:
            continue
        lowered = text.lower().rstrip(":")
        if lowered not in label_set:
            continue
        parent = text_node.parent if isinstance(text_node.parent, Tag) else None
        if parent:
            for candidate in all_text_near(parent):
                if candidate.lower().rstrip(":") != lowered:
                    return candidate
    soup_text = "\n".join(soup.stripped_strings)
    for label in labels:
        pattern = re.compile(re.escape(label) + r"\s*:?\s*(.+)", re.I)
        match = pattern.search(soup_text)
        if match:
            return clean_text(match.group(1))
    return None


def parse_detail_page(html: str, url: str, card: TenderCard) -> Dict[str, Optional[str]]:
    soup = BeautifulSoup(html, "html.parser")
    title = clean_text((soup.find("h1") or soup.find("title")).get_text(" ", strip=True)) if soup.find("h1") or soup.find("title") else card.title
    detail_values = {}
    for heading in soup.select("h3"):
        key = clean_text(heading.get_text(" ", strip=True))
        if not key:
            continue
        value = None
        sibling = heading.find_next_sibling()
        while sibling and not value:
            sibling_text = clean_text(sibling.get_text(" ", strip=True))
            if sibling_text:
                value = sibling_text
                break
            sibling = sibling.find_next_sibling()
        if value:
            detail_values[key] = value
    tender_id = (
        detail_values.get("Tender ID")
        or detail_values.get("Tender Id")
        or detail_values.get("Tendr Id")
        or find_labeled_value(soup, ["Tender Id", "Tender ID", "Tendr Id"])
    )
    bid_opening_date = normalize_date(detail_values.get("Bid Opening") or detail_values.get("Bid Opening Date") or find_labeled_value(soup, ["Bid Opening", "Bid Opening Date"]))
    submission_deadline = normalize_date(detail_values.get("Submission Deadline") or find_labeled_value(soup, ["Submission Deadline"]))
    booklet_price = normalize_amount(detail_values.get("Tender Booklet Price") or find_labeled_value(soup, ["Tender Booklet Price", "Booklet Price"]))
    contract_period = extract_explicit_contract_period_from_text(
        detail_values.get("Contract Period")
        or detail_values.get("Contract Duration")
        or find_labeled_value(soup, ["Contract Period", "Contract Duration", "مدة العقد", "مدة التعاقد"])
    )
    attachment_links = []
    for anchor in soup.select("a[href]"):
        href = anchor.get("href")
        if not href or ".pdf" not in href.lower():
            continue
        attachment_links.append(
            {
                "url": urljoin(url, href),
                "label": clean_text(anchor.get_text(" ", strip=True)) or href.rsplit("/", 1)[-1],
            }
        )
    description = None
    for candidate in soup.select("article p, .entry-content p, .post-content p, main p, p"):
        text = clean_text(candidate.get_text(" ", strip=True))
        if looks_like_noise_description(text):
            continue
        if "Saudi Arabia" in text and any(char.isdigit() for char in text):
            continue
        description = text
        break
    return {
        "notice_id": tender_id,
        "publication_date": bid_opening_date,
        "closing_date": submission_deadline,
        "amount": booklet_price,
        "currency": DEFAULT_CURRENCY,
        "title": title or card.title,
        "status": card.status,
        "classification": card.status,
        "description": description,
        "contract_period": contract_period,
        "buyer": "NUPCO",
        "awarding_agency_name": "NUPCO",
        "attachments": attachment_links,
    }


def categorize_attachments(
    attachments: List[Dict[str, str]],
) -> Tuple[List[Dict[str, str]], List[Dict[str, str]], List[Dict[str, str]], List[Dict[str, str]]]:
    preliminary_pdfs = []
    result_pdfs = []
    item_pdfs = []
    terms_pdfs = []
    for attachment in attachments:
        label = (attachment.get("label") or "").lower()
        if "faq" in label:
            continue
        if any(keyword in label for keyword in TERMS_KEYWORDS):
            terms_pdfs.append(attachment)
            continue
        if any(keyword in label for keyword in PRELIMINARY_KEYWORDS):
            preliminary_pdfs.append(attachment)
        elif any(keyword in label for keyword in ITEM_KEYWORDS):
            item_pdfs.append(attachment)
        elif any(keyword in label for keyword in RESULT_KEYWORDS):
            result_pdfs.append(attachment)
    result_pdfs.sort(key=lambda x: ("final" not in (x["label"] or "").lower(), x["url"]))
    preliminary_pdfs.sort(key=lambda x: x["url"])
    item_pdfs.sort(key=lambda x: x["url"])
    terms_pdfs.sort(key=lambda x: x["url"])
    return preliminary_pdfs, result_pdfs, item_pdfs, terms_pdfs


def looks_like_model_token(token: str) -> bool:
    if not token:
        return False
    if token.upper() in {"GENERAL", "ITEMIZED", "SPECIALIZED"}:
        return False
    return bool(re.search(r"\d", token) or "." in token or "-" in token or "/" in token)


def parse_preliminary_result_rows(pdf_text: str) -> Dict[str, Dict[str, Optional[str]]]:
    rows: Dict[str, Dict[str, Optional[str]]] = {}
    lines = [clean_text(line) for line in pdf_text.splitlines()]
    lines = [line for line in lines if line]
    blocks: List[str] = []
    buffer = ""
    for line in lines:
        if ITEM_LIST_PAGE_RE.match(line):
            continue
        if re.search(r"\b(?:SN|SRM|ITEM NO|ITEM NAME|SUPPLIER CODE|SUPPLIER NAME|MODEL|MANUFACTURER|COUNTRY|REMARKS|GROUP)\b", line, re.I):
            continue
        if re.match(r"^\d{1,4}\s+\d{7,14}\s+", line):
            if buffer:
                blocks.append(buffer)
            buffer = line
            continue
        if buffer:
            buffer = clean_text(f"{buffer} {line}")
    if buffer:
        blocks.append(buffer)

    for block in blocks:
        tokens = block.split()
        if len(tokens) < 8:
            continue
        item_no = tokens[0]
        if not item_no.isdigit():
            continue
        supplier_code_idx = None
        for idx in range(3, len(tokens)):
            if re.fullmatch(r"\d{5,7}", tokens[idx]):
                supplier_code_idx = idx
                break
        if supplier_code_idx is None or supplier_code_idx + 2 >= len(tokens):
            continue
        supplier_name_end = None
        for idx in range(supplier_code_idx + 1, len(tokens) - 2):
            if looks_like_model_token(tokens[idx]):
                supplier_name_end = idx
                break
        if supplier_name_end is None:
            continue
        supplier_name = clean_text(" ".join(tokens[supplier_code_idx + 1 : supplier_name_end]))
        if supplier_name:
            rows[item_no] = {"supplier_name": supplier_name}
    return rows


def parse_item_list_rows(pdf_text: str) -> List[Dict[str, Optional[str]]]:
    rows: List[Dict[str, Optional[str]]] = []
    lines = [clean_text(line) for line in pdf_text.splitlines()]
    lines = [line for line in lines if line]
    blocks: List[str] = []
    buffer = ""
    for line in lines:
        if ITEM_LIST_PAGE_RE.match(line):
            continue
        if re.search(r"\b(?:SN|SRM CODE|ITEM LIST|ITEM DESCRIPTION|UOM|QTY|GROUP)\b", line, re.I):
            continue
        if ITEM_LIST_ROW_START_RE.match(line):
            if buffer:
                blocks.append(buffer)
            buffer = line
            continue
        if buffer:
            buffer = clean_text(f"{buffer} {line}")
    if buffer:
        blocks.append(buffer)

    for block in blocks:
        parsed = parse_item_list_block(block)
        if not parsed:
            continue
        rows.append(parsed)
    return rows


def parse_item_list_block(block: str) -> Optional[Dict[str, Optional[str]]]:
    if not block:
        return None
    text = clean_text(block)
    if not text:
        return None
    start = ITEM_LIST_ROW_START_RE.match(text)
    if not start:
        return None
    item_no = start.group("item_no")
    tail = clean_text(start.group("rest")) or ""
    tokens = tail.split()
    if len(tokens) < 2:
        return None
    if tokens[-1].upper() in {"GENERAL", "ITEMIZED", "SPECIALIZED"}:
        quantity_token = tokens[-2] if len(tokens) >= 2 else None
        uom_token = tokens[-3] if len(tokens) >= 3 else None
        desc_tokens = tokens[:-3]
    else:
        quantity_token = tokens[-1]
        uom_token = tokens[-2] if len(tokens) >= 2 else None
        desc_tokens = tokens[:-2]
    quantity_match = re.fullmatch(r"\d+(?:\.\d+)?", quantity_token or "")
    if not quantity_match:
        return None
    quantity = quantity_token.replace(",", "")
    uom = clean_text(uom_token)
    if uom:
        uom = uom.upper()
        uom = {
            "PIECES": "PIECE",
            "PCS": "PC",
            "EACHES": "EACH",
            "BTLS": "BOTTLE",
            "VIALS": "VIAL",
            "BAGS": "BAG",
            "ROLLS": "ROLL",
            "SETS": "SET",
            "KITS": "KIT",
            "UNITS": "UNIT",
        }.get(uom, uom)
    description = clean_text(" ".join(desc_tokens)) if desc_tokens else None
    if not description and tail:
        description = clean_text(tail)

    return {
        "item_no": item_no,
        "item_description": description,
        "item_uom": uom,
        "item_quantity": quantity,
    }


def parse_result_pdf_rows(pdf_text: str) -> List[Dict[str, Optional[str]]]:
    lines = [clean_text(line) for line in pdf_text.splitlines()]
    lines = [line for line in lines if line]
    rows: List[List[str]] = []
    current: List[str] = []
    for line in lines:
        if VENDOR_SPLIT_RE.match(line) or GENERIC_ROW_RE.match(line):
            if current:
                rows.append(current)
            current = [line]
        elif current:
            current.append(line)
    if current:
        rows.append(current)

    parsed = []
    for block in rows:
        first_line = block[0]
        match = VENDOR_SPLIT_RE.match(first_line)
        if match:
            item_no = match.group("item_no")
            candidate_text = " ".join([match.group("rest")] + block[1:])
            awarded_date = extract_awarded_date(candidate_text)
        else:
            generic_match = GENERIC_ROW_RE.match(first_line)
            if not generic_match:
                continue
            item_no = generic_match.group("item_no")
            candidate_text = " ".join([generic_match.group("rest")] + block[1:])
            awarded_date = extract_awarded_date(candidate_text)
        parsed.append(
            {
                "item_no": item_no,
                "awarded_date": awarded_date,
            }
        )
    return parsed


def extract_awarded_date(text: str) -> Optional[str]:
    if not text:
        return None
    match = DATE_SUFFIX_RE.search(text)
    if not match:
        return None
    raw = match.group("date")
    for fmt in ("%b %d %Y", "%B %d %Y"):
        try:
            return datetime.strptime(raw, fmt).strftime("%Y-%m-%d")
        except ValueError:
            continue
    return normalize_date(raw)


def merge_result_dates(rows: List[Dict[str, Optional[str]]], result_rows: List[Dict[str, Optional[str]]]) -> None:
    result_by_item_no: Dict[str, str] = {}
    for row in result_rows:
        item_no = row.get("item_no")
        awarded_date = row.get("awarded_date")
        if item_no and awarded_date and item_no not in result_by_item_no:
            result_by_item_no[item_no] = awarded_date
    if not result_by_item_no:
        return
    for row in rows:
        item_no = row.get("item_no")
        if item_no and not row.get("awarded_date") and item_no in result_by_item_no:
            row["awarded_date"] = result_by_item_no[item_no]


def merge_supplier_enrichment(rows: List[Dict[str, Optional[str]]], supplier_rows: Dict[str, Dict[str, Optional[str]]]) -> None:
    for row in rows:
        item_no = row.get("item_no")
        if not item_no:
            continue
        enrichment = supplier_rows.get(item_no)
        if enrichment and not row.get("supplier_name"):
            row["supplier_name"] = enrichment.get("supplier_name")


def apply_dominant_supplier_fallback(
    rows: List[Dict[str, Optional[str]]],
    supplier_rows: Dict[str, Dict[str, Optional[str]]],
) -> None:
    supplier_counts: Dict[str, int] = {}
    for enrichment in supplier_rows.values():
        supplier_name = clean_text(enrichment.get("supplier_name"))
        if not supplier_name:
            continue
        supplier_counts[supplier_name] = supplier_counts.get(supplier_name, 0) + 1
    if not supplier_counts:
        return
    dominant_supplier, dominant_count = max(supplier_counts.items(), key=lambda item: item[1])
    total_supplier_rows = sum(supplier_counts.values())
    if len(supplier_counts) == 1 or dominant_count / max(total_supplier_rows, 1) >= 0.8:
        for row in rows:
            if not clean_text(row.get("supplier_name")):
                row["supplier_name"] = dominant_supplier


def build_award_rows(
    metadata: Dict[str, Optional[str]],
    notice_url: str,
    query_text: str,
    item_rows: List[Dict[str, Optional[str]]],
) -> List[AwardRow]:
    scraped_at_utc = datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")
    if not item_rows:
        item_rows = [{"item_no": None, "item_description": None, "item_uom": None, "item_quantity": None, "supplier_name": None, "awarded_date": None}]
    output = []
    for row in item_rows:
        amount = metadata.get("amount")
        dedup_key = "|".join(
            [
                "nupco",
                metadata.get("notice_id") or "",
                metadata.get("status") or "",
                row.get("item_no") or "",
                row.get("supplier_name") or "",
                row.get("awarded_date") or "",
            ]
        )
        output.append(
            AwardRow(
                source="nupco",
                country="Saudi Arabia",
                country_code="SA",
                publication_date=metadata.get("publication_date"),
                closing_date=metadata.get("closing_date"),
                title=metadata.get("title"),
                description=metadata.get("description") or row.get("item_description"),
                buyer=metadata.get("buyer"),
                classification=metadata.get("classification"),
                status=metadata.get("status"),
                currency=DEFAULT_CURRENCY,
                amount=amount,
                awarding_agency_name=metadata.get("awarding_agency_name"),
                supplier_name=row.get("supplier_name"),
                awarded_date=row.get("awarded_date"),
                awarded_value_detail=amount,
                contract_period=metadata.get("contract_period"),
                item_no=row.get("item_no"),
                item_description=row.get("item_description"),
                item_uom=row.get("item_uom"),
                item_quantity=row.get("item_quantity"),
                item_unit_price=None,
                item_awarded_value=None,
                notice_id=metadata.get("notice_id"),
                notice_url=notice_url,
                query_text=query_text,
                scraped_at_utc=scraped_at_utc,
                dedup_key=dedup_key,
            )
        )
    return output


def is_in_date_window(publication_date: Optional[str]) -> bool:
    parsed = parse_iso_date(publication_date)
    if not parsed:
        return False
    return DATE_WINDOW_START <= parsed <= DATE_WINDOW_END


def scrape(max_tenders: Optional[int], headless: bool) -> List[AwardRow]:
    session = build_session()
    listing_limit = max_tenders * 10 if max_tenders else None
    cards = extract_cards_with_scroll(max_tenders=listing_limit, headless=headless)
    log_debug(f"Collected {len(cards)} candidate tender cards from the listing.")
    all_rows: List[AwardRow] = []
    successful_tenders = 0
    for index, card in enumerate(cards, start=1):
        log_debug(f"Processing tender {index}/{len(cards)}: {card.notice_url}")
        detail_html = fetch_html(session, card.notice_url)
        metadata = parse_detail_page(detail_html, card.notice_url, card)
        if not is_in_date_window(metadata.get("publication_date")):
            log_debug(
                f"Skipping tender outside publication_date window: {card.notice_url} "
                f"(publication_date={metadata.get('publication_date')})"
            )
            continue
        attachments = metadata.pop("attachments") or []
        preliminary_pdfs, result_pdfs, item_pdfs, terms_pdfs = categorize_attachments(attachments)
        log_debug(
            f"Tender attachment buckets for {card.notice_url}: "
            f"item_pdfs={len(item_pdfs)} preliminary_pdfs={len(preliminary_pdfs)} "
            f"result_pdfs={len(result_pdfs)} terms_pdfs={len(terms_pdfs)}"
        )
        contract_period = metadata.get("contract_period")

        for attachment in terms_pdfs:
            if contract_period:
                break
            try:
                pdf_text = fetch_pdf_text(session, attachment["url"])
            except Exception:
                log_debug(f"Failed to fetch terms PDF: {attachment['url']}")
                continue
            if not pdf_text:
                continue
            contract_period = extract_explicit_contract_period_from_text(pdf_text)
            if contract_period:
                log_debug(f"Derived explicit contract period from terms PDF {attachment['url']}: {contract_period}")
            else:
                contract_period = extract_contract_period_from_text(pdf_text)
                if contract_period:
                    log_debug(f"Derived fallback contract period from terms PDF {attachment['url']}: {contract_period}")

        item_rows: List[Dict[str, Optional[str]]] = []
        for attachment in item_pdfs:
            try:
                pdf_text = fetch_pdf_text(session, attachment["url"])
            except Exception:
                log_debug(f"Failed to fetch item PDF: {attachment['url']}")
                continue
            if not pdf_text:
                log_debug(f"Skipped non-PDF or empty item attachment: {attachment['url']}")
                continue
            if not contract_period:
                contract_period = extract_explicit_contract_period_from_text(pdf_text)
            item_rows = parse_item_list_rows(pdf_text)
            if item_rows:
                log_debug(f"Parsed {len(item_rows)} item rows from {attachment['url']}")
                break

        supplier_rows: Dict[str, Dict[str, Optional[str]]] = {}
        for attachment in preliminary_pdfs:
            try:
                pdf_text = fetch_pdf_text(session, attachment["url"])
            except Exception:
                log_debug(f"Failed to fetch preliminary PDF: {attachment['url']}")
                continue
            if not pdf_text:
                continue
            if not contract_period:
                contract_period = extract_explicit_contract_period_from_text(pdf_text)
            supplier_rows.update(parse_preliminary_result_rows(pdf_text))
        if supplier_rows:
            log_debug(f"Supplier enrichment rows collected: {len(supplier_rows)} for {card.notice_url}")

        result_rows: List[Dict[str, Optional[str]]] = []
        for attachment in result_pdfs:
            try:
                pdf_text = fetch_pdf_text(session, attachment["url"])
            except Exception:
                log_debug(f"Failed to fetch result PDF: {attachment['url']}")
                continue
            if not pdf_text:
                continue
            if not contract_period:
                contract_period = extract_explicit_contract_period_from_text(pdf_text)
            parsed_rows = parse_result_pdf_rows(pdf_text)
            result_rows.extend(parsed_rows)
        if result_rows:
            log_debug(f"Result rows collected: {len(result_rows)} for {card.notice_url}")

        if not item_rows:
            log_debug(f"Skipping tender because no item rows were parsed: {card.notice_url}")
            continue
        merge_supplier_enrichment(item_rows, supplier_rows)
        apply_dominant_supplier_fallback(item_rows, supplier_rows)
        merge_result_dates(item_rows, result_rows)
        if contract_period:
            metadata["contract_period"] = contract_period
        tender_rows = build_award_rows(
            metadata=metadata,
            notice_url=card.notice_url,
            query_text="site:nupco.com/en/tenders result",
            item_rows=item_rows,
        )
        all_rows.extend(tender_rows)
        successful_tenders += 1
        log_debug(
            f"Stored {len(tender_rows)} rows for tender {card.notice_url}; "
            f"running total rows={len(all_rows)} successful_tenders={successful_tenders}"
        )
        if max_tenders and successful_tenders >= max_tenders:
            break
        time.sleep(0.5)

    return all_rows


def main() -> None:
    parser = argparse.ArgumentParser(description="Scrape awarded tender data from NUPCO.")
    parser.add_argument("--output", default="nupco_awards.jsonl", help="Output JSONL path")
    parser.add_argument("--csv-output", default=None, help="Optional CSV output path")
    parser.add_argument("--max-tenders", type=int, default=None, help="Limit number of successful tenders to process")
    parser.add_argument("--show-browser", action="store_true", help="Run browser in headed mode")
    parser.add_argument("--validate", action="store_true", help="Validate rows against the normalized schema")
    args = parser.parse_args()
    rows = scrape(max_tenders=args.max_tenders, headless=not args.show_browser)
    ensure_parent_dir(args.output)
    write_jsonl(args.output, rows)
    if args.csv_output:
        ensure_parent_dir(args.csv_output)
        write_csv(args.csv_output, rows)
    if args.validate:
        errors, count = validate_rows([row.__dict__ for row in rows])
        if errors:
            raise SystemExit("Validation failed:\n" + "\n".join(errors[:50]))
        print(f"Validated {count} rows")
    print(f"Wrote {len(rows)} rows to {args.output}")


if __name__ == "__main__":
    main()

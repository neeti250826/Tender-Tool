#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import importlib
import json
import logging
import sys
from dataclasses import dataclass
from html import unescape
from html.parser import HTMLParser
from datetime import datetime, timezone
from pathlib import Path
from typing import TYPE_CHECKING, Dict, Iterable, List, Optional, Sequence, Tuple

import re

if TYPE_CHECKING:
    import pandas as pd_types


ROOT_DIR = Path(__file__).resolve().parents[1]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))


pd = importlib.import_module("pandas")
requests = importlib.import_module("requests")

latam_defaults = importlib.import_module("latam_spec_defaults")
TranslationConfig = getattr(latam_defaults, "TranslationConfig")
add_standard_colab_args = getattr(latam_defaults, "add_standard_colab_args")
build_query_text = getattr(latam_defaults, "build_query_text")
build_run_keywords = getattr(latam_defaults, "build_run_keywords")
build_run_output_stem = getattr(latam_defaults, "build_run_output_stem")
ensure_spec_folder_layout = getattr(latam_defaults, "ensure_spec_folder_layout")
resolve_date_range = getattr(latam_defaults, "resolve_date_range")
resolve_output_base_dir = getattr(latam_defaults, "resolve_output_base_dir")
save_spec_outputs = getattr(latam_defaults, "save_spec_outputs")
translate_dataframe_to_english = getattr(latam_defaults, "translate_dataframe_to_english")

mdt_schema = importlib.import_module("mdt_schema")
to_mdt_schema = getattr(mdt_schema, "to_mdt_schema")

mdt_export = importlib.import_module("mdt_export")
save_mdt_outputs = getattr(mdt_export, "save_mdt_outputs")


logger = logging.getLogger("gebiz_scraper")


NORMALIZED_COLUMNS: List[str] = [
    "source",
    "country",
    "country_code",
    "publication_date",
    "title",
    "description",
    "buyer",
    "classification",
    "tender_status",
    "currency",
    "amount",
    "notice_id",
    "notice_url",
    "query_text",
    "scraped_at_utc",
    "dedup_key",
]


@dataclass(frozen=True)
class AdvancedFilter:
    label: str
    control_id: str
    control_name: str
    control_type: str
    options: Tuple[Tuple[str, str], ...] = ()


@dataclass(frozen=True)
class PlaywrightSession:
    cookies: Tuple[dict, ...]


def _discover_playwright_session(*, url: str, timeout_seconds: int = 30) -> Optional[PlaywrightSession]:
    """Best-effort: use Playwright to obtain browser cookies.

    GeBIZ uses JSF and may set anti-bot/session cookies via JavaScript. When
    requests-only POSTs return a "Session Expired" page, these cookies can be
    required for successful form submission.
    """

    try:
        playwright_sync = importlib.import_module("playwright.sync_api")
        sync_playwright = getattr(playwright_sync, "sync_playwright")
    except Exception:
        return None

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        context = browser.new_context(
            user_agent=(
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
            )
        )
        page = context.new_page()
        page.goto(str(url), wait_until="domcontentloaded", timeout=max(5, int(timeout_seconds)) * 1000)
        page.wait_for_timeout(1500)
        cookies = tuple(context.cookies())
        browser.close()
        if not cookies:
            return None
        return PlaywrightSession(cookies=cookies)


def _strip_tags(value: str) -> str:
    text = re.sub(r"<br\s*/?>", " ", str(value or ""), flags=re.IGNORECASE)
    text = re.sub(r"<[^>]+>", "", text)
    return unescape(text).strip()


class _JSFFormParser(HTMLParser):
    """Minimal HTML parser to extract JSF form fields + labels.

    We avoid external deps (BeautifulSoup) and keep this resilient across
    minor markup changes.
    """

    def __init__(self) -> None:
        super().__init__()
        self.forms: List[dict] = []
        self._active_form: Optional[dict] = None
        self._label_for: Optional[str] = None
        self._label_text: List[str] = []
        self._active_select: Optional[dict] = None
        self._active_option: Optional[dict] = None
        self._active_button: Optional[dict] = None

    def handle_starttag(self, tag: str, attrs: List[tuple[str, Optional[str]]]) -> None:
        a = {k: (v if v is not None else "") for k, v in attrs}
        t = tag.lower()
        if t == "form":
            self._active_form = {
                "id": a.get("id", ""),
                "name": a.get("name", ""),
                "action": a.get("action", ""),
                "inputs": {},  # id -> attrs
                "inputs_by_name": {},  # name -> attrs
                "selects": {},  # id -> attrs + options
                "selects_by_name": {},
                "buttons": [],  # attrs + text
                "labels": [],  # (for_id, text)
            }
            self.forms.append(self._active_form)
            return

        if self._active_form is None:
            return

        if t == "input":
            inp = {
                "id": a.get("id", ""),
                "name": a.get("name", ""),
                "type": (a.get("type", "") or "").lower(),
                "value": a.get("value", ""),
            }
            if inp["id"]:
                self._active_form["inputs"][inp["id"]] = inp
            if inp["name"]:
                self._active_form["inputs_by_name"][inp["name"]] = inp
        elif t == "select":
            sel = {
                "id": a.get("id", ""),
                "name": a.get("name", ""),
                "options": [],  # list[dict(value,label)]
            }
            if sel["id"]:
                self._active_form["selects"][sel["id"]] = sel
            if sel["name"]:
                self._active_form["selects_by_name"][sel["name"]] = sel
            self._active_select = sel
        elif t == "option" and self._active_select is not None:
            opt = {"value": a.get("value", ""), "label_parts": []}
            self._active_option = opt
            self._active_select["options"].append(opt)
        elif t == "button":
            btn = {
                "id": a.get("id", ""),
                "name": a.get("name", ""),
                "type": (a.get("type", "") or "").lower(),
                "value": a.get("value", ""),
                "text_parts": [],
            }
            self._active_form["buttons"].append(btn)
            self._active_button = btn
        elif t == "label":
            self._label_for = a.get("for", "")
            self._label_text = []

    def handle_endtag(self, tag: str) -> None:
        t = tag.lower()
        if t == "form":
            self._active_form = None
            self._active_button = None
        elif t == "label" and self._active_form is not None and self._label_for is not None:
            text = _strip_tags(" ".join(self._label_text))
            self._active_form["labels"].append((self._label_for, text))
            self._label_for = None
            self._label_text = []
        elif t == "select":
            self._active_select = None
        elif t == "option":
            self._active_option = None
        elif t == "button":
            self._active_button = None

    def handle_data(self, data: str) -> None:
        if self._active_form is None:
            return
        if self._label_for is not None:
            self._label_text.append(str(data or ""))
        if self._active_button is not None:
            self._active_button["text_parts"].append(str(data or ""))
        if self._active_option is not None:
            self._active_option["label_parts"].append(str(data or ""))


def _parse_jsf_forms(html: str) -> List[dict]:
    parser = _JSFFormParser()
    parser.feed(str(html or ""))

    # Finalize option/button labels.
    for form in parser.forms:
        for sel in list(form.get("selects", {}).values()):
            for opt in sel.get("options", []):
                opt["label"] = _strip_tags(" ".join(opt.get("label_parts", [])))
        for btn in form.get("buttons", []):
            btn["text"] = _strip_tags(" ".join(btn.get("text_parts", [])))
    return parser.forms


def _pick_main_search_form(forms: List[dict]) -> Optional[dict]:
    """Pick the form most likely to be the main advanced search form."""

    if not forms:
        return None
    # Heuristic: choose the form with the most inputs/selects, but boost the one
    # that looks like the BOAdvancedSearch form.
    def score(f: dict) -> int:
        base = int(len(f.get("inputs", {})) + len(f.get("selects", {})) + len(f.get("buttons", [])))
        action = str(f.get("action", "") or "").lower()
        if "boadvancedsearch" in action:
            base += 50
        for btn in list(f.get("buttons", [])):
            if "search" in str(btn.get("text", "") or "").lower():
                base += 50
        return base

    return sorted(forms, key=score, reverse=True)[0]


def _pick_form_by_action(forms: List[dict], action_contains: str) -> Optional[dict]:
    """Pick the form whose action contains a token (case-insensitive)."""

    token = str(action_contains or "").strip().lower()
    if not token:
        return None
    for f in list(forms or []):
        action = str(f.get("action", "") or "").lower()
        if token in action:
            return f
    return None


def _extract_view_state(form: dict) -> str:
    # JSF uses either id or name 'javax.faces.ViewState'
    inp = form.get("inputs_by_name", {}).get("javax.faces.ViewState")
    if isinstance(inp, dict) and inp.get("value"):
        return str(inp.get("value"))
    # Fallback: search in inputs by id
    for val in form.get("inputs", {}).values():
        if str(val.get("name", "")) == "javax.faces.ViewState" and val.get("value"):
            return str(val.get("value"))
    return ""


def list_advanced_search_filters(html: str) -> List[AdvancedFilter]:
    forms = _parse_jsf_forms(html)
    form = _pick_main_search_form(forms)
    if not form:
        return []

    out: List[AdvancedFilter] = []
    for for_id, label in list(form.get("labels", [])):
        if not label or not for_id:
            continue
        # Try resolve to select/input by id.
        sel = form.get("selects", {}).get(for_id)
        inp = form.get("inputs", {}).get(for_id)
        if isinstance(sel, dict):
            name = str(sel.get("name", ""))
            options = tuple((str(o.get("value", "")), str(o.get("label", ""))) for o in sel.get("options", []))
            out.append(
                AdvancedFilter(
                    label=label,
                    control_id=str(for_id),
                    control_name=name,
                    control_type="select",
                    options=options,
                )
            )
        elif isinstance(inp, dict):
            out.append(
                AdvancedFilter(
                    label=label,
                    control_id=str(for_id),
                    control_name=str(inp.get("name", "")),
                    control_type=str(inp.get("type", "") or "input"),
                )
            )

    # Stable order and de-dupe by (label,name)
    seen = set()
    ordered: List[AdvancedFilter] = []
    for f in sorted(out, key=lambda x: (x.label.lower(), x.control_name.lower())):
        key = (f.label.lower(), f.control_name)
        if key in seen:
            continue
        seen.add(key)
        ordered.append(f)
    return ordered


def _find_search_button(form: dict) -> Optional[dict]:
    """Return a button/input dict representing the 'Search' action."""

    # Prefer a <button> with visible text 'Search'
    for btn in list(form.get("buttons", [])):
        text = str(btn.get("text", "") or "").lower()
        if "search" in text:
            return btn

    # Fallback to an <input type=submit> with value containing Search
    for inp in list(form.get("inputs_by_name", {}).values()):
        if str(inp.get("type", "")) not in {"submit", "button"}:
            continue
        val = str(inp.get("value", "") or "").lower()
        if "search" in val:
            return inp
    return None


def _find_submit_input_by_value(form: dict, wanted_value: str) -> Optional[dict]:
    """Find a submit/button input whose value equals wanted_value."""

    want = str(wanted_value or "").strip().lower()
    if not want:
        return None
    for inp in list(form.get("inputs_by_name", {}).values()):
        if str(inp.get("type", "") or "").lower() not in {"submit", "button"}:
            continue
        val = str(inp.get("value", "") or "").strip().lower()
        if val == want:
            return inp
    return None


def _label_to_filter_map(filters: Iterable[AdvancedFilter]) -> Dict[str, AdvancedFilter]:
    out: Dict[str, AdvancedFilter] = {}
    for f in list(filters or []):
        out[f.label.strip().lower()] = f
    return out


def _resolve_select_value(filter_def: AdvancedFilter, desired: str) -> str:
    want = str(desired or "").strip()
    if not want:
        return ""

    # First: exact match against option values.
    for value, label in filter_def.options:
        if want == value:
            return value

    # Second: case-insensitive match against labels.
    want_norm = want.lower()
    for value, label in filter_def.options:
        if want_norm == str(label or "").strip().lower():
            return value

    # Third: substring match against labels (still deterministic, but strict).
    for value, label in filter_def.options:
        if want_norm in str(label or "").strip().lower() and str(label or "").strip():
            return value

    opts = ", ".join([f"{v}→{l}" for v, l in filter_def.options][:50])
    raise ValueError(
        f"Unknown value '{want}' for filter '{filter_def.label}'. Available options: {opts}"
    )


def _resolve_status_mode(filter_def: AdvancedFilter, *, mode: str) -> str:
    """Resolve a status option value from a coarse mode.

    mode:
    - "active": try to find Open/Active/Ongoing
    - "inactive": try to find Closed/Awarded/Expired/Cancelled
    """

    m = str(mode or "").strip().lower()
    if m not in {"active", "inactive"}:
        raise ValueError(f"Unknown status mode: {mode}")

    active_tokens = ["open", "active", "ongoing", "in progress", "current"]
    inactive_tokens = ["closed", "award", "awarded", "expired", "inactive", "cancel", "cancelled", "canceled"]
    tokens = active_tokens if m == "active" else inactive_tokens

    for value, label in filter_def.options:
        label_norm = str(label or "").strip().lower()
        if any(t in label_norm for t in tokens):
            return value

    opts = ", ".join([f"{v}→{l}" for v, l in filter_def.options][:50])
    raise ValueError(
        f"Could not resolve '{mode}' tender status from filter '{filter_def.label}'. Available options: {opts}"
    )


def _is_truthy(value: str) -> bool:
    v = str(value or "").strip().lower()
    return v in {"1", "true", "yes", "y", "on", "checked"}


def _parse_gebiz_datetime_to_date(value: str) -> str:
    text = _strip_tags(value)
    if not text:
        return ""
    for fmt in ["%d %b %Y %I:%M %p", "%d %b %Y %I:%M%p"]:
        try:
            return datetime.strptime(text, fmt).date().isoformat()
        except Exception:
            continue
    return ""


def _parse_gebiz_datetime_to_utc_iso(value: str) -> str:
    """Parse GeBIZ 'dd Mon YYYY hh:mm AM/PM' into an ISO string.

    We treat GeBIZ times as local portal times (SGT). If timezone is not present
    in the string, we keep it naive and return date-level ISO when parsing fails.
    """

    text = _strip_tags(value)
    if not text:
        return ""

    for fmt in ["%d %b %Y %I:%M %p", "%d %b %Y %I:%M%p"]:
        try:
            dt = datetime.strptime(text, fmt)
            # GeBIZ displays local SG time; store without tz offset to avoid false precision.
            return dt.replace(microsecond=0).isoformat()
        except Exception:
            continue
    return ""


def parse_bolisting_html(html: str) -> List[Dict[str, str]]:
    """Parse GeBIZ BOListing HTML into minimal row dicts.

    Returns a list of dicts with keys:
    - notice_id, notice_url, title, buyer, publication_date, classification, tender_status, closing_at
    """

    text = str(html or "")
    anchor_re = re.compile(
        r'href="(?P<href>/ptn/opportunity/directlink\.xhtml\?docCode=(?P<code>[^&\"]+)[^\"]*)"[^>]*>(?P<title>[^<]+)</a>',
        flags=re.IGNORECASE,
    )
    matches = list(anchor_re.finditer(text))
    rows: List[Dict[str, str]] = []
    for idx, match in enumerate(matches):
        start = match.start()
        end = matches[idx + 1].start() if idx + 1 < len(matches) else min(len(text), start + 20000)
        block = text[start:end]

        code = str(match.group("code") or "").strip()
        href = str(match.group("href") or "").strip()
        title = _strip_tags(match.group("title") or "")

        def extract(label: str) -> str:
            m = re.search(
                rf"<span>\s*{re.escape(label)}\s*</span>.*?formOutputText_VALUE-DIV[^>]*>(.*?)</div>",
                block,
                flags=re.IGNORECASE | re.DOTALL,
            )
            return _strip_tags(m.group(1)) if m else ""

        buyer = extract("Agency")
        published_raw = extract("Published")
        publication_date = _parse_gebiz_datetime_to_date(published_raw)
        classification = extract("Procurement Category")
        closing_raw = extract("Closing on")
        closing_at = _parse_gebiz_datetime_to_utc_iso(closing_raw)

        # Attempt to capture a status token near this listing.
        # Prefer tokens *before* the anchor (to avoid accidentally picking up the
        # next listing's status).
        tender_status = ""
        status_re = re.compile(r"\b(OPEN|CLOSED|AWARDED|CANCELLED|CANCELED|EXPIRED)\b", flags=re.IGNORECASE)

        prefix = _strip_tags(text[max(0, start - 1600) : start])
        prefix_hits = list(status_re.finditer(prefix))
        if prefix_hits:
            tender_status = str(prefix_hits[-1].group(1) or "").upper()
        else:
            # Fallback: check only the first part of the block.
            status_text = _strip_tags(block[:1200])
            status_match = status_re.search(status_text)
            if status_match:
                tender_status = str(status_match.group(1) or "").upper()

        # If the page doesn't explicitly label status per card, infer from closing time.
        # This supports the user's "active vs inactive" concept even when the UI is tab-based.
        if not tender_status and closing_at:
            try:
                # closing_at is naive ISO; compare at date-time granularity.
                closing_dt = datetime.fromisoformat(closing_at)
                now_dt = datetime.now()
                tender_status = "OPEN" if now_dt < closing_dt else "CLOSED"
            except Exception:
                pass

        if not code:
            continue
        rows.append(
            {
                "notice_id": code,
                "notice_url": f"https://www.gebiz.gov.sg{href}",
                "title": title,
                "buyer": buyer,
                "publication_date": publication_date,
                "classification": classification,
                "tender_status": tender_status,
                "closing_at": closing_at,
            }
        )
    return rows


def fetch_bolisting_requests(
    *,
    query_text: str,
    years: Sequence[int],
    tender_status: str = "",
    max_pages: int = 1,
    match_mode: str = "any",
    search_in: Sequence[str] = ("Title",),
    timeout_seconds: int = 30,
) -> "pd_types.DataFrame":
    """Fetch and parse BOListing (public opportunities listing) via requests.

    Notes:
    - BOListing is JSF-based; to support paging and built-in search controls, we
      submit the form via POST (with ViewState) rather than only using a simple GET.
    """

    # 'origin=menu' appears to render a richer first page in a pure-requests context.
    url = "https://www.gebiz.gov.sg/ptn/opportunity/BOListing.xhtml?origin=menu"
    session = requests.Session()
    session.headers.update(
        {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            "Referer": url,
            "Origin": "https://www.gebiz.gov.sg",
        }
    )

    max_pages_int = int(max_pages) if str(max_pages).isdigit() else 1
    if max_pages_int < 0:
        max_pages_int = 0

    # Normalize search-in options.
    allowed_search_in = {"title", "document no.", "agency", "procurement category"}
    wanted_search_in = [str(x or "").strip() for x in list(search_in or []) if str(x or "").strip()]
    if not wanted_search_in:
        wanted_search_in = ["Title"]
    wanted_search_in_norm = [x.lower() for x in wanted_search_in if x.lower() in allowed_search_in]
    if not wanted_search_in_norm:
        wanted_search_in_norm = ["title"]

    mm = str(match_mode or "any").strip().lower()
    if mm not in {"all", "any"}:
        mm = "any"

    q = str(query_text or "").strip()
    rows: List[Dict[str, str]] = []
    seen_notice_ids: set[str] = set()

    page_no = 0
    last_html = ""
    while True:
        if max_pages_int and page_no >= max_pages_int:
            break

        # Refresh form state each loop (ViewState changes per page).
        response = session.get(url, timeout=max(5, int(timeout_seconds))) if page_no == 0 else session.post(url, data=payload, timeout=max(5, int(timeout_seconds)))
        response.raise_for_status()
        last_html = str(response.text or "")

        page_rows = parse_bolisting_html(last_html)
        added = 0
        for r in page_rows:
            nid = str(r.get("notice_id", "") or "").strip()
            if nid and nid not in seen_notice_ids:
                seen_notice_ids.add(nid)
                rows.append(r)
                added += 1

        # Build payload for next request.
        forms = _parse_jsf_forms(last_html)
        form = _pick_form_by_action(forms, "bolisting.xhtml") or (forms[0] if forms else None)
        if not form:
            break

        payload = {}
        form_name = str(form.get("name") or form.get("id") or "").strip()
        if form_name:
            payload[form_name] = form_name
        for name, inp in dict(form.get("inputs_by_name", {})).items():
            if str(inp.get("type", "") or "").lower() == "hidden" and name:
                payload[name] = str(inp.get("value", ""))

        # JSF statefulness: include other scalar inputs too (some pager/search
        # widgets store state in text inputs rather than hidden inputs).
        for name, inp in dict(form.get("inputs_by_name", {})).items():
            if not name or name in payload:
                continue
            itype = str(inp.get("type", "") or "").lower()
            if itype in {"hidden", "submit", "button", "checkbox", "radio"}:
                continue
            payload[name] = str(inp.get("value", "") or "")

        view_state = _extract_view_state(form)
        if view_state:
            payload["javax.faces.ViewState"] = view_state

        # Apply built-in BOListing search widgets.
        if q:
            payload["contentForm:j_idt179_searchBar_INPUT-SEARCH"] = q
        payload["contentForm:j_id53"] = "Match All" if mm == "all" else "Match Any"

        # Search-in checkboxes.
        checkbox_map = {
            "title": "contentForm:j_id52_0",
            "document no.": "contentForm:j_id52_1",
            "agency": "contentForm:j_id52_2",
            "procurement category": "contentForm:j_id52_3",
        }
        for key_norm, field_name in checkbox_map.items():
            if key_norm in wanted_search_in_norm:
                payload[field_name] = str(form.get("inputs_by_name", {}).get(field_name, {}).get("value", "on"))

        # For the first request, click Go if we have a query. Otherwise, we rely on default listing.
        if page_no == 0 and q:
            go = _find_submit_input_by_value(form, "Go")
            if go and go.get("name"):
                payload[str(go.get("name"))] = str(go.get("value") or "Go")

        # Click Next for subsequent pages.
        if page_no >= 0:
            next_btn = _find_submit_input_by_value(form, "Next")
            if not next_btn or not next_btn.get("name"):
                break
            # If we couldn't extract or advance results, stop.
            if not page_rows or added == 0:
                break
            payload[str(next_btn.get("name"))] = str(next_btn.get("value") or "Next")

        page_no += 1

    tokens = [t.lower() for t in re.split(r"\s+", str(query_text or "").strip()) if t]
    if tokens:
        rows = [row for row in rows if any(t in str(row.get("title", "")).lower() for t in tokens)]

    status = str(tender_status or "").strip().upper()
    if status:
        rows = [row for row in rows if str(row.get("tender_status", "")).upper() == status]

    allowed_years = {int(y) for y in years if str(y).isdigit() or isinstance(y, int)}
    if allowed_years:
        filtered: List[Dict[str, str]] = []
        for row in rows:
            pub = str(row.get("publication_date", ""))
            year = int(pub[:4]) if len(pub) >= 4 and pub[:4].isdigit() else None
            if year is None or year in allowed_years:
                filtered.append(row)
        rows = filtered

    scraped_at_utc = _utc_now_iso()
    out_rows: List[Dict[str, str]] = []
    for row in rows:
        notice_id = str(row.get("notice_id", "")).strip()
        notice_url = str(row.get("notice_url", "")).strip()
        title = str(row.get("title", "")).strip()
        buyer = str(row.get("buyer", "")).strip()
        publication_date = str(row.get("publication_date", "")).strip()
        classification = str(row.get("classification", "")).strip()
        tender_status_row = str(row.get("tender_status", "")).strip().upper()
        out_rows.append(
            {
                "source": "SG_GEBIZ",
                "country": "Singapore",
                "country_code": "SG",
                "publication_date": publication_date,
                "title": title,
                "description": "",
                "buyer": buyer,
                "classification": classification,
                "tender_status": tender_status_row,
                "currency": "",
                "amount": "",
                "notice_id": notice_id,
                "notice_url": notice_url,
                "query_text": str(query_text or "").strip(),
                "scraped_at_utc": scraped_at_utc,
                "dedup_key": _stable_dedup_key("SG_GEBIZ", notice_id, notice_url),
            }
        )

    if not out_rows:
        return pd.DataFrame([]).reindex(columns=list(NORMALIZED_COLUMNS)).fillna("")
    return pd.DataFrame(out_rows).reindex(columns=list(NORMALIZED_COLUMNS)).fillna("")


def discover_advanced_search_filters_requests(
    *,
    query_text: str,
    output_target: str,
    region: str,
    website_id: str,
    timeout_seconds: int = 30,
) -> Tuple[str, int, str]:
    """Discover available Advanced Search filters and persist as an artifact."""

    base_dir = resolve_output_base_dir(
        output_target=output_target,
        region=region,
        website_id=website_id,
    )
    layout = ensure_spec_folder_layout(base_dir)
    web_dir = Path(layout["web"])
    artifact_path = web_dir / f"gebiz_advanced_filters_{_timestamp_token()}.json"

    url = "https://www.gebiz.gov.sg/ptn/opportunity/BOAdvancedSearch.xhtml?origin=advanced"
    error_message = ""
    filters: List[AdvancedFilter] = []
    try:
        response = requests.get(url, timeout=max(5, int(timeout_seconds)))
        response.raise_for_status()
        filters = list_advanced_search_filters(response.text)
    except Exception as exc:
        error_message = f"requests_error: {exc}"

    payload = {
        "ts_utc": _utc_now_iso(),
        "source": "SG_GEBIZ",
        "query_text": str(query_text or ""),
        "page_url": url,
        "filter_count": len(filters),
        "filters": [
            {
                "label": f.label,
                "control_id": f.control_id,
                "control_name": f.control_name,
                "control_type": f.control_type,
                "options": [{"value": v, "label": l} for v, l in f.options],
            }
            for f in filters
        ],
        "error": error_message,
    }
    artifact_path.parent.mkdir(parents=True, exist_ok=True)
    artifact_path.write_text(json.dumps(payload, ensure_ascii=True, indent=2), encoding="utf-8")
    return str(artifact_path), len(filters), error_message


def fetch_advanced_search_requests(
    *,
    query_text: str,
    years: Sequence[int],
    tender_status: str = "",
    advanced_filters: Sequence[str] = (),
    advanced_fields: Sequence[str] = (),
    timeout_seconds: int = 30,
) -> "pd_types.DataFrame":
    """Fetch first page of results using Advanced Search.

    This is best-effort: if GeBIZ changes to fully JS-driven results loading,
    consider using --discover-only to capture endpoints.
    """

    url = "https://www.gebiz.gov.sg/ptn/opportunity/BOAdvancedSearch.xhtml?origin=advanced"
    q = str(query_text or "").strip()

    def attempt(with_playwright: bool) -> str:
        session = requests.Session()
        session.headers.update(
            {
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
                "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
                "Referer": url,
                "Origin": "https://www.gebiz.gov.sg",
            }
        )

        if with_playwright:
            pw = _discover_playwright_session(url=url, timeout_seconds=timeout_seconds)
            if pw is not None:
                for c in pw.cookies:
                    try:
                        session.cookies.set(
                            name=str(c.get("name", "")),
                            value=str(c.get("value", "")),
                            domain=str(c.get("domain", "")) or None,
                            path=str(c.get("path", "/")) or "/",
                        )
                    except Exception:
                        continue

        response = session.get(url, timeout=max(5, int(timeout_seconds)))
        response.raise_for_status()

        forms = _parse_jsf_forms(response.text)
        form = _pick_main_search_form(forms)
        if not form:
            raise RuntimeError("Failed to locate GeBIZ advanced search form")

        filters = list_advanced_search_filters(response.text)
        by_label = _label_to_filter_map(filters)

        payload: Dict[str, object] = {}

        # JSF requires the form name as a parameter (often hidden input with same name).
        form_name = str(form.get("name") or form.get("id") or "").strip()
        if form_name:
            payload[form_name] = form_name

        # Include all hidden inputs so server state stays consistent.
        for name, inp in dict(form.get("inputs_by_name", {})).items():
            if str(inp.get("type", "")) == "hidden" and name:
                payload[name] = str(inp.get("value", ""))

        # Ensure ViewState
        view_state = _extract_view_state(form)
        if view_state:
            payload["javax.faces.ViewState"] = view_state

        # Apply: tender status if provided.
        # NOTE: BOAdvancedSearch does not always expose status as a form control.
        # If no status filter exists, we fall back to post-filtering on parsed results.
        status_post_filter = str(tender_status or "").strip()
        if status_post_filter and status_post_filter not in {"__AUTO_ACTIVE__", "__AUTO_INACTIVE__"}:
            candidates = ["tender status", "opportunity status", "status"]
            chosen: Optional[AdvancedFilter] = None
            for c in candidates:
                if c in by_label:
                    chosen = by_label[c]
                    break
            if chosen is None:
                for f in filters:
                    if f.control_type == "select" and "status" in f.label.lower():
                        chosen = f
                        break
            if chosen is not None and chosen.control_name and chosen.control_type == "select":
                payload[chosen.control_name] = _resolve_select_value(chosen, status_post_filter)

        # Apply: advanced filters by label text.
        # Format: "Label=Value" (repeatable)
        for item in list(advanced_filters or []):
            text = str(item or "").strip()
            if not text or "=" not in text:
                continue
            k, v = text.split("=", 1)
            key = k.strip().lower()
            if key not in by_label:
                raise ValueError(
                    f"Unknown advanced filter label '{k}'. Use --list-advanced-filters to see available labels."
                )
            f = by_label[key]
            if not f.control_name:
                continue
            if f.control_type == "select":
                payload[f.control_name] = _resolve_select_value(f, v)
            elif f.control_type == "checkbox":
                if _is_truthy(v):
                    payload[f.control_name] = "on"
            else:
                payload[f.control_name] = str(v)

        # Apply: advanced fields by raw form field name.
        # Format: "fieldName=value" (repeatable)
        for item in list(advanced_fields or []):
            text = str(item or "").strip()
            if not text or "=" not in text:
                continue
            k, v = text.split("=", 1)
            name = k.strip()
            if name:
                payload[name] = str(v)

        # Apply query text.
        if q:
            # GeBIZ advanced search uses dedicated title keyword fields. Prefer the
            # most inclusive default: "(All these words)".
            all_words = by_label.get("(all these words)")
            if all_words is not None and all_words.control_name:
                payload[all_words.control_name] = q
            else:
                # Prefer a labeled keyword field.
                keyword_labels = ["keywords", "keyword", "search", "title"]
                keyword_field_name = ""
                for f in filters:
                    if f.control_type in {"text", "input", ""} and any(t in f.label.lower() for t in keyword_labels):
                        if f.control_name:
                            keyword_field_name = f.control_name
                            break
                if not keyword_field_name:
                    # Fall back to first non-hidden input of type text
                    for inp in form.get("inputs_by_name", {}).values():
                        if str(inp.get("type", "")) in {"text", ""} and str(inp.get("name", "")):
                            keyword_field_name = str(inp.get("name", ""))
                            break
                if keyword_field_name:
                    payload[keyword_field_name] = q

        # Include remaining scalar filter fields (text-like inputs) so the request carries
        # the full set of simple advanced-search filters.
        for name, inp in dict(form.get("inputs_by_name", {})).items():
            if not name or name in payload:
                continue
            itype = str(inp.get("type", "") or "").lower()
            if itype in {"hidden", "submit", "button", "checkbox", "radio"}:
                continue
            payload[name] = str(inp.get("value", "") or "")

        # Include select controls with their default (first option) if not explicitly set.
        for sel in list(form.get("selects_by_name", {}).values()):
            sel_name = str(sel.get("name", "") or "").strip()
            if not sel_name or sel_name in payload:
                continue
            options = list(sel.get("options", []) or [])
            if options:
                payload[sel_name] = str(options[0].get("value", "") or "")

        btn = _find_search_button(form)
        if btn is None:
            raise RuntimeError("Failed to locate Advanced Search submit button")
        btn_name = str(btn.get("name") or "").strip()
        if btn_name:
            payload[btn_name] = str(btn.get("value") or btn_name)

        post_url = "https://www.gebiz.gov.sg" + str(form.get("action") or "/ptn/opportunity/BOAdvancedSearch.xhtml")
        post_response = session.post(post_url, data=payload, timeout=max(5, int(timeout_seconds)))
        post_response.raise_for_status()
        if "session expired" in str(post_response.text or "").lower():
            raise RuntimeError("session_expired")
        return str(post_response.text or "")

    try:
        html = attempt(with_playwright=False)
    except Exception as exc:
        # If GeBIZ returns "Session Expired" for requests-only POSTs, retry once
        # with a Playwright-acquired cookie jar.
        if "session_expired" in str(exc).lower():
            html = attempt(with_playwright=True)
        else:
            raise

    rows = parse_bolisting_html(html)

    tokens = [t.lower() for t in re.split(r"\s+", q) if t]
    if tokens:
        rows = [row for row in rows if any(t in str(row.get("title", "")).lower() for t in tokens)]

    allowed_years = {int(y) for y in years if str(y).isdigit() or isinstance(y, int)}
    if allowed_years:
        filtered: List[Dict[str, str]] = []
        for row in rows:
            pub = str(row.get("publication_date", ""))
            year = int(pub[:4]) if len(pub) >= 4 and pub[:4].isdigit() else None
            if year is None or year in allowed_years:
                filtered.append(row)
        rows = filtered

    # Apply post-filter status.
    status_post_filter = str(tender_status or "").strip()
    if status_post_filter:
        status_norm = str(status_post_filter).strip().upper()
        if status_norm == "__AUTO_ACTIVE__":
            rows = [r for r in rows if str(r.get("tender_status", "")).upper() in {"OPEN", "ACTIVE", "ONGOING"}]
        elif status_norm == "__AUTO_INACTIVE__":
            rows = [r for r in rows if str(r.get("tender_status", "")).upper() in {"CLOSED", "AWARDED", "EXPIRED", "CANCELLED", "CANCELED"}]
        else:
            rows = [r for r in rows if str(r.get("tender_status", "")).upper() == status_norm]

    scraped_at_utc = _utc_now_iso()
    out_rows: List[Dict[str, str]] = []
    for row in rows:
        notice_id = str(row.get("notice_id", "")).strip()
        notice_url = str(row.get("notice_url", "")).strip()
        title = str(row.get("title", "")).strip()
        buyer = str(row.get("buyer", "")).strip()
        publication_date = str(row.get("publication_date", "")).strip()
        classification = str(row.get("classification", "")).strip()
        tender_status_row = str(row.get("tender_status", "")).strip().upper()
        if not notice_id:
            continue
        out_rows.append(
            {
                "source": "SG_GEBIZ",
                "country": "Singapore",
                "country_code": "SG",
                "publication_date": publication_date,
                "title": title,
                "description": "",
                "buyer": buyer,
                "classification": classification,
                "tender_status": tender_status_row,
                "currency": "",
                "amount": "",
                "notice_id": notice_id,
                "notice_url": notice_url,
                "query_text": q,
                "scraped_at_utc": scraped_at_utc,
                "dedup_key": _stable_dedup_key("SG_GEBIZ", notice_id, notice_url),
            }
        )

    if not out_rows:
        return pd.DataFrame([]).reindex(columns=list(NORMALIZED_COLUMNS)).fillna("")
    return pd.DataFrame(out_rows).reindex(columns=list(NORMALIZED_COLUMNS)).fillna("")


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def _stable_dedup_key(*parts: str) -> str:
    payload = "|".join([str(part or "").strip() for part in parts])
    return hashlib.sha1(payload.encode("utf-8")).hexdigest()


def build_placeholder_normalized_df(*, query_text: str) -> "pd_types.DataFrame":
    scraped_at_utc = _utc_now_iso()
    notice_id = "GEBIZ_PLACEHOLDER"
    notice_url = ""
    title = "GeBIZ scaffold placeholder"
    description = "Not implemented: SG_GEBIZ fetch/normalize pipeline is scaffolded only."

    row = {
        "source": "SG_GEBIZ",
        "country": "Singapore",
        "country_code": "SG",
        "publication_date": "",
        "title": title,
        "description": description,
        "buyer": "",
        "classification": "",
        "tender_status": "",
        "currency": "",
        "amount": "",
        "notice_id": notice_id,
        "notice_url": notice_url,
        "query_text": str(query_text or "").strip(),
        "scraped_at_utc": scraped_at_utc,
        "dedup_key": _stable_dedup_key("SG_GEBIZ", notice_id, str(query_text or "").strip()),
    }

    return pd.DataFrame([row]).reindex(columns=list(NORMALIZED_COLUMNS)).fillna("")


def parse_args(argv: Optional[Sequence[str]] = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Scaffold scraper for Singapore GeBIZ (SG_GEBIZ)")
    parser.add_argument("--date-from", default=None, help="Start date (YYYY-MM-DD).")
    parser.add_argument("--date-to", default=None, help="End date (YYYY-MM-DD).")
    parser.add_argument("--query", default="", help="Optional keyword search.")
    parser.add_argument("--output-target", default="", help="Google Drive URL or local output folder.")
    parser.add_argument("--disable-deduplication", action="store_true", help="Disable default deduplication.")
    parser.add_argument(
        "--discover-only",
        action="store_true",
        help="Use Playwright to discover data endpoints and write web artifacts, then exit.",
    )

    parser.add_argument(
        "--project-name",
        default="MDT_2026",
        help="Project name token in outputs (PROJECT_NAME_YEAR).",
    )
    parser.add_argument("--website-id", default="SG_GEBIZ", help="Website ID (uppercase underscore).")
    parser.add_argument("--source-label", default="Singapore GeBIZ", help="Human readable source label.")
    parser.add_argument("--region", default="EMEA", choices=["EMEA", "LATAM"], help="Regional output routing.")

    # Advanced search options
    parser.add_argument(
        "--use-advanced-search",
        action="store_true",
        help="Use BOAdvancedSearch flow instead of BOListing.",
    )
    parser.add_argument(
        "--list-advanced-filters",
        action="store_true",
        help="Print available BOAdvancedSearch filters (labels/options) and exit.",
    )
    parser.add_argument(
        "--tender-status",
        default="",
        help="Set tender/opportunity status filter by option label or raw value (e.g. 'Open', 'Closed').",
    )
    parser.add_argument(
        "--max-pages",
        type=int,
        default=1,
        help="Max pages to fetch from BOListing (safety; set 0 for unlimited).",
    )
    parser.add_argument(
        "--match-mode",
        choices=["all", "any"],
        default="any",
        help="Keyword match mode for BOListing search bar (all/any).",
    )
    parser.add_argument(
        "--search-in",
        action="append",
        default=[],
        help="BOListing search scope (repeatable): Title | Document No. | Agency | Procurement Category.",
    )
    status_group = parser.add_mutually_exclusive_group()
    status_group.add_argument(
        "--active-only",
        action="store_true",
        help="Convenience: set tender status to an 'active/open' option (resolved from BOAdvancedSearch options).",
    )
    status_group.add_argument(
        "--inactive-only",
        action="store_true",
        help="Convenience: set tender status to an 'inactive/closed/awarded' option (resolved from BOAdvancedSearch options).",
    )
    parser.add_argument(
        "--advanced-filter",
        action="append",
        default=[],
        help="Advanced filter by label: 'Label=Value' (repeatable). Use --list-advanced-filters to discover labels.",
    )
    parser.add_argument(
        "--advanced-field",
        action="append",
        default=[],
        help="Advanced field by raw form name: 'fieldName=value' (repeatable).",
    )

    # Convenience aliases for common Advanced Search fields (by label).
    parser.add_argument("--title-all", default="", help="Advanced search: (All these words)")
    parser.add_argument("--title-any", default="", help="Advanced search: (Any of these words)")
    parser.add_argument("--title-none", default="", help="Advanced search: (None of these words)")
    parser.add_argument("--title-exact", default="", help="Advanced search: (Exact word or phrase)")
    parser.add_argument("--document-no", default="", help="Advanced search: Document No.")
    parser.add_argument("--reference-no", default="", help="Advanced search: Reference No.")
    parser.add_argument(
        "--opportunity-type",
        action="append",
        default=[],
        help="Advanced search: Opportunity type checkbox by label (repeatable, e.g. --opportunity-type 'Tender Lite').",
    )

    add_standard_colab_args(parser, default_country="SG")
    return parser.parse_args(list(argv) if argv is not None else None)


def _timestamp_token() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")


def discover_endpoints_playwright(
    *,
    query_text: str,
    output_target: str,
    region: str,
    website_id: str,
    timeout_seconds: int = 30,
) -> Tuple[str, int, str]:
    """Attempt to discover GeBIZ data endpoints via Playwright.

    Returns (artifact_path, record_count, error_message).
    - If Playwright is unavailable, returns ("", 0, "playwright_not_installed").
    - Always best-effort; does not raise.
    """

    try:
        playwright_sync = importlib.import_module("playwright.sync_api")
        sync_playwright = getattr(playwright_sync, "sync_playwright")
    except Exception:
        logger.warning(
            "Playwright not available. Install 'playwright' to enable --discover-only."
        )
        return "", 0, "playwright_not_installed"

    base_dir = resolve_output_base_dir(
        output_target=output_target,
        region=region,
        website_id=website_id,
    )
    layout = ensure_spec_folder_layout(base_dir)
    web_dir = Path(layout["web"])
    artifact_path = web_dir / f"gebiz_discovery_{_timestamp_token()}.jsonl"

    records: List[dict] = []
    error_message = ""

    def should_capture(response) -> bool:
        try:
            request = response.request
            if getattr(request, "resource_type", "") in {"xhr", "fetch"}:
                return True
            headers = getattr(response, "headers", {}) or {}
            content_type = str(headers.get("content-type", "") or "").lower()
            return ("application/json" in content_type) or ("text/" in content_type)
        except Exception:
            return False

    with sync_playwright() as p:
        try:
            browser = p.chromium.launch(headless=True)
            context = browser.new_context(
                user_agent=(
                    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                    "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
                )
            )
            page = context.new_page()

            def on_response(response):
                if len(records) >= 200:
                    return
                if not should_capture(response):
                    return
                try:
                    request = response.request
                    headers = getattr(response, "headers", {}) or {}
                    content_type = str(headers.get("content-type", "") or "")
                    body_preview = ""
                    if "json" in content_type.lower() or content_type.lower().startswith("text/"):
                        try:
                            body_preview = str(response.text() or "")[:500]
                        except Exception:
                            body_preview = ""
                    records.append(
                        {
                            "ts_utc": _utc_now_iso(),
                            "url": str(getattr(response, "url", "") or ""),
                            "method": str(getattr(request, "method", "") or ""),
                            "status": int(getattr(response, "status", 0) or 0),
                            "resource_type": str(getattr(request, "resource_type", "") or ""),
                            "content_type": content_type,
                            "body_preview": body_preview,
                        }
                    )
                except Exception:
                    return

            page.on("response", on_response)

            url = "https://www.gebiz.gov.sg/ptn/opportunity/BOAdvancedSearch.xhtml?origin=advanced"
            page.goto(url, wait_until="domcontentloaded", timeout=timeout_seconds * 1000)
            page.wait_for_timeout(5000)

            # Best-effort: try to type query text if an obvious input is present.
            q = str(query_text or "").strip()
            if q:
                try:
                    page.locator("input[type='text']").first.fill(q)
                    page.keyboard.press("Enter")
                    page.wait_for_timeout(5000)
                except Exception:
                    pass

            browser.close()
        except Exception as exc:
            error_message = f"playwright_error: {exc}"

    artifact_path.parent.mkdir(parents=True, exist_ok=True)
    with artifact_path.open("w", encoding="utf-8") as handle:
        header = {
            "ts_utc": _utc_now_iso(),
            "source": "SG_GEBIZ",
            "query_text": str(query_text or ""),
            "record_count": len(records),
            "error": error_message,
        }
        handle.write(json.dumps({"type": "summary", **header}, ensure_ascii=True) + "\n")
        for record in records:
            handle.write(json.dumps({"type": "response", **record}, ensure_ascii=True) + "\n")

    return str(artifact_path), len(records), error_message


def fetch_records_requests(*, endpoint_hint: str = "") -> "pd_types.DataFrame":
    """Requests-based fetch stub.

    Once a stable GeBIZ JSON endpoint is confirmed (from --discover-only artifacts), implement:
    - parameterized query + paging
    - retry/backoff on 429/5xx
    - mapping into NORMALIZED_COLUMNS
    """

    _ = endpoint_hint
    return pd.DataFrame([])


def run(args: argparse.Namespace) -> Dict[str, object]:
    date_from, date_to, normalized_years = resolve_date_range(
        date_from=args.date_from,
        date_to=args.date_to,
        years=args.years,
    )
    query_text = build_query_text(args.query, args.keywords)
    keywords = build_run_keywords(keywords=args.keywords, query_text=query_text)

    discover_summary: Dict[str, object] = {}
    if bool(getattr(args, "discover_only", False)):
        artifact_path, record_count, error = discover_endpoints_playwright(
            query_text=query_text,
            output_target=args.output_target,
            region=args.region,
            website_id=args.website_id,
        )
        discover_summary = {
            "artifact_path": artifact_path,
            "record_count": record_count,
            "error": error,
        }

        # Also persist the full advanced filter list (requests-based, no browser required).
        try:
            filters_path, filter_count, filter_err = discover_advanced_search_filters_requests(
                query_text=query_text,
                output_target=args.output_target,
                region=args.region,
                website_id=args.website_id,
            )
            discover_summary["advanced_filters_artifact_path"] = filters_path
            discover_summary["advanced_filter_count"] = filter_count
            discover_summary["advanced_filters_error"] = filter_err
        except Exception as exc:
            discover_summary["advanced_filters_error"] = f"filters_discovery_error: {exc}"

    normalized_df = pd.DataFrame()
    if not bool(getattr(args, "discover_only", False)):
        try:
            if bool(getattr(args, "list_advanced_filters", False)):
                # Print to stdout for operator convenience.
                url = "https://www.gebiz.gov.sg/ptn/opportunity/BOAdvancedSearch.xhtml?origin=advanced"
                html = requests.get(url, timeout=30).text
                filters = list_advanced_search_filters(html)
                print("BOAdvancedSearch filters:")
                for f in filters:
                    print(f"- {f.label} ({f.control_type}) name={f.control_name}")
                    if f.options:
                        for v, l in f.options[:50]:
                            print(f"    {v} -> {l}")
                return {
                    "date_from": date_from,
                    "date_to": date_to,
                    "query_text": query_text,
                    "keywords": keywords,
                    "normalized_rows": 0,
                    "discover": discover_summary,
                    "spec": {},
                    "mdt": {},
                }

            status_value = str(getattr(args, "tender_status", "") or "").strip()
            if not status_value and bool(getattr(args, "active_only", False)):
                status_value = "__AUTO_ACTIVE__"
            if not status_value and bool(getattr(args, "inactive_only", False)):
                status_value = "__AUTO_INACTIVE__"

            # Build convenience label filters.
            extra_label_filters: List[str] = []
            mapping = {
                "title_all": "(All these words)",
                "title_any": "(Any of these words)",
                "title_none": "(None of these words)",
                "title_exact": "(Exact word or phrase)",
                "document_no": "Document No.",
                "reference_no": "Reference No.",
            }
            for arg_key, label in mapping.items():
                val = str(getattr(args, arg_key, "") or "").strip()
                if val:
                    extra_label_filters.append(f"{label}={val}")

            for opt in list(getattr(args, "opportunity_type", []) or []):
                lbl = str(opt or "").strip()
                if lbl:
                    extra_label_filters.append(f"{lbl}=true")

            advanced_filters = list(getattr(args, "advanced_filter", []) or []) + extra_label_filters

            use_advanced = bool(getattr(args, "use_advanced_search", False)) or bool(status_value)
            use_advanced = use_advanced or bool(getattr(args, "advanced_field", []))
            use_advanced = use_advanced or bool(advanced_filters)
            if use_advanced:
                try:
                    normalized_df = fetch_advanced_search_requests(
                        query_text=query_text,
                        years=normalized_years,
                        tender_status=status_value,
                        advanced_filters=advanced_filters,
                        advanced_fields=list(getattr(args, "advanced_field", []) or []),
                    )
                except Exception as exc:
                    logger.warning("GeBIZ advanced search failed, falling back to BOListing: %s", exc)
                    normalized_df = pd.DataFrame()

                if normalized_df is None or len(getattr(normalized_df, "index", [])) == 0:
                    logger.warning("GeBIZ advanced search returned no rows; falling back to BOListing")
                    # BOListing supports only a subset of filters; status is applied post-parse.
                    status_simple = ""
                    if status_value == "__AUTO_ACTIVE__":
                        status_simple = "OPEN"
                    elif status_value == "__AUTO_INACTIVE__":
                        status_simple = "CLOSED"
                    else:
                        status_simple = status_value
                    normalized_df = fetch_bolisting_requests(
                        query_text=query_text,
                        years=normalized_years,
                        tender_status=status_simple,
                        max_pages=int(getattr(args, "max_pages", 1) or 1),
                        match_mode=str(getattr(args, "match_mode", "any") or "any"),
                        search_in=list(getattr(args, "search_in", []) or []),
                    )
            else:
                # BOListing supports only a subset of filters; status is applied post-parse.
                status_simple = ""
                if status_value == "__AUTO_ACTIVE__":
                    status_simple = "OPEN"
                elif status_value == "__AUTO_INACTIVE__":
                    status_simple = "CLOSED"
                else:
                    status_simple = status_value
                normalized_df = fetch_bolisting_requests(
                    query_text=query_text,
                    years=normalized_years,
                    tender_status=status_simple,
                    max_pages=int(getattr(args, "max_pages", 1) or 1),
                    match_mode=str(getattr(args, "match_mode", "any") or "any"),
                    search_in=list(getattr(args, "search_in", []) or []),
                )
        except Exception as exc:
            logger.warning("GeBIZ fetch failed: %s", exc)
            normalized_df = pd.DataFrame()
    if normalized_df is None or len(getattr(normalized_df, "index", [])) == 0:
        normalized_df = build_placeholder_normalized_df(query_text=query_text)
    normalized_df = normalized_df.copy()
    normalized_df["date_from"] = date_from
    normalized_df["date_to"] = date_to

    translated_df = translate_dataframe_to_english(
        normalized_df,
        TranslationConfig(
            enabled=bool(args.enable_google_translation),
            project_id=args.google_project_id,
            target_language=args.translation_target_language,
            columns=args.translate_columns,
        ),
        only_when_missing=not args.translate_all,
    )

    spec_summary = save_spec_outputs(
        translated_df,
        output_target=args.output_target,
        region=args.region,
        website_id=args.website_id,
        source_label=args.source_label,
        project_name=args.project_name,
        years=normalized_years,
        keywords=keywords,
        deduplicate_results=not args.disable_deduplication,
    )

    base_dir = resolve_output_base_dir(
        output_target=args.output_target,
        region=args.region,
        website_id=args.website_id,
    )
    layout = ensure_spec_folder_layout(base_dir)
    run_stem = build_run_output_stem(
        project_name=args.project_name,
        years=list(normalized_years),
        keywords=list(keywords),
    )

    mdt_df = to_mdt_schema(translated_df)
    mdt_prefix = Path(layout["tender_data_tool"]) / run_stem
    mdt_paths = save_mdt_outputs(mdt_df, mdt_prefix)

    return {
        "date_from": date_from,
        "date_to": date_to,
        "query_text": query_text,
        "keywords": keywords,
        "normalized_rows": len(translated_df),
        "discover": discover_summary,
        "spec": spec_summary,
        "mdt": mdt_paths,
    }


def main(argv: Optional[Sequence[str]] = None) -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
    args = parse_args(argv)
    result = run(args)

    spec = result.get("spec")
    if not isinstance(spec, dict):
        spec = {}
    mdt = result.get("mdt")
    if not isinstance(mdt, dict):
        mdt = {}
    logger.info(
        "Dedup before/after: %s -> %s (removed=%s)",
        spec.get("dedup_before"),
        spec.get("dedup_after"),
        spec.get("dedup_removed"),
    )
    logger.info("Run output: %s", spec.get("run_csv"))
    logger.info("Consolidated output: %s", spec.get("consolidated_csv"))
    logger.info("MDT CSV: %s", mdt.get("csv_path"))

    discover = result.get("discover")
    if isinstance(discover, dict) and discover.get("artifact_path"):
        logger.info("Discovery artifact: %s", discover.get("artifact_path"))


if __name__ == "__main__":
    main()

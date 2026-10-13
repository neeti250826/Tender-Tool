"""Muasamcong (mpi.gov.vn) smart search helpers.

This portal is a JS app (Vue + Liferay). Actual listings are fetched via:

  POST /o/egp-portal-contractor-selection-v2/services/smart/search?token=<...>

The token appears to be ephemeral and is easiest to obtain via Playwright
by capturing the first smart/search request the page emits.

Design goal:
- Use Playwright ONLY to obtain token/cookies (endpoint discovery)
- Use requests for paging + data retrieval
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Dict, Iterable, List, Optional, Sequence
from urllib.parse import urlencode, urlparse, parse_qs

import requests

logger = logging.getLogger(__name__)


MUASAMCONG_BASE_URL = "https://muasamcong.mpi.gov.vn"
CONTRACTOR_SELECTION_INDEX_URL = (
    "https://muasamcong.mpi.gov.vn/web/guest/contractor-selection?render=index"
)

SMART_SEARCH_PATH = "/o/egp-portal-contractor-selection-v2/services/smart/search"


def _iso_z_now_ms() -> str:
    # Match browser-like timestamps such as: 2026-03-16T00:21:02.329Z
    return (
        datetime.now(timezone.utc)
        .isoformat(timespec="milliseconds")
        .replace("+00:00", "Z")
    )


def _iso_z_day_start(date_yyyy_mm_dd: str) -> str:
    return f"{date_yyyy_mm_dd}T00:00:00.000Z"


def _iso_z_day_end(date_yyyy_mm_dd: str) -> str:
    return f"{date_yyyy_mm_dd}T23:59:59.999Z"


@dataclass(frozen=True)
class SmartSearchAuth:
    token: str
    cookies: List[Dict[str, Any]]


def discover_smart_search_auth_playwright(
    *,
    url: str = CONTRACTOR_SELECTION_INDEX_URL,
    timeout_seconds: int = 60,
    nav_retries: int = 3,
) -> SmartSearchAuth:
    """Capture the smart/search token and cookies via Playwright."""

    try:
        playwright_sync = __import__("playwright.sync_api", fromlist=["sync_playwright"])
        sync_playwright = getattr(playwright_sync, "sync_playwright")
    except Exception as exc:  # pragma: no cover
        raise RuntimeError("playwright_not_installed") from exc

    captured = {"url": ""}

    with sync_playwright() as p:
        # Some endpoints are sensitive to automation detection.
        browser = p.chromium.launch(
            headless=True,
            args=[
                "--disable-blink-features=AutomationControlled",
            ],
        )
        context = browser.new_context(
            user_agent=(
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                "(KHTML, like Gecko) Chrome/145.0.0.0 Safari/537.36"
            ),
            locale="vi-VN",
        )
        page = context.new_page()

        # Best-effort stealth (do not break if blocked by CSP, etc.).
        try:
            page.add_init_script(
                "Object.defineProperty(navigator, 'webdriver', {get: () => undefined});"
            )
        except Exception:
            pass

        def on_request(req):
            try:
                u = str(req.url() or "")
            except Exception:
                return
            if SMART_SEARCH_PATH in u and "token=" in u and not captured["url"]:
                captured["url"] = u

        page.on("request", on_request)

        last_nav_error: Optional[Exception] = None
        for attempt in range(max(1, int(nav_retries))):
            try:
                page.goto(url, wait_until="domcontentloaded", timeout=timeout_seconds * 1000)
                last_nav_error = None
                break
            except Exception as exc:
                last_nav_error = exc
                page.wait_for_timeout(1500)

        if last_nav_error is not None:
            raise RuntimeError(f"playwright_goto_failed: {last_nav_error}")

        # Give the app time to bootstrap.
        page.wait_for_timeout(8000)

        # Try to trigger smart/search if it doesn't fire automatically.
        if not captured["url"]:
            # 1) click the main search button
            try:
                page.get_by_role("button", name="Tìm kiếm").first.click(timeout=5000)
            except Exception:
                pass
        if not captured["url"]:
            # 2) click the status tabs (these actions are known to emit smart/search)
            for label in ("Chưa đóng thầu", "Đã đóng thầu"):
                try:
                    page.get_by_text(label, exact=False).first.click(timeout=5000)
                    page.wait_for_timeout(1500)
                except Exception:
                    continue

        deadline = datetime.now(timezone.utc).timestamp() + timeout_seconds
        while not captured["url"] and datetime.now(timezone.utc).timestamp() < deadline:
            page.wait_for_timeout(250)

        cookies = context.cookies()
        browser.close()

    if not captured["url"]:
        raise RuntimeError("smart_search_token_not_captured")

    parsed = urlparse(captured["url"])
    qs = parse_qs(parsed.query)
    token = (qs.get("token") or [""])[0]
    if not token:
        raise RuntimeError("smart_search_token_missing")

    return SmartSearchAuth(token=token, cookies=list(cookies or []))


def apply_playwright_cookies_to_session(
    session: requests.Session, cookies: Sequence[Dict[str, Any]]
) -> None:
    for c in list(cookies or []):
        try:
            session.cookies.set(
                name=str(c.get("name", "")),
                value=str(c.get("value", "")),
                domain=str(c.get("domain", "")) or urlparse(MUASAMCONG_BASE_URL).hostname,
                path=str(c.get("path", "/")) or "/",
            )
        except Exception:
            continue


def build_smart_search_payload(
    *,
    keyword: str,
    page_number: int,
    page_size: int,
    record_types: Sequence[str],
    include_case_khkq: bool,
    public_date_from: Optional[str],
    public_date_to: Optional[str],
    tender_status: str,
) -> List[Dict[str, Any]]:
    filters: List[Dict[str, Any]] = []

    if record_types:
        filters.append(
            {"fieldName": "type", "searchType": "in", "fieldValues": list(record_types)}
        )

    if not include_case_khkq:
        filters.append(
            {
                "fieldName": "caseKHKQ",
                "searchType": "not_in",
                "fieldValues": ["1"],
            }
        )

    if public_date_from or public_date_to:
        filters.append(
            {
                "fieldName": "publicDate",
                "searchType": "range",
                "from": _iso_z_day_start(public_date_from) if public_date_from else None,
                "to": _iso_z_day_end(public_date_to) if public_date_to else None,
            }
        )

    now_z = _iso_z_now_ms()
    if tender_status == "open":
        filters.append(
            {"fieldName": "bidCloseDate", "searchType": "range", "from": now_z, "to": None}
        )
    elif tender_status == "closed":
        filters.append(
            {"fieldName": "bidCloseDate", "searchType": "range", "from": None, "to": now_z}
        )

    query_obj: Dict[str, Any] = {
        "index": "es-contractor-selection",
        "keyWord": str(keyword or ""),
        "matchType": "all-1",
        "matchFields": ["notifyNo", "bidName"],
        "filters": filters,
    }

    return [
        {"pageSize": int(page_size), "pageNumber": int(page_number), "query": [query_obj]}
    ]


def smart_search_page(
    *,
    session: requests.Session,
    token: str,
    payload: List[Dict[str, Any]],
    timeout_seconds: int = 45,
) -> Dict[str, Any]:
    url = f"{MUASAMCONG_BASE_URL}{SMART_SEARCH_PATH}?{urlencode({'token': token})}"
    headers = {
        "accept": "application/json, text/plain, */*",
        "content-type": "application/json",
        "referer": CONTRACTOR_SELECTION_INDEX_URL,
    }
    resp = session.post(url, headers=headers, data=json.dumps(payload), timeout=timeout_seconds)
    resp.raise_for_status()
    return resp.json()


def iter_smart_search_records(
    *,
    token: str,
    cookies: Sequence[Dict[str, Any]] = (),
    keyword: str,
    page_size: int,
    max_pages: Optional[int],
    record_types: Sequence[str],
    include_case_khkq: bool,
    public_date_from: Optional[str],
    public_date_to: Optional[str],
    tender_status: str,
    timeout_seconds: int = 45,
) -> Iterable[Dict[str, Any]]:
    session = requests.Session()
    apply_playwright_cookies_to_session(session, cookies)
    try:
        session.get(CONTRACTOR_SELECTION_INDEX_URL, timeout=timeout_seconds)
    except Exception:
        pass

    page_number = 0
    pages_seen = 0
    while True:
        if max_pages is not None and pages_seen >= int(max_pages):
            break

        payload = build_smart_search_payload(
            keyword=keyword,
            page_number=page_number,
            page_size=page_size,
            record_types=record_types,
            include_case_khkq=include_case_khkq,
            public_date_from=public_date_from,
            public_date_to=public_date_to,
            tender_status=tender_status,
        )
        data = smart_search_page(
            session=session, token=token, payload=payload, timeout_seconds=timeout_seconds
        )

        content = (data.get("page") or {}).get("content") if isinstance(data, dict) else None
        if not isinstance(content, list) or not content:
            break

        for item in content:
            if isinstance(item, dict):
                yield item

        page_number += 1
        pages_seen += 1


def build_detail_v2_url(item: Dict[str, Any]) -> str:
    portlet_render_param = (
        "_egpportalcontractorselectionv2_WAR_egpportalcontractorselectionv2_render"
    )
    base = "https://muasamcong.mpi.gov.vn/web/guest/contractor-selection"

    step_code = str(item.get("stepCode") or "")
    step = ""
    for candidate in ("tbmt", "khlcnt", "kqst", "kqlcnt", "ycbg"):
        if candidate in step_code:
            step = candidate
            break

    params: Dict[str, Any] = {
        "p_p_id": "egpportalcontractorselectionv2_WAR_egpportalcontractorselectionv2",
        "p_p_lifecycle": "0",
        "p_p_state": "normal",
        "p_p_mode": "view",
        portlet_render_param: "detail-v2",
        "type": item.get("type"),
        "stepCode": item.get("stepCode"),
        "id": item.get("id"),
        "notifyId": item.get("notifyId"),
        "inputResultId": item.get("inputResultId") or "undefined",
        "bidOpenId": item.get("bidOpenId") or "undefined",
        "techReqId": item.get("techReqId") or "undefined",
        "bidPreNotifyResultId": item.get("bidPreNotifyResultId") or "undefined",
        "bidPreOpenId": item.get("bidPreOpenId") or "undefined",
        "processApply": item.get("processApply"),
        "bidMode": item.get("bidMode"),
        "notifyNo": item.get("notifyNo"),
        "planNo": item.get("planNo"),
        "pno": item.get("pno") or "undefined",
        "step": step or None,
        "isInternet": item.get("isInternet"),
        "caseKHKQ": item.get("caseKHKQ") or "undefined",
        "bidForm": item.get("bidForm"),
    }

    cleaned = {k: v for k, v in params.items() if v is not None}
    return f"{base}?{urlencode(cleaned)}"

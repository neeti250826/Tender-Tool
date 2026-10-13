"""Shared helpers for scaffold portal scrapers.

These helpers support:
- listing advanced-search filters from an HTML form
- building a best-effort POST payload for an advanced-search submission

They intentionally avoid external dependencies (BeautifulSoup, lxml).
"""

from __future__ import annotations

import json
import re
from dataclasses import asdict
from typing import Dict, Iterable, List, Optional, Sequence, Tuple

import requests

from form_filter_discovery import FormControl, FormOption, extract_controls, parse_forms, pick_main_form


def fetch_html(url: str, *, timeout_seconds: int = 30, headers: Optional[dict] = None) -> str:
    hdrs = {"User-Agent": "Mozilla/5.0"}
    if headers:
        hdrs.update(headers)
    resp = requests.get(url, timeout=max(5, int(timeout_seconds)), headers=hdrs)
    resp.raise_for_status()
    return str(resp.text or "")


def discover_controls(
    *,
    url: str,
    action_contains: Sequence[str] = (),
    timeout_seconds: int = 30,
) -> Tuple[Optional[dict], List[FormControl]]:
    html = fetch_html(url, timeout_seconds=timeout_seconds)
    forms = parse_forms(html)
    form = pick_main_form(forms, action_contains=action_contains)
    if not form:
        return None, []
    return form, extract_controls(form)


def _resolve_select_value(control: FormControl, desired: str) -> str:
    want = str(desired or "").strip()
    if not want:
        return ""
    # exact value
    for opt in control.options:
        if want == opt.value:
            return opt.value
    # label case-insensitive
    want_norm = want.lower()
    for opt in control.options:
        if want_norm == str(opt.label or "").strip().lower():
            return opt.value
    # substring label match (strict-ish)
    for opt in control.options:
        if want_norm in str(opt.label or "").strip().lower() and str(opt.label or "").strip():
            return opt.value
    opts = ", ".join([f"{o.value}→{o.label}" for o in control.options][:50])
    raise ValueError(f"Unknown value '{want}' for '{control.label}'. Available: {opts}")


def _is_truthy(value: str) -> bool:
    v = str(value or "").strip().lower()
    return v in {"1", "true", "yes", "y", "on", "checked"}


def build_advanced_payload(
    *,
    form: dict,
    controls: Sequence[FormControl],
    query_text: str,
    advanced_filters: Sequence[str],
    advanced_fields: Sequence[str],
    include_defaults: bool = True,
) -> Dict[str, object]:
    """Build best-effort POST payload based on controls + requested filters.

    advanced_filters: list of "Label=Value" entries
    advanced_fields: list of "rawName=value" entries
    """

    payload: Dict[str, object] = {}

    form_name = str(form.get("name") or form.get("id") or "").strip()
    if form_name:
        payload[form_name] = form_name

    # hidden inputs
    for name, inp in dict(form.get("inputs_by_name", {})).items():
        if str(inp.get("type", "")) == "hidden" and name:
            payload[name] = str(inp.get("value", ""))

    # label map
    by_label = {c.label.strip().lower(): c for c in list(controls or []) if c.label}

    # apply label-based filters
    for item in list(advanced_filters or []):
        text = str(item or "").strip()
        if not text or "=" not in text:
            continue
        k, v = text.split("=", 1)
        key = k.strip().lower()
        if key not in by_label:
            raise ValueError(f"Unknown filter label '{k}'.")
        c = by_label[key]
        if not c.name:
            continue
        if c.control_type == "select":
            payload[c.name] = _resolve_select_value(c, v)
        elif c.control_type == "checkbox":
            if _is_truthy(v):
                payload[c.name] = "on"
        else:
            payload[c.name] = str(v)

    # apply raw fields
    for item in list(advanced_fields or []):
        text = str(item or "").strip()
        if not text or "=" not in text:
            continue
        k, v = text.split("=", 1)
        name = k.strip()
        if name:
            payload[name] = str(v)

    if include_defaults:
        # include scalar defaults for completeness
        for name, inp in dict(form.get("inputs_by_name", {})).items():
            if not name or name in payload:
                continue
            itype = str(inp.get("type", "") or "").lower()
            if itype in {"hidden", "submit", "button", "checkbox", "radio"}:
                continue
            payload[name] = str(inp.get("value", "") or "")

        for sel in list(form.get("selects_by_name", {}).values()):
            sel_name = str(sel.get("name", "") or "").strip()
            if not sel_name or sel_name in payload:
                continue
            options = list(sel.get("options", []) or [])
            if options:
                payload[sel_name] = str(options[0].get("value", "") or "")

    # best-effort: set query into the first text-like input if present
    q = str(query_text or "").strip()
    if q:
        for name, inp in dict(form.get("inputs_by_name", {})).items():
            itype = str(inp.get("type", "") or "").lower()
            if itype in {"text", ""} and name and name not in payload:
                payload[name] = q
                break

    return payload


def payload_to_json(payload: Dict[str, object]) -> str:
    return json.dumps(payload, ensure_ascii=True, indent=2, sort_keys=True)

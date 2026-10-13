from __future__ import annotations

import json
import re
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Dict, List

import requests
from requests import RequestException

from harness.shared.normalize import normalize_text, utc_now_iso
from harness.shared.schema import OutputRow
from harness.shared.text_extract import first_match, strip_html_tags
from harness.sources.base import SmokeProbeResult
from harness.sources.registry import SOURCES

CONFIG = SOURCES["poland_ezamowienia"]
EVIDENCE_PATH = Path("evidence") / "poland_contract_notice_sample.json"
LIVE_API_URL = "https://ezamowienia.gov.pl/mo-board/api/v1/notice"
LIVE_NOTICE_TYPES = ("ContractNotice", "TenderResultNotice", "ContractPerformingNotice")
LIVE_AWARDED_NOTICE_TYPES = ("TenderResultNotice", "ContractPerformingNotice")
MEDICAL_CPV_PREFIXES = ("331", "336", "851")
MEDICAL_PATTERNS = (
    r"\bszpital",
    r"\bmedycz",
    r"\bzdrow",
    r"\bklinicz",
    r"\bklinika",
    r"\bokulist",
    r"\bpsychiatr",
    r"\bapte",
    r"\busg\b",
    r"\blaborator",
    r"\bdiagnost",
    r"\brehabilit",
    r"\bambulatoryj",
    r"\bpiel",
    r"\bratownict",
    r"\bkrwiodaw",
    r"\bkrwiolecz",
    r"\bodczynnik",
    r"\btransportu sanitarnego",
    r"\buslug medyczn",
    r"\bopieki zdrowot",
)
MIN_SPLIT_DAYS = 1
ORIGINAL_NOTICE_LOOKBACK_DAYS = 365


def _load_sample_notice() -> Dict[str, object]:
    payload = json.loads(EVIDENCE_PATH.read_text(encoding="utf-8"))
    return payload[0]


def _build_notice_url(object_id: str) -> str:
    return f"https://ezamowienia.gov.pl/mo-client-board/bzp/notice-details/id/{object_id}"


def _extract_description(html_body: str) -> str:
    for pattern in (
        r"4\.2\.2\.\).*?</h3>\s*<p class=\"mb-0\">(.*?)</p>",
        r"4\.5\.1\.\).*?</h3>\s*<p class=\"mb-0\">(.*?)</p>",
        r"3\.8\.\).*?</h3>\s*<p class=\"mb-0\">(.*?)</p>",
    ):
        section = first_match(pattern, html_body, flags=re.S)
        if section:
            return strip_html_tags(section)
    return normalize_text(strip_html_tags(html_body)[:500])


def _extract_html_value(html_body: str, pattern: str) -> str:
    return normalize_text(strip_html_tags(first_match(pattern, html_body, flags=re.S)))


def _full_notice_text(html_body: str) -> str:
    return normalize_text(strip_html_tags(html_body))


def _extract_html_money(html_body: str, section_prefix: str) -> tuple[str, str]:
    pattern = rf"{re.escape(section_prefix)}.*?<span class=\"normal\">\s*([0-9\s,\.]+)\s*([A-Z]{{3}})\s*</span>"
    match = re.search(pattern, html_body, re.S)
    if not match:
        return "", ""
    return normalize_text(match.group(2)), normalize_text(match.group(1)).replace(" ", "")


def _extract_contract_period(html_body: str, notice_type: str) -> str:
    if notice_type != "ContractPerformingNotice":
        return ""
    contract_date = _extract_html_value(
        html_body,
        r"<h3 class=\"mb-0\">4\.1\.\)\s*Data zawarcia umowy:\s*<span class=\"normal\">(.*?)</span></h3>",
    )
    completion_date = _extract_html_value(
        html_body,
        r"<h3 class=\"mb-0\">5\.2\.\)\s*Termin wykonania umowy:\s*<span class=\"normal\">(.*?)</span></h3>",
    )
    if contract_date and completion_date:
        return f"{contract_date} to {completion_date}"
    if completion_date:
        return completion_date
    return _extract_html_value(html_body, r"4\.2\.\).*?Okres realizacji zam[oó]wienia:\s*</h3>\s*(.*?)<!--")


def _extract_closing_date_from_html(html_body: str) -> str:
    for pattern in (
        r"8\.1\.\)\s*Termin sk[łl]adania ofert:\s*<span class=\"normal\">(.*?)</span>",
        r"Termin sk[łl]adania ofert.*?<span class=\"normal\">(.*?)</span>",
    ):
        value = _extract_html_value(html_body, pattern)
        if value:
            return value
    return ""


def _extract_quantity_fields(description: str) -> tuple[str, str]:
    match = re.search(
        r"(\d[\d\s.,]*)\s*(sztuk(?:a|i)?|szt\.|szt|godzin(?:y)?|godz\.|opakowan|opakowanie|litrow|ml|kg|g|m2|m3|mb)\b",
        description,
        re.I,
    )
    if not match:
        return "", ""
    return normalize_text(match.group(1)).replace(" ", ""), normalize_text(match.group(2))


def _extract_table_style_item_fields(description: str) -> tuple[str, str, str, str]:
    text = normalize_text(description)
    if not text:
        return "", "", "", ""

    row_match = re.search(
        r"(?:Lp\.|L\.p\.|LP\.)\s+.*?(?:J\.m\.|Jednostka miary).*?(?:Ilo[ść]?[ć]?|Zamawiana ilość|Wymagana.*?ilość).*?"
        r"(?:\d+\.\s+){0,4}(?P<item_no>\d+)[.)]\s*(?P<row_body>.*?)(?=\s+\d+[.)]\s|\s+Szczeg|\s+Szcz[a-ząćęłńóśżź]|\s*$)",
        text,
        re.I,
    )
    if row_match:
        item_no = normalize_text(row_match.group("item_no"))
        row_body = normalize_text(row_match.group("row_body"))
        package_unit_matches = list(
            re.finditer(
                r"(sztuk(?:a|i)?|szt\.|szt|opk\.|opk|op\.|op|opakowan|opakowanie|zestaw|zestawy|kpl\.|kpl|kompl\.|kompl|para|par|amp\.|amp|fiol\.|fiol|tabl\.|tabl|kaps\.|kaps)\b",
                row_body,
                re.I,
            )
        )
        if package_unit_matches:
            unit_match = package_unit_matches[0]
            item_desc = normalize_text(row_body[: unit_match.start()]).strip(" .,:;")
            item_uom = normalize_text(unit_match.group(1))
            remainder = normalize_text(row_body[unit_match.end() :]).strip(" .,:;")
            quantity_tokens = re.findall(r"\d[\d.,]*", remainder)
            item_quantity = ""
            if quantity_tokens:
                if remainder.lower().startswith(("a ", "x ", "a", "x")) and len(quantity_tokens) > 1:
                    item_quantity = quantity_tokens[-1]
                else:
                    item_quantity = quantity_tokens[0]
                item_quantity = normalize_text(item_quantity).replace(" ", "")
            if item_desc and item_uom and item_quantity:
                return item_no or "1", item_desc, item_uom, item_quantity

        if not package_unit_matches:
            match = re.search(
                r"(?P<item_desc>.*?)\s+"
                r"(?P<item_uom>ml|l|kg|g|m2|m3|mb)\s*[,:\.]?\s*(?P<item_quantity>\d[\d\s.,]*)\b",
                row_body,
                re.I,
            )
            if match:
                item_desc = normalize_text(match.group("item_desc")).strip(" .,:;")
                item_uom = normalize_text(match.group("item_uom"))
                item_quantity = normalize_text(match.group("item_quantity")).replace(" ", "")
                return item_no or "1", item_desc, item_uom, item_quantity

        match = re.search(
            r"(?P<item_desc>.*?)\s+"
            r"(?P<item_uom>ml|l|kg|g|m2|m3|mb)\s*[,:\.]?\s*(?P<item_quantity>\d[\d\s.,]*)\b",
            row_body,
            re.I,
        )
        if match and not package_unit_matches:
            item_desc = normalize_text(match.group("item_desc")).strip(" .,:;")
            item_uom = normalize_text(match.group("item_uom"))
            item_quantity = normalize_text(match.group("item_quantity")).replace(" ", "")
            return item_no or "1", item_desc, item_uom, item_quantity

    match = re.search(
        r"J\.m\.\s*:\s*(?P<item_uom>sztuk(?:a|i)?|szt\.|szt|op\.|op|opakowan|opakowanie|kpl\.|kpl|kompl\.|kompl|para|par|amp\.|amp|fiol\.|fiol|ml|l|kg|g|m2|m3|mb)\s*,?\s*Ilo[ść]?[ć]?\s*:\s*(?P<item_quantity>\d[\d\s.,]*)",
        text,
        re.I,
    )
    if match:
        return "1", "", normalize_text(match.group("item_uom")), normalize_text(match.group("item_quantity")).replace(" ", "")

    return "", "", "", ""


def _extract_pharma_list_item_fields(description: str) -> tuple[str, str, str, str]:
    text = normalize_text(description)
    if not text:
        return "", "", "", ""

    header_patterns = (
        r"(?:L\.p\.|LP\.|Lp\.)\s+.*?(?:Jednostka miary|Zamawiana ilość|Wymagana.*?ilość asortymentu)\s*(?P<row_no>1)?[.)]?\s*(?P<row_body>.*?)(?=\s+\d+[.)]\s|\s*$)",
        r"(?:L\.p\.|LP\.|Lp\.)\s+.*?ILOŚĆ OPAK\.\s*(?P<row_no>1)?[.)]?\s*(?P<row_body>.*?)(?=\s+\d+[.)]\s|\s*$)",
        r"Przedmiotem zamówienia jest dostawa produktów leczniczych:\s*(?P<row_no>1)?[.)]?\s*(?P<row_body>.*?)(?=\s+\d+[.)]\s|\s*$)",
    )
    row_body = ""
    row_no = "1"
    for pattern in header_patterns:
        match = re.search(pattern, text, re.I)
        if match:
            row_no = normalize_text(match.groupdict().get("row_no")) or "1"
            row_body = normalize_text(match.group("row_body"))
            break
    if not row_body:
        return "", "", "", ""

    package_quantity_match = re.search(r"(?:ilość opakowań|ilosc opakowan)\s*(?P<qty>\d[\d\s.,]*)$", row_body, re.I)
    if package_quantity_match:
        quantity = normalize_text(package_quantity_match.group("qty")).replace(" ", "")
        item_desc = normalize_text(row_body[: package_quantity_match.start()]).strip(" -–.;,")
        return row_no, item_desc, "opak.", quantity

    end_pack_match = re.search(
        r"(?P<item_desc>.*?)\s+(?:(?P<pack_size>\d[\d\s.,]*)\s+)?(?P<item_uom>opk\.|opk|opak\w*|op\.|op|fiol\.|fiol|amp\.|amp|tabl\.|tabl|kaps\.|kaps|sasz|wstrzykiwaczy|ampułkostrzykawka)\s*[x.]?\s*(?P<qty>\d[\d\s.,]*)$",
        row_body,
        re.I,
    )
    if end_pack_match:
        item_desc = normalize_text(end_pack_match.group("item_desc")).strip(" -–.;,")
        item_uom = normalize_text(end_pack_match.group("item_uom"))
        quantity = normalize_text(end_pack_match.group("qty")).replace(" ", "")
        return row_no, item_desc, item_uom, quantity

    if re.search(r"ILOŚĆ OPAK\.|ilosc opak", text, re.I):
        qty_tokens = re.findall(r"\d[\d\s.,]*", row_body)
        if qty_tokens:
            quantity = normalize_text(qty_tokens[-1]).replace(" ", "")
            item_desc = normalize_text(row_body[: row_body.rfind(qty_tokens[-1])]).strip(" -–.;,")
            return row_no, item_desc, "opak.", quantity

    return "", "", "", ""


def _extract_first_pharma_row_item_fields(description: str) -> tuple[str, str, str, str]:
    text = normalize_text(description)
    if not text:
        return "", "", "", ""

    first_row_patterns = (
        r"(?:L\.p\.|LP\.|Lp\.)\s+.*?(?:Jednostka miary|Zamawiana ilo[Å›Ä‡]|Wymagana.*?ilo[Å›Ä‡] asortymentu|ILO[ÅšÄ†] OPAK\.)\s*(?:1[.)]?\s*)?(?P<row_body>.*?)(?=(?:[;,.]\s*2[.)]\s)|(?:\s+2[.)]\s)|\s*$)",
        r"Przedmiotem zam[oÃ³]wienia jest dostawa produkt[oÃ³]w leczniczych:\s*(?:1[.)]?\s*)?(?P<row_body>.*?)(?=(?:[;,.]\s*2[.)]\s)|(?:\s+2[.)]\s)|\s*$)",
        r"(?:^|:\s*)1[.)]?\s*(?P<row_body>.*?)(?=(?:[;,.]\s*2[.)]\s)|(?:\s+2[.)]\s)|\s*$)",
    )
    row_body = ""
    for pattern in first_row_patterns:
        match = re.search(pattern, text, re.I)
        if match:
            row_body = normalize_text(match.group("row_body"))
            row_body = re.sub(r"^(?:Zamawiana ilo[Å›Ä‡]\s*)?1\s*", "", row_body, flags=re.I).strip(" -â€“.;,")
            break
    if not row_body:
        package_quantity_match = re.search(r"(?:ilo[Å›Ä‡] opakowa[Å„]|ilosc opakowan)\s*(?P<qty>\d[\d\s.,]*)", text, re.I)
        if package_quantity_match:
            item_desc = normalize_text(text[: package_quantity_match.start()]).strip(" -â€“.;,")
            quantity = normalize_text(package_quantity_match.group("qty")).replace(" ", "")
            return "1", item_desc, "opak.", quantity
        return "", "", "", ""

    package_quantity_match = re.search(r"(?:ilo[Å›Ä‡] opakowa[Å„]|ilosc opakowan)\s*(?P<qty>\d[\d\s.,]*)$", row_body, re.I)
    if package_quantity_match:
        quantity = normalize_text(package_quantity_match.group("qty")).replace(" ", "")
        item_desc = normalize_text(row_body[: package_quantity_match.start()]).strip(" -â€“.;,")
        return "1", item_desc, "opak.", quantity

    trailing_package_match = re.search(
        r"(?P<item_desc>.*?)\s+(?:(?P<pack_size>\d[\d\s.,]*)\s+)?(?P<item_uom>opk\.|opk|opak\w*|op\.|op|fiol\.|fiol|amp\.|amp|tabl\.|tabl|kaps\.|kaps|sasz|wstrzykiwaczy|ampuÅ‚kostrzykawka)\s*(?:[x.]?\s*|[-â€“]\s*)(?P<qty>\d[\d\s.,]*)$",
        row_body,
        re.I,
    )
    if trailing_package_match:
        item_desc = normalize_text(trailing_package_match.group("item_desc")).strip(" -â€“.;,")
        item_uom = normalize_text(trailing_package_match.group("item_uom"))
        quantity = normalize_text(trailing_package_match.group("qty")).replace(" ", "")
        return "1", item_desc, item_uom, quantity

    if re.search(r"ILO[ÅšÄ†] OPAK\.|ilosc opak", text, re.I):
        qty_tokens = re.findall(r"\d[\d\s.,]*", row_body)
        if qty_tokens:
            quantity = normalize_text(qty_tokens[-1]).replace(" ", "")
            item_desc = normalize_text(row_body[: row_body.rfind(qty_tokens[-1])]).strip(" -â€“.;,")
            return "1", item_desc, "opak.", quantity

    return "", "", "", ""


def _extract_first_pharma_row_item_fields_v2(description: str) -> tuple[str, str, str, str]:
    text = normalize_text(description)
    if not text:
        return "", "", "", ""

    direct_pack_match = re.search(
        r":\s*1[.)]?\s*(?P<item_desc>.*?)\s*[-â€“]\s*(?P<qty>\d[\d\s.,]*)\s*(?P<item_uom>opk\.|opk|op\.|op)\b",
        text,
        re.I,
    )
    if direct_pack_match:
        return (
            "1",
            normalize_text(direct_pack_match.group("item_desc")).strip(" -â€“.;,"),
            normalize_text(direct_pack_match.group("item_uom")),
            normalize_text(direct_pack_match.group("qty")).replace(" ", ""),
        )

    direct_pack_match = re.search(
        r"1[.)]?\s*(?P<item_desc>.*?)\s*[-â€“]\s*(?P<qty>\d[\d\s.,]*)\s*(?P<item_uom>opk\.|opk|op\.|op)\b",
        text,
        re.I,
    )
    if direct_pack_match:
        return (
            "1",
            normalize_text(direct_pack_match.group("item_desc")).strip(" -â€“.;,"),
            normalize_text(direct_pack_match.group("item_uom")),
            normalize_text(direct_pack_match.group("qty")).replace(" ", ""),
        )

    direct_opak_match = re.search(
        r"dostawa\s+(?P<item_desc>.*?)(?:-|â€“)?\s*ilo\S*\s+opak\S*\s*(?P<qty>\d[\d\s.,]*)",
        text,
        re.I,
    )
    if direct_opak_match:
        return (
            "1",
            normalize_text(direct_opak_match.group("item_desc")).strip(" -â€“.;,"),
            "opak.",
            normalize_text(direct_opak_match.group("qty")).replace(" ", ""),
        )

    opak_row_match = re.search(r"OPAK\.\s*1[.)]?\s*(?P<row_body>.*?)(?=\s+2[.)]\s|\s*$)", text, re.I)
    if opak_row_match:
        row_body = normalize_text(opak_row_match.group("row_body")).strip(" -â€“.;,")
        qty_tokens = re.findall(r"\d[\d\s.,]*", row_body)
        if qty_tokens:
            quantity = normalize_text(qty_tokens[-1]).replace(" ", "")
            item_desc = normalize_text(row_body[: row_body.rfind(qty_tokens[-1])]).strip(" -â€“.;,")
            return "1", item_desc, "opak.", quantity

    unit_row_match = re.search(
        r"Jednostka miary.*?asortymentu\s*1\s*(?P<row_body>.*?)(?=\s+2\s|\s*$)",
        text,
        re.I,
    )
    if unit_row_match:
        row_body = normalize_text(unit_row_match.group("row_body")).strip(" -â€“.;,")
        unit_match = re.search(
            r"(?P<item_desc>.*?)\s+\d+\s+(?P<item_uom>fiol\.|fiol|amp\.|amp|tabl\.|tabl|kaps\.|kaps|sasz|op\.|op)\s*(?P<qty>\d[\d\s.,]*)$",
            row_body,
            re.I,
        )
        if unit_match:
            return (
                "1",
                normalize_text(unit_match.group("item_desc")).strip(" -â€“.;,"),
                normalize_text(unit_match.group("item_uom")),
                normalize_text(unit_match.group("qty")).replace(" ", ""),
            )

    direct_unit_row_match = re.search(
        r"asortymentu\s*1\s*(?P<item_desc>.*?)\s+\d+\s+(?P<item_uom>fiol\.|fiol|amp\.|amp|tabl\.|tabl|kaps\.|kaps|sasz|op\.|op)\s*(?P<qty>\d[\d\s.,]*)(?=\s+\d+\s|\s*$)",
        text,
        re.I,
    )
    if direct_unit_row_match:
        return (
            "1",
            normalize_text(direct_unit_row_match.group("item_desc")).strip(" -â€“.;,"),
            normalize_text(direct_unit_row_match.group("item_uom")),
            normalize_text(direct_unit_row_match.group("qty")).replace(" ", ""),
        )

    package_quantity_match = re.search(r"ilo\S*\s+opak\S*\s*(?P<qty>\d[\d\s.,]*)", text, re.I)
    if package_quantity_match and " 1 " not in text[: package_quantity_match.start()]:
        item_desc = normalize_text(text[: package_quantity_match.start()]).strip(" -â€“.;,")
        quantity = normalize_text(package_quantity_match.group("qty")).replace(" ", "")
        return "1", item_desc, "opak.", quantity

    row_body = ""
    structural_patterns = (
        r"(?:L\.p\.|LP\.|Lp\.).*?(?:Jednostka miary|Zamawiana ilo\S+|Wymagana.*?ilo\S+|ILO\S*\s+OPAK\.)\s*1[.)]?\s*(?P<row_body>.*?)(?=(?:[;,.]\s*2[.)]\s)|(?:\s+2[.)]\s)|\s*$)",
        r"Przedmiotem zam[oÃ³]wienia jest dostawa produkt[oÃ³]w leczniczych:\s*1[.)]?\s*(?P<row_body>.*?)(?=(?:[;,.]\s*2[.)]\s)|(?:\s+2[.)]\s)|\s*$)",
        r"(?:^|:\s*)1[.)]?\s*(?P<row_body>.*?)(?=(?:[;,.]\s*2[.)]\s)|(?:\s+2[.)]\s)|\s*$)",
    )
    for pattern in structural_patterns:
        match = re.search(pattern, text, re.I)
        if match:
            row_body = normalize_text(match.group("row_body")).strip(" -â€“.;,")
            break
    if not row_body:
        return "", "", "", ""

    row_body = re.sub(r"^(?:1\s+)?", "", row_body)

    end_pack_match = re.search(
        r"(?P<item_desc>.*?)\s+(?:(?P<pack_size>\d[\d\s.,]*)\s+)?(?P<item_uom>opk\.|opk|opak\w*|op\.|op|fiol\.|fiol|amp\.|amp|tabl\.|tabl|kaps\.|kaps|sasz|wstrzykiwaczy|ampułkostrzykawka)\s*(?:[x.]?\s*|[-â€“]\s*)(?P<qty>\d[\d\s.,]*)$",
        row_body,
        re.I,
    )
    if end_pack_match:
        item_desc = normalize_text(end_pack_match.group("item_desc")).strip(" -â€“.;,")
        item_uom = normalize_text(end_pack_match.group("item_uom"))
        quantity = normalize_text(end_pack_match.group("qty")).replace(" ", "")
        return "1", item_desc, item_uom, quantity

    qty_tokens = re.findall(r"\d[\d\s.,]*", row_body)
    if re.search(r"ILO\S*\s+OPAK\.|opak", text, re.I) and qty_tokens:
        quantity = normalize_text(qty_tokens[-1]).replace(" ", "")
        item_desc = normalize_text(row_body[: row_body.rfind(qty_tokens[-1])]).strip(" -â€“.;,")
        return "1", item_desc, "opak.", quantity

    return "", "", "", ""


def _item_candidate_score(description: str) -> tuple[int, int, int]:
    item_quantity, item_uom = _extract_quantity_fields(description)
    return (
        1 if item_quantity and item_uom else 0,
        1 if item_quantity or item_uom else 0,
        -len(description),
    )


def _choose_item_source_description(description: str, original_description: str) -> str:
    candidates = [candidate for candidate in [description, original_description] if candidate]
    if not candidates:
        return ""
    return max(candidates, key=_item_candidate_score)


def _extract_item_description(description: str, title: str) -> str:
    cleaned = normalize_text(description)
    if cleaned:
        cleaned = re.split(r"Szcz[a-zA-Z?óÓłŁżŻźŹęĘąĄśŚćĆńŃ]{2,}\s+opis", cleaned, maxsplit=1, flags=re.I)[0].strip(
            " .,:;"
        )
        cleaned = re.sub(
            r"\s*[–\-?]?\s*\d[\d\s.,]*\s*(sztuk(?:a|i)?|szt\.|szt|godzin(?:y)?|godz\.|opakowan|opakowanie|litrow|ml|kg|g|m2|m3|mb)\b\.?$",
            "",
            cleaned,
            flags=re.I,
        ).strip(" .,:;")
    return cleaned or title


def _extract_standalone_item_description(description: str, title: str, classification: str) -> str:
    classification_text = normalize_text(classification)
    if classification_text.startswith(("601", "772", "850", "851", "983")):
        return ""

    candidate = _extract_item_description(description, title)
    if not candidate:
        return ""

    candidate_lower = candidate.lower()
    if len(candidate) > 180:
        return ""
    if any(marker in candidate_lower for marker in ("body {", "font-family", ".text-center", ".bg-light", "box-sizing")):
        return ""
    if re.fullmatch(r"pakiet\s+\d+", candidate_lower) or re.fullmatch(r"zadanie\s+\d+", candidate_lower):
        return ""
    if any(
        phrase in candidate_lower
        for phrase in (
            "świadczenie usług",
            "transport sanitarn",
            "szczegółowy opis",
            "zgodnie z załącznikiem",
            "zgodnie z zał",
            "stanowiącym załącznik",
            "formularz",
            " swz",
            " na okres",
            "pakietów",
        )
    ):
        return ""

    candidate = re.sub(
        r"^(?:1\.\s*)?(?:przedmiotem zam[oÃ³]wienia jest\s+|przedmiot zam[oÃ³]wienia stanowi\s+)",
        "",
        candidate,
        flags=re.I,
    )
    candidate = re.sub(r"^(?:dostawa|zakup(?:u)?|zakup i dostawa)\s+", "", candidate, flags=re.I)
    candidate = re.sub(r"^\d+\s*[-.)]\s*", "", candidate)
    candidate = candidate.strip(" .,:;\"'“-”")

    if not candidate or len(candidate) < 4:
        return ""
    if candidate.lower() in {"pakiet", "zadanie"}:
        return ""
    return candidate


def _extract_cpv_from_html(html_body: str) -> str:
    matches = re.findall(r"\b\d{8}-\d\b(?:\s*\([^)]+\))?", strip_html_tags(html_body))
    if not matches:
        return ""
    seen = []
    for match in matches:
        cleaned = normalize_text(match)
        if cleaned and cleaned not in seen:
            seen.append(cleaned)
    return ",".join(seen)


def _parse_decimal(value: str) -> Decimal | None:
    cleaned = normalize_text(value).replace(" ", "").replace("\xa0", "")
    if not cleaned:
        return None
    cleaned = cleaned.replace(",", ".")
    try:
        return Decimal(cleaned)
    except InvalidOperation:
        return None


def _format_decimal(value: Decimal) -> str:
    quantized = value.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
    text = format(quantized, "f")
    return text.rstrip("0").rstrip(".") if "." in text else text


def _parse_iso_date(value: str) -> date:
    return datetime.strptime(value, "%Y-%m-%d").date()


def _format_iso_date(value: date) -> str:
    return value.isoformat()


def _fetch_notice_window(session: requests.Session, notice_type: str, date_from: str, date_to: str, page_size: int) -> List[Dict[str, object]]:
    last_error: Exception | None = None
    for _ in range(3):
        try:
            response = session.get(
                LIVE_API_URL,
                params={
                    "PageNumber": 1,
                    "PageSize": page_size,
                    "NoticeType": notice_type,
                    "PublicationDateFrom": date_from,
                    "PublicationDateTo": date_to,
                },
                timeout=60,
            )
            response.raise_for_status()
            return response.json()
        except RequestException as exc:
            last_error = exc
    if last_error is not None:
        raise last_error
    return []


def _collect_notice_map_by_tender_id(
    session: requests.Session, notice_type: str, date_from: str, date_to: str, page_size: int
) -> Dict[str, Dict[str, object]]:
    notices_by_tender_id: Dict[str, Dict[str, object]] = {}
    for _, _, notices in _iter_stable_notice_windows(session, notice_type, date_from, date_to, page_size):
        for notice in notices:
            tender_id = normalize_text(notice.get("tenderId"))
            if not tender_id or tender_id in notices_by_tender_id:
                continue
            notices_by_tender_id[tender_id] = notice
    return notices_by_tender_id


def _iter_stable_notice_windows(
    session: requests.Session, notice_type: str, date_from: str, date_to: str, page_size: int
) -> List[tuple[str, str, List[Dict[str, object]]]]:
    try:
        notices = _fetch_notice_window(session, notice_type, date_from, date_to, page_size)
    except RequestException:
        notices = []
        start = _parse_iso_date(date_from)
        end = _parse_iso_date(date_to)
        if (end - start).days > MIN_SPLIT_DAYS:
            midpoint = start + timedelta(days=(end - start).days // 2)
            left_to = midpoint.isoformat()
            right_from = (midpoint + timedelta(days=1)).isoformat()
            windows = _iter_stable_notice_windows(session, notice_type, date_from, left_to, page_size)
            if midpoint < end:
                windows.extend(_iter_stable_notice_windows(session, notice_type, right_from, date_to, page_size))
            return windows
        return [(date_from, date_to, notices)]
    if len(notices) < page_size:
        return [(date_from, date_to, notices)]

    start = _parse_iso_date(date_from)
    end = _parse_iso_date(date_to)
    if (end - start).days <= MIN_SPLIT_DAYS:
        return [(date_from, date_to, notices)]

    midpoint = start + timedelta(days=(end - start).days // 2)
    left_to = midpoint.isoformat()
    right_from = (midpoint + timedelta(days=1)).isoformat()

    windows = _iter_stable_notice_windows(session, notice_type, date_from, left_to, page_size)
    if midpoint < end:
        windows.extend(_iter_stable_notice_windows(session, notice_type, right_from, date_to, page_size))
    return windows


def _medical_text(notice: Dict[str, object]) -> str:
    return " ".join(
        [
            normalize_text(notice.get("cpvCode")).lower(),
            normalize_text(notice.get("orderObject")).lower(),
        ]
    )


def _is_medical_notice(notice: Dict[str, object]) -> bool:
    cpv = normalize_text(notice.get("cpvCode"))
    if any(cpv.startswith(prefix) for prefix in MEDICAL_CPV_PREFIXES):
        return True
    haystack = _medical_text(notice)
    return any(re.search(pattern, haystack) for pattern in MEDICAL_PATTERNS)


def _is_awarded_notice(notice: Dict[str, object]) -> bool:
    notice_type = normalize_text(notice.get("noticeType"))
    if notice_type == "TenderResultNotice":
        return normalize_text(notice.get("procedureResult")) == "zawarcieUmowy"
    return notice_type == "ContractPerformingNotice"


def map_notice_to_rows(
    notice: Dict[str, object], query_text: str = "", original_notice: Dict[str, object] | None = None
) -> List[Dict[str, str]]:
    html_body = str(notice.get("htmlBody") or "")
    original_html_body = str((original_notice or {}).get("htmlBody") or "")
    full_html_text = _full_notice_text(html_body)
    original_full_html_text = _full_notice_text(original_html_body)
    cpv = normalize_text(notice.get("cpvCode")) or normalize_text((original_notice or {}).get("cpvCode"))
    if not cpv:
        cpv = _extract_cpv_from_html(html_body) or _extract_cpv_from_html(original_html_body)
    title = normalize_text(notice.get("orderObject"))
    notice_number = normalize_text(notice.get("noticeNumber"))
    object_id = normalize_text(notice.get("objectId"))
    notice_type = normalize_text(notice.get("noticeType"))
    description = _extract_description(html_body)
    original_description = ""
    if original_notice:
        original_description = _extract_description(original_html_body)
        if len(original_description) > len(description):
            description = original_description

    contractors = notice.get("contractors") or []
    awarded_supplier_name = ""
    if contractors:
        awarded_supplier_name = normalize_text((contractors[0] or {}).get("contractorName"))
    if not awarded_supplier_name:
        awarded_supplier_name = _extract_html_value(html_body, r"4\.3\.1\.\).*?<span class=\"normal\">(.*?)</span>")

    currency = ""
    amount = ""
    awarded_currency = ""
    awarded_value = ""
    item_award = ""

    if notice_type == "ContractPerformingNotice":
        awarded_currency, awarded_value = _extract_html_money(html_body, "4.4.)")
        item_award_currency, item_award = _extract_html_money(html_body, "5.5.)")
        if item_award_currency and not awarded_currency:
            awarded_currency = item_award_currency
        if item_award_currency and not currency:
            currency = item_award_currency
        amount = awarded_value
    elif notice_type == "TenderResultNotice":
        awarded_currency, awarded_value = _extract_html_money(html_body, "6.1.5.)")
        if not awarded_value:
            awarded_currency, awarded_value = _extract_html_money(html_body, "5.1.)")
        currency = awarded_currency
        amount = awarded_value

    item_source_description = _choose_item_source_description(_extract_description(html_body), original_description)
    pharma_item_no, pharma_item_desc, pharma_item_uom, pharma_item_quantity = _extract_first_pharma_row_item_fields_v2(
        item_source_description
    )
    if pharma_item_quantity and pharma_item_uom:
        item_no = pharma_item_no or "1"
        item_desc = pharma_item_desc or title
        item_uom = pharma_item_uom
        item_quantity = pharma_item_quantity
    else:
        table_item_no, table_item_desc, table_item_uom, table_item_quantity = _extract_table_style_item_fields(
            item_source_description
        )
        if table_item_quantity and table_item_uom:
            item_no = table_item_no or "1"
            item_desc = table_item_desc or title
            item_uom = table_item_uom
            item_quantity = table_item_quantity
        else:
            item_quantity, item_uom = _extract_quantity_fields(item_source_description)
            item_no = "1" if item_quantity or item_uom else ""
            item_desc = _extract_item_description(item_source_description, title) if item_quantity or item_uom else ""
    if original_notice and not (item_quantity and item_uom):
        (
            original_pharma_item_no,
            original_pharma_item_desc,
            original_pharma_item_uom,
            original_pharma_item_quantity,
        ) = _extract_first_pharma_row_item_fields_v2(original_full_html_text)
        if original_pharma_item_quantity and original_pharma_item_uom:
            item_no = original_pharma_item_no or item_no or "1"
            item_desc = original_pharma_item_desc or item_desc or title
            item_uom = original_pharma_item_uom
            item_quantity = original_pharma_item_quantity
    if original_notice and not (item_quantity and item_uom):
        (
            original_item_no,
            original_item_desc,
            original_item_uom,
            original_item_quantity,
        ) = _extract_table_style_item_fields(original_full_html_text)
        if original_item_quantity and original_item_uom:
            item_no = original_item_no or item_no or "1"
            item_desc = original_item_desc or item_desc or title
            item_uom = original_item_uom
            item_quantity = original_item_quantity
    if original_notice and not (item_quantity and item_uom):
        original_quantity, original_uom = _extract_quantity_fields(original_full_html_text)
        item_quantity = item_quantity or original_quantity
        item_uom = item_uom or original_uom
    if item_quantity or item_uom:
        item_no = item_no or "1"
        item_desc = item_desc or _extract_item_description(item_source_description, title)
    elif not item_desc:
        item_desc = _extract_standalone_item_description(item_source_description, title, cpv)
        if item_desc:
            item_no = item_no or "1"

    item_unit_price = ""
    quantity_decimal = _parse_decimal(item_quantity)
    total_decimal = _parse_decimal(item_award or awarded_value)
    if quantity_decimal and total_decimal and quantity_decimal > 0:
        item_unit_price = _format_decimal(total_decimal / quantity_decimal)

    row = OutputRow(
        source=CONFIG.source,
        country=CONFIG.country,
        country_cc=CONFIG.country_cc,
        publication_date=normalize_text(notice.get("publicationDate")),
        closing_date=normalize_text(notice.get("submittingOffersDate"))
        or normalize_text((original_notice or {}).get("submittingOffersDate"))
        or _extract_closing_date_from_html(html_body)
        or _extract_closing_date_from_html(original_html_body),
        title=title,
        description=description,
        buyer=normalize_text(notice.get("organizationName")),
        classification=cpv,
        status="Complete" if notice_type == "ContractPerformingNotice" else "Awarded",
        currency=currency,
        amount=amount,
        awarding_supplier_name=awarded_supplier_name,
        awarded_currency=awarded_currency,
        awarded_value=awarded_value,
        contract_period=_extract_contract_period(html_body, notice_type),
        item_no=item_no,
        item_desc=item_desc,
        item_uom=item_uom,
        item_quantity=item_quantity,
        item_unit_price=item_unit_price,
        item_award=item_award,
        notice_id=notice_number or normalize_text(notice.get("tenderId")),
        notice_url=_build_notice_url(object_id) if object_id else "",
        query_text=query_text,
        scraped_at=utc_now_iso(),
        dedup_key="|".join(
            part for part in [CONFIG.key, normalize_text(notice.get("tenderId")), notice_number] if part
        ),
    )
    return [row.to_dict()]


def smoke_probe() -> SmokeProbeResult:
    notice = _load_sample_notice()
    rows = map_notice_to_rows(notice, query_text="fixture:2024-01-01..2024-01-03")
    row = rows[0]
    ok = all([row["notice_id"], row["title"], row["buyer"], row["classification"], row["notice_url"]])
    return SmokeProbeResult(
        source_key=CONFIG.key,
        ok=ok,
        mode="fixture",
        detail="Mapped one public BZP contract notice sample into the normalized schema.",
        sample_rows=rows,
    )


def live_window_rows(date_from: str, date_to: str, page_size: int = 50) -> List[Dict[str, str]]:
    rows: List[Dict[str, str]] = []
    session = requests.Session()
    session.headers.update({"User-Agent": "Mozilla/5.0"})

    for notice_type in LIVE_NOTICE_TYPES:
        response = session.get(
            LIVE_API_URL,
            params={
                "PageNumber": 1,
                "PageSize": page_size,
                "NoticeType": notice_type,
                "PublicationDateFrom": date_from,
                "PublicationDateTo": date_to,
            },
            timeout=60,
        )
        response.raise_for_status()
        notices = response.json()
        query_text = f"live:{notice_type}:{date_from}..{date_to}"
        for notice in notices:
            rows.extend(map_notice_to_rows(notice, query_text=query_text))

    return rows


def live_medical_awarded_rows(date_from: str, date_to: str, page_size: int = 100) -> List[Dict[str, str]]:
    rows: List[Dict[str, str]] = []
    session = requests.Session()
    session.headers.update({"User-Agent": "Mozilla/5.0"})
    contract_notice_from = _format_iso_date(_parse_iso_date(date_from) - timedelta(days=ORIGINAL_NOTICE_LOOKBACK_DAYS))
    original_notices = _collect_notice_map_by_tender_id(
        session, "ContractNotice", contract_notice_from, date_to, page_size
    )

    for notice_type in LIVE_AWARDED_NOTICE_TYPES:
        for window_from, window_to, notices in _iter_stable_notice_windows(
            session, notice_type, date_from, date_to, page_size
        ):
            query_text = f"live-medical-awarded:{notice_type}:{window_from}..{window_to}"
            for notice in notices:
                if not _is_awarded_notice(notice):
                    continue
                if not _is_medical_notice(notice):
                    continue
                original_notice = original_notices.get(normalize_text(notice.get("tenderId")))
                rows.extend(map_notice_to_rows(notice, query_text=query_text, original_notice=original_notice))

    return rows

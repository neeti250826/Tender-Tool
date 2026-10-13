from __future__ import annotations

from datetime import datetime, timezone


def repair_mojibake(value: str) -> str:
    text = str(value)
    suspicious_markers = ("Ã", "Å", "Ø", "Ù", "Ð", "Ñ")
    if not any(marker in text for marker in suspicious_markers):
        return text
    for source_encoding in ("latin1", "cp1252"):
        try:
            repaired = text.encode(source_encoding).decode("utf-8")
        except (UnicodeEncodeError, UnicodeDecodeError):
            continue
        if repaired and repaired != text:
            return repaired
    return text


def normalize_text(value: object) -> str:
    if value is None:
        return ""
    repaired = repair_mojibake(str(value))
    return " ".join(repaired.split()).strip()


def normalize_country_code(value: object) -> str:
    return normalize_text(value).upper()


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def preserve_unknown(value: object) -> str:
    if value in (None, "", "unknown", "Unknown"):
        return ""
    return normalize_text(value)

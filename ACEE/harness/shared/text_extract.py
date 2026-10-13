from __future__ import annotations

import html
import re


TAG_RE = re.compile(r"<[^>]+>")
SPACE_RE = re.compile(r"\s+")


def strip_html_tags(value: str) -> str:
    text = TAG_RE.sub(" ", value)
    text = html.unescape(text)
    return SPACE_RE.sub(" ", text).strip()


def first_match(pattern: str, value: str, flags: int = 0) -> str:
    match = re.search(pattern, value, flags)
    if not match:
        return ""
    return SPACE_RE.sub(" ", match.group(1)).strip()


"""HTML/JSF form filter discovery helpers.

Goal: provide a lightweight, dependency-free way (stdlib only) to:
- fetch an advanced-search page
- enumerate form controls that represent filters (text inputs, selects, checkboxes)

This is used by multiple scaffold tender portal scrapers to implement:
- --list-advanced-filters
- best-effort mapping of label -> control name

NOTE: Many procurement portals are JS-heavy; for those, pair this with a
Playwright --discover-only mode to capture XHR endpoints.
"""

from __future__ import annotations

from dataclasses import dataclass
from html.parser import HTMLParser
from typing import Dict, Iterable, List, Optional, Sequence, Tuple


@dataclass(frozen=True)
class FormOption:
    value: str
    label: str


@dataclass(frozen=True)
class FormControl:
    label: str
    control_id: str
    name: str
    control_type: str  # text/select/checkbox/hidden/etc
    options: Tuple[FormOption, ...] = ()


class _FormParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.forms: List[dict] = []
        self._form: Optional[dict] = None
        self._label_for: Optional[str] = None
        self._label_parts: List[str] = []
        self._select: Optional[dict] = None
        self._option: Optional[dict] = None
        self._button: Optional[dict] = None

    def handle_starttag(self, tag: str, attrs: List[tuple[str, Optional[str]]]) -> None:
        t = tag.lower()
        a = {k: (v if v is not None else "") for k, v in attrs}

        if t == "form":
            self._form = {
                "id": a.get("id", ""),
                "name": a.get("name", ""),
                "action": a.get("action", ""),
                "inputs": {},
                "inputs_by_name": {},
                "selects": {},
                "selects_by_name": {},
                "labels": [],  # (for_id, text)
            }
            self.forms.append(self._form)
            return

        if self._form is None:
            return

        if t == "label":
            self._label_for = a.get("for", "")
            self._label_parts = []
        elif t == "input":
            inp = {
                "id": a.get("id", ""),
                "name": a.get("name", ""),
                "type": (a.get("type", "") or "").lower(),
                "value": a.get("value", ""),
            }
            if inp["id"]:
                self._form["inputs"][inp["id"]] = inp
            if inp["name"]:
                self._form["inputs_by_name"][inp["name"]] = inp
        elif t == "select":
            sel = {
                "id": a.get("id", ""),
                "name": a.get("name", ""),
                "options": [],
            }
            if sel["id"]:
                self._form["selects"][sel["id"]] = sel
            if sel["name"]:
                self._form["selects_by_name"][sel["name"]] = sel
            self._select = sel
        elif t == "option" and self._select is not None:
            opt = {"value": a.get("value", ""), "label_parts": []}
            self._option = opt
            self._select["options"].append(opt)

    def handle_endtag(self, tag: str) -> None:
        t = tag.lower()
        if t == "form":
            self._form = None
            self._select = None
            self._option = None
        elif t == "label" and self._form is not None and self._label_for is not None:
            text = " ".join(self._label_parts).strip()
            self._form["labels"].append((self._label_for, text))
            self._label_for = None
            self._label_parts = []
        elif t == "select":
            self._select = None
        elif t == "option":
            self._option = None

    def handle_data(self, data: str) -> None:
        if self._form is None:
            return
        if self._label_for is not None:
            self._label_parts.append(str(data or ""))
        if self._option is not None:
            self._option["label_parts"].append(str(data or ""))


def parse_forms(html: str) -> List[dict]:
    parser = _FormParser()
    parser.feed(str(html or ""))
    # finalize option labels
    for f in parser.forms:
        for sel in list(f.get("selects", {}).values()):
            for opt in sel.get("options", []):
                opt["label"] = " ".join(opt.get("label_parts", [])).strip()
    return parser.forms


def pick_main_form(forms: Sequence[dict], *, action_contains: Sequence[str] = ()) -> Optional[dict]:
    if not forms:
        return None
    tokens = [str(t or "").lower() for t in list(action_contains or []) if str(t or "").strip()]

    def score(form: dict) -> int:
        base = int(len(form.get("inputs", {})) + len(form.get("selects", {})))
        action = str(form.get("action", "") or "").lower()
        if tokens and any(t in action for t in tokens):
            base += 100
        return base

    return sorted(list(forms), key=score, reverse=True)[0]


def extract_controls(form: dict) -> List[FormControl]:
    labels: Dict[str, str] = {str(fid): str(text).strip() for fid, text in list(form.get("labels", [])) if fid}
    controls: List[FormControl] = []

    # controls referenced by label[for]
    for fid, label in labels.items():
        if not label:
            continue
        if fid in form.get("selects", {}):
            sel = form["selects"][fid]
            opts = tuple(FormOption(str(o.get("value", "")), str(o.get("label", ""))) for o in sel.get("options", []))
            controls.append(
                FormControl(
                    label=label,
                    control_id=str(fid),
                    name=str(sel.get("name", "")),
                    control_type="select",
                    options=opts,
                )
            )
        elif fid in form.get("inputs", {}):
            inp = form["inputs"][fid]
            controls.append(
                FormControl(
                    label=label,
                    control_id=str(fid),
                    name=str(inp.get("name", "")),
                    control_type=str(inp.get("type", "") or "input"),
                )
            )

    # unlabeled selects/inputs (best-effort)
    for name, sel in dict(form.get("selects_by_name", {})).items():
        if any(c.name == name for c in controls):
            continue
        opts = tuple(FormOption(str(o.get("value", "")), str(o.get("label", ""))) for o in sel.get("options", []))
        controls.append(
            FormControl(
                label="(unlabeled select)",
                control_id=str(sel.get("id", "")),
                name=str(name),
                control_type="select",
                options=opts,
            )
        )
    for name, inp in dict(form.get("inputs_by_name", {})).items():
        if any(c.name == name for c in controls):
            continue
        itype = str(inp.get("type", "") or "").lower()
        if itype in {"hidden", "submit", "button"}:
            continue
        controls.append(
            FormControl(
                label="(unlabeled input)",
                control_id=str(inp.get("id", "")),
                name=str(name),
                control_type=itype or "input",
            )
        )

    # stable order
    return sorted(controls, key=lambda c: (c.label.lower(), c.name.lower()))


def format_controls_for_cli(controls: Iterable[FormControl], *, max_options: int = 50) -> str:
    lines: List[str] = []
    for c in list(controls or []):
        lines.append(f"- {c.label} ({c.control_type}) name={c.name}")
        if c.options:
            for opt in list(c.options)[: max_options if max_options > 0 else 0]:
                lines.append(f"    {opt.value} -> {opt.label}")
    return "\n".join(lines).rstrip() + ("\n" if lines else "")

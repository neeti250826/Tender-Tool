"""Taxonomy loader + text normalisation + inverted-index builder.

Loads the Clearstate MedTech mapping taxonomy (Mapping_Taxonomy.xlsx) and turns
each dimension tab into a controlled vocabulary with an inverted token index used
for fast candidate generation during keyword + fuzzy (semantic) matching.

Dimension tab -> target field:
  dim_overview  -> OU
  dim_subview   -> Sub-OU   (+ sub_ou -> ou lookup)
  dim_product   -> Product Category
  dim_company   -> Company
  dim_procedure -> Family   (procedure family / group)
"""
from __future__ import annotations

import re
import unicodedata
from collections import defaultdict

import openpyxl

# --- Generic medtech/tender words that must NOT be the SOLE basis of a match ---
GENERIC = {
    "medical", "equipment", "equipments", "device", "devices", "system", "systems",
    "supply", "supplies", "material", "materials", "kit", "kits", "set", "sets",
    "disposable", "disposables", "hospital", "surgical", "surgery", "instrument",
    "instruments", "product", "products", "health", "healthcare", "care", "unit",
    "units", "machine", "machines", "line", "procurement", "package", "goods",
    "service", "services", "use", "single", "sterile", "consumable", "consumables",
    "general", "patient", "clinical", "treatment", "therapy", "and", "for", "the",
    "of", "with", "other", "others", "various", "accessory", "accessories", "type",
    "types", "model", "new", "high", "low", "small", "large", "size", "standard",
    "portable", "digital", "medicine", "pharmaceutical", "chemical", "solution",
    "solutions", "specialized", "professional", "function", "assorted", "spare",
    "part", "parts", "component", "components", "item", "items", "no", "number",
    "procedure", "based",
}

# Company legal-form / descriptor words that are not distinctive on their own.
COMPANY_STOP = {
    "inc", "ltd", "co", "corp", "corporation", "company", "limited", "gmbh", "ag",
    "llc", "plc", "sa", "srl", "bv", "nv", "kg", "holdings", "holding", "group",
    "international", "global", "medical", "med", "healthcare", "health", "diagnostics",
    "diagnostic", "technologies", "technology", "systems", "system", "devices",
    "device", "surgical", "pharma", "pharmaceutical", "pharmaceuticals", "labs",
    "laboratories", "laboratory", "industries", "industry", "solutions", "sciences",
    "science", "biosciences", "bio", "manufacturing", "products", "the", "and",
    "of", "vietnam", "asia", "trading", "commercial", "services", "spa",
}

# Placeholder vocab values that must never be treated as a real mapping target.
JUNK = {
    "others", "other", "unknown", "na", "n a", "misc", "miscellaneous", "none",
    "various", "tbd", "unspecified", "not applicable", "other players", "others players",
    "no match", "nomatch", "", "null", "others player",
}

# Catch-all / ambiguous taxonomy values dropped to avoid systematic false positives.
CATEGORY_BLOCKLIST = {
    "accessories and instruments", "accessories", "instruments", "mapping system",
    "repair", "power system", "category", "consumables", "general", "spare parts",
    "parts", "software", "accessory products", "accessories and consumables",
    "ai in colonoscopy",
}

_ws_re = re.compile(r"[^a-z0-9&]+")


def norm(s) -> str:
    """Lower-case, strip diacritics/punctuation, normalise &/and, collapse spaces."""
    if s is None:
        return ""
    s = str(s)
    s = unicodedata.normalize("NFKD", s).encode("ascii", "ignore").decode("ascii")
    s = s.lower().replace("&", " and ")
    s = _ws_re.sub(" ", s)
    return re.sub(r"\s+", " ", s).strip()


def tokens(s: str) -> list[str]:
    return [t for t in norm(s).split(" ") if t]


# Light stopword set for tokenising TAXONOMY terms. Unlike GENERIC it KEEPS
# clinical descriptors (surgery, cardiac, vascular, therapy, diagnostic, ...) so
# a term like "Cardiac Surgery" keeps both tokens and must match both.
TAXO_STOP = {
    "and", "or", "the", "of", "for", "with", "to", "in", "on", "a", "an", "based",
    "other", "others", "various", "system", "systems", "device", "devices",
    "product", "products", "solution", "solutions", "medical", "equipment",
    "equipments", "general", "use", "single", "kit", "kits", "set", "sets",
    "accessory", "accessories", "disposable", "disposables", "supply", "supplies",
    "material", "materials", "type", "types", "model", "standard", "care",
    "unit", "units", "procedure", "procedures", "new",
}

# Single-token terms that are too generic to map on their own (match-time only).
NOISE_SINGLE = {
    "access", "adapter", "advanced", "arm", "basic", "blankets", "capital",
    "category", "closure", "delivery", "gel", "hand", "imaging", "power", "powered",
    "repair", "saline", "sensors", "sports", "synthetics", "tubing", "management",
    "temperature", "breathing", "trauma", "total", "section", "prevalence", "spine",
    "msk", "nour", "instrumented", "innovations", "robotic", "robotics", "pump",
    "pumps", "hardware", "small", "core", "duet", "becker", "arm", "adhesive",
    "adhesives", "patient", "catheter", "mapping", "laser",
}

# Two-letter company brands worth keeping despite the len>=3 default.
SHORT_BRANDS = {"bd", "ge", "3m", "gc", "b braun", "j and j"}


def sig_tokens(s: str) -> list[str]:
    """Distinctive tokens for a taxonomy term: len>=3 and not a light stopword."""
    return [t for t in tokens(s) if len(t) >= 3 and t not in TAXO_STOP]


def company_sig_tokens(s: str) -> list[str]:
    """Company tokens: len>=2, drop legal-form/descriptor words."""
    return [t for t in tokens(s) if len(t) >= 2 and t not in COMPANY_STOP]


class Dimension:
    """One controlled vocabulary + inverted index for candidate generation."""

    def __init__(self, name: str, sig_fn=sig_tokens):
        self.name = name
        self.sig_fn = sig_fn
        self.terms: list[str] = []           # canonical output value per entry
        self.match_terms: list[str] = []     # searchable string per entry
        self.sig: list[list[str]] = []       # significant tokens per entry
        self.norm_terms: list[str] = []      # normalised searchable string
        self.extra: list[dict] = []          # extra payload per entry (e.g. ou for sub_ou)
        self.index: dict[str, set[int]] = defaultdict(set)  # token -> entry ids

    def add(self, out_value: str, match_str: str, extra: dict | None = None):
        if norm(out_value) in JUNK or norm(match_str) in JUNK:
            return  # placeholder value, not a real mapping target
        if norm(match_str) in CATEGORY_BLOCKLIST:
            return  # catch-all / ambiguous value, drop to avoid false positives
        if self.name in ("product_category", "family") and norm(match_str).endswith("others"):
            return  # "<Brand> - Others" catch-all bucket, not a real category
        st = self.sig_fn(match_str)
        if not st:
            return  # nothing distinctive to match on
        i = len(self.terms)
        self.terms.append(out_value)
        self.match_terms.append(str(match_str))
        self.norm_terms.append(norm(match_str))
        self.sig.append(st)
        self.extra.append(extra or {})
        for t in set(st):
            self.index[t].add(i)

    def candidates(self, row_token_set: set[str]) -> set[int]:
        cand: set[int] = set()
        for t in row_token_set:
            ids = self.index.get(t)
            if ids:
                cand |= ids
        return cand

    def __len__(self):
        return len(self.terms)


def load_taxonomy(path: str) -> dict[str, Dimension]:
    wb = openpyxl.load_workbook(path, data_only=True)

    def col(sheet, idx=0, min_row=2):
        return [r[idx] for r in wb[sheet].iter_rows(min_row=min_row, values_only=True)]

    dims: dict[str, Dimension] = {}

    # OU
    d = Dimension("ou")
    seen = set()
    for v in col("dim_overview", 0):
        if v and norm(v) not in seen:
            seen.add(norm(v)); d.add(str(v).strip(), str(v))
    dims["ou"] = d

    # Sub-OU (+ ou lookup). Keep first ou seen for each sub_ou.
    d = Dimension("sub_ou")
    seen = set()
    for r in wb["dim_subview"].iter_rows(min_row=2, values_only=True):
        sub, ou = r[0], r[1]
        if sub and norm(sub) not in seen:
            seen.add(norm(sub)); d.add(str(sub).strip(), str(sub), {"ou": (str(ou).strip() if ou else "")})
    dims["sub_ou"] = d

    # Product Category
    d = Dimension("product_category")
    seen = set()
    for v in col("dim_product", 0):
        if v and norm(v) not in seen:
            seen.add(norm(v)); d.add(str(v).strip(), str(v))
    dims["product_category"] = d

    # Company
    d = Dimension("company", sig_fn=company_sig_tokens)
    seen = set()
    for v in col("dim_company", 0):
        if v and norm(v) not in seen:
            seen.add(norm(v)); d.add(str(v).strip(), str(v))
    dims["company"] = d

    # Family (dim_procedure). Match against the input 'procedure' and
    # 'Mapped Canonical procedure'; output the procedure family (group) + category.
    d = Dimension("family")
    seen = set()
    for r in wb["dim_procedure"].iter_rows(min_row=2, values_only=True):
        procedure = r[0]
        canonical = r[1]
        group = r[2]          # "Mapped procedure group" == family
        category = r[10]      # "Mapped procedure category"
        fam_out = str(group).strip() if group else (str(canonical).strip() if canonical else "")
        for term in {procedure, canonical}:
            if term and norm(term) not in seen:
                seen.add(norm(term))
                d.add(fam_out, str(term),
                      {"category": (str(category).strip() if category else ""),
                       "canonical": (str(canonical).strip() if canonical else "")})
    dims["family"] = d

    return dims


if __name__ == "__main__":
    dims = load_taxonomy(r"<DOWNLOADS>/Mapping_Taxonomy.xlsx")
    for k, d in dims.items():
        print(f"{k:18s} entries={len(d):4d}  index_tokens={len(d.index)}")

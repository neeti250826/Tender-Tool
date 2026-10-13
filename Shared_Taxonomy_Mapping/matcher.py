"""Keyword + semantic (fuzzy) matcher over the taxonomy dimensions.

Mirrors the tender-intelligence-memory plugin: approved-exact (keyword) first,
then advisory fuzzy word-similarity (no embeddings).

For each taxonomy term we require its distinctive tokens to appear in the row's
search text AND to appear CLOSE TOGETHER (locality), which prevents a term like
"Cardiac Surgery" from matching "cardiac catheterization ... general surgery"
where the words are scattered far apart.

  keyword : every distinctive token present exactly, within the locality window
  fuzzy   : same, but >=1 token matched via per-token spelling similarity (>=88),
            or (for terms with >=3 tokens) one token missing entirely
"""
from __future__ import annotations

from collections import defaultdict

from rapidfuzz import fuzz

from taxonomy import tokens, NOISE_SINGLE, SHORT_BRANDS

TOKEN_FUZZY_CUTOFF = 88   # per-token spelling similarity to count as a near hit
SLACK = 2                 # extra tokens allowed inside the locality window


def _min_span(pos_lists: list[list[int]]) -> int:
    """Smallest window (max-min position) containing >=1 occurrence of every token."""
    events = []
    for ti, pl in enumerate(pos_lists):
        for p in pl:
            events.append((p, ti))
    events.sort()
    need = len(pos_lists)
    cnt = defaultdict(int)
    have = 0
    best = 10 ** 9
    l = 0
    for p, ti in events:
        cnt[ti] += 1
        if cnt[ti] == 1:
            have += 1
        while have == need:
            lp, lti = events[l]
            if p - lp < best:
                best = p - lp
            cnt[lti] -= 1
            if cnt[lti] == 0:
                have -= 1
            l += 1
    return best


def _occurrences(st, R, allow_fuzzy):
    """Positions of each term token in row token list R (exact then fuzzy)."""
    occ = {}
    for t in st:
        pos = [k for k, rt in enumerate(R) if rt == t]
        if pos:
            occ[t] = ("exact", pos)
    missing = [t for t in st if t not in occ]
    fuzzy_used = False
    if allow_fuzzy and missing and len(st) <= 5 and len(R) <= 90:
        for t in missing:
            pos = [k for k, rt in enumerate(R)
                   if len(rt) >= 3 and fuzz.ratio(t, rt) >= TOKEN_FUZZY_CUTOFF]
            if pos:
                occ[t] = ("fuzzy", pos)
                fuzzy_used = True
    return occ, fuzzy_used


def _match_dimension(dim, row_tokens: set[str], R: list[str], is_company=False, min_sig=1):
    cand = dim.candidates(row_tokens)
    if not cand:
        return None
    best = None
    for i in cand:
        st = dim.sig[i]
        n = len(st)
        if n < min_sig:
            continue  # e.g. supplier pass: require >=2-token OEM name

        if n == 1:
            tok = st[0]
            if tok not in row_tokens:
                continue
            if is_company:
                if tok not in SHORT_BRANDS and len(tok) < 4:
                    continue  # drop short/ambiguous acronyms (e.g. "SMT")
            else:
                if len(tok) < 4 or tok in NOISE_SINGLE:
                    continue
            score, method, fuzzy_used = 1.0, "keyword", False
        else:
            occ, fuzzy_used = _occurrences(st, R, allow_fuzzy=True)
            matched = len(occ)
            if matched < n:
                continue  # require ALL distinctive tokens (no dropping the rare one)
            span = _min_span([occ[t][1] for t in occ])
            if span > (n - 1) + SLACK:
                continue  # tokens too scattered -> reject
            score = 1.0
            method = "fuzzy" if fuzzy_used else "keyword"

        # confidence
        if is_company:
            conf = "high" if (method == "keyword" and (n >= 2 or len(st[0]) >= 4)) else "medium"
        elif method == "keyword" and n >= 2:
            conf = "high"
        else:
            conf = "medium"

        rank = (1 if method == "keyword" else 0, n, score)
        payload = (dim.terms[i], dim.match_terms[i], method, round(score, 3), conf, dim.extra[i])
        if best is None or rank > best[0]:
            best = (rank, payload)
    return best[1] if best else None


def match_row(dims, item_text: str, context_text: str, company_text: str,
              supplier_text: str = "") -> dict:
    """item_text  = the specific line item (drives Product Category + Family).
       context_text = title + item (drives the broader OU + Sub-OU).
       company_text = OEM signal fields (drives Company).
       supplier_text = awarded VN supplier; used only for >=2-word OEM names."""
    i_list = tokens(item_text)
    i_set = set(i_list)
    x_list = tokens(context_text)
    x_set = set(x_list)
    c_list = tokens(company_text)
    c_set = set(c_list)

    out = {}
    out["product_category"] = _match_dimension(dims["product_category"], i_set, i_list)
    out["family"] = _match_dimension(dims["family"], i_set, i_list)
    out["ou"] = _match_dimension(dims["ou"], x_set, x_list)
    out["sub_ou"] = _match_dimension(dims["sub_ou"], x_set, x_list)
    out["company"] = _match_dimension(dims["company"], c_set, c_list, is_company=True)

    # Fallback: company from the awarded supplier name, but only a >=2-word OEM
    # phrase (e.g. "Karl Storz Vietnam" -> Karl Storz), never a single token.
    if not out["company"] and supplier_text:
        s_list = tokens(supplier_text)
        m = _match_dimension(dims["company"], set(s_list), s_list, is_company=True, min_sig=2)
        if m:
            out["company"] = (m[0], m[1], "supplier_name", m[3], "medium", m[5])

    if out["sub_ou"] and not out["ou"]:
        ou_from_sub = out["sub_ou"][5].get("ou")
        if ou_from_sub:
            out["ou"] = (ou_from_sub, out["sub_ou"][1], "derived_from_sub_ou",
                         out["sub_ou"][3], out["sub_ou"][4], {})
    return out

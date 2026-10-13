# -*- coding: utf-8 -*-
"""Consolidated VN tender value/volume DB + aggregate tables + market sizing vs MDT.

Value = unit_price (VND) * quantity ; converted to USD at FX.
Aggregates by OU / Sub-OU / Product Category / Company.
Market sizing: tender value/volume vs MDT Eurasia Vietnam market (CY2025), by OU & Sub-OU.
Output: VN_Medtech_Market_Sizing.xlsx
"""
from __future__ import annotations
import re
import pandas as pd
import numpy as np

VNEPS = r"<DOWNLOADS>/vneps_awarded_medtech.csv"
MAPPED = r"<WORKSPACE>/VNEPS_Awarded_Medtech_Mapped.xlsx"
MDT = r"<WORKSPACE>/mdt_vietnam_market.csv"
OUT = r"<WORKSPACE>/VN_Medtech_Market_Sizing.xlsx"
FX = 24500.0  # VND per USD (approx CY2024-25)


def num(x):
    s = re.sub(r"[^0-9.]", "", str(x).replace(",", ""))
    try:
        return float(s) if s not in ("", ".") else 0.0
    except Exception:
        return 0.0


def canon_ou(s):
    s = str(s or "")
    s = re.sub(r"\s*\([^)]*\)", "", s)          # drop parenthetical suffix
    s = s.replace(" and ", " & ").strip().lower()
    return s


def canon(s):
    return re.sub(r"\s+", " ", str(s or "")).strip().lower()


# canonical display label per OU (merges the taxonomy's duplicate name variants)
_OU_LABEL = {
    "coronary & renal denervation": "Coronary & Renal Denervation (CRDN)",
    "structural heart & aortic": "Structural Heart & Aortic (SH&A)",
    "cardiac rhythm management": "Cardiac Rhythm Management (CRM)",
    "cardiac ablation solutions": "Cardiac Ablation Solutions (CAS)",
    "peripheral vascular health": "Peripheral Vascular Health (PVH)",
}


def ou_label(raw):
    c = canon_ou(raw)
    if not c:
        return ""
    return _OU_LABEL.get(c, str(raw))


def year_of(s):
    m = re.search(r"(20\d\d)", str(s or ""))
    return m.group(1) if m else ""


def main():
    # --- load mapped VNEPS (mapping columns) and raw (price/qty) ---
    m = pd.read_excel(MAPPED, sheet_name="Mapped")
    raw = pd.read_csv(VNEPS, dtype=str, keep_default_na=False)
    # align: mapped 'Mapped' sheet contains original cols incl name/unit_price/quantity too
    df = m.copy()
    df["unit_price_vnd"] = df["unit_price"].map(num)
    df["quantity_units"] = df["quantity"].map(num)
    df["value_vnd"] = df["unit_price_vnd"] * df["quantity_units"]
    df["value_usd"] = df["value_vnd"] / FX
    df["volume"] = df["quantity_units"]
    for c in ["map_ou", "map_sub_ou", "map_product_category", "map_company"]:
        df[c] = df[c].fillna("").astype(str)
    df["OU"] = df["map_ou"].map(ou_label)          # normalised OU display label
    df["award_year"] = df["result_date"].map(year_of)

    # ---------- Aggregate tables ----------
    def agg(keys):
        g = df.groupby(keys, dropna=False).agg(
            value_vnd=("value_vnd", "sum"),
            value_usd=("value_usd", "sum"),
            volume_units=("volume", "sum"),
            line_items=("value_vnd", "size"),
            distinct_products=("name", "nunique"),
            distinct_awards=("notice_no", "nunique"),
        ).reset_index()
        g["value_usd_M"] = (g["value_usd"] / 1e6).round(3)
        g["value_vnd_bn"] = (g["value_vnd"] / 1e9).round(2)
        g = g.sort_values("value_usd", ascending=False)
        return g

    by_ou = agg(["OU"])
    by_subou = agg(["OU", "map_sub_ou"])
    by_cat = agg(["OU", "map_sub_ou", "map_product_category"])
    by_company = agg(["map_company"])
    by_ou_company = agg(["OU", "map_company"])

    # ---------- Market sizing vs MDT (CY2025) ----------
    mdt = pd.read_csv(MDT, dtype=str, keep_default_na=False)
    mdt = mdt[mdt["period"] == "CY2025"].copy()
    v = mdt["product_value_usd_M"].map(num)
    # a few capital rows are in raw USD (value>100) -> normalise to $M
    mdt["mkt_value_usd_M"] = np.where(v > 100, v / 1e6, v)
    mdt["mkt_volume"] = mdt["product_volume_units"].map(num)
    mdt["share_val"] = mdt["share_value_pct"].map(num)
    mdt["share_vol"] = mdt["share_volume_pct"].map(num)
    mdt["cou"] = mdt["ou"].map(canon_ou)
    mdt["csub"] = mdt["sub_ou"].map(canon)
    # MDT product_value_usd / product_volume_units = Medtronic's tracked value/volume (user-confirmed).
    # TOTAL market = tracked / share (only where share > 0).
    mdt["mdt_implied_total_M"] = np.where(mdt["share_val"] > 0, mdt["mkt_value_usd_M"] / mdt["share_val"], np.nan)
    mdt["mdt_implied_vol"] = np.where(mdt["share_vol"] > 0, mdt["mkt_volume"] / mdt["share_vol"], np.nan)

    df["cou"] = df["map_ou"].map(canon_ou)
    df["csub"] = df["map_sub_ou"].map(canon)
    df2025 = df[df["award_year"] == "2025"]

    def troll(frame, keys):
        return frame[frame["map_ou"] != ""].groupby(keys).agg(
            tender_value_usd_M=("value_usd", lambda s: round(s.sum() / 1e6, 2)),
            tender_volume=("volume", "sum"), tender_lines=("value_usd", "size")).reset_index()

    def troll25(frame, keys):
        return frame.groupby(keys).agg(
            tender_value_2025_M=("value_usd", lambda s: round(s.sum() / 1e6, 2))).reset_index()

    def mroll(keys):
        return mdt.groupby(keys).agg(
            mdt_market_value_M=("mdt_implied_total_M", "sum"),      # implied TOTAL market $M
            mdt_market_volume=("mdt_implied_vol", "sum"),           # implied TOTAL market units
            mdt_mdtronic_value_M=("mkt_value_usd_M", "sum")).reset_index()

    lab_ou = mdt.groupby("cou")["ou"].first().to_dict()
    lab_sub = mdt.groupby(["cou", "csub"])["sub_ou"].first().to_dict()

    def add_cov(t):
        t["value_coverage_CY2025_%"] = np.where(t["mdt_market_value_M"] > 0,
                                                (t["tender_value_2025_M"] / t["mdt_market_value_M"] * 100).round(1), np.nan)
        t["value_coverage_allyr_%"] = np.where(t["mdt_market_value_M"] > 0,
                                               (t["tender_value_usd_M"] / t["mdt_market_value_M"] * 100).round(1), np.nan)
        t["volume_coverage_%"] = np.where(t["mdt_market_volume"] > 0,
                                          (t["tender_volume"] / t["mdt_market_volume"] * 100).round(1), np.nan)
        return t

    # ----- OU level -----
    ms_ou = pd.merge(troll(df, "cou"), mroll("cou"), on="cou", how="outer")
    ms_ou = pd.merge(ms_ou, troll25(df2025[df2025["map_ou"] != ""], "cou"), on="cou", how="left")
    for c in ["tender_value_usd_M", "tender_value_2025_M", "tender_volume", "tender_lines",
              "mdt_market_value_M", "mdt_market_volume", "mdt_mdtronic_value_M"]:
        ms_ou[c] = ms_ou[c].fillna(0)
    ms_ou = add_cov(ms_ou)
    ms_ou["OU"] = ms_ou["cou"].map(lambda c: _OU_LABEL.get(c, lab_ou.get(c, str(c).title())))
    ms_ou = ms_ou[["OU", "tender_value_2025_M", "tender_value_usd_M", "tender_volume", "tender_lines",
                   "mdt_market_value_M", "mdt_market_volume", "mdt_mdtronic_value_M",
                   "value_coverage_CY2025_%", "value_coverage_allyr_%", "volume_coverage_%"]].round(2).sort_values(
        "tender_value_usd_M", ascending=False)

    # ----- Sub-OU level -----
    ms_sub = pd.merge(troll(df, ["cou", "csub"]), mroll(["cou", "csub"]), on=["cou", "csub"], how="outer")
    ms_sub = pd.merge(ms_sub, troll25(df2025[df2025["map_sub_ou"] != ""], ["cou", "csub"]), on=["cou", "csub"], how="left")
    for c in ["tender_value_usd_M", "tender_value_2025_M", "tender_volume", "tender_lines",
              "mdt_market_value_M", "mdt_market_volume", "mdt_mdtronic_value_M"]:
        ms_sub[c] = ms_sub[c].fillna(0)
    ms_sub = add_cov(ms_sub)
    ms_sub["OU"] = ms_sub["cou"].map(lambda c: _OU_LABEL.get(c, lab_ou.get(c, str(c).title())))
    ms_sub["Sub_OU"] = ms_sub.apply(lambda r: lab_sub.get((r["cou"], r["csub"]), str(r["csub"]).title()), axis=1)
    ms_sub = ms_sub[["OU", "Sub_OU", "tender_value_2025_M", "tender_value_usd_M", "tender_volume", "tender_lines",
                     "mdt_market_value_M", "mdt_market_volume", "mdt_mdtronic_value_M",
                     "value_coverage_CY2025_%", "value_coverage_allyr_%", "volume_coverage_%"]].round(2).sort_values(
        "tender_value_usd_M", ascending=False)

    notes = pd.DataFrame({"Note": [
        "TENDER side = VNEPS awarded public-procurement line items (unit_price VND x quantity), converted at %d VND/USD." % FX,
        "  - 'tender_value_2025_M' = awards dated 2025 (period-aligned to MDT CY2025); 'tender_value_usd_M' = all years 2024-2026.",
        "  - Value/volume include high-volume consumables and occasional capital/bulk lines; not deduplicated across hospitals.",
        "MDT side = MDT Eurasia Reviewer Engine, Datastore tab, country=Vietnam, period CY2025.",
        "  - CONFIRMED: product_value_usd / product_volume_units = Medtronic's OWN tracked value/volume.",
        "  - 'mdt_market_value_M' = TOTAL market = product_value_usd / share_value_pct (only categories with share>0).",
        "  - 'mdt_market_volume' = TOTAL market units = product_volume_units / share_volume_pct.",
        "  - 'mdt_mdtronic_value_M' = Medtronic's own tracked value ($M), for reference.",
        "  - MDT Vietnam sizing is PARTIAL (many categories share=0/blank -> excluded), so MDT totals UNDERSTATE the market;",
        "    coverage >100% reflects that partial MDT coverage + tender consumable/bulk breadth - treat as INDICATIVE.",
        "COVERAGE = tender as % of MDT implied total market; 'value_coverage_CY2025_%' is the apples-to-apples primary.",
    ]})

    # ---------- Consolidated raw DB (key columns) ----------
    keep = ["mapping_status", "map_ou", "map_sub_ou", "map_product_category", "map_company", "map_family",
            "name", "name_en", "manufacturer", "brand", "supplier", "buyer", "location",
            "unit", "unit_en", "quantity", "unit_price", "value_vnd", "value_usd", "result_date",
            "keyword", "notice_no", "origin", "origin_en"]
    consolidated = df[[c for c in keep if c in df.columns]].copy()

    # ---------- write ----------
    totals = {
        "Total awarded value (USD $M)": round(df["value_usd"].sum() / 1e6, 1),
        "Total awarded value (VND bn)": round(df["value_vnd"].sum() / 1e9, 0),
        "Total volume (units)": int(df["volume"].sum()),
        "Line items": len(df),
        "Mapped line items": int((df["mapping_status"] == "Mapped").sum()),
        "FX (VND/USD)": FX,
    }
    with pd.ExcelWriter(OUT, engine="openpyxl") as xl:
        pd.DataFrame(list(totals.items()), columns=["Metric", "Value"]).to_excel(xl, sheet_name="Summary", index=False)
        notes.to_excel(xl, sheet_name="Market Sizing NOTES", index=False)
        ms_ou.to_excel(xl, sheet_name="Market Sizing by OU", index=False)
        ms_sub.to_excel(xl, sheet_name="Market Sizing by Sub-OU", index=False)
        by_ou.to_excel(xl, sheet_name="Agg by OU", index=False)
        by_subou.to_excel(xl, sheet_name="Agg by Sub-OU", index=False)
        by_cat.to_excel(xl, sheet_name="Agg by Product Category", index=False)
        by_company.to_excel(xl, sheet_name="Agg by Company", index=False)
        by_ou_company.to_excel(xl, sheet_name="Agg by OU x Company", index=False)
        consolidated.to_excel(xl, sheet_name="Consolidated Tender DB", index=False)

    print("DONE ->", OUT)
    print("Totals:", totals)
    print("\nAgg by OU (normalised):")
    print(by_ou[["OU", "value_usd_M", "volume_units", "line_items"]].head(15).to_string(index=False))
    print("\nMarket sizing by OU (tender vs MDT implied total market):")
    cols = ["OU", "tender_value_2025_M", "mdt_market_value_M", "value_coverage_CY2025_%",
            "tender_volume", "mdt_market_volume", "volume_coverage_%"]
    print(ms_ou[ms_ou["mdt_market_value_M"] > 0][cols].to_string(index=False))


if __name__ == "__main__":
    main()

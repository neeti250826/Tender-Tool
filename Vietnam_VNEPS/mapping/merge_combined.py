# -*- coding: utf-8 -*-
"""Merge the VN-tender mapping and the VNEPS-awarded mapping into ONE workbook.

Output: VN_Medtech_Mapped_Combined.xlsx
  - Summary
  - Mapped (Combined)      : harmonized union of both sources' mapped rows
  - VNEPS Awarded - Mapped : full detail (with English columns)
  - VNEPS Awarded - Unmapped
  - VN Tender - Mapped     : full detail
(The 75k VN-tender UNMAPPED rows stay in VN_Medtech_Taxonomy_Mapped.xlsx to keep this file lean.)
"""
from __future__ import annotations
import time
import openpyxl
from openpyxl.cell import WriteOnlyCell
from openpyxl.styles import Font, PatternFill
from openpyxl.cell.cell import ILLEGAL_CHARACTERS_RE

VN = r"<WORKSPACE>/VN_Medtech_Taxonomy_Mapped.xlsx"
VNEPS = r"<WORKSPACE>/VNEPS_Awarded_Medtech_Mapped.xlsx"
OUT = r"<WORKSPACE>/VN_Medtech_Mapped_Combined.xlsx"

COMMON = ["source", "map_ou", "map_sub_ou", "map_product_category", "map_company",
          "map_family", "mapped_fields", "n_mapped_dims", "item_name", "item_name_en",
          "brand", "manufacturer_raw", "supplier", "buyer", "location", "country",
          "amount_or_price", "currency", "date", "notice_id"]


def san(v):
    if v is None:
        return None
    s = str(v)
    s = ILLEGAL_CHARACTERS_RE.sub("", s)
    return s[:32000] if len(s) > 32000 else s


def read_sheet(path, sheet):
    wb = openpyxl.load_workbook(path, read_only=True)
    ws = wb[sheet]
    it = ws.iter_rows(values_only=True)
    hdr = list(next(it))
    idx = {h: i for i, h in enumerate(hdr)}
    return hdr, idx, it


def g(row, idx, col):
    i = idx.get(col)
    return "" if (i is None or i >= len(row) or row[i] is None) else row[i]


def main():
    t0 = time.time()
    out = openpyxl.Workbook(write_only=True)

    # ---- Mapped (Combined) ----
    combined = out.create_sheet("Mapped (Combined)")
    combined.freeze_panes = "A2"
    hc = []
    for h in COMMON:
        c = WriteOnlyCell(combined, value=h); c.font = Font(bold=True, color="FFFFFF")
        c.fill = PatternFill("solid", fgColor="1F4E78"); hc.append(c)
    combined.append(hc)

    n_vn = n_vneps = 0

    # VN tender mapped
    hdr, idx, it = read_sheet(VN, "Mapped")
    for r in it:
        row = ["VN Tender",
               g(r, idx, "map_ou"), g(r, idx, "map_sub_ou"), g(r, idx, "map_product_category"),
               g(r, idx, "map_company"), g(r, idx, "map_family"),
               g(r, idx, "mapped_fields"), g(r, idx, "n_mapped_dims"),
               g(r, idx, "item_description_english"), g(r, idx, "item_description_english"),
               "", g(r, idx, "mapped_oem") or g(r, idx, "final_player"),
               g(r, idx, "supplier_name_english"), g(r, idx, "buyer_english"), "",
               g(r, idx, "country") or "Vietnam", g(r, idx, "amount"), g(r, idx, "currency"),
               g(r, idx, "awarded_date") or g(r, idx, "publication_date"), g(r, idx, "notice_id")]
        combined.append([san(x) for x in row]); n_vn += 1

    # VNEPS mapped
    hdr, idx, it = read_sheet(VNEPS, "Mapped")
    for r in it:
        row = ["VNEPS Awarded",
               g(r, idx, "map_ou"), g(r, idx, "map_sub_ou"), g(r, idx, "map_product_category"),
               g(r, idx, "map_company"), g(r, idx, "map_family"),
               g(r, idx, "mapped_fields"), g(r, idx, "n_mapped_dims"),
               g(r, idx, "name"), g(r, idx, "name_en"),
               g(r, idx, "brand"), g(r, idx, "manufacturer"),
               g(r, idx, "supplier"), g(r, idx, "buyer"), g(r, idx, "location"),
               "Vietnam", g(r, idx, "unit_price"), "VND",
               g(r, idx, "result_date"), g(r, idx, "notice_no")]
        combined.append([san(x) for x in row]); n_vneps += 1

    # ---- copy detail sheets verbatim ----
    def copy_sheet(src_path, src_sheet, dst_name):
        hdr, idx, it = read_sheet(src_path, src_sheet)
        ws = out.create_sheet(dst_name[:31]); ws.freeze_panes = "A2"
        hcells = []
        for h in hdr:
            c = WriteOnlyCell(ws, value=h); c.font = Font(bold=True, color="FFFFFF")
            c.fill = PatternFill("solid", fgColor="1F4E78"); hcells.append(c)
        ws.append(hcells)
        cnt = 0
        for r in it:
            ws.append([san(x) for x in r]); cnt += 1
        return cnt

    v_map = copy_sheet(VNEPS, "Mapped", "VNEPS Awarded - Mapped")
    v_unmap = copy_sheet(VNEPS, "Unmapped", "VNEPS Awarded - Unmapped")
    t_map = copy_sheet(VN, "Mapped", "VN Tender - Mapped")

    # ---- Summary (first) ----
    s = out.create_sheet("Summary")
    out.move_sheet("Summary", -(len(out.sheetnames) - 1))
    s.column_dimensions["A"].width = 42; s.column_dimensions["B"].width = 60
    tc = WriteOnlyCell(s, value="VN Medtech — Combined Mapped Dataset"); tc.font = Font(bold=True, size=14)
    s.append([tc])
    for ln in [
        ["Generated", time.strftime("%Y-%m-%d %H:%M")],
        ["", ""],
        ["Mapped (Combined) total rows", n_vn + n_vneps],
        ["  from VN Tender", n_vn],
        ["  from VNEPS Awarded", n_vneps],
        ["", ""],
        ["Sheets", "Mapped (Combined); VNEPS Awarded - Mapped/Unmapped; VN Tender - Mapped"],
        ["VNEPS Awarded - Mapped", v_map],
        ["VNEPS Awarded - Unmapped", v_unmap],
        ["VN Tender - Mapped", t_map],
        ["Note", "VN Tender UNMAPPED rows (~76k) remain in VN_Medtech_Taxonomy_Mapped.xlsx"],
    ]:
        s.append(ln)

    out.save(OUT)
    print(f"DONE {time.time()-t0:.1f}s -> {OUT}")
    print(f"Mapped (Combined): {n_vn + n_vneps}  (VN {n_vn} + VNEPS {n_vneps})")


if __name__ == "__main__":
    main()

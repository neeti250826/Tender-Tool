"""Apply the established CANLAT FY27 Q1 layout to a step-3 Excel extract."""

from __future__ import annotations

import argparse
import os
from copy import copy
from pathlib import Path
from typing import Dict, Iterable

from openpyxl import Workbook, load_workbook
from openpyxl.formula.translate import Translator
from openpyxl.utils import get_column_letter


TARGET_SHEET = "Tenders"
TARGET_COLUMN_COUNT = 39
RAW_COLUMN_COUNT = 26
FORMULA_COLUMNS = (28, 33, 34, 35, 36, 37)  # AB, AG:AK


def copy_column_dimensions(source, target) -> None:
    for column in range(1, TARGET_COLUMN_COUNT + 1):
        letter = get_column_letter(column)
        source_dimension = source.column_dimensions[letter]
        target_dimension = target.column_dimensions[letter]
        target_dimension.width = source_dimension.width
        target_dimension.hidden = source_dimension.hidden
        target_dimension.outlineLevel = source_dimension.outlineLevel
        target_dimension.collapsed = source_dimension.collapsed


def copy_cell_style(source_cell, target_cell) -> None:
    # Style IDs are local to a workbook, so copy the component objects rather
    # than assigning the source cell's internal style reference directly.
    target_cell.font = copy(source_cell.font)
    target_cell.fill = copy(source_cell.fill)
    target_cell.border = copy(source_cell.border)
    target_cell.alignment = copy(source_cell.alignment)
    target_cell.number_format = source_cell.number_format
    target_cell.protection = copy(source_cell.protection)


def copy_sheet_layout(source, target) -> None:
    target.sheet_view.showGridLines = source.sheet_view.showGridLines
    target.sheet_properties = copy(source.sheet_properties)
    target.sheet_format = copy(source.sheet_format)
    target.page_margins = copy(source.page_margins)
    target.page_setup = copy(source.page_setup)
    target.print_options = copy(source.print_options)
    target.freeze_panes = source.freeze_panes
    target.sheet_state = source.sheet_state
    copy_column_dimensions(source, target)
    target.row_dimensions[1].height = source.row_dimensions[1].height
    target.row_dimensions[2].height = source.row_dimensions[2].height


def formula_for_row(source, column: int, target_row: int) -> str:
    formula = source.cell(2, column).value
    if not isinstance(formula, str) or not formula.startswith("="):
        raise ValueError(
            f"Template cell {get_column_letter(column)}2 must contain a formula; found {formula!r}"
        )
    origin = f"{get_column_letter(column)}2"
    return Translator(formula, origin=origin).translate_formula(f"{get_column_letter(column)}{target_row}")


def validate_raw_headers(headers: Iterable[object]) -> None:
    values = list(headers)
    if len(values) != RAW_COLUMN_COUNT:
        raise ValueError(f"Expected {RAW_COLUMN_COUNT} raw columns, found {len(values)}")
    required = {"URL", "Detailed description (ESP)", "Start Date", "End Date"}
    missing = sorted(required - {str(value or "").strip() for value in values})
    if missing:
        raise ValueError(f"Raw extract is missing required column(s): {', '.join(missing)}")


def write_formatted_workbook(raw_path: Path, template_path: Path, output_path: Path, limit: int | None) -> int:
    raw_book = load_workbook(raw_path, read_only=True, data_only=False)
    raw_sheet = raw_book.active
    raw_header = [cell.value for cell in next(raw_sheet.iter_rows(max_row=1))]
    validate_raw_headers(raw_header)

    template_book = load_workbook(template_path, read_only=False, data_only=False)
    if TARGET_SHEET not in template_book.sheetnames:
        raise ValueError(f"Template workbook does not contain {TARGET_SHEET!r}")
    template_sheet = template_book[TARGET_SHEET]
    template_header = [template_sheet.cell(1, column).value for column in range(1, TARGET_COLUMN_COUNT + 1)]
    if len(template_header) != TARGET_COLUMN_COUNT or template_header[0] != "Index":
        raise ValueError("Template does not have the expected CANLAT FY27 Q1 header layout")

    output_book = Workbook()
    output_sheet = output_book.active
    output_sheet.title = TARGET_SHEET
    copy_sheet_layout(template_sheet, output_sheet)

    for column in range(1, TARGET_COLUMN_COUNT + 1):
        cell = output_sheet.cell(1, column, template_header[column - 1])
        copy_cell_style(template_sheet.cell(1, column), cell)

    rows_written = 0
    for row_number, raw_row in enumerate(raw_sheet.iter_rows(min_row=2, values_only=True), start=2):
        if limit is not None and rows_written >= limit:
            break
        values = list(raw_row)
        if len(values) < RAW_COLUMN_COUNT:
            values.extend([None] * (RAW_COLUMN_COUNT - len(values)))

        for column in range(1, TARGET_COLUMN_COUNT + 1):
            copy_cell_style(template_sheet.cell(2, column), output_sheet.cell(row_number, column))
        output_sheet.row_dimensions[row_number].height = template_sheet.row_dimensions[2].height

        output_sheet.cell(row_number, 1).value = rows_written + 1
        for raw_column, value in enumerate(values[:RAW_COLUMN_COUNT], start=2):
            output_sheet.cell(row_number, raw_column).value = value

        url_cell = output_sheet.cell(row_number, 6)
        if isinstance(url_cell.value, str) and url_cell.value.strip():
            url_cell.hyperlink = url_cell.value.strip()

        for column in FORMULA_COLUMNS:
            output_sheet.cell(row_number, column).value = formula_for_row(template_sheet, column, row_number)

        # AC:AF are deliberate reviewer inputs, while AL:AM are filled by the
        # FY27 Q1 preparation step to keep formulas and translation handling in one place.
        for column in range(29, 33):
            output_sheet.cell(row_number, column).value = None
        output_sheet.cell(row_number, 38).value = None
        output_sheet.cell(row_number, 39).value = None
        rows_written += 1

    output_sheet.auto_filter.ref = f"A1:{get_column_letter(TARGET_COLUMN_COUNT)}{rows_written + 1}"
    output_path.parent.mkdir(parents=True, exist_ok=True)
    temporary = output_path.with_suffix(".in_progress.xlsx")
    output_book.save(temporary)
    output_book.close()
    raw_book.close()
    template_book.close()
    os.replace(temporary, output_path)
    return rows_written


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--raw", type=Path, required=True, help="Workbook from step5_excel_export.py")
    parser.add_argument("--template", type=Path, required=True, help="Existing CANLAT FY27 Q1 workbook")
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--limit", type=int, help="Optional row cap for a smoke test")
    args = parser.parse_args()
    if args.limit is not None and args.limit < 0:
        raise ValueError("--limit cannot be negative")
    rows = write_formatted_workbook(
        args.raw.resolve(), args.template.resolve(), args.output.resolve(), args.limit
    )
    print(f"Wrote {rows} tender rows to {args.output.resolve()}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

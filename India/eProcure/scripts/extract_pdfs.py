"""
extract_pdfs.py  —  run EasyOCR + rule-based parsing on local PDF files
========================================================================
Use this to process PDFs you already have on disk without Gemini.
"""

import argparse
import csv
import json
import logging
import os
import sys

from common import (
    COLUMNS,
    _looks_like_table_page,
    ocr_image_bytes,
    pdf_bytes_to_text_pages,
    pdf_path_to_images,
    parse_items_from_ocr_text,
)


def extract_pdf(
    pdf_path: str,
    dpi: int = 450,
    stop_after_first_item_section: bool = True,
    max_consecutive_non_item_pages: int = 2,
    min_pages_after_first_item: int = 2,
) -> list[dict]:
    """
    Full pipeline for one local PDF file:
      1. Rasterise all pages to JPEG bytes
      2. EasyOCR each page
      3. Rule-based parser extracts item rows into COLUMNS

    Early-stop logic:
    - once item pages start appearing, keep scanning a few more pages
    - stop only after `max_consecutive_non_item_pages` empty/non-item pages
      and only after at least `min_pages_after_first_item` pages have been checked
      beyond the first item page
    """
    logging.info(f"\nProcessing: {pdf_path}")

    notice_meta = {
        "title": "",   # do not take title from PDF filename
        "refNo": "",
        "date": "",
        "org": "",
        "link": "",
        "query_text": "",
    }

    try:
        with open(pdf_path, "rb") as f:
            pdf_bytes = f.read()
        text_pages = pdf_bytes_to_text_pages(pdf_bytes)
        pages = pdf_path_to_images(pdf_path, dpi=dpi)
    except Exception as e:
        logging.error(f"  Could not rasterise PDF: {e}")
        return []

    logging.info(f"  {len(pages)} page(s) to process.")
    all_records = []

    first_item_page = None
    consecutive_non_item_pages = 0

    for i, jpeg_bytes in enumerate(pages, start=1):
        logging.info(f"  Page {i}/{len(pages)} — EasyOCR…")

        try:
            ocr_text = ocr_image_bytes(jpeg_bytes, page_num=i, total_pages=len(pages))
            if not ocr_text.strip():
                logging.info(f"  Page {i}: OCR returned empty text — skipping.")
                records = []
            else:
                logging.debug(f"  OCR ({len(ocr_text)} chars):\n{ocr_text[:4000]}")
                records = parse_items_from_ocr_text(
                    ocr_text=ocr_text,
                    notice_meta=notice_meta,
                    page_num=i,
                )
        except Exception as e:
            logging.error(f"  EasyOCR failed on page {i}: {e}")
            records = []

        if records:
            all_records.extend(records)
            consecutive_non_item_pages = 0

            if first_item_page is None:
                first_item_page = i

            if not notice_meta["org"]:
                notice_meta["org"] = records[0].get("buyer", "")
        else:
            if first_item_page is not None:
                consecutive_non_item_pages += 1

        if stop_after_first_item_section and first_item_page is not None:
            pages_checked_after_first_item = i - first_item_page

            if (
                pages_checked_after_first_item >= min_pages_after_first_item
                and consecutive_non_item_pages >= max_consecutive_non_item_pages
            ):
                logging.info(
                    "  Item section already extracted; "
                    f"stopping after {consecutive_non_item_pages} consecutive non-item page(s)."
                )
                break

    logging.info(f"  Total items extracted from {os.path.basename(pdf_path)}: {len(all_records)}")
    return all_records


def save_csv(records: list[dict], path: str):
    with open(path, "w", newline="", encoding="utf-8-sig") as f:
        w = csv.DictWriter(f, fieldnames=COLUMNS, extrasaction="ignore")
        w.writeheader()
        w.writerows(records)
    print(f"✓ CSV  → {path}  ({len(records)} rows)")


def save_json(records: list[dict], path: str):
    with open(path, "w", encoding="utf-8") as f:
        json.dump(records, f, ensure_ascii=False, indent=2)
    print(f"✓ JSON → {path}  ({len(records)} records)")


def main():
    parser = argparse.ArgumentParser(
        description="Extract tender item data from local PDFs using EasyOCR only.",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    parser.add_argument("pdfs", nargs="+", help="One or more PDF file paths to process")
    parser.add_argument("--dpi", type=int, default=450, help="PDF rasterisation DPI")
    parser.add_argument("--output-dir", default="output", help="Output directory for CSV + JSON")
    parser.add_argument("--no-early-stop", action="store_true", help="Scan all pages even after item pages are extracted")
    parser.add_argument("--verbose", action="store_true")
    args = parser.parse_args()

    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s [%(levelname)s] %(message)s",
        datefmt="%H:%M:%S",
    )

    all_records = []
    for pdf_path in args.pdfs:
        if not os.path.isfile(pdf_path):
            logging.warning(f"File not found — skipping: {pdf_path}")
            continue
        all_records.extend(
            extract_pdf(
                pdf_path,
                dpi=args.dpi,
                stop_after_first_item_section=not args.no_early_stop,
                max_consecutive_non_item_pages=2,
                min_pages_after_first_item=2,
            )
        )
    if not all_records:
        print("No records extracted. Try higher DPI or --verbose.")
        sys.exit(0)

    os.makedirs(args.output_dir, exist_ok=True)
    save_csv(all_records, os.path.join(args.output_dir, "tenders.csv"))
    save_json(all_records, os.path.join(args.output_dir, "tenders.json"))
    print(f"\n✓ Done — {len(all_records)} total line items.")


if __name__ == "__main__":
    main()

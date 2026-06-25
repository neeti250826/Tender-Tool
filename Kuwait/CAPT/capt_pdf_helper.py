from __future__ import annotations

import argparse
import json
import re
import subprocess
from pathlib import Path

import fitz


def parse_pages(raw: str) -> list[int]:
    pages: list[int] = []
    for part in raw.split(","):
        token = part.strip()
        if not token:
            continue
        if "-" in token:
            start_raw, end_raw = token.split("-", 1)
            start = int(start_raw)
            end = int(end_raw)
            if end < start:
                raise ValueError(f"Invalid page range: {token}")
            pages.extend(range(start, end + 1))
        else:
            pages.append(int(token))
    return sorted(set(pages))


DEFAULT_TESSERACT_PATH = Path(r"C:\Program Files\Tesseract-OCR\tesseract.exe")

MEETING_RE = re.compile(r"202\d/\d+")
DATE_RE = re.compile(r"20\d{2}/\d{2}/\d{2}")


def normalize_whitespace(text: str) -> str:
    return " ".join(text.split())


def extract_pdf_summary(pdf_path: Path, max_scan_pages: int = 4) -> dict[str, str]:
    doc = fitz.open(pdf_path)
    pages_to_scan = min(len(doc), max_scan_pages)
    snippets: list[str] = []
    for index in range(pages_to_scan):
        snippets.append(doc[index].get_text("text"))
    combined = "\n".join(snippets)
    normalized = normalize_whitespace(combined)

    publication_date = ""
    meeting_number = ""

    publication_marker = "تاريخ النشر"
    publication_index = normalized.find(publication_marker)
    if publication_index != -1:
        publication_window = normalized[publication_index : publication_index + 120]
        publication_match = DATE_RE.search(publication_window)
        if publication_match:
            publication_date = publication_match.group(0)
    if not publication_date:
        publication_match = DATE_RE.search(normalized)
        if publication_match:
            publication_date = publication_match.group(0)

    meeting_marker = "اجتماع رقم"
    meeting_index = normalized.find(meeting_marker)
    if meeting_index != -1:
        meeting_window = normalized[meeting_index : meeting_index + 60]
        meeting_match = MEETING_RE.search(meeting_window)
        if meeting_match:
            meeting_number = meeting_match.group(0)
    if not meeting_number:
        meeting_match = MEETING_RE.search(normalized)
        if meeting_match:
            meeting_number = meeting_match.group(0)

    return {
        "pdf": str(pdf_path),
        "pages": str(len(doc)),
        "meeting_number": meeting_number,
        "publication_date": publication_date,
    }


def render_pages(
    pdf_path: Path,
    output_dir: Path,
    pages: list[int],
    zoom: float,
    run_ocr: bool,
    tesseract_path: Path,
    ocr_lang: str,
    tessdata_dir: Path | None,
    grep_terms: list[str],
) -> None:
    output_dir.mkdir(parents=True, exist_ok=True)
    doc = fitz.open(pdf_path)
    matrix = fitz.Matrix(zoom, zoom)
    grep_terms_lower = [term.lower() for term in grep_terms]
    max_page = len(doc)
    valid_pages = [page_no for page_no in pages if 1 <= page_no <= max_page]
    skipped_pages = [page_no for page_no in pages if page_no < 1 or page_no > max_page]
    if skipped_pages:
        print(
            f"warning: skipped out-of-range pages for {pdf_path.name}: "
            f"{', '.join(str(page_no) for page_no in skipped_pages)} "
            f"(document has {max_page} pages)"
        )
    for page_no in valid_pages:
        page = doc[page_no - 1]
        png_path = output_dir / f"page_{page_no}.png"
        text_path = output_dir / f"page_{page_no}.txt"
        pix = page.get_pixmap(matrix=matrix, alpha=False)
        pix.save(png_path)
        extracted_text = page.get_text("text")
        text_path.write_text(extracted_text, encoding="utf-8")
        ocr_text = ""
        if run_ocr:
            ocr_text = run_tesseract_ocr(png_path, tesseract_path, ocr_lang, tessdata_dir)
            (output_dir / f"page_{page_no}.ocr.txt").write_text(ocr_text, encoding="utf-8")
        if grep_terms_lower:
            combined = f"{extracted_text}\n{ocr_text}".lower()
            matched_terms = [term for term in grep_terms if term.lower() in combined]
            if matched_terms:
                safe_terms = json.dumps(matched_terms, ensure_ascii=True)
                print(f"matches page {page_no}: {safe_terms}")
        print(f"rendered {png_path}")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Render selected CAPT PDF pages to PNG and extracted text for manual verification."
    )
    parser.add_argument("pdf", type=Path, help="Path to a local CAPT PDF file")
    parser.add_argument(
        "--pages",
        required=True,
        help="Comma-separated page list or ranges, e.g. 32-40 or 20,33,34",
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=Path("Kuwait") / "CAPT" / "pdf_inspection",
        help="Directory where rendered PNGs and text files will be written",
    )
    parser.add_argument("--zoom", type=float, default=2.0, help="Render zoom factor")
    parser.add_argument(
        "--ocr",
        action="store_true",
        help="Run Tesseract OCR on each rendered PNG and write page_<n>.ocr.txt files",
    )
    parser.add_argument(
        "--tesseract-path",
        type=Path,
        default=DEFAULT_TESSERACT_PATH,
        help="Path to the local tesseract executable",
    )
    parser.add_argument(
        "--ocr-lang",
        default="eng",
        help="Tesseract language code to use for OCR, e.g. eng",
    )
    parser.add_argument(
        "--tessdata-dir",
        type=Path,
        default=None,
        help="Optional directory containing Tesseract traineddata files",
    )
    parser.add_argument(
        "--grep",
        nargs="+",
        default=[],
        help="Optional search terms to match against extracted text and OCR text",
    )
    parser.add_argument(
        "--summary",
        action="store_true",
        help="Print extracted PDF metadata summary (page count, meeting number, publication date)",
    )
    parser.add_argument(
        "--summary-only",
        action="store_true",
        help="Print extracted PDF metadata summary and skip page rendering",
    )
    return parser


def run_tesseract_ocr(
    image_path: Path,
    tesseract_path: Path,
    ocr_lang: str,
    tessdata_dir: Path | None,
) -> str:
    if not tesseract_path.exists():
        raise FileNotFoundError(f"Tesseract executable not found at {tesseract_path}")
    command = [
        str(tesseract_path),
        str(image_path),
        "stdout",
        "-l",
        ocr_lang,
    ]
    if tessdata_dir is not None:
        command.extend(["--tessdata-dir", str(tessdata_dir)])
    result = subprocess.run(command, capture_output=True, check=True)
    return result.stdout.decode("utf-8", errors="ignore")


def main() -> None:
    parser = build_parser()
    args = parser.parse_args()
    if args.summary or args.summary_only:
        summary = extract_pdf_summary(args.pdf.resolve())
        print(json.dumps(summary, ensure_ascii=True))
        if args.summary_only:
            return
    pages = parse_pages(args.pages)
    render_pages(
        args.pdf.resolve(),
        args.output_dir.resolve(),
        pages,
        args.zoom,
        args.ocr,
        args.tesseract_path.resolve(),
        args.ocr_lang,
        args.tessdata_dir.resolve() if args.tessdata_dir else None,
        args.grep,
    )


if __name__ == "__main__":
    main()

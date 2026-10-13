"""OCR the MTI Ayub Teaching Hospital evaluation (scanned sideways) -> ocr/ayub_text.json {page: text}."""
import fitz, json, subprocess
d = fitz.open("ayub_29398.pdf")
out = {}
for i, pg in enumerate(d):
    p = f"ocr/ayub_page.png"
    pg.get_pixmap(matrix=fitz.Matrix(250 / 72, 250 / 72).prerotate(270)).save(p)
    out[i + 1] = subprocess.run([r"C:/Program Files/Tesseract-OCR/tesseract.exe", p, "-", "--psm", "6"],
                                capture_output=True, text=True, encoding="utf8").stdout
    print(i + 1, len(out[i + 1]), out[i + 1][:80].replace("\n", " "), flush=True)
json.dump(out, open("ocr/ayub_text.json", "w", encoding="utf8"), ensure_ascii=False)

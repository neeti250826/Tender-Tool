"""Text for every federal BER: PDF text layer if present, else Tesseract OCR (auto-rotation via OSD) -> ber_text.json."""
import fitz, glob, json, os, subprocess
TESS = r"C:/Program Files/Tesseract-OCR/tesseract.exe"
out = {}
for f in sorted(glob.glob("ber/*.pdf")):
    d = fitz.open(f)
    txt = "\n".join(p.get_text() for p in d)
    if len(txt.strip()) < 200:
        parts = []
        for i, p in enumerate(d):
            png = "ber/_tmp.png"
            p.get_pixmap(dpi=300).save(png)
            osd = subprocess.run([TESS, png, "-", "--psm", "0"], capture_output=True, text=True, encoding="utf8").stdout
            rot = int((([l for l in osd.splitlines() if l.startswith("Rotate:")] or ["Rotate: 0"])[0]).split(":")[1])
            if rot:
                p.get_pixmap(matrix=fitz.Matrix(300 / 72, 300 / 72).prerotate(rot)).save(png)
            parts.append(subprocess.run([TESS, png, "-", "--psm", "6"], capture_output=True, text=True, encoding="utf8").stdout)
        txt, src = "\n".join(parts), "ocr"
    else:
        src = "text"
    out[os.path.basename(f)[:-4]] = {"src": src, "text": txt}
    print(os.path.basename(f), src, len(txt), flush=True)
json.dump(out, open("ber_text.json", "w", encoding="utf8"), ensure_ascii=False, indent=0)

"""Download EPMS evaluation reports for medical-related federal evaluations -> federal/ber/<EVL>.pdf, + meta CSV."""
import csv, html, re, time, urllib.request
KW = r"surgical|suture|disposable|medical (equipment|device|stores|supplies|items)|catheter|stent|cardiac|cath ?lab|orthop|implant|endoscop|laparoscop|ventilator|anaesth|anesth|hospital|pims|polyclinic|medic|electrosurg|defibrill|monitoring equipment|ecg|suction|ot table|c-arm|neurolog"
R = [r for r in csv.DictReader(open("epms_evaluations.csv", encoding="utf-8-sig")) if re.search(KW, r["title"] + " " + r["text"], re.I)]


def get(url, binary=False):
    for a in range(4):
        try:
            b = urllib.request.urlopen(urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"}), timeout=180).read()
            return b if binary else b.decode("utf8", "ignore")
        except Exception:
            time.sleep(5 * (a + 1))
    return b"" if binary else ""


meta = []
for r in R:
    e = r["evaluation_no"]
    s = get(f"https://epms.ppra.gov.pk/public/evaluations/evaluation-details/{e}")
    t = re.sub(r"\s+", " ", html.unescape(re.sub(r"<[^>]+>", " | ", re.sub(r"<(script|style)[^>]*>.*?</\1>", "", s, flags=re.S))))
    g = lambda k: (re.search(re.escape(k) + r" \| ([^|]+)", t) or [None, ""])[1].strip()
    pdfs = re.findall(r'href="(/pdf\?file=[^"]+)"', s)
    n = 0
    for i, p in enumerate(pdfs):
        b = get("https://epms.ppra.gov.pk" + html.unescape(p), binary=True)
        if b[:4] == b"%PDF":
            open(f"ber/{e}{'_' + str(i) if i else ''}.pdf", "wb").write(b)
            n += 1
    meta.append({"evaluation_no": e, "title": r["title"], "organization": g("Organization Name"), "office": g("Office Name"), "city": g("City"),
                 "evaluation_type": g("Evaluation Type"), "bids": g("Number of Bids Received"), "lowest_bidder": g("Lowest Bidder"),
                 "published": g("Evaluation Published Date"), "advertised": g("Tender Advertisement Date"), "tender_no": r["tender_no"], "pdfs": n})
    print(e, n, g("Evaluation Type"), r["title"][:60], flush=True)
    time.sleep(1)
with open("federal_medical_evaluations.csv", "w", newline="", encoding="utf-8-sig") as f:
    w = csv.DictWriter(f, fieldnames=list(meta[0].keys()))
    w.writeheader()
    w.writerows(meta)
print("evaluations", len(meta), "with pdf", sum(1 for m in meta if m["pdfs"]))

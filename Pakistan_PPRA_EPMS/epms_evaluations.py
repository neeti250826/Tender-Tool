"""PPRA EPMS federal evaluation results (BER listings) -> epms_evaluations.csv; one row per evaluation, with its document links."""
import csv, html, re, time, urllib.request

BASE = "https://epms.ppra.gov.pk/public/evaluations"


def get(url):
    for a in range(4):
        try:
            return urllib.request.urlopen(urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"}), timeout=180).read().decode("utf8", "ignore")
        except Exception:
            time.sleep(5 * (a + 1))
    return ""


def clean(x):
    return re.sub(r"\s+", " ", html.unescape(re.sub(r"<[^>]+>", " | ", x))).strip(" |")


rows, page, last = [], 1, 1
while page <= last:
    s = get(f"{BASE}?page={page}")
    m = re.search(r"Page \d+ of ([\d,]+)", s)
    last = int(m.group(1).replace(",", "")) if m else last
    body = s[s.find("<tbody"):s.find("</tbody>")]
    parts = body.split('<tr class="cb-rt-main"')[1:]
    for p in parts:
        ev = re.search(r"(EVL\d+)", p)
        ts = re.search(r"(TS\d+\w?)", p)
        title = re.search(r'data-label="Evaluation Details">\s*<span>\s*<strong>(.*?)</strong>', p, re.S)
        txt = clean(p)
        hrefs = [h for h in re.findall(r'href="([^"]+)"', p) if not h.startswith("#")]
        rows.append({"evaluation_no": ev.group(1) if ev else "", "tender_no": ts.group(1) if ts else "",
                     "title": clean(title.group(1)) if title else "", "text": txt[:1500], "links": " ".join(sorted(set(hrefs)))})
    print(page, last, len(parts), flush=True)
    page += 1
    time.sleep(1)
with open("epms_evaluations.csv", "w", newline="", encoding="utf-8-sig") as f:
    w = csv.DictWriter(f, fieldnames=list(rows[0].keys()))
    w.writeheader()
    w.writerows(rows)
print("evaluations", len(rows))

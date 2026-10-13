"""PPRA EPMS public contracts register (federal) -> epms_contracts.csv (all pages; one row per contract)."""
import csv, html, re, time, urllib.request

BASE = "https://epms.ppra.gov.pk/public/contracts"


def get(url):
    for a in range(4):
        try:
            return urllib.request.urlopen(urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"}), timeout=120).read().decode("utf8", "ignore")
        except Exception:
            time.sleep(5 * (a + 1))
    return ""


def clean(x):
    return re.sub(r"\s+", " ", html.unescape(re.sub(r"<[^>]+>", " ", x))).strip()


rows, page = [], 1
while True:
    s = get(f"{BASE}?page={page}")
    body = s[s.find("<tbody>"):s.find("</tbody>")]
    trs = re.findall(r"<tr>(.*?)</tr>", body, re.S)
    for tr in trs:
        tds = re.findall(r"<td[^>]*>(.*?)</td>", tr, re.S)
        if len(tds) < 7:
            continue
        det = tds[2]
        strongs = [clean(x) for x in re.findall(r"<strong[^>]*>(.*?)</strong>", det, re.S)]
        winner = clean((re.findall(r"fa-award\"></i>(.*?)</small>", det, re.S) or [""])[0])
        badges = [clean(x) for x in re.findall(r"badge[^>]*>(.*?)</small>", det, re.S)]
        links = re.findall(r"href=\"([^\"]+)\"", tds[6] + tds[7] if len(tds) > 7 else tds[6])
        rows.append({"contract_no": clean(tds[1]).replace("PPRA Contract No", "").strip(), "buyer": strongs[0] if strongs else "",
                     "title": strongs[1] if len(strongs) > 1 else "", "winner": winner, "tags": " | ".join(badges),
                     "organization": clean(tds[3]), "contract_value": clean(tds[4]), "advertise_date": clean(tds[5]),
                     "links": " ".join(links)})
    print(page, len(trs), flush=True)
    m = re.search(r"Page \d+ of ([\d,]+)", s)
    last = int(m.group(1).replace(",", "")) if m else page
    if page >= last or not trs:
        break
    page += 1
    time.sleep(1)
with open("epms_contracts.csv", "w", newline="", encoding="utf-8-sig") as f:
    w = csv.DictWriter(f, fieldnames=list(rows[0].keys()))
    w.writeheader()
    w.writerows(rows)
print("contracts", len(rows))

"""KPPRA evaluated tenders for selected KP health entities -> kppra_evaluated.csv (all pages, newest data kept)."""
import csv, html, re, time, urllib.parse, urllib.request
import json
ENT_ALL = dict(json.load(open(r"kppra_health_entities.json")))
ENT_OLD = {"30137": "Lady Reading Hospital", "30242": "Khyber Teaching Hospital", "29793": "Hayatabad Medical Complex",
       "30191": "MTI Ayub Teaching Hospital", "29901": "Mardan Medical Complex", "30187": "Institute of Kidney Disease",
       "29736": "Khalifa Gul Nawaz Teaching Hospital Bannu", "31419": "MTI Bannu", "30526": "MTI DHQ/MMM D.I.Khan", "31875": "MTI D.I.Khan",
       "30884": "Burns & Plastic Surgery Centre", "30885": "Burns & Trauma Centre", "29777": "DGHS KP", "29598": "Health Department KP",
       "31028": "Bacha Khan Medical Complex Swabi", "30114": "King Abdullah Teaching Hospital Mansehra", "30156": "Benazir Bhutto Shaheed TH Abbottabad",
       "31640": "Khyber Institute of Child Health"}
ENT = {k: v for k, v in ENT_ALL.items() if not __import__("re").search(r"hydro|hpp|agricult|building division|judge|tribunal|revenue|social welfare|youth|forensic|technical|polytechnic|irrigation|public health engineering|education|e-governance|fisher|hayatabad, peshawar$", v, __import__("re").I)}
BASE = "http://kppra.gov.pk/kppra/"


def get(url):
    for a in range(4):
        try:
            return urllib.request.urlopen(urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"}), timeout=90).read().decode("utf8", "ignore")
        except Exception:
            time.sleep(3 * (a + 1))
    return ""


def rows(s):
    out = []
    for r in re.findall(r"<tr>(.*?)</tr>", s, re.S):
        tds = [re.sub(r"\s+", " ", html.unescape(re.sub(r"<[^>]+>", "", t))).strip() for t in re.findall(r"<td[^>]*>(.*?)</td>", r, re.S)]
        docs = re.findall(r"processtender_documents.php\?tender_id=(\d+)", r)
        notice = re.findall(r"force_download.php\?file=([^\"']+)", r)
        if len(tds) >= 5 and docs:
            out.append({"tender_no": tds[0], "entity": tds[1], "description": tds[2], "advertised": tds[3], "closing": tds[4],
                        "doc_tender_id": docs[0], "notice_file": notice[0] if notice else ""})
    return out


all_rows = []
for eid, name in ENT.items():
    p, got = 1, 0
    while True:
        s = get(BASE + "evaluated_tenders.php?" + urllib.parse.urlencode({"tender_ref": "", "fromDate": "", "toDate": "", "dpart_id": eid, "tender_type_id": "1",
                                                                          "sort_field": "tender_start_date", "sort_order": "DESC", "search": "", "p": p}))
        rs = rows(s)
        for r in rs:
            r["entity_id"], r["entity_short"] = eid, name
        all_rows += rs
        got += len(rs)
        if len(rs) < 25:
            break
        p += 1
        time.sleep(0.5)
    print(f"{name:45} {got}", flush=True)
seen, uniq = set(), []
for r in all_rows:
    if r["doc_tender_id"] not in seen:
        seen.add(r["doc_tender_id"])
        uniq.append(r)
with open("kppra_evaluated.csv", "w", newline="", encoding="utf-8-sig") as f:
    w = csv.DictWriter(f, fieldnames=list(uniq[0].keys()))
    w.writeheader()
    w.writerows(uniq)
print("total", len(uniq))

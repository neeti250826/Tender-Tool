"""
Cached batch translation via translate.googleapis.com/translate_a/single (client=gtx, no key).
Lines are sent in newline-joined batches (<= ~3500 chars) and cached in translation_cache.sqlite,
so re-runs only translate new strings.

    from translate import translate_many
    en = translate_many(["Kalp pili çift odacıklı", ...], src="tr")   # -> list[str]
"""
import json, os, sqlite3, time, urllib.parse, urllib.request

DB = os.path.join(os.path.dirname(os.path.abspath(__file__)), "translation_cache.sqlite")
URL = "https://translate.googleapis.com/translate_a/single"
MAX_CHARS = 3500


def _db():
    c = sqlite3.connect(DB)
    c.execute("CREATE TABLE IF NOT EXISTS t (src TEXT, text TEXT, en TEXT, PRIMARY KEY (src, text))")
    return c


def _call(lines, src):
    q = "\n".join(lines)
    data = urllib.parse.urlencode({"client": "gtx", "sl": src, "tl": "en", "dt": "t", "q": q}).encode()
    req = urllib.request.Request(URL, data=data, headers={"User-Agent": "Mozilla/5.0",
                                                          "Content-Type": "application/x-www-form-urlencoded;charset=UTF-8"})
    for attempt in range(5):
        try:
            with urllib.request.urlopen(req, timeout=60) as r:
                d = json.loads(r.read().decode("utf-8"))
            out = "".join(seg[0] for seg in d[0] if seg and seg[0])
            parts = out.split("\n")
            if len(parts) == len(lines):
                return [p.strip() for p in parts]
            # line count drifted (rare): fall back to one-by-one
            return [_call([ln], src)[0] for ln in lines] if len(lines) > 1 else [out.strip()]
        except Exception:
            time.sleep(2 * (attempt + 1))
    return [""] * len(lines)


def translate_many(texts, src="tr", pace=0.3, verbose=True):
    con = _db()
    uniq = sorted({(t or "").strip() for t in texts if (t or "").strip()})
    have = {}
    for i in range(0, len(uniq), 500):
        chunk = uniq[i:i + 500]
        q = "SELECT text, en FROM t WHERE src=? AND text IN (%s)" % ",".join("?" * len(chunk))
        have.update(dict(con.execute(q, [src, *chunk]).fetchall()))
    todo = [u for u in uniq if u not in have]
    batch, size, done = [], 0, 0
    for u in todo + [None]:
        if u is not None and (size + len(u) + 1 <= MAX_CHARS or not batch):
            batch.append(u.replace("\n", " "))
            size += len(u) + 1
            continue
        if batch:
            res = _call(batch, src)
            con.executemany("INSERT OR REPLACE INTO t VALUES (?,?,?)", [(src, b, e) for b, e in zip(batch, res)])
            con.commit()
            have.update(zip(batch, res))
            done += len(batch)
            if verbose and done % 2000 < len(batch):
                print(f"  translated {done}/{len(todo)}", flush=True)
            time.sleep(pace)
        batch, size = ([u.replace("\n", " ")], len(u) + 1) if u is not None else ([], 0)
    con.close()
    return [have.get((t or "").strip().replace("\n", " "), have.get((t or "").strip(), "")) for t in texts]


if __name__ == "__main__":
    print(translate_many(["İlaç salınımlı koroner stent", "Kalp pili çift odacıklı", "Cerrahi sütür emilebilir"]))

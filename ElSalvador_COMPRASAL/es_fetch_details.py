"""Fetch COMPRASAL process detail + award report for every tagged ES process (cached to es_details/)."""
import concurrent.futures as cf
import json
import os
import sys
import time

import pandas as pd
import requests

HERE = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(HERE, "es_details")
os.makedirs(OUT, exist_ok=True)
B = "https://www.comprasal.gob.sv/api/v1/publico"
H = {"User-Agent": "Mozilla/5.0", "Accept": "application/json"}


def get(url, path):
    if os.path.exists(path):
        return
    for i in range(4):
        try:
            r = requests.get(url, headers=H, timeout=90)
            if r.status_code == 200:
                open(path, "w", encoding="utf-8").write(r.text)
                return
        except requests.RequestException:
            pass
        time.sleep(3 * (i + 1))


def job(row):
    pid, aid = row
    get(f"{B}/obtener/detalle/procesos/publicos/{pid}", os.path.join(OUT, f"proc_{pid}.json"))
    get(f"{B}/obtener/informe-adjudicacion/{aid}", os.path.join(OUT, f"inf_{aid}.json"))


if __name__ == "__main__":
    src = sys.argv[1] if len(sys.argv) > 1 else "es_tagged.pkl"
    m = pd.read_pickle(os.path.join(HERE, src))
    jobs = list(m.sort_values("award_id").drop_duplicates("proc_id")[["proc_id", "award_id"]].itertuples(index=False, name=None))
    with cf.ThreadPoolExecutor(4) as ex:
        for i, _ in enumerate(ex.map(job, jobs), 1):
            if i % 50 == 0:
                print(i, "/", len(jobs), flush=True)
    print("done", len(jobs))

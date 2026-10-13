"""Read only the par_memberOf sheet (unit -> institution) from an HC1 xlsx, streaming."""
import os
import sys
import time

import openpyxl
import pandas as pd

HERE = os.path.dirname(os.path.abspath(__file__))
for f in sys.argv[1:]:
    out = os.path.join(HERE, "hn_pkl", f"{f}_member.pkl")
    if os.path.exists(out):
        continue
    t = time.time()
    wb = openpyxl.load_workbook(os.path.join(HERE, "hn_raw", f + ".xlsx"), read_only=True)
    ws = wb["par_memberOf"]
    rows = ws.iter_rows(values_only=True)
    hdr = next(rows)
    df = pd.DataFrame(list(rows), columns=hdr)
    pd.to_pickle(df, out)
    print(f, len(df), f"{time.time() - t:.0f}s", flush=True)

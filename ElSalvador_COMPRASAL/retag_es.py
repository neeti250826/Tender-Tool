"""Re-tag COMPRASAL award rows with the current tagger (writes es_tagged.pkl)."""
import os
import sys

import pandas as pd

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
from tagger import tag  # noqa: E402

df = pd.read_pickle(os.path.join(HERE, "es_all_awards.pkl"))
procs = df.drop_duplicates("proc_id")[["proc_id", "nombre", "inst"]]
res = [dict(proc_id=r.proc_id, **t) for r in procs.itertuples() if (t := tag(title=r.nombre, buyer=r.inst))]
m = df.merge(pd.DataFrame(res), on="proc_id")
m.to_pickle(os.path.join(HERE, "es_tagged.pkl"))
missing = [p for p in m.proc_id.unique() if not os.path.exists(os.path.join(HERE, "es_details", f"proc_{p}.json"))]
print(m.proc_id.nunique(), "ES processes tagged;", len(missing), "without cached detail")

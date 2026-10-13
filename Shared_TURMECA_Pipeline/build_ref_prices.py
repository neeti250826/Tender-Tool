"""
Reference unit prices (USD) per taxonomy Device Category, from Pakistan KP bid evaluation reports:
  * Govt. MCC BERs (drugs + medical devices / surgical disposables) - pakistan/kp_mcc_items.csv
  * DGHS rate-contracting BERs (equipment, instruments, hospital supplies) - pakistan/kp_ber_bids.csv (winners)
Each winning item is mapped with the same vocab layer as the tenders (line description only).
Price = the winning unit rate (PKR) / FX. Category reference = median over mapped items; p25/p75 and n kept
so thin or wide categories can be judged. Categories without a mapped item get no price (KSA then reports
volume and share only - nothing is guessed).
Output: turmeca/ref_prices.csv, turmeca/ref_price_items.csv
"""
import csv, os, statistics, sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
from vocab_rules import Vocab  # noqa: E402

PKR_PER_USD = 276.984011  # open.er-api.com, 2026-10-01 (PKR has traded ~277-285/USD since 2024)
FX_NOTE = "PKR/USD 276.98 spot 2026-10-01 applied to FY2024-25..2026-27"


def read(p):
    with open(p, encoding="utf-8-sig") as f:
        return list(csv.DictReader(f))


def main():
    v = Vocab()
    obs = []
    for r in read(os.path.join(HERE, "pakistan", "kp_mcc_items.csv")):
        rate = float(r["winner_rate_pkr"] or 0)
        if rate <= 0:
            continue
        m = v.product(r["description"])  # own text only: MCC numbers are reused for different items across years
        if m:
            obs.append({"source": "KP Govt MCC BER", "fy": r["fy"], "ref": r["mcc_ref"], "description": r["description"],
                        "winner": r["winner_firm"], "make": "", "rate_pkr": rate, "usd": rate / PKR_PER_USD, "bids": r["bids"], **m})
    for r in read(os.path.join(HERE, "pakistan", "kp_ber_bids.csv")):
        if not r["winner"]:
            continue
        rate = float(r["quoted_pkr"] or 0)
        if rate <= 0:
            continue
        m = v.product(r["item"] or r["item_raw"])
        if m:
            obs.append({"source": "KP DGHS equipment BER", "fy": r["fy"], "ref": r["block"], "description": r["item_raw"],
                        "winner": r["firm"], "make": r["make"], "rate_pkr": rate, "usd": rate / PKR_PER_USD, "bids": r["bids_on_item"], **m})
    # de-duplicate identical (source, fy, description, rate) - some reports repeat tables
    seen, uniq = set(), []
    for o in obs:
        k = (o["source"], o["fy"], o["description"].lower(), round(o["rate_pkr"], 2))
        if k not in seen:
            seen.add(k)
            uniq.append(o)
    cols = ["product_category", "sub_ou", "ou", "source", "fy", "ref", "description", "winner", "make", "rate_pkr", "usd", "bids"]
    with open(os.path.join(HERE, "ref_price_items.csv"), "w", newline="", encoding="utf-8-sig") as f:
        w = csv.DictWriter(f, fieldnames=cols, extrasaction="ignore")
        w.writeheader()
        w.writerows(sorted(uniq, key=lambda o: (o["product_category"], o["usd"])))
    by = {}
    for o in uniq:
        by.setdefault(o["product_category"], []).append(o)
    rows = []
    for pc, os_ in sorted(by.items()):
        u = sorted(o["usd"] for o in os_)
        q = statistics.quantiles(u, n=4) if len(u) >= 4 else [u[0], statistics.median(u), u[-1]]
        rows.append({"product_category": pc, "sub_ou": os_[0]["sub_ou"], "ou": os_[0]["ou"], "unit_price_usd": round(statistics.median(u), 4),
                     "p25_usd": round(q[0], 4), "p75_usd": round(q[-1], 4), "n_obs": len(u),
                     "fys": ", ".join(sorted({o["fy"] for o in os_})), "source": "; ".join(sorted({o["source"] for o in os_})),
                     "basis": "median winning unit rate", "fx": FX_NOTE})
    with open(os.path.join(HERE, "ref_prices.csv"), "w", newline="", encoding="utf-8-sig") as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0].keys()))
        w.writeheader()
        w.writerows(rows)
    print("mapped price observations", len(uniq), "categories priced", len(rows))
    for r in rows:
        print(f"  {r['product_category'][:45]:45} n={r['n_obs']:<4} median ${r['unit_price_usd']:<10} p25-p75 ${r['p25_usd']}-{r['p75_usd']}")


if __name__ == "__main__":
    main()

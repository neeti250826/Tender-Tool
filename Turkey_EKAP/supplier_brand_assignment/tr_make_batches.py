"""Select the IVD-relevant suppliers worth researching and split them into batches."""
import json, sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from tr_brand_rules import detect

BASE = Path(r"<WORKSPACE>")
MAP = BASE / "mapping"
BATCH_DIR = MAP / "tr_batches"
TOP_N = 500
BATCH = 20


def main():
    prof = json.loads((MAP / "tr_supplier_profile.json").read_text(encoding="utf-8"))
    rules, research = {}, []

    for p in prof:
        d = detect(p["supplier_name"], p["supplier_name_en"])
        if d and d[0]:
            rules[p["supplier_name"]] = {
                "player": d[0], "group": d[1], "is_ivd": d[2], "basis": d[3],
                "confidence": "High",
            }
            continue
        collision = d[3] if d else None
        # IVD-relevant enough to be worth researching
        if p["ivd_score"] >= 0.25 or p["seg_rows"] > 0 or collision:
            p2 = dict(p)
            p2["collision"] = collision
            research.append(p2)

    research.sort(key=lambda x: (-x["rows"], -x["value"]))
    research = research[:TOP_N]

    BATCH_DIR.mkdir(exist_ok=True)
    for f in BATCH_DIR.glob("*.json"):
        f.unlink()

    n = 0
    for i in range(0, len(research), BATCH):
        chunk = research[i:i + BATCH]
        payload = [{
            "supplier_name": c["supplier_name"],
            "supplier_name_en": c["supplier_name_en"],
            "tender_rows": c["rows"],
            "ivd_segments_seen": c["ivd_segments"],
            "roche_segments_seen": c["segments"],
            "sample_items": c["top_items"][:6],
            "name_collision_note": c["collision"],
        } for c in chunk]
        n += 1
        (BATCH_DIR / f"batch_{n:02d}.json").write_text(
            json.dumps(payload, ensure_ascii=False, indent=1), encoding="utf-8")

    (MAP / "tr_rule_assigned.json").write_text(
        json.dumps(rules, ensure_ascii=False, indent=1), encoding="utf-8")
    print("rule-assigned:", len(rules))
    print("to research:", len(research), "in", n, "batches")
    print("research rows cover:", sum(c["rows"] for c in research))


if __name__ == "__main__":
    main()

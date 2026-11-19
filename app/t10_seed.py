"""Import known SH T10 fixture metadata into the real match database.

A fixture snapshot is NOT a licensed live score feed. Never manufacture scores,
results, toss outcomes or a LIVE state from prediction data.
"""
import datetime
import json
import os

SNAPSHOT = os.path.join(os.path.dirname(__file__), "data", "abu_dhabi_t10_2026_11_19_prematch.json")
WHO = {"actor": "sh-fixture-seed", "role": "admin", "user_id": None}

def seed(db_fn):
    import api_v1
    if not os.path.isfile(SNAPSHOT):
        return {"skipped": "snapshot unavailable"}
    with open(SNAPSHOT, encoding="utf-8") as f:
        doc = json.load(f)
    c = db_fn()
    counts = {"created": 0, "duplicate": 0}
    try:
        if not c.execute("SELECT 1 FROM sqlite_master WHERE name='matches'").fetchone():
            return {"skipped": "match schema unavailable"}
        for m in doc.get("matches", []):
            ist = datetime.datetime.fromisoformat(doc["date"] + "T" + m["start_ist"]).replace(
                tzinfo=datetime.timezone(datetime.timedelta(hours=5, minutes=30)))
            start_utc = ist.astimezone(datetime.timezone.utc).isoformat()
            d = {"competition": doc["competition"], "season": "2026",
                 "home": m["home"], "away": m["away"], "start_utc": start_utc,
                 "match_no": str(m["match_no"]), "format": "T10",
                 "source": "SH owner fixture snapshot (schedule unverified)",
                 "data_origin": "imported"}
            result = api_v1.admin_match(c, WHO, d)
            counts["created" if result["status"] == "created" else "duplicate"] += 1
        c.commit()
        return counts
    except Exception:
        c.rollback()
        raise
    finally:
        c.close()

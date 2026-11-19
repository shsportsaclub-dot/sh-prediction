"""Run pending SH PREDICTION migrations from a shell: backup, verify, migrate, verify.
Usage: SH_PREDICTION_DB=/var/data/prediction.sqlite3 python tools/migrate.py [--check]"""
import json, os, sys
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "app"))
import main, schema, system
c = main.db()
if "--check" in sys.argv:
    print(json.dumps({"pending": schema.pending(c)})); sys.exit(0)
print(json.dumps(system.run(c, main.DB), indent=2)); c.commit()

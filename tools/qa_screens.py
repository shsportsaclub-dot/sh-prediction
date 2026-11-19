"""Browser QA: start a throw-away server, run the explicit migration, load clearly labelled DEMO data,
drive every viewer and admin screen in Chrome (phone + desktop), save screenshots and report console errors,
colour probes and viewer-isolation checks. Usage: python tools/qa_screens.py <out_dir>"""
import json, os, subprocess, sys, tempfile, time, urllib.request, urllib.error
from playwright.sync_api import sync_playwright

OUT = sys.argv[1] if len(sys.argv) > 1 else "docs/qa"
os.makedirs(OUT, exist_ok=True)
env = dict(os.environ, SH_PREDICTION_DB=tempfile.mkdtemp() + "/qa.sqlite3", SH_PREDICTION_ADMIN_TOKEN="qa-admin", PORT="8765", HOST="127.0.0.1")
srv = subprocess.Popen([sys.executable, "app/main.py"], env=env, stderr=subprocess.DEVNULL)
B = "http://127.0.0.1:8765"
A = {"X-Admin-Token": "qa-admin"}

def call(p, d=None, h=None, m=None, ok=True):
    r = urllib.request.Request(B + p, data=json.dumps(d).encode() if d is not None else None, headers=dict({"Content-Type": "application/json"}, **(h or {})), method=m)
    try:
        return json.loads(urllib.request.urlopen(r).read())
    except urllib.error.HTTPError as e:
        if ok:
            raise SystemExit("%s -> %s %s" % (p, e.code, e.read().decode()))
        return {"status": e.code}

report = {"shots": [], "console_errors": [], "checks": {}}
try:
    for _ in range(50):
        try:
            call("/health"); break
        except Exception:
            time.sleep(0.1)
    report["checks"]["viewer_before_migration"] = call("/api/v1/matches", ok=False).get("status")
    mig = call("/api/v1/admin/system/migrate", {"confirm": True}, A)
    report["checks"]["migration"] = {"status": mig["status"], "backup_ok": mig["backup"]["integrity"] == "ok"}
    ids = call("/api/v1/admin/demo-seed", {}, A)["demo_match_ids"]
    e = call("/api/v1/admin/experts", {"display_name": "Demo Tipster", "country": "India", "language_code": "te", "bio": "DEMO profile for screen review"}, A)["expert_id"]
    call("/api/v1/admin/experts/%d/verify" % e, {}, A)
    up = ids[-1]
    m = call("/api/v1/matches/%d" % up, h=A)
    p = call("/api/v1/predictions", {"match_id": up, "prediction_type": "winner", "predicted_team_id": m["home"]["id"], "confidence": 64, "explanation": "DEMO: stronger recent form", "expert_id": e}, A)
    call("/api/v1/admin/predictions/%d/publish" % p["prediction_id"], {"public_note": "DEMO published pick"}, A)
    for r in call("/api/v1/admin/predictions?dataset=demo&limit=100", h=A)["items"]:
        if r["status"] == "locked" and not r["published_at"] and r["match_id"] != up:
            call("/api/v1/admin/predictions/%d/publish" % r["id"], {}, A)
    call("/api/v1/admin/matches/%d" % up, {"weather": "DEMO: clear, 31°C", "pitch_report": "DEMO: dry surface, expected to help spin later"}, A)
    roles = ["wicket_keeper", "batter", "batter", "batter", "all_rounder", "all_rounder", "bowler", "bowler", "bowler", "bowler", "batter"]
    for t in (m["home"], m["away"]):
        pids = []
        for i, r in enumerate(roles):
            pid = call("/api/v1/admin/players", {"name": "Demo %s %d" % (t["short_code"] or "P", i + 1), "role": r}, A)["player_id"]
            pids.append(pid)
            call("/api/v1/admin/player-stats", {"player_id": pid, "format": "T10", "matches": 12, "runs": 90 + 25 * (i % 6), "batting_avg": 18, "strike_rate": 150,
                                                 "wickets": [0, 0, 0, 0, 6, 8, 14, 12, 10, 9, 0][i], "economy": 9.5, "source": "DEMO statistics"}, A)
        call("/api/v1/admin/matches/%d/playing-xi" % up, {"team_id": t["id"], "players": [{"player_id": x, "is_captain": k == 1, "is_keeper": k == 0} for k, x in enumerate(pids)]}, A)
    live = call("/api/v1/admin/matches", {"competition": "SH Demo League", "home": "Demo Royal Rhinos", "away": "Demo Eagle Eyes", "start_utc": "2026-01-10T14:00:00+00:00", "source": "SH demo generator", "data_origin": "demo", "match_no": "D6", "format": "T10", "venue": "Demo Oval"}, A)["match_id"]
    lm = call("/api/v1/matches/%d" % live, h=A)
    for ino, bat, tgt, pattern in ((1, lm["home"]["id"], None, [1, 4, 0, 6, 1, 1, "W", 2, 4, 0, 1, 6] * 5), (2, lm["away"]["id"], 101, [1, 0, 4, "W", 1, 2, 0, 6, 1, "W", 0, 1, 2, 4])):
        for i, x in enumerate(pattern, 1):
            b = {"match_id": live, "innings_no": ino, "batting_team_id": bat, "seq": i, "commentary": "DEMO ball"}
            if tgt:
                b["target"] = tgt
            b.update({"is_wicket": 1, "wicket_kind": "caught"} if x == "W" else {"runs_bat": x})
            if call("/api/v1/admin/ball-events", b, A)["innings_completed"]:
                break
    # viewer isolation probe (no login, no key)
    report["checks"]["viewer_admin_endpoints"] = sorted({call(pth, ok=False).get("status") for pth in
        ("/api/v1/admin/master-list", "/api/v1/admin/predictions", "/api/v1/admin/audit", "/api/v1/admin/dashboard")})
    report["checks"]["viewer_sees_factor_weights"] = "contribution" in json.dumps(call("/api/v1/matches/%d/signals" % up))
    with sync_playwright() as pw:
        br = pw.chromium.launch(executable_path="/usr/bin/google-chrome", args=["--no-sandbox"])
        def shoot(pg, name):
            f = "%s/%s.png" % (OUT, name); pg.screenshot(path=f, full_page=True); report["shots"].append(f)
        for theme, vp in (("dark", {"width": 390, "height": 844}), ("light", {"width": 1280, "height": 900})):
            ctx = br.new_context(viewport=vp, device_scale_factor=2 if vp["width"] < 500 else 1)
            pg = ctx.new_page()
            pg.on("console", lambda msg: report["console_errors"].append(msg.text) if msg.type == "error" else None)
            pg.on("pageerror", lambda ex: report["console_errors"].append(str(ex)))
            pg.goto(B + "/")
            pg.evaluate("th=>{localStorage.setItem('shp_theme',th);localStorage.setItem('shp_demo','1')}", theme)
            viewer = ["home", "matches", "match/%d/prediction" % up, "match/%d/fantasy" % up, "match/%d/xi" % up, "match/%d/weather" % up,
                      "match/%d/live" % live, "match/%d/graphs" % live, "match/%d/fow" % live, "match/%d/partnerships" % live,
                      "match/%d/scorecard" % live, "match/%d/commentary" % live, "match/%d/result" % ids[0], "match/%d/h2h" % ids[0],
                      "experts", "ai", "accuracy", "settings"] if theme == "dark" else ["home", "match/%d/prediction" % up, "match/%d/live" % live]
            for s in viewer:
                pg.goto(B + "/#/" + s); pg.reload(); pg.wait_for_timeout(700)
                shoot(pg, "viewer-%s-%s" % (theme, s.replace("/", "_")))
            if theme == "dark":
                pg.goto(B + "/#/assistant"); pg.wait_for_timeout(500)
                for q in ("What is the LBW law?", "DUB vs DEE head to head", "Who scored a century on Mars?"):
                    pg.fill("#aq", q); pg.click("#af button"); pg.wait_for_timeout(500)
                shoot(pg, "viewer-dark-assistant")
                admin_links = pg.evaluate("()=>[...document.querySelectorAll('a')].filter(a=>/admin|classic/i.test(a.href)).length")
                report["checks"]["viewer_admin_links"] = admin_links
                pg.goto(B + "/#/settings"); pg.wait_for_timeout(600); pg.select_option("#lang", "te"); pg.wait_for_timeout(900)
                pg.goto(B + "/#/match/%d/prediction" % up); pg.reload(); pg.wait_for_timeout(900)
                shoot(pg, "viewer-dark-telugu-prediction")
                report["checks"]["telugu_tabs"] = pg.eval_on_selector_all(".sub a", "e=>e.slice(0,6).map(x=>x.textContent)")
                pg.goto(B + "/#/settings"); pg.wait_for_timeout(500); pg.select_option("#lang", "en"); pg.wait_for_timeout(500)
            # admin panel
            pg.goto(B + "/admin-panel"); pg.wait_for_timeout(500)
            shoot(pg, "admin-%s-signin" % theme)
            pg.fill("#k", "qa-admin"); pg.click("#kgo"); pg.wait_for_timeout(900)
            sections = ["dashboard", "master", "matches", "results", "predictions", "experts", "import", "providers", "accuracy", "audit", "roles", "settings"] if theme == "dark" else ["dashboard", "master", "predictions"]
            for s in sections:
                pg.goto(B + "/admin-panel#" + s); pg.wait_for_timeout(900)
                if s == "master":
                    pg.select_option("#mds", "demo"); pg.wait_for_timeout(600)
                    report["checks"]["master_colours_%s" % theme] = pg.evaluate("""()=>[...document.querySelectorAll('table.ml tbody tr')].slice(0,4).map(tr=>[...tr.querySelectorAll('td')].map(td=>[...td.querySelectorAll('span')].length?[...td.querySelectorAll('span')].map(s=>s.textContent+':'+getComputedStyle(s).color).join(' '):td.textContent+':'+getComputedStyle(td).color))""")
                shoot(pg, "admin-%s-%s" % (theme, s))
            ctx.close()
        br.close()
finally:
    srv.terminate()
print(json.dumps(report, indent=1, ensure_ascii=False))

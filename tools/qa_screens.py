"""Start a throw-away server with DEMO data, drive every hub screen in Chrome, save screenshots and console errors.
Usage: python tools/qa_screens.py <out_dir>"""
import json, os, subprocess, sys, tempfile, time, urllib.request, urllib.error
from playwright.sync_api import sync_playwright
OUT = sys.argv[1] if len(sys.argv) > 1 else "docs/qa"
os.makedirs(OUT, exist_ok=True)
env = dict(os.environ, SH_PREDICTION_DB=tempfile.mkdtemp() + "/qa.sqlite3", SH_PREDICTION_ADMIN_TOKEN="qa-admin", PORT="8765", HOST="127.0.0.1")
srv = subprocess.Popen([sys.executable, "app/main.py"], env=env)
B = "http://127.0.0.1:8765"
def call(p, d=None, h=None, m=None):
    r = urllib.request.Request(B + p, data=json.dumps(d).encode() if d is not None else None, headers=dict({"Content-Type": "application/json"}, **(h or {})), method=m)
    try:
        return json.loads(urllib.request.urlopen(r).read())
    except urllib.error.HTTPError as e:
        raise SystemExit("%s %s -> %s %s" % (p, d, e.code, e.read().decode()))
try:
    for _ in range(50):
        try: call("/health"); break
        except Exception: time.sleep(0.1)
    A = {"X-Admin-Token": "qa-admin"}
    ids = call("/api/v1/admin/demo-seed", {}, A)["demo_match_ids"]
    e = call("/api/v1/admin/experts", {"display_name": "Demo Tipster", "country": "India", "language_code": "te", "bio": "DEMO profile for screen review"}, A)["expert_id"]
    call("/api/v1/admin/experts/%d/verify" % e, {}, A)
    m = call("/api/v1/matches/%d" % ids[-1], h=A)
    call("/api/v1/predictions", {"match_id": ids[-1], "prediction_type": "winner", "predicted_team_id": m["home"]["id"], "confidence": 64, "explanation": "DEMO: stronger recent form", "expert_id": e}, A)
    live = call("/api/v1/admin/matches", {"competition": "SH Demo League", "home": "Demo Royal Rhinos", "away": "Demo Eagle Eyes", "start_utc": "2026-01-10T14:00:00+00:00", "source": "SH demo generator", "data_origin": "demo", "match_no": "D6", "format": "T10", "venue": "Demo Oval"}, A)["match_id"]
    lm = call("/api/v1/matches/%d" % live, h=A)
    seq = 0
    for ino, bat, tgt, pattern in ((1, lm["home"]["id"], None, [1, 4, 0, 6, 1, 1, "W", 2, 4, 0, 1, 6] * 5), (2, lm["away"]["id"], 101, [1, 0, 4, "W", 1, 2, 0, 6, 1, "W", 0, 1, 2, 4])):
        for i, x in enumerate(pattern, 1):
            seq += 1
            b = {"match_id": live, "innings_no": ino, "batting_team_id": bat, "seq": i, "commentary": "DEMO ball"}
            if tgt: b["target"] = tgt
            b.update({"is_wicket": 1, "wicket_kind": "caught"} if x == "W" else {"runs_bat": x})
            r = call("/api/v1/admin/ball-events", b, A)
            if r["innings_completed"]: break
    o = call("/auth/generate", {"phone": "9000099999"}); tok = call("/auth/verify", {"phone": "9000099999", "otp": o["otp"]})["token"]
    shots, errors = [], []
    with sync_playwright() as p:
        br = p.chromium.launch(executable_path="/usr/bin/google-chrome", args=["--no-sandbox"])
        for theme, vp in (("dark", {"width": 390, "height": 844}), ("light", {"width": 1280, "height": 900})):
            call("/api/v1/me/preferences", {"theme": theme, "language_code": "en"}, {"Authorization": "Bearer " + tok}, "PUT")
            ctx = br.new_context(viewport=vp, device_scale_factor=2 if vp["width"] < 500 else 1)
            pg = ctx.new_page()
            pg.on("console", lambda msg: errors.append(msg.text) if msg.type == "error" else None)
            pg.on("pageerror", lambda ex: errors.append(str(ex)))
            pg.goto(B + "/hub")
            pg.evaluate("([t,th])=>{localStorage.setItem('shp_session',t);localStorage.setItem('shp_theme',th);localStorage.setItem('shp_demo','1')}", [tok, theme])
            screens = ["home", "master", "matches", "match/%d/info" % ids[-1], "match/%d/preds" % ids[-1], "match/%d/ai" % ids[-1], "match/%d/live" % live,
                       "match/%d/score" % live, "match/%d/comm" % live, "experts", "experts/%d" % e, "ai", "accuracy", "settings"]
            if theme == "light": screens = ["master", "match/%d/live" % live, "accuracy"]
            for s in screens:
                pg.goto(B + "/hub#/" + s); pg.reload(); pg.wait_for_timeout(700)
                if s == "master": pg.select_option("#comp", label="SH Demo League"); pg.wait_for_timeout(500)
                f = "%s/%s-%s.png" % (OUT, theme, s.replace("/", "_")); pg.screenshot(path=f, full_page=True); shots.append(f)
                if s == "master":
                    pg.click("[data-v=act]"); pg.wait_for_timeout(400)
                    f = "%s/%s-master_results.png" % (OUT, theme); pg.screenshot(path=f, full_page=True); shots.append(f)
                    pg.click("[data-v=pred]"); pg.wait_for_timeout(200)
            if theme == "dark":  # language switch persists across reload
                pg.goto(B + "/hub#/settings"); pg.wait_for_timeout(600); pg.select_option("#lang", "te"); pg.wait_for_timeout(800)
                pg.goto(B + "/hub#/master"); pg.reload(); pg.wait_for_timeout(800)
                f = "%s/dark-master_telugu.png" % OUT; pg.screenshot(path=f, full_page=True); shots.append(f)
                heads = pg.eval_on_selector_all(".ml th", "e=>e.map(x=>x.textContent)")
                print("TELUGU_HEADERS", heads)
                pg.select_option("#comp", label="SH Demo League"); pg.wait_for_timeout(400)
                colors = pg.evaluate("""()=>[...document.querySelectorAll('.ml tbody tr')].slice(0,3).map(tr=>[...tr.querySelectorAll('td span')].map(s=>s.textContent+':'+getComputedStyle(s).color))""")
                print("COLORS", json.dumps(colors, ensure_ascii=False))
                pg.goto(B + "/hub#/settings"); pg.wait_for_timeout(500); pg.select_option("#lang", "en"); pg.wait_for_timeout(500)
            ctx.close()
        br.close()
    print("SHOTS", len(shots)); print("CONSOLE_ERRORS", errors)
finally:
    srv.terminate()

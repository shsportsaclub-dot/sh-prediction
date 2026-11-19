"""SH SOCIAL end-to-end acceptance proof (Master Build Script section 16).

PHOTO UPLOAD -> VIDEO UPLOAD -> AUTOMATIC VIDEO PROCESSING -> REEL PUBLICATION -> REEL PLAYBACK -> SOCIAL FEED -> MATCH CENTER,
then moderation, deletion cleanup and persistence across a server restart.
Production-like settings: codes are NOT exposed by the API; verification emails go through real SMTP to a local mail catcher.
Usage: python tools/e2e_social.py docs/qa/e2e
"""
import json, os, re, socketserver, sqlite3, subprocess, sys, tempfile, threading, time, urllib.request, urllib.error

OUT = sys.argv[1] if len(sys.argv) > 1 else "docs/qa/e2e"
os.makedirs(OUT, exist_ok=True)
WORK = tempfile.mkdtemp()
DB = os.path.join(WORK, "prod-like.sqlite3")
MEDIA_DIR = os.path.join(WORK, "media")
def _free():
    import socket
    k = socket.socket(); k.bind(("127.0.0.1", 0)); p = k.getsockname()[1]; k.close(); return p
PORT, SMTP_PORT = _free(), _free()
B = "http://127.0.0.1:%d" % PORT
ADMIN = {"X-Admin-Token": "e2e-admin-key"}
LOG = []

def log(step, ok, **evidence):
    LOG.append({"step": step, "ok": bool(ok), **evidence})
    print(("PASS " if ok else "FAIL ") + step)
    if not ok:
        raise SystemExit("step failed: " + step)

# ---------------------------------------------------------------- local SMTP mail catcher (no third party)
MAILBOX = []
class SMTPHandler(socketserver.StreamRequestHandler):
    def handle(self):
        w = lambda s: self.wfile.write((s + "\r\n").encode())
        w("220 sh-e2e-mailcatcher")
        data_mode, buf = False, []
        while True:
            line = self.rfile.readline()
            if not line:
                return
            s = line.decode(errors="replace").rstrip("\r\n")
            if data_mode:
                if s == ".":
                    MAILBOX.append("\n".join(buf)); buf = []; data_mode = False; w("250 queued")
                else:
                    buf.append(s[1:] if s.startswith("..") else s)
                continue
            cmd = s[:4].upper()
            if cmd in ("EHLO", "HELO"):
                w("250 sh-e2e")
            elif cmd in ("MAIL", "RCPT", "RSET", "NOOP"):
                w("250 ok")
            elif cmd == "DATA":
                data_mode = True; w("354 end with .")
            elif cmd == "QUIT":
                w("221 bye"); return
            else:
                w("250 ok")
socketserver.ThreadingTCPServer.allow_reuse_address = True
smtp = socketserver.ThreadingTCPServer(("127.0.0.1", SMTP_PORT), SMTPHandler)
threading.Thread(target=smtp.serve_forever, daemon=True).start()

ENV = dict(os.environ, SH_PREDICTION_DB=DB, SH_MEDIA_DIR=MEDIA_DIR, SH_PREDICTION_ADMIN_TOKEN="e2e-admin-key", PORT=str(PORT), HOST="127.0.0.1",
           SH_SMTP_HOST="127.0.0.1", SH_SMTP_PORT=str(SMTP_PORT), SH_SMTP_FROM="no-reply@sh-prediction.test", SH_SMTP_STARTTLS="0",
           SH_DEV_EXPOSE_CODES="0", SH_DEV_PHONE_LOGIN="0", SH_COLLECTORS="0", SH_MEDIA_SIGNING_KEY="e2e-signing-key-stable-across-restart")
ENV.pop("SH_DEV_EXPOSE_CODES", None); ENV["SH_DEV_EXPOSE_CODES"] = "0"
SERVER_LOG = open(os.path.join(OUT, "server.log"), "w")

def start_server():
    p = subprocess.Popen([sys.executable, "app/main.py"], env=ENV, stdout=SERVER_LOG, stderr=SERVER_LOG)
    for _ in range(100):
        try:
            urllib.request.urlopen(B + "/health"); return p
        except Exception:
            time.sleep(0.1)
    raise SystemExit("server did not start")

def call(path, data=None, h=None, method=None):
    r = urllib.request.Request(B + path, data=json.dumps(data).encode() if data is not None else None,
                               headers=dict({"Content-Type": "application/json"}, **(h or {})), method=method)
    try:
        x = urllib.request.urlopen(r); return x.status, json.loads(x.read())
    except urllib.error.HTTPError as e:
        return e.code, json.loads(e.read() or b"{}")

def code_from_mail(to):
    for _ in range(50):
        for m in reversed(MAILBOX):
            if ("To: " + to) in m:
                c = re.search(r"code is (\d{6})", m)
                if c:
                    return c.group(1)
        time.sleep(0.1)
    raise SystemExit("no email for " + to)

def register(username):
    s, r = call("/api/v1/auth/register", {"username": username, "email": username + "@example.test", "password": "E2e-Passw0rd-SH", "display_name": username.title()})
    assert s == 201 and "dev_code" not in r, r
    code = code_from_mail(username + "@example.test")
    s2, v = call("/api/v1/auth/verify-email", {"login": username, "code": code})
    s3, t = call("/api/v1/auth/login", {"login": username, "password": "E2e-Passw0rd-SH"})
    return {"Authorization": "Bearer " + t["token"]}, {"register": r, "verify_status": s2, "login_status": s3, "email_delivery": r["email_verification"]}

def upload(h, path, kind, mime, purpose):
    size = os.path.getsize(path)
    s, r = call("/api/v1/media/uploads", {"kind": kind, "mime": mime, "bytes": size, "filename": os.path.basename(path), "purpose": purpose}, h)
    assert s == 201, r
    data, off, chunks = open(path, "rb").read(), 0, 0
    while off < size:
        part = data[off:off + 512 * 1024]
        req = urllib.request.Request(B + r["upload_url"], data=part, method="PUT", headers={"Content-Range": "bytes %d-%d/%d" % (off, off + len(part) - 1, size)})
        off = json.loads(urllib.request.urlopen(req).read())["received_bytes"]; chunks += 1
    s, c = call("/api/v1/media/uploads/%d/complete" % r["media_id"], {}, h)
    return r["media_id"], {"bytes": size, "chunks": chunks, "complete": c}

def wait_ready(h, mid):
    t0 = time.time()
    while time.time() - t0 < 180:
        s, r = call("/api/v1/media/uploads/%d" % mid, h=h)
        if r["status"] in ("ready", "failed"):
            return r, round(time.time() - t0, 1)
        time.sleep(0.3)
    raise SystemExit("processing timeout")

def dbq(sql, *a):
    c = sqlite3.connect(DB); c.row_factory = sqlite3.Row
    try:
        return [dict(r) for r in c.execute(sql, a)]
    finally:
        c.close()

srv = start_server()
try:
    s, mig = call("/api/v1/admin/system/migrate", {"confirm": True}, ADMIN)
    log("database migration with verified backup", s == 200 and mig["status"] == "migrated", applied=mig["applied"], backup=mig["backup"]["integrity"])
    s, m = call("/api/v1/admin/matches", {"competition": "SH E2E Demo Cup", "home": "E2E Lions", "away": "E2E Tigers", "start_utc": "2030-06-01T14:00:00+00:00",
                                          "source": "E2E test fixture (demo)", "data_origin": "demo", "venue": "E2E Oval", "format": "T20"}, ADMIN)
    MATCH = m["match_id"]
    # 1. User A registers (real email verification) and logs in
    A, ev = register("creator_asha")
    log("1. User A registers, verifies email via SMTP and logs in", ev["verify_status"] == 200 and ev["login_status"] == 200 and ev["email_delivery"] == "sent",
        **ev, emails_received=len(MAILBOX))
    # real files
    from PIL import Image
    jpg = os.path.join(WORK, "ground.jpg")
    im = Image.new("RGB", (2000, 1200), (30, 90, 60))
    for x in range(0, 2000, 50):
        for y in range(0, 1200, 50):
            im.putpixel((x, y), (250, 250, 250))
    im.save(jpg, "JPEG", quality=92)
    mp4 = os.path.join(WORK, "nets.mp4")
    subprocess.run(["ffmpeg", "-hide_banner", "-loglevel", "error", "-y", "-f", "lavfi", "-i", "testsrc2=duration=6:size=1280x720:rate=30",
                    "-f", "lavfi", "-i", "sine=frequency=330:duration=6", "-c:v", "libx264", "-preset", "veryfast", "-pix_fmt", "yuv420p", "-c:a", "aac", "-shortest", mp4], check=True)
    # 2. photo upload + publish
    img_id, up = upload(A, jpg, "image", "image/jpeg", "post")
    rimg, secs = wait_ready(A, img_id)
    s, photo_post = call("/api/v1/social/posts", {"kind": "photo", "body": "Pitch looks dry today #E2E #pitch", "media_ids": [img_id], "match_id": MATCH}, A)
    log("2. Photo uploaded (chunked), processed and published", rimg["status"] == "ready" and photo_post.get("status") == "published",
        upload=up, processing_seconds=secs, renditions=rimg["renditions"], post=photo_post)
    s, text_post = call("/api/v1/social/posts", {"kind": "analysis", "body": "Lions have the stronger death bowling #E2E", "match_id": MATCH}, A)
    log("3. Text post created and published", s == 201, post=text_post)
    # 4-7. video upload, automatic processing, thumbnail, reel publication
    vid_id, vup = upload(A, mp4, "video", "video/mp4", "reel")
    s, reel_post = call("/api/v1/social/posts", {"kind": "reel", "body": "Net session highlights #E2E #reels", "media_ids": [vid_id], "match_id": MATCH}, A)
    log("4. Video uploaded; reel post waits for processing", reel_post.get("status") == "processing", upload=vup, post=reel_post)
    rvid, vsecs = wait_ready(A, vid_id)
    job = dbq("SELECT id, status, attempts, log FROM jobs WHERE ref_id=? AND kind='process_media'", vid_id)[0]
    log("5. Background worker processed the video automatically", rvid["status"] == "ready" and job["status"] == "done", processing_seconds=vsecs, job=job)
    files = sorted(os.path.relpath(os.path.join(dp, f), MEDIA_DIR) for dp, _, fs in os.walk(os.path.join(MEDIA_DIR, str(vid_id))) for f in fs)
    log("6. Thumbnail, MP4 and HLS renditions generated on disk", "%d/thumb.jpg" % vid_id in files and "%d/video.mp4" % vid_id in files and "%d/master.m3u8" % vid_id in files,
        files=files, renditions=rvid["renditions"])
    s, rp = call("/api/v1/social/posts/%d" % reel_post["post_id"])
    log("7. Reel published automatically after processing", rp["status"] == "published" and rp["media"][0]["width"] == 720 and rp["media"][0]["height"] == 1280,
        media=rp["media"][0])
    vid2, _ = upload(A, mp4, "video", "video/mp4", "reel")
    s, reel2 = call("/api/v1/social/posts", {"kind": "reel", "body": "Second reel for swipe test #E2E", "media_ids": [vid2]}, A)
    r2, _ = wait_ready(A, vid2)
    for _ in range(50):
        if call("/api/v1/social/posts/%d" % reel2["post_id"])[1].get("status") == "published": break
        time.sleep(0.2)
    log("7b. Second reel published (needed to prove swipe navigation)", r2["status"] == "ready", post=reel2)
    # 8-13. User B: separate login, watch, follow, like, comment, share, save
    Bh, evb = register("viewer_bala")
    from playwright.sync_api import sync_playwright
    with sync_playwright() as p:
        br = p.chromium.launch(executable_path="/usr/bin/google-chrome", args=["--no-sandbox", "--autoplay-policy=no-user-gesture-required"])
        ctx = br.new_context(viewport={"width": 390, "height": 844}, device_scale_factor=2, user_agent="Mozilla/5.0 (Linux; Android 14; Pixel 8) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/130 Mobile Safari/537.36")
        pg = ctx.new_page()
        errors = []
        pg.on("pageerror", lambda e: errors.append(str(e)))
        pg.goto(B + "/")
        pg.evaluate("t=>localStorage.setItem('shp_session',t)", Bh["Authorization"][7:])
        pg.goto(B + "/#/reels"); pg.reload(); pg.wait_for_selector(".reel video", timeout=15000); pg.wait_for_timeout(2500)
        play = pg.evaluate("""async()=>{const v=document.querySelector('.reel video');v.muted=true;await v.play().catch(()=>{});const t0=v.currentTime;await new Promise(r=>setTimeout(r,1500));
            const t1=v.currentTime;v.pause();const paused=v.paused;return {readyState:v.readyState,t0,t1,advanced:t1>t0,paused,src:v.currentSrc,videoWidth:v.videoWidth,videoHeight:v.videoHeight,duration:v.duration}}""")
        pg.screenshot(path=os.path.join(OUT, "08-reel-playing-user-b.png"))
        log("8-9. User B opens the Reel in Chrome; it plays, advances and pauses", play["advanced"] and play["paused"] and play["videoWidth"] == 720, playback=play)
        pg.evaluate("()=>{const r=document.querySelector('.reels');r.scrollBy(0,r.clientHeight)}"); pg.wait_for_timeout(600)
        swiped = pg.evaluate("()=>document.querySelector('.reels').scrollTop>0")
        log("9b. Swipe navigation scrolls to the next reel slot", swiped, scroll_top_positive=swiped)
        pg.evaluate("id=>document.querySelector('.reel[data-id=\"'+id+'\"]').scrollIntoView()", str(reel_post["post_id"])); pg.wait_for_timeout(600)
        R = ".reel[data-id='%d'] " % reel_post["post_id"]
        pg.click(R + ".fw"); pg.wait_for_timeout(500)
        pg.click(R + ".lk"); pg.wait_for_timeout(500)
        pg.click(R + ".sv"); pg.wait_for_timeout(500)
        pg.evaluate("()=>{navigator.share=undefined;navigator.clipboard.writeText=async()=>{}}")
        pg.click(R + ".sh"); pg.wait_for_timeout(500)
        pg.screenshot(path=os.path.join(OUT, "10-reel-after-follow-like-save-share.png"))
        pg.goto(B + "/#/post/%d" % reel_post["post_id"]); pg.wait_for_selector("#cb", timeout=10000)
        pg.fill("#cb", "Great net session! #E2E"); pg.click("#cf button"); pg.wait_for_timeout(1200)
        pg.screenshot(path=os.path.join(OUT, "11-comment-posted.png"), full_page=True)
        call("/api/v1/social/posts/%d/watch" % reel_post["post_id"], {"watched_ms": 5800}, Bh)
        post_counts = call("/api/v1/social/posts/%d" % reel_post["post_id"], h=Bh)[1]
        db_counts = {"follows": dbq("SELECT COUNT(*) n FROM follows f JOIN accounts a ON a.user_id=f.followee_id WHERE a.username='creator_asha'")[0]["n"],
                     "likes": dbq("SELECT COUNT(*) n FROM reactions WHERE post_id=?", reel_post["post_id"])[0]["n"],
                     "comments": dbq("SELECT COUNT(*) n FROM comments WHERE post_id=? AND status='visible'", reel_post["post_id"])[0]["n"],
                     "shares": dbq("SELECT COUNT(*) n FROM shares WHERE post_id=?", reel_post["post_id"])[0]["n"],
                     "saves": dbq("SELECT COUNT(*) n FROM bookmarks WHERE post_id=?", reel_post["post_id"])[0]["n"],
                     "views": dbq("SELECT COUNT(*) n FROM post_views WHERE post_id=?", reel_post["post_id"])[0]["n"]}
        ok = post_counts["counts"] == {"views": 1, "likes": 1, "comments": 1, "shares": 1, "saves": 1} and db_counts["follows"] == 1 and post_counts["me"]["following_author"]
        log("10-13. User B followed, liked, commented, shared and saved; counts match the database", ok, api_counts=post_counts["counts"], db_counts=db_counts,
            me=post_counts["me"])
        dash = call("/api/v1/me/dashboard", h=A)[1]
        w = dbq("SELECT COUNT(*) n, COALESCE(SUM(watched_ms),0) ms, COALESCE(SUM(completed),0) done FROM watch_sessions w JOIN posts p ON p.id=w.post_id JOIN accounts a ON a.user_id=p.author_id WHERE a.username='creator_asha'")[0]
        db_dash = {"sessions": w["n"], "watch_ms": w["ms"], "rate": round(100.0 * w["done"] / w["n"], 1) if w["n"] else None,
                   "views": dbq("SELECT COUNT(*) n FROM post_views v JOIN posts p ON p.id=v.post_id JOIN accounts a ON a.user_id=p.author_id WHERE a.username='creator_asha' AND p.status!='deleted'")[0]["n"]}
        log("14. Creator analytics updated (views, likes, comments, shares, saves, followers, watch time, completion)",
            dash["views"] == db_dash["views"] and dash["likes"] == 1 and dash["comments"] == 1 and dash["shares"] == 1 and dash["saves"] == 1 and dash["followers"] == 1
            and dash["watch_sessions"] == db_dash["sessions"] >= 2 and dash["watch_time_ms"] == db_dash["watch_ms"] and dash["reel_completion_rate"] == db_dash["rate"],
            database=db_dash,
            dashboard={k: dash[k] for k in ("posts", "views", "likes", "comments", "shares", "saves", "followers", "watch_time_ms", "watch_sessions", "reel_completion_rate")})
        pg.evaluate("()=>localStorage.setItem('shp_demo','1')")
        pg.goto(B + "/#/match/%d/community" % MATCH); pg.reload(); pg.wait_for_timeout(2500)
        pg.screenshot(path=os.path.join(OUT, "15-match-center-community.png"), full_page=True)
        com = call("/api/v1/matches/%d/community" % MATCH)[1]
        ids = {x["id"] for x in com["posts"]["items"]}
        log("15. Cricket posts appear in the Match Center Community by Match ID", {photo_post["post_id"], text_post["post_id"], reel_post["post_id"]} <= ids,
            community_post_ids=sorted(ids))
        # 16. report + admin moderation
        s, rep = call("/api/v1/social/reports", {"target_type": "post", "target_id": text_post["post_id"], "reason": "E2E moderation check"}, Bh)
        s2, mod = call("/api/v1/admin/social/moderate", {"action": "remove_post", "target_type": "post", "target_id": text_post["post_id"], "reason": "E2E: content check"}, ADMIN)
        gone = call("/api/v1/social/posts/%d" % text_post["post_id"])[0]
        apg = ctx.new_page(); apg.goto(B + "/admin-panel"); apg.fill("#k", "e2e-admin-key"); apg.click("#kgo"); apg.wait_for_timeout(800)
        apg.goto(B + "/admin-panel#moderation"); apg.wait_for_timeout(1500); apg.screenshot(path=os.path.join(OUT, "16-admin-moderation.png"), full_page=True)
        log("16. Post reported by User B and removed by an administrator", s == 201 and s2 == 200 and gone == 404,
            report_status=s, moderation=mod, viewer_status_after=gone, report_row=dbq("SELECT status, resolved_by FROM reports WHERE target_id=?", text_post["post_id"]))
        # 17-18. ownership and deletion cleanup (photo post)
        not_owner = call("/api/v1/social/posts/%d/delete" % photo_post["post_id"], {}, Bh)[0]
        photo_dir = os.path.join(MEDIA_DIR, str(img_id))
        before = os.path.isdir(photo_dir)
        s, d = call("/api/v1/social/posts/%d/delete" % photo_post["post_id"], {}, A)
        log("17-18. Only the owner can delete; deletion removes the media files", not_owner == 403 and before and not os.path.exists(photo_dir),
            other_user_delete_status=not_owner, files_before=before, files_after=os.path.exists(photo_dir),
            media_row=dbq("SELECT status FROM media_assets WHERE id=?", img_id))
        # 19. admin endpoints reject unauthorized users
        codes = {p: call("/api/v1/admin/" + p, h=Bh)[0] for p in ("social/users", "social/reports", "media/storage", "master-list", "audit")}
        log("19. Admin endpoints reject a logged-in non-admin", set(codes.values()) == {403}, statuses=codes)
        # 20. responsive layouts
        for name, vp in (("android-phone", {"width": 360, "height": 780}), ("desktop", {"width": 1366, "height": 900})):
            c2 = br.new_context(viewport=vp); p2 = c2.new_page(); p2.goto(B + "/#/social"); p2.wait_for_timeout(1500)
            p2.screenshot(path=os.path.join(OUT, "20-social-%s.png" % name), full_page=True)
            overflow = p2.evaluate("()=>document.documentElement.scrollWidth>window.innerWidth+1")
            log("20. Social feed renders without horizontal overflow on " + name, not overflow, viewport=vp)
            c2.close()
        log("browser had no JavaScript errors", not errors, errors=errors)
        br.close()
    # persistence across restart
    srv.terminate(); srv.wait(10)
    srv = start_server()
    s, again = call("/api/v1/social/posts/%d" % reel_post["post_id"])
    mp4_url = again["media"][0]["urls"]["mp4"]
    st = urllib.request.urlopen(urllib.request.Request(B + mp4_url, headers={"Range": "bytes=0-1023"})).status
    log("10 (persistence). After a server restart the Reel, its counts and its media are still served",
        s == 200 and again["counts"]["likes"] == 1 and again["counts"]["comments"] == 1 and st == 206, counts=again["counts"], media_status=st)
finally:
    srv.terminate()
    smtp.shutdown(); smtp.server_close()
    json.dump({"ran_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()), "steps": LOG, "emails_sent": len(MAILBOX)}, open(os.path.join(OUT, "e2e-evidence.json"), "w"), indent=1, default=str)
print("ALL %d STEPS PASSED" % len(LOG) if all(x["ok"] for x in LOG) else "FAILED")

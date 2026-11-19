"""SH SOCIAL, accounts, media pipeline, live stream, commentary, game engine and admin sweep — real files, real server."""
import io, json, os, sqlite3, subprocess, sys, tempfile, threading, time, unittest, urllib.request, urllib.error
sys.path.insert(0, os.path.dirname(__file__))
import test_v1 as T  # shared server, DB and helpers (sets env first)
import main, media, social, game, commentary, api_v1

WORKER = media.Worker(main.db, social.on_media_ready, interval=0.1).start()
A = T.A
call = T.call

def setUpModule():
    T._migrate_once()

def wait_media(h, mid, timeout=90):
    for _ in range(int(timeout / 0.2)):
        s, r = call("/api/v1/media/uploads/%d" % mid, h=h)
        if r.get("status") in ("ready", "failed"):
            return r
        time.sleep(0.2)
    raise AssertionError("media %d not processed" % mid)

def upload(h, path, kind, mime, purpose="post", chunk=300000, crop=None):
    size = os.path.getsize(path)
    body = {"kind": kind, "mime": mime, "bytes": size, "filename": os.path.basename(path), "purpose": purpose}
    if crop:
        body["crop"] = crop
    s, r = call("/api/v1/media/uploads", body, h)
    assert s == 201, r
    url = r["upload_url"]
    data = open(path, "rb").read()
    off = 0
    while off < size:
        part = data[off:off + chunk]
        req = urllib.request.Request(T.B + url, data=part, method="PUT", headers={"Content-Range": "bytes %d-%d/%d" % (off, off + len(part) - 1, size)})
        res = json.loads(urllib.request.urlopen(req).read())
        off = res["received_bytes"]
    s, done = call("/api/v1/media/uploads/%d/complete" % r["media_id"], {}, h)
    assert s == 200, done
    return r["media_id"]

def make_jpeg(path, w=1600, h=900):
    from PIL import Image
    im = Image.new("RGB", (w, h), (20, 60, 140))
    for x in range(0, w, 40):
        for y in range(0, h, 40):
            im.putpixel((x, y), (255, 200, 0))
    exif = Image.Exif(); exif[0x010F] = "SecretCamMaker"
    im.save(path, "JPEG", quality=90, exif=exif)

def make_mp4(path, seconds=3, size="640x360"):
    subprocess.run(["ffmpeg", "-hide_banner", "-loglevel", "error", "-y", "-f", "lavfi", "-i", "testsrc=duration=%d:size=%s:rate=25" % (seconds, size),
                    "-f", "lavfi", "-i", "sine=frequency=440:duration=%d" % seconds, "-c:v", "libx264", "-preset", "veryfast", "-pix_fmt", "yuv420p",
                    "-c:a", "aac", "-shortest", path], check=True)

def raw_get(path, headers=None):
    req = urllib.request.Request(T.B + path, headers=headers or {})
    try:
        r = urllib.request.urlopen(req)
        return r.status, r.read(), dict(r.headers)
    except urllib.error.HTTPError as e:
        return e.code, e.read(), dict(e.headers)

class Accounts(unittest.TestCase):
    def test_register_validation_lockout_reset_and_no_code_leak(self):
        self.assertEqual(call("/api/v1/auth/register", {"username": "weakling", "email": "w@example.test", "password": "short"})[0], 400)
        self.assertEqual(call("/api/v1/auth/register", {"username": "Bad Name!", "email": "x@example.test", "password": T.PASSWORD})[0], 400)
        h = T.account("acc_owner")
        self.assertEqual(call("/api/v1/auth/register", {"username": "acc_owner", "email": "other@example.test", "password": T.PASSWORD})[0], 409)
        me = call("/api/v1/me", h=h)[1]
        self.assertEqual((me["username"], me["email_verified"]), ("acc_owner", True))
        # wrong password 5 times -> locked
        for _ in range(5):
            self.assertEqual(call("/api/v1/auth/login", {"login": "acc_owner", "password": "Wrong-Passw0rd"})[0], 401)
        self.assertEqual(call("/api/v1/auth/login", {"login": "acc_owner", "password": T.PASSWORD})[1]["error"]["code"], "LOCKED")
        c = T.db(); c.execute("UPDATE accounts SET locked_until=NULL WHERE username='acc_owner'"); c.commit(); c.close()
        # password reset signs out everywhere
        s, r = call("/api/v1/auth/request-password-reset", {"login": "acc_owner"})
        self.assertEqual(call("/api/v1/auth/reset-password", {"login": "acc_owner", "code": "000000", "new_password": "New-Passw0rd-1"})[0], 400)
        self.assertEqual(call("/api/v1/auth/reset-password", {"login": "acc_owner", "code": r["dev_code"], "new_password": "New-Passw0rd-1"})[0], 200)
        self.assertEqual(call("/api/v1/me", h=h)[0], 401)
        self.assertEqual(call("/api/v1/auth/login", {"login": "acc_owner@example.test", "password": "New-Passw0rd-1"})[0], 200)
        # production default: codes are never returned, mail goes to the outbox (not_configured without SMTP)
        os.environ["SH_DEV_EXPOSE_CODES"] = "0"
        try:
            s, r = call("/api/v1/auth/register", {"username": "prod_like", "email": "prod@example.test", "password": T.PASSWORD})
            self.assertEqual(s, 201)
            self.assertNotIn("dev_code", r)
            self.assertEqual(r["email_verification"], "not_configured")
            ob = call("/api/v1/admin/mail/outbox", h=A)[1]
            self.assertNotIn("body", ob["items"][0])
        finally:
            os.environ["SH_DEV_EXPOSE_CODES"] = "1"

    def test_phone_code_login_disabled_by_default(self):
        old = os.environ.pop("SH_DEV_PHONE_LOGIN", None)
        try:
            self.assertEqual(call("/auth/generate", {"phone": "9123456789"})[0], 410)
        finally:
            if old:
                os.environ["SH_DEV_PHONE_LOGIN"] = old

    def test_unverified_cannot_post_and_manual_verify(self):
        h = T.account("unver_user", verify=False)
        self.assertEqual(call("/api/v1/social/posts", {"kind": "text", "body": "hello"}, h)[1]["error"]["code"], "EMAIL_NOT_VERIFIED")
        uid = call("/api/v1/me", h=h)[1]["user_id"]
        self.assertEqual(call("/api/v1/admin/users/%d/verify-email" % uid, {"reason": "checked ID"}, A)[0], 200)
        self.assertEqual(call("/api/v1/social/posts", {"kind": "text", "body": "hello #cricket"}, h)[0], 201)

    def test_delete_account_erases_profile(self):
        h = T.account("leaving_user")
        call("/api/v1/social/posts", {"kind": "text", "body": "bye all"}, h)
        self.assertEqual(call("/api/v1/me/delete", {"password": "nope"}, h)[0], 401)
        self.assertEqual(call("/api/v1/me/delete", {"password": T.PASSWORD}, h)[0], 200)
        self.assertEqual(call("/api/v1/social/users/leaving_user")[0], 404)
        self.assertEqual(call("/api/v1/me", h=h)[0], 401)

class Social(unittest.TestCase):
    def test_posts_follow_like_comment_views_share_save_block(self):
        a, b = T.account("soc_alice"), T.account("soc_bob")
        s, p = call("/api/v1/social/posts", {"kind": "text", "body": "Big game tonight #IPL @soc_bob"}, a)
        self.assertEqual(s, 201, p)
        pid = p["post_id"]
        self.assertEqual(call("/api/v1/social/posts", {"kind": "text", "body": "Big game tonight #IPL @soc_bob"}, a)[1]["error"]["code"], "DUPLICATE")
        self.assertEqual(call("/api/v1/social/users/soc_alice/follow", {}, b)[1]["following"], True)
        self.assertEqual(call("/api/v1/social/posts/%d/like" % pid, {}, b)[1]["likes"], 1)
        call("/api/v1/social/posts/%d/comments" % pid, {"body": "agreed!"}, b)
        call("/api/v1/social/posts/%d/save" % pid, {}, b)
        call("/api/v1/social/posts/%d/share" % pid, {"channel": "whatsapp"}, b)
        for _ in range(3):
            call("/api/v1/social/posts/%d/view" % pid, {}, b)        # same viewer, same day -> 1
        call("/api/v1/social/posts/%d/view" % pid, {}, a)            # author's own view -> not counted
        post = call("/api/v1/social/posts/%d" % pid, h=b)[1]
        self.assertEqual(post["counts"], {"views": 1, "likes": 1, "comments": 1, "shares": 1, "saves": 1})
        self.assertEqual((post["hashtags"], post["me"]["following_author"]), (["ipl"], True))
        notes = call("/api/v1/me/notifications", h=a)[1]
        self.assertTrue({"follow", "like", "comment"} <= {n["kind"] for n in notes["items"]})
        mention = call("/api/v1/me/notifications", h=b)[1]
        self.assertIn("mention", {n["kind"] for n in mention["items"]})
        self.assertEqual(call("/api/v1/social/feed?feed=following", h=b)[1]["items"][0]["id"], pid)
        self.assertTrue(any(x["id"] == pid for x in call("/api/v1/social/feed?feed=hashtag&tag=ipl")[1]["items"]))
        # edit keeps history; other users cannot edit or delete
        self.assertEqual(call("/api/v1/social/posts/%d/edit" % pid, {"body": "changed"}, b)[0], 403)
        call("/api/v1/social/posts/%d/edit" % pid, {"body": "Big game tonight #IPL (edited)"}, a)
        self.assertEqual(len(call("/api/v1/social/posts/%d/edits" % pid)[1]["items"]), 1)
        self.assertEqual(call("/api/v1/social/posts/%d/delete" % pid, {}, b)[0], 403)
        # block hides content both ways and removes the follow
        call("/api/v1/social/users/soc_bob/block", {}, a)
        self.assertEqual(call("/api/v1/social/posts/%d" % pid, h=b)[0], 404)
        self.assertEqual(call("/api/v1/social/users/soc_alice/follow", {}, b)[1]["error"]["code"], "BLOCKED")

    def test_private_profile_and_poll(self):
        a, b = T.account("priv_amy"), T.account("priv_ben")
        call("/api/v1/me/profile", {"private_profile": True, "bio": "only friends"}, a)
        pid = call("/api/v1/social/posts", {"kind": "poll", "body": "Who wins?", "options": ["Home", "Away"]}, a)[1]["post_id"]
        self.assertEqual(call("/api/v1/social/posts/%d" % pid)[0], 404)
        self.assertEqual(call("/api/v1/social/posts/%d" % pid, h=b)[0], 404)
        call("/api/v1/social/users/priv_amy/follow", {}, b)
        self.assertEqual(call("/api/v1/social/posts/%d" % pid, h=b)[0], 200)
        call("/api/v1/social/posts/%d/vote" % pid, {"option": 1}, b)
        self.assertEqual(call("/api/v1/social/posts/%d" % pid, h=b)[1]["poll"]["votes"], [0, 1])

    def test_tipster_prediction_post_locked_accuracy_and_community(self):
        tip = T.account("tip_ravi")
        call("/api/v1/me/tipster-application", {}, tip)
        uid = call("/api/v1/me", h=tip)[1]["user_id"]
        self.assertEqual(call("/api/v1/social/posts", {"kind": "prediction", "body": "x", "match_id": 1}, tip)[1]["error"]["code"], "NOT_A_TIPSTER")
        call("/api/v1/admin/social/moderate", {"action": "approve_tipster", "target_type": "user", "target_id": uid, "reason": "application ok"}, A)
        mid = T.mk_match("Tip Lions", "Tip Tigers", comp="Tipster Cup", days=T.SOON)
        h_id, a_id = T.team_ids(mid)
        s, p = call("/api/v1/social/posts", {"kind": "prediction", "body": "Lions in form #tips", "match_id": mid, "prediction_type": "winner",
                                             "predicted_team_id": h_id, "confidence": 70}, tip)
        self.assertEqual(s, 201, p)
        call("/api/v1/social/posts", {"kind": "toss_prediction", "body": "Tigers call it", "match_id": mid, "predicted_team_id": a_id}, tip)
        pred_before = dict(T.db().execute("SELECT * FROM predictions WHERE id=?", (p["prediction_id"],)).fetchone())
        call("/api/v1/social/posts/%d/edit" % p["post_id"], {"body": "Lions in form, edited"}, tip)
        self.assertEqual(dict(T.db().execute("SELECT * FROM predictions WHERE id=?", (p["prediction_id"],)).fetchone()), pred_before)  # pick untouched
        time.sleep(T.SOON_WAIT)
        late = call("/api/v1/social/posts", {"kind": "prediction", "body": "late pick", "match_id": mid, "predicted_team_id": a_id}, tip)
        self.assertEqual(late[1]["error"]["code"], "MATCH_STARTED")
        call("/api/v1/admin/toss", {"match_id": mid, "winner_team_id": h_id, "decision": "bat", "source": "s"}, A)
        call("/api/v1/admin/results", {"match_id": mid, "result_type": "win", "winner_team_id": h_id, "source": "s"}, A)
        call("/api/v1/social/posts/%d/delete" % p["post_id"], {}, tip)          # deleting the post keeps the pick
        hist = call("/api/v1/social/users/tip_ravi/predictions")[1]["items"]
        self.assertEqual(sorted((x["prediction_type"], x["result"]) for x in hist), [("toss", "incorrect"), ("winner", "correct")])
        prof = call("/api/v1/social/users/tip_ravi")[1]
        self.assertEqual((prof["prediction_stats"]["correct"], prof["prediction_stats"]["incorrect"], prof["prediction_stats"]["accuracy"]), (1, 1, 50.0))
        lb = call("/api/v1/social/leaderboard?board=accuracy&min_settled=2")[1]
        row = [x for x in lb["items"] if x["username"] == "tip_ravi"][0]
        self.assertEqual((row["settled"], row["accuracy"]), (2, 50.0))
        com = call("/api/v1/matches/%d/community" % mid)[1]
        self.assertEqual(com["verified_result"]["winner"], "Tip Lions")
        self.assertEqual(len(com["tipster_picks"]), 1)   # the deleted post's pick stays in history but the post itself is gone
        self.assertIn("SH AI", com["sh_ai"]["label"])

    def test_report_moderation_and_suspension(self):
        a, b = T.account("mod_author"), T.account("mod_reporter")
        pid = call("/api/v1/social/posts", {"kind": "text", "body": "spammy http://x http://y http://z"}, a)[1]["post_id"]
        self.assertEqual(call("/api/v1/social/reports", {"target_type": "post", "target_id": pid, "reason": "spam links"}, b)[0], 201)
        self.assertEqual(call("/api/v1/social/reports", {"target_type": "post", "target_id": pid, "reason": "spam links"}, b)[0], 409)
        rep = call("/api/v1/admin/social/reports", h=A)[1]["items"]
        self.assertTrue(any(r["target_id"] == pid for r in rep))
        self.assertTrue(any(x["post_id"] == pid for x in call("/api/v1/admin/social/spam", h=A)[1]["link_heavy_posts"]))
        call("/api/v1/admin/social/moderate", {"action": "remove_post", "target_type": "post", "target_id": pid, "reason": "spam"}, A)
        self.assertEqual(call("/api/v1/social/posts/%d" % pid)[0], 404)
        uid = T.db().execute("SELECT user_id FROM accounts WHERE username='mod_author'").fetchone()[0]
        call("/api/v1/admin/social/moderate", {"action": "suspend_user", "target_type": "user", "target_id": uid, "reason": "repeated spam"}, A)
        self.assertEqual(call("/api/v1/me", h=a)[0], 401)
        self.assertEqual(call("/api/v1/auth/login", {"login": "mod_author", "password": T.PASSWORD})[1]["error"]["code"], "SUSPENDED")
        self.assertGreaterEqual(len(call("/api/v1/admin/social/moderation-log", h=A)[1]["items"]), 2)

class Media(unittest.TestCase):
    def test_photo_video_reel_pipeline_and_cleanup(self):
        tmp = tempfile.mkdtemp()
        a, b = T.account("media_creator"), T.account("media_viewer")
        jpg = os.path.join(tmp, "p.jpg"); make_jpeg(jpg)
        img = upload(a, jpg, "image", "image/jpeg", crop={"x": 0, "y": 0, "w": 0.5, "h": 1})
        r = wait_media(a, img)
        self.assertEqual(r["status"], "ready", r)
        st, body, hd = raw_get(r["renditions"]["image_lg"], {"Authorization": a["Authorization"]})
        self.assertEqual(st, 200)
        from PIL import Image
        im = Image.open(io.BytesIO(body))
        self.assertEqual(im.size, (800, 900))                      # cropped to the left half, within 1080
        self.assertNotIn(b"SecretCamMaker", body)                   # EXIF stripped
        self.assertEqual(raw_get(r["renditions"]["image_lg"])[0], 404)  # not public until it is in a published post
        pid = call("/api/v1/social/posts", {"kind": "photo", "body": "Ground photo #pitch", "media_ids": [img]}, a)[1]["post_id"]
        self.assertEqual(raw_get(r["renditions"]["thumb"])[0], 200)
        mp4 = os.path.join(tmp, "v.mp4"); make_mp4(mp4)
        vid = upload(a, mp4, "video", "video/mp4", purpose="reel")
        s, rp = call("/api/v1/social/posts", {"kind": "reel", "body": "Net session #reels", "media_ids": [vid]}, a)
        self.assertEqual(rp["status"], "processing")
        rv = wait_media(a, vid)
        self.assertEqual(rv["status"], "ready", rv)
        self.assertEqual(set(rv["renditions"]), {"mp4", "thumb", "hls"})
        post = call("/api/v1/social/posts/%d" % rp["post_id"], h=b)[1]
        self.assertEqual(post["status"], "published")
        m = post["media"][0]
        self.assertEqual((m["width"], m["height"]), (720, 1280))       # vertical 9:16
        st, part, hd = raw_get(m["urls"]["mp4"], {"Range": "bytes=0-99"})
        self.assertEqual((st, len(part)), (206, 100))
        st, pl, _ = raw_get(m["urls"]["hls"])
        self.assertIn(b"hls_720p/index.m3u8", pl)
        st, seg, _ = raw_get(m["urls"]["hls"].replace("master.m3u8", "hls_360p/index.m3u8"))
        self.assertIn(b"seg_000.ts", seg)
        self.assertTrue(any(x["id"] == rp["post_id"] for x in call("/api/v1/social/feed?feed=reels", h=b)[1]["items"]))
        call("/api/v1/social/posts/%d/watch" % rp["post_id"], {"watched_ms": 99999}, b)
        dash = call("/api/v1/me/dashboard", h=a)[1]
        self.assertEqual((dash["watch_sessions"], dash["reel_completion_rate"]), (1, 100.0))
        # wrong owner cannot use or inspect someone else's upload; delete cleans the files
        self.assertEqual(call("/api/v1/media/uploads/%d" % vid, h=b)[0], 404)
        self.assertEqual(call("/api/v1/social/posts", {"kind": "photo", "media_ids": [img]}, b)[0], 400)
        path = media.storage().path(str(vid))
        self.assertTrue(os.path.isdir(path))
        call("/api/v1/social/posts/%d/delete" % rp["post_id"], {}, a)
        self.assertFalse(os.path.exists(path))
        self.assertEqual(raw_get(m["urls"]["mp4"])[0], 404)

    def test_upload_validation_resume_and_signature(self):
        a = T.account("media_validator")
        self.assertEqual(call("/api/v1/media/uploads", {"kind": "video", "mime": "application/x-msdownload", "bytes": 10}, a)[0], 415)
        self.assertEqual(call("/api/v1/media/uploads", {"kind": "image", "mime": "image/jpeg", "bytes": 10**9}, a)[0], 413)
        tmp = tempfile.mkdtemp(); fake = os.path.join(tmp, "x.jpg")
        open(fake, "wb").write(b"MZ" + os.urandom(5000))           # not really an image
        s, r = call("/api/v1/media/uploads", {"kind": "image", "mime": "image/jpeg", "bytes": 5002}, a)
        mid = r["media_id"]
        bad = urllib.request.Request(T.B + "/api/v1/media/uploads/%d?exp=9999999999&sig=forged" % mid, data=b"x", method="PUT", headers={"Content-Range": "bytes 0-0/5002"})
        with self.assertRaises(urllib.error.HTTPError) as e:
            urllib.request.urlopen(bad)
        self.assertEqual(e.exception.code, 403)
        data = open(fake, "rb").read()
        req = urllib.request.Request(T.B + r["upload_url"], data=data[:2000], method="PUT", headers={"Content-Range": "bytes 0-1999/5002"})
        urllib.request.urlopen(req)
        # resume: a wrong offset is refused and the server says where to continue
        req = urllib.request.Request(T.B + r["upload_url"], data=data[3000:], method="PUT", headers={"Content-Range": "bytes 3000-5001/5002"})
        with self.assertRaises(urllib.error.HTTPError) as e:
            urllib.request.urlopen(req)
        self.assertEqual(e.exception.code, 409)
        st = call("/api/v1/media/uploads/%d" % mid, h=a)[1]
        self.assertEqual(st["received_bytes"], 2000)
        req = urllib.request.Request(T.B + st["upload_url"], data=data[2000:], method="PUT", headers={"Content-Range": "bytes 2000-5001/5002"})
        urllib.request.urlopen(req)
        self.assertEqual(call("/api/v1/media/uploads/%d/complete" % mid, {}, a)[1]["error"]["code"], "UNSUPPORTED_TYPE")

class LiveCommentaryGame(unittest.TestCase):
    def test_sse_stream_and_own_scoring_updates(self):
        mid = T.mk_match("Sse Lions", "Sse Tigers", days=-0.01, format="T10")
        h, a = T.team_ids(mid)
        bat = call("/api/v1/admin/players", {"name": "Sse Opener", "role": "batter"}, A)[1]["player_id"]
        bowl = call("/api/v1/admin/players", {"name": "Sse Quick", "role": "bowler"}, A)[1]["player_id"]
        got = []
        def listen():
            req = urllib.request.Request(T.B + "/api/v1/matches/%d/stream" % mid)
            r = urllib.request.urlopen(req, timeout=20)
            for line in r:
                line = line.decode().strip()
                if line.startswith("data:"):
                    got.append(json.loads(line[5:]))
                if sum(1 for g in got if "seq" in g) >= 3:
                    break
        os.environ["SH_SSE_MAX_SECONDS"] = "15"
        th = threading.Thread(target=listen, daemon=True); th.start()
        time.sleep(0.5)
        for i, x in enumerate([4, 6, 1], 1):
            call("/api/v1/admin/ball-events", {"match_id": mid, "innings_no": 1, "batting_team_id": h, "seq": i, "runs_bat": x, "batter_id": bat, "bowler_id": bowl}, A)
        th.join(15)
        balls = [g for g in got if "seq" in g]
        self.assertEqual([g["score"] for g in balls], ["4/0", "10/0", "11/0"])
        self.assertIn("FOUR", balls[0]["commentary"])
        sc = call("/api/v1/matches/%d/scorecard" % mid)[1]["innings"][0]["players"]
        rows = {p["name"]: p for p in sc}
        self.assertEqual((rows["Sse Opener"]["runs"], rows["Sse Opener"]["balls"], rows["Sse Opener"]["fours"], rows["Sse Opener"]["sixes"]), (11, 3, 1, 1))
        self.assertEqual((rows["Sse Quick"]["overs_bowled"], rows["Sse Quick"]["runs_conceded"]), ("0.3", 11))
        te = call("/api/v1/matches/%d/commentary?lang=te" % mid)[1]
        self.assertIn("ఫోర్", te["items"][-1]["generated_commentary"])
        rp = call("/api/v1/matches/%d/replay" % mid)[1]
        self.assertTrue(all(e["animation"]["reconstructed"] for e in rp["events"]))

    def test_commentary_never_invents(self):
        ev = [{"innings_no": 1, "seq": 1, "over_no": 0, "ball_in_over": 1, "runs_bat": 0, "extras": 0, "extra_type": None, "is_wicket": 1,
               "wicket_kind": "lbw", "batter": None, "bowler": None, "batting_team_id": 1}]
        line = commentary.generate(ev, "en", {1: "Team"})[0]["text"]
        self.assertIn("the batter", line)
        self.assertNotIn("caught", line)

    def test_game_laws_and_separation(self):
        for fmt in ("T10", "T20", "ODI"):
            for seed in range(25):
                res, events, _ = game.simulate(fmt, seed=seed)
                self.assertTrue(game.validate_events(events, fmt))
                self.assertTrue(res["virtual"])
        bad = [{"innings_no": 1, "over_no": o, "bowler": "Same", "extra_type": None, "is_wicket": 0, "wicket_kind": None} for o in (0, 1) for _ in range(6)]
        with self.assertRaises(game.LawsError):
            game.validate_events(bad, "T20")
        h = T.account("gamer_one")
        s, g = call("/api/v1/game/simulate", {"format": "T10", "seed": 7}, h)
        self.assertEqual(s, 201)
        self.assertEqual(call("/api/v1/game/simulate", {"format": "T10", "seed": 7}, h)[1]["result"], g["result"])   # deterministic by seed
        full = call("/api/v1/game/%d" % g["game_id"])[1]
        self.assertTrue(full["virtual"] and full["events"] and full["events"][0]["animation"]["reconstructed"] is False)
        before = T.db().execute("SELECT COUNT(*) FROM matches").fetchone()[0]
        call("/api/v1/game/simulate", {"format": "T20"}, h)
        self.assertEqual(T.db().execute("SELECT COUNT(*) FROM matches").fetchone()[0], before)   # never touches real matches

class AdminSweep(unittest.TestCase):
    """Every admin endpoint must refuse anonymous callers and logged-in non-admins."""
    GETS = ["audit", "monitor", "dashboard", "master-list", "predictions", "users", "settings", "providers", "calibration", "accuracy", "fantasy/rules",
            "system/status", "model-versions", "cricsheet", "social/users", "social/reports", "social/posts", "social/spam", "social/moderation-log",
            "media/jobs", "media/storage", "mail/outbox"]
    POSTS = ["teams", "matches", "toss", "results", "ball-events", "experts", "players", "player-stats", "model-versions", "import", "settings", "demo-seed",
             "system/migrate", "fantasy/rules", "experts/1/verify", "users/1/role", "predictions/1/publish", "predictions/1/unpublish", "predictions/1/lock",
             "providers/demo/sync", "providers/demo", "matches/1", "matches/1/model-prediction", "matches/1/squad", "matches/1/playing-xi",
             "matches/1/scorecard", "matches/1/fantasy", "cricsheet/import", "player-stats/rebuild", "social/moderate", "media/cleanup", "media/retry",
             "users/1/verify-email"]
    def test_all_admin_endpoints_fail_closed(self):
        user = T.account("not_an_admin")
        tried = 0
        for who in ({}, user, {"X-Admin-Token": "wrong-token"}):
            for p in self.GETS:
                self.assertEqual(call("/api/v1/admin/" + p, h=who)[0], 403, p); tried += 1
            for p in self.POSTS:
                self.assertEqual(call("/api/v1/admin/" + p, {}, who)[0], 403, p); tried += 1
        for p in ("/fixtures", "/register", "/register.csv", "/predictions", "/accuracy", "/admin/drafts", "/admin/audit"):
            self.assertEqual(raw_get(p, {"Authorization": user["Authorization"]})[0], 403, p); tried += 1
        self.assertEqual(tried, 3 * (len(self.GETS) + len(self.POSTS)) + 7)

if __name__ == "__main__":
    unittest.main()

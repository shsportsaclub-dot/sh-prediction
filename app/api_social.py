"""/api/v1 routes for accounts, SH SOCIAL, media, the cricket game and admin moderation.
Called from api_v1.dispatch; every route enforces its own authentication/authorization here in the backend."""
import json

import auth
import engine
import game
import media
import social
from schema import now

def _need_acct(who):
    if not who or not who.get("account"):
        raise social.SocialError(401, "UNAUTHENTICATED", "log in first")
    return who["account"]

def _page(q):
    try:
        limit = int(q.get("limit", ["20"])[0]); offset = int(q.get("offset", ["0"])[0])
    except ValueError:
        raise social.bad("limit and offset must be integers")
    if not 1 <= limit <= 50 or offset < 0:
        raise social.bad("limit must be 1..50 and offset >= 0")
    return limit, offset

def _qv(q, k):
    v = q.get(k, [None])[0]
    return v.strip() if isinstance(v, str) and v.strip() else None

def me_out(c, a):
    return {"user_id": a["user_id"], "username": a["username"], "email": a["email"], "email_verified": bool(a["email_verified_at"]),
            "display_name": a["display_name"], "bio": a["bio"], "account_type": a["account_type"], "private_profile": bool(a["private_profile"]),
            "tipster_application": a["tipster_application"], "creator_verified": bool(a["creator_verified"]),
            "avatar": (social.media_out(c, a["avatar_media_id"]) or {}).get("urls", {}).get("thumb") if a["avatar_media_id"] else None}

def dispatch(c, h, who, method, P, q, body_fn, helpers):
    """Returns (status, body) or None when the path is not ours."""
    ip = h.headers.get("X-Forwarded-For", h.client_address[0]).split(",")[0].strip()
    ua = h.headers.get("User-Agent", "")
    vid = who["user_id"] if who and who.get("account") else None
    if not P:
        return None
    head = P[0]
    # ---------------------------------------------------------------- auth
    if head == "auth" and method == "POST" and len(P) == 2:
        d = body_fn()
        fn = {"register": lambda: auth.register(c, d), "verify-email": lambda: auth.verify_email(c, d),
              "resend-verification": lambda: auth.resend_verification(c, d), "login": lambda: auth.login(c, d, ua),
              "request-password-reset": lambda: auth.request_reset(c, d), "reset-password": lambda: auth.reset_password(c, d)}.get(P[1])
        if P[1] == "logout":
            auth.logout(c, h.headers.get("Authorization", "").removeprefix("Bearer ").strip(), bool(d.get("everywhere")), vid)
            return 200, {"logged_out": True}
        if fn:
            return (201 if P[1] == "register" else 200), fn()
        return None
    # ---------------------------------------------------------------- me
    if head == "me" and P != ["me", "preferences"]:
        a = _need_acct(who)
        if method == "GET" and P == ["me"]:
            return 200, me_out(c, a)
        if method == "GET" and P == ["me", "notifications"]:
            limit, offset = _page(q)
            return 200, social.notifications(c, a["user_id"], limit, offset, _qv(q, "unread") == "1")
        if method == "GET" and P == ["me", "dashboard"]:
            return 200, social.dashboard(c, a)
        if method == "GET" and P == ["me", "blocked"]:
            return 200, {"items": [dict(r) for r in c.execute("SELECT a.username FROM blocks b JOIN accounts a ON a.user_id=b.blocked_id WHERE b.blocker_id=?", (a["user_id"],))]}
        if method in ("POST", "PUT"):
            d = body_fn()
            if P == ["me", "profile"]:
                upd = {}
                if "display_name" in d:
                    dn = str(d["display_name"] or "").strip()
                    if not 1 <= len(dn) <= 60:
                        raise social.bad("display name must be 1-60 characters")
                    upd["display_name"] = dn
                if "bio" in d:
                    if len(str(d["bio"] or "")) > 500:
                        raise social.bad("bio is limited to 500 characters")
                    upd["bio"] = str(d["bio"] or "").strip() or None
                if "private_profile" in d:
                    upd["private_profile"] = 1 if d["private_profile"] else 0
                for k, purpose in (("avatar_media_id", "avatar"), ("cover_media_id", "cover")):
                    if k in d:
                        m = c.execute("SELECT * FROM media_assets WHERE id=? AND owner_id=? AND purpose=? AND status='ready'", (d[k], a["user_id"], purpose)).fetchone()
                        if d[k] is not None and not m:
                            raise social.bad("%s must be your processed %s image" % (k, purpose))
                        upd[k] = d[k]
                if not upd:
                    raise social.bad("nothing to update")
                c.execute("UPDATE accounts SET %s, updated_at=? WHERE user_id=?" % ",".join(k + "=?" for k in upd), list(upd.values()) + [now(), a["user_id"]])
                return 200, me_out(c, c.execute("SELECT * FROM accounts WHERE user_id=?", (a["user_id"],)).fetchone())
            if P == ["me", "password"]:
                return 200, auth.change_password(c, a, d)
            if P == ["me", "delete"]:
                return 200, auth.delete_account(c, a, d, media.remove_media)
            if P == ["me", "tipster-application"]:
                social.require_verified(a)
                if a["account_type"] in ("tipster", "expert_tipster"):
                    raise social.SocialError(409, "ALREADY_TIPSTER", "you are already a tipster")
                c.execute("UPDATE accounts SET tipster_application='pending', updated_at=? WHERE user_id=?", (now(), a["user_id"]))
                return 200, {"tipster_application": "pending"}
            if P == ["me", "notifications", "read"]:
                ids = d.get("ids")
                if ids == "all":
                    c.execute("UPDATE notifications SET read_at=? WHERE user_id=? AND read_at IS NULL", (now(), a["user_id"]))
                elif isinstance(ids, list):
                    c.executemany("UPDATE notifications SET read_at=? WHERE user_id=? AND id=?", [(now(), a["user_id"], int(i)) for i in ids])
                return 200, {"ok": True}
        return None
    # ---------------------------------------------------------------- media uploads
    if head == "media":
        if method == "POST" and P == ["media", "uploads"]:
            a = _need_acct(who)
            social.require_verified(a)
            return 201, media.init_upload(c, a["user_id"], body_fn())
        if len(P) >= 3 and P[:2] == ["media", "uploads"]:
            mid = int(P[2])
            a = _need_acct(who)
            m = c.execute("SELECT * FROM media_assets WHERE id=?", (mid,)).fetchone()
            if not m or m["owner_id"] != a["user_id"]:
                raise social.SocialError(404, "NOT_FOUND", "upload not found")
            if method == "GET" and len(P) == 3:
                out = {"media_id": mid, "status": m["status"], "received_bytes": m["received_bytes"], "declared_bytes": m["declared_bytes"], "error": m["error"],
                       "renditions": social.media_out(c, mid)["urls"]}
                if m["status"] == "uploading":
                    out["upload_url"] = media.upload_url(mid)  # fresh signed URL to resume
                return 200, out
            if method == "POST" and len(P) == 4 and P[3] == "complete":
                return 200, media.complete_upload(c, mid)
        return None
    # ---------------------------------------------------------------- social
    if head == "social":
        if method == "GET":
            if P == ["social", "feed"]:
                limit, offset = _page(q)
                return 200, social.feed(c, _qv(q, "feed") or "for_you", vid, limit, offset, _qv(q, "match_id"), _qv(q, "tag"), _qv(q, "username"), _qv(q, "q"),
                                       _qv(q, "dataset") or "verified")
            if P == ["social", "hashtags", "trending"]:
                return 200, {"items": social.trending_hashtags(c)}
            if P == ["social", "leaderboard"]:
                cid = _qv(q, "competition_id")
                return 200, social.leaderboard(c, _qv(q, "board") or "overall", int(cid) if cid else None, int(_qv(q, "min_settled") or 5),
                                               me_user_id=vid)
            if P == ["social", "search", "users"]:
                qq = _qv(q, "q") or ""
                if len(qq) < 2:
                    raise social.bad("search needs at least 2 characters")
                rows = c.execute("""SELECT username, display_name, account_type FROM accounts WHERE status='active' AND (username LIKE ? OR display_name LIKE ?)
                                    ORDER BY username LIMIT 20""", ("%" + qq[:40] + "%", "%" + qq[:40] + "%")).fetchall()
                return 200, {"items": [dict(r) for r in rows]}
            if len(P) == 3 and P[1] == "posts":
                return 200, social.post_out(c, social.visible_post(c, int(P[2]), vid), vid)
            if len(P) == 4 and P[1] == "posts" and P[3] == "comments":
                limit, offset = _page(q)
                return 200, social.list_comments(c, int(P[2]), vid, limit, offset)
            if len(P) == 4 and P[1] == "posts" and P[3] == "edits":
                social.visible_post(c, int(P[2]), vid)
                return 200, {"items": [dict(r) for r in c.execute("SELECT old_body, edited_at FROM post_edits WHERE post_id=? ORDER BY id", (int(P[2]),))]}
            if len(P) == 3 and P[1] == "users":
                return 200, social.profile(c, P[2], vid)
            if len(P) == 4 and P[1] == "users" and P[3] in ("followers", "following"):
                t = c.execute("SELECT user_id FROM accounts WHERE username=? AND status='active'", (P[2].lower(),)).fetchone()
                if not t:
                    raise social.SocialError(404, "NOT_FOUND", "user not found")
                col, other = ("followee_id", "follower_id") if P[3] == "followers" else ("follower_id", "followee_id")
                rows = c.execute("SELECT a.username, a.display_name FROM follows f JOIN accounts a ON a.user_id=f.%s WHERE f.%s=? AND a.status='active' ORDER BY f.created_at DESC LIMIT 100" % (other, col), (t[0],)).fetchall()
                return 200, {"items": [dict(r) for r in rows]}
            if len(P) == 4 and P[1] == "users" and P[3] == "predictions":
                limit, offset = _page(q)
                return 200, social.prediction_history(c, P[2], limit, offset)
            return None
        if method == "POST":
            d = body_fn()
            if P == ["social", "posts"]:
                a = _need_acct(who)
                return 201, social.create_post(c, a, d, helpers["create_prediction"])
            if P == ["social", "reports"]:
                return 201, social.report(c, _need_acct(who), d)
            if len(P) == 4 and P[1] == "posts":
                pid = int(P[2])
                act = P[3]
                if act == "view":
                    social.visible_post(c, pid, vid)
                    return 200, social.record_view(c, pid, vid, ip, ua)
                if act == "watch":
                    social.visible_post(c, pid, vid)
                    return 200, social.record_watch(c, pid, vid, ip, ua, d)
                if act == "share":
                    return 200, social.share(c, pid, vid, d.get("channel", "link"))
                a = _need_acct(who)
                fns = {"like": lambda: social.react(c, a, pid, True, d.get("kind", "like"), ip), "unlike": lambda: social.react(c, a, pid, False),
                       "comments": lambda: social.comment(c, a, pid, d), "save": lambda: social.bookmark(c, a, pid, True),
                       "unsave": lambda: social.bookmark(c, a, pid, False), "vote": lambda: social.vote(c, a, pid, d.get("option")),
                       "edit": lambda: social.edit_post(c, a, pid, d), "delete": lambda: social.delete_post(c, a, pid, media.remove_media)}
                if act in fns:
                    return 200, fns[act]()
            if len(P) == 4 and P[1] == "users" and P[3] in ("follow", "unfollow", "block", "unblock"):
                a = _need_acct(who)
                if P[3] in ("follow", "unfollow"):
                    return 200, social.follow(c, a, P[2], P[3] == "follow")
                return 200, social.block(c, a, P[2], P[3] == "block")
        return None
    # ---------------------------------------------------------------- cricket game (virtual; never mixed with real results)
    if head == "game":
        if method == "POST" and P == ["game", "simulate"]:
            a = _need_acct(who)
            social.rate_check(c, a["user_id"], "game_matches", "created_by", 20, 60)
            d = body_fn()
            try:
                res, events, teams = game.simulate(d.get("format", "T20"), d.get("home"), d.get("away"), d.get("seed"))
            except game.LawsError as e:
                raise social.bad(str(e))
            gid = game.store(c, a["user_id"], d.get("format", "T20"), res, events, teams)
            return 201, {"game_id": gid, "result": res}
        if method == "GET" and P == ["game"]:
            rows = c.execute("SELECT id, format, seed, result_json, created_at FROM game_matches ORDER BY id DESC LIMIT 20").fetchall()
            return 200, {"items": [dict(id=r["id"], format=r["format"], seed=r["seed"], created_at=r["created_at"], result=json.loads(r["result_json"])) for r in rows],
                         "note": "Virtual games are simulations and never count as real cricket results."}
        if method == "GET" and len(P) == 2:
            g = c.execute("SELECT * FROM game_matches WHERE id=?", (int(P[1]),)).fetchone()
            if not g:
                raise social.SocialError(404, "NOT_FOUND", "game not found")
            ev = [json.loads(r[0]) for r in c.execute("SELECT payload FROM game_events WHERE game_id=? ORDER BY seq", (g["id"],))]
            return 200, {"game_id": g["id"], "virtual": True, "result": json.loads(g["result_json"]), "teams": json.loads(g["config_json"]), "events": ev}
        return None
    return None

def match_extras(c, mid, P, q, who, helpers):
    """Match Center additions: Community (SH AI, tipster picks, posts kept apart) and replay directives."""
    vid = who["user_id"] if who and who.get("account") else None
    if P[2] == "community":
        sig = helpers["signals"](c, mid)
        picks = c.execute("""SELECT po.id AS post_id, a.username, a.display_name, x.verified, p.prediction_type, t.name AS pick, p.confidence, p.locked_at,
                             pp.published_at, e.result FROM posts po JOIN predictions p ON p.id=po.prediction_id JOIN accounts a ON a.user_id=po.author_id
                             JOIN expert_profiles x ON x.id=p.expert_id LEFT JOIN teams t ON t.id=p.predicted_team_id
                             JOIN prediction_publications pp ON pp.prediction_id=p.id
                             LEFT JOIN prediction_evaluations e ON e.prediction_id=p.id AND e.superseded_at IS NULL
                             WHERE po.match_id=? AND po.status='published' AND a.status='active' ORDER BY pp.published_at""", (mid,)).fetchall()
        res = c.execute("SELECT r.result_type, t.name FROM match_results r LEFT JOIN teams t ON t.id=r.winner_team_id WHERE r.match_id=?", (mid,)).fetchone()
        limit, offset = _page(q)
        return {"match_id": mid,
                "sh_ai": {"home_win_probability": sig["pre_match"]["home_win_probability"], "away_win_probability": sig["pre_match"]["away_win_probability"],
                          "label": "SH AI model (separate from tipsters)"},
                "tipster_picks": [dict(r) for r in picks],
                "verified_result": {"result_type": res[0], "winner": res[1]} if res else None,
                "posts": social.feed(c, "match", vid, limit, offset, match_id=mid),
                "note": "Tipster picks are locked when posted and settled against the verified result; SH AI and tipsters are shown separately."}
    if P[2] == "replay":
        rows = [dict(r) for r in c.execute("""SELECT b.innings_no, b.seq, b.over_no, b.ball_in_over, b.runs_bat, b.extras, b.extra_type, b.is_wicket, b.wicket_kind,
                                              bt.name AS batter, bw.name AS bowler FROM ball_events b LEFT JOIN players bt ON bt.id=b.batter_id
                                              LEFT JOIN players bw ON bw.id=b.bowler_id WHERE b.match_id=? ORDER BY b.innings_no, b.seq""", (mid,))]
        return {"match_id": mid, "mode": "real_match_replay", "events": game.replay_directives(rows, seed=mid),
                "note": "Outcomes are real recorded deliveries; ball paths are reconstructions because trajectories were not recorded."}
    return None

def admin_dispatch(c, who, method, A, q, body_fn):
    actor = who["actor"]
    if method == "GET":
        if A == ("social", "users"):
            qq = _qv(q, "q")
            sql = """SELECT a.user_id, a.username, a.email, a.email_verified_at, a.account_type, a.status, a.tipster_application, a.creator_verified, a.created_at,
                     (SELECT COUNT(*) FROM posts p WHERE p.author_id=a.user_id) AS posts, (SELECT COUNT(*) FROM reports r WHERE r.target_type='user' AND r.target_id=a.user_id AND r.status='open') AS open_reports
                     FROM accounts a"""
            args = []
            if qq:
                sql += " WHERE a.username LIKE ? OR a.email LIKE ?"; args = ["%" + qq + "%"] * 2
            return 200, {"items": [dict(r) for r in c.execute(sql + " ORDER BY a.user_id DESC LIMIT 200", args)]}
        if A == ("social", "reports"):
            rows = c.execute("SELECT r.*, a.username AS reporter FROM reports r JOIN accounts a ON a.user_id=r.reporter_id WHERE r.status=? ORDER BY r.id DESC LIMIT 200",
                             (_qv(q, "status") or "open",)).fetchall()
            out = []
            for r in rows:
                d = dict(r)
                if r["target_type"] == "post":
                    p = c.execute("SELECT id, body, kind, status, author_id FROM posts WHERE id=?", (r["target_id"],)).fetchone()
                    d["target"] = dict(p) if p else None
                elif r["target_type"] == "comment":
                    cm = c.execute("SELECT id, body, status, post_id FROM comments WHERE id=?", (r["target_id"],)).fetchone()
                    d["target"] = dict(cm) if cm else None
                else:
                    u = c.execute("SELECT user_id, username, status FROM accounts WHERE user_id=?", (r["target_id"],)).fetchone()
                    d["target"] = dict(u) if u else None
                out.append(d)
            return 200, {"items": out}
        if A == ("social", "posts"):
            rows = c.execute("SELECT p.id, p.kind, p.body, p.status, p.created_at, a.username FROM posts p JOIN accounts a ON a.user_id=p.author_id ORDER BY p.id DESC LIMIT 200").fetchall()
            return 200, {"items": [dict(r) for r in rows]}
        if A == ("social", "spam"):
            return 200, social.spam_signals(c)
        if A == ("social", "moderation-log"):
            return 200, {"items": [dict(r) for r in c.execute("SELECT * FROM moderation_actions ORDER BY id DESC LIMIT 200")]}
        if A == ("media", "jobs"):
            return 200, {"items": [dict(r) for r in c.execute("""SELECT j.*, m.kind, m.purpose, m.status AS media_status, m.error AS media_error FROM jobs j
                                                                  LEFT JOIN media_assets m ON m.id=j.ref_id ORDER BY j.id DESC LIMIT 100""")]}
        if A == ("media", "storage"):
            st = media.storage().usage()
            st["assets"] = {r[0]: r[1] for r in c.execute("SELECT status, COUNT(*) FROM media_assets GROUP BY status")}
            st["tools"] = media.tools()
            st["warning"] = "SH_MEDIA_DIR must be on a persistent disk or replaced by object storage; ephemeral disks lose media on restart."
            return 200, st
        if A == ("mail", "outbox"):
            return 200, {"items": [dict(r) for r in c.execute("SELECT id, to_address, subject, status, error, created_at, sent_at FROM mail_outbox ORDER BY id DESC LIMIT 100")],
                         "smtp_configured": auth.smtp_configured(), "note": "Message bodies (codes) are never shown here."}
        return None
    d = body_fn()
    if A == ("social", "moderate"):
        r = social.moderate(c, actor, d, media.remove_media)
        return 200, r
    if A == ("media", "cleanup"):
        return 200, media.cleanup(c, int(d.get("max_age_hours", 24)))
    if A == ("media", "retry"):
        j = c.execute("SELECT * FROM jobs WHERE id=? AND status='failed'", (d.get("job_id"),)).fetchone()
        if not j:
            raise social.SocialError(404, "NOT_FOUND", "failed job not found")
        c.execute("UPDATE media_assets SET status='processing', error=NULL WHERE id=?", (j["ref_id"],))
        c.execute("UPDATE jobs SET status='queued', updated_at=? WHERE id=?", (now(), j["id"]))
        return 200, {"requeued": j["id"]}
    if len(A) == 3 and A[0] == "users" and A[2] == "verify-email":
        uid = int(A[1])
        if not c.execute("UPDATE accounts SET email_verified_at=COALESCE(email_verified_at, ?) WHERE user_id=?", (now(), uid)).rowcount:
            raise social.SocialError(404, "NOT_FOUND", "account not found")
        c.execute("INSERT INTO moderation_actions(actor,action,target_type,target_id,reason,created_at) VALUES(?,?,?,?,?,?)",
                  (actor, "manual_email_verification", "user", uid, d.get("reason") or "admin verified identity", now()))
        return 200, {"user_id": uid, "email_verified": True}
    return None

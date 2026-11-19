"""SH SOCIAL: posts, feeds, reels, engagement, profiles, tipster leaderboard, creator dashboard, notifications, moderation.

Rules that keep it honest:
* Prediction posts create a separate, locked prediction record (pre-match only). The post text can be edited
  (edit history kept); the pick can never change. The pick is published by the tipster's own post.
* Views: one view per viewer per post per UTC day (viewer = account id, or a salted hash of IP + user agent for
  signed-out viewers). Authors viewing their own posts are not counted. Counts are computed from records, never stored as
  editable numbers.
* Watch time: reported by the player in sessions; capped at the video length; a session counts as completed at >= 90%.
* Accuracy: only locked, eligible, settled predictions (no pending, void or late picks); sample size always shown.
"""
import datetime
import hashlib
import json
import math
import os
import re

import engine
from schema import now

POST_KINDS = ("text", "photo", "video", "reel", "prediction", "analysis", "pitch_report", "toss_prediction", "playing_xi", "fantasy", "poll")
HASHTAG_RE = re.compile(r"(?<!\w)#([A-Za-z0-9_]{2,40})")
MENTION_RE = re.compile(r"(?<!\w)@([a-z0-9_]{3,24})")
VIEW_SALT = (os.getenv("SH_VIEW_SALT") or os.urandom(16).hex())

class SocialError(Exception):
    def __init__(self, status, code, message):
        super().__init__(message)
        self.status, self.code, self.message = status, code, message

def bad(m):
    return SocialError(400, "VALIDATION_ERROR", m)

def notify(c, user_id, kind, params):
    if user_id:
        c.execute("INSERT INTO notifications(user_id,kind,message_key,params_json,created_at) VALUES(?,?,?,?,?)",
                  (user_id, kind, "notify." + kind, json.dumps(params), now()))

def blocked_between(c, a, b):
    return bool(a and b and c.execute("SELECT 1 FROM blocks WHERE (blocker_id=? AND blocked_id=?) OR (blocker_id=? AND blocked_id=?)", (a, b, b, a)).fetchone())

def require_verified(acct):
    if not acct["email_verified_at"]:
        raise SocialError(403, "EMAIL_NOT_VERIFIED", "verify your email before posting or interacting")

def rate_check(c, uid, table, col, limit, minutes):
    since = (datetime.datetime.now(datetime.timezone.utc) - datetime.timedelta(minutes=minutes)).isoformat()
    n = c.execute("SELECT COUNT(*) FROM %s WHERE %s=? AND created_at>=?" % (table, col), (uid, since)).fetchone()[0]
    if n >= limit:
        raise SocialError(429, "RATE_LIMITED", "slow down: too many actions in a short time")

# ------------------------------------------------------------------ posts
def _tags(c, post_id, body):
    c.execute("DELETE FROM post_hashtags WHERE post_id=?", (post_id,))
    c.execute("DELETE FROM mentions WHERE post_id=?", (post_id,))
    for t in {x.lower() for x in HASHTAG_RE.findall(body)}:
        c.execute("INSERT OR IGNORE INTO hashtags(tag) VALUES(?)", (t,))
        hid = c.execute("SELECT id FROM hashtags WHERE tag=?", (t,)).fetchone()[0]
        c.execute("INSERT OR IGNORE INTO post_hashtags(post_id,hashtag_id) VALUES(?,?)", (post_id, hid))
    mentioned = []
    for u in set(MENTION_RE.findall(body)):
        r = c.execute("SELECT user_id FROM accounts WHERE username=? AND status='active'", (u,)).fetchone()
        if r:
            c.execute("INSERT OR IGNORE INTO mentions(post_id,user_id) VALUES(?,?)", (post_id, r[0]))
            mentioned.append(r[0])
    return mentioned

def create_post(c, acct, d, create_prediction):
    require_verified(acct)
    uid = acct["user_id"]
    lim = int((c.execute("SELECT value FROM system_settings WHERE key='posts_per_hour_limit'").fetchone() or [20])[0])
    rate_check(c, uid, "posts", "author_id", lim, 60)
    kind = d.get("kind", "text")
    if kind not in POST_KINDS:
        raise bad("kind must be one of " + ", ".join(POST_KINDS))
    body = str(d.get("body") or "").strip()
    if len(body) > 5000:
        raise bad("post text is limited to 5000 characters")
    media_ids = d.get("media_ids") or []
    if not isinstance(media_ids, list) or len(media_ids) > 10 or not all(isinstance(x, int) for x in media_ids):
        raise bad("media_ids must be a list of up to 10 ids")
    if kind == "photo" and not media_ids:
        raise bad("a photo post needs at least one image")
    if kind in ("video", "reel") and len(media_ids) != 1:
        raise bad("a %s post needs exactly one video" % kind)
    if kind in ("text", "analysis", "pitch_report", "playing_xi", "fantasy") and not body and not media_ids:
        raise bad("write something first")
    match_id = d.get("match_id")
    if match_id is not None:
        if not c.execute("SELECT 1 FROM matches WHERE id=?", (int(match_id),)).fetchone():
            raise bad("unknown match_id")
        match_id = int(match_id)
    if kind in ("prediction", "toss_prediction") and not match_id:
        raise bad("prediction posts must be tagged to a match")
    # duplicate-text spam guard
    if body and c.execute("SELECT 1 FROM posts WHERE author_id=? AND body=? AND created_at>=? AND status='published'",
                          (uid, body, (datetime.datetime.now(datetime.timezone.utc) - datetime.timedelta(hours=1)).isoformat())).fetchone():
        raise SocialError(409, "DUPLICATE", "you just posted the same text")
    statuses = []
    for mid in media_ids:
        m = c.execute("SELECT * FROM media_assets WHERE id=?", (mid,)).fetchone()
        if not m or m["owner_id"] != uid or m["status"] in ("removed", "failed", "uploading"):
            raise bad("media %d is not yours or not uploaded" % mid)
        if c.execute("SELECT 1 FROM post_media WHERE media_id=?", (mid,)).fetchone():
            raise bad("media %d is already used in another post" % mid)
        want = "image" if kind == "photo" else ("video" if kind in ("video", "reel") else m["kind"])
        if m["kind"] != want:
            raise bad("media %d is not a %s" % (mid, want))
        if kind == "reel" and m["purpose"] != "reel":
            raise bad("upload the video with purpose 'reel' so it is formatted 9:16")
        statuses.append(m["status"])
    prediction_id = None
    if kind in ("prediction", "toss_prediction"):
        ex = c.execute("SELECT * FROM expert_profiles WHERE user_id=?", (uid,)).fetchone()
        if acct["account_type"] not in ("tipster", "expert_tipster") or not ex:
            raise SocialError(403, "NOT_A_TIPSTER", "apply for Tipster status to post predictions")
        ptype = "toss" if kind == "toss_prediction" else d.get("prediction_type", "winner")
        who = {"user_id": uid, "role": "expert", "actor": "user:%d" % uid}
        res = create_prediction(c, who, {"match_id": match_id, "prediction_type": ptype, "predicted_team_id": d.get("predicted_team_id"),
                                         "predicted_value": d.get("predicted_value"), "confidence": d.get("confidence"),
                                         "explanation": body[:2000] or None, "lock": True}, allow_unverified_expert=True)
        prediction_id = res["prediction_id"]
        c.execute("INSERT OR IGNORE INTO prediction_publications(prediction_id,published_at,published_by,public_note) VALUES(?,?,?,?)",
                  (prediction_id, now(), "tipster-post:%d" % uid, None))
    status = "published" if all(s == "ready" for s in statuses) else "processing"
    origin = "demo" if d.get("demo") else "verified"
    c.execute("INSERT INTO posts(author_id,kind,body,match_id,prediction_id,status,created_at,data_origin) VALUES(?,?,?,?,?,?,?,?)",
              (uid, kind, body, match_id, prediction_id, status, now(), origin))
    pid = c.execute("SELECT last_insert_rowid()").fetchone()[0]
    for i, mid in enumerate(media_ids):
        c.execute("INSERT INTO post_media(post_id,media_id,position) VALUES(?,?,?)", (pid, mid, i))
    if kind == "poll":
        opts = d.get("options")
        if not isinstance(opts, list) or not 2 <= len(opts) <= 6 or not all(isinstance(o, str) and 1 <= len(o.strip()) <= 80 for o in opts):
            raise bad("a poll needs 2-6 options of up to 80 characters")
        c.execute("INSERT INTO polls(post_id,options_json,closes_at) VALUES(?,?,?)", (pid, json.dumps([o.strip() for o in opts]), d.get("closes_at")))
    for m in _tags(c, pid, body):
        if m != uid:
            notify(c, m, "mention", {"post_id": pid, "by": acct["username"]})
    if status == "published":
        _notify_followers(c, uid, pid, acct["username"])
    return {"post_id": pid, "status": status, "prediction_id": prediction_id}

def _notify_followers(c, uid, pid, username):
    for f in c.execute("SELECT follower_id FROM follows WHERE followee_id=? LIMIT 500", (uid,)).fetchall():
        notify(c, f[0], "new_post", {"post_id": pid, "by": username})

def on_media_ready(c, media_id):
    """Called by the media worker: publish posts whose media are all ready."""
    for p in c.execute("SELECT p.* FROM posts p JOIN post_media pm ON pm.post_id=p.id WHERE pm.media_id=? AND p.status='processing'", (media_id,)).fetchall():
        pending = c.execute("""SELECT COUNT(*) FROM post_media pm JOIN media_assets m ON m.id=pm.media_id WHERE pm.post_id=? AND m.status<>'ready'""", (p["id"],)).fetchone()[0]
        if not pending:
            c.execute("UPDATE posts SET status='published' WHERE id=?", (p["id"],))
            a = c.execute("SELECT username FROM accounts WHERE user_id=?", (p["author_id"],)).fetchone()
            notify(c, p["author_id"], "media_ready", {"post_id": p["id"]})
            _notify_followers(c, p["author_id"], p["id"], a[0] if a else "")

def edit_post(c, acct, pid, d):
    p = c.execute("SELECT * FROM posts WHERE id=?", (pid,)).fetchone()
    if not p or p["status"] in ("deleted", "removed"):
        raise SocialError(404, "NOT_FOUND", "post not found")
    if p["author_id"] != acct["user_id"]:
        raise SocialError(403, "FORBIDDEN", "only the author can edit this post")
    body = str(d.get("body") or "").strip()
    if len(body) > 5000:
        raise bad("post text is limited to 5000 characters")
    if body == p["body"]:
        return {"post_id": pid, "edited": False}
    c.execute("INSERT INTO post_edits(post_id,old_body,edited_at) VALUES(?,?,?)", (pid, p["body"], now()))
    c.execute("UPDATE posts SET body=?, edited_at=? WHERE id=?", (body, now(), pid))
    _tags(c, pid, body)
    return {"post_id": pid, "edited": True, "note": "the locked pick of a prediction post never changes" if p["prediction_id"] else None}

def delete_post(c, acct, pid, remove_media, by_admin=False):
    p = c.execute("SELECT * FROM posts WHERE id=?", (pid,)).fetchone()
    if not p or p["status"] == "deleted":
        raise SocialError(404, "NOT_FOUND", "post not found")
    if not by_admin and p["author_id"] != acct["user_id"]:
        raise SocialError(403, "FORBIDDEN", "only the author can delete this post")
    c.execute("UPDATE posts SET status='deleted' WHERE id=?", (pid,))
    for m in c.execute("SELECT media_id FROM post_media WHERE post_id=?", (pid,)).fetchall():
        remove_media(c, m[0])
    # a deleted prediction post keeps its locked pick in the record (no cherry-picking by deleting losers)
    return {"post_id": pid, "deleted": True, "prediction_kept": bool(p["prediction_id"])}

# ------------------------------------------------------------------ reading
def media_out(c, mid):
    m = c.execute("SELECT * FROM media_assets WHERE id=?", (mid,)).fetchone()
    if not m:
        return None
    r = {x["kind"]: "/media/" + x["path"] for x in c.execute("SELECT * FROM media_renditions WHERE media_id=?", (mid,))}
    return {"id": mid, "kind": m["kind"], "status": m["status"], "width": m["width"], "height": m["height"], "duration_ms": m["duration_ms"], "urls": r}

def _author(c, uid):
    a = c.execute("SELECT user_id,username,display_name,account_type,creator_verified,avatar_media_id,status FROM accounts WHERE user_id=?", (uid,)).fetchone()
    if not a:
        return {"user_id": uid, "username": None, "display_name": "SH user"}
    ex = c.execute("SELECT id, verified FROM expert_profiles WHERE user_id=?", (uid,)).fetchone()
    av = media_out(c, a["avatar_media_id"]) if a["avatar_media_id"] else None
    return {"user_id": uid, "username": a["username"], "display_name": a["display_name"], "account_type": a["account_type"],
            "verified_expert": bool(ex and ex["verified"]), "creator_verified": bool(a["creator_verified"]),
            "avatar": av["urls"].get("thumb") if av else None}

def counts(c, pid):
    one = lambda sql: c.execute(sql, (pid,)).fetchone()[0]
    return {"views": one("SELECT COUNT(*) FROM post_views WHERE post_id=?"), "likes": one("SELECT COUNT(*) FROM reactions WHERE post_id=?"),
            "comments": one("SELECT COUNT(*) FROM comments WHERE post_id=? AND status='visible'"), "shares": one("SELECT COUNT(*) FROM shares WHERE post_id=?"),
            "saves": one("SELECT COUNT(*) FROM bookmarks WHERE post_id=?")}

def post_out(c, p, viewer_id=None):
    d = {k: p[k] for k in ("id", "author_id", "kind", "body", "match_id", "status", "created_at", "edited_at", "data_origin")}
    d["author"] = _author(c, p["author_id"])
    d["media"] = [media_out(c, r[0]) for r in c.execute("SELECT media_id FROM post_media WHERE post_id=? ORDER BY position", (p["id"],))]
    d["counts"] = counts(c, p["id"])
    d["hashtags"] = [r[0] for r in c.execute("SELECT h.tag FROM post_hashtags ph JOIN hashtags h ON h.id=ph.hashtag_id WHERE ph.post_id=?", (p["id"],))]
    d["edits"] = c.execute("SELECT COUNT(*) FROM post_edits WHERE post_id=?", (p["id"],)).fetchone()[0]
    if p["match_id"]:
        m = c.execute("""SELECT m.id, h.name AS home, a.name AS away, m.start_utc FROM matches m JOIN teams h ON h.id=m.home_team_id
                         JOIN teams a ON a.id=m.away_team_id WHERE m.id=?""", (p["match_id"],)).fetchone()
        d["match"] = dict(m) if m else None
    if p["prediction_id"]:
        pr = c.execute("""SELECT p.prediction_type, p.predicted_value, p.confidence, p.created_at, p.locked_at, t.name AS team, e.result, e.rule,
                          pp.published_at FROM predictions p LEFT JOIN teams t ON t.id=p.predicted_team_id
                          LEFT JOIN prediction_evaluations e ON e.prediction_id=p.id AND e.superseded_at IS NULL
                          LEFT JOIN prediction_publications pp ON pp.prediction_id=p.id WHERE p.id=?""", (p["prediction_id"],)).fetchone()
        d["pick"] = dict(pr) if pr else None
        if d["pick"] and p["match_id"]:
            r = c.execute("SELECT r.result_type, t.name FROM match_results r LEFT JOIN teams t ON t.id=r.winner_team_id WHERE r.match_id=?", (p["match_id"],)).fetchone()
            d["pick"]["match_result"] = {"result_type": r[0], "winner": r[1]} if r else None
    if p["kind"] == "poll":
        pl = c.execute("SELECT * FROM polls WHERE post_id=?", (p["id"],)).fetchone()
        if pl:
            opts = json.loads(pl["options_json"])
            votes = [c.execute("SELECT COUNT(*) FROM poll_votes WHERE post_id=? AND option_index=?", (p["id"], i)).fetchone()[0] for i in range(len(opts))]
            d["poll"] = {"options": opts, "votes": votes, "closes_at": pl["closes_at"],
                         "my_vote": (c.execute("SELECT option_index FROM poll_votes WHERE post_id=? AND user_id=?", (p["id"], viewer_id)).fetchone() or [None])[0] if viewer_id else None}
    if viewer_id:
        d["me"] = {"liked": bool(c.execute("SELECT 1 FROM reactions WHERE post_id=? AND user_id=?", (p["id"], viewer_id)).fetchone()),
                   "saved": bool(c.execute("SELECT 1 FROM bookmarks WHERE post_id=? AND user_id=?", (p["id"], viewer_id)).fetchone()),
                   "following_author": bool(c.execute("SELECT 1 FROM follows WHERE follower_id=? AND followee_id=?", (viewer_id, p["author_id"])).fetchone()),
                   "is_author": viewer_id == p["author_id"]}
    return d

def _visible_sql(viewer_id):
    """Published posts by active accounts, private profiles only for followers, nothing across a block."""
    base = """p.status='published' AND EXISTS(SELECT 1 FROM accounts a WHERE a.user_id=p.author_id AND a.status='active'
              AND (a.private_profile=0 OR a.user_id=:v OR EXISTS(SELECT 1 FROM follows f WHERE f.follower_id=:v AND f.followee_id=a.user_id)))"""
    if viewer_id:
        base += " AND NOT EXISTS(SELECT 1 FROM blocks b WHERE (b.blocker_id=:v AND b.blocked_id=p.author_id) OR (b.blocker_id=p.author_id AND b.blocked_id=:v))"
    return base

def visible_post(c, pid, viewer_id):
    p = c.execute("SELECT p.* FROM posts p WHERE p.id=:id AND " + _visible_sql(viewer_id), {"id": pid, "v": viewer_id or -1}).fetchone()
    if not p:
        raise SocialError(404, "NOT_FOUND", "post not found")
    return p

FEEDS = ("for_you", "following", "latest", "trending", "reels", "match", "hashtag", "user", "saved", "search")

def feed(c, kind, viewer_id, limit=20, offset=0, match_id=None, tag=None, username=None, q=None, dataset="verified"):
    if kind not in FEEDS:
        raise bad("feed must be one of " + ", ".join(FEEDS))
    args = {"v": viewer_id or -1, "lim": limit, "off": offset}
    # real people's posts always show; demo mode only adds the labelled DEMO posts (cricket results stay separate elsewhere)
    where = [_visible_sql(viewer_id), "p.data_origin IN ('verified', :ds)"]
    args["ds"] = "demo" if dataset == "demo" else "verified"
    order = "p.created_at DESC, p.id DESC"
    if kind == "following":
        if not viewer_id:
            raise SocialError(401, "UNAUTHENTICATED", "log in to see posts from people you follow")
        where.append("p.author_id IN (SELECT followee_id FROM follows WHERE follower_id=:v)")
    elif kind == "reels":
        where.append("p.kind='reel'")
    elif kind == "match":
        where.append("p.match_id=:m"); args["m"] = int(match_id or 0)
    elif kind == "hashtag":
        where.append("p.id IN (SELECT ph.post_id FROM post_hashtags ph JOIN hashtags h ON h.id=ph.hashtag_id WHERE h.tag=:t)"); args["t"] = str(tag or "").lower().lstrip("#")
    elif kind == "user":
        where.append("p.author_id=(SELECT user_id FROM accounts WHERE username=:u)"); args["u"] = str(username or "").lower()
    elif kind == "saved":
        if not viewer_id:
            raise SocialError(401, "UNAUTHENTICATED", "log in to see saved posts")
        where.append("p.id IN (SELECT post_id FROM bookmarks WHERE user_id=:v)")
    elif kind == "search":
        qq = str(q or "").strip()
        if len(qq) < 2:
            raise bad("search needs at least 2 characters")
        where.append("(p.body LIKE :q OR p.author_id IN (SELECT user_id FROM accounts WHERE username LIKE :q OR display_name LIKE :q))"); args["q"] = "%" + qq[:60] + "%"
    if kind in ("for_you", "trending", "reels"):
        # original ranking: engagement (log-scaled), freshness decay, interests from the viewer's likes and follows,
        # match relevance (upcoming/live matches), watch completion for reels, creator diversity (max 2 per author per page)
        since = (datetime.datetime.now(datetime.timezone.utc) - datetime.timedelta(days=2 if kind == "trending" else 30)).isoformat()
        where.append("p.created_at>=:since"); args["since"] = since
        rows = c.execute("SELECT p.* FROM posts p WHERE " + " AND ".join(where) + " ORDER BY p.created_at DESC LIMIT 500", args).fetchall()
        liked_tags = {r[0] for r in c.execute("""SELECT DISTINCT ph.hashtag_id FROM reactions r JOIN post_hashtags ph ON ph.post_id=r.post_id WHERE r.user_id=?""", (viewer_id or -1,))}
        followed = {r[0] for r in c.execute("SELECT followee_id FROM follows WHERE follower_id=?", (viewer_id or -1,))}
        hot_matches = {r[0] for r in c.execute("SELECT id FROM matches WHERE status IN ('live','scheduled') AND data_origin<>'demo'")}
        scored = []
        tnow = datetime.datetime.now(datetime.timezone.utc)
        for p in rows:
            k = counts(c, p["id"])
            age_h = max(0.0, (tnow - engine.pdt(p["created_at"])).total_seconds() / 3600)
            eng = math.log1p(k["likes"] * 3 + k["comments"] * 4 + k["shares"] * 5 + k["saves"] * 4 + k["views"] * 0.2)
            fresh = 1 / (1 + age_h / (12 if kind == "trending" else 24))
            interest = 0.0
            if kind != "trending":
                tags = {r[0] for r in c.execute("SELECT hashtag_id FROM post_hashtags WHERE post_id=?", (p["id"],))}
                interest = 0.8 * len(tags & liked_tags) + (1.0 if p["author_id"] in followed else 0)
            match_rel = 0.7 if p["match_id"] in hot_matches else 0
            completion = 0.0
            if p["kind"] in ("reel", "video"):
                w = c.execute("SELECT AVG(completed), COUNT(*) FROM watch_sessions WHERE post_id=?", (p["id"],)).fetchone()
                completion = (w[0] or 0) * 1.5 if w[1] else 0
            scored.append((eng * 1.2 + fresh * 3 + interest + match_rel + completion, p))
        scored.sort(key=lambda x: -x[0])
        per_author, ranked = {}, []
        for s, p in scored:  # creator diversity
            per_author[p["author_id"]] = per_author.get(p["author_id"], 0) + 1
            if per_author[p["author_id"]] <= 2 or kind == "reels" and per_author[p["author_id"]] <= 3:
                ranked.append(p)
        page = ranked[offset:offset + limit]
        return {"items": [post_out(c, p, viewer_id) for p in page], "limit": limit, "offset": offset, "feed": kind, "has_more": len(ranked) > offset + limit}
    rows = c.execute("SELECT p.* FROM posts p WHERE " + " AND ".join(where) + " ORDER BY " + order + " LIMIT :lim OFFSET :off", args).fetchall()
    return {"items": [post_out(c, p, viewer_id) for p in rows], "limit": limit, "offset": offset, "feed": kind, "has_more": len(rows) == limit}

def trending_hashtags(c, limit=10):
    since = (datetime.datetime.now(datetime.timezone.utc) - datetime.timedelta(days=2)).isoformat()
    return [{"tag": r[0], "posts": r[1]} for r in c.execute("""SELECT h.tag, COUNT(*) n FROM post_hashtags ph JOIN hashtags h ON h.id=ph.hashtag_id
        JOIN posts p ON p.id=ph.post_id WHERE p.status='published' AND p.created_at>=? GROUP BY h.tag ORDER BY n DESC LIMIT ?""", (since, limit))]

# ------------------------------------------------------------------ engagement
def record_view(c, pid, viewer_id, ip, ua):
    p = c.execute("SELECT author_id FROM posts WHERE id=?", (pid,)).fetchone()
    if not p or p[0] == viewer_id:
        return {"counted": False}
    key = "u:%d" % viewer_id if viewer_id else "a:" + hashlib.sha256((VIEW_SALT + (ip or "") + "|" + (ua or "")[:200]).encode()).hexdigest()[:32]
    day = datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%d")
    cur = c.execute("INSERT OR IGNORE INTO post_views(post_id,viewer_key,day,first_seen_at) VALUES(?,?,?,?)", (pid, key, day, now()))
    return {"counted": bool(cur.rowcount)}

def record_watch(c, pid, viewer_id, ip, ua, d):
    p = c.execute("SELECT p.*, m.duration_ms FROM posts p JOIN post_media pm ON pm.post_id=p.id JOIN media_assets m ON m.id=pm.media_id WHERE p.id=? AND m.kind='video'", (pid,)).fetchone()
    if not p:
        raise SocialError(404, "NOT_FOUND", "video post not found")
    dur = p["duration_ms"] or 0
    try:
        watched = max(0, min(int(d.get("watched_ms", 0)), dur))
    except (TypeError, ValueError):
        raise bad("watched_ms must be a number")
    key = "u:%d" % viewer_id if viewer_id else "a:" + hashlib.sha256((VIEW_SALT + (ip or "") + "|" + (ua or "")[:200]).encode()).hexdigest()[:32]
    if p["author_id"] != viewer_id:
        c.execute("INSERT INTO watch_sessions(post_id,viewer_key,watched_ms,duration_ms,completed,created_at) VALUES(?,?,?,?,?,?)",
                  (pid, key, watched, dur, 1 if dur and watched >= 0.9 * dur else 0, now()))
    return {"watched_ms": watched, "completed": bool(dur and watched >= 0.9 * dur)}

def react(c, acct, pid, on, kind="like", ip=None):
    require_verified(acct)
    p = visible_post(c, pid, acct["user_id"])
    if on:
        rate_check(c, acct["user_id"], "reactions", "user_id", 300, 60)
        if kind not in ("like", "fire", "clap", "wow"):
            raise bad("unknown reaction")
        cur = c.execute("INSERT OR REPLACE INTO reactions(post_id,user_id,kind,created_at,ip_hash) VALUES(?,?,?,?,?)",
                        (pid, acct["user_id"], kind, now(), hashlib.sha256((VIEW_SALT + (ip or "")).encode()).hexdigest()[:16]))
        if p["author_id"] != acct["user_id"]:
            notify(c, p["author_id"], "like", {"post_id": pid, "by": acct["username"]})
    else:
        c.execute("DELETE FROM reactions WHERE post_id=? AND user_id=?", (pid, acct["user_id"]))
    return {"post_id": pid, "liked": on, "likes": counts(c, pid)["likes"]}

def comment(c, acct, pid, d):
    require_verified(acct)
    p = visible_post(c, pid, acct["user_id"])
    rate_check(c, acct["user_id"], "comments", "user_id", 30, 10)
    body = str(d.get("body") or "").strip()
    if not 1 <= len(body) <= 1000:
        raise bad("comment must be 1-1000 characters")
    parent = d.get("parent_id")
    if parent is not None and not c.execute("SELECT 1 FROM comments WHERE id=? AND post_id=? AND status='visible'", (parent, pid)).fetchone():
        raise bad("reply target not found")
    c.execute("INSERT INTO comments(post_id,user_id,parent_id,body,created_at) VALUES(?,?,?,?,?)", (pid, acct["user_id"], parent, body, now()))
    cid = c.execute("SELECT last_insert_rowid()").fetchone()[0]
    if p["author_id"] != acct["user_id"]:
        notify(c, p["author_id"], "comment", {"post_id": pid, "comment_id": cid, "by": acct["username"]})
    for u in set(MENTION_RE.findall(body)):
        r = c.execute("SELECT user_id FROM accounts WHERE username=? AND status='active'", (u,)).fetchone()
        if r and r[0] != acct["user_id"]:
            notify(c, r[0], "mention", {"post_id": pid, "comment_id": cid, "by": acct["username"]})
    return {"comment_id": cid}

def list_comments(c, pid, viewer_id, limit=50, offset=0):
    visible_post(c, pid, viewer_id)
    rows = c.execute("""SELECT cm.*, a.username, a.display_name FROM comments cm JOIN accounts a ON a.user_id=cm.user_id
                        WHERE cm.post_id=? AND cm.status='visible' AND a.status='active' ORDER BY cm.id LIMIT ? OFFSET ?""", (pid, limit, offset)).fetchall()
    return {"items": [{k: r[k] for k in ("id", "parent_id", "body", "created_at", "username", "display_name", "user_id")} for r in rows],
            "limit": limit, "offset": offset}

def share(c, pid, viewer_id, channel):
    visible_post(c, pid, viewer_id)
    if channel not in ("link", "whatsapp", "sms", "telegram", "x", "facebook", "other"):
        raise bad("unknown share channel")
    c.execute("INSERT INTO shares(post_id,user_id,channel,created_at) VALUES(?,?,?,?)", (pid, viewer_id, channel, now()))
    return {"post_id": pid, "url": "/#/post/%d" % pid, "shares": counts(c, pid)["shares"]}

def bookmark(c, acct, pid, on):
    visible_post(c, pid, acct["user_id"])
    if on:
        c.execute("INSERT OR IGNORE INTO bookmarks(user_id,post_id,created_at) VALUES(?,?,?)", (acct["user_id"], pid, now()))
    else:
        c.execute("DELETE FROM bookmarks WHERE user_id=? AND post_id=?", (acct["user_id"], pid))
    return {"post_id": pid, "saved": on}

def vote(c, acct, pid, option):
    require_verified(acct)
    visible_post(c, pid, acct["user_id"])
    pl = c.execute("SELECT * FROM polls WHERE post_id=?", (pid,)).fetchone()
    if not pl:
        raise SocialError(404, "NOT_FOUND", "poll not found")
    if pl["closes_at"] and pl["closes_at"] < now():
        raise SocialError(409, "CLOSED", "poll closed")
    if not isinstance(option, int) or not 0 <= option < len(json.loads(pl["options_json"])):
        raise bad("invalid option")
    c.execute("INSERT OR REPLACE INTO poll_votes(post_id,user_id,option_index,created_at) VALUES(?,?,?,?)", (pid, acct["user_id"], option, now()))
    return {"post_id": pid, "voted": option}

def follow(c, acct, username, on):
    t = c.execute("SELECT user_id, status FROM accounts WHERE username=?", (str(username).lower(),)).fetchone()
    if not t or t["status"] != "active":
        raise SocialError(404, "NOT_FOUND", "user not found")
    if t[0] == acct["user_id"]:
        raise bad("you cannot follow yourself")
    if on:
        if blocked_between(c, acct["user_id"], t[0]):
            raise SocialError(403, "BLOCKED", "you cannot follow this account")
        rate_check(c, acct["user_id"], "follows", "follower_id", 100, 60)
        if c.execute("INSERT OR IGNORE INTO follows(follower_id,followee_id,created_at) VALUES(?,?,?)", (acct["user_id"], t[0], now())).rowcount:
            notify(c, t[0], "follow", {"by": acct["username"]})
    else:
        c.execute("DELETE FROM follows WHERE follower_id=? AND followee_id=?", (acct["user_id"], t[0]))
    return {"username": username, "following": on, "followers": c.execute("SELECT COUNT(*) FROM follows WHERE followee_id=?", (t[0],)).fetchone()[0]}

def block(c, acct, username, on):
    t = c.execute("SELECT user_id FROM accounts WHERE username=?", (str(username).lower(),)).fetchone()
    if not t or t[0] == acct["user_id"]:
        raise SocialError(404, "NOT_FOUND", "user not found")
    if on:
        c.execute("INSERT OR IGNORE INTO blocks(blocker_id,blocked_id,created_at) VALUES(?,?,?)", (acct["user_id"], t[0], now()))
        c.execute("DELETE FROM follows WHERE (follower_id=? AND followee_id=?) OR (follower_id=? AND followee_id=?)", (acct["user_id"], t[0], t[0], acct["user_id"]))
    else:
        c.execute("DELETE FROM blocks WHERE blocker_id=? AND blocked_id=?", (acct["user_id"], t[0]))
    return {"username": username, "blocked": on}

def report(c, acct, d):
    tt, tid, reason = d.get("target_type"), d.get("target_id"), str(d.get("reason") or "").strip()
    if tt not in ("post", "comment", "user") or not isinstance(tid, int) or not 3 <= len(reason) <= 500:
        raise bad("target_type (post/comment/user), target_id and a reason (3-500 characters) are required")
    table = {"post": "posts", "comment": "comments", "user": "accounts"}[tt]
    col = "user_id" if tt == "user" else "id"
    if not c.execute("SELECT 1 FROM %s WHERE %s=?" % (table, col), (tid,)).fetchone():
        raise SocialError(404, "NOT_FOUND", "nothing to report")
    rate_check(c, acct["user_id"], "reports", "reporter_id", 20, 60)
    if not c.execute("INSERT OR IGNORE INTO reports(reporter_id,target_type,target_id,reason,created_at) VALUES(?,?,?,?,?)",
                     (acct["user_id"], tt, tid, reason, now())).rowcount:
        raise SocialError(409, "DUPLICATE", "you already reported this")
    return {"reported": True}

# ------------------------------------------------------------------ profiles, tipsters, leaderboards
def tipster_stats(c, uid, competition_id=None, days=None):
    sql = """SELECT e.result FROM predictions p JOIN expert_profiles x ON x.id=p.expert_id JOIN matches m ON m.id=p.match_id
             LEFT JOIN prediction_evaluations e ON e.prediction_id=p.id AND e.superseded_at IS NULL
             WHERE x.user_id=? AND p.locked_at IS NOT NULL AND p.status='locked' AND p.prediction_type<>'live_winner'
             AND p.id IN (SELECT prediction_id FROM prediction_publications) AND m.data_origin<>'demo'"""
    args = [uid]
    if competition_id:
        sql += " AND m.competition_id=?"; args.append(competition_id)
    if days:
        sql += " AND m.start_utc>=?"; args.append((datetime.datetime.now(datetime.timezone.utc) - datetime.timedelta(days=days)).isoformat())
    res = [r[0] or "pending" for r in c.execute(sql, args)]
    t = engine.tally(res)
    recent = [r[0] for r in c.execute(sql.replace("SELECT e.result", "SELECT e.result, m.start_utc") + " AND e.result IN ('correct','incorrect') ORDER BY m.start_utc DESC LIMIT 5", args)]
    t["recent_form"] = "".join("W" if r == "correct" else "L" for r in recent)
    return t

def badges(stats, followers, posts):
    b = []
    if stats["settled"] >= 20 and (stats["accuracy"] or 0) >= 60:
        b.append("Sharp Shooter (60%+ over 20+ settled picks)")
    if stats["settled"] >= 50:
        b.append("Half-century of settled picks")
    if stats["recent_form"].startswith("WWW"):
        b.append("Hat-trick: last 3 picks correct")
    if followers >= 100:
        b.append("100 followers")
    if posts >= 50:
        b.append("50 posts")
    return b

def profile(c, username, viewer_id):
    a = c.execute("SELECT * FROM accounts WHERE username=?", (str(username).lower(),)).fetchone()
    if not a or a["status"] != "active" or blocked_between(c, viewer_id, a["user_id"]):
        raise SocialError(404, "NOT_FOUND", "user not found")
    uid = a["user_id"]
    one = lambda sql, *x: c.execute(sql, x).fetchone()[0]
    followers = one("SELECT COUNT(*) FROM follows WHERE followee_id=?", uid)
    posts = one("SELECT COUNT(*) FROM posts WHERE author_id=? AND status='published'", uid)
    st = tipster_stats(c, uid)
    out = {"user_id": uid, "username": a["username"], "display_name": a["display_name"], "bio": a["bio"], "joined": a["created_at"][:10],
           "account_type": a["account_type"], "creator_verified": bool(a["creator_verified"]),
           "verified_expert": bool(c.execute("SELECT 1 FROM expert_profiles WHERE user_id=? AND verified=1", (uid,)).fetchone()),
           "avatar": (media_out(c, a["avatar_media_id"]) or {}).get("urls", {}).get("thumb") if a["avatar_media_id"] else None,
           "cover": (media_out(c, a["cover_media_id"]) or {}).get("urls", {}).get("image_lg") if a["cover_media_id"] else None,
           "followers": followers, "following": one("SELECT COUNT(*) FROM follows WHERE follower_id=?", uid), "posts": posts,
           "total_views": one("SELECT COUNT(*) FROM post_views v JOIN posts p ON p.id=v.post_id WHERE p.author_id=? AND p.status='published'", uid),
           "private_profile": bool(a["private_profile"]), "prediction_stats": st, "badges": badges(st, followers, posts)}
    if viewer_id:
        out["me"] = {"following": bool(c.execute("SELECT 1 FROM follows WHERE follower_id=? AND followee_id=?", (viewer_id, uid)).fetchone()),
                     "blocked": bool(c.execute("SELECT 1 FROM blocks WHERE blocker_id=? AND blocked_id=?", (viewer_id, uid)).fetchone()),
                     "is_me": viewer_id == uid}
    return out

def prediction_history(c, username, limit=50, offset=0):
    a = c.execute("SELECT user_id FROM accounts WHERE username=? AND status='active'", (str(username).lower(),)).fetchone()
    if not a:
        raise SocialError(404, "NOT_FOUND", "user not found")
    rows = c.execute("""SELECT p.id, p.match_id, p.prediction_type, t.name AS pick, p.predicted_value, p.confidence, p.created_at, p.locked_at, m.start_utc,
                        h.name AS home, aw.name AS away, e.result, e.rule, pp.published_at FROM predictions p JOIN expert_profiles x ON x.id=p.expert_id
                        JOIN matches m ON m.id=p.match_id JOIN teams h ON h.id=m.home_team_id JOIN teams aw ON aw.id=m.away_team_id
                        LEFT JOIN teams t ON t.id=p.predicted_team_id LEFT JOIN prediction_evaluations e ON e.prediction_id=p.id AND e.superseded_at IS NULL
                        JOIN prediction_publications pp ON pp.prediction_id=p.id WHERE x.user_id=? AND p.status='locked'
                        ORDER BY m.start_utc DESC LIMIT ? OFFSET ?""", (a[0], limit, offset)).fetchall()
    return {"items": [dict(r) for r in rows], "limit": limit, "offset": offset,
            "note": "Every published pick is listed, including losing and deleted-post picks; picks cannot be removed."}

LEADERBOARDS = ("overall", "accuracy", "volume", "recent", "followers", "engagement", "competition")
OVERALL_RULE = ("World ranking score (0-100): 60 x shrunk accuracy x track-record factor + 15 x activity in picks + 10 x posting activity (30 days) "
                "+ 10 x engagement + 5 x followers. Shrunk accuracy = (correct+1)/(settled+2), so 1 lucky pick is not 100%; "
                "track-record factor = settled picks / 20 (max 1). Activity parts use log scale so spam does not win. "
                "Only locked, pre-match, published picks count; nothing is entered by hand.")

def _overall_score(x):
    import math
    acc = (x["correct"] + 1) / (x["settled"] + 2)
    trust = min(1.0, x["settled"] / 20.0)
    lg = lambda v, cap: min(1.0, math.log10(1 + v) / math.log10(1 + cap))
    return round(60 * acc * trust + 15 * lg(x["eligible"], 200) + 10 * lg(x["posts_30d"], 60) + 10 * lg(x["engagement"], 2000) + 5 * lg(x["followers"], 5000), 2)


def leaderboard(c, kind, competition_id=None, min_settled=5, limit=50, me_user_id=None):
    if kind not in LEADERBOARDS:
        raise bad("leaderboard must be one of " + ", ".join(LEADERBOARDS))
    out = []
    for a in c.execute("""SELECT a.user_id, a.username, a.display_name, a.account_type FROM accounts a JOIN expert_profiles x ON x.user_id=a.user_id
                          WHERE a.status='active' AND a.account_type IN ('tipster','expert_tipster')""").fetchall():
        st = tipster_stats(c, a["user_id"], competition_id if kind == "competition" else None, 30 if kind == "recent" else None)
        followers = c.execute("SELECT COUNT(*) FROM follows WHERE followee_id=?", (a["user_id"],)).fetchone()[0]
        eng = c.execute("""SELECT (SELECT COUNT(*) FROM reactions r JOIN posts p ON p.id=r.post_id WHERE p.author_id=:u)
                           + (SELECT COUNT(*) FROM comments cm JOIN posts p ON p.id=cm.post_id WHERE p.author_id=:u AND cm.status='visible')
                           + (SELECT COUNT(*) FROM shares s JOIN posts p ON p.id=s.post_id WHERE p.author_id=:u)""", {"u": a["user_id"]}).fetchone()[0]
        posts_30d = c.execute("SELECT COUNT(*) FROM posts WHERE author_id=? AND status='published' AND created_at>=?",
                              (a["user_id"], (datetime.datetime.now(datetime.timezone.utc) - datetime.timedelta(days=30)).isoformat())).fetchone()[0]
        out.append({"user_id": a["user_id"], "username": a["username"], "display_name": a["display_name"], "account_type": a["account_type"], "posts_30d": posts_30d,
                    "accuracy": st["accuracy"], "settled": st["settled"], "correct": st["correct"], "incorrect": st["incorrect"],
                    "eligible": st["settled"] + st["pending"], "recent_form": st["recent_form"], "followers": followers, "engagement": eng})
    for x in out:
        x["score"] = _overall_score(x)
    excluded = []
    if kind == "overall":
        out.sort(key=lambda x: (-x["score"], -x["settled"], x["username"]))
    elif kind in ("accuracy", "recent", "competition"):
        excluded = [x for x in out if x["settled"] < min_settled]
        out = [x for x in out if x["settled"] >= min_settled]
        out.sort(key=lambda x: (-(x["accuracy"] or 0), -x["settled"]))
    elif kind == "volume":
        out.sort(key=lambda x: -x["eligible"])
    elif kind == "followers":
        out.sort(key=lambda x: -x["followers"])
    else:
        out.sort(key=lambda x: -x["engagement"])
    for i, x in enumerate(out, 1):
        x["rank"] = i
    me = None
    if me_user_id:
        mine = next((x for x in out if x["user_id"] == me_user_id), None)
        if mine:
            me = dict(mine, out_of=len(out))
        else:
            ex = next((x for x in excluded if x["user_id"] == me_user_id), None)
            if ex:
                me = dict(ex, rank=None, out_of=len(out), reason="needs %d settled picks to be ranked here (has %d)" % (min_settled, ex["settled"]))
            else:
                me = {"rank": None, "reason": "only tipsters are ranked; apply to become a tipster from your account page"}
    for x in out + excluded:
        x.pop("user_id", None)
    if me:
        me.pop("user_id", None)
    rule = OVERALL_RULE if kind == "overall" else "Accuracy = correct / (correct + incorrect) from locked, published, pre-match picks; pending, void and late picks excluded."
    return {"board": kind, "min_settled": min_settled if kind in ("accuracy", "recent", "competition") else None, "items": out[:limit],
            "total_ranked": len(out), "me": me, "rule": rule}

def dashboard(c, acct):
    uid = acct["user_id"]
    one = lambda sql, *x: c.execute(sql, x).fetchone()[0]
    posts = c.execute("SELECT id, kind, created_at FROM posts WHERE author_id=? AND status IN ('published','processing') ORDER BY id DESC", (uid,)).fetchall()
    ids = [p["id"] for p in posts] or [-1]
    q = ",".join("?" * len(ids))
    w = c.execute("SELECT COALESCE(SUM(watched_ms),0), COUNT(*), COALESCE(SUM(completed),0) FROM watch_sessions WHERE post_id IN (%s)" % q, ids).fetchone()
    monthly = [dict(r) for r in c.execute("""SELECT substr(p.created_at,1,7) AS month, COUNT(DISTINCT p.id) AS posts,
        (SELECT COUNT(*) FROM post_views v JOIN posts p2 ON p2.id=v.post_id WHERE p2.author_id=:u AND substr(v.day,1,7)=substr(p.created_at,1,7)) AS views
        FROM posts p WHERE p.author_id=:u AND p.status='published' GROUP BY month ORDER BY month DESC LIMIT 12""", {"u": uid})]
    daily = [dict(r) for r in c.execute("""SELECT v.day, COUNT(*) AS views FROM post_views v JOIN posts p ON p.id=v.post_id WHERE p.author_id=?
        GROUP BY v.day ORDER BY v.day DESC LIMIT 30""", (uid,))]
    return {"posts": len(posts), "views": one("SELECT COUNT(*) FROM post_views WHERE post_id IN (%s)" % q, *ids),
            "likes": one("SELECT COUNT(*) FROM reactions WHERE post_id IN (%s)" % q, *ids),
            "comments": one("SELECT COUNT(*) FROM comments WHERE status='visible' AND post_id IN (%s)" % q, *ids),
            "shares": one("SELECT COUNT(*) FROM shares WHERE post_id IN (%s)" % q, *ids),
            "saves": one("SELECT COUNT(*) FROM bookmarks WHERE post_id IN (%s)" % q, *ids),
            "followers": one("SELECT COUNT(*) FROM follows WHERE followee_id=?", uid),
            "watch_time_ms": w[0], "watch_sessions": w[1], "reel_completion_rate": round(100 * w[2] / w[1], 1) if w[1] else None,
            "prediction_performance": tipster_stats(c, uid), "monthly": monthly, "engagement_trend_daily_views": daily,
            "counting_rules": "1 view per viewer per post per UTC day; own views excluded; completion = watched >= 90% of the video."}

def notifications(c, uid, limit=50, offset=0, unread_only=False):
    rows = c.execute("SELECT * FROM notifications WHERE user_id=? %s ORDER BY id DESC LIMIT ? OFFSET ?" % ("AND read_at IS NULL" if unread_only else ""),
                     (uid, limit, offset)).fetchall()
    return {"items": [dict(r, params=json.loads(r["params_json"] or "{}")) for r in rows],
            "unread": c.execute("SELECT COUNT(*) FROM notifications WHERE user_id=? AND read_at IS NULL", (uid,)).fetchone()[0]}

# ------------------------------------------------------------------ admin moderation
def spam_signals(c):
    hour = (datetime.datetime.now(datetime.timezone.utc) - datetime.timedelta(hours=1)).isoformat()
    burst = [dict(r) for r in c.execute("""SELECT a.username, COUNT(*) AS posts_last_hour FROM posts p JOIN accounts a ON a.user_id=p.author_id
        WHERE p.created_at>=? GROUP BY p.author_id HAVING COUNT(*)>=10 ORDER BY 2 DESC""", (hour,))]
    dup = [dict(r) for r in c.execute("""SELECT body, COUNT(DISTINCT author_id) AS authors, COUNT(*) AS posts FROM posts WHERE status='published' AND length(body)>=20
        GROUP BY body HAVING COUNT(DISTINCT author_id)>=3 ORDER BY 3 DESC LIMIT 20""")]
    # fake engagement: many likes on one post from accounts created in the last day sharing one network hash
    fake = [dict(r) for r in c.execute("""SELECT r.post_id, r.ip_hash, COUNT(*) AS likes FROM reactions r JOIN accounts a ON a.user_id=r.user_id
        WHERE a.created_at>=? GROUP BY r.post_id, r.ip_hash HAVING COUNT(*)>=5 ORDER BY 3 DESC LIMIT 20""",
        ((datetime.datetime.now(datetime.timezone.utc) - datetime.timedelta(days=1)).isoformat(),))]
    links = [dict(r) for r in c.execute("""SELECT p.id AS post_id, a.username FROM posts p JOIN accounts a ON a.user_id=p.author_id
        WHERE p.status='published' AND (length(p.body)-length(replace(p.body,'http','')))/4 >= 3 ORDER BY p.id DESC LIMIT 20""")]
    return {"posting_bursts": burst, "duplicate_text_across_accounts": dup, "suspicious_like_clusters": fake, "link_heavy_posts": links}

def moderate(c, actor, d, remove_media):
    action, tt, tid = d.get("action"), d.get("target_type"), d.get("target_id")
    reason = str(d.get("reason") or "").strip()
    if not reason:
        raise bad("reason required")
    if action == "remove_post":
        if not c.execute("UPDATE posts SET status='removed', removed_reason=? WHERE id=? AND status IN ('published','processing')", (reason, tid)).rowcount:
            raise SocialError(404, "NOT_FOUND", "post not found")
        p = c.execute("SELECT author_id FROM posts WHERE id=?", (tid,)).fetchone()
        notify(c, p[0], "post_removed", {"post_id": tid, "reason": reason})
        tt = "post"
    elif action == "restore_post":
        if not c.execute("UPDATE posts SET status='published', removed_reason=NULL WHERE id=? AND status='removed'", (tid,)).rowcount:
            raise SocialError(404, "NOT_FOUND", "removed post not found")
        tt = "post"
    elif action == "remove_comment":
        if not c.execute("UPDATE comments SET status='removed' WHERE id=?", (tid,)).rowcount:
            raise SocialError(404, "NOT_FOUND", "comment not found")
        tt = "comment"
    elif action in ("suspend_user", "unsuspend_user"):
        st = "suspended" if action == "suspend_user" else "active"
        if not c.execute("UPDATE accounts SET status=?, suspended_reason=? WHERE user_id=? AND status<>'deleted'", (st, reason if st == "suspended" else None, tid)).rowcount:
            raise SocialError(404, "NOT_FOUND", "user not found")
        if st == "suspended":
            c.execute("DELETE FROM auth_sessions WHERE user_id=?", (tid,))
        tt = "user"
    elif action in ("approve_tipster", "reject_tipster", "verify_expert", "unverify_expert", "verify_creator", "unverify_creator"):
        a = c.execute("SELECT * FROM accounts WHERE user_id=?", (tid,)).fetchone()
        if not a:
            raise SocialError(404, "NOT_FOUND", "user not found")
        if action == "approve_tipster":
            c.execute("UPDATE accounts SET account_type='tipster', tipster_application='approved' WHERE user_id=?", (tid,))
            if not c.execute("SELECT 1 FROM expert_profiles WHERE user_id=?", (tid,)).fetchone():
                c.execute("INSERT INTO expert_profiles(user_id,display_name,language_code,created_at) VALUES(?,?,'en',?)", (tid, a["display_name"], now()))
            c.execute("UPDATE users SET role='expert' WHERE id=?", (tid,))
            notify(c, tid, "tipster_approved", {})
        elif action == "reject_tipster":
            c.execute("UPDATE accounts SET tipster_application='rejected' WHERE user_id=?", (tid,))
        elif action in ("verify_expert", "unverify_expert"):
            v = action == "verify_expert"
            c.execute("UPDATE expert_profiles SET verified=?, verified_at=? WHERE user_id=?", (1 if v else 0, now() if v else None, tid))
            c.execute("UPDATE accounts SET account_type=? WHERE user_id=? AND account_type IN ('tipster','expert_tipster')", ("expert_tipster" if v else "tipster", tid))
        else:
            c.execute("UPDATE accounts SET creator_verified=? WHERE user_id=?", (1 if action == "verify_creator" else 0, tid))
        tt = "user"
    elif action == "dismiss_report":
        if not c.execute("UPDATE reports SET status='dismissed', resolved_at=?, resolved_by=? WHERE id=? AND status='open'", (now(), actor, tid)).rowcount:
            raise SocialError(404, "NOT_FOUND", "open report not found")
        tt = "report"
    else:
        raise bad("unknown moderation action")
    if tt in ("post", "comment", "user"):
        c.execute("UPDATE reports SET status='actioned', resolved_at=?, resolved_by=? WHERE target_type=? AND target_id=? AND status='open'", (now(), actor, tt, tid))
    c.execute("INSERT INTO moderation_actions(actor,action,target_type,target_id,reason,created_at) VALUES(?,?,?,?,?,?)", (actor, action, tt, tid, reason, now()))
    return {"action": action, "target_id": tid, "done": True}

"""SH News agent.

Two kinds of items, nothing copied:
1. SH reports - written by SH from our own verified results, toss calls and live scores (our own content).
2. Headlines - title, short teaser and link from publishers' public RSS feeds (made for syndication); the article stays on
   the publisher's site and the publisher is named on every item. Feeds are set in the collector job config and can be removed.
"""
import datetime
import html
import json
import re
import urllib.request
import xml.etree.ElementTree as ET

DEFAULT_FEEDS = [{"name": "BBC Sport", "url": "https://feeds.bbci.co.uk/sport/cricket/rss.xml"}]


def _table(c):
    c.execute("""CREATE TABLE IF NOT EXISTS news_items(id INTEGER PRIMARY KEY, source TEXT NOT NULL, title TEXT NOT NULL, link TEXT NOT NULL UNIQUE,
                 summary TEXT, image TEXT, published_at TEXT, fetched_at TEXT NOT NULL)""")


def _clean(s, n=220):
    s = html.unescape(re.sub(r"<[^>]+>", " ", s or ""))
    s = re.sub(r"\s+", " ", s).strip()
    return s if len(s) <= n else s[:n].rsplit(" ", 1)[0] + "…"


def _date(s):
    if not s:
        return None
    for f in ("%a, %d %b %Y %H:%M:%S %Z", "%a, %d %b %Y %H:%M:%S %z", "%Y-%m-%dT%H:%M:%S%z", "%Y-%m-%dT%H:%M:%SZ"):
        try:
            d = datetime.datetime.strptime(s.strip(), f)
            if not d.tzinfo:
                d = d.replace(tzinfo=datetime.timezone.utc)
            return d.astimezone(datetime.timezone.utc).isoformat()
        except ValueError:
            pass
    return None


def parse_rss(raw, source):
    root = ET.fromstring(raw)
    out = []
    MED = "{http://search.yahoo.com/mrss/}"
    for it in root.iter("item"):
        title, link = _clean(it.findtext("title"), 200), (it.findtext("link") or "").strip()
        if not title or not link.startswith("http"):
            continue
        img = None
        th = it.find(MED + "thumbnail")
        if th is not None and (th.get("url") or "").startswith("https://"):
            img = th.get("url")
        out.append({"source": source, "title": title, "link": link, "summary": _clean(it.findtext("description")),
                    "image": img, "published_at": _date(it.findtext("pubDate"))})
    return out


def fetch(c, cfg, now_fn, opener=urllib.request.urlopen):
    _table(c)
    feeds = cfg.get("feeds") or DEFAULT_FEEDS
    got, notes = 0, []
    for f in feeds:
        try:
            raw = opener(urllib.request.Request(f["url"], headers={"User-Agent": "SH-PREDICTION-News/1.0"}), timeout=20).read()
            for x in parse_rss(raw, f["name"])[:40]:
                cur = c.execute("INSERT OR IGNORE INTO news_items(source,title,link,summary,image,published_at,fetched_at) VALUES(?,?,?,?,?,?,?)",
                                (x["source"], x["title"], x["link"], x["summary"], x["image"], x["published_at"] or now_fn(), now_fn()))
                got += cur.rowcount
        except Exception as e:
            notes.append("%s: %s" % (f.get("name"), str(e)[:120]))
    old = (datetime.datetime.now(datetime.timezone.utc) - datetime.timedelta(days=int(cfg.get("keep_days", 10)))).isoformat()
    c.execute("DELETE FROM news_items WHERE published_at < ?", (old,))
    c.commit()
    return {"new": got, "notes": notes}


def sh_reports(c, days=4, limit=20):
    """SH's own short match reports from verified results (and live matches in progress)."""
    since = (datetime.datetime.now(datetime.timezone.utc) - datetime.timedelta(days=days)).isoformat()
    rows = c.execute("""SELECT m.id, m.status, m.start_utc, cp.name AS comp, th.name AS home, ta.name AS away, th.id AS hid, ta.id AS aid,
            r.result_type, r.winner_team_id, r.margin, r.verified_at, tr.winner_team_id AS toss_w, tr.decision
        FROM matches m JOIN competitions cp ON cp.id=m.competition_id JOIN teams th ON th.id=m.home_team_id JOIN teams ta ON ta.id=m.away_team_id
        LEFT JOIN match_results r ON r.match_id=m.id LEFT JOIN toss_results tr ON tr.match_id=m.id
        WHERE m.data_origin<>'demo' AND m.start_utc>=? AND (r.match_id IS NOT NULL OR m.status='live')
        ORDER BY COALESCE(r.verified_at, m.start_utc) DESC LIMIT ?""", (since, limit)).fetchall()
    out = []
    for x in rows:
        x = dict(x)
        name = lambda tid: x["home"] if tid == x["hid"] else x["away"]
        toss = ("%s won the toss and chose to %s." % (name(x["toss_w"]), x["decision"])) if x["toss_w"] and x["decision"] else ""
        if x["result_type"] in ("win", "awarded", "tie_super_over") and x["winner_team_id"]:
            w = name(x["winner_team_id"]); l = x["away"] if w == x["home"] else x["home"]
            title = "%s beat %s%s" % (w, l, (" by " + x["margin"]) if x["margin"] else "")
        elif x["result_type"]:
            title = "%s v %s: %s" % (x["home"], x["away"], x["result_type"].replace("_", " "))
        else:
            title = "Live: %s v %s" % (x["home"], x["away"])
        out.append({"source": "SH", "kind": "sh_report", "title": title, "summary": " ".join(s for s in (x["comp"] + ".", toss) if s),
                    "link": "#/match/%d" % x["id"], "published_at": x["verified_at"] or x["start_utc"], "image": None})
    return out


def feed(c, limit=40):
    _table(c)
    items = sh_reports(c)
    items += [dict(r, kind="headline") for r in (dict(zip(("source", "title", "link", "summary", "image", "published_at"), row)) for row in
              c.execute("SELECT source,title,link,summary,image,published_at FROM news_items ORDER BY published_at DESC LIMIT ?", (limit,)).fetchall())]
    items.sort(key=lambda x: x.get("published_at") or "", reverse=True)
    return items[:limit]

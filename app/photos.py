"""Player photos from Wikimedia Commons only (free licences: CC0, public domain, CC BY, CC BY-SA), with author and licence kept
for attribution. Lookup: Wikipedia search "<name> cricketer" -> the article's lead image -> Commons licence check.
Non-free images (fair-use files hosted on Wikipedia itself) are rejected. Results, including "no photo", are cached 30 days.
Owner-approved photos can be set by an admin and always win. No scraping of other sites.
"""
import json, re, urllib.parse, urllib.request

UA = {"User-Agent": "SH-PREDICTION/1.0 (player photo lookup; contact via app admin)"}
WP = "https://en.wikipedia.org/w/api.php?"
COMMONS = "https://commons.wikimedia.org/w/api.php?"
FREE = re.compile(r"^(cc0|public domain|pd\b|cc[- ]by(-sa)?[- ]?\d|cc[- ]by(-sa)?$)", re.I)
TTL_DAYS = 30


def _table(c):
    c.execute("""CREATE TABLE IF NOT EXISTS player_photos(name_key TEXT PRIMARY KEY, name TEXT NOT NULL, url TEXT, page TEXT, license TEXT,
                 author TEXT, source TEXT NOT NULL, approved INTEGER NOT NULL DEFAULT 0, fetched_at TEXT NOT NULL)""")


def key(name):
    return re.sub(r"\s+", " ", re.sub(r"[^a-z .'-]", "", (name or "").lower())).strip()


def _get(url, fetch):
    return fetch(url) if fetch else json.loads(urllib.request.urlopen(urllib.request.Request(url, headers=UA), timeout=8).read())


def lookup(name, fetch=None):
    q = urllib.parse.urlencode({"action": "query", "format": "json", "generator": "search", "gsrsearch": name + " cricketer", "gsrlimit": 3,
                                "prop": "pageimages|description", "piprop": "thumbnail|name", "pithumbsize": 240, "redirects": 1})
    pages = sorted((_get(WP + q, fetch).get("query") or {}).get("pages", {}).values(), key=lambda p: p.get("index", 99))
    last = key(name).split(" ")[-1] if key(name) else ""
    for p in pages:
        desc = (p.get("description") or "").lower()
        if "cricket" not in desc or (last and last not in key(p.get("title"))):
            continue                                  # must be a cricketer with the same surname
        if not p.get("pageimage") or not p.get("thumbnail"):
            return None
        q2 = urllib.parse.urlencode({"action": "query", "format": "json", "titles": "File:" + p["pageimage"], "prop": "imageinfo",
                                     "iiprop": "extmetadata"})
        info = list((_get(COMMONS + q2, fetch).get("query") or {}).get("pages", {}).values())
        meta = ((info[0].get("imageinfo") or [{}])[0].get("extmetadata") or {}) if info else {}
        lic = (meta.get("LicenseShortName") or {}).get("value", "")
        if not lic or not FREE.match(lic.strip()):
            return None                               # not on Commons or not a free licence: no photo
        author = re.sub(r"<[^>]+>", "", (meta.get("Artist") or {}).get("value", "")).strip()[:120]
        return {"url": p["thumbnail"]["source"], "page": "https://en.wikipedia.org/wiki/" + urllib.parse.quote(p["title"].replace(" ", "_")),
                "license": lic, "author": author or "Wikimedia Commons contributor", "source": "Wikimedia Commons"}
    return None


def get_many(c, names, now_fn, fetch=None, max_lookups=6):
    """Cached photos for up to 40 names; at most max_lookups outside lookups per call (the rest come on later calls)."""
    import datetime
    _table(c)
    out, looked = {}, 0
    for n in names[:40]:
        k = key(n)
        if not k:
            continue
        r = c.execute("SELECT * FROM player_photos WHERE name_key=?", (k,)).fetchone()
        fresh = r and (r["approved"] or (datetime.datetime.fromisoformat(now_fn()) - datetime.datetime.fromisoformat(r["fetched_at"])).days < TTL_DAYS)
        if not fresh and looked < max_lookups:
            looked += 1
            try:
                p = lookup(n, fetch)
            except Exception:
                out[n] = ({x: r[x] for x in ("url", "page", "license", "author", "source")} if r and r["url"] else None)
                continue                              # network trouble: try again on a later call, never cache a failure
            c.execute("""INSERT INTO player_photos(name_key,name,url,page,license,author,source,fetched_at) VALUES(?,?,?,?,?,?,?,?)
                         ON CONFLICT(name_key) DO UPDATE SET url=excluded.url, page=excluded.page, license=excluded.license, author=excluded.author,
                         source=excluded.source, fetched_at=excluded.fetched_at WHERE approved=0""",
                      (k, n, (p or {}).get("url"), (p or {}).get("page"), (p or {}).get("license"), (p or {}).get("author"),
                       (p or {}).get("source") or "Wikimedia Commons (no free photo found)", now_fn()))
            r = c.execute("SELECT * FROM player_photos WHERE name_key=?", (k,)).fetchone()
        if r:
            out[n] = {x: r[x] for x in ("url", "page", "license", "author", "source")} if r["url"] else None
    return out


def approve(c, name, url, license_, author, now_fn):
    """Admin: set an owner-approved photo (e.g. from the team's media kit with permission)."""
    _table(c)
    c.execute("""INSERT INTO player_photos(name_key,name,url,page,license,author,source,approved,fetched_at) VALUES(?,?,?,?,?,?,'Owner approved',1,?)
                 ON CONFLICT(name_key) DO UPDATE SET url=excluded.url, license=excluded.license, author=excluded.author, source='Owner approved',
                 approved=1, fetched_at=excluded.fetched_at""", (key(name), name, url, None, license_, author, now_fn()))

import os,json,sqlite3,datetime
from http.server import ThreadingHTTPServer,BaseHTTPRequestHandler
from urllib.parse import urlparse,parse_qs
from pathlib import Path
from screen_login import generate,verify,authorized,logout
DB=os.getenv("SH_PREDICTION_DB","data/prediction.sqlite3")
TOKEN=os.getenv("SH_PREDICTION_ADMIN_TOKEN","")
def now(): return datetime.datetime.now(datetime.timezone.utc).isoformat()
def db():
 os.makedirs(os.path.dirname(os.path.abspath(DB)),exist_ok=True)
 c=sqlite3.connect(DB);c.row_factory=sqlite3.Row
 c.executescript("""CREATE TABLE IF NOT EXISTS fixtures(id INTEGER PRIMARY KEY,competition TEXT NOT NULL,season TEXT NOT NULL,home TEXT NOT NULL,away TEXT NOT NULL,start_utc TEXT NOT NULL,source TEXT NOT NULL,UNIQUE(competition,season,home,away,start_utc));
 CREATE TABLE IF NOT EXISTS predictions(id INTEGER PRIMARY KEY,fixture_id INTEGER UNIQUE NOT NULL,toss_pick TEXT,winner_pick TEXT,created_at TEXT NOT NULL,status TEXT NOT NULL DEFAULT 'draft',approved_at TEXT);
 CREATE TABLE IF NOT EXISTS outcomes(fixture_id INTEGER PRIMARY KEY,toss_winner TEXT,match_winner TEXT,source TEXT NOT NULL,verified_at TEXT NOT NULL);
 CREATE TABLE IF NOT EXISTS archive(id INTEGER PRIMARY KEY,fixture_id INTEGER,section TEXT NOT NULL,payload TEXT NOT NULL,source TEXT NOT NULL,reviewed INTEGER DEFAULT 0,created_at TEXT NOT NULL);
 CREATE TABLE IF NOT EXISTS odds(id INTEGER PRIMARY KEY,fixture_id INTEGER NOT NULL,team TEXT NOT NULL,price REAL NOT NULL CHECK(price>=1.01 AND price<=1000),observed_at TEXT NOT NULL,source TEXT NOT NULL,reviewed INTEGER NOT NULL DEFAULT 0,created_at TEXT NOT NULL,UNIQUE(fixture_id,team,observed_at,source));""")
 return c
class H(BaseHTTPRequestHandler):
 def sendj(self,code,obj):
  b=json.dumps(obj,ensure_ascii=False).encode();self.send_response(code);self.send_header("Content-Type","application/json; charset=utf-8");self.send_header("Cache-Control","no-store");self.send_header("Content-Length",str(len(b)));self.end_headers();self.wfile.write(b)
 def auth(self): return authorized(self.headers.get("Authorization","").removeprefix("Bearer ").strip()) or (bool(TOKEN) and self.headers.get("X-Admin-Token")==TOKEN)
 def body(self):
  n=int(self.headers.get("Content-Length","0"))
  if n<1 or n>1000000:raise ValueError("invalid payload size")
  return json.loads(self.rfile.read(n))
 def do_GET(self):
  p=urlparse(self.path).path
  if p in ("/","/app"):
   b=(Path(__file__).parent/"index.html").read_bytes();self.send_response(200);self.send_header("Content-Type","text/html; charset=utf-8");self.send_header("Content-Length",str(len(b)));self.end_headers();self.wfile.write(b);return
  if p=="/sh-prediction-welcome.html":
   b=(Path(__file__).parent/"sh-prediction-welcome.html").read_bytes();self.send_response(200);self.send_header("Content-Type","text/html; charset=utf-8");self.send_header("Cache-Control","no-store");self.send_header("Content-Length",str(len(b)));self.end_headers();self.wfile.write(b);return
  if p=="/icon.svg":
   b=(Path(__file__).parent/"icon.svg").read_bytes();self.send_response(200);self.send_header("Content-Type","image/svg+xml");self.send_header("Content-Length",str(len(b)));self.end_headers();self.wfile.write(b);return
  if p=="/health":return self.sendj(200,{"status":"ok","app":"SH PREDICTION"})
  if not self.auth():return self.sendj(403,{"error":"login required"})
  if p.startswith("/admin/") and not self.auth():return self.sendj(403,{"error":"admin token required"})
  with db() as c:
   if p=="/fixtures": rows=c.execute("SELECT * FROM fixtures ORDER BY start_utc DESC LIMIT 200")
   elif p=="/results": rows=c.execute("SELECT f.*,o.toss_winner,o.match_winner FROM fixtures f JOIN outcomes o ON f.id=o.fixture_id ORDER BY f.start_utc DESC LIMIT 200")
   elif p=="/predictions": rows=c.execute("SELECT * FROM predictions WHERE status='approved' ORDER BY id DESC LIMIT 200")
   elif p=="/archive": rows=c.execute("SELECT * FROM archive WHERE reviewed=1 ORDER BY id DESC LIMIT 200")
   elif p=="/admin/drafts": rows=c.execute("SELECT * FROM predictions WHERE status='draft'")
   elif p=="/admin/odds_pending": rows=c.execute("SELECT * FROM odds WHERE reviewed=0 ORDER BY id DESC LIMIT 200")
   elif p=="/odds":
    try: fid=int(parse_qs(urlparse(self.path).query).get("fixture_id",["0"])[0])
    except ValueError:return self.sendj(400,{"error":"invalid fixture"})
    rows=c.execute("SELECT team,price,observed_at,source FROM odds WHERE reviewed=1 AND fixture_id=? ORDER BY observed_at",(fid,))
   elif p=="/accuracy":
    rows=c.execute("SELECT p.toss_pick,p.winner_pick,o.toss_winner,o.match_winner FROM predictions p JOIN outcomes o ON o.fixture_id=p.fixture_id WHERE p.status='approved'").fetchall()
    return self.sendj(200,{k:{"correct":sum(r[p]==r[a] for r in rows if r[p] and r[a]),"total":sum(bool(r[p] and r[a]) for r in rows)} for k,p,a in [("toss","toss_pick","toss_winner"),("winner","winner_pick","match_winner")]})
   else:return self.sendj(404,{"error":"not found"})
   return self.sendj(200,[dict(x) for x in rows])
 def do_POST(self):
  try:
   p=urlparse(self.path).path;d=self.body()
   if p=="/auth/generate":return self.sendj(200,generate(d.get("phone","")))
   if p=="/auth/verify":
    token=verify(d.get("phone",""),d.get("otp",""))
    return self.sendj(200,{"token":token}) if token else self.sendj(403,{"error":"Incorrect or expired code"})
   if p=="/auth/logout":
    logout(self.headers.get("Authorization","").removeprefix("Bearer ").strip())
    return self.sendj(200,{"status":"logged_out"})
   if not self.auth():return self.sendj(403,{"error":"login required"})
   with db() as c:
    if p=="/admin/fixtures":
     for k in ("competition","season","home","away","start_utc","source"):
      if not str(d.get(k,"")).strip():raise ValueError("missing "+k)
     if d["home"]==d["away"]:raise ValueError("teams must differ")
     dt=datetime.datetime.fromisoformat(d["start_utc"].replace("Z","+00:00"))
     if dt.tzinfo is None:raise ValueError("timezone required")
     c.execute("INSERT OR IGNORE INTO fixtures(competition,season,home,away,start_utc,source) VALUES(?,?,?,?,?,?)",tuple(d[k] for k in ("competition","season","home","away","start_utc","source")))
     result={"status":"saved"}
    elif p=="/admin/predictions":
     f=c.execute("SELECT * FROM fixtures WHERE id=?",(d["fixture_id"],)).fetchone()
     if not f:raise ValueError("unknown fixture")
     if now()>=datetime.datetime.fromisoformat(f["start_utc"].replace("Z","+00:00")).astimezone(datetime.timezone.utc).isoformat():raise ValueError("match already started")
     for k in ("toss_pick","winner_pick"):
      if d.get(k) and d[k] not in (f["home"],f["away"]):raise ValueError("invalid "+k)
     c.execute("INSERT INTO predictions(fixture_id,toss_pick,winner_pick,created_at) VALUES(?,?,?,?)",(d["fixture_id"],d.get("toss_pick"),d.get("winner_pick"),now()))
     result={"status":"draft"}
    elif p=="/admin/approve":
     r=c.execute("SELECT p.*,f.start_utc FROM predictions p JOIN fixtures f ON f.id=p.fixture_id WHERE p.id=?",(d["prediction_id"],)).fetchone()
     if not r or r["status"]!="draft":raise ValueError("draft not found")
     if now()>=datetime.datetime.fromisoformat(r["start_utc"].replace("Z","+00:00")).astimezone(datetime.timezone.utc).isoformat():raise ValueError("match already started")
     c.execute("UPDATE predictions SET status='approved',approved_at=? WHERE id=?",(now(),d["prediction_id"]));result={"status":"approved"}
    elif p=="/admin/outcomes":
     f=c.execute("SELECT * FROM fixtures WHERE id=?",(d["fixture_id"],)).fetchone()
     if not f:raise ValueError("unknown fixture")
     for k in ("toss_winner","match_winner"):
      if d.get(k) and d[k] not in (f["home"],f["away"]):raise ValueError("invalid "+k)
     if not d.get("source"):raise ValueError("source required")
     c.execute("INSERT INTO outcomes(fixture_id,toss_winner,match_winner,source,verified_at) VALUES(?,?,?,?,?)",(d["fixture_id"],d.get("toss_winner"),d.get("match_winner"),d["source"],now()));result={"status":"recorded"}
    elif p=="/admin/import_odds_batch":
     items=d.get("rows")
     if not isinstance(items,list) or not 1<=len(items)<=1000:raise ValueError("1..1000 rows required")
     prepared=[]
     for r in items:
      f=c.execute("SELECT home,away FROM fixtures WHERE id=?",(r["fixture_id"],)).fetchone()
      if not f or r["team"] not in (f["home"],f["away"]):raise ValueError("invalid fixture/team")
      price=float(r["price"])
      if not 1.01<=price<=1000:raise ValueError("invalid decimal price")
      t=datetime.datetime.fromisoformat(r["observed_at"].replace("Z","+00:00"))
      if t.tzinfo is None or not str(r.get("source","")).strip():raise ValueError("timestamp timezone and source required")
      prepared.append((r["fixture_id"],r["team"],price,t.astimezone(datetime.timezone.utc).isoformat(),r["source"],now()))
     before=c.total_changes;c.executemany("INSERT OR IGNORE INTO odds(fixture_id,team,price,observed_at,source,created_at) VALUES(?,?,?,?,?,?)",prepared)
     added=c.total_changes-before;result={"status":"pending_review","imported":added,"duplicates":len(items)-added}
    elif p=="/admin/review_odds":
     cur=c.execute("UPDATE odds SET reviewed=1 WHERE id=? AND reviewed=0",(d["id"],))
     if not cur.rowcount:raise ValueError("pending record not found")
     result={"status":"approved"}
    elif p=="/admin/archive":
     if d.get("section") not in ("scorecard","points_table","commentary_summary","stats","series","match_info"):raise ValueError("invalid section")
     if not str(d.get("source","")).startswith("https://"):raise ValueError("HTTPS source required")
     if not isinstance(d.get("payload"),(dict,list)):raise ValueError("JSON payload required")
     c.execute("INSERT INTO archive(fixture_id,section,payload,source,created_at) VALUES(?,?,?,?,?)",(d.get("fixture_id"),d["section"],json.dumps(d["payload"]),d["source"],now()));result={"status":"pending_review"}
    elif p=="/admin/review_archive":
     cur=c.execute("UPDATE archive SET reviewed=1 WHERE id=? AND reviewed=0",(d["id"],))
     if not cur.rowcount:raise ValueError("pending record not found")
     result={"status":"approved"}
    else:return self.sendj(404,{"error":"not found"})
    c.commit();return self.sendj(200,result)
  except (ValueError,KeyError,TypeError,sqlite3.Error) as e:return self.sendj(400,{"error":str(e)})
if __name__=="__main__":
 with db():pass
 ThreadingHTTPServer((os.getenv("HOST","0.0.0.0"),int(os.getenv("PORT","8080"))),H).serve_forever()

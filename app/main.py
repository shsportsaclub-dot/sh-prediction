import os,json,sqlite3,datetime,secrets
from http.server import ThreadingHTTPServer,BaseHTTPRequestHandler
from urllib.parse import urlparse,parse_qs
from pathlib import Path
from screen_login import generate,verify,authorized,logout
import api_v1,apk,live,media,social,re,hashlib
# build id: Render sets RENDER_GIT_COMMIT for every deploy; locally fall back to a hash of the app files
def _build_id():
 c=os.environ.get("RENDER_GIT_COMMIT","").strip()
 if c:return c[:12]
 h=hashlib.sha1()
 for f in sorted(Path(__file__).parent.glob("*")):
  if f.suffix in (".html",".js",".py"):h.update(f.read_bytes())
 return h.hexdigest()[:12]
BUILD=_build_id()
DB=os.getenv("SH_PREDICTION_DB","data/prediction.sqlite3")
TOKEN=os.getenv("SH_PREDICTION_ADMIN_TOKEN","").strip()
def now(): return datetime.datetime.now(datetime.timezone.utc).isoformat()
class LegacyConn(sqlite3.Connection):
 lp="legacy_predictions"
 def _m(self,sql):return sql if self.lp=="legacy_predictions" else sql.replace("legacy_predictions",self.lp)
 def execute(self,sql,*a):return super().execute(self._m(sql),*a)
 def executemany(self,sql,*a):return super().executemany(self._m(sql),*a)
 def executescript(self,sql):return super().executescript(self._m(sql))
def db():
 os.makedirs(os.path.dirname(os.path.abspath(DB)),exist_ok=True)
 c=sqlite3.connect(DB,timeout=10,factory=LegacyConn);c.row_factory=sqlite3.Row
 # v1 owns the "predictions" table name. Until an admin runs the migration, the v0 table keeps its old
 # name and the classic screens keep working through this name mapping (no schema change on page load).
 if not getattr(db,"wal",False):
  # WAL lets readers (SSE, feeds) work while the scorer, importer or media worker writes
  try:sqlite3.Connection.execute(c,"PRAGMA journal_mode=WAL");db.wal=True
  except sqlite3.OperationalError:pass
 sqlite3.Connection.execute(c,"PRAGMA busy_timeout=10000")
 c.lp="predictions" if "fixture_id" in {r[1] for r in sqlite3.Connection.execute(c,"PRAGMA table_info(predictions)")} else "legacy_predictions"
 c.executescript("""CREATE TABLE IF NOT EXISTS fixtures(id INTEGER PRIMARY KEY,competition TEXT NOT NULL,season TEXT NOT NULL,home TEXT NOT NULL,away TEXT NOT NULL,start_utc TEXT NOT NULL,source TEXT NOT NULL,UNIQUE(competition,season,home,away,start_utc));
 CREATE TABLE IF NOT EXISTS legacy_predictions(id INTEGER PRIMARY KEY,fixture_id INTEGER UNIQUE NOT NULL,toss_pick TEXT,winner_pick TEXT,created_at TEXT NOT NULL,status TEXT NOT NULL DEFAULT 'draft',approved_at TEXT);
 CREATE TABLE IF NOT EXISTS outcomes(fixture_id INTEGER PRIMARY KEY,toss_winner TEXT,match_winner TEXT,source TEXT NOT NULL,verified_at TEXT NOT NULL);
 CREATE TABLE IF NOT EXISTS archive(id INTEGER PRIMARY KEY,fixture_id INTEGER,section TEXT NOT NULL,payload TEXT NOT NULL,source TEXT NOT NULL,reviewed INTEGER DEFAULT 0,created_at TEXT NOT NULL);
 CREATE TABLE IF NOT EXISTS odds(id INTEGER PRIMARY KEY,fixture_id INTEGER NOT NULL,team TEXT NOT NULL,price REAL NOT NULL CHECK(price>=1.01 AND price<=1000),observed_at TEXT NOT NULL,source TEXT NOT NULL,reviewed INTEGER NOT NULL DEFAULT 0,created_at TEXT NOT NULL,UNIQUE(fixture_id,team,observed_at,source));""")
 for t,col,ddl in (("fixtures","venue","TEXT"),("fixtures","match_no","TEXT"),("outcomes","status","TEXT NOT NULL DEFAULT 'completed'"),("outcomes","toss_decision","TEXT"),("outcomes","remarks","TEXT")):
  if col not in {r[1] for r in c.execute("PRAGMA table_info("+t+")")}:c.execute("ALTER TABLE "+t+" ADD COLUMN "+col+" "+ddl)
 c.executescript("""CREATE TABLE IF NOT EXISTS audit_logs(id INTEGER PRIMARY KEY,action TEXT NOT NULL,payload TEXT,old_value TEXT,created_at TEXT NOT NULL);
 CREATE TRIGGER IF NOT EXISTS predictions_immutable BEFORE UPDATE OF fixture_id,toss_pick,winner_pick,created_at ON legacy_predictions WHEN OLD.status='approved' BEGIN SELECT RAISE(ABORT,'approved prediction is immutable'); END;
 CREATE TRIGGER IF NOT EXISTS predictions_nodelete BEFORE DELETE ON legacy_predictions WHEN OLD.status='approved' BEGIN SELECT RAISE(ABORT,'approved prediction cannot be deleted'); END;""")
 return c
api_v1.DB_FN=db
api_v1.DB_PATH=DB
def pdt(x):
 d=datetime.datetime.fromisoformat(str(x).replace("Z","+00:00"))
 return d.astimezone(datetime.timezone.utc) if d.tzinfo else d.replace(tzinfo=datetime.timezone.utc)
def verdict(pick,actual,o,kind,locked):
 """Settlement rules: no pick -> No Prediction; approved after start -> Ineligible; no outcome -> Pending;
 winner: non-completed match -> Void; toss: missing toss on non-completed match -> Void; else Correct/Wrong."""
 if not pick:return "No Prediction"
 if not locked:return "Ineligible"
 if o is None:return "Pending"
 st=o["status"] or "completed"
 if not actual:return "Void" if st!="completed" else "Pending"
 if kind=="winner" and st!="completed":return "Void"
 return "Correct" if pick==actual else "Wrong"
def tally(rows,k):
 c={x:0 for x in ("Correct","Wrong","Pending","Void","Excluded")}
 for r in rows:
  v=r[k]
  if v in c:c[v]+=1
  elif r["has_prediction"] and v in ("No Prediction","Ineligible"):c["Excluded"]+=1
 n=c["Correct"]+c["Wrong"]
 return {"correct":c["Correct"],"wrong":c["Wrong"],"pending":c["Pending"],"void":c["Void"],"excluded":c["Excluded"],"total":n,"percent":round(100*c["Correct"]/n,1) if n else None,"formula":"Correct / (Correct + Wrong) x 100; Pending, Void and Excluded are not in the denominator"}
def compute(c):
 rows=[]
 q=c.execute("SELECT f.*,p.id pid,p.toss_pick,p.winner_pick,p.created_at pcreated,p.approved_at,o.toss_winner,o.match_winner,o.status ostatus,o.toss_decision,o.remarks,o.source osource,o.verified_at FROM fixtures f LEFT JOIN legacy_predictions p ON p.fixture_id=f.id AND p.status='approved' LEFT JOIN outcomes o ON o.fixture_id=f.id ORDER BY f.start_utc DESC LIMIT 1000").fetchall()
 for i,r in enumerate(q,1):
  o={"status":r["ostatus"]} if r["toss_winner"] is not None or r["match_winner"] is not None or r["ostatus"] else None
  has=r["pid"] is not None
  locked=has and r["approved_at"] and pdt(r["approved_at"])<pdt(r["start_utc"])
  tv=verdict(r["toss_pick"],r["toss_winner"],o,"toss",locked) if has else "No Prediction"
  wv=verdict(r["winner_pick"],r["match_winner"],o,"winner",locked) if has else "No Prediction"
  st="Completed" if o and (r["ostatus"] or "completed")=="completed" else ("Abandoned / No result" if o else ("Awaiting result" if pdt(r["start_utc"])<=datetime.datetime.now(datetime.timezone.utc) else "Scheduled"))
  rows.append({"sno":i,"match_id":r["id"],"date_utc":r["start_utc"],"tournament":r["competition"],"season":r["season"],"venue":r["venue"],"match_no":r["match_no"],"home":r["home"],"away":r["away"],"toss_prediction":r["toss_pick"],"actual_toss":r["toss_winner"],"toss_decision":r["toss_decision"],"toss_result":tv,"winner_prediction":r["winner_pick"],"actual_winner":r["match_winner"],"winner_result":wv,"status":st,"predicted_at":r["pcreated"],"locked_at":r["approved_at"],"source":r["source"],"result_source":r["osource"],"remarks":r["remarks"],"has_prediction":has})
 out={"toss":tally(rows,"toss_result"),"winner":tally(rows,"winner_result"),"by_competition":{}}
 for t in sorted({r["tournament"] for r in rows}):
  sub=[r for r in rows if r["tournament"]==t];out["by_competition"][t]={"toss":tally(sub,"toss_result"),"winner":tally(sub,"winner_result")}
 return rows,out
REG_COLS=["sno","match_id","date_utc","tournament","season","venue","match_no","home","away","toss_prediction","actual_toss","toss_decision","toss_result","winner_prediction","actual_winner","winner_result","status","predicted_at","locked_at","source","remarks"]
def csv_text(rows):
 import csv,io
 b=io.StringIO();w=csv.writer(b);w.writerow(REG_COLS)
 for r in rows:w.writerow([("'"+str(r[k]) if isinstance(r[k],str) and r[k][:1] in "=+-@" else ("" if r[k] is None else r[k])) for k in REG_COLS])
 return b.getvalue()
class H(BaseHTTPRequestHandler):
 def sendj(self,code,obj):
  b=json.dumps(obj,ensure_ascii=False).encode();self.send_response(code);self.send_header("Content-Type","application/json; charset=utf-8");self.send_header("Cache-Control","no-store");self.send_header("Content-Length",str(len(b)));self.end_headers();self.wfile.write(b)
 def admin_ok(self): return bool(TOKEN) and secrets.compare_digest(self.headers.get("X-Admin-Token",""),TOKEN)
 def auth(self): return authorized(self.headers.get("Authorization","").removeprefix("Bearer ").strip()) or self.admin_ok()
 def body(self):
  n=int(self.headers.get("Content-Length","0"))
  if n<1 or n>1000000:raise ValueError("invalid payload size")
  return json.loads(self.rfile.read(n))
 def v1(self,method):
  u=urlparse(self.path)
  code,obj=api_v1.route(self,method,u.path,parse_qs(u.query),self.body)
  return self.sendj(code,obj)
 def do_PUT(self):
  u=urlparse(self.path);mm=re.fullmatch(r"/api/v1/media/uploads/(\d+)",u.path)
  if mm:return self.upload_chunk(int(mm.group(1)),parse_qs(u.query))
  if u.path.startswith("/api/v1/"):return self.v1("PUT")
  return self.sendj(405,{"error":"method not allowed"})
 def upload_chunk(self,mid,q):
  """Resumable signed upload: PUT raw bytes with Content-Range: bytes start-end/total."""
  if not media.check_sig(mid,q.get("exp",[""])[0],q.get("sig",[""])[0]):return self.sendj(403,{"error":{"code":"BAD_SIGNATURE","message":"upload URL expired or invalid; ask for a new one"}})
  n=int(self.headers.get("Content-Length","0"))
  if n<1 or n>media.CHUNK*2:return self.sendj(400,{"error":{"code":"VALIDATION_ERROR","message":"chunk must be 1 byte to %d bytes"%(media.CHUNK*2)}})
  cr=re.fullmatch(r"bytes (\d+)-(\d+)/(\d+)",self.headers.get("Content-Range",""))
  if not cr or int(cr.group(2))-int(cr.group(1))+1!=n:return self.sendj(400,{"error":{"code":"VALIDATION_ERROR","message":"Content-Range: bytes start-end/total required"}})
  data=self.rfile.read(n);c=db()
  try:
   r=media.put_chunk(c,mid,int(cr.group(1)),data);c.commit();return self.sendj(200,r)
  except media.MediaError as e:return self.sendj(e.status,{"error":{"code":e.code,"message":e.message}})
  finally:c.close()
 def serve_media(self,path):
  """Media renditions with access control, HTTP Range (video seeking) and CDN-friendly caching for public files."""
  mm=re.fullmatch(r"/media/(\d+)/([A-Za-z0-9_./-]+)",path)
  if not mm or ".." in mm.group(2):return self.sendj(404,{"error":"not found"})
  mid=int(mm.group(1));c=db()
  try:
   a=c.execute("SELECT * FROM media_assets WHERE id=?",(mid,)).fetchone() if c.execute("SELECT 1 FROM sqlite_master WHERE name='media_assets'").fetchone() else None
   if not a or a["status"]!="ready":return self.sendj(404,{"error":"not found"})
   public=a["purpose"] in ("avatar","cover") or c.execute("SELECT 1 FROM post_media pm JOIN posts p ON p.id=pm.post_id JOIN accounts ac ON ac.user_id=p.author_id WHERE pm.media_id=? AND p.status='published' AND ac.status='active' AND ac.private_profile=0",(mid,)).fetchone()
   if not public:
    import auth
    acct=auth.session_user(c,self.headers.get("Authorization","").removeprefix("Bearer ").strip())
    ok=self.admin_ok() or (acct and acct["user_id"]==a["owner_id"]) or (acct and c.execute("SELECT 1 FROM post_media pm JOIN posts p ON p.id=pm.post_id JOIN follows f ON f.followee_id=p.author_id WHERE pm.media_id=? AND p.status='published' AND f.follower_id=?",(mid,acct["user_id"])).fetchone())
    if not ok:return self.sendj(404,{"error":"not found"})
   c.commit()
  finally:c.close()
  fp=media.storage().path("%d/%s"%(mid,mm.group(2)))
  if not os.path.isfile(fp):return self.sendj(404,{"error":"not found"})
  ctype={".jpg":"image/jpeg",".mp4":"video/mp4",".m3u8":"application/vnd.apple.mpegurl",".ts":"video/mp2t"}.get(os.path.splitext(fp)[1],"application/octet-stream")
  size=os.path.getsize(fp);start,end=0,size-1;status=200
  rg=re.fullmatch(r"bytes=(\d*)-(\d*)",self.headers.get("Range",""))
  if rg:
   if rg.group(1):start=int(rg.group(1));end=int(rg.group(2)) if rg.group(2) else size-1
   else:start=max(0,size-int(rg.group(2)))
   if start>=size or start>end:
    self.send_response(416);self.send_header("Content-Range","bytes */%d"%size);self.send_header("Content-Length","0");self.end_headers();return
   end=min(end,size-1);status=206
  self.send_response(status);self.send_header("Content-Type",ctype);self.send_header("Accept-Ranges","bytes");self.send_header("X-Content-Type-Options","nosniff")
  self.send_header("Cache-Control","public, max-age=31536000, immutable" if public else "private, no-store")
  if status==206:self.send_header("Content-Range","bytes %d-%d/%d"%(start,end,size))
  self.send_header("Content-Length",str(end-start+1));self.end_headers()
  with open(fp,"rb") as f:
   f.seek(start);left=end-start+1
   while left>0:
    chunk=f.read(min(65536,left))
    if not chunk:break
    try:self.wfile.write(chunk)
    except (BrokenPipeError,ConnectionResetError):return
    left-=len(chunk)
 def do_GET(self):
  p=urlparse(self.path).path
  sm=re.fullmatch(r"/api/v1/matches/(\d+)/stream",p)
  if sm:
   c=db();pending=__import__("schema").pending(c);c.close()
   if pending:return self.sendj(503,{"error":{"code":"MIGRATION_PENDING","message":"migration pending"}})
   q=parse_qs(urlparse(self.path).query)
   last=self.headers.get("Last-Event-ID") or q.get("last_id",["0"])[0]
   try:last=int(last)
   except ValueError:last=0
   return live.stream(self,db,int(sm.group(1)),last,int(os.getenv("SH_SSE_MAX_SECONDS","300")))
  if p.startswith("/media/"):return self.serve_media(p)
  if p.startswith("/api/v1/"):return self.v1("GET")
  if p=="/download/sh-prediction.apk":
   try:
    kind,x=apk.resolve()
    if kind=="redirect":
     self.send_response(302);self.send_header("Location",x);self.send_header("Content-Length","0");self.end_headers();return
    self.send_response(200);self.send_header("Content-Type","application/vnd.android.package-archive");self.send_header("Content-Disposition","attachment; filename=sh-prediction.apk")
    if x.headers.get("Content-Length"):self.send_header("Content-Length",x.headers["Content-Length"])
    self.end_headers()
    while True:
     chunk=x.read(65536)
     if not chunk:break
     self.wfile.write(chunk)
    return
   except Exception:return self.sendj(502,{"error":"APK download is not available right now"})
  if p in ("/","/app","/hub","/admin-panel"):
   f={"/admin-panel":"admin.html"}.get(p,"hub.html")
   b=(Path(__file__).parent/f).read_bytes().replace(b"__SH_BUILD__",BUILD.encode());self.send_response(200);self.send_header("Content-Type","text/html; charset=utf-8");self.send_header("Cache-Control","no-store");self.send_header("X-Frame-Options","DENY");self.send_header("Referrer-Policy","no-referrer");self.send_header("Content-Length",str(len(b)));self.end_headers();self.wfile.write(b);return
  if p=="/shell.js":
   b=(Path(__file__).parent/"shell.js").read_bytes();self.send_response(200);self.send_header("Content-Type","text/javascript; charset=utf-8");self.send_header("Cache-Control","no-cache");self.send_header("Content-Length",str(len(b)));self.end_headers();self.wfile.write(b);return
  if p=="/match_center.js":
   b=(Path(__file__).parent/"match_center.js").read_bytes();self.send_response(200);self.send_header("Content-Type","text/javascript; charset=utf-8");self.send_header("Cache-Control","no-cache");self.send_header("Content-Length",str(len(b)));self.end_headers();self.wfile.write(b);return
  if p=="/hub_social.js":
   b=(Path(__file__).parent/"hub_social.js").read_bytes();self.send_response(200);self.send_header("Content-Type","text/javascript; charset=utf-8");self.send_header("Cache-Control","no-cache");self.send_header("Content-Length",str(len(b)));self.end_headers();self.wfile.write(b);return
  if p=="/classic":
   b=(Path(__file__).parent/"index.html").read_bytes();self.send_response(200);self.send_header("Content-Type","text/html; charset=utf-8");self.send_header("Content-Length",str(len(b)));self.end_headers();self.wfile.write(b);return
  if p=="/sh-original-blueprint.html":
   b=(Path(__file__).parent/"sh-original-blueprint.html").read_bytes();self.send_response(200);self.send_header("Content-Type","text/html; charset=utf-8");self.send_header("Content-Length",str(len(b)));self.end_headers();self.wfile.write(b);return
  if p=="/sh-prediction-welcome.html":
   b=(Path(__file__).parent/"sh-prediction-welcome.html").read_bytes();self.send_response(200);self.send_header("Content-Type","text/html; charset=utf-8");self.send_header("Cache-Control","no-store");self.send_header("Content-Length",str(len(b)));self.end_headers();self.wfile.write(b);return
  if p=="/sh-prediction-icon.png":
   b=(Path(__file__).parent/"sh-prediction-icon.png").read_bytes();self.send_response(200);self.send_header("Content-Type","image/png");self.send_header("Cache-Control","public, max-age=86400");self.send_header("Content-Length",str(len(b)));self.end_headers();self.wfile.write(b);return
  if p=="/icon.svg":
   b=(Path(__file__).parent/"icon.svg").read_bytes();self.send_response(200);self.send_header("Content-Type","image/svg+xml");self.send_header("Content-Length",str(len(b)));self.end_headers();self.wfile.write(b);return
  if p=="/version":return self.sendj(200,{"build":BUILD})
  if p=="/health":return self.sendj(200,{"status":"ok","app":"SH PREDICTION","build":BUILD,"admin_key_configured":bool(TOKEN),"admin_key_length":len(TOKEN)})
  # v0 data endpoints hold the original prediction register: admin only (master script: viewers never see it)
  if not self.admin_ok():return self.sendj(403,{"error":"admin token required"})
  with db() as c:
   if p=="/fixtures": rows=c.execute("SELECT * FROM fixtures ORDER BY start_utc DESC LIMIT 200")
   elif p=="/results": rows=c.execute("SELECT f.*,o.toss_winner,o.match_winner FROM fixtures f JOIN outcomes o ON f.id=o.fixture_id ORDER BY f.start_utc DESC LIMIT 200")
   elif p=="/predictions": rows=c.execute("SELECT * FROM legacy_predictions WHERE status='approved' ORDER BY id DESC LIMIT 200")
   elif p=="/archive": rows=c.execute("SELECT * FROM archive WHERE reviewed=1 ORDER BY id DESC LIMIT 200")
   elif p=="/admin/drafts": rows=c.execute("SELECT * FROM legacy_predictions WHERE status='draft'")
   elif p=="/admin/odds_pending": rows=c.execute("SELECT * FROM odds WHERE reviewed=0 ORDER BY id DESC LIMIT 200")
   elif p=="/odds":
    try: fid=int(parse_qs(urlparse(self.path).query).get("fixture_id",["0"])[0])
    except ValueError:return self.sendj(400,{"error":"invalid fixture"})
    rows=c.execute("SELECT team,price,observed_at,source FROM odds WHERE reviewed=1 AND fixture_id=? ORDER BY observed_at",(fid,))
   elif p=="/accuracy": return self.sendj(200,compute(c)[1])
   elif p=="/register": return self.sendj(200,[{k:v for k,v in r.items() if k!="has_prediction"} for r in compute(c)[0]])
   elif p=="/register.csv":
    b=csv_text(compute(c)[0]).encode("utf-8-sig");self.send_response(200);self.send_header("Content-Type","text/csv; charset=utf-8");self.send_header("Content-Disposition","attachment; filename=sh-prediction-register.csv");self.send_header("Content-Length",str(len(b)));self.end_headers();self.wfile.write(b);return
   elif p=="/admin/audit": rows=c.execute("SELECT * FROM audit_logs ORDER BY id DESC LIMIT 200")
   else:return self.sendj(404,{"error":"not found"})
   return self.sendj(200,[dict(x) for x in rows])
 def do_POST(self):
  if urlparse(self.path).path.startswith("/api/v1/"):return self.v1("POST")
  try:
   p=urlparse(self.path).path;d=self.body();old=None
   if p=="/auth/generate":
    # the on-screen phone code proves nothing about phone ownership: disabled outside local development
    if os.getenv("SH_DEV_PHONE_LOGIN")!="1":return self.sendj(410,{"error":"Phone code login is disabled. Use account login (username/email + password)."})
    return self.sendj(200,generate(d.get("phone","")))
   if p=="/auth/verify":
    token=verify(d.get("phone",""),d.get("otp",""))
    return self.sendj(200,{"token":token}) if token else self.sendj(403,{"error":"Incorrect or expired code"})
   if p=="/auth/logout":
    logout(self.headers.get("Authorization","").removeprefix("Bearer ").strip())
    return self.sendj(200,{"status":"logged_out"})
   if not p.startswith("/admin/") or not self.admin_ok():return self.sendj(403,{"error":"admin token required"})
   with db() as c:
    if p=="/admin/fixtures":
     for k in ("competition","season","home","away","start_utc","source"):
      if not str(d.get(k,"")).strip():raise ValueError("missing "+k)
     if d["home"]==d["away"]:raise ValueError("teams must differ")
     dt=datetime.datetime.fromisoformat(d["start_utc"].replace("Z","+00:00"))
     if dt.tzinfo is None:raise ValueError("timezone required")
     c.execute("INSERT OR IGNORE INTO fixtures(competition,season,home,away,start_utc,source,venue,match_no) VALUES(?,?,?,?,?,?,?,?)",tuple(d[k] for k in ("competition","season","home","away","start_utc","source"))+(d.get("venue"),d.get("match_no")))
     result={"status":"saved"}
    elif p=="/admin/predictions":
     f=c.execute("SELECT * FROM fixtures WHERE id=?",(d["fixture_id"],)).fetchone()
     if not f:raise ValueError("unknown fixture")
     if now()>=datetime.datetime.fromisoformat(f["start_utc"].replace("Z","+00:00")).astimezone(datetime.timezone.utc).isoformat():raise ValueError("match already started")
     for k in ("toss_pick","winner_pick"):
      if d.get(k) and d[k] not in (f["home"],f["away"]):raise ValueError("invalid "+k)
     c.execute("INSERT INTO legacy_predictions(fixture_id,toss_pick,winner_pick,created_at) VALUES(?,?,?,?)",(d["fixture_id"],d.get("toss_pick"),d.get("winner_pick"),now()))
     result={"status":"draft"}
    elif p=="/admin/approve":
     r=c.execute("SELECT p.*,f.start_utc FROM legacy_predictions p JOIN fixtures f ON f.id=p.fixture_id WHERE p.id=?",(d["prediction_id"],)).fetchone()
     if not r or r["status"]!="draft":raise ValueError("draft not found")
     if now()>=datetime.datetime.fromisoformat(r["start_utc"].replace("Z","+00:00")).astimezone(datetime.timezone.utc).isoformat():raise ValueError("match already started")
     c.execute("UPDATE legacy_predictions SET status='approved',approved_at=? WHERE id=?",(now(),d["prediction_id"]));result={"status":"approved"}
    elif p=="/admin/outcomes":
     f=c.execute("SELECT * FROM fixtures WHERE id=?",(d["fixture_id"],)).fetchone()
     if not f:raise ValueError("unknown fixture")
     for k in ("toss_winner","match_winner"):
      if d.get(k) and d[k] not in (f["home"],f["away"]):raise ValueError("invalid "+k)
     if not d.get("source"):raise ValueError("source required")
     if c.execute("SELECT 1 FROM outcomes WHERE fixture_id=?",(d["fixture_id"],)).fetchone():raise ValueError("outcome already recorded")
     if d.get("status","completed") not in ("completed","abandoned","no_result","void"):raise ValueError("invalid status")
     if d.get("toss_decision") not in (None,"Bat","Bowl"):raise ValueError("invalid toss_decision")
     c.execute("INSERT INTO outcomes(fixture_id,toss_winner,match_winner,source,verified_at,status,toss_decision,remarks) VALUES(?,?,?,?,?,?,?,?)",(d["fixture_id"],d.get("toss_winner"),d.get("match_winner"),d["source"],now(),d.get("status","completed"),d.get("toss_decision"),d.get("remarks")));result={"status":"recorded"}
    elif p=="/admin/outcomes_revise":
     o=c.execute("SELECT * FROM outcomes WHERE fixture_id=?",(d["fixture_id"],)).fetchone()
     if not o:raise ValueError("no outcome to revise")
     f=c.execute("SELECT home,away FROM fixtures WHERE id=?",(d["fixture_id"],)).fetchone()
     if not str(d.get("reason","")).strip() or not str(d.get("source","")).strip():raise ValueError("reason and source required")
     for k in ("toss_winner","match_winner"):
      if d.get(k) and d[k] not in (f["home"],f["away"]):raise ValueError("invalid "+k)
     if d.get("status","completed") not in ("completed","abandoned","no_result","void"):raise ValueError("invalid status")
     if d.get("toss_decision") not in (None,"Bat","Bowl"):raise ValueError("invalid toss_decision")
     old=dict(o);m={k:d[k] for k in ("toss_winner","match_winner","status","toss_decision","remarks") if k in d}
     if m:c.execute("UPDATE outcomes SET "+",".join(k+"=?" for k in m)+",source=?,verified_at=? WHERE fixture_id=?",tuple(m.values())+(d["source"],now(),d["fixture_id"]))
     result={"status":"revised"}
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
    if p.startswith("/admin/"):c.execute("INSERT INTO audit_logs(action,payload,old_value,created_at) VALUES(?,?,?,?)",(p,json.dumps(d,ensure_ascii=False)[:4000],json.dumps(old,ensure_ascii=False) if old else None,now()))
    c.commit();return self.sendj(200,result)
  except (ValueError,KeyError,TypeError,sqlite3.Error) as e:return self.sendj(400,{"error":str(e)})
WORKER=None
def start_worker():
 global WORKER
 if WORKER is None and os.getenv("SH_WORKER_INLINE","1")=="1":WORKER=media.Worker(db,social.on_media_ready).start()
 return WORKER
def auto_prepare_empty_db():
 """A brand-new, empty database (e.g. after a restart on a host without a persistent disk) is prepared at startup:
 there is nothing to back up or lose. A database that holds any data still waits for the admin's
 'Back up and run migration' action. SH_AUTO_PREPARE_EMPTY=0 turns this off."""
 if os.getenv("SH_AUTO_PREPARE_EMPTY","1")=="0":return "disabled"
 import schema
 c=db()
 try:
  if not schema.pending(c):return "up_to_date"
  if sqlite3.Connection.execute(c,"SELECT 1 FROM sqlite_master WHERE name='schema_migrations'").fetchone():return "has_data"
  tables=[r[0] for r in sqlite3.Connection.execute(c,"SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'")]
  if any(sqlite3.Connection.execute(c,'SELECT 1 FROM "%s" LIMIT 1'%t).fetchone() for t in tables):return "has_data"
  schema.migrate(c);c.commit()
  print("SH PREDICTION: empty database prepared at startup (migrations applied)",flush=True)
  return "prepared"
 finally:c.close()
if __name__=="__main__":
 with db():pass
 start_worker()
 auto_prepare_empty_db()
 import scheduler;scheduler.start(db)  # 24/7 data collectors (SH_COLLECTORS=0 disables)
 ThreadingHTTPServer((os.getenv("HOST","0.0.0.0"),int(os.getenv("PORT","8080"))),H).serve_forever()

import os,sys,json,tempfile,threading,unittest,urllib.request,urllib.error
d=tempfile.mkdtemp();os.environ["SH_PREDICTION_DB"]=d+"/t.sqlite3";os.environ["SH_PREDICTION_ADMIN_TOKEN"]="adm-test-token"
sys.path.insert(0,os.path.join(os.path.dirname(__file__),"..","app"))
import main
from http.server import ThreadingHTTPServer
srv=ThreadingHTTPServer(("127.0.0.1",0),main.H);threading.Thread(target=srv.serve_forever,daemon=True).start()
B="http://127.0.0.1:%d"%srv.server_port
def call(path,data=None,h=None):
 r=urllib.request.Request(B+path,data=json.dumps(data).encode() if data is not None else None,headers=dict({"Content-Type":"application/json"},**(h or {})))
 try:
  x=urllib.request.urlopen(r);return x.status,json.loads(x.read())
 except urllib.error.HTTPError as e:return e.code,json.loads(e.read())
def login(phone):
 s,o=call("/auth/generate",{"phone":phone});s,t=call("/auth/verify",{"phone":phone,"otp":o["otp"]});return t["token"]
class T(unittest.TestCase):
 def test_health_public(self):self.assertEqual(call("/health")[0],200)
 def test_data_needs_login(self):self.assertEqual(call("/fixtures")[0],403)
 def test_user_cannot_use_admin(self):
  tok=login("9000000001");h={"Authorization":"Bearer "+tok}
  self.assertEqual(call("/fixtures",h=h)[0],200)
  self.assertEqual(call("/admin/fixtures",{"competition":"x","season":"1","home":"A","away":"B","start_utc":"2030-01-01T00:00:00Z","source":"s"},h)[0],403)
  self.assertEqual(call("/admin/drafts",h=h)[0],403)
 def test_admin_flow(self):
  a={"X-Admin-Token":"adm-test-token"}
  self.assertEqual(call("/admin/fixtures",{"competition":"x","season":"1","home":"A","away":"B","start_utc":"2030-01-01T00:00:00Z","source":"s"},a)[0],200)
  self.assertEqual(call("/admin/fixtures",{"competition":"x","season":"1","home":"A","away":"A","start_utc":"2030-01-01T00:00:00Z","source":"s"},a)[0],400)
  self.assertEqual(call("/admin/fixtures",{},{"X-Admin-Token":"wrong"})[0],403)
 def test_outcome_once(self):
  a={"X-Admin-Token":"adm-test-token"}
  call("/admin/fixtures",{"competition":"y","season":"1","home":"C","away":"D","start_utc":"2030-02-01T00:00:00Z","source":"s"},a)
  import sqlite3;fid=sqlite3.connect(os.environ["SH_PREDICTION_DB"]).execute("select id from fixtures where home='C'").fetchone()[0]
  o={"fixture_id":fid,"toss_winner":"C","match_winner":"D","source":"manual"}
  self.assertEqual(call("/admin/outcomes",o,a)[0],200);self.assertEqual(call("/admin/outcomes",o,a)[0],400)
 def test_bad_phone(self):self.assertEqual(call("/auth/generate",{"phone":"12"})[0],400)
if __name__=="__main__":unittest.main()

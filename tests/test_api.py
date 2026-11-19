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
  self.assertEqual(call("/fixtures",h=h)[0],403)  # v0 register data is admin-only now
  self.assertEqual(call("/fixtures",h={"X-Admin-Token":"adm-test-token"})[0],200)
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

# ---- accuracy engine / settlement / immutability / audit ----
import sqlite3
A={"X-Admin-Token":"adm-test-token"}
def q1(sql,args=()):
 c=sqlite3.connect(os.environ["SH_PREDICTION_DB"],timeout=10)
 try:return c.execute(sql,args).fetchone()[0]
 finally:c.close()
def fx(h,a,comp="Eng Cup",start="2031-01-01T10:00:00Z"):
 call("/admin/fixtures",{"competition":comp,"season":"2031","home":h,"away":a,"start_utc":start,"source":"manual","venue":"Test Ground","match_no":"1"},A)
 return q1("select id from fixtures where home=? and away=?",(h,a))
def predict(fid,toss,win):
 call("/admin/predictions",{"fixture_id":fid,"toss_pick":toss,"winner_pick":win},A)
 pid=q1("select id from legacy_predictions where fixture_id=?",(fid,))
 call("/admin/approve",{"prediction_id":pid},A);return pid
class Acc(unittest.TestCase):
 def test_settlement_rules(self):
  h={"Authorization":"Bearer "+login("9000000002")}
  f1=fx("P1","Q1","Acc Cup");predict(f1,"P1","P1");call("/admin/outcomes",{"fixture_id":f1,"toss_winner":"P1","match_winner":"Q1","source":"m","toss_decision":"Bat"},A)   # toss correct, winner wrong
  f2=fx("P2","Q2","Acc Cup");predict(f2,"Q2","Q2");call("/admin/outcomes",{"fixture_id":f2,"toss_winner":"P2","match_winner":"Q2","source":"m"},A)                       # toss wrong, winner correct
  f3=fx("P3","Q3","Acc Cup");predict(f3,"P3","P3")                                                                                                                   # pending
  f4=fx("P4","Q4","Acc Cup");predict(f4,"P4","P4");call("/admin/outcomes",{"fixture_id":f4,"match_winner":None,"source":"m","status":"abandoned"},A)                # void
  s,acc=call("/accuracy",h=A);self.assertEqual(s,200)
  t,w=acc["by_competition"]["Acc Cup"]["toss"],acc["by_competition"]["Acc Cup"]["winner"]
  self.assertEqual((t["correct"],t["wrong"],t["pending"],t["void"],t["total"],t["percent"]),(1,1,1,1,2,50.0))
  self.assertEqual((w["correct"],w["wrong"],w["pending"],w["void"],w["total"],w["percent"]),(1,1,1,1,2,50.0))
  self.assertEqual(acc["toss"]["total"],acc["toss"]["correct"]+acc["toss"]["wrong"])
  s,reg=call("/register",h=A);row=[r for r in reg if r["match_id"]==f1][0]
  self.assertEqual((row["toss_result"],row["winner_result"],row["toss_decision"],row["venue"]),("Correct","Wrong","Bat","Test Ground"))
 def test_late_prediction_excluded(self):
  f=fx("L1","L2")
  c=sqlite3.connect(os.environ["SH_PREDICTION_DB"],timeout=10);c.execute("INSERT INTO legacy_predictions(fixture_id,toss_pick,winner_pick,created_at,status,approved_at) VALUES(?,?,?,?,?,?)",(f,"L1","L1","2031-01-02T00:00:00+00:00","approved","2031-01-02T00:00:00+00:00"));c.commit();c.close()
  call("/admin/outcomes",{"fixture_id":f,"toss_winner":"L1","match_winner":"L1","source":"m"},A)
  s,reg=call("/register",h=A);r=[x for x in reg if x["match_id"]==f][0]
  self.assertEqual((r["toss_result"],r["winner_result"]),("Ineligible","Ineligible"))
 def test_approved_prediction_immutable(self):
  f=fx("I1","I2");pid=predict(f,"I1","I1")
  c=main.db()
  try:
   with self.assertRaises(sqlite3.DatabaseError):c.execute("UPDATE legacy_predictions SET winner_pick='I2' WHERE id=?",(pid,))
   with self.assertRaises(sqlite3.DatabaseError):c.execute("DELETE FROM legacy_predictions WHERE id=?",(pid,))
  finally:c.close()
 def test_revision_audited_and_admin_only(self):
  f=fx("R1","R2");call("/admin/outcomes",{"fixture_id":f,"toss_winner":"R1","match_winner":"R1","source":"m"},A)
  self.assertEqual(call("/admin/outcomes_revise",{"fixture_id":f,"match_winner":"R2","source":"s","reason":"correction"},{"Authorization":"Bearer "+login("9000000004")})[0],403)
  self.assertEqual(call("/admin/outcomes_revise",{"fixture_id":f,"match_winner":"R2"},A)[0],400)  # reason+source required
  self.assertEqual(call("/admin/outcomes_revise",{"fixture_id":f,"match_winner":"R2","source":"s","reason":"correction"},A)[0],200)
  s,log=call("/admin/audit",h=A);rev=[x for x in log if x["action"]=="/admin/outcomes_revise"][0]
  self.assertIn('"R1"',rev["old_value"])
 def test_csv_export_neutralises_formulas(self):
  self.assertTrue(main.csv_text([dict({k:None for k in main.REG_COLS},home="=SUM(1)")]).count("'=SUM(1)")==1)

if __name__=="__main__":unittest.main()

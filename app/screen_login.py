import secrets,time,threading,re,os,sqlite3,hashlib
lock=threading.RLock()
pending={}
DB=os.getenv("SH_PREDICTION_DB","data/prediction.sqlite3")
def connection():
 os.makedirs(os.path.dirname(os.path.abspath(DB)),exist_ok=True)
 c=sqlite3.connect(DB,timeout=10)
 c.execute("CREATE TABLE IF NOT EXISTS login_sessions(token_hash TEXT PRIMARY KEY, phone TEXT NOT NULL, created_at REAL NOT NULL)")
 return c
def generate(phone):
 if not isinstance(phone,str) or not re.fullmatch(r"[0-9]{10,15}",phone):raise ValueError("Enter a valid mobile number")
 with lock:
  t=time.time()
  for k,v in list(pending.items()):
   if v["expires"]<t:pending.pop(k,None)
  if phone in pending and t-pending[phone]["issued"]<20:raise ValueError("Wait 20 seconds")
  code=f"{secrets.randbelow(1000000):06d}"
  pending[phone]={"code":code,"issued":t,"expires":t+300,"tries":0}
  return {"otp":code,"expires_in_seconds":300,"warning":"On-screen OTP does not prove phone ownership"}
def verify(phone,code):
 with lock:
  p=pending.get(phone)
  if not p or p["expires"]<time.time():return None
  p["tries"]+=1
  if p["tries"]>5:pending.pop(phone,None);return None
  if not secrets.compare_digest(str(code),p["code"]):return None
  pending.pop(phone,None)
  token=secrets.token_urlsafe(32)
  with connection() as c:c.execute("INSERT INTO login_sessions(token_hash,phone,created_at) VALUES(?,?,?)",(hashlib.sha256(token.encode()).hexdigest(),phone,time.time()))
  return token
def authorized(token):
 if not token:return False
 with connection() as c:
  return c.execute("SELECT 1 FROM login_sessions WHERE token_hash=?",(hashlib.sha256(token.encode()).hexdigest(),)).fetchone() is not None
def logout(token):
 if token:
  with connection() as c:c.execute("DELETE FROM login_sessions WHERE token_hash=?",(hashlib.sha256(token.encode()).hexdigest(),))

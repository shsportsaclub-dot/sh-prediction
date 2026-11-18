import secrets,time,threading,re
lock=threading.RLock()
pending={}
sessions={}
def clean():
 t=time.time()
 for store in (pending,sessions):
  for k,v in list(store.items()):
   if v["expires"]<t:store.pop(k,None)
def generate(phone):
 if not isinstance(phone,str) or not re.fullmatch(r"[0-9]{10,15}",phone):raise ValueError("Enter a valid mobile number")
 with lock:
  clean()
  if phone in pending and time.time()-pending[phone]["issued"]<20:raise ValueError("Wait 20 seconds")
  code=f"{secrets.randbelow(1000000):06d}"
  pending[phone]={"code":code,"issued":time.time(),"expires":time.time()+300,"tries":0}
  return {"otp":code,"expires_in_seconds":300,"warning":"On-screen OTP does not prove phone ownership"}
def verify(phone,code):
 with lock:
  clean()
  p=pending.get(phone)
  if not p:return None
  p["tries"]+=1
  if p["tries"]>5:pending.pop(phone,None);return None
  if not secrets.compare_digest(str(code),p["code"]):return None
  pending.pop(phone,None)
  token=secrets.token_urlsafe(32)
  sessions[token]={"expires":time.time()+8*3600,"phone":phone}
  return token
def authorized(token):
 with lock:
  clean()
  return bool(token and token in sessions)
def logout(token):
 with lock:sessions.pop(token,None)

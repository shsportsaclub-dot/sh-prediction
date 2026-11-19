"""SH accounts: username + password (PBKDF2-SHA256), email verification and password reset by one-time codes,
server-side sessions, lockout after repeated failures, account deletion.

* Codes are only ever delivered by email (SMTP settings in server environment variables). They are never
  returned by the API or shown on screen. If SMTP is not configured the message is recorded in mail_outbox
  with status 'not_configured' and an admin can verify the account manually from the admin panel.
* The old on-screen phone code login is disabled unless SH_DEV_PHONE_LOGIN=1 (local development only).
"""
import datetime
import hashlib
import hmac
import os
import re
import secrets
import smtplib
from email.message import EmailMessage

from schema import now

PBKDF2_ITERATIONS = 310000
SESSION_DAYS = 30
CODE_MINUTES = 15
MAX_FAILED = 5
LOCK_MINUTES = 15
USERNAME_RE = re.compile(r"^[a-z0-9_]{3,24}$")
EMAIL_RE = re.compile(r"^[^@\s]{1,64}@[^@\s]{1,190}\.[a-z]{2,24}$", re.I)

class AuthError(Exception):
    def __init__(self, status, code, message):
        super().__init__(message)
        self.status, self.code, self.message = status, code, message

def _ts(minutes=0, days=0):
    return (datetime.datetime.now(datetime.timezone.utc) + datetime.timedelta(minutes=minutes, days=days)).isoformat()

def hash_password(pw):
    salt = secrets.token_bytes(16)
    dk = hashlib.pbkdf2_hmac("sha256", pw.encode(), salt, PBKDF2_ITERATIONS)
    return "pbkdf2_sha256$%d$%s$%s" % (PBKDF2_ITERATIONS, salt.hex(), dk.hex())

def check_password(pw, stored):
    try:
        algo, it, salt, dk = stored.split("$")
        got = hashlib.pbkdf2_hmac("sha256", pw.encode(), bytes.fromhex(salt), int(it))
        return algo == "pbkdf2_sha256" and hmac.compare_digest(got.hex(), dk)
    except (ValueError, AttributeError):
        return False

def validate_password(pw):
    if not isinstance(pw, str) or len(pw) < 10 or len(pw) > 200:
        raise AuthError(400, "WEAK_PASSWORD", "password must be 10-200 characters")
    if pw.lower() == pw or pw.upper() == pw or not re.search(r"\d", pw):
        raise AuthError(400, "WEAK_PASSWORD", "use upper and lower case letters and at least one digit")

# ------------------------------------------------------------------ mail
def smtp_configured():
    return bool(os.getenv("SH_SMTP_HOST") and os.getenv("SH_SMTP_FROM"))

def send_mail(c, to, subject, body):
    c.execute("INSERT INTO mail_outbox(to_address,subject,body,status,created_at) VALUES(?,?,?,?,?)",
              (to, subject, body, "queued" if smtp_configured() else "not_configured", now()))
    mid = c.execute("SELECT last_insert_rowid()").fetchone()[0]
    if not smtp_configured():
        return "not_configured"
    try:
        msg = EmailMessage()
        msg["From"], msg["To"], msg["Subject"] = os.getenv("SH_SMTP_FROM"), to, subject
        msg.set_content(body)
        port = int(os.getenv("SH_SMTP_PORT", "587"))
        with smtplib.SMTP(os.getenv("SH_SMTP_HOST"), port, timeout=20) as s:
            if os.getenv("SH_SMTP_STARTTLS", "1") == "1":
                s.starttls()
            if os.getenv("SH_SMTP_USER"):
                s.login(os.getenv("SH_SMTP_USER"), os.getenv("SH_SMTP_PASSWORD", ""))
            s.send_message(msg)
        c.execute("UPDATE mail_outbox SET status='sent',sent_at=? WHERE id=?", (now(), mid))
        return "sent"
    except Exception as e:  # never leak SMTP errors to the client
        c.execute("UPDATE mail_outbox SET status='failed',error=? WHERE id=?", (str(e)[:300], mid))
        return "failed"

def _issue_code(c, user_id, purpose, email):
    code = "%06d" % secrets.randbelow(1000000)
    c.execute("UPDATE auth_codes SET used_at=? WHERE user_id=? AND purpose=? AND used_at IS NULL", (now(), user_id, purpose))
    c.execute("INSERT INTO auth_codes(user_id,purpose,code_hash,expires_at,created_at) VALUES(?,?,?,?,?)",
              (user_id, purpose, hashlib.sha256(code.encode()).hexdigest(), _ts(minutes=CODE_MINUTES), now()))
    subject = {"verify_email": "Verify your SH PREDICTION account", "reset_password": "Reset your SH PREDICTION password"}[purpose]
    body = "Your SH PREDICTION code is %s. It expires in %d minutes. If you did not ask for it, ignore this email." % (code, CODE_MINUTES)
    delivery = send_mail(c, email, subject, body)
    return code, delivery

def _use_code(c, user_id, purpose, code):
    r = c.execute("SELECT * FROM auth_codes WHERE user_id=? AND purpose=? AND used_at IS NULL ORDER BY id DESC LIMIT 1", (user_id, purpose)).fetchone()
    if not r or r["expires_at"] < now():
        raise AuthError(400, "CODE_INVALID", "code is invalid or expired")
    if r["attempts"] >= 5:
        raise AuthError(429, "TOO_MANY_ATTEMPTS", "too many attempts; request a new code")
    c.execute("UPDATE auth_codes SET attempts=attempts+1 WHERE id=?", (r["id"],))
    if not hmac.compare_digest(hashlib.sha256(str(code).encode()).hexdigest(), r["code_hash"]):
        c.commit()  # count the failed attempt even though the request fails
        raise AuthError(400, "CODE_INVALID", "code is invalid or expired")
    c.execute("UPDATE auth_codes SET used_at=? WHERE id=?", (now(), r["id"]))

def dev_expose_codes():
    return os.getenv("SH_DEV_EXPOSE_CODES") == "1"

# ------------------------------------------------------------------ account lifecycle
def register(c, d):
    open_ = c.execute("SELECT value FROM system_settings WHERE key='registration_open'").fetchone()
    if open_ and open_[0] != "1":
        raise AuthError(403, "REGISTRATION_CLOSED", "registration is closed")
    username = str(d.get("username") or "").strip().lower()
    email = str(d.get("email") or "").strip().lower()
    if not USERNAME_RE.match(username):
        raise AuthError(400, "VALIDATION_ERROR", "username: 3-24 lowercase letters, digits or _")
    if not EMAIL_RE.match(email):
        raise AuthError(400, "VALIDATION_ERROR", "a valid email address is required")
    validate_password(d.get("password"))
    if c.execute("SELECT 1 FROM accounts WHERE username=? OR email=?", (username, email)).fetchone():
        raise AuthError(409, "TAKEN", "username or email already registered")
    c.execute("INSERT INTO users(phone,display_name,role,created_at) VALUES(NULL,?, 'user', ?)", (username, now()))
    uid = c.execute("SELECT last_insert_rowid()").fetchone()[0]
    display = (str(d.get("display_name") or "").strip() or username)[:60]
    c.execute("""INSERT INTO accounts(user_id,username,email,password_hash,display_name,created_at,updated_at) VALUES(?,?,?,?,?,?,?)""",
              (uid, username, email, hash_password(d["password"]), display, now(), now()))
    code, delivery = _issue_code(c, uid, "verify_email", email)
    out = {"user_id": uid, "username": username, "email_verification": delivery}
    if dev_expose_codes():
        out["dev_code"] = code  # local tests only; never enabled in production
    return out

def _account_by_login(c, login):
    login = str(login or "").strip().lower()
    return c.execute("SELECT * FROM accounts WHERE username=? OR email=?", (login, login)).fetchone()

def verify_email(c, d):
    a = _account_by_login(c, d.get("login") or d.get("email"))
    if not a:
        raise AuthError(400, "CODE_INVALID", "code is invalid or expired")
    _use_code(c, a["user_id"], "verify_email", d.get("code"))
    c.execute("UPDATE accounts SET email_verified_at=?,updated_at=? WHERE user_id=?", (now(), now(), a["user_id"]))
    return {"verified": True}

def resend_verification(c, d):
    a = _account_by_login(c, d.get("login"))
    if a and not a["email_verified_at"] and a["status"] == "active":
        code, delivery = _issue_code(c, a["user_id"], "verify_email", a["email"])
        return {"sent": True, "dev_code": code} if dev_expose_codes() else {"sent": True}
    return {"sent": True}  # same answer either way: no account enumeration

def login(c, d, user_agent=""):
    a = _account_by_login(c, d.get("login"))
    generic = AuthError(401, "LOGIN_FAILED", "wrong username/email or password")
    if not a or a["status"] == "deleted":
        check_password(str(d.get("password") or ""), hash_password("timing-equaliser"))
        raise generic
    if a["locked_until"] and a["locked_until"] > now():
        raise AuthError(429, "LOCKED", "too many failed attempts; try again in %d minutes" % LOCK_MINUTES)
    if not check_password(str(d.get("password") or ""), a["password_hash"]):
        fails = a["failed_logins"] + 1
        c.execute("UPDATE accounts SET failed_logins=?, locked_until=? WHERE user_id=?",
                  (0 if fails >= MAX_FAILED else fails, _ts(minutes=LOCK_MINUTES) if fails >= MAX_FAILED else None, a["user_id"]))
        c.commit()  # the failure counter must survive the error response (the API rolls back on errors)
        raise generic
    if a["status"] == "suspended":
        raise AuthError(403, "SUSPENDED", "this account is suspended")
    c.execute("UPDATE accounts SET failed_logins=0, locked_until=NULL WHERE user_id=?", (a["user_id"],))
    token = secrets.token_urlsafe(32)
    c.execute("INSERT INTO auth_sessions(token_hash,user_id,created_at,last_seen_at,expires_at,user_agent) VALUES(?,?,?,?,?,?)",
              (hashlib.sha256(token.encode()).hexdigest(), a["user_id"], now(), now(), _ts(days=SESSION_DAYS), (user_agent or "")[:200]))
    return {"token": token, "user_id": a["user_id"], "username": a["username"], "email_verified": bool(a["email_verified_at"])}

def session_user(c, token):
    if not token:
        return None
    h = hashlib.sha256(token.encode()).hexdigest()
    s = c.execute("SELECT * FROM auth_sessions WHERE token_hash=?", (h,)).fetchone()
    if not s or s["expires_at"] < now():
        return None
    a = c.execute("SELECT * FROM accounts WHERE user_id=?", (s["user_id"],)).fetchone()
    if not a or a["status"] != "active":
        return None
    c.execute("UPDATE auth_sessions SET last_seen_at=? WHERE token_hash=?", (now(), h))
    return a

def logout(c, token, everywhere=False, user_id=None):
    if everywhere and user_id:
        c.execute("DELETE FROM auth_sessions WHERE user_id=?", (user_id,))
    elif token:
        c.execute("DELETE FROM auth_sessions WHERE token_hash=?", (hashlib.sha256(token.encode()).hexdigest(),))

def request_reset(c, d):
    a = _account_by_login(c, d.get("login"))
    out = {"sent": True}
    if a and a["status"] == "active" and a["email"]:
        code, _ = _issue_code(c, a["user_id"], "reset_password", a["email"])
        if dev_expose_codes():
            out["dev_code"] = code
    return out

def reset_password(c, d):
    a = _account_by_login(c, d.get("login"))
    if not a:
        raise AuthError(400, "CODE_INVALID", "code is invalid or expired")
    _use_code(c, a["user_id"], "reset_password", d.get("code"))
    validate_password(d.get("new_password"))
    c.execute("UPDATE accounts SET password_hash=?,failed_logins=0,locked_until=NULL,updated_at=? WHERE user_id=?",
              (hash_password(d["new_password"]), now(), a["user_id"]))
    c.execute("DELETE FROM auth_sessions WHERE user_id=?", (a["user_id"],))  # sign out everywhere
    return {"reset": True}

def change_password(c, a, d):
    if not check_password(str(d.get("old_password") or ""), a["password_hash"]):
        raise AuthError(401, "LOGIN_FAILED", "current password is wrong")
    validate_password(d.get("new_password"))
    c.execute("UPDATE accounts SET password_hash=?,updated_at=? WHERE user_id=?", (hash_password(d["new_password"]), now(), a["user_id"]))
    return {"changed": True}

def delete_account(c, a, d, remove_media):
    """Erases personal data: profile, email, sessions; posts deleted; media files removed.
    Locked predictions stay (anonymised) so historical accuracy cannot be rewritten by deleting an account."""
    if not check_password(str(d.get("password") or ""), a["password_hash"]):
        raise AuthError(401, "LOGIN_FAILED", "password is wrong")
    uid = a["user_id"]
    c.execute("""UPDATE accounts SET status='deleted', username=?, email=NULL, display_name='Deleted user', bio=NULL, avatar_media_id=NULL,
                 cover_media_id=NULL, password_hash='!', updated_at=? WHERE user_id=?""", ("deleted_%d" % uid, now(), uid))
    c.execute("UPDATE users SET phone=NULL, display_name='Deleted user' WHERE id=?", (uid,))
    c.execute("UPDATE posts SET status='deleted' WHERE author_id=?", (uid,))
    c.execute("UPDATE comments SET status='deleted', body='' WHERE user_id=?", (uid,))
    for tbl, col in (("follows", "follower_id"), ("follows", "followee_id"), ("reactions", "user_id"), ("bookmarks", "user_id"),
                     ("blocks", "blocker_id"), ("blocks", "blocked_id"), ("auth_sessions", "user_id")):
        c.execute("DELETE FROM %s WHERE %s=?" % (tbl, col), (uid,))
    for m in c.execute("SELECT id FROM media_assets WHERE owner_id=? AND status<>'removed'", (uid,)).fetchall():
        remove_media(c, m[0])
    c.execute("UPDATE expert_profiles SET display_name='Deleted tipster', bio=NULL, contact_url=NULL WHERE user_id=?", (uid,))
    return {"deleted": True}

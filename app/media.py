"""SH media pipeline: resumable signed uploads -> validation -> background processing -> renditions -> serving.

Storage: LocalStorage under SH_MEDIA_DIR (must be a persistent disk in production). The Storage interface is
the only place files are touched, so an S3-compatible backend can replace it without changing the API.
Images: Pillow (EXIF stripped, orientation fixed, optional crop, 1080 px + 320 px JPEG).
Video: ffprobe validation, ffmpeg H.264/AAC MP4 (faststart), JPEG thumbnail, HLS 360p + 720p with a master playlist.
Reels are normalised to vertical 9:16 (720x1280) with padding, never stretched.
"""
import hashlib
import hmac
import json
import os
import shutil
import sqlite3
import datetime
import subprocess
import threading
import time

from schema import now

LIMITS = {"image": 15 * 1024 * 1024, "video": 200 * 1024 * 1024}
MAX_VIDEO_SECONDS = {"post": 180, "reel": 90}
IMAGE_MIME = {"image/jpeg", "image/png", "image/webp", "image/gif"}
VIDEO_MIME = {"video/mp4", "video/quicktime", "video/webm", "video/x-matroska", "video/3gpp"}
CHUNK = 1024 * 1024
URL_TTL = 6 * 3600
_SIGNING_KEY = (os.getenv("SH_MEDIA_SIGNING_KEY") or os.urandom(32).hex()).encode()

class MediaError(Exception):
    def __init__(self, status, code, message):
        super().__init__(message)
        self.status, self.code, self.message = status, code, message

# ------------------------------------------------------------------ storage
class LocalStorage:
    name = "local-disk"
    def __init__(self, root):
        self.root = os.path.abspath(root)
        os.makedirs(self.root, exist_ok=True)
    def path(self, key):
        p = os.path.abspath(os.path.join(self.root, key))
        if not p.startswith(self.root + os.sep):
            raise MediaError(400, "BAD_PATH", "invalid media path")
        return p
    def dir_for(self, media_id):
        d = self.path(str(int(media_id)))
        os.makedirs(d, exist_ok=True)
        return d
    def delete_media(self, media_id):
        shutil.rmtree(self.path(str(int(media_id))), ignore_errors=True)
    def usage(self):
        total = files = 0
        for dp, _, fs in os.walk(self.root):
            for f in fs:
                files += 1
                total += os.path.getsize(os.path.join(dp, f))
        du = shutil.disk_usage(self.root)
        return {"backend": self.name, "root": self.root, "bytes": total, "files": files, "disk_free_bytes": du.free, "disk_total_bytes": du.total}

STORAGE = None

def tools():
    """What this server can actually do; video processing needs ffmpeg/ffprobe, images need Pillow."""
    try:
        import PIL  # noqa: F401
        pil = True
    except ImportError:
        pil = False
    return {"pillow": pil, "ffmpeg": bool(shutil.which("ffmpeg")), "ffprobe": bool(shutil.which("ffprobe")),
            "virus_scanner": bool(shutil.which("clamdscan") or shutil.which("clamscan"))}

def storage():
    global STORAGE
    if STORAGE is None:
        root = os.getenv("SH_MEDIA_DIR") or os.path.join(os.path.dirname(os.path.abspath(os.getenv("SH_PREDICTION_DB", "data/prediction.sqlite3"))), "media")
        STORAGE = LocalStorage(root)
    return STORAGE

# ------------------------------------------------------------------ signed upload URLs
def sign(media_id, exp):
    return hmac.new(_SIGNING_KEY, ("%d:%d" % (media_id, exp)).encode(), hashlib.sha256).hexdigest()

def upload_url(media_id):
    exp = int(time.time()) + URL_TTL
    return "/api/v1/media/uploads/%d?exp=%d&sig=%s" % (media_id, exp, sign(media_id, exp))

def check_sig(media_id, exp, sig):
    try:
        exp = int(exp)
    except (TypeError, ValueError):
        return False
    return exp >= time.time() and hmac.compare_digest(sign(media_id, exp), str(sig or ""))

def init_upload(c, user_id, d):
    kind = d.get("kind")
    if kind not in LIMITS:
        raise MediaError(400, "VALIDATION_ERROR", "kind must be image or video")
    purpose = d.get("purpose", "post")
    if purpose not in ("post", "reel", "avatar", "cover") or (purpose == "reel" and kind != "video") or (purpose in ("avatar", "cover") and kind != "image"):
        raise MediaError(400, "VALIDATION_ERROR", "invalid purpose for this kind")
    mime = str(d.get("mime") or "").lower()
    if mime not in (IMAGE_MIME if kind == "image" else VIDEO_MIME):
        raise MediaError(415, "UNSUPPORTED_TYPE", "file type not allowed")
    try:
        size = int(d.get("bytes"))
    except (TypeError, ValueError):
        raise MediaError(400, "VALIDATION_ERROR", "bytes required")
    limit = LIMITS[kind]
    s = c.execute("SELECT value FROM system_settings WHERE key=?", ("max_%s_mb" % kind,)).fetchone()
    if s:
        limit = int(s[0]) * 1024 * 1024
    if not 1 <= size <= limit:
        raise MediaError(413, "TOO_LARGE", "file must be at most %d MB" % (limit // (1024 * 1024)))
    pending = c.execute("SELECT COUNT(*) FROM media_assets WHERE owner_id=? AND status IN ('uploading','processing')", (user_id,)).fetchone()[0]
    if pending >= 10:
        raise MediaError(429, "TOO_MANY_UPLOADS", "finish your current uploads first")
    crop = d.get("crop")
    if crop is not None:
        if kind != "image" or not isinstance(crop, dict) or not all(isinstance(crop.get(k), (int, float)) and 0 <= crop[k] <= 1 for k in ("x", "y", "w", "h")) \
                or crop["w"] <= 0 or crop["h"] <= 0 or crop["x"] + crop["w"] > 1.0001 or crop["y"] + crop["h"] > 1.0001:
            raise MediaError(400, "VALIDATION_ERROR", "crop must be fractions x,y,w,h within the image")
    c.execute("""INSERT INTO media_assets(owner_id,kind,purpose,status,filename,mime,declared_bytes,crop_json,upload_secret,created_at,updated_at)
                 VALUES(?,?,?,'uploading',?,?,?,?,?,?,?)""", (user_id, kind, purpose, str(d.get("filename") or "")[:120], mime, size,
                                                          json.dumps(crop) if crop else None, os.urandom(8).hex(), now(), now()))
    mid = c.execute("SELECT last_insert_rowid()").fetchone()[0]
    open(os.path.join(storage().dir_for(mid), "original.part"), "wb").close()
    return {"media_id": mid, "upload_url": upload_url(mid), "chunk_bytes": CHUNK, "received_bytes": 0, "status": "uploading"}

def put_chunk(c, media_id, start, data):
    a = c.execute("SELECT * FROM media_assets WHERE id=?", (media_id,)).fetchone()
    if not a or a["status"] != "uploading":
        raise MediaError(409, "NOT_UPLOADING", "upload is not open")
    if start != a["received_bytes"]:
        raise MediaError(409, "OFFSET_MISMATCH", "resume from byte %d" % a["received_bytes"])
    if a["received_bytes"] + len(data) > a["declared_bytes"]:
        raise MediaError(413, "TOO_LARGE", "more bytes than declared")
    with open(os.path.join(storage().dir_for(media_id), "original.part"), "ab") as f:
        f.write(data)
    c.execute("UPDATE media_assets SET received_bytes=received_bytes+?, updated_at=? WHERE id=?", (len(data), now(), media_id))
    return {"media_id": media_id, "received_bytes": a["received_bytes"] + len(data), "declared_bytes": a["declared_bytes"]}

def _sniff(path):
    with open(path, "rb") as f:
        h = f.read(16)
    if h[:3] == b"\xff\xd8\xff" or h[:8] == b"\x89PNG\r\n\x1a\n" or h[:4] == b"RIFF" and h[8:12] == b"WEBP" or h[:6] in (b"GIF87a", b"GIF89a"):
        return "image"
    if h[4:8] == b"ftyp" or h[:4] == b"\x1aE\xdf\xa3":
        return "video"
    return None

def scan_file(path):
    """Malware scanning hook: uses ClamAV when installed on the server, otherwise records 'not_scanned'."""
    exe = shutil.which("clamdscan") or shutil.which("clamscan")
    if not exe:
        return "not_scanned"
    r = subprocess.run([exe, "--no-summary", path], capture_output=True, text=True, timeout=120)
    return "clean" if r.returncode == 0 else ("infected" if r.returncode == 1 else "scan_error")

def complete_upload(c, media_id):
    a = c.execute("SELECT * FROM media_assets WHERE id=?", (media_id,)).fetchone()
    if not a or a["status"] != "uploading":
        raise MediaError(409, "NOT_UPLOADING", "upload is not open")
    if a["received_bytes"] != a["declared_bytes"]:
        raise MediaError(409, "INCOMPLETE", "received %d of %d bytes" % (a["received_bytes"], a["declared_bytes"]))
    part = os.path.join(storage().dir_for(media_id), "original.part")
    kind = _sniff(part)
    if kind != a["kind"]:
        c.execute("UPDATE media_assets SET status='failed', error='content does not match declared type', updated_at=? WHERE id=?", (now(), media_id))
        os.remove(part)
        raise MediaError(415, "UNSUPPORTED_TYPE", "file content is not a supported %s" % a["kind"])
    scan = scan_file(part)
    if scan == "infected":
        c.execute("UPDATE media_assets SET status='failed', scan_status=?, error='malware detected', updated_at=? WHERE id=?", (scan, now(), media_id))
        os.remove(part)
        raise MediaError(422, "REJECTED", "file rejected by malware scan")
    sha = hashlib.sha256()
    with open(part, "rb") as f:
        for b in iter(lambda: f.read(1 << 20), b""):
            sha.update(b)
    os.replace(part, os.path.join(storage().dir_for(media_id), "original"))
    c.execute("UPDATE media_assets SET status='processing', sha256=?, scan_status=?, updated_at=? WHERE id=?", (sha.hexdigest(), scan, now(), media_id))
    c.execute("INSERT INTO jobs(kind,ref_id,status,created_at,updated_at) VALUES('process_media',?,'queued',?,?)", (media_id, now(), now()))
    return {"media_id": media_id, "status": "processing", "scan_status": scan}

# ------------------------------------------------------------------ processing
def _rendition(c, media_id, kind, filename, mime, width=None, height=None):
    p = os.path.join(storage().dir_for(media_id), filename)
    c.execute("INSERT OR REPLACE INTO media_renditions(media_id,kind,path,mime,width,height,bytes) VALUES(?,?,?,?,?,?,?)",
              (media_id, kind, "%d/%s" % (media_id, filename), mime, width, height, os.path.getsize(p)))

def process_image(c, a):
    from PIL import Image, ImageOps
    Image.MAX_IMAGE_PIXELS = 40_000_000
    d = storage().dir_for(a["id"])
    with Image.open(os.path.join(d, "original")) as im:
        im.load()
        im = ImageOps.exif_transpose(im)
        if getattr(im, "is_animated", False):
            im.seek(0)
        im = im.convert("RGB")
        if a["crop_json"]:
            cr = json.loads(a["crop_json"])
            W, H = im.size
            im = im.crop((int(cr["x"] * W), int(cr["y"] * H), int((cr["x"] + cr["w"]) * W), int((cr["y"] + cr["h"]) * H)))
        W, H = im.size
        for kind, side, q in (("image_lg", 1080, 84), ("thumb", 320, 78)):
            r = im.copy()
            r.thumbnail((side, side))
            r.save(os.path.join(d, kind + ".jpg"), "JPEG", quality=q, optimize=True, progressive=True)  # re-encode: metadata dropped
            _rendition(c, a["id"], kind, kind + ".jpg", "image/jpeg", r.size[0], r.size[1])
    c.execute("UPDATE media_assets SET width=?, height=? WHERE id=?", (W, H, a["id"]))
    os.remove(os.path.join(d, "original"))  # keep only cleaned renditions (no original EXIF/GPS on disk)
    return "image %dx%d -> 1080/320 jpeg" % (W, H)

def _ffprobe(path):
    if not shutil.which("ffprobe"):
        raise MediaError("ffmpeg/ffprobe is not installed on this server; deploy with the Dockerfile")
    r = subprocess.run(["ffprobe", "-v", "error", "-print_format", "json", "-show_streams", "-show_format", path], capture_output=True, text=True, timeout=60)
    if r.returncode:
        raise MediaError(415, "UNSUPPORTED_TYPE", "not a readable video")
    info = json.loads(r.stdout)
    v = next((s for s in info.get("streams", []) if s.get("codec_type") == "video"), None)
    if not v:
        raise MediaError(415, "UNSUPPORTED_TYPE", "no video stream")
    has_audio = any(s.get("codec_type") == "audio" for s in info.get("streams", []))
    rot = 0
    for sd in v.get("side_data_list", []) or []:
        if "rotation" in sd:
            rot = abs(int(sd["rotation"]))
    w, h = int(v["width"]), int(v["height"])
    if rot in (90, 270):
        w, h = h, w
    return w, h, float(info["format"].get("duration") or v.get("duration") or 0), has_audio

def _ff(args, log):
    r = subprocess.run(["ffmpeg", "-hide_banner", "-loglevel", "error", "-y"] + args, capture_output=True, text=True, timeout=1800)
    log.append("ffmpeg %s -> %d %s" % (" ".join(a for a in args if not a.startswith("/")), r.returncode, r.stderr[-300:]))
    if r.returncode:
        raise MediaError(500, "PROCESSING_FAILED", "ffmpeg failed")

def process_video(c, a, log):
    d = storage().dir_for(a["id"])
    src = os.path.join(d, "original")
    w, h, dur, has_audio = _ffprobe(src)
    if dur <= 0 or dur > MAX_VIDEO_SECONDS["reel" if a["purpose"] == "reel" else "post"]:
        raise MediaError(422, "TOO_LONG", "video must be up to %d seconds" % MAX_VIDEO_SECONDS["reel" if a["purpose"] == "reel" else "post"])
    reel = a["purpose"] == "reel"
    if reel:
        TW, TH = 720, 1280
        vf = "scale=%d:%d:force_original_aspect_ratio=decrease,pad=%d:%d:(ow-iw)/2:(oh-ih)/2:color=black,setsar=1" % (TW, TH, TW, TH)
    else:
        scale = min(1.0, 1280 / max(w, h))
        TW, TH = max(2, int(w * scale) // 2 * 2), max(2, int(h * scale) // 2 * 2)
        vf = "scale=%d:%d,setsar=1" % (TW, TH)
    audio = ["-c:a", "aac", "-b:a", "128k"] if has_audio else ["-an"]
    _ff(["-i", src, "-vf", vf, "-c:v", "libx264", "-preset", "veryfast", "-crf", "26", "-pix_fmt", "yuv420p", "-movflags", "+faststart"] + audio + [os.path.join(d, "video.mp4")], log)
    _rendition(c, a["id"], "mp4", "video.mp4", "video/mp4", TW, TH)
    _ff(["-ss", "%.2f" % min(1.0, dur / 2), "-i", os.path.join(d, "video.mp4"), "-frames:v", "1", "-q:v", "3", os.path.join(d, "thumb.jpg")], log)
    _rendition(c, a["id"], "thumb", "thumb.jpg", "image/jpeg", TW, TH)
    variants = []
    for name, short in (("360p", 360), ("720p", 720)):
        sw = TW if TW <= TH else None
        if TW >= TH:
            vw, vh = int(TW * short / TH) // 2 * 2, short
        else:
            vw, vh = short, int(TH * short / TW) // 2 * 2
        if vh > TH or vw > TW:
            vw, vh = TW, TH
        os.makedirs(os.path.join(d, "hls_" + name), exist_ok=True)
        _ff(["-i", os.path.join(d, "video.mp4"), "-vf", "scale=%d:%d" % (vw, vh), "-c:v", "libx264", "-preset", "veryfast", "-crf", "28",
             "-g", "48", "-sc_threshold", "0"] + (["-c:a", "aac", "-b:a", "96k"] if has_audio else ["-an"]) +
            ["-f", "hls", "-hls_time", "4", "-hls_playlist_type", "vod", "-hls_segment_filename", os.path.join(d, "hls_" + name, "seg_%03d.ts"),
             os.path.join(d, "hls_" + name, "index.m3u8")], log)
        variants.append((name, vw, vh, 800000 if short == 360 else 2200000))
    with open(os.path.join(d, "master.m3u8"), "w") as f:
        f.write("#EXTM3U\n#EXT-X-VERSION:3\n")
        for name, vw, vh, bw in variants:
            f.write("#EXT-X-STREAM-INF:BANDWIDTH=%d,RESOLUTION=%dx%d\nhls_%s/index.m3u8\n" % (bw, vw, vh, name))
    _rendition(c, a["id"], "hls", "master.m3u8", "application/vnd.apple.mpegurl", TW, TH)
    c.execute("UPDATE media_assets SET width=?, height=?, duration_ms=? WHERE id=?", (TW, TH, int(dur * 1000), a["id"]))
    os.remove(src)
    return "video %dx%d %.1fs -> mp4 %dx%d, thumb, hls 360p/720p" % (w, h, dur, TW, TH)

def process(c, media_id, on_ready=None):
    a = c.execute("SELECT * FROM media_assets WHERE id=?", (media_id,)).fetchone()
    log = []
    try:
        summary = process_image(c, a) if a["kind"] == "image" else process_video(c, a, log)
        c.execute("UPDATE media_assets SET status='ready', processed_at=?, updated_at=?, error=NULL WHERE id=?", (now(), now(), media_id))
        if on_ready:
            on_ready(c, media_id)
        return "ready", summary + ("\n" + "\n".join(log) if log else "")
    except Exception as e:
        msg = getattr(e, "message", str(e))
        c.execute("UPDATE media_assets SET status='failed', error=?, updated_at=? WHERE id=?", (msg[:300], now(), media_id))
        return "failed", msg + "\n" + "\n".join(log)

def remove_media(c, media_id):
    storage().delete_media(media_id)
    c.execute("DELETE FROM media_renditions WHERE media_id=?", (media_id,))
    c.execute("UPDATE media_assets SET status='removed', updated_at=? WHERE id=?", (now(), media_id))

def cleanup(c, max_age_hours=24):
    """Removes abandoned uploads and processed media never attached to a post (except avatars/covers)."""
    cutoff = time.strftime("%Y-%m-%dT%H:%M:%S", time.gmtime(time.time() - max_age_hours * 3600))
    stale = c.execute("""SELECT id FROM media_assets WHERE status IN ('uploading','failed') AND updated_at < ?
                         UNION SELECT id FROM media_assets m WHERE status='ready' AND purpose IN ('post','reel') AND updated_at < ?
                         AND NOT EXISTS(SELECT 1 FROM post_media pm WHERE pm.media_id=m.id)""", (cutoff, cutoff)).fetchall()
    for r in stale:
        remove_media(c, r[0])
    return {"removed": len(stale)}

# ------------------------------------------------------------------ background worker
class Worker:
    """Polls the jobs table. Runs inside the web process by default (single instance) or as its own process."""
    def __init__(self, db_fn, on_ready=None, interval=0.5):
        self.db_fn, self.on_ready, self.interval = db_fn, on_ready, interval
        self.stop = threading.Event()
        self.thread = None
        self.last_cleanup = 0
    def run_once(self):
        c = self.db_fn()
        try:
            if not c.execute("SELECT 1 FROM sqlite_master WHERE name='jobs'").fetchone():
                return False
            # recover jobs left 'running' by a crash or restart (30 min): retry up to 3 attempts, then mark failed
            stale = (datetime.datetime.now(datetime.timezone.utc) - datetime.timedelta(minutes=30)).isoformat()
            if c.execute("SELECT 1 FROM jobs WHERE status='running' AND updated_at<? LIMIT 1", (stale,)).fetchone():
                c.execute("UPDATE jobs SET status=CASE WHEN attempts<3 THEN 'queued' ELSE 'failed' END, error='interrupted', updated_at=? WHERE status='running' AND updated_at<?", (now(), stale))
                c.commit()
            j = c.execute("SELECT * FROM jobs WHERE status='queued' ORDER BY id LIMIT 1").fetchone()
            if not j:
                if time.time() - self.last_cleanup > 3600:
                    self.last_cleanup = time.time()
                    cleanup(c); c.commit()
                return False
            if not c.execute("UPDATE jobs SET status='running', attempts=attempts+1, updated_at=? WHERE id=? AND status='queued'", (now(), j["id"])).rowcount:
                return True
            c.commit()
            t0 = time.time()
            status, log = process(c, j["ref_id"], self.on_ready) if j["kind"] == "process_media" else ("failed", "unknown job")
            for attempt in range(6):   # the result must be recorded even if another writer briefly holds the lock
                try:
                    c.execute("UPDATE jobs SET status=?, log=?, error=?, updated_at=? WHERE id=?",
                              ("done" if status == "ready" else "failed", ("%.1fs " % (time.time() - t0)) + log[-4000:], None if status == "ready" else log[:300], now(), j["id"]))
                    c.commit()
                    break
                except sqlite3.OperationalError:
                    c.rollback()
                    if attempt == 5:
                        raise
                    time.sleep(0.5 * (attempt + 1))
            return True
        finally:
            c.close()
    def loop(self):
        while not self.stop.is_set():
            try:
                busy = self.run_once()
            except Exception:
                busy = False
            if not busy:
                self.stop.wait(self.interval)
    def start(self):
        self.thread = threading.Thread(target=self.loop, daemon=True, name="sh-media-worker")
        self.thread.start()
        return self

# Deployment guide

Stack: our own Python server (standard library + Pillow), SQLite, FFmpeg for video, built as a Docker image from this repo. Android app = our own WebView APK built by GitHub Actions. Nothing is bought except hosting you approve.

## Rules
* Nothing is pushed, deployed or paid for without your explicit approval.
* The database is never changed on a page load. After a deploy viewers see "being prepared" (HTTP 503) until an admin presses "Back up and run migration"; the backup is checked (integrity + row counts) before migrating, and old prediction history is checked afterwards.
* The authoritative database and all user media must be on persistent storage — never on the free plan's ephemeral disk.
* Secrets (admin key, media signing key, SMTP password) only as Render secret environment variables.

## Hosting options (prices from the providers' pricing pages, checked Nov 2026; confirm before buying)
| Option | Monthly cost | Database | Media | Sleeps? | Background worker | SMTP email | Verdict |
|---|---|---|---|---|---|---|---|
| A. Render Starter + 1 GB disk (current `render.yaml`) | about $7 + $0.25/GB disk | SQLite on the disk; nightly backup copies on the same disk | same disk | no | runs inside the web service (built in) | allowed | **Recommended now.** Simplest; one instance only (a disk blocks scaling). Grow the disk as media grows. |
| B. Render free web + free Postgres | $0 | Postgres free: 1 GB, **expires after 30 days** (14-day grace) | nowhere persistent | yes, after 15 min idle | stops when asleep | **blocked** | Not usable for production: data and media would be lost. Fine for a short staging test. |
| C. Render free web + Supabase / Neon free | $0 | Supabase 500 MB (pauses after 7 idle days) / Neon 1 GB (scale-to-zero) | Supabase 1 GB files or Cloudflare R2 10 GB free | web sleeps | stops when asleep | blocked | Needs a code change from SQLite to Postgres and object storage. Possible later; free limits are small for video. |
| D. Render Starter + Postgres Basic + Cloudflare R2 | about $7 + $6 + R2 ($0.015/GB over 10 GB, no download fees) | managed Postgres with backups | R2 (CDN-friendly) | no | separate worker possible | allowed | **Next step when there is real traffic**; needs the Postgres + R2 adapters (not built yet). |
| E. Own VPS | from ~$5 | you manage | you manage | no | yes | depends | Cheapest at scale, but you would need to run updates and backups yourself — not suitable from a phone. |

Media sizes for planning: a 60-second reel ≈ 6–12 MB after processing (MP4 + two HLS sizes + thumbnail); 1 GB holds roughly 100 reels.

## Data bridge settings (Batch 05)
* `CRICKETDATA_API_KEY`: your CricketData.org key (the same one the Telegram bot uses is fine; SH PREDICTION spends at most 60 of the 100 free hits a day and stops when fewer than 15 remain).
* Share each league sheet: open it → **Share** → General access **Anyone with the link → Viewer**. Without this the sheet sync reports "not shared publicly" for that league and the others carry on.
* Collectors start automatically with the server. Admin → **Data Bridge** shows every job; "Run now" starts one immediately.
* On the **free** Render plan collectors stop while the service sleeps (after 15 min without visitors), and data is erased on restart. Keeping data and collecting 24/7 needs Starter ($7/mo) plus a disk. Nothing paid is switched on without your approval.

## 1. Staging first
1. Render → New → Web Service → this repo, branch with the approved commit → name `sh-prediction-staging`, **Runtime: Docker**.
2. Env: `SH_PREDICTION_ADMIN_TOKEN` (generate), `SH_MEDIA_SIGNING_KEY` (generate), `SH_PREDICTION_DB=/tmp/staging.sqlite3` (staging may reset).
3. Open `/admin-panel` → enter key → "Back up and run migration".
4. Admin → Media & Storage must show `pillow ✓ ffmpeg ✓ ffprobe ✓`.
5. Run the checks in `docs/qa/QA-REPORT.md` on the staging address (register two accounts, upload a photo and a reel, play it, follow/like/comment, moderate).

## 2. Production (after staging passes and you approve)
1. The existing service `sh-prediction` runs the Python runtime. Change it to Docker: Render → service → Settings → Runtime → Docker (or apply `render.yaml` as a Blueprint). Keep the disk at `/var/data`.
2. Add env `SH_MEDIA_SIGNING_KEY` (generate) and `SH_MEDIA_DIR=/var/data/media`. Optional email: `SH_SMTP_HOST`, `SH_SMTP_PORT`, `SH_SMTP_USER`, `SH_SMTP_PASSWORD`, `SH_SMTP_FROM`.
3. Push the approved commit → Manual Deploy → `/admin-panel` → "Back up and run migration" → check the reported backup and checks.
4. Check `/health`, `/`, Admin → Dashboard and Media & Storage.
5. Rollback: redeploy the previous commit and restore the backup file reported in step 3.

## Addresses
| Path | Who |
|---|---|
| `/` | viewers (also opened by the Android app) |
| `/admin-panel` | admins (key required) |
| `/classic` | old admin console (key required) |
| `/download/sh-prediction.apk` | our APK |

## Known limits
* The Docker image could not be built in this workspace (Docker Hub is not reachable from here); the server and all tests run on Python 3.13 with FFmpeg 6.1 and Pillow 12. The first Render Docker build is the real check.
* SQLite + local disk = one instance. Moving to option D needs new storage adapters.

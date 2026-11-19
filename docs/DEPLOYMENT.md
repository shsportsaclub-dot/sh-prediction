# Deployment guide

Stack: Python 3 standard library (no packages to buy or install), SQLite, Android WebView shell built by our own free GitHub Actions workflow.

## Rules
* Nothing is pushed or deployed without your explicit approval.
* The database is never changed on a page load. After a deploy, viewers see "being prepared" (HTTP 503) until an admin runs the migration.
* The migration first copies the database to `backup-<time>.sqlite3` next to it, checks the copy (integrity + row counts), and only then migrates. After migrating it checks that v0 fixtures, predictions and outcomes are all still there.

## 1. Staging first
Staging = a second Render web service from the same repo and branch, with its own empty database, used only for checking.
1. Render → New → Web Service → this repo → name `sh-prediction-staging`.
2. Build command `echo ready`, start command `python app/main.py`.
3. Environment: `SH_PREDICTION_ADMIN_TOKEN` = a new secret; `SH_PREDICTION_DB=/tmp/staging.sqlite3` (free plan: data resets on restart, fine for staging).
4. Open `https://<staging>.onrender.com/admin-panel`, enter the key → "Back up and run migration".
5. Admin → Settings is ready; optional: `POST /api/v1/admin/demo-seed` for labelled demo data.
6. Regression check on staging: open every viewer screen and admin section, and confirm `/api/v1/admin/master-list` answers 403 without the key. (The automated suite, `python -m unittest discover -s tests -v`, runs locally against a fresh server.)
7. Proof URL = the staging address.

## 2. Production (only after staging passes and you approve)
1. Push the approved commit to `main`; Render → Manual Deploy.
2. Open `/admin-panel` → the panel shows "Database migration needed" → press "Back up and run migration". It reports the backup path and every check.
3. Check `/health`, the viewer site `/`, and Admin → Dashboard.
4. Rollback: redeploy the previous commit and restore the backup file reported in step 2.

## Addresses
| Path | Who |
|---|---|
| `/` | viewers (public site, also what the Android app opens) |
| `/admin-panel` | admins (key required) |
| `/classic` | old admin console (key required) |
| `/download/sh-prediction.apk` | APK from our own build |

## Cost
`render.yaml` uses `plan: starter` with a 1 GB disk — those are paid Render features. On the free plan the SQLite file is lost on every restart. Free options need a decision: keep paying for the disk, or move the database to a free hosted database (code change).

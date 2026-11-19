# Production deployment guide

Stack: Python 3.11+ standard library only (no pip install), SQLite on a Render persistent disk, Android WebView shell.

## Render (existing service `sh-prediction-api`)
1. Merge/push the approved commit to `main`.
2. Render dashboard → service → **Manual Deploy → Deploy latest commit**.
3. Environment (already in `render.yaml`): `SH_PREDICTION_ADMIN_TOKEN` (secret), `SH_PREDICTION_DB=/var/data/prediction.sqlite3` (on the 1 GB disk).
4. First request after deploy runs migration `001_normalized_core` automatically:
   * the v0 table `predictions` is renamed to `legacy_predictions` (rows and immutability triggers kept);
   * v1 tables are created; languages, the 2026 competition listing and model `sh-baseline 1.0.0` are seeded;
   * v0 fixtures / approved predictions / outcomes are mirrored into v1 on every request (idempotent).
5. Check `GET /health` → `{"status":"ok"}` and `GET /api/v1/admin/monitor` (admin token) → migration listed.
6. Open `/hub` on the phone (login first on `/`).

**Backup before deploying:** Render shell → `cp /var/data/prediction.sqlite3 /var/data/prediction.backup.sqlite3`.
**Rollback:** redeploy the previous commit and copy the backup file back. v0 code would recreate an empty `predictions` table, so restore the backup rather than running v0 on the migrated file.

## Android
The APK opens `https://sh-prediction.onrender.com/`; the Hub is reached from the button at the top of the classic screen.
Hash routing (`/hub#/...`) means the phone Back button steps back through screens.
The GitHub Action `android-apk.yml` rebuilds the APK only when `android/**` changes; no Android change in this batch.

## Single instance
SQLite on a disk requires exactly one instance (no autoscaling). The in-memory rate limiter assumes the same.

## Data providers
Add provider IDs via `POST /api/v1/admin/matches` with `provider` + `provider_id`; repeats are ignored (`duplicate_provider_id`).
A scheduled connector for a licensed live feed is the next batch; keep any provider key in Render env vars, never in the repo.

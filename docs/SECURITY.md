# SH PREDICTION — security review (Batch 04, 2026-11-19)

## How access is enforced
| Layer | Who | How it is checked (backend, every request) |
|---|---|---|
| Viewer | anyone | Public read endpoints only. Unpublished predictions, model factors/weights, the results Master List, audit logs, settings, emails and IP data are never returned. |
| Account | logged-in user | `Authorization: Bearer` session (random 32-byte token, stored hashed, 30-day expiry, revoked on logout / password reset / suspension / deletion). |
| Tipster / expert | account with role | Prediction posts need tipster status; verified-expert badge set only by an admin. |
| Admin | holder of `SH_PREDICTION_ADMIN_TOKEN` | Every `/api/v1/admin/*` path and the legacy register endpoints. Compared in constant time. |

Proof: `tests/test_social.py::AdminSweep` calls **22 GET + 33 POST admin paths** with (a) no credentials, (b) a logged-in normal account, (c) a wrong admin key, plus the legacy admin paths — every one is refused (401/403) and nothing is changed. The E2E run repeats this with a real browser account (step 19).

## Fixed in this batch
* **On-screen phone login code removed.** `/auth/generate` now answers 410 in production; phone numbers are never treated as authenticated. The old Settings form is replaced by username/email + password accounts with email verification.
* Codes are never returned by the API or shown in the admin outbox (bodies hidden). Only the test-only flag `SH_DEV_EXPOSE_CODES=1` exposes them; it is not set in `render.yaml`.
* Login lockout after 5 failures (15 min) — counters are committed before the error is returned (was rolled back before).
* Uploads: signed, expiring URLs; size and duration limits; type checked by file signature, not the name; EXIF/location stripped from photos; media served with `nosniff` and access checks.
* Viewer feeds hide private profiles, blocked users, suspended accounts and removed posts.
* Rate limit 300 requests/min/IP plus posting limit per hour; duplicate-text guard.

## Open risks (need your decision or a paid/free service)
| # | Risk | Severity | Recommendation |
|---|---|---|---|
| 1 | **GitHub repository is public** (`private: false`). All code, including the prediction engine, is readable. Secrets are not in it (scan clean). | High for "our logic only visible to us" | Make it private: GitHub → Settings → General → Danger zone → Change visibility. Before that: Render deploys through its GitHub App (keeps working for private repos once the app has access); the APK workflow and the `apk-latest` release download used by `/download/sh-prediction.apk` will need a token or a public mirror of only the APK. |
| 2 | One shared admin key, no per-admin accounts / 2FA | Medium | Keep the key long and secret (Render generates it); rotate if shared. Per-admin accounts are a later step. |
| 3 | SMTP not configured; Render free plan blocks SMTP ports | Medium | Until configured, verification emails wait in the outbox and an admin can verify manually. Use a paid plan or an HTTPS email API with a free tier (needs your approval). |
| 4 | No virus scanner installed (ClamAV hook returns `not_scanned`) | Medium | Install ClamAV in the Docker image when the server has ≥1 GB RAM (free software, but memory-heavy). |
| 5 | Rate limits are in memory (reset on restart, per instance) | Low | Fine for one instance. |
| 6 | SQLite single file | Medium | Must be on a persistent disk with backups (see DEPLOYMENT.md). |
| 7 | Media on the server disk, not object storage | Medium | Works with the persistent disk; move to S3-compatible storage (e.g. Cloudflare R2) when it grows. |

## Secrets
Never in the repo: admin key, media signing key, SMTP password, GitHub tokens. Set them as Render secret environment variables. A scan of the working tree for keys/tokens/phone numbers found only synthetic test values.

## Data bridge (Batch 05)
* `CRICKETDATA_API_KEY` is read from the server environment only. It is never stored in the database, logged (errors mask `apikey=***`), or returned by any API; tests check this.
* Collector controls (`/admin/bridge/...`) and the registry are admin-only (checked: no credentials and normal accounts get 401/403). Every change is audited.
* Only sources with a recorded permission are collected: Cricsheet (ODC-By), CricketData (owner's API key), the owner's own sheets and SH scoring. Cricbuzz, ESPNcricinfo and CREX are marked `not_permitted` and are never fetched. No APK is used as a data source.
* Google Sheets shared as "Anyone with the link" can be opened by anyone who has the link. Don't put private data in them.
* Cricsheet downloads accept only `*_json.zip` names found on cricsheet.org's own downloads page, from cricsheet.org only (fixed base URL), with a 400 MB size limit.

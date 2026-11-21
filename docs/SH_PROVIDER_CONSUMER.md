# SH provider event consumer — design and continuation

Owner direction: continue the next unfinished SH DATA LINE / SH Prediction integration step without routine questions. Audited DATA LINE `187e8538` and Prediction `d8802e24`; both are deployed. Reproduced Prediction baseline: 125 tests passing. The current connector uses the legacy matches/balls contract; it cannot consume the new event_read provider endpoint.

Design: add an opt-in server-side consumer module and durable event inbox. SH_DATA_PROVIDER_MODE=events selects it; legacy mode remains the default. Require a scoped consumer credential and HTTPS origin. Fetch only /v1/provider/events, reject redirects and bound response size. Store immutable normalized revisions, delivery receipts and a durable cursor in one transaction. Checkpoint identity includes origin and a one-way credential fingerprint so a rotated/re-scoped key starts safe replay; inbox identities deduplicate the same origin/event/revision across key rotation.

Filtered empty pages must advance cursors while has_more is true. Bound work to two pages per pass. Preserve source timestamps, data kind, license evidence, correction revisions and downstream inbox IDs. Do not infer local matches from names or silently mutate cricket scorecards without sport-specific validation/mapping. Live and historical kinds are allowed by default; synthetic requires explicitly selecting synthetic in SH_DATA_EVENT_KINDS for an isolated QA environment.

Honor 429 Retry-After and persist cooldown without sleeping inside network/database work. Authentication failures never fall back to a master credential or raw endpoint. Do not hold a database write lock across an HTTP request. Validate the entire page before commit; conflicts/malformed rows roll back the page and its checkpoint. Errors contain codes, not URLs, keys or provider bodies.

Create only new module-owned versioned tables when the consumer is enabled, never from a page view. Do not modify applied core migrations or add a global pending migration that blocks existing production pages. Public live-status exposes only safe aggregate state; authenticated admin GET /api/v1/admin/bridge/sh-events exposes normalized inbox evidence.

Execution: failing regression tests first; implement module, scheduler branch and read-only audit endpoint; run full suite and add missing server CI; review and commit tested changes. Extend the existing DATA LINE historical verifier to trace real permitted records into this Prediction inbox locally. Verify both exact deployed commits, health/authentication and CI. Production credentials/source grants, sport-specific application and genuine live-source-to-production acceptance remain unverified until separately observed.

## Runtime contract

| Server variable | Meaning |
| --- | --- |
| SH_DATA_PROVIDER_MODE | `events` enables this worker; absent/legacy retains existing match/ball ingestion |
| SH_DATA_API_URL | HTTPS SH DATA LINE base URL, no embedded credentials, query or fragment |
| SH_DATA_API_KEY | Expiring scoped `event_read` credential kept only in the backend environment |
| SH_DATA_EVENT_KINDS | Comma-separated allowlist; default `live,historical`; synthetic is explicit QA opt-in |
| SH_DATA_PROVIDER | Existing off/false/none switch disables acquisition |

Source distribution grants and the credential's consumer/sport/competition/source/data-kind entitlements must already cover the requested data. A mode selection cannot grant access. Invalid configurations make no requests and never fall back to a master key or the raw API. Existing configured legacy clients remain on their previous route until explicitly switched.

The server live loop calls the consumer once per iteration, at most two pages/pass. Cooldown is persisted across restart; valid Retry-After seconds/date is honored within a defensive one-day bound. Responses are limited to 4 MiB and 200 records/page. Malformed or oversized pages keep the checkpoint unchanged and record a nonsecret error code. Redirects are rejected before any credential can be forwarded. Retained event facts do not yet imply a mapped fixture, applied sport rules or public scorecard update.

The admin evidence endpoint returns immutable original events alongside the latest delivery receipt and receipt count. Changed attribution/distribution evidence on replay is appended without rewriting original facts. Structured participant lists are preserved as supplied by DATA LINE; no name-based cross-source merge occurs. Review findings on latest-receipt display, structured participants and excessive retry headers were reproduced with failing tests and fixed.

The module-owned inbox uses additive tables created by an enabled background pass, not a page view. It does not alter the app's existing applied migrations or mark all public APIs migration-pending. Source identity plus revision deduplicates within an origin; local inbox IDs provide downstream acceptance identities. A new key starts an independent cursor while deduplicating facts across credential rotation.

## Validation and remaining boundary

Real archive-to-consumer verification uses DATA LINE's `verify_provider_delivery.py --prediction-root /path/to/sh-prediction`. It downloaded the official Cricsheet archive and traced six historical deliveries from India–New Zealand `cricsheet:1539436` through real local HTTP into this inbox, preserving all six event IDs and local inbox IDs 1–6. Restart resumed at source cursor 6 without duplicate insertion. The source event timestamp is explicitly archive publication time; no ground timestamp was invented. The archive-wide legacy sample retained 236 deliveries and 22 player records.

This is local historical acceptance. No credentials, source grants, source events or data were written to production. Genuine live-source-to-production SH Prediction output and sport-specific application remain unverified. The enabled production configuration and persisted volume/recovery must be confirmed before activation can be called complete. New server CI covers regression tests and retains logs; a successful deploy remains separate from acquisition acceptance.

Final local verification: 140 server tests passed after review fixes, including legacy migration/prediction/security coverage, admin access, durable replay, receipt evidence, structured participants, redirects and retry boundaries. Compilation and whitespace checks passed. Source archive digest and exact consumer module digest are recorded in DATA LINE's `docs/verification/prediction_consumer_historical_2026_11_21.json`. The DATA LINE regression suite still reports 121 passing tests.

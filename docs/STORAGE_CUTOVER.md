# Prediction storage cutover — 21 November 2026

## Observed production state

The service-specific Render API reports runtime `plan: free` and build `buildPlan: starter` for Prediction `srv-dbupd249v7es73995adg`. This does not establish whether the owner has paid their Render account invoice. DATA LINE `srv-dc043t67bikc739b5e2g` reports paid runtime plan `0.5c-512mb`. Prediction starts `python app/main.py`, and reports the database under `/opt/render/project/src/data/prediction.sqlite3`, outside a dedicated mount. The existing `render.yaml` describes a different named Docker service; it is **not proof** that the existing service has a disk. Do not create a second service or apply that Blueprint as a substitute for migrating the existing service.

The Render connector supports environment-variable updates but has no disk-attachment or remote-shell operation. The service's storage dashboard requires sign-in in the available browser. No plan, disk, production environment variable or credential was changed in this work.

## Snapshot tool and verified recovery

`tools/storage_copy.py` creates an explicit SQLite-native snapshot, including committed WAL records. It pins row counts and backup to one read transaction, checks integrity, reopens the copy, calculates SHA-256, restricts file permissions and publishes atomically without replacing an existing destination. Missing/corrupt sources, existing destinations and SQLite sidecars are rejected. A destination expected to persist must lie under the supplied actual filesystem mount. A directory named `/var/data` alone is insufficient.

Local/offline recovery rehearsal:

```sh
python tools/storage_copy.py --source /absolute/path/prediction.sqlite3 --destination /absolute/path/rehearsal.sqlite3 --snapshot-only
```

Runtime snapshot to a prepared mounted disk, after arranging a controlled writer pause:

```sh
python tools/storage_copy.py --source /opt/render/project/src/data/prediction.sqlite3 --destination /var/data/prediction.sqlite3 --mount-root /var/data
```

This command must run on the runtime host where both paths exist. The tool does not stop writers, migrate schemas, copy media, modify credentials or switch application paths. It always reports `production_cutover_verified: false`. A consistent snapshot can immediately become outdated if writers continue; the writer pause and final switch need independent verification.

## Existing-service cutover requirements

1. First preserve the current database using SQLite backup and verify an independently reopened copy. Preserve user media separately. Keep an off-service recovery copy; a file on the ephemeral filesystem can disappear on the next deployment.
2. Confirm a supported paid service plan and disk attachment for this existing service. Disk attachment or a plan/environment update can restart the service and lose ephemeral files. Do not assume the old runtime database will still exist after attaching a disk. If the old runtime cannot coexist with the new mount, transfer the verified off-service backup to the new runtime first.
3. During the final snapshot and switch, stop collector and user writes using a controlled maintenance procedure; verify that old and new instances cannot both accept writes. The snapshot utility alone does not implement maintenance mode.
4. Restore the preserved verified database to a **new, absent** path on the actual mount, using the tool. Verify identity, migration state, provider inbox records, receipt history and checkpoint values. Preserve the old backup; never substitute a blank database.
5. Only then point `SH_PREDICTION_DB` at the restored file and `SH_MEDIA_DIR` at separately restored persistent media. Keep the established start command and repository. Verify `/health` and `/api/v1/live-status` show the intended build and mounted storage.
6. Re-enable writers and confirm a controlled restart retains the same canonical records and cursor. Check SQLite integrity and an independently restored backup. Only this runtime evidence establishes persistence.
7. Configure the explicitly scoped DATA LINE event-read credential/source grants and enable events mode following `SH_PROVIDER_CONSUMER.md`. Verify the same genuine source event in DATA LINE storage, authenticated provider API and Prediction's admin inbox. Do not infer successful acquisition from fixtures supplied by Prediction's separate legacy collectors.

The local tests cover committed WAL recovery, an independent process reopening the copy, concurrent source commits, overwrite/sidecar protection, missing and corrupt sources, mount checks and staging cleanup. These results establish tool behavior, not a completed production cutover or live sports feed.

Reference checked: [Render persistent disks](https://render.com/docs/disks), 21 November 2026. A disk attachment triggers a deployment; preserve ephemeral data before changing storage.

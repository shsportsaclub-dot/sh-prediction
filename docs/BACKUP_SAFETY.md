# Verified backup history — 21 November 2026

The existing migration backup routine reused second-resolution filenames. Two calls in one second could replace the first recovery point. Backups also inherited ordinary file permissions, counted an unpinned live source after copying, and left partial recovery files after an exception.

Four regression tests reproduce those failures before the fix. Backups now use hidden, exclusively created owner-only staging files; source counts and copied bytes share one read snapshot. SQLite integrity and row counts are checked before a standalone DELETE-journal snapshot is published using a non-overwriting hard link. File and parent directory are fsynced before migration may start. Staging files are removed on failure. Existing API response fields and backup discovery remain compatible.

Validation: full local suite 152 passed; targeted backup regressions 4 passed, including same-second recovery history and concurrent WAL writes. Compilation and whitespace checks passed. Independent review requested directory fsync; the final change includes it.

This code publication uses `[skip render]`: the current production database is still outside a mounted disk, and a verified external backup has not been obtained. The previously approved Wormhole receiver fails DNS resolution in the workspace; an authenticated terminal clipboard transfer probe was also unsupported. No backup payload was exported by that probe. The source snapshot remains on the runtime host. A private transfer keypair created for the unused encryption experiment was never granted application access and was not sent to production.

The owner has already approved private workspace/Library backup and the 1 GB `/var/data` disk at an additional $0.25/month. Do not request the same authorization again. Preserve current production until an authorized reachable backup route is verified; do not treat this fix or local tests as a completed production cutover.

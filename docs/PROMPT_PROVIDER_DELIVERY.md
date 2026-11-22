# Prompt SH provider event delivery — 22 November 2026

A separate `sh-provider-events` reader starts only when SH DATA LINE event mode has valid existing configuration and SH_COLLECTORS is not 0. It does not start a new source acquisition feed, issue keys or change their scopes. The main collector loop keeps running other source jobs independently. Its former event sync path remains a fallback when the dedicated reader is not running.

The reader calls `/v1/provider/events?after=<durable cursor>&wait_ms=15000`, with a 25-second socket timeout. After successful long-poll responses it reconnects without the previous ten-second sleep. Backlog pages after the first page request zero wait. Existing atomic inbox/receipt/cursor persistence, validation, conflict checks and Retry-After/error cooldown remain in use. An older server that ignores long polling falls back to ten-second pacing; errors do not create a retry spin.

`stream_running` reports the actual thread's liveness in provider status; it does not certify source coverage or freshness. One daemon reader per Python process is guarded against duplicate startup. Socket wait is bounded; a stop signal is observed after the current request returns. Current deployment uses one process; multiple replicas need separate coordination rather than assuming this in-process guard is shared.

No consumer UI or prediction eligibility rule changes. Concurrent owner league index/sheet fixture-link changes from main88232d4d86d21f20d2b64c45088404273ce38788 are preserved. This release consumes existing entitled normalized observations; it does not count other providers as SH-owned acquisition.

Source polling frequency and physical-event latency are separate. A local synthetic source-write/consumer-persistence loopback measured 4.198 ms and 2.879 ms for two revisions of one event, demonstrating removal of fixed response waiting. These are not Internet, production source, live cricket or microsecond guarantees. The producer stores the detailed test evidence separately.

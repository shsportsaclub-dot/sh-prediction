# Prompt SH event reader — 22 November 2026

Runtime af88196e7f56a96945f2d0fcb649fe1003f50581, Render deployment dep-dc13h3p42hec73fhm4dg, LIVE00:35:13UTC (06:05:13IST). Source runtime2702340282f7f5d51879c9b9be37cd620914ebe9 was deployed first, LIVE00:31:51UTC.

Full local regression178passed; targeted consumer17passed; compileall passed. GitHub Actions44967272067 succeeded on attempt1. An independent read-only review found no important issues. Concurrent owner-sheet/index and fixture-join changes from88232d4d86d21f20d2b64c45088404273ce38788 were reacquired and retained.

Public status evidence in prompt_reader_status_2026_11_22.json: HTTP200, stream_running=true, cursor236, records236, last_error=null. Health200 buildaf88196e7f56. Source logs show authenticated after236&wait_ms15000 reads returning200 at00:35:28.022 and00:35:43.358UTC, confirming the isolated reader is issuing long polls and reconnecting without an extra ten-second pause. These236records are the already-verified historical slice; no new genuine live event is claimed. production_verified remainsfalse.

One status probe during deployment returned502; after LIVE the same endpoint succeeded. Separate Traceback log queries after00:35:14UTC returned no matches for both services. The first combined log query was rejected because the services are in different regions, then correctly queried individually. No CI retries occurred in this release.

A real local HTTP source-write → APIwait → consumer-persistence test exercised one synthetic cricket event and a same-identity correction. First sample4.198/2.879ms, repeat5.819/4.255ms. Source repository retains the JSON evidence and reusable ops/verify_prompt_delivery.py. These timings are loopback observations, not Internet or physical sport/source latency. No production credentials, keys or synthetic source records were created.

No new live source, UI, prediction-lock rule, sport engine or worldwide coverage was added. Source collection intervals still respect each source's permissions/rate/cache rules. The change removes avoidable delivery waiting after observations have reached SH storage.

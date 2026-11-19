# Source registry and global coverage (checked 19 Nov 2026)

Machine-readable copy: table `source_registry` (Admin → Global Registry → Sources; `GET /api/v1/admin/registry/sources`).

## Sources
| Source | URL | Historical | Live | Ball-by-ball | Licence / permission | Adapter |
|---|---|---|---|---|---|---|
| Cricsheet | https://cricsheet.org | yes | no (after matches) | yes | ODC-By 1.0: reuse allowed with attribution | implemented |
| CricketData.org API | https://cricketdata.org | no | yes (score) | not on free plan | Commercial API, free plan 100 hits/day with the owner's key; redistribution per its terms (owner to confirm) | implemented |
| Owner Google Sheets | docs.google.com | yes | no | no | Owner's own data | implemented |
| SH own scoring | — | yes | yes | yes | First-party | implemented |
| ICC official site | https://www.icc-cricket.com | yes | yes | ? | Not reviewed: discovery and cross-checks only | none |
| 12 Full-Member boards (BCCI, CA, ECB, PCB, CSA, NZC, SLC, BCB, CWI, ZC, Cricket Ireland, ACB) | see Countries | ? | ? | ? | Not reviewed | none |
| Cricbuzz, ESPNcricinfo, CREX | — | yes | yes | yes | Proprietary: **not permitted**; functional reference only | none |

## Countries
ICC membership is **111 (12 Full, 99 Associate)** after Mauritius was admitted in July 2026.

| Group | In registry | Board recorded | Research status |
|---|---|---|---|
| Full Members | 12 / 12 | 12 (name + official site) | Partially Verified: domestic competitions pending |
| Associate Members | 16 / 99 confirmed so far | 0 | Not Researched |
| Other countries/regions from the owner's League Index | added on sync | — | Not Researched |

The full associate list could not be read from an accessible source in this session; it is **not** filled in from memory.

## Competitions
Sources: the owner's League Index tabs (World Competition Catalogue, Country League Directory, India State Leagues, 2026 Verified Archive, Research Push 01–03) are loaded as **unverified**, plus every competition created by an import. A competition becomes *verified* only when an official source confirms its name, organiser and seasons.

## Coverage matrix (current, not claimed beyond this)
| Competition group | Historical | Live score | Live ball-by-ball | Source verified | Adapter tested |
|---|---|---|---|---|---|
| Leagues on Cricsheet (IPL, WPL, BBL, WBBL, NPL, ILT20, T20Is and the rest of its catalogue) | yes, after real import on the server | via CricketData if covered | no | yes (Cricsheet) | with Cricsheet-format files; real download pending |
| Owner's 6 leagues | from the sheets | no | no | owner data | with stand-in files; sheets not yet shared |
| Matches covered by CricketData | result only | score only | no | provider | with provider-format JSON; real key pending on server |
| SH-scored matches | yes | yes | yes | first-party | yes (real server, E2E) |
| Everything else (state, district, club, school…) | unavailable | unavailable | unavailable | not researched | — |

Worldwide district-level and club-level research (script §2 of the league discovery brief) has **not** started beyond the owner's index. It needs country-by-country research against official board sites. That is ongoing work, and the registry tracks the status of each country.

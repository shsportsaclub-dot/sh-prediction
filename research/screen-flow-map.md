# Screen flow map (current app, from app/index.html)
Welcome (iframe /sh-prediction-welcome.html) -> postMessage "sh-prediction-enter" -> Login (phone -> Generate OTP -> Verify) -> Main tabs.
Tabs now: Matches | Results | Archive | Predictions | Accuracy.
Matches/Results card -> Match Center (select match -> Verified Decimal Odds canvas chart).
Target flow: Welcome -> Login -> Home with locked top switch "CRICKET | WORLD" -> Matches list -> Match Center (17 tabs) -> Series / Teams / Players / Rankings / Archive / Predictions / Accuracy.
Match Center 17 tabs: use the list from the master script. Each tab must show an empty state ("No verified data yet") when no authorized data exists.

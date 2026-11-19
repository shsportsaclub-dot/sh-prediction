# SH Cricket Game engine (`app/game.py`)

Our own code; no game engine, asset pack or licence was bought.

## Two modes, kept apart
| Mode | Data | Label |
|---|---|---|
| Virtual match | Simulated by our engine, stored only in `game_matches` / `game_events` | "VIRTUAL — not a real match"; never used in results, accuracy or statistics |
| Real match replay | Real recorded deliveries from `ball_events` (own scoring or Cricsheet) | "Reconstruction": outcomes are real; ball paths are drawn because trajectories were not recorded |

## Simulation
* Formats: T10 (10 overs, 2-over bowler quota), T20 (20, 4), ODI (50, 10). Seeded, so a match can be reproduced.
* Teams: 11 players with roles (batter, wicket-keeper, all-rounder, bowler), batting and bowling ratings; validated (11 players, unique names, at least 5 bowling options).
* Each ball: batting intent (format and phase: powerplay, middle, death; required rate when chasing), bowler skill and type (pace/spin), extras (wide, no-ball, bye, leg-bye), wickets by type (bowled, caught, lbw, stumped for spin, run out), fielding outcome.
* AI strategies: bowling AI picks the best legal bowler (overs left, not the previous over's bowler, not the keeper), preferring spin in the middle overs and pace at the start and death, and spreading overs; batting AI attacks in the powerplay and death overs, raises intent with the required rate and plays safer as wickets fall (from the 6th wicket).
* State machine: innings → over → ball; innings ends at 10 wickets, end of overs, or when the target is passed; a tie is recorded as a tie.

## Laws checked on every simulated match (`validate_events`)
* Law 17: six fair balls per over; wides and no-balls re-bowled; no bowler bowls consecutive overs (17.8).
* Playing conditions: bowler quota per format; free hit after a no-ball, carried over if the free-hit ball is a wide/no-ball; on a free hit only run out is possible.
* Law 18: batters change ends on odd runs and at the end of each over.
* Laws 21–22: wide/no-ball add one extra run and are not legal balls.
Tests: `tests/test_social.py::LiveCommentaryGame` simulates many seeds per format and validates each; average scores are T10 ≈ 96, T20 ≈ 169, ODI ≈ 288.

## Animation interface
Every ball yields a directive `{type, result, direction_deg, distance, height, reconstructed}`. The viewer draws it on a 2D field (canvas) with play/pause and speed; wickets red, boundaries green, aerial shots dashed. The directive format is independent of the renderer, so a 3D or physics renderer can replace the 2D canvas later without changing the engine.

## Not done yet
Interactive play (the user batting or bowling in real time), 3D graphics, player photos/kits, and multiplayer. The simulation and replay viewer above are complete and tested.

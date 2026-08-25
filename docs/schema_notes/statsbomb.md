# StatsBomb Open Data — schema notes

All facts below were measured directly from files downloaded on 2026-08-25 into
`data/raw/statsbomb/` (gitignored). Nothing here is copied from documentation.

Primary specimen: **UEFA Euro 2024 Final, Spain 2–1 England, `match_id = 3943043`**
(3 304 events, 2 882 360-frames). Secondary specimen used for penalties/extra time:
**Portugal 0–0 Slovenia, R16, `match_id = 3941020`** (4 225 events, periods 1–5).

---

## 1. URLs and branch

The repository was **renamed**: `github.com/statsbomb/open-data` now 301-redirects to
`github.com/hudl/open-data`. Default branch is **`master`** (`main` returns HTTP 404).
Both org spellings serve identical bytes on `raw.githubusercontent.com` (verified:
`competitions.json` is 34 887 bytes from both), so the legacy `statsbomb/…` URLs still work.

```
BASE = https://raw.githubusercontent.com/statsbomb/open-data/master/data

{BASE}/competitions.json
{BASE}/matches/{competition_id}/{season_id}.json
{BASE}/events/{match_id}.json
{BASE}/lineups/{match_id}.json
{BASE}/three-sixty/{match_id}.json
```

Measured sizes for `match_id=3943043`: events 2.7 MB, lineups 22 KB, three-sixty 6.7 MB.

## 2. competitions.json

Flat list, 80 entries. Keys per entry:

```
competition_id, season_id, country_name, competition_name, competition_gender,
competition_youth, competition_international, season_name,
match_updated, match_updated_360, match_available_360, match_available
```

**UEFA Euro 2024 → `competition_id = 55`, `season_id = 282`** (`match_available_360` is a
non-null ISO timestamp, so 360 exists). Other Euro rows observed: `55/43` (Euro 2020),
`53/315` (Women's Euro 2025), `53/106` (Women's Euro 2022).

## 3. matches/55/282.json

51 matches. All 51 have `match_status == "available"` **and** `match_status_360 == "available"`.
Top-level keys:

```
match_id, match_date, kick_off, competition{competition_id,country_name,competition_name},
season{season_id,season_name},
home_team{home_team_id,home_team_name,home_team_gender,home_team_group,country,managers[]},
away_team{away_team_id,away_team_name,...}, home_score, away_score,
match_status, match_status_360, last_updated, last_updated_360,
metadata{data_version,shot_fidelity_version,xy_fidelity_version},
match_week, competition_stage{id,name}, stadium{id,name,country}, referee{id,name,country}
```

Note the **asymmetric team key names** (`home_team.home_team_id` vs `away_team.away_team_id`) —
you cannot use one accessor for both. `metadata.data_version` was `"1.1.0"`,
`shot_fidelity_version` / `xy_fidelity_version` both `"2"`.

Match IDs with 360 data (all 51 qualify; a few concrete ones):

| match_id | fixture | stage |
|---|---|---|
| 3943043 | Spain vs England | Final |
| 3942819 | Netherlands vs England | Semi-finals |
| 3942226 | Spain vs Germany | Quarter-finals |
| 3941020 | Portugal vs Slovenia | Round of 16 (went to penalties) |
| 3930158 | Germany vs Scotland | Group Stage |
| 3930166 | Portugal vs Czech Republic | Group Stage |

Verified by HTTP HEAD that `{BASE}/three-sixty/3943043.json` and `.../3930158.json` both return 200.

## 4. Event object

Top-level keys and how often they were present across the 3 304 events of match 3943043:

| key | present | notes |
|---|---|---|
| `id` | 100 % | UUID string — joins to 360 `event_uuid` |
| `index` | 100 % | 1-based, dense, sequential within the match |
| `period` | 100 % | 1,2 = halves; 3,4 = ET; 5 = shootout |
| `timestamp` | 100 % | `"HH:MM:SS.mmm"`, resets each period |
| `minute`, `second` | 100 % | match wall clock, not period clock |
| `type` | 100 % | `{id, name}` |
| `possession` | 100 % | integer possession-chain counter |
| `possession_team` | 100 % | `{id, name}` |
| `play_pattern` | 100 % | `{id, name}` |
| `team` | 100 % | `{id, name}` — the acting team |
| `player` | 99.5 % | `{id, name}` — absent on Starting XI / Half Start / Half End / Tactical Shift |
| `position` | 99.5 % | `{id, name}` |
| `location` | 99.2 % | `[x, y]`, always length 2 |
| `related_events` | 96.6 % | list of 1–5 event `id`s |
| `duration` | 73.5 % | seconds, float |
| `under_pressure` | 21.5 % | **only ever `true`** |
| `counterpress` | 2.8 % | only ever `true` |
| `out` | 0.8 % | only ever `true` |
| `off_camera` | 0.8 % | only ever `true` |

A real event, verbatim:

```json
{
 "id": "5416dcdc-765b-488d-aa81-3e902846ce38",
 "index": 133,
 "period": 1,
 "timestamp": "00:03:05.550",
 "minute": 3,
 "second": 5,
 "type": { "id": 30, "name": "Pass" },
 "possession": 7,
 "possession_team": { "id": 772, "name": "Spain" },
 "play_pattern": { "id": 4, "name": "From Throw In" },
 "team": { "id": 772, "name": "Spain" },
 "player": { "id": 3477, "name": "Álvaro Borja Morata Martín" },
 "position": { "id": 23, "name": "Center Forward" },
 "location": [ 69.2, 69.5 ],
 "duration": 0.24199,
 "under_pressure": true,
 "related_events": [ "fc31cdab-...", "b0419026-..." ],
 "pass": {
  "length": 3.5128336,
  "angle": 0.08550529,
  "height": { "id": 1, "name": "Ground Pass" },
  "end_location": [ 72.7, 69.8 ],
  "body_part": { "id": 40, "name": "Right Foot" },
  "outcome": { "id": 9, "name": "Incomplete" }
 }
}
```

`type.name` values observed (match 3943043): Pass 915, Ball Receipt* 876, Carry 757,
Pressure 327, Ball Recovery 69, Duel 68, Clearance 42, Block 41, Goal Keeper 30, Dribble 25,
Shot 25, Dispossessed 21, Foul Committed 19, Foul Won 19, Miscontrol 15, Dribbled Past 11,
50/50 8, Substitution 7, Injury Stoppage 6, Interception 5, Half Start 4, Half End 4,
Tactical Shift 3, Starting XI 2, Referee Ball-Drop 2, Shield 2, Error 1.
Note the literal asterisk in **`"Ball Receipt*"`**.

### 4.1 Type-specific sub-dicts

The sub-dict key is the snake_case of the type name. Keys observed inside each:

```
pass            length, angle, height{id,name}, end_location, recipient{id,name},
                body_part{id,name}, type{id,name}, outcome{id,name}, technique{id,name},
                switch, cross, shot_assist, goal_assist, assisted_shot_id, through_ball,
                cut_back, inswinging, outswinging, no_touch, aerial_won
shot            statsbomb_xg, end_location, technique{id,name}, body_part{id,name},
                type{id,name}, outcome{id,name}, freeze_frame[], key_pass_id,
                first_time, deflected, aerial_won, one_on_one
carry           end_location                       (ONLY key)
dribble         outcome{id,name}, nutmeg, overrun
duel            type{id,name}, outcome{id,name}    (outcome present on only 35/68)
foul_committed  card{id,name}, advantage, offensive
foul_won        defensive, advantage
goalkeeper      type{id,name}, position{id,name}, end_location, outcome{id,name},
                technique{id,name}, body_part{id,name}
clearance       body_part{id,name}, head, left_foot, right_foot, aerial_won
interception    outcome{id,name}
ball_receipt    outcome{id,name}   (present on only 105/876 Ball Receipt* events — Incomplete only)
ball_recovery   recovery_failure
substitution    outcome{id,name}, replacement{id,name}
50_50           outcome{id,name}   (key literally starts with a digit)
block           deflection, offensive, save_block
injury_stoppage in_chain
```

`Pressure`, `Miscontrol`, `Dispossessed`, `Dribbled Past`, `Error`, `Shield` carry **no**
sub-dict — all their information is in the top-level fields.
`counterpress` is a bare top-level boolean, **not** a dict.

### 4.2 Where end coordinates live

| event type | path | length |
|---|---|---|
| Pass | `pass.end_location` | always 2 → `[x, y]` |
| Carry | `carry.end_location` | always 2 |
| Shot | `shot.end_location` | **2 or 3** → `[x, y]` or `[x, y, z]` |
| Goal Keeper | `goalkeeper.end_location` | always 2 (present on 16/30) |

Measured on match 3943043: of 25 shots, **15 had 3 components and 10 had 2**. The 3rd
component is height `z` in the same units, ground = 0. Every `location` (3 278 of them)
and every `pass`/`carry` end_location was length 2. A loader must branch on
`len(shot.end_location)`.

All three goals ended at exactly `x = 120.0`:

```
Nicholas Williams  loc [109.9, 28.0]  end [120.0, 42.4, 0.2]  xg 0.112
Cole Palmer        loc [ 98.4, 49.0]  end [120.0, 37.1, 0.2]  xg 0.038
Mikel Oyarzabal    loc [111.2, 36.3]  end [120.0, 38.4, 0.2]  xg 0.283
```

Off-target shots crossing the goal line were recorded at `y` 29.8 / 49.3 (wide of the posts)
and `z` 3.80 / 5.00 (over the bar). So the goal frame is `y ∈ [36, 44]`, `z ∈ [0, 2.67]`.

### 4.3 Where outcome lives

There is no shared outcome field. Per type, measured value sets:

```
pass.outcome.name          {Incomplete 121, Out 19, Unknown 2, Pass Offside 1}
                           ABSENT (143/915 present) => a COMPLETE pass
shot.outcome.name          {Blocked 9, Off T 6, Saved 6, Goal 3, Wayward 1}   always present
duel.outcome.name          {Won, Success In Play, Lost Out, Lost In Play}     35/68 present
dribble.outcome.name       {Incomplete 16, Complete 9}                        always present
interception.outcome.name  {Won, Lost In Play, Success In Play}               always present
ball_receipt.outcome.name  {Incomplete}                                       only when failed
goalkeeper.outcome.name    {Success, Saved Twice, No Touch, Touched Out,
                            In Play Danger, In Play Safe, Collected Twice}    14/30 present
50_50.outcome.name         {Lost, Won, Success To Team}                       always present
substitution.outcome.name  {Tactical 6, Injury 1}                             always present
```

**Absence of `pass.outcome` means the pass was completed.** This is the single most common
way to get pass accuracy wrong.

### 4.4 Where body_part lives

```
pass.body_part.name        {Right Foot 485, Left Foot 332, Head 30, Keeper Arm 9,
                            No Touch 3, Other 3}       862/915 present
shot.body_part.name        {Left Foot 11, Right Foot 10, Head 4}   always present
goalkeeper.body_part.name  {Both Hands 5, Right Hand 1}            6/30 present
clearance.body_part.name   {Head 20, Left Foot 12, Right Foot 10}  always present
```

Also present as redundant booleans on `clearance`: `head`, `left_foot`, `right_foot`.

### 4.5 Set pieces — and how to identify CORNERS

Two different fields, two different meanings. Measured on match 3943043:

```
pass.type.name       Recovery 62, Throw-in 32, Goal Kick 17, Free Kick 16,
                     Corner 12, Kick Off 5, Interception 4        (absent on the other 767 passes)
                     ids: Corner 61, Free Kick 62, Goal Kick 63,
                          Interception 64, Kick Off 65, Recovery 66, Throw-in 67

play_pattern.name    Regular Play 1236, From Throw In 880, From Free Kick 355,
                     From Corner 276, From Goal Kick 263, From Keeper 118,
                     From Kick Off 92, Other 51, From Counter 33
                     ids: Regular Play 1, From Corner 2, From Free Kick 3, From Throw In 4,
                          Other 5, From Counter 6, From Goal Kick 7, From Keeper 8, From Kick Off 9
```

- **`pass.type.name == "Corner"` (id 61) marks the 12 corner *deliveries*** — the kick itself.
- **`play_pattern.name == "From Corner"` (id 2) marks all 276 events in the possession chains
  that *followed* a corner** — including the defending team's clearances and the second phase.

So: use `pass.type.name == "Corner"` to count corners; use `play_pattern.name == "From Corner"`
to select a corner *sequence*. They differ by a factor of 23 in this match.

Every corner delivery was located at exactly `[120.0, 0.1]` or `[120.0, 80.0]`:

```
idx  203 Spain   loc [120.0,  0.1] -> end [116.3, 34.4]  High Pass  Inswinging
idx  556 England loc [120.0, 80.0] -> end [112.3, 45.9]  Low Pass   Inswinging
idx 2513 Spain   loc [120.0,  0.1] -> end [111.9, 43.8]  High Pass  Inswinging
idx 3239 England loc [120.0,  0.1] -> end [109.5, 44.1]  High Pass  Outswinging
```

`shot.type.name` is a *separate* enum. Match 3943043 contained only `Open Play` (id 87);
match 3941020 additionally yielded `Free Kick` (id 62) and `Penalty` (id 88):

```
shot.type.name  {Open Play 24, Penalty 7, Free Kick 5}   (match 3941020)
```

Note `Free Kick` reuses id **62** in both the `pass.type` and `shot.type` enums — the ids are
namespaced per field, so never build one global id→name map.

### 4.6 Timestamps

`timestamp` is `"HH:MM:SS.mmm"` and **restarts at `00:00:00.000` at the beginning of every
period**. `minute`/`second` are the broadcast wall clock and do not reset.

Verified on all 5 periods of match 3941020 — every period's first event has
`timestamp == "00:00:00.000"`:

```
p1 first ts=00:00:00.000 minute=0    last ts=00:47:12.077 minute=47
p2 first ts=00:00:00.000 minute=45   last ts=00:49:27.244 minute=94
p3 first ts=00:00:00.000 minute=90   last ts=00:15:44.271 minute=105
p4 first ts=00:00:00.000 minute=105  last ts=00:15:59.104 minute=120
p5 first ts=00:00:00.000 minute=120  last ts=00:04:15.049 minute=124
```

So the canonical `t` (seconds within period) is just the parsed timestamp:

```python
h, m, s = event["timestamp"].split(":")
t = int(h) * 3600 + int(m) * 60 + float(s)
```

and the relationship to the wall clock is exact — across all 3 304 events of match 3943043,
`minute*60 + second == PERIOD_OFFSET[period] + floor(t)` held with **0 exceptions**, where

```python
PERIOD_OFFSET = {1: 0, 2: 45*60, 3: 90*60, 4: 105*60, 5: 120*60}   # seconds
```

Do **not** derive `t` by subtracting the offset from `minute`/`second`: that loses the
milliseconds and is wrong for events after 45:00 within a period (first-half stoppage time
reaches `timestamp` 00:47:12 while `minute` is 47).

---

## 5. Coordinates

### 5.1 Extent, origin, units

Nominal pitch is **120 × 80**, `x ∈ [0, 120]`, `y ∈ [0, 80]`. Measured over match 3943043:
event `location` spans x 0.6 → 120.0 and y 0.1 → 80.0; `pass.end_location` spans x 2.0 → 120.0,
y 0.1 → 80.0.

**Units are yards**, established from fixed pitch furniture:

- Penalty shootout kicks in match 3941020 are all recorded at `location = [108.1, 40.1]`.
  `120 − 108 = 12` → the penalty spot is 12 units from the goal line = **12 yards**.
- Goal posts sit at `y = 36` and `y = 44` → 8 units wide = **8 yards**.
- Corner flags at `[120, 0]` / `[120, 80]`, goal centre at `y = 40`.

Note the nominal 120 × 80 yd (109.7 × 73.2 m) is larger than a 105 × 68 m pitch; StatsBomb
uses a fixed nominal pitch for every stadium, so absolute metres are approximate by design.

### 5.2 x direction: the acting team always attacks toward x = 120

All three goals ended at `x = 120.0`, and all 12 corners were taken at `x = 120.0`,
regardless of which team or which half.

### 5.3 y direction: y = 0 is the attacking team's LEFT

Established empirically from corner swing vs. kicking foot — 10/10 consistent:

```
corner at y≈0    Inswinging  Right Foot   x5      Outswinging  Left Foot  x1
corner at y≈80   Inswinging  Left Foot    x4
```

From the attacking team's **left** flank an inswinging delivery is struck with the **right**
foot, and vice versa. The `y ≈ 0` corner is therefore the attacker's left. With `x` increasing
toward the attacked goal, that puts the origin at the **top-left** when the pitch is drawn with
the attacked goal on the right — i.e. **y increases downward** (screen convention), and the
StatsBomb y axis is inverted relative to a standard maths orientation.

`pass.angle` is `atan2(end_y − y, end_x − x)` in these raw axes (checked:
`[69.2,69.5] → [72.7,69.8]`, `atan2(0.3, 3.5) = 0.0855` = the recorded `0.08550529`), so
flipping y also flips the sign of `angle`.

### 5.4 THE BIG ONE: the frame is per *event team*, not per *possession team*

Each event's coordinates are expressed in a frame where **`event.team`** attacks toward
`x = 120` — **not** `event.possession_team`. For the 17.3 % of events (571/3304) where
`team.id != possession_team.id`, the coordinates are rotated 180° relative to the team on the ball.

Evidence 1 — goalkeepers. Every `Goal Keeper` event sits at `x ≈ 1–8` even though the shot it
responds to ends at `x ≈ 120`:

```
England  Shot Faced     loc=[1.8, 44.1]
England  Goal Conceded  loc=[2.7, 43.0]
Spain    Shot Saved     loc=[1.4, 39.6]
Portugal Goal Keeper    loc=[1.0, 40.0]   (facing a penalty struck from [108.1, 40.1])
```

Evidence 2 — quantitative. Pairing each of the 289 off-possession `Pressure` events with its
temporally adjacent possession-team event:

```
median L1 error assuming a SHARED frame : 90.6
median L1 error assuming a MIRRORED frame:  6.9
```

Evidence 3 — the corner sequence in the committed fixture (event indices 2513–2518):

```
2513 Pass          Spain   loc [120.0,  0.1]   corner delivery
2516 Shot          Spain   loc [111.9, 43.8]
2517 Block         England loc [  7.7, 36.7]   == mirror of [112.3, 43.3]
2518 Goal Keeper   England loc [  1.0, 38.8]
```

Evidence 4 — the *counter-example* that proves it is per-team and not per-event: inside
`shot.freeze_frame`, the opposition keeper is at `x = 118.3` because that nested frame is
expressed in the **shooter's** frame:

```json
{"location": [118.3, 36.0], "player": {"id": 3468, "name": "Jordan Pickford"},
 "position": {"id": 1, "name": "Goalkeeper"}, "teammate": false}
```

**Consequence for sportio.** The canonical schema wants left-to-right for the team *in
possession*. So for every event with `team.id != possession_team.id`, apply

```python
x, y = 120.0 - x, 80.0 - y        # and the same to every end_location
```

before the metre rescale. Skipping this silently places roughly one event in six on the wrong
half of the pitch.

### 5.5 Transform to 105 × 68 m

Taking y increasing **upward** from a bottom-left origin (right-handed), and after the §5.4
mirror where needed:

```python
X_SCALE = 105.0 / 120.0      # 0.875
Y_SCALE =  68.0 /  80.0      # 0.85

x_m = x_sb * X_SCALE
y_m = (80.0 - y_sb) * Y_SCALE
z_m = z_sb * Y_SCALE         # shot end_location 3rd component, if present
```

If instead y is kept increasing downward (origin top-left, matching StatsBomb), drop the
`80.0 −` and use `y_m = y_sb * Y_SCALE`.

Landmark check of the linear rescale:

| landmark | StatsBomb | → metres | real |
|---|---|---|---|
| centre spot | (60, 40) | (52.50, 34.00) | (52.5, 34.0) ✓ |
| attacked goal centre | (120, 40) | (105.00, 34.00) | (105.0, 34.0) ✓ |
| goal width | 8 units | 6.80 m | 7.32 m |
| penalty spot from goal line | 12 units | 10.50 m | 11.00 m |
| penalty box depth | 18 units | 15.75 m | 16.50 m |
| penalty box width | 44 units | 37.40 m | 40.32 m |

The plain linear rescale is what mplsoccer/socceraction/kloppy do, but it shrinks the box and
goal by **5–7 %**. If box-relative features matter, a piecewise-linear landmark-preserving map
is the alternative — but it is not what the ecosystem uses, so match the ecosystem by default
and expose the choice.

---

## 6. three-sixty/{match_id}.json

Flat list, 2 882 entries for match 3943043. Exactly three keys per entry:
**`event_uuid`**, **`visible_area`**, **`freeze_frame`**.

```json
{
 "event_uuid": "fce8cc2d-8365-40ed-bae9-70578940b3ff",
 "visible_area": [0.0, 80.0, 0.0, 37.776208238276105, 21.38378569766795, 0.0,
                  64.45185619079346, 0.0, 67.78987708444917, 80.0, 0.0, 80.0],
 "freeze_frame": [
  {"teammate": true,  "actor": false, "keeper": true,  "location": [5.976231771673298, 42.2296254150667]},
  {"teammate": true,  "actor": true,  "keeper": false, "location": [9.100000381469727, 57.20000076293945]},
  {"teammate": true,  "actor": false, "keeper": false, "location": [9.663865822853083, 30.292096313932255]},
  {"teammate": false, "actor": false, "keeper": false, "location": [17.00479956690728, 57.523981847363196]}
 ]
}
```

- `event_uuid` joins to `event.id`. **All 2 882 uuids resolved** into the events file.
- `visible_area` is a **flat, alternating `[x1,y1,x2,y2,…]` list**, *not* a list of pairs.
  Observed lengths: 10 (1 283×), 12 (1 081×), 14 (516×), 8 (2×) → 4–7 polygon vertices.
- `freeze_frame` players carry only `teammate`, `actor`, `keeper`, `location` — there is
  **no player_id, no name, no jersey number**.

Measured over all 2 882 frames:

```
players per frame     min 6, max 22, mean 16.5, median 17
decile boundaries     12, 14, 15, 16, 17, 18, 19, 19, 20
actors per frame      exactly 1 in all 2 882 frames
keeper present in     913 / 2 882 frames  (31.7 %)
teammates per frame   mean 8.1
x range               −1.999 .. 123.034      (OUT of [0,120])
y range               −7.501 ..  86.005      (OUT of [0,80])
```

The frame shares its event's coordinate system: the `actor`'s location equals the parent
event's `location` **exactly** — L1 distance median 0.00 and p90 0.00 over 2 882 frames.
So §5.4's per-event-team mirror applies to freeze frames too.

Coverage is 2 882 / 3 304 = **87.2 %** of events. Frames exist mostly for on-ball events
(Ball Receipt* 802, Pass 767, Carry 700, Pressure 275, Duel 60). Events *without* a frame:
Pass 148, Ball Receipt* 74, Carry 57, Pressure 52, Goal Keeper 17.

### 6.1 Why 360 is not tracking data

2 882 frames across ~96 minutes is **≈ 0.5 Hz**, and the samples are event-triggered rather
than evenly spaced. It also lacks `player_id`, `jersey`, `vx`, `vy` and any frame counter, and
only sees players inside the broadcast camera polygon (6–22 of 22). It therefore **cannot
populate the sportio `tracking` schema**, which requires ≥10 Hz plus per-player identity. Treat
StatsBomb as an events-only source and attach 360 as per-event context (e.g. into `extra`).

### 6.2 shot.freeze_frame is a different, richer object

Embedded in shot events, and unlike the 360 frames it **does** identify players:

```
keys: location, player{id,name}, position{id,name}, teammate
```

25 shots in match 3943043 carried 6–19 players each (325 rows total). No `actor` or `keeper`
flag — the shooter is the event's own `player`, and the keeper is identified by
`position.name == "Goalkeeper"`.

## 7. lineups/{match_id}.json

List of 2 objects, keys `team_id`, `team_name`, `lineup`. Each `lineup` entry:

```json
{"player_id": 3042, "player_name": "Mikel Merino Zazón", "player_nickname": "Mikel Merino",
 "jersey_number": 6, "country": {"id": 214, "name": "Spain"}, "cards": [],
 "positions": [{"position_id": 17, "position": "Right Wing", "from": "88:40", "to": "89:54",
                "from_period": 2, "to_period": 2,
                "start_reason": "Substitution - On (Tactical)", "end_reason": "Tactical Shift"}]}
```

This is the **only** place `jersey_number` appears outside the `Starting XI` event's
`tactics.lineup[].jersey_number`. Note `positions[].from` / `to` are `"MM:SS"` **wall-clock**
strings (not the period-relative `HH:MM:SS.mmm` used by events) and `to` is `null` for a player
still on at the whistle.

---

## 8. Gotchas summary

1. Repo renamed `statsbomb/open-data` → `hudl/open-data`; branch is `master`, `main` 404s.
2. Coordinates are per **event team**, not possession team — mirror `(120−x, 80−y)` for the
   17.3 % of events where `team.id != possession_team.id`.
3. `y` increases **downward** in StatsBomb; flip it for a bottom-left-origin metre pitch.
4. `shot.end_location` is length **2 or 3**; everything else is length 2.
5. Missing `pass.outcome` means **completed**, not unknown.
6. `under_pressure`, `counterpress`, `out`, `off_camera`, `switch`, `cross`, `aerial_won`,
   `first_time`, `deflected` etc. appear **only when true** — absence is false, never `False`.
7. `"Ball Receipt*"` contains a literal asterisk.
8. The `50_50` key starts with a digit — not a valid Python identifier.
9. `visible_area` is a flat alternating list, not a list of `[x, y]` pairs.
10. 360 freeze-frame coordinates go out of bounds (x −2.0 → 123.0, y −7.5 → 86.0) — clip.
11. `matches` uses `home_team.home_team_id` but `away_team.away_team_id`.
12. `timestamp` resets per period; `minute`/`second` do not. Use `timestamp` for `t`.
13. Period 5 is the shootout: 16 events, all shots at `location [108.1, 40.1]`,
    `shot.type.name == "Penalty"`. Decide explicitly whether to emit or drop these.
14. `Free Kick` is id 62 in **both** `pass.type` and `shot.type`; ids are per-field namespaces.
15. Events files are ~3 MB and 360 files ~7 MB per match — 51 Euro 2024 matches is ~500 MB.
    Cache aggressively.

## 9. Committed fixtures

Under `tests/fixtures/statsbomb/` (all real bytes, sliced; nothing synthesised):

| file | contents | size |
|---|---|---|
| `competitions.json` | 10 real entries, Euro 2024 (`55/282`) first | 4.3 KB |
| `matches_55_282.json` | 6 real Euro 2024 matches incl. the Final | 10.0 KB |
| `events_3943043_slice.json` | events `index` 2460–2600 (141 events), period 2, `00:19:16.065`–`00:25:08.092` | 89.7 KB |
| `three-sixty_3943043_slice.json` | 50 freeze frames for event indices 2500–2560 | 81.0 KB |
| `lineups_3943043.json` | both teams, complete | 21.5 KB |

The events slice deliberately contains **2 corner deliveries** (`index` 2513, 2559),
**4 shots** (2511 Saved, 2516 Blocked, 2582 Off T, 2592 Blocked), **42 events with
`play_pattern.name == "From Corner"`**, and the mirrored England defensive events that
demonstrate gotcha #2. Every `event_uuid` in the 360 slice resolves inside the events slice.
The two large slices are stored as compact JSON purely to stay under the 100 KB fixture budget;
values are byte-identical to the source.

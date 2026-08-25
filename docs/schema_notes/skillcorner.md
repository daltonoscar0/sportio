# SkillCorner Open Data

Repo: <https://github.com/SkillCorner/opendata> — branch **`master`** (not `main`), public, no auth.

> **The repo was restructured on 2025-10-06** (commit `741bdb798b`, *"Uploading new data and
> deleting old data"*). The layout this note documents is **not** the one most tutorials and
> blog posts describe. Both layouts are covered below; the **current** one is authoritative.

Everything below was measured against real bytes downloaded on 2026-08-25.

---

## 1. Current layout (`master`)

```
data/matches.json                                     # 3.3 KB index of all 10 matches
data/matches/{match_id}/{match_id}_match.json         # ~28 KB  metadata + roster
data/matches/{match_id}/{match_id}_tracking_extrapolated.jsonl   # ~85 MB  GIT LFS
data/matches/{match_id}/{match_id}_dynamic_events.csv # ~4.5 MB 294 columns
data/matches/{match_id}/{match_id}_phases_of_play.csv # ~125 KB
data/aggregates/aus1league_*aggregates_20242025.csv   # season-level, not per match
```

Note the `{match_id}_` filename prefix — the directory name is repeated in every filename.

### URL templates

```
https://raw.githubusercontent.com/SkillCorner/opendata/master/data/matches.json
https://raw.githubusercontent.com/SkillCorner/opendata/master/data/matches/{match_id}/{match_id}_match.json
https://raw.githubusercontent.com/SkillCorner/opendata/master/data/matches/{match_id}/{match_id}_dynamic_events.csv
https://raw.githubusercontent.com/SkillCorner/opendata/master/data/matches/{match_id}/{match_id}_phases_of_play.csv
```

**Tracking is Git LFS** (`.gitattributes`: `*.jsonl filter=lfs diff=lfs merge=lfs -text`).
`raw.githubusercontent.com` returns a **133-byte pointer stub**, not data:

```
version https://git-lfs.github.com/spec/v1
oid sha256:3577e2803da95390f8b2f85d47829eb55fbbfee6211c94adc65db0dc78e46b41
size 89280839
```

Use the **media** host instead — it needs `-L` (302 to an S3 signed URL) and honours `Range`:

```
https://media.githubusercontent.com/media/SkillCorner/opendata/master/data/matches/{match_id}/{match_id}_tracking_extrapolated.jsonl
```

Verified: `HTTP/2 206`, `accept-ranges: bytes`, `content-range: bytes 0-3000000/89280839`.
Range requests work, so a loader can stream/seek instead of pulling 85 MB.

### The 10 match ids

All **A-League (AUS) 2024/2025**, `competition_id 61`, `season_id 95`, `competition_edition_id 870`.
The upstream README still says *"10 matches"*; the older *9-match* dataset is the legacy one (§4).

| match_id | date | home v away | `pitch_length` | `pitch_width` | `home_team_side` (P1, P2) |
|---|---|---|---|---|---|
| 1886347 | 2024-11-30T04:00:00Z | Auckland FC v Newcastle | 104 | 68 | right_to_left, left_to_right |
| 1899585 | 2024-12-07T04:00:00Z | Auckland FC v Wellington P FC | 104 | 68 | right_to_left, left_to_right |
| 1925299 | 2024-12-21T06:00:00Z | Brisbane FC v Perth Glory | 105 | 68 | right_to_left, left_to_right |
| 1953632 | 2024-12-31T08:00:00Z | CC Mariners v Melbourne City | 105 | 68 | left_to_right, right_to_left |
| 1996435 | 2025-02-01T06:00:00Z | Sydney FC v Adelaide United | 105 | 68 | left_to_right, right_to_left |
| 2006229 | 2025-03-07T08:35:00Z | Melbourne City v Macarthur FC | 105 | 68 | right_to_left, left_to_right |
| 2011166 | 2025-04-12T05:00:00Z | Wellington P FC v Melbourne V FC | 105 | 68 | right_to_left, left_to_right |
| 2013725 | 2025-04-27T07:00:00Z | Western United v Sydney FC | 106 | 68 | left_to_right, right_to_left |
| 2015213 | 2025-05-03T08:00:00Z | Western United v Auckland FC | 106 | 68 | left_to_right, right_to_left |
| 2017461 | 2025-05-17T09:35:00Z | Melbourne V FC v Auckland FC | 105 | 68 | left_to_right, right_to_left |

`data/matches.json` is a flat list; each entry has exactly
`id`, `date_time`, `home_team{id,short_name}`, `away_team{id,short_name}`, `status`,
`competition_id`, `season_id`, `competition_edition_id`. Its `date_time` agrees with each
`{match_id}_match.json` for all 10.

`pitch_length` varies (**104 / 105 / 106**); `pitch_width` is 68 in all 10.

---

## 2. `{match_id}_match.json`

Top-level keys (measured on `1886347`):

```
id  home_team_score  away_team_score  date_time  stadium  home_team  home_team_kit
away_team  away_team_kit  home_team_coach  away_team_coach  home_team_playing_time
away_team_playing_time  competition_edition  match_periods  competition_round
referees  players  status  home_team_side  ball  pitch_length  pitch_width
```

Exact key paths sportio needs:

| target field | key path | note |
|---|---|---|
| `match_id` | `id` (int) | also `match_id` column in the CSVs |
| `competition` | `competition_edition.competition.name` | `"A-League"`; area in `.competition.area` (`"AUS"`) |
| `season` | `competition_edition.season.name` | `"2024/2025"`; also `.start_year` / `.end_year` |
| home team | `home_team.id`, `home_team.name`, `.short_name`, `.acronym` | `4177`, `"Auckland FC"`, `"AUC"` |
| away team | `away_team.id`, `away_team.name`, … | `1805`, `"Newcastle United Jets FC"`, `"NEW"` |
| pitch | `pitch_length`, `pitch_width` (int, metres) | |
| direction | `home_team_side` — `list[str]`, one per period | `["right_to_left","left_to_right"]` |
| periods | `match_periods[]` | see below |
| kickoff | `date_time` — ISO-8601 Z | `"2024-11-30T04:00:00Z"` |

```jsonc
"match_periods": [
  {"period": 1, "name": "period_1", "start_frame": 10,    "end_frame": 27790, "duration_frames": 27780, "duration_minutes": 46.3},
  {"period": 2, "name": "period_2", "start_frame": 27800, "end_frame": 59060, "duration_frames": 31260, "duration_minutes": 52.1}
]
```

`duration_frames / (duration_minutes * 60)` = **10.0** for all 20 periods across all 10 matches
(±0.0007 from the 2-dp rounding of `duration_minutes`). Frame rate is **10 Hz**, exactly the
canonical minimum — no resampling needed.

### `players[]` (36 entries per match, incl. subs)

```jsonc
{
  "id": 38673,                    // <-- THIS is what tracking `player_id` references
  "trackable_object": 39794,      // <-- NOT used by the current tracking file (see gotchas)
  "team_player_id": 1507965,
  "team_id": 4177,                // join to home_team.id / away_team.id for home/away
  "number": 10,                   // jersey
  "first_name": "Guillermo Luis",
  "last_name": "May Bartesaghi",
  "short_name": "G. May",
  "birthday": "1998-03-11",
  "gender": "male",
  "player_role": {"id": 15, "position_group": "Center Forward", "name": "Center Forward", "acronym": "CF"},
  "start_time": "00:00:00",       // nullable (unused subs)
  "end_time": "01:25:21",         // nullable
  "yellow_card": 0, "red_card": 0, "injured": false, "goal": 0, "own_goal": 0,
  "playing_time": {
    "total": {"minutes_tip": 29.55, "minutes_otip": 18.76, "start_frame": 10, "end_frame": 52009,
              "minutes_played": 86.65, "minutes_played_regular_time": 86.65},
    "by_period": [{"name": "period_1", "start_frame": 10, "end_frame": 27790, "minutes_played": 46.3, ...}]
  }
}
```

`tip` / `otip` = time in / out of possession.

### `referees` and `ball`

- `referees` is `[]` (**empty**) in all 10 current matches. The legacy set did have referees.
- `ball` is `{"trackable_object": 55}` in all 10 — a **vestigial** field. The current tracking
  file carries the ball in its own `ball_data` object and never emits id `55`.

---

## 3. `{match_id}_tracking_extrapolated.jsonl`

**JSON Lines** (one JSON object per line), ~59 k lines, ~85 MB. The legacy file was a single
giant JSON array — this one is *not*, so stream it line by line.

A complete frame, verbatim (`1886347`, frame 10 = kickoff, player list truncated here):

```jsonc
{
  "frame": 10,
  "timestamp": "00:00:00.00",
  "period": 1,
  "ball_data": {"x": 0.32, "y": 0.38, "z": 0.13, "is_detected": true},
  "possession": {"player_id": null, "group": null},
  "image_corners_projection": {
    "x_top_left": -52.52, "y_top_left": 39.0,
    "x_bottom_left": -23.21, "y_bottom_left": -37.05,
    "x_bottom_right": 22.76, "y_bottom_right": -36.88,
    "x_top_right": 50.99, "y_top_right": 39.0
  },
  "player_data": [
    {"x": -39.63, "y": -0.08, "player_id": 51009,  "is_detected": false},
    {"x": -19.21, "y": -9.18, "player_id": 176224, "is_detected": true},
    {"x":   2.67, "y":  9.94, "player_id": 38673,  "is_detected": true}
  ]
}
```

Top-level key union over the whole sample — exactly these 7, always present:
`frame`, `timestamp`, `period`, `ball_data`, `possession`, `image_corners_projection`, `player_data`.

`player_data[]` key union — exactly these 4: **`x`, `y`, `player_id`, `is_detected`**.
There is **no** `trackable_object`, **no** `track_id`, **no** `z`, **no** `group_name`,
**no** `is_visible`, **no** team field.

| target field | key path |
|---|---|
| `frame` | `frame` (int, 0-based, contiguous over the whole file incl. pre-match/half-time) |
| `period` | `period` — `1`, `2`, or **`null`** outside live play |
| `t` | derive: `(frame - match_periods[period-1].start_frame) / 10.0` |
| `player_id` | `player_data[].player_id` → join to `players[].id` |
| `jersey` | via roster: `players[].number` |
| `team` | via roster: `players[].team_id` vs `home_team.id` / `away_team.id` |
| `x`, `y` | `player_data[].x/.y` (metres, pitch-centred) |
| `confidence` | `player_data[].is_detected` (bool) — see below |
| ball row | `ball_data.x/.y/.z` + `ball_data.is_detected` |

### Ball

The ball is **not** a row in `player_data`. It is the separate `ball_data` object, with a **`z`**
(height) the players don't have. Emit it as the `team == "ball"` row with `player_id`/`jersey` null.

### How sparse is it? (this is "extrapolated" data)

Measured over **1 987 live frames** (period-1 head + a period-2 slice of `1886347`):

- `len(player_data)` is **exactly 22 in every single live frame** — never more, never fewer.
  The file is **dense**: SkillCorner has already extrapolated the off-camera players.
- `is_detected == true` (genuinely seen by the broadcast camera): mean **13.85 / 22 = 62.98 %**,
  median 15, min **0**, max **20**.
- **0.00 %** of frames have all 22 detected; **15.45 %** of frames have fewer than 11 detected.
- `ball_data.is_detected` is true in **82.34 %** of frames — but `ball_data.x` is **never null**
  when `is_detected` is false. Positions are always filled in.

So the broadcast sparsity is real (~63 % genuine) but it is expressed **only** through the
`is_detected` flag, never through missing rows. Map `is_detected` → `confidence`
(e.g. `1.0` / `0.5`) rather than dropping rows, and do not treat this feed as ground truth
for off-camera players.

### `possession`

`{"player_id": <int|null>, "group": <"home team"|"away team"|null>}`.
Over the sample: `group` = `"away team"` 1032, `null` 568, `"home team"` 387.
`possession.player_id` is **null in 76.5 %** of live frames even when `group` is set — so
`group` is the reliable field and the on-ball player usually is not resolved here. Note the
values contain a **space** (`"home team"`, not `"home_team"`).

### Time

`timestamp` is `"HH:MM:SS.ss"` and is a **match clock, not a period clock**:

- period 1 starts at `"00:00:00.00"` on its `start_frame`
- period 2 starts at `"00:45:00.00"` on its `start_frame` — a flat **+45:00 (2700 s) offset**,
  regardless of how long first-half stoppage actually was

Verified on `1886347` (P2 `start_frame` 27800): frame 31783 → `"00:51:38.30"`, and
`(31783 − 27800)/10 = 398.3` s, `398.3 + 2700 = 3098.3 s = 51:38.3`. Exact.
Re-verified on `2017461` (P2 `start_frame` 39670): frame 46025 → `"00:55:35.50"`;
frame-based `t = 635.5` and `ts − 2700 = 635.5`. Exact.

**Prefer `t = (frame - start_frame) / 10.0`** — it is offset-free, avoids parsing, and matches
the timestamp to the centisecond.

`timestamp` and `period` are **`null`** before kickoff, during half-time and after full time; in
those frames `player_data` is `[]` and every `ball_data` value is `null`. Filter on
`period is not None`.

---

## 4. Coordinate system

**Metres. Origin at the centre spot. Right-handed, viewed from above.**

- `+x` runs along the length; `−x` to `+x` is the "left_to_right" attacking direction.
- `+y` is the **top of the broadcast image** — confirmed by `image_corners_projection`, whose
  `y_top_*` are positive (`39.0`) and `y_bottom_*` negative (`−37.05`).
- Nominal ranges: `x ∈ [−pitch_length/2, +pitch_length/2]`, `y ∈ [−pitch_width/2, +pitch_width/2]`
  → for `1886347` (104 × 68): `x ∈ [−52, 52]`, `y ∈ [−34, 34]`.

**Empirically measured** over 1 987 live frames of `1886347`:

| | min | max | nominal bound |
|---|---|---|---|
| player `x` | −52.12 | 51.72 | ±52 |
| player `y` | −34.82 | 36.96 | ±34 |
| ball `x` | −52.50 | 50.52 | ±52 |
| ball `y` | −37.14 | 36.40 | ±34 |
| ball `z` | **−0.24** | 4.90 | ≥0 |

Values **overshoot the touchline** (y to 36.96, ~3 m out) and ball `z` goes slightly **negative**.
Do not assume in-bounds; clip only if a consumer requires it.

Values are rounded to **2 decimal places** in the current files (the legacy set had full float
precision, e.g. `7.83006579535`).

### Direction is fixed per period, and flips at half time

`home_team_side[period - 1]` gives the direction the **home team attacks** in that period —
`"left_to_right"` means home attacks toward `+x`. It always flips between P1 and P2.

Confirmed on `1886347` frame 10 (`home_team_side[0] == "right_to_left"`): home (Auckland) GK
A. Paulsen at `x = +40.47`, home CBs at `x ≈ +17`; away (Newcastle) GK R. Scott at `x = −39.63`.
Home defends `+x`, therefore attacks toward `−x` = right-to-left. Consistent.

Left/right handedness also checks out: away attacks `+x`, and its **LB** sits at `y = +15.73`
while its **RB** sits at `y = −32.47` — i.e. for a team attacking `+x`, its own left is `+y`.

### Transform to 105 × 68

With origin at the **bottom-left corner**, `x ∈ [0,105]`, `y ∈ [0,68]`:

```python
x_out = (x_sc / pitch_length + 0.5) * 105.0
y_out = (y_sc / pitch_width  + 0.5) * 68.0
```

Because `pitch_width == 68` for all 10 matches the y factor is exactly 1.0 (a pure +34 shift);
the x factor is `105/104 = 1.009615`, `1.0`, or `105/106 = 0.990566` depending on the match.

To force **attacking left-to-right for the team in possession**, rotate 180° *before* the shift —
flip **both** axes, never x alone (flipping x alone mirrors the pitch and swaps the wings):

```python
direction = home_side if group == "home team" else opposite(home_side)
if direction == "right_to_left":
    x_sc, y_sc = -x_sc, -y_sc
```

Worked example (`1886347` frame 10, away in possession, no flip):
GK R. Scott `(−39.63, −0.08) → (12.49, 33.92)`; GK A. Paulsen `(40.47, 0.24) → (93.36, 34.24)`.
Both GKs land ~12 m from their own goal line, dead centre in y. Correct.

For **tracking** rows, `possession.group` is null 28.6 % of the time, so a per-frame
possession-relative flip is not always defined. Normalising tracking by `home_team_side` (home
always attacks left-to-right) is the stable choice; reserve the possession-relative flip for events,
which carry their own `attacking_side` per row.

---

## 5. `{match_id}_dynamic_events.csv` (294 columns)

This is **SkillCorner "Game Intelligence"**, derived from tracking — **not** a conventional
event feed. `event_type` has only **four** values:

| `event_type` | count in first 2 197 rows |
|---|---|
| `passing_option` | 1 125 |
| `player_possession` | 434 |
| `on_ball_engagement` | 388 |
| `off_ball_run` | 250 |

There is no top-level `pass` or `shot` type — an actual pass is a `player_possession` row whose
**`end_type == "pass"`**, a shot is one whose `end_type == "shot"`.

Columns sportio cares about:

| target | column | measured values |
|---|---|---|
| `match_id` | `match_id` | `1886347` |
| `period` | `period` | `1`, `2` |
| `t` | `frame_start` → `(frame_start - start_frame)/10.0` | prefer over `time_start` |
| — | `time_start`, `time_end` | **`"MM:SS.s"`** e.g. `"00:01.8"`, `"35:39.5"` — period-relative, **a different format from tracking's `"HH:MM:SS.ss"` match clock** |
| — | `minute_start`, `second_start`, `duration` | ints / float seconds |
| `team_id`, `team` | `team_id`, `team_shortname` | `1805`, `"Newcastle"` |
| `player_id`, `player` | `player_id`, `player_name` | `966120`, `"B. Gibson"` |
| — | `player_position`, `player_position_id` | `"CF"`, `19` |
| `type` | `event_type` (+ `event_type_id`) | 4 values above |
| `subtype` | `event_subtype` (+ `event_subtype_id`) | `pressing`, `pressure`, `recovery_press`, `counter_press`, `run_ahead_of_the_ball`, `coming_short`, `dropping_off`, `support`, `pulling_wide`, `cross_receiver`, `behind`, `pulling_half_space`, `underlap`, `other`, `""` |
| `x`, `y` | `x_start`, `y_start` | same centred metric frame as tracking |
| `end_x`, `end_y` | `x_end`, `y_end` | |
| `outcome` | `pass_outcome` | `successful` / `unsuccessful` / `""` |
| `body_part` | `is_header` (`True`/`False`/`""`), `hand_pass` | no full body-part enum |
| direction | **`attacking_side`** (+`attacking_side_id`) | `"left_to_right"` / `"right_to_left"` **per row** |
| `pressure` | no direct flag | derive from `event_subtype ∈ {pressure, pressing, counter_press, recovery_press}` on `on_ball_engagement` rows, or from `separation_start` / `close_at_player_possession_start` / `pressing_chain` |

`attacking_side` is per-row, so events need no lookup into `home_team_side` — but the two must
agree, and they do (P1 of `1886347`: `right_to_left` 1 210 rows, `left_to_right` 987).

Other useful columns: `end_type` (`pass`, `indirect_regain`, `possession_loss`, `shot`,
`clearance`, `foul_suffered`, `foul_committed`, `direct_disruption`, …), `start_type`
(`pass_reception`, `pass_interception`, `recovery`, `throw_in_reception`, `goal_kick_reception`,
`free_kick_reception`, `corner_reception`, …), `xthreat`, `xpass_completion`, `xshot_*`,
`player_targeted_*` (the intended receiver, with x/y at pass and at reception),
`phase_index`, `team_in_possession_phase_type`, and `fully_extrapolated` (row derived entirely
from extrapolated positions — a quality flag worth surfacing).

`{match_id}_phases_of_play.csv` (43 columns) is one row per possession phase:
`frame_start`, `frame_end`, `team_in_possession_id`, `attacking_side`,
`team_in_possession_phase_type` (`create`, `direct`, …), `team_out_of_possession_phase_type`
(`medium_block`, `defending_direct`, …), plus team shape width/length at start and end.

---

## 6. Legacy layout (the 9-match dataset) — still pinnable

The pre-2025 dataset most documentation describes is gone from `master` but intact at the last
commit before the restructure, **`1b99d401dd`** (2020-10-09). Those blobs are **not** LFS, so
plain `raw.githubusercontent.com` returns real data:

```
https://raw.githubusercontent.com/SkillCorner/opendata/1b99d401dd/data/matches/{match_id}/match_data.json
https://raw.githubusercontent.com/SkillCorner/opendata/1b99d401dd/data/matches/{match_id}/structured_data.json
```

The **9** legacy match ids: `2068, 2269, 2417, 2440, 2841, 3442, 3518, 3749, 4039`
(`match_data.json` 14–18 KB; `structured_data.json` 53–77 MB).

`match_data.json` (`2068`) — same family, but **no `match_periods` and no `home_team_side`**,
so attacking direction must be inferred from goalkeeper x-positions. It *does* have
`referees[]` (with its own `trackable_object`, e.g. `11180`), `home_team_coach`,
`pitch_length` 105 / `pitch_width` 68, and `ball.trackable_object` 55.
`players[]` (43 entries) carries both `id` and `trackable_object`.

`structured_data.json` is a **single JSON array**, not JSONL. Frame keys are exactly
`possession`, `frame`, `data`, `period`, `time` — note **`time`** (`"0:00.00"`, `M:SS.ss`,
period-relative), not `timestamp`.

`data[]` key union: **`x`, `y`, `z`, `trackable_object`, `track_id`** — `z` only on the ball.

```jsonc
{"y": 7.83006579535, "x": -22.432314464, "trackable_object": 7648, "track_id": 19}
```

This is the format the current one replaced, and it is **genuinely sparse** — measured over
125 live frames of `2068`:

- objects per frame: min 13, max 19, **mean 15.24**
- identified players per frame: mean **14.84 = 67.5 % of 22**; players who are off camera
  simply **have no row** (there is no extrapolation and no `is_detected` flag)
- ball (`trackable_object == 55`) present in only **40.0 %** of frames; its `z` is sometimes `null`
- full float precision, unlike the current 2-dp rounding

`trackable_object: null` rows (anonymous tracks with only a `track_id`) and the `group_name`
field are described in SkillCorner's old docs but **did not occur** in the 125-frame sample
measured here — a loader should still tolerate both.

Legacy ids are `trackable_object`, **not** `players[].id`. Current ids are `players[].id`,
**not** `trackable_object`. The two layouts key on different columns.

---

## 7. Gotchas

1. **Branch is `master`.** `main` does not exist.
2. **Tracking is Git LFS.** `raw.githubusercontent.com` silently returns a 133-byte pointer that
   is valid text and will not raise — it just is not data. Use
   `media.githubusercontent.com/media/...` with `-L`. Detect the stub by checking for the
   `version https://git-lfs.github.com/spec/v1` first line.
3. **`start_frame` is NOT always 10.** It is 10 for six matches but **2300** (`2011166`),
   **4040** (`2013725`), **2210** (`2015213`), **2510** (`2017461`). Half-time frames are also
   present in the file, so P2 `start_frame` can be ~9 500 frames after P1 `end_frame`
   (`2017461`: P1 ends 30210, P2 starts 39670). Always read `match_periods`; never assume.
4. **`timestamp` is a match clock with a hard +45:00 offset in period 2**, while the events CSV's
   `time_start` is period-relative and in a *different* format (`MM:SS.s` vs `HH:MM:SS.ss`).
   Mixing them silently shifts every second-half event by 45 minutes. Use frames.
5. **`ball.trackable_object: 55` in `match.json` is vestigial** — the current tracking file never
   emits it. The ball lives in `ball_data`. Only the legacy format uses id 55.
6. **`player_data[].player_id` joins to `players[].id`, not `players[].trackable_object`.**
   Verified: the 22 ids in a frame are a subset of `players[].id` and share **zero** members with
   the `trackable_object` set.
7. **No team field in tracking.** Home/away comes only from `players[].team_id` vs
   `home_team.id`/`away_team.id`. A player_id missing from the roster cannot be assigned a side.
8. **The data is extrapolated, so "22 players present" is not "22 players observed."**
   Only ~63 % carry `is_detected == true`, and some frames have **0**. Positions for the rest are
   modelled. Carry `is_detected` into `confidence` and do not silently present it as measured.
9. **`period` / `timestamp` are `null`** outside live play, with `player_data == []` and all
   `ball_data` values null. `json.loads` succeeds; arithmetic on them does not.
10. **`pitch_length` varies (104/105/106).** Hard-coding 105 skews x by up to ~1 % (≈0.5 m at the
    touchline). `pitch_width` is 68 everywhere, so the y scale is exactly 1.0 — but read it anyway.
11. **Coordinates overshoot the pitch** (y to 36.96 vs a ±34 bound) and ball `z` can be **negative**
    (−0.24). Bounds-assertions on raw values will fire.
12. **`possession.group` values contain a space**: `"home team"` / `"away team"`, and the field is
    null in 28.6 % of live frames.
13. **`referees` is `[]`** in all 10 current matches (the legacy set had them).
14. **The 85 MB JSONL will not fit in memory as one list** — ~59 k frames × 22 players ≈ 1.3 M
    rows per match. Stream it; the media host supports `Range`.
15. **`event_type` is not a conventional event vocabulary.** There is no `pass` or `shot` type;
    those are `player_possession` rows discriminated by `end_type`. A loader expecting
    StatsBomb-style types will produce an empty frame.
16. **No true `pressure` boolean and no body-part enum.** Both must be derived
    (`event_subtype` / `is_header` + `hand_pass`).

---

## 8. Fixtures

Committed under `tests/fixtures/skillcorner/` — all real bytes, all < 100 KB.

| file | bytes | contents |
|---|---|---|
| `matches.json` | 3 323 | full index of all 10 matches |
| `1886347_match.json` | 27 541 | **complete, untrimmed** metadata + 36-player roster |
| `1886347_tracking_head.jsonl` | 96 493 | frames **0–58** verbatim: 10 null-period frames then kickoff at frame 10 — covers the null→live transition |
| `1886347_tracking_period2.jsonl` | 96 239 | frames **31783–31832** verbatim, period 2 — covers the +45:00 match-clock offset |
| `1886347_dynamic_events_head.csv` | 96 832 | header + first 100 event rows, all 294 columns |
| `legacy/2068_match_data.json` | 16 914 | complete legacy metadata (has `referees`, lacks `match_periods`) |
| `legacy/2068_structured_data_slice.json` | 96 901 | frames **1828–1899**, valid JSON array, spans the legacy null→live transition |

Every `.jsonl` / legacy slice was asserted to contain **strictly consecutive** frame numbers.
The tracking lines are byte-identical to upstream (not re-serialised), so they exercise a real
parser against real formatting. The legacy slice is re-serialised compactly to fit the size cap;
its values are unmodified.

Full downloads cached (gitignored) under `data/raw/skillcorner/`.

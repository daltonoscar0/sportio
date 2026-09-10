# Metrica Sports sample data, schema notes

Source: <https://github.com/metrica-sports/sample-data> (branch `master`).
Public, no auth, no rate limiting beyond normal raw.githubusercontent.com limits.
Verified live on 2026-08-25. Everything below was measured on the real files, not inferred.

Anonymised: no real competition / season / team / player names. Teams are literally
`Home` / `Away` (games 1-2) and `Team A` / `Team B` (game 3).

## 1. Repo layout

```
data/
  Sample_Game_1/
    Sample_Game_1_RawEventsData.csv                  139,446 B
    Sample_Game_1_RawTrackingData_Home_Team.csv   32,782,961 B
    Sample_Game_1_RawTrackingData_Away_Team.csv   32,782,073 B
  Sample_Game_2/
    Sample_Game_2_RawEventsData.csv                  153,897 B
    Sample_Game_2_RawTrackingData_Home_Team.csv   31,890,338 B
    Sample_Game_2_RawTrackingData_Away_Team.csv   29,627,711 B
  Sample_Game_3/
    Sample_Game_3_events.json                      1,709,486 B   (Metrica JSON events)
    Sample_Game_3_metadata.xml                        81,806 B   (FIFA EPTS metadata)
    Sample_Game_3_tracking.txt                    53,443,115 B   (FIFA EPTS tracking)
```

Games 1 and 2 = "Metrica CSV" format. Game 3 = EPTS/FIFA format (added 2021-04-15),
a completely different set of files. There is **no** CSV tracking for game 3 and **no**
EPTS tracking for games 1-2. There is no `documentation/` folder in the repo despite the
README referencing one.

## 2. URL templates

```
https://raw.githubusercontent.com/metrica-sports/sample-data/master/data/Sample_Game_{g}/Sample_Game_{g}_RawTrackingData_Home_Team.csv
https://raw.githubusercontent.com/metrica-sports/sample-data/master/data/Sample_Game_{g}/Sample_Game_{g}_RawTrackingData_Away_Team.csv
https://raw.githubusercontent.com/metrica-sports/sample-data/master/data/Sample_Game_{g}/Sample_Game_{g}_RawEventsData.csv
```
with `g` in `{1, 2}`. For game 3:
```
https://raw.githubusercontent.com/metrica-sports/sample-data/master/data/Sample_Game_3/Sample_Game_3_metadata.xml
https://raw.githubusercontent.com/metrica-sports/sample-data/master/data/Sample_Game_3/Sample_Game_3_tracking.txt
https://raw.githubusercontent.com/metrica-sports/sample-data/master/data/Sample_Game_3/Sample_Game_3_events.json
```
Directory listing (if you want to discover files):
`https://api.github.com/repos/metrica-sports/sample-data/contents/data/Sample_Game_{g}`

## 3. Tracking CSV, the 3-row header, verbatim

First six lines of `Sample_Game_1_RawTrackingData_Home_Team.csv`, byte for byte:

```
,,,Home,,Home,,Home,,Home,,Home,,Home,,Home,,Home,,Home,,Home,,Home,,Home,,Home,,Home,,,
,,,11,,1,,2,,3,,4,,5,,6,,7,,8,,9,,10,,12,,13,,14,,,
Period,Frame,Time [s],Player11,,Player1,,Player2,,Player3,,Player4,,Player5,,Player6,,Player7,,Player8,,Player9,,Player10,,Player12,,Player13,,Player14,,Ball,
1,1,0.04,0.00082,0.48238,0.32648,0.65322,0.33701,0.48863,0.30927,0.35529,0.32137,0.21262,0.41094,0.72589,0.41698,0.47843,0.39125,0.3255,0.45388,0.21174,0.52697,0.3798,0.55243,0.43269,NaN,NaN,NaN,NaN,NaN,NaN,0.45472,0.38709
1,2,0.08,0.00096,0.48238,0.32648,0.65322,0.33701,0.48863,0.30927,0.35529,0.32137,0.21262,0.41094,0.72589,0.41698,0.47843,0.39125,0.3255,0.45388,0.21174,0.52697,0.3798,0.55243,0.43269,NaN,NaN,NaN,NaN,NaN,NaN,0.49645,0.40656
1,3,0.12,0.00114,0.48238,0.32648,0.65322,0.33701,0.48863,0.30927,0.35529,0.32137,0.21262,0.41094,0.72589,0.41698,0.47843,0.39125,0.3255,0.45388,0.21174,0.52697,0.3798,0.55243,0.43269,NaN,NaN,NaN,NaN,NaN,NaN,0.53716,0.42556
```

Away file, first four lines:

```
,,,Away,,Away,,Away,,Away,,Away,,Away,,Away,,Away,,Away,,Away,,Away,,Away,,Away,,Away,,Away,
,,,25,,15,,16,,17,,18,,19,,20,,21,,22,,23,,24,,26,,27,,28,,,
Period,Frame,Time [s],Player25,,Player15,,Player16,,Player17,,Player18,,Player19,,Player20,,Player21,,Player22,,Player23,,Player24,,Player26,,Player27,,Player28,,Ball,
1,1,0.04,0.90509,0.47462,0.58393,0.20794,0.67658,0.4671,0.6731,0.76476,0.40783,0.61525,0.45472,0.38709,0.5596,0.67775,0.55243,0.43269,0.50067,0.94322,0.43693,0.05002,0.37833,0.27383,NaN,NaN,NaN,NaN,NaN,NaN,0.45472,0.38709
```

### Row semantics (all three header rows have exactly 33 fields; so does every data row)

| row | meaning |
|-----|---------|
| 1 | team label. Non-empty only at even column indices `3,5,7,…,29` → the value `"Home"` / `"Away"`. Purely redundant with the filename. |
| 2 | **shirt number** for the player whose X column is at that index. Non-empty at indices `3,5,…,29`. |
| 3 | the real header. `Period,Frame,Time [s]` at indices 0,1,2; then `PlayerNN` at each even index `3,5,…,29` naming the **X** column; then `Ball` at index 31 naming the ball X column. |

Column index -> meaning (0-based, exactly 33 columns):

```
0  Period
1  Frame
2  Time [s]
3  <first player> X       4  <first player> Y     (header label sits on the X column only)
5  <second player> X      6  <second player> Y
...                                               (14 players × 2 = indices 3..30)
31 Ball X                32 Ball Y
```

Row 2 pairs the shirt number to the player id: for the Home file index 3 carries
`Player11` / shirt `11`; index 5 carries `Player1` / shirt `1`, etc. In games 1 and 2 the
number in `PlayerNN` happens to equal the shirt number for the home team, but do **not**
rely on it, read row 2 for the jersey and row 3 for the id. Away players carry global ids
(`Player15…Player28`) whose shirt numbers in row 2 are `15…28` here, but the id namespace
is match-global across both teams, so `player_id` is unique match-wide while `jersey` is
only unique within a team.

Player column ordering is **goalkeeper first, then outfield, then substitutes**, it is
*not* numerically sorted: Home order is `11, 1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 12, 13, 14`,
Away order is `25, 15, 16, 17, 18, 19, 20, 21, 22, 23, 24, 26, 27, 28`. Never assume
`Player11` is the GK by number; it is the GK because it is the first player column.

### Robust pandas parse

```python
import csv, pandas as pd

def read_metrica_tracking(path):
    with open(path, newline="") as f:
        r = csv.reader(f)
        row_team, row_jersey, row_name = next(r), next(r), next(r)

    df = pd.read_csv(path, skiprows=2)           # row 3 becomes the header
    # -> columns: Period, Frame, Time [s], Player11, Unnamed: 4, Player1, Unnamed: 6, ...
    #             ..., Player14, Unnamed: 30, Ball, Unnamed: 32

    cols = []
    for i, name in enumerate(row_name):
        if i < 3 or not name:
            continue
        cols.append({
            "entity":  "ball" if name == "Ball" else name,   # "Player11" / "ball"
            "team":    (row_team[i] or None) if name != "Ball" else "ball",
            "jersey":  (row_jersey[i] or None) or None,
            "x_col":   df.columns[i],
            "y_col":   df.columns[i + 1],
        })
    return df, cols
```

Do **not** use `header=[0,1,2]`; the empty cells make pandas forward-fill a MultiIndex in
a way that silently mislabels the Y columns. Do **not** key off the `Unnamed: N` names
(they are pandas artefacts and shift if the file changes). Key off **positional index + 1**.

## 4. Frame rate, time, periods (measured on Sample_Game_1)

* `Frame`: integer, starts at **1**, strictly `+1` per row, runs `1 … 145006` (both files identical).
* `Time [s]`: `0.04 … 5800.24`. Every consecutive diff is exactly `0.04` → **25 fps**.
* Exact identity holds: `Frame == Time [s] * 25` (verified `np.allclose`, atol 1e-6).
* `Period`: `1` for frames `1…71268` (71,268 rows), `2` for frames `71269…145006` (73,738 rows).
* **`Time [s]` is CUMULATIVE across periods, not reset.** Period 2 begins at
  `Time [s] = 2850.76`, i.e. it continues straight on from period 1's last value `2850.72`.
  `Frame` is likewise continuous, there is no half-time gap in the file, the two halves
  are simply concatenated. Period 1 spans 47.51 min of frames, period 2 spans 49.16 min.
* For the canonical `t` (seconds within period):
  `t = df["Time [s]"] - df.groupby("Period")["Time [s]"].transform("min")`
  (or equivalently `(Frame - first_frame_of_period) / 25`).
* Home and Away tracking files are frame-aligned: `Period`, `Frame`, `Time [s]` and both
  `Ball` columns are element-wise identical between the two files. Load either one for the
  ball; do not double-count it.

Game 3 (EPTS) is also 25 fps (`<FrameRate>25</FrameRate>`), first half frames `1…69661`,
second half `69662…143761`.

Both are ≥ the 10 Hz tracking minimum; downsample by taking every 3rd frame if you want 8.33 Hz,
or every frame for the full 25 Hz.

## 5. Coordinate system

Normalised to the unit square. Stated by the repo README and confirmed empirically:

> "You'll see the data goes from 0 to 1 on each axis. The coordinate (0,0) is the top left,
> (1,1) is the bottom right, and (0.5,0.5) is the kick off point.
> The dimensions of the field are the same for both games: 105x68 meters."

* **Origin = top-left corner** of the pitch as seen from the broadcast camera.
* `x` increases to the **right** (toward the right-hand goal line at `x = 1`).
* `y` increases **downward** (screen/image convention, i.e. a *left-handed* system -
  y is flipped relative to the usual "y up" analytics convention).
* Centre spot = `(0.5, 0.5)`. Measured ball position at real kick-offs:
  `(0.49442, 0.49757)`, `(0.49415, 0.49726)`, `(0.49358, 0.49875)`, `(0.50217, 0.50665)`.
* Goal mouths are at `x ≈ 0` and `x ≈ 1`, centred on `y = 0.5`. Goal half-width
  `3.66 / 68 = 0.0538`, so the goal spans `y ∈ [0.4462, 0.5538]`. Every scored goal in
  game 1 lands in that band: `End Y` = `0.55, 0.54, 0.54, 0.51` at `End X` = `1.01, 1.01, 0.00, -0.01`.

Measured ranges in `Sample_Game_1` (values escape `[0,1]`, players and ball go off-pitch):

| quantity | min | max |
|---|---|---|
| player x (all 28 players) | `-0.02973` | `1.04722` |
| player y (all 28 players) | `-0.05000` | `1.05000` (hard clamp) |
| ball x | `-0.04548` | `1.05996` |
| ball y | `-0.03991` | `1.03782` |
| events `Start X` | `0.00` | `1.01` |
| events `Start Y` | `-0.02` | `1.01` |
| events `End X` | `-0.05` | `1.06` |
| events `End Y` | `-0.04` | `1.04` |

Do **not** clip to `[0,1]`, off-pitch positions (throw-ins, goals over the line, players
on the touchline) are legitimate and the clip would corrupt them.

### Transform to 105 × 68 metres

Absolute pitch frame, origin bottom-left, y up (the usual analytics convention):

```
x_m = x_norm * 105.0
y_m = (1.0 - y_norm) * 68.0        # NOTE the flip: Metrica y runs downward
```

Centred variant (origin at centre spot, x right, y up):

```
x_m = (x_norm - 0.5) * 105.0       # in [-52.5, +52.5]
y_m = (0.5 - y_norm) * 68.0        # in [-34, +34]
```

Sanity check of the scale: with the above, ball speed over game 1 has median 5.29 m/s and
p99 23.66 m/s; a typical outfield player (Player7) has median 1.42 m/s and p99 6.03 m/s.
Those are physically right for football, so the 105×68 mapping is correct.

## 6. Direction of play, teams DO switch ends at half time

Measured on `Sample_Game_1`, mean `x` over all frames of each period:

| | period 1 | period 2 |
|---|---|---|
| mean x, all Home players | `0.4735` | `0.5828` |
| mean x, all Away players | `0.6017` | `0.4583` |
| **Home GK (`Player11`) mean x** | **`0.1245`** | **`0.9053`** |
| **Away GK (`Player25`) mean x** | **`0.8936`** | **`0.1168`** |

So in period 1 Home defends the **left** goal and attacks **+x** (left->right); in period 2
Home defends the **right** goal and attacks **−x**. Away is the mirror.

Corroborated by the shots: every Home shot in period 1 has `End X` near `1.0` (`1.01, 1.04, 0.98, 1.03, 1.05, 1.00`)
and every Home shot in period 2 has `End X` near `0.0` (`-0.02, 0.00, 0.00, -0.01, -0.03, -0.02, 0.02`).

**Detector to use** (robust, no metadata needed for games 1-2):

```python
# GK = the FIRST player column in each tracking file.
gk_x = df.groupby("Period")[gk_x_col].mean()
# attacking direction for that team in that period:
#   +1 (left->right) if gk_x < 0.5 else -1
```
Mean x of the whole team also works (`0.4735 / 0.5828` vs `0.6017 / 0.4583`) but the
separation is only ~0.12, whereas the GK separates by ~0.78. Use the GK.

The switch is instantaneous at the period boundary, Home GK x is `0.15355` at frame 71268
and `1.01279` at frame 71269.

To normalise to "attacking left-to-right for the team in possession", flip when direction
is `-1`: `x' = 105 - x_m`, `y' = 68 - y_m` (a 180° rotation, not a mirror, mirroring only
x would flip left/right wing labels).

Game 3 does not need the heuristic, its metadata states it directly:
`<Team id="FIFATMA">` has `ProviderParameter` `attack_direction_first_half = right_to_left`
and `FIFATMB` has `left_to_right`.

## 7. Events CSV (games 1 and 2)

Single header line, verbatim, identical in both games:

```
Team,Type,Subtype,Period,Start Frame,Start Time [s],End Frame,End Time [s],From,To,Start X,Start Y,End X,End Y
```

First five rows of `Sample_Game_1_RawEventsData.csv`:

```
Away,SET PIECE,KICK OFF,1,1,0.04,0,0,Player19,,NaN,NaN,NaN,NaN
Away,PASS,,1,1,0.04,3,0.12,Player19,Player21,0.45,0.39,0.55,0.43
Away,PASS,,1,3,0.12,17,0.68,Player21,Player15,0.55,0.43,0.58,0.21
Away,PASS,,1,45,1.8,61,2.44,Player15,Player19,0.55,0.19,0.45,0.31
Away,PASS,,1,77,3.08,96,3.84,Player19,Player21,0.45,0.32,0.49,0.47
```

* Game 1: 1745 rows (`Home` 917 / `Away` 828; period 1 892 / period 2 853).
* Game 2: 1935 rows (`Home` 1044 / `Away` 891).
* `Team` ∈ `{Home, Away}`, matches the tracking filename.
* `Start Frame` / `End Frame` index directly into the tracking `Frame` column (1-based).
* `Start Time [s]` / `End Time [s]` are the same **cumulative** clock as tracking
  (`Start Time [s] == Start Frame / 25`).
* `From` is the actor, `To` the receiver (`To` null on 946/1745 rows in game 1 -
  only passes and some challenges have one). Both are strings like `Player11`.
* `Start X/Y`, `End X/Y` are in the same 0-1 top-left-origin frame as tracking, but
  **rounded to 2 decimals**. Cross-checked against the tracking ball position at
  `Start Frame`: median distance `0.0045` (≈0.4 m), p90 `0.0182`; 85.3 % of events are
  within `0.01`. They are genuinely synchronised, just coarser.
* Missing coords in game 1: `Start X/Y` null on 81 rows, `End X/Y` null on 636 rows.
  Nulls appear as the literal string `NaN`.

### `Type` vocabulary (complete, union of games 1 and 2, 9 values)

`BALL LOST`, `BALL OUT`, `CARD`, `CHALLENGE`, `FAULT RECEIVED`, `PASS`, `RECOVERY`,
`SET PIECE`, `SHOT`

Game 1 counts: `PASS` 799, `RECOVERY` 278, `BALL LOST` 257, `CHALLENGE` 233, `SET PIECE` 77,
`BALL OUT` 51, `SHOT` 24, `FAULT RECEIVED` 22, `CARD` 4.
Game 2 counts: `PASS` 964, `CHALLENGE` 311, `RECOVERY` 248, `BALL LOST` 233, `SET PIECE` 80,
`BALL OUT` 49, `SHOT` 24, `FAULT RECEIVED` 20, `CARD` 6.

Game 3's JSON adds a 10th type, `CARRY` (1395 of its 3620 events). Games 1-2 have **no**
carry/dribble-with-ball events at all.

### `Subtype` is a hyphen-joined *set of tags*, not an enum

`Subtype` is empty (`NaN`) on 953/1745 rows in game 1. When present it is one or more
atomic tags joined with `-`, e.g. `HEAD-ON TARGET-GOAL` = {HEAD, ON TARGET, GOAL}.
61 distinct composite strings across games 1+2; **tag order is not stable**, game 1 has
`HEAD-OFF TARGET-OUT` while game 2 has `OFF TARGET-HEAD-OUT`. Parse with `s.split("-")`
into a set, never string-match the whole thing.

Careful: `TACKLE-FAULT-WON` splits cleanly, but a naive split also breaks nothing here
because no atomic tag contains a hyphen (they contain spaces instead: `OFF TARGET`,
`GOAL KICK`, `THROW IN`, `CORNER KICK`, `KICK OFF`, `FREE KICK`, `DEEP BALL`,
`THROUGH BALL`, `HAND BALL`, `END HALF`, `REFEREE HIT`, `ON TARGET`).

**Authoritative atomic tag list** (39 values, from `Sample_Game_3_events.json` →
`metadata[]` where `category == "SUBTYPE"`), with Metrica's own ids:

```
11 HEAD          12 CLEARANCE     13 CROSS        14 THROUGH BALL  15 DEEP BALL
16 OFFSIDE       17 VOLUNTARY     18 FORCED       19 END HALF      20 GOAL KICK
21 HAND BALL     22 REFEREE HIT   23 INTERCEPTION 24 THEFT         25 BLOCKED
26 SAVED         27 WOODWORK      28 ON TARGET    29 OFF TARGET    30 GOAL
31 OUT           32 FREE KICK     33 CORNER KICK  34 THROW IN      35 KICK OFF
36 PENALTY       37 DIRECT        38 INDIRECT     39 RETAKEN       40 YELLOW
41 RED           42 GROUND        43 AERIAL       44 TACKLE        45 DRIBBLE
46 FAULT         47 ADVANTAGE     48 WON          49 LOST
```
and `category == "TYPE"`:
```
1 PASS   2 SHOT   3 RECOVERY   4 FAULT RECEIVED   5 SET PIECE
6 BALL OUT   7 BALL LOST   8 CARD   9 CHALLENGE   10 CARRY
```

Composite `Subtype` strings actually observed in game 1 (52 distinct incl. `NaN`), by Type:

| Type | Subtypes observed (game 1) |
|---|---|
| `PASS` | `CLEARANCE`, `CROSS`, `DEEP BALL`, `GOAL KICK`, `HEAD`, `HEAD-CLEARANCE`, `THROUGH BALL-DEEP BALL`, *(empty)* |
| `SHOT` | `BLOCKED`, `HEAD-OFF TARGET-OUT`, `HEAD-ON TARGET-GOAL`, `HEAD-ON TARGET-SAVED`, `HEAD-WOODWORK-OUT`, `OFF TARGET`, `OFF TARGET-OUT`, `ON TARGET-GOAL`, `ON TARGET-SAVED` |
| `RECOVERY` | `BLOCKED`, `INTERCEPTION`, `SAVED`, `THEFT` |
| `BALL LOST` | `CLEARANCE`, `CROSS-INTERCEPTION`, `DEEP BALL`, `END HALF`, `FORCED`, `GOAL KICK`, `GOAL KICK-INTERCEPTION`, `HEAD`, `HEAD-CLEARANCE`, `HEAD-FORCED`, `HEAD-INTERCEPTION`, `INTERCEPTION`, `OFFSIDE`, `REFEREE HIT`, `THEFT`, `WOODWORK` |
| `BALL OUT` | `CLEARANCE`, `CROSS`, `GOAL KICK`, `HEAD`, `HEAD-CLEARANCE`, `WOODWORK-GOAL`, *(empty)* |
| `CHALLENGE` | `AERIAL-FAULT-LOST`, `AERIAL-FAULT-WON`, `AERIAL-LOST`, `AERIAL-WON`, `DRIBBLE-WON`, `GROUND`, `GROUND-ADVANTAGE-LOST`, `GROUND-FAULT-LOST`, `GROUND-FAULT-WON`, `GROUND-LOST`, `GROUND-WON`, `TACKLE-ADVANTAGE-LOST`, `TACKLE-ADVANTAGE-WON`, `TACKLE-FAULT-LOST`, `TACKLE-FAULT-WON`, `TACKLE-LOST`, `TACKLE-WON` |
| `SET PIECE` | `CORNER KICK` (11), `FREE KICK` (32), `KICK OFF` (6), `THROW IN` (28) |
| `CARD` | `YELLOW` |
| `FAULT RECEIVED` | *(always empty)* |

Additional composites present only in game 2: `CLEARANCE-INTERCEPTION`, `FAULT-WON`,
`FORCED-END HALF`, `FREE KICK-RETAKEN`, `GROUND-ADVANTAGE-WON`, `HAND BALL`,
`HEAD-INTERCEPTION-CLEARANCE`, `KICK OFF-RETAKEN`, `OFF TARGET-HEAD-OUT`, `PENALTY`.
`RED` never appears in either sample.

### Mapping to the canonical event schema

| canonical | Metrica CSV |
|---|---|
| `match_id` | synthesise, e.g. `"metrica-1"` (nothing in the files) |
| `competition` | none, use `"Metrica Sample"` |
| `season` | none |
| `team_id` / `team` | `Team` (`"Home"` / `"Away"`) |
| `player_id` / `player` | `From` (string `"Player11"`; strip the `Player` prefix for a numeric id) |
| `t` | `Start Time [s]` **minus** the period's first `Start Time [s]` |
| `period` | `Period` |
| `type` | `Type` |
| `subtype` | `Subtype` (split on `-` for tags) |
| `x` / `y` | `Start X` / `Start Y` → metres via §5 |
| `end_x` / `end_y` | `End X` / `End Y` |
| `outcome` | derive from tags: `WON`/`LOST`, `GOAL`/`SAVED`/`OFF TARGET`/`BLOCKED`/`WOODWORK`, `INTERCEPTION` |
| `pressure` | **not available**, Metrica has no under-pressure flag. Emit `None`/`False`, or derive from tracking (nearest opponent distance) |
| `body_part` | only `HEAD` is tagged; everything else is implicitly foot/unknown. Do **not** assume "not HEAD ⇒ foot" for e.g. `HAND BALL`. |
| `extra` | keep `End Frame`, `End Time [s]`, `To`, raw `Subtype` |

## 8. Player id ↔ tracking column mapping

Events use exactly the strings that appear in tracking header row 3:
`Player1 … Player28` in game 1 (28 distinct ids across `From` ∪ `To`; 14 in the Home file,
14 in the Away file, disjoint). So the join is a literal string match against the row-3
labels. The shirt number lives in row 2 at the same column index.

Which file a player is in tells you their team; there is no team field in events beyond
`Team`, and `Team` in events uses the same `"Home"`/`"Away"` vocabulary as the filenames.

**Game 2 breaks this.** Its events file contains `"Player 26"`, with a space, on 32 rows,
and never `"Player26"`. A naive `==` join silently drops those 32 events. Normalise with
`re.sub(r"\s+", "", pid)` (or `pid.replace(" ", "")`) before joining. Game 1 has no such
anomaly (all 28 ids match `^Player\d+$`).

## 9. Game 3, EPTS format (different loader entirely)

`Sample_Game_3_metadata.xml` (FIFA EPTS XML, root `<main>`):

```
main/Metadata/GlobalConfig/FrameRate                       -> "25"
main/Metadata/GlobalConfig/ProviderGlobalParameters/ProviderParameter
      first_half_start=1  first_half_end=69661
      second_half_start=69662  second_half_end=143761
      (first/second_extra_half_* present but empty)
main/Metadata/Sessions/Session[@id="session1"]/Start        -> "2019-02-21T03:30:07.000Z"
main/Metadata/Sessions/Session/FieldSize/Width              -> "105"
main/Metadata/Sessions/Session/FieldSize/Height             -> "68"
main/Metadata/Sessions/Session/Competition[@id="DEMO"]      -> "Demo"
main/Metadata/Sessions/Session/MatchParameters/Score        -> idLocalTeam="FIFATMA" idVisitingTeam="FIFATMB", 0-2
main/Metadata/Teams/Team[@id]/Name                          -> "Team A" / "Team B"
main/Metadata/Teams/Team/ProviderTeamsParameters/ProviderParameter
      attack_direction_first_half -> "right_to_left" (FIFATMA) / "left_to_right" (FIFATMB)
main/Metadata/Players/Player[@id="P3578"][@teamId="FIFATMA"]/Name        -> "Player 11"
      .../ShirtNumber -> "11"
      .../ProviderPlayerParameters/ProviderParameter: position_type ("Goalkeeper",
          "Right Back", "Right Center Back (4)", ...), position_index, position_x, position_y
      35 <Player> elements total
main/Metadata/Devices/Device/Sensors/Sensor[@id="position"]/Channels/Channel[@id="x"|"y"]/Unit -> "normalized"
main/Metadata/PlayerChannels/PlayerChannel[@channelId="x"|"y"][@id="player1_x"][@playerId="P3578"]   (70 elements)
main/DataFormatSpecifications/DataFormatSpecification[@startFrame][@endFrame][@separator=":"]
      StringRegister name="frameCount"
      SplitRegister separator=";"  ->  SplitRegister separator=","  -> PlayerChannelRef ×2  (22 players)
      SplitRegister separator=","  ->  BallChannelRef channelId="x"|"y"
```

There are **11** `DataFormatSpecification` blocks, each covering a frame range, the column
layout changes at every substitution. Ranges: `1–69661`, `69662–89697`, `89698–93452`,
`93453–93835`, `93836–94657`, `94658–98472`, `98473–102811`, `102812–110298`,
`110299–120212`, `120213–129831`, `129832–143761`. Each block always lists 22 players + ball,
but *which* `playerN_*` channels differ. A loader must pick the block whose
`[startFrame, endFrame]` contains the frame before decoding the row.

`Sample_Game_3_tracking.txt`, one line per frame, no header:

```
1:0.84722,0.52855;0.65268,0.24792;...;0.48864,0.36357:NaN,NaN
2:0.84722,0.52855;0.65231,0.24513;...;0.48834,0.36362:NaN,NaN
```
`frameCount : player1_x,player1_y ; player2_x,player2_y ; … ; player22_x,player22_y : ball_x,ball_y`
Same normalised 0-1 coordinates. Missing values are the literal `NaN`.

`Sample_Game_3_events.json`, `{"data": [...3620 events...], "metadata": [...49 code entries...]}`.
Per-event keys:

```json
{
  "index": 2,
  "team":  {"name": "Team A", "id": "FIFATMA"},
  "type":  {"name": "PASS", "id": 1},
  "subtypes": null,
  "start": {"frame": 361, "time": 14.44, "x": 0.50125, "y": 0.48725},
  "end":   {"frame": 377, "time": 15.08, "x": 0.49864, "y": 0.48705},
  "period": 1,
  "from": {"name": "Player 10", "id": "P3577"},
  "to":   {"name": "Player 7",  "id": "P3574"}
}
```

`subtypes` is polymorphic: `null` (2750 events), a single object (477), or a **list** of
objects (393), e.g. `[{"name": "GROUND", "id": 42}, {"name": "LOST", "id": 49}]`. Handle all
three. `to` is `null` for non-pass events. `x`/`y` are `null` on set pieces and cards.
`time` is again cumulative (period 1 `14.44…2781.68`, period 2 `2803.6…5742.12`).
Note event `from.name` is `"Player 10"` **with a space**, unlike games 1-2, join on
`from.id` (`P3577`), which matches `Player/@id` in the metadata.

## 10. Gotchas that will break a naive loader

1. **Three header rows in the tracking CSV.** `pd.read_csv(path)` without `skiprows=2`
   produces a garbage frame. `header=[0,1,2]` also misparses (empty cells forward-fill).
2. **Every X column has an unnamed Y column immediately to its right.** After
   `skiprows=2` pandas renames these to `Unnamed: 4`, `Unnamed: 6`, … `Unnamed: 32`.
   Use positional index `+1`, not the `Unnamed:` names.
3. **The Away file mislabels the ball's X column.** Header row 1 of the Away file has
   `"Away"` at column index **31** (the `Ball` X column), giving 15 `"Away"` labels for
   14 players. The Home file correctly leaves index 31 blank. Deriving team membership by
   scanning row 1 will assign the ball to the away team.
4. **`Time [s]` does not reset at half time.** Period 2 starts at `2850.76 s`. Frame
   numbering is also continuous (`71269`), so there is no gap you can detect from the index.
   Subtract the per-period minimum to get seconds-within-period.
5. **Teams switch ends.** Any cross-period aggregation without flipping period 2 will
   average the two halves to nonsense (Home mean x `0.4735` then `0.5828`).
6. **The ball is `NaN` 39.1 % of frames** in game 1 (56,755 / 145,006), dead ball, half
   time, and the whole stretch from the period-2 first frame (71269) until the period-2
   kick-off at frame 72135. Don't forward-fill it; drop those ball rows.
7. **Substitutions appear as complementary all-NaN column spans**, not as extra rows.
   Home: `Player1` valid frames `1–46706`, `Player12` `46706–145006`; `Player6` `1–110849`,
   `Player13` `110849–145006`; `Player10` `1–121392`, `Player14` `121392–145006`.
   Away: `Player19` `1–119381` / `Player28` `119381–145006`; `Player22` `1–106869` /
   `Player27` `106869–145006`; `Player24` `1–106599` / `Player26` `106599–145006`.
   Melting to long format must drop NaN rows or you get 14 rows per team per frame
   instead of 11.
8. **Coordinates escape `[0, 1]`** (down to `-0.05`, up to `1.06`). Do not clip.
   Player `y` is hard-clamped at exactly `-0.05` / `1.05` while off pitch, which produces
   a run of identical values.
9. **Position teleports exist within a period.** Naive `diff/dt` velocity on game 1 Home
   gives max 557 m/s (`Player3`, frame 71279, walking on at the start of period 2 from the
   clamped `y = -0.05` line) and 70 m/s (`Player10`). Frames with a >1 m single-frame jump:
   `Player2` 11, `Player3` 9, `Player8` 13, `Player9` 1, `Player10` 7, 0 for everyone
   else. Ball has 183 frames above 40 m/s. For `vx`/`vy`, compute the diff **within**
   period, then clip implausible speeds (>12 m/s players, >45 m/s ball) to NaN and smooth
   (Savitzky-Golay or a ~7-frame moving average), otherwise the period boundary alone
   yields 1481 m/s.
10. **`Team` on a goal event is the last-touch team, not the scoring team.**
    Game 1 row index 1093 is `Home,BALL OUT,WOODWORK-GOAL,2...,End X 1.01`, in period 2
    Home defends `x = 1`, so this is a Home own goal and it is immediately followed by a
    `Home,SET PIECE,KICK OFF` (row 1094). The team that takes the restart kick-off is the
    team that **conceded**. Determine the scorer from attacking direction + goal end.
11. **Goals also appear under `Type = BALL OUT`** (`WOODWORK-GOAL`), not only under `SHOT`.
    Filtering `Type == "SHOT"` misses them.
12. **The first `SET PIECE / KICK OFF` row has `End Frame = 0`, `End Time [s] = 0`**
    (game 1 row 0). It is the only row with `End Frame == 0`. An `End Frame` of 0 is not a
    valid frame index (frames are 1-based), treat as null.
13. **The period-1 tracking does not start at the kick-off touch.** Frame 1 already has the
    ball at `(0.45472, 0.38709)`, i.e. the kick-off has been taken; the event file
    nonetheless stamps `KICK OFF` at frame 1 with null coordinates.
14. **Game 2 events contain `"Player 26"` with a space** (32 rows). Strip whitespace from
    player ids before joining to tracking columns.
15. **`Subtype` token order is not stable across games** (`HEAD-OFF TARGET-OUT` in game 1
    vs `OFF TARGET-HEAD-OUT` in game 2). Split into a set.
16. **Nulls are the literal string `NaN`** in both CSVs, fine for pandas defaults, but a
    hand-rolled `csv` reader must handle it.
17. **Game 3 is a different format entirely**, no CSV tracking, 11 frame-range-dependent
    column layouts, `subtypes` polymorphic (null | dict | list), and a `CARRY` event type
    that does not exist in games 1-2.
18. **No competition, season, match id, date, or real names** anywhere in games 1-2. Game 3
    has a date (`2019-02-21T03:30:07.000Z`) and a fake competition (`Demo`). All of
    `match_id`, `competition`, `season` must be synthesised by sportio.
19. **No under-pressure flag** in any Metrica format. `pressure` cannot be populated from
    the event data; it must be left null or computed from tracking.
20. Tracking files are ~30 MB each; a full game is ~65 MB. Stream/cache, never fetch twice.

## 11. Fixtures committed

Under `tests/fixtures/metrica/`:

* `Sample_Game_1_RawTrackingData_Home_Team.trunc.csv`, 81,917 B. Byte-identical 3-row
  header plus 362 data rows: frames `2200–2380` (period 1) and `72100–72280` (period 2).
* `Sample_Game_1_RawTrackingData_Away_Team.trunc.csv`, 81,865 B. Same frame set.
* `Sample_Game_1_RawEventsData.trunc.csv`, 94,705 B. Byte-exact prefix of the real file:
  header + first 1200 data rows (period 1 all 892 rows, period 2 first 308 rows;
  all 9 `Type` values, 48 distinct `Subtype` values).
* `game3/Sample_Game_3_metadata.xml`, 81,806 B, the complete real EPTS metadata.
* `game3/Sample_Game_3_tracking.head.txt`, 3,984 B, first frames of the EPTS stream.
* `game3/Sample_Game_3_events.head.json`, 58,087 B, first 120 events plus the full
  `metadata` code list.
* `game3/Sample_Game_3_tracking.slice.txt`, 70,355 B, 190 real rows in two windows: frames
  13560-13589 (period 1) and 120193-120352 (period 2). The second straddles the
  `DataFormatSpecification` boundary at 120212/120213, where `player16_*` switches from P3588
  (shirt 21) to P3700 (shirt 35), and reaches live ball again at 120305. This is the fixture
  that makes the block switching testable at all, the `head` file covers only block 1.
* `game3/Sample_Game_3_events.slice.json`, 34,529 B, 52 events (31 period 1, 21 period 2):
  both Team B goals into opposite ends, a yellow card, set pieces with null x/y, and all three
  `subtypes` shapes (null, object, list).

Properties the tracking fixtures preserve (assert these in tests):

| | Home | Away |
|---|---|---|
| shape after `skiprows=2` | `(362, 33)` | `(362, 33)` |
| rows per period | 181 / 181 | 181 / 181 |
| GK mean x, period 1 | `0.2661` (`Player11`) | `0.9942` (`Player25`) |
| GK mean x, period 2 | `0.9503` | `0.0521` |
| ball non-null rows | 256 | 256 |

The event fixture contains both a period-1 goal (`Home`, `HEAD-ON TARGET-GOAL`, frame 2289,
`End X 1.01`) and a period-2 goal (`Home`, `ON TARGET-GOAL`, frame 90005, `End X 0.00`) -
i.e. the same team scoring into opposite ends, which is exactly the direction-flip case.
Frames 2289 and 72100-72280 are both inside the truncated tracking windows, so the
event↔tracking synchronisation check works offline.

Full downloads are cached (gitignored) under `data/raw/metrica/`.

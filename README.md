# sportio

Shared data layer for the sports tools suite (setpiece, pressing, scout, replay, ruck).

Every open soccer and rugby source the suite uses is loaded here and normalised into exactly
two dataframes — `events` and `tracking`. Downstream tools import `sportio` and never touch a
vendor schema.

## Quickstart

```python
import sportio

ev = sportio.load_events("statsbomb", competition="Euro 2024", limit=3)
tr = sportio.load_tracking("metrica", match=1)

corners = sportio.corners(ev, with_freeze_frame=True)   # set-piece slice with 360 context
players = sportio.freeze_frames(corners)                # one row per tracked player
press   = sportio.set_pieces(ev, ["free_kick"], window=8.0)

ev = sportio.add_possession(ev)          # possession chains, however the vendor counts them
ev = sportio.add_zones(ev)               # the shared 18-zone grid, not one per tool
squad = sportio.load_lineups("statsbomb", match=3943043)   # shirt numbers and minutes

sportio.to_metrica(tr, "out.csv")        # round-trippable Metrica CSV pair
sportio.to_csv(ev, "euro2024.csv")       # canonical CSV, re-readable by `sportio validate`

sportio.validate_events(ev)              # raises SchemaError on anything off-contract
sportio.source_table()                   # what each source provides, and under what licence
```

```console
$ sportio info
$ sportio fetch statsbomb --competition "Euro 2024" --match 3943043 --out final.csv
$ sportio validate data/raw/metrica/Sample_Game_1_RawTrackingData_Home_Team.csv
```

## Canonical schemas

**`events`** — `match_id, competition, season, team_id, team, player_id, player, t, period,
type, subtype, x, y, end_x, end_y, outcome, pressure, body_part, extra`

**`tracking`** — `match_id, t, period, frame, team, player_id, jersey, x, y, vx, vy, confidence`

**`lineups`** (auxiliary, not a third canonical plane) — `match_id, team_id, team, player_id,
player, nickname, jersey, position, starter, on_at_full_time, minutes, minutes_estimated,
yellow_cards, red_cards, positions`. It exists because a shirt number and a minutes total live
nowhere in either canonical frame, and per-90 normalisation is impossible without them.

Guarantees every loader makes:

| | |
|---|---|
| Pitch | 105 × 68 m, origin **bottom-left**, `x` → right, `y` → **up** |
| Direction | events attack **left-to-right for the team in possession**; tracking is flipped so the **home** team attacks +x in every period |
| Time | `t` is **seconds since the start of the current period** — never a match clock |
| Rate | tracking is at least 10 Hz; slower sources are resampled, faster ones are left alone |
| Entities | `tracking.team` is only ever `home`, `away` or `ball` |
| Vocabulary | `type` / `subtype` / `outcome` are lowercase `snake_case`; set pieces use a shared vocabulary (`corner`, `free_kick`, `throw_in`, `goal_kick`, `kick_off`, `penalty`, `lineout`, `scrum`) |
| Nulls | nullable pandas dtypes throughout; `extra` is always a JSON **object** string |
| Escape hatch | anything a source knows that the schema does not is preserved in `extra` |

`sportio.validate_events` / `validate_tracking` enforce all of it with a pydantic row model.

### Derived views

These take a canonical frame and hand back a copy with extra columns, or a summary. They are
deliberately *not* part of the canonical schema — the column list above is a contract — but they
live here so that every tool computes them the same way.

| | |
|---|---|
| `possessions` / `add_possession` / `possession_frame` | Possession chains. Uses the vendor's own counter where there is one (StatsBomb chains, SkillCorner phases) and derives one from team changes and restarts where there is not. Ids never collide across matches. |
| `zones` / `add_zones` / `zone_labels` | The shared pitch grid, `ZONES_18` (6x3) by default, numbered from the defending corner. |
| `enrich_from_tracking` | Fills what an event feed omits but the tracking knows: set-piece positions from the ball, and a `pressure` flag from the nearest opponent. `metrica.load_events(enrich=True)` wires it up. |
| `possession_spans` + `normalize_direction(convention="possession")` | Rotates tracking per possession so the team on the ball attacks +x, matching the events convention. |

## Sources

| source | events | tracking | what it is | licence |
|---|---|---|---|---|
| **statsbomb** | ✅ | — | [StatsBomb Open Data](https://github.com/statsbomb/open-data): full event feeds plus 360 freeze frames, which land in `events.extra["freeze_frame"]` already on the canonical pitch. | StatsBomb Open Data User Agreement (non-commercial, attribution) |
| **metrica** | ✅ | ✅ | [Metrica Sports sample data](https://github.com/metrica-sports/sample-data): three fully-tracked anonymised matches at 25 Hz with matching event files. Games 1-2 are CSV; game 3 is FIFA EPTS, whose column layout is rewritten at every substitution — both arrive as the same canonical frame. | CC BY-NC-SA 4.0 |
| **skillcorner** | ✅ | ✅ | [SkillCorner open data](https://github.com/SkillCorner/opendata): ten A-League matches of 10 Hz broadcast tracking, plus their derived "dynamic events". | CC BY-NC-SA 4.0 |
| **soccernet** | — | ✅ | [SN-GSR-2025](https://huggingface.co/datasets/SoccerNet/SN-GSR-2025): 30-second game-state clips with metric pitch positions. Public, but 11.2 GB per split — sportio reads an already-extracted sequence. | GPL-3.0 (the separate SoccerNet-Tracking MOT archives are NDA-gated) |
| **rugby** | ✅ | — | ESPN rugby play-by-play (tries, conversions, penalty goals, drop goals, cards, substitutions, half markers). The type enum was established by censusing 9,626 rows across 184 matches. **No positional data exists in any open rugby feed** — see `TODO.md`. | ESPN content, used for research |

`sportio info` prints the same table, and `sportio info <source>` the detail.

## Downloads

Everything fetched is cached under `data/raw/` (gitignored) and never re-fetched. Requests are
rate-limited to one per second per host with exponential backoff. Set `SPORTIO_DATA_DIR` to move
the cache and `SPORTIO_OFFLINE=1` to forbid the network entirely — the test suite runs that way.

Sizes worth knowing before you type a command: a full StatsBomb competition is ~500 MB
(`--limit` caps it), a Metrica game is ~65 MB, a SkillCorner tracking file is ~85 MB behind Git
LFS, and a SoccerNet split is 11.2 GB.

## Development

```console
uv sync
uv run pytest          # offline, against tests/fixtures/
uv run pytest -m network   # the same acceptance checks against the live sources
uv run ruff check
```

The suite is verified against both ends of the declared pandas range — 2.1 (with numpy 1.x) and
3.0 — because the whole point of this package is that five other tools can depend on it.

`docs/schema_notes/` holds a measured, per-source description of every raw format — field paths,
coordinate systems and the specific ways each one breaks a naive loader. Read the relevant one
before changing a loader.

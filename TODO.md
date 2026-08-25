# TODO

Everything here is known and deliberate. Nothing in this list is silently wrong in the code —
each item is either a manual step, a limit of the source data, or a decision worth revisiting.

## Manual steps

### SoccerNet — download is manual, on purpose

`sportio fetch soccernet` refuses to run. A SN-GSR-2025 split is **11.2 GB** and sportio will
not pull that behind your back.

1. Download a split from <https://huggingface.co/datasets/SoccerNet/SN-GSR-2025>
   (`valid.zip` is the smallest useful one). It is **public** — no token, no NDA, despite what
   most write-ups about SoccerNet say. Range requests work, so the annotations can be pulled
   without the JPEGs if you only want positions.
2. Extract one sequence directory, e.g. `SNGS-056/`, containing `Labels-GameState.json`.
3. `sportio.load_tracking("soccernet", path="…/SNGS-056")`, or
   `sportio validate …/SNGS-056`.

The `SoccerNet` pip package is only needed if you want its downloader; sportio does not import
it. It is declared as the optional extra `sportio[soccernet]`.

### SoccerNet-Tracking (MOT) — gated *and* image-space only

The MOT-style archives (`gt/gt.txt`, `seqinfo.ini`, `gameinfo.ini`) need the SoccerNet NDA
password, and they ship **no camera calibration**. `soccernet.read_mot` parses them faithfully,
but `load_tracking(format="mot")` emits canonical rows with `x`/`y` **null** and warns, rather
than inventing a homography. Recovering pitch positions from MOT would need a calibration model
— that is a project, not a loader change.

The MOT fixture under `tests/fixtures/soccernet/mot/SNMOT-116/` is **synthetic**: hand-written
from the documented field names because the real archive is gated. Its `seqinfo.ini` says
`seqLength=750` while `gt/gt.txt` holds 3 frames. One detail is a genuine guess — whether
`trackletID_<i>` values have a space after the `;`. Verify against a real archive if you get one.

## Source limitations

### Rugby has no coordinates. At all.

This is the biggest gap in the suite and it is not fixable with more code:

- `rugbypy` / `seanyboi/rugbydata` publish **box-score aggregates only**. There is no
  `events/`, `plays/` or `timeline/` directory in either data version, and no ball-by-ball
  function in the package API.
- ESPN's rugby feed carries a **scoring-and-discipline** list — try, conversion, penalty goal,
  cards, substitutions — with a clock, a team and one athlete. A recursive walk of the full
  summary payload finds no coordinate, zone, metre or distance key. `commentaryAvailable` is
  `false`, so there is not even free text to derive positions from.
- Everything else found on GitHub is results-only, a scraper with no bundled data, or a parser
  for licensed Opta Superscout XML.

Consequences, all reflected in `sportio.loaders.rugby`:

- `x`, `y`, `end_x`, `end_y`, `pressure`, `body_part` are structurally null.
- 11 of the 17 terms in `RUGBY_EVENT_TYPES` — `carry, pass, kick, ruck, maul, lineout, scrum,
  tackle, turnover, knock_on, penalty` — never appear. The vocabulary is defined anyway so a
  better feed can be dropped in without touching anything downstream.
- The spec's `x = metres from own line` convention is therefore unimplemented. If a positional
  feed ever appears, map it into the existing `x`/`y` columns rather than adding new ones.
- ESPN `type.id` **4** and **6** were not observed in the sampled matches. They are mapped to
  `drop_goal` and red `card` from the enum ordering and flagged `extra["type_mapping"] =
  "unverified"`. Confirm against a match containing one before relying on them.
- Only *successful* kicks at goal produce a detail row, so conversion counts are not
  attempt counts.

### Metrica

- **Game 3 (FIFA EPTS format) is not implemented.** It is a different file set entirely:
  `Sample_Game_3_metadata.xml` (EPTS XML), `Sample_Game_3_tracking.txt` (a
  `frame:player_x,player_y;…:ball_x,ball_y` stream) and `Sample_Game_3_events.json`. The
  tracking stream has **11 different column layouts**, one per frame range, changing at every
  substitution — a loader has to select the right `DataFormatSpecification` before decoding
  each row. Schema is fully documented in `docs/schema_notes/metrica.md` §9. Games 1 and 2
  (CSV) are what `GAMES` advertises.
- **Every `SET PIECE` row has null coordinates** — all 62 of them in game 1, including all 10
  corners. `sportio.corners()` on Metrica returns rows with `x`/`y` null. The position can only
  be recovered by joining `Start Frame` against the tracking ball, which needs the full 65 MB
  tracking files. Worth adding as an opt-in `enrich_from_tracking=` flag.
- There is no `under_pressure` concept anywhere in Metrica, so `pressure` is always `False`.
  Deriving it from nearest-opponent distance in the tracking data is a real option.
- No competition, season, match id or real names exist in games 1–2; `match_id` is synthesised
  as `metrica-{n}`.

### StatsBomb

- **360 coverage of corners is thin.** 360 frames exist for ~87% of *events*, but only a
  minority of *corner deliveries* carry one — 3 of 12 in the Euro 2024 final. So
  `sportio.corners(ev)` returns every corner, and `corners(ev, with_freeze_frame=True)` returns
  the subset that has 360 context. The spec's acceptance criterion ("each with a freeze frame
  of ≥15 players") holds for the filtered set — every corner that has a frame comfortably
  clears 15 — but making the filter the default would silently hide three quarters of the
  corners from the setpiece tool. Flagging rather than deciding unilaterally.
- The 120×80 → 105×68 rescale is **plain linear**, which is what mplsoccer / socceraction /
  kloppy do, so sportio matches the ecosystem. It shrinks the penalty box and goal by 5–7%
  (goal 6.80 m vs 7.32 m, penalty spot 10.50 m vs 11.00 m). If box-relative features start to
  matter, add a piecewise-linear landmark-preserving option to `PitchSpec` rather than changing
  the default.
- Period 5 (penalty shootouts) is emitted as ordinary events, all located at the penalty spot.
  Decide per consumer whether to drop them.
- 360 freeze frames are attached per event into `extra`, which makes a full-competition events
  frame large. `three_sixty=False` turns it off.

### SkillCorner

- Tracking is **Git LFS**; `raw.githubusercontent.com` returns a 133-byte pointer stub that
  parses fine as text and is not data. The loader uses `media.githubusercontent.com` and raises
  if it ever sees a stub.
- The feed is **extrapolated**: all 22 players have a position in every live frame, but only
  ~63% are `is_detected`. That maps to `confidence` 1.0 vs 0.5. Do not treat 0.5 rows as
  measurements.
- `dynamic_events.csv` is Game Intelligence output, not a conventional event feed. `event_type`
  has four values; a pass is a `player_possession` row with `end_type == "pass"`. The committed
  fixture happens to contain **no** `end_type == "shot"` row, so that branch of the mapping is
  exercised only by the network tests. Worth extending the fixture.
- `1886347_tracking_period2.jsonl` is an extrapolation dead zone (mean 1.08 of 22 players
  detected). It is good for testing the time base and bad for testing geometry — the tests use
  it only for the former.
- `pitch_length` varies across matches (104/105/106 m) and the loader reads it per match. The
  canonical pitch is always 105×68, so a 104 m pitch is stretched by ~1%; this relocates the
  error rather than removing it, which is the best a fixed canonical pitch can do.

## Nice to have

- `to_parquet` and `rugby.load_rugbypy` need `pyarrow`, which sportio deliberately does not
  depend on. Both raise a clear install hint.
- `resample_tracking` interpolates linearly. For broadcast tracking a constant-velocity or
  spline fill would be better across short occlusions; `max_gap` currently just blanks them.
- `normalize_direction` supports `"home_ltr"` and `"raw"`. A `"possession"` convention for
  tracking (rotating per possession, matching the events convention) would help the pressing
  tool but needs a possession signal that only SkillCorner provides.
- No writer for StatsBomb or SkillCorner formats yet; only Metrica round-trips.

# TODO

Everything here is known and deliberate. Nothing in this list is silently wrong in the code -
each item is either a manual step, a limit of the source data, or a decision worth revisiting.

## Manual steps

### SoccerNet-Tracking (MOT), gated *and* image-space only

The MOT-style archives (`gt/gt.txt`, `seqinfo.ini`, `gameinfo.ini`) need the SoccerNet NDA
password, and they ship **no camera calibration**. `soccernet.read_mot` parses them faithfully,
but `load_tracking(format="mot")` emits canonical rows with `x`/`y` **null** and warns, rather
than inventing a homography. Recovering pitch positions from MOT would need a calibration model
- that is a project, not a loader change.

The MOT fixture under `tests/fixtures/soccernet/mot/SNMOT-116/` is **synthetic**: hand-written
from the documented field names because the real archive is gated. Its `seqinfo.ini` says
`seqLength=750` while `gt/gt.txt` holds 3 frames. One detail is a genuine guess, whether
`trackletID_<i>` values have a space after the `;`. Verify against a real archive if you get one.

## Source limitations

### Rugby has no coordinates. At all.

This is the biggest gap in the suite and it is not fixable with more code:

- `rugbypy` / `seanyboi/rugbydata` publish **box-score aggregates only**. There is no
  `events/`, `plays/` or `timeline/` directory in either data version, and no ball-by-ball
  function in the package API.
- ESPN's rugby feed carries a **scoring-and-discipline** list, try, conversion, penalty goal,
  drop goal, cards, substitutions and half markers, with a clock, a team and one athlete. A
  recursive walk of the full summary payload finds no coordinate, zone, metre or distance key.
  `commentaryAvailable` is `false`, so there is not even free text to derive positions from.
- Everything else found on GitHub is results-only, a scraper with no bundled data, or a parser
  for licensed Opta Superscout XML.

Consequences, all reflected in `sportio.loaders.rugby`:

- `x`, `y`, `end_x`, `end_y`, `pressure`, `body_part` are structurally null.
- 11 of the 19 terms in `RUGBY_EVENT_TYPES`, `carry, pass, kick, ruck, maul, lineout, scrum,
  tackle, turnover, knock_on, penalty`, never appear. The vocabulary is defined anyway so a
  better feed can be dropped in without touching anything downstream.
- The spec's `x = metres from own line` convention is therefore unimplemented. If a positional
  feed ever appears, map it into the existing `x`/`y` columns rather than adding new ones.
- Missed conversions and penalty goals produce **no row at all**, so those are counts of kicks
  *made*, not attempted. A missed drop goal does get its own row (`type.id` 37), so the three
  are not comparable attempt counts.
- The **scoreboard** play shape omits `period.number`, so the loader infers the half from the
  clock and sets `extra["period_inferred"]`. First-half added time overruns the nominal 2400 s
  boundary (a period-1 play at 2419 s, a period-2 play at 2402 s), so plays within ~20 s of
  half time can land in the wrong half. Use `summary` when the half matters.

The type enum itself is now **settled**, not guessed: a census of 9,626 detail rows across 184
matches and 11 competitions found exactly thirteen ids (1-12 and 37) and nothing else. See
`docs/schema_notes/rugby.md` §2.5 for the counts and the witness matches.

### Metrica

- **Events and tracking anchor `t` to different things in period 2.** Tracking sets `t = 0` at
  the period's first *frame* (game 1: frame 71269), while events set it at the period's first
  *event*, which is later, the second half restarts play well after the tracking file resumes.
  So `events.t` and `tracking.t` are on different period clocks in period 2 and must not be
  joined directly **unless you align them**: pass
  `starts=metrica.period_starts(tracking)` to `load_events` and both frames land on the same
  clock (verified event-by-event against the tracking rows). Failing that, join on frames -
  every event carries `extra["start_frame"]`, which indexes straight into `tracking.frame`.
  Making the alignment automatic would mean the events loader pulling the 65 MB tracking file,
  so it stays opt-in. `enrich=True` does it for you.
- Set pieces have null coordinates in the source, all 62 of them in game 1, including all 10
  corners. `load_events(enrich=True)` recovers them from the tracking ball; without it,
  `sportio.corners()` on Metrica returns positionless rows. Roughly one corner per match still
  cannot be recovered because the ball itself is null in tracking at that frame (dead ball).
- Metrica has no under-pressure concept, so `pressure` is `False` unless you pass `enrich=True`,
  which derives it from the distance to the nearest opponent and records that distance in
  `extra["opponent_distance"]`. 3 m is the default threshold; StatsBomb's own flag is closer to
  a 5 m cone, so tune it if you are trying to match that feed.
- Game 3 (FIFA EPTS) is supported and routes through `metrica_epts`, but `enrich=True` is not
  wired up for it.
- No competition, season, match id or real names exist in games 1-2; `match_id` is synthesised
  as `metrica-{n}`.

### StatsBomb

- **360 coverage of corners is thin.** 360 frames exist for ~87% of *events*, but only a
  minority of *corner deliveries* carry one, 3 of 12 in the Euro 2024 final. So
  `sportio.corners(ev)` returns every corner, and `corners(ev, with_freeze_frame=True)` returns
  the subset that has 360 context. The spec's acceptance criterion ("each with a freeze frame
  of ≥15 players") holds for the filtered set, every corner that has a frame comfortably
  clears 15, but making the filter the default would silently hide three quarters of the
  corners from the setpiece tool. Flagging rather than deciding unilaterally.
- The 120×80 -> 105×68 rescale is **plain linear by default**, which is what mplsoccer /
  socceraction / kloppy do, so sportio matches the ecosystem out of the box. It shrinks the
  penalty box and goal by 5-7% (goal 6.80 m vs 7.32 m, penalty spot 10.50 m vs 11.00 m). Pass
  `pitch="landmark"` for the piecewise map that pins the real markings instead. The two are not
  interchangeable, a frame read one way must be written back the same way.
- Period 5 (penalty shootouts) is emitted as ordinary events, all located at the penalty spot.
  Decide per consumer whether to drop them.
- 360 freeze frames are attached per event into `extra`, which makes a full-competition events
  frame large. `three_sixty=False` turns it off.
- `extra["length"]` and `extra["angle"]` are **recomputed** from the canonical coordinates, not
  copied from `pass.length` / `pass.angle`. StatsBomb measures those in 120x80 units on a
  y-down axis and the rescale is anisotropic (0.875 in x, 0.85 in y), so a copied value drifts
  from the coordinates beside it by up to ~15% in length and ~0.8 degrees in angle.
- `load_lineups` infers full time from the events when you pass them and otherwise falls back
  to the last substitution, which is only a floor. `minutes_estimated` marks exactly the rows
  that fallback affected.

### SoccerNet

- Downloading is automatic and cheap: `sportio fetch soccernet --split valid`, or
  `sportio.load_tracking("soccernet", split="valid", sequence="SNGS-056")`. The split archives
  are ZIP64 and Hugging Face honours byte ranges, so only the `Labels-GameState.json` members
  are fetched, **192 MB for all 58 sequences of `valid`, against 11.2 GB for the archive**.
  The JPEGs are 98% of it and sportio never opens one. No token, no NDA, despite what most
  write-ups about SoccerNet say.
- The `SoccerNet` pip package is only needed if you want *its* downloader; sportio does not
  import it. It stays declared as the optional extra `sportio[soccernet]`.
- Clips lose camera calibration for stretches at a time, `bbox_pitch` goes null on every
  object for hundreds of consecutive frames. Those detections are dropped by default;
  `keep_uncalibrated=True` keeps them with null coordinates.
- `attributes.team` is `left`/`right` **relative to the camera**, not a club, and a 30-second
  clip carries no goal or possession context, so attacking direction genuinely cannot be
  inferred. `direction` defaults to `"raw"` for this source alone.
- There is no squad data in the labels beyond `attributes.jersey`, so no `load_lineups`.

### SkillCorner

- Tracking is **Git LFS**; `raw.githubusercontent.com` returns a 133-byte pointer stub that
  parses fine as text and is not data. The loader uses `media.githubusercontent.com` and raises
  if it ever sees a stub.
- The feed is **extrapolated**: all 22 players have a position in every live frame, but only
  ~63% are `is_detected`. That maps to `confidence` 1.0 vs 0.5. Do not treat 0.5 rows as
  measurements.
- **Event coordinates are already in the acting team's attacking frame.** This is undocumented
  upstream; it was established by joining `x_start` against the same player's tracked position
  in the same frame, where a `right_to_left` row comes back negated on *both* axes. So the
  loader applies no rotation by default and only mirrors `on_ball_engagement` rows (the one
  event type whose actor is the team *off* the ball) to reach the canonical possession frame.
  `frame="acting"` opts out. If SkillCorner ever changes this, the join in
  `tests/test_sources.py::test_skillcorner_events_are_already_in_the_acting_teams_frame`
  is what will catch it.
- `dynamic_events.csv` is Game Intelligence output, not a conventional event feed. `event_type`
  has four values; a pass is a `player_possession` row with `end_type == "pass"` and a shot is
  one with `end_type == "shot"`.
- `1886347_tracking_period2.jsonl` is an extrapolation dead zone (mean 1.08 of 22 players
  detected). It is good for testing the time base and bad for testing geometry, the tests use
  it only for the former.
- `pitch_length` varies across matches (104/105/106 m) and the loader reads it per match. The
  canonical pitch is always 105×68, so a 104 m pitch is stretched by ~1%; this relocates the
  error rather than removing it, which is the best a fixed canonical pitch can do.

## Nice to have

- `to_parquet` and `rugby.load_rugbypy` need `pyarrow`, which sportio deliberately does not
  depend on. Both raise a clear install hint.
- Metrica game 3 does not support `enrich=True`; the EPTS tracking stream would need routing
  into the enricher first.
- `possession_spans` needs a `sides=` mapping for any source whose team ids are not literally
  `home`/`away`. The match metadata knows the answer for SkillCorner and StatsBomb, so a loader
  could supply it automatically.
- SoccerNet publishes no squad data in the GSR labels beyond `attributes.jersey`, so it has no
  `load_lineups`.

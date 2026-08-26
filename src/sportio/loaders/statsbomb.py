"""StatsBomb open data -- events and 360 freeze frames.

Repo: https://github.com/statsbomb/open-data (now redirecting to ``hudl/open-data``;
``raw.githubusercontent.com`` still serves the original path). Branch ``master``.

Three things about this feed are easy to get wrong and are handled here:

* **Coordinates are expressed in the acting team's frame, not the possession team's.** For the
  ~17% of events where ``team.id != possession_team.id`` -- pressures, blocks, goalkeeper
  actions -- the raw coordinates are rotated 180 degrees relative to the team on the ball. The
  canonical schema wants left-to-right *for the team in possession*, so those events are
  mirrored before rescaling. ``frame="acting"`` opts out and keeps StatsBomb's own convention.
* **A missing ``pass.outcome`` means the pass was completed**, not that the outcome is unknown.
* ``shot.end_location`` has **three** components when the shot left the ground; everything
  else has two.

360 freeze frames are attached per event at ``extra["freeze_frame"]`` with their coordinates
already on the canonical pitch. See ``docs/schema_notes/statsbomb.md``.
"""

from __future__ import annotations

import json
import math
import re
from pathlib import Path
from typing import Any

import pandas as pd
from tqdm.auto import tqdm

from ..http import Fetcher, default_fetcher
from ..pitch import PITCH_WIDTH, STATSBOMB, STATSBOMB_LANDMARK, PitchSpec
from ..schema import LINEUP_COLUMNS, concat_events, conform_lineups, encode_extra
from ..setpieces import extra_field
from ._common import finish_events, snake

__all__ = [
    "EURO_2024",
    "find_competition",
    "load_competitions",
    "load_events",
    "load_lineups",
    "load_matches",
]

BASE = "https://raw.githubusercontent.com/statsbomb/open-data/master/data"

#: ``(competition_id, season_id)`` for UEFA Euro 2024, the suite's default demo competition.
EURO_2024 = (55, 282)

_SB_LENGTH = 120.0
_SB_WIDTH = 80.0

#: Sub-dict ``type.name`` values that mark a restart, normalised to the canonical vocabulary.
_SET_PIECES = {
    "corner": "corner",
    "free_kick": "free_kick",
    "throw_in": "throw_in",
    "kick_off": "kick_off",
    "goal_kick": "goal_kick",
    "penalty": "penalty",
}

#: The type sub-dict is normally ``snake(type.name)``. "Goal Keeper" is the one exception --
#: StatsBomb spells that sub-dict "goalkeeper", so all 30 keeper events in a match would
#: otherwise lose their end_location, outcome, body_part and Shot Faced/Goal Conceded type.
_SUBDICT_ALIASES = {"goal_keeper": "goalkeeper"}

#: Keys promoted out of the type sub-dict into canonical columns; not repeated in ``extra``.
#: ``length`` and ``angle`` go too: StatsBomb measures them in its own 120x80 axes, and the
#: rescale is anisotropic (x by 0.875, y by 0.85), so neither survives the transform. They are
#: recomputed from the canonical coordinates by :func:`_geometry`.
_PROMOTED = frozenset({"end_location", "outcome", "body_part", "type", "length", "angle"})

_TOKEN = re.compile(r"[a-z0-9]+")


# --------------------------------------------------------------------------------------
# competition and match discovery
# --------------------------------------------------------------------------------------


def load_competitions(*, fetcher: Fetcher | None = None) -> pd.DataFrame:
    """Every competition/season pair StatsBomb publishes."""
    fetcher = fetcher or default_fetcher()
    return pd.DataFrame(fetcher.json(f"{BASE}/competitions.json", "statsbomb/competitions.json"))


def find_competition(
    query: str,
    season: str | None = None,
    *,
    competitions: pd.DataFrame | None = None,
    fetcher: Fetcher | None = None,
) -> tuple[int, int]:
    """Resolve a human name like ``"Euro 2024"`` to ``(competition_id, season_id)``.

    Matching is on tokens against ``"{country} {competition} {season}"``, so ``"Euro 2024"``,
    ``"UEFA Euro 2024"`` and ``("UEFA Euro", season="2024")`` all resolve to ``(55, 282)``.
    """
    table = load_competitions(fetcher=fetcher) if competitions is None else competitions
    wanted = set(_TOKEN.findall(query.lower()))
    if season:
        wanted |= set(_TOKEN.findall(str(season).lower()))
    if not wanted:
        raise ValueError("empty competition query")

    hits = []
    for row in table.to_dict(orient="records"):
        haystack = " ".join(
            str(row.get(k, "")) for k in ("country_name", "competition_name", "season_name")
        ).lower()
        tokens = set(_TOKEN.findall(haystack))
        if wanted <= tokens:
            hits.append((len(tokens), int(row["competition_id"]), int(row["season_id"]), haystack))
    if not hits:
        raise LookupError(f"no StatsBomb competition matches {query!r} (season={season!r})")
    # Prefer the most specific label when several match, e.g. "Euro" alone.
    hits.sort()
    if len(hits) > 1 and hits[0][0] == hits[1][0]:
        raise LookupError(f"{query!r} is ambiguous; candidates: {sorted(h[3] for h in hits)}")
    return hits[0][1], hits[0][2]


def load_matches(
    competition_id: int,
    season_id: int,
    *,
    fetcher: Fetcher | None = None,
) -> pd.DataFrame:
    """The match list for one competition/season."""
    fetcher = fetcher or default_fetcher()
    payload = fetcher.json(
        f"{BASE}/matches/{competition_id}/{season_id}.json",
        f"statsbomb/matches_{competition_id}_{season_id}.json",
    )
    return pd.json_normalize(payload)


# --------------------------------------------------------------------------------------
# lineups
# --------------------------------------------------------------------------------------

#: Assumed full time when nothing better is available, in minutes.
_NOMINAL_FULL_TIME = 90.0


def load_lineups(
    competition: str | None = None,
    *,
    season: str | None = None,
    match: int | str | None = None,
    competition_id: int | None = None,
    season_id: int | None = None,
    limit: int | None = None,
    lineups_file: str | Path | None = None,
    events: pd.DataFrame | None = None,
    full_time_minutes: float | None = None,
    fetcher: Fetcher | None = None,
) -> pd.DataFrame:
    """Squad lists with shirt numbers, positions and minutes played.

    Args:
        events: a canonical events frame for the same match(es). Used only to read the real
            full-time clock, which is what turns an open-ended ``positions[].to`` into minutes.
        full_time_minutes: state full time yourself and skip the inference entirely.

    Minutes are exact for anyone with a closed ``to`` on every spell. For a player still on at
    the whistle, full time is taken from ``events`` when you pass them, otherwise from the
    latest substitution in the file, otherwise 90 minutes -- and ``minutes_estimated`` says
    which of those happened, rather than leaving you to guess.
    """
    fetcher = fetcher or default_fetcher()

    if lineups_file is not None:
        payload = json.loads(Path(lineups_file).read_text())
        match_id = str(match or Path(lineups_file).stem)
        full_time = _full_time(match_id, payload, events, full_time_minutes)
        return _lineups_frame(payload, match_id, full_time)

    match_ids = _resolve_matches(
        competition, season, match, competition_id, season_id, limit, fetcher
    )
    frames = []
    for one in tqdm(match_ids, desc="statsbomb lineups", leave=False):
        payload = fetcher.json(
            f"{BASE}/lineups/{one}.json", f"statsbomb/lineups_{one}.json"
        )
        full_time = _full_time(str(one), payload, events, full_time_minutes)
        frames.append(_lineups_frame(payload, str(one), full_time))
    if not frames:
        return pd.DataFrame(columns=list(LINEUP_COLUMNS))
    return pd.concat(frames, ignore_index=True)


def _resolve_matches(
    competition: str | None,
    season: str | None,
    match: int | str | None,
    competition_id: int | None,
    season_id: int | None,
    limit: int | None,
    fetcher: Fetcher,
) -> list[int]:
    if match is not None and competition is None and competition_id is None:
        return [int(match)]
    if competition_id is None or season_id is None:
        if competition is None:
            raise ValueError("pass match=, or competition= (or competition_id= and season_id=)")
        competition_id, season_id = find_competition(competition, season, fetcher=fetcher)
    matches = load_matches(competition_id, season_id, fetcher=fetcher)
    if match is not None:
        matches = matches.loc[matches["match_id"].astype("int64") == int(match)]
    if limit is not None:
        matches = matches.head(limit)
    return [int(m) for m in matches["match_id"]]


def _full_time(
    match_id: str,
    payload: list[dict[str, Any]],
    events: pd.DataFrame | None,
    stated: float | None,
) -> tuple[float, bool]:
    """``(full_time_seconds, estimated)`` on the wall clock the lineups use."""
    if stated is not None:
        return stated * 60.0, False

    if events is not None and not events.empty:
        rows = events.loc[events["match_id"].astype("string") == match_id]
        if not rows.empty:
            minutes = pd.to_numeric(extra_field(rows, "minute"), errors="coerce")
            seconds = pd.to_numeric(extra_field(rows, "second"), errors="coerce")
            clock = (minutes * 60.0 + seconds.fillna(0.0)).dropna()
            if not clock.empty:
                return float(clock.max()), False

    # Every substituted player has a closed `to`; the latest of them is a floor on full time,
    # not full time itself, so anything derived from it is flagged as an estimate.
    latest = 0.0
    for team in payload:
        for player in team.get("lineup") or []:
            for spell in player.get("positions") or []:
                end = _clock_seconds(spell.get("to"))
                if end is not None:
                    latest = max(latest, end)
    return (latest or _NOMINAL_FULL_TIME * 60.0), True


def _clock_seconds(value: Any) -> float | None:
    """``"88:40"`` -> 5320.0. This is the match wall clock, not a period clock."""
    if not isinstance(value, str) or ":" not in value:
        return None
    try:
        minutes, seconds = value.split(":")
        return int(minutes) * 60.0 + float(seconds)
    except ValueError:  # pragma: no cover - defensive
        return None


def _lineups_frame(
    payload: list[dict[str, Any]], match_id: str, full_time: tuple[float, bool]
) -> pd.DataFrame:
    full_time_seconds, estimated = full_time
    rows = []
    for team in payload:
        team_id = _as_str(team.get("team_id"))
        team_name = team.get("team_name")
        for player in team.get("lineup") or []:
            spells = player.get("positions") or []
            played, open_ended = _minutes(spells, full_time_seconds)
            cards = player.get("cards") or []
            rows.append(
                {
                    "match_id": match_id,
                    "team_id": team_id,
                    "team": team_name,
                    "player_id": _as_str(player.get("player_id")),
                    "player": player.get("player_name"),
                    "nickname": player.get("player_nickname"),
                    "jersey": player.get("jersey_number"),
                    "position": spells[0].get("position") if spells else None,
                    "starter": bool(spells) and _clock_seconds(spells[0].get("from")) == 0.0,
                    "on_at_full_time": open_ended,
                    "minutes": played,
                    "minutes_estimated": estimated and open_ended,
                    "yellow_cards": sum(1 for c in cards if _card(c) == "yellow card"),
                    "red_cards": sum(1 for c in cards if "red" in _card(c)),
                    "positions": encode_extra({"spells": spells}) if spells else "{}",
                }
            )
    return conform_lineups(pd.DataFrame(rows, columns=list(LINEUP_COLUMNS)))


def _minutes(spells: list[dict[str, Any]], full_time_seconds: float) -> tuple[float, bool]:
    """Total time on the pitch, and whether any spell ran to the final whistle."""
    total = 0.0
    open_ended = False
    for spell in spells:
        start = _clock_seconds(spell.get("from"))
        if start is None:
            continue
        end = _clock_seconds(spell.get("to"))
        if end is None:
            end, open_ended = full_time_seconds, True
        total += max(0.0, end - start)
    return round(total / 60.0, 2), open_ended


def _card(card: Any) -> str:
    if isinstance(card, dict):
        return str(card.get("card_type") or "").lower()
    return str(card).lower()


# --------------------------------------------------------------------------------------
# events
# --------------------------------------------------------------------------------------


def load_events(
    competition: str | None = None,
    *,
    season: str | None = None,
    match: int | str | None = None,
    competition_id: int | None = None,
    season_id: int | None = None,
    limit: int | None = None,
    three_sixty: bool = True,
    frame: str = "possession",
    pitch: str = "linear",
    events_file: str | Path | None = None,
    three_sixty_file: str | Path | None = None,
    fetcher: Fetcher | None = None,
) -> pd.DataFrame:
    """Load StatsBomb events as canonical events.

    Args:
        competition: human name, e.g. ``"Euro 2024"``. Resolved via :func:`find_competition`.
        season: optional season label to disambiguate a competition name.
        match: a single ``match_id``. Omit to load every match in the competition.
        competition_id, season_id: use StatsBomb ids directly instead of a name.
        limit: cap how many matches are loaded (useful before committing to ~500 MB).
        three_sixty: attach 360 freeze frames to ``extra["freeze_frame"]``.
        frame: ``"possession"`` (default, canonical) mirrors off-possession events so the team
            on the ball always attacks +x; ``"acting"`` keeps StatsBomb's per-team frame.
        pitch: ``"linear"`` (default) rescales 120x80 to 105x68 proportionally, which is what
            mplsoccer, socceraction and kloppy do -- match it and your numbers match theirs.
            ``"landmark"`` instead pins the goal line, boxes, penalty spot and halfway line to
            their real positions, correcting the 5-7% the linear map shrinks the box by.
        events_file, three_sixty_file: read these files instead of downloading, for one match.
    """
    fetcher = fetcher or default_fetcher()

    spec = _pitch_spec(pitch)
    if events_file is not None:
        payload = json.loads(Path(events_file).read_text())
        frames = _load_three_sixty_file(three_sixty_file) if three_sixty_file else {}
        return finish_events(
            _events_frame(
                payload,
                match_id=str(match or Path(events_file).stem),
                competition=competition,
                season=season,
                freeze=frames,
                frame=frame,
                spec=spec,
            )
        )

    if competition_id is None or season_id is None:
        if competition is None:
            raise ValueError("pass competition= (or competition_id= and season_id=)")
        competition_id, season_id = find_competition(competition, season, fetcher=fetcher)

    matches = load_matches(competition_id, season_id, fetcher=fetcher)
    if match is not None:
        matches = matches.loc[matches["match_id"].astype("int64") == int(match)]
        if matches.empty:
            raise LookupError(f"match {match} is not in competition {competition_id}/{season_id}")
    if limit is not None:
        matches = matches.head(limit)

    out = [
        _load_one_match(row, fetcher=fetcher, three_sixty=three_sixty, frame=frame, spec=spec)
        for row in tqdm(matches.to_dict(orient="records"), desc="statsbomb matches", leave=False)
    ]
    return finish_events(concat_events(out))


def _pitch_spec(pitch: str) -> PitchSpec:
    if pitch == "linear":
        return STATSBOMB
    if pitch == "landmark":
        return STATSBOMB_LANDMARK
    raise ValueError(f"unknown pitch {pitch!r}; use 'linear' or 'landmark'")


def _load_one_match(
    row: dict[str, Any],
    *,
    fetcher: Fetcher,
    three_sixty: bool,
    frame: str,
    spec: PitchSpec,
) -> pd.DataFrame:
    match_id = int(row["match_id"])
    payload = fetcher.json(f"{BASE}/events/{match_id}.json", f"statsbomb/events_{match_id}.json")
    freeze: dict[str, dict[str, Any]] = {}
    if three_sixty and str(row.get("match_status_360", "available")) == "available":
        try:
            frames = fetcher.json(
                f"{BASE}/three-sixty/{match_id}.json", f"statsbomb/three-sixty_{match_id}.json"
            )
        except Exception:  # a missing or broken 360 file must not sink the match
            frames = []
        freeze = {f["event_uuid"]: f for f in frames if f.get("event_uuid")}
    return _events_frame(
        payload,
        match_id=str(match_id),
        competition=str(row.get("competition.competition_name") or ""),
        season=str(row.get("season.season_name") or ""),
        freeze=freeze,
        frame=frame,
        spec=spec,
    )


def _load_three_sixty_file(path: str | Path) -> dict[str, dict[str, Any]]:
    payload = json.loads(Path(path).read_text())
    return {f["event_uuid"]: f for f in payload if f.get("event_uuid")}


def _events_frame(
    payload: list[dict[str, Any]],
    *,
    match_id: str,
    competition: str | None,
    season: str | None,
    freeze: dict[str, dict[str, Any]],
    frame: str,
    spec: PitchSpec = STATSBOMB,
) -> pd.DataFrame:
    if frame not in {"possession", "acting"}:
        raise ValueError(f"unknown frame {frame!r}; use 'possession' or 'acting'")
    rows = [
        _event_row(event, match_id, competition, season, freeze, frame, spec)
        for event in payload
    ]
    return pd.DataFrame(rows, columns=list(_EVENT_KEYS))


_EVENT_KEYS = (
    "match_id",
    "competition",
    "season",
    "team_id",
    "team",
    "player_id",
    "player",
    "t",
    "period",
    "type",
    "subtype",
    "x",
    "y",
    "end_x",
    "end_y",
    "outcome",
    "pressure",
    "body_part",
    "extra",
)


def _event_row(
    event: dict[str, Any],
    match_id: str,
    competition: str | None,
    season: str | None,
    freeze: dict[str, dict[str, Any]],
    frame: str,
    spec: PitchSpec,
) -> dict[str, Any]:
    type_name = (event.get("type") or {}).get("name", "")
    key = snake(type_name) or "unknown"
    payload = event.get(_SUBDICT_ALIASES.get(key, key))
    body = payload if isinstance(payload, dict) else {}

    team = event.get("team") or {}
    possession_team = event.get("possession_team") or {}
    mirror = frame == "possession" and team.get("id") != possession_team.get("id")

    x, y = _point(event.get("location"), mirror, spec)
    end_raw = body.get("end_location")
    end_x, end_y = _point(end_raw, mirror, spec)
    end_z = _height(end_raw)

    subtype_name = (body.get("type") or {}).get("name")
    subtype = snake(subtype_name)
    subtype = _SET_PIECES.get(subtype or "", subtype)

    outcome = (body.get("outcome") or {}).get("name")
    if outcome is None and key == "pass" and "pass" in event:
        # StatsBomb omits pass.outcome entirely on a completed pass.
        outcome = "Complete"

    extra = _extra(event, body, key, end_z, freeze, mirror, spec)
    extra.update(_geometry(x, y, end_x, end_y))

    return {
        "match_id": match_id,
        "competition": competition or None,
        "season": season or None,
        "team_id": _as_str(team.get("id")),
        "team": team.get("name"),
        "player_id": _as_str((event.get("player") or {}).get("id")),
        "player": (event.get("player") or {}).get("name"),
        "t": _timestamp_seconds(event.get("timestamp")),
        "period": event.get("period"),
        "type": key,
        "subtype": subtype,
        "x": x,
        "y": y,
        "end_x": end_x,
        "end_y": end_y,
        "outcome": snake(outcome),
        # under_pressure is written only when true; its absence is false, never False.
        "pressure": bool(event.get("under_pressure", False)),
        "body_part": snake((body.get("body_part") or {}).get("name")),
        "extra": encode_extra(extra),
    }


def _extra(
    event: dict[str, Any],
    body: dict[str, Any],
    key: str,
    end_z: float | None,
    freeze: dict[str, dict[str, Any]],
    mirror: bool,
    spec: PitchSpec,
) -> dict[str, Any]:
    extra: dict[str, Any] = {
        "id": event.get("id"),
        "index": event.get("index"),
        "possession": event.get("possession"),
        "possession_team": (event.get("possession_team") or {}).get("name"),
        "play_pattern": snake((event.get("play_pattern") or {}).get("name")),
        "position": (event.get("position") or {}).get("name"),
        "duration": event.get("duration"),
        "minute": event.get("minute"),
        "second": event.get("second"),
        "mirrored": mirror or None,
    }
    for flag in ("counterpress", "off_camera", "out"):
        if event.get(flag):
            extra[flag] = True
    if event.get("related_events"):
        extra["related_events"] = event["related_events"]
    if end_z is not None:
        extra["end_z"] = end_z

    for name, value in body.items():
        if name in _PROMOTED or value is None:
            continue
        if name == "freeze_frame":
            # shot.freeze_frame is richer than the 360 one: it names the players.
            extra["shot_freeze_frame"] = [_shot_player(p, mirror, spec) for p in value]
            continue
        extra[name] = _flatten(value)

    blob = freeze.get(str(event.get("id")))
    if blob:
        extra["freeze_frame"] = [
            _freeze_player(p, mirror, spec) for p in blob.get("freeze_frame") or []
        ]
        extra["visible_area"] = _visible_area(blob.get("visible_area"), mirror, spec)

    return {k: v for k, v in extra.items() if v is not None}


def _geometry(
    x: float | None, y: float | None, end_x: float | None, end_y: float | None
) -> dict[str, float]:
    """``length`` in metres and ``angle`` in radians, on the canonical pitch.

    Recomputed rather than copied: StatsBomb's own ``pass.length``/``pass.angle`` are measured
    in 120x80 units on a y-down axis, and the rescale to 105x68 is anisotropic, so a copied
    value would quietly disagree with the coordinates sitting next to it.
    """
    if x is None or y is None or end_x is None or end_y is None:
        return {}
    dx, dy = end_x - x, end_y - y
    return {"length": math.hypot(dx, dy), "angle": math.atan2(dy, dx)}


def _flatten(value: Any) -> Any:
    """StatsBomb nests every enum as ``{"id": n, "name": s}``; keep just the name."""
    if isinstance(value, dict) and set(value) <= {"id", "name"} and "name" in value:
        return value["name"]
    if isinstance(value, list):
        return [_flatten(v) for v in value]
    return value


def _freeze_player(player: dict[str, Any], mirror: bool, spec: PitchSpec) -> dict[str, Any]:
    x, y = _point(player.get("location"), mirror, spec)
    return {
        "teammate": bool(player.get("teammate", False)),
        "actor": bool(player.get("actor", False)),
        "keeper": bool(player.get("keeper", False)),
        "location": [x, y],
    }


def _shot_player(player: dict[str, Any], mirror: bool, spec: PitchSpec) -> dict[str, Any]:
    x, y = _point(player.get("location"), mirror, spec)
    return {
        "teammate": bool(player.get("teammate", False)),
        "player": (player.get("player") or {}).get("name"),
        "player_id": (player.get("player") or {}).get("id"),
        "position": (player.get("position") or {}).get("name"),
        "location": [x, y],
    }


def _visible_area(area: Any, mirror: bool, spec: PitchSpec) -> list[list[float]] | None:
    """``visible_area`` is a flat ``[x1,y1,x2,y2,...]`` list, not a list of pairs."""
    if not area:
        return None
    pairs = []
    for i in range(0, len(area) - 1, 2):
        x, y = _point([area[i], area[i + 1]], mirror, spec)
        if x is not None and y is not None:
            pairs.append([x, y])
    return pairs or None


def _point(
    location: Any, mirror: bool, spec: PitchSpec = STATSBOMB
) -> tuple[float | None, float | None]:
    if not isinstance(location, (list, tuple)) or len(location) < 2:
        return None, None
    x, y = float(location[0]), float(location[1])
    if mirror:
        x, y = _SB_LENGTH - x, _SB_WIDTH - y
    return spec.to_canonical(x, y)


def _height(location: Any) -> float | None:
    """The third component of ``shot.end_location``, rescaled with the y axis."""
    if not isinstance(location, (list, tuple)) or len(location) < 3:
        return None
    return float(location[2]) * (PITCH_WIDTH / _SB_WIDTH)


def _timestamp_seconds(value: Any) -> float | None:
    """``"HH:MM:SS.mmm"`` -> seconds. The clock restarts at zero every period."""
    if not isinstance(value, str):
        return None
    try:
        hours, minutes, seconds = value.split(":")
        return int(hours) * 3600 + int(minutes) * 60 + float(seconds)
    except (ValueError, TypeError):
        return None


def _as_str(value: Any) -> str | None:
    return None if value is None else str(value)

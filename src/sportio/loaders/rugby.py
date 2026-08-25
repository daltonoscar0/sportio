"""Rugby union play-by-play, from ESPN's public JSON.

**Read this before using it.** There is no open rugby-union event dataset with coordinates.
``rugbypy`` publishes box-score aggregates only (no ball-by-ball table exists in its data repo),
and ESPN's rugby feed carries a *scoring-and-discipline* event list -- tries, conversions,
penalty goals, cards, substitutions -- with a clock, a team and one athlete per event, and

* **no field position of any kind** (a recursive walk of the full summary payload finds no
  coordinate, zone, metre or distance key), and
* **no free-text commentary** (``commentaryAvailable`` is ``false``), so there is nothing to
  derive positions or open-play actions from either.

So ``x``, ``y``, ``end_x``, ``end_y``, ``pressure`` and ``body_part`` are structurally null for
this source, and ``carry, pass, kick, ruck, maul, lineout, scrum, tackle, turnover, knock_on``
never appear. The canonical vocabulary is defined below anyway, so a better feed can be dropped
in without changing anything downstream. See ``docs/schema_notes/rugby.md`` and TODO.md.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pandas as pd

from ..http import Fetcher, default_fetcher
from ..schema import concat_events, encode_extra
from ._common import finish_events

__all__ = [
    "LEAGUES",
    "RUGBY_EVENT_TYPES",
    "load_events",
    "load_rugbypy",
    "load_scoreboard",
]

SITE = "https://site.api.espn.com/apis/site/v2/sports/rugby"
RUGBYDATA = "https://raw.githubusercontent.com/seanyboi/rugbydata/main/data/v3"

#: ESPN site-API league slugs. These are slugs, not ESPN's internal league ids.
LEAGUES: dict[str, int] = {
    "six_nations": 180659,
    "premiership": 267979,
    "rugby_world_cup": 164205,
    "united_rugby_championship": 270559,
    "top_14": 270557,
    "super_rugby": 2009,
}

#: The canonical rugby type vocabulary. Terms marked below are not populated by ESPN.
RUGBY_EVENT_TYPES: tuple[str, ...] = (
    "carry", "pass", "kick", "ruck", "maul", "lineout", "scrum", "tackle",
    "turnover", "knock_on", "penalty", "try", "conversion", "penalty_goal",
    "drop_goal", "card", "substitution",
)

#: ``details[].type.id`` -> ``(type, subtype, outcome)``.
#: Ids 4 and 6 were not observed in the sampled matches; their mapping follows the enum
#: ordering and is flagged as unverified in ``extra["type_mapping"]``.
_TYPE_MAP: dict[str, tuple[str, str | None, str | None]] = {
    "1": ("try", None, "success"),
    "2": ("conversion", None, "success"),
    "3": ("penalty_goal", None, "success"),
    "4": ("drop_goal", None, "success"),
    "5": ("card", "yellow", None),
    "6": ("card", "red", None),
    "7": ("substitution", "off", None),
    "8": ("substitution", "on", None),
}

_UNVERIFIED_TYPE_IDS = frozenset({"4", "6"})

_HALF_SECONDS = 2400.0


# --------------------------------------------------------------------------------------
# discovery
# --------------------------------------------------------------------------------------


def load_scoreboard(
    league: int | str = "six_nations",
    date: str | None = None,
    *,
    scoreboard_file: str | Path | None = None,
    fetcher: Fetcher | None = None,
) -> pd.DataFrame:
    """Matches on one date. ``date`` is ``YYYYMMDD``; ESPN ignores date *ranges*."""
    payload = _scoreboard_payload(league, date, scoreboard_file, fetcher)
    rows = []
    for event in payload.get("events") or []:
        competition = (event.get("competitions") or [{}])[0]
        teams = {c.get("homeAway"): c for c in competition.get("competitors") or []}
        rows.append(
            {
                "event_id": event.get("id"),
                "date": event.get("date"),
                "name": event.get("name"),
                "home": ((teams.get("home") or {}).get("team") or {}).get("displayName"),
                "away": ((teams.get("away") or {}).get("team") or {}).get("displayName"),
                "home_score": (teams.get("home") or {}).get("score"),
                "away_score": (teams.get("away") or {}).get("score"),
                "status": (((event.get("status") or {}).get("type")) or {}).get("name"),
                "plays": len(competition.get("details") or []),
            }
        )
    return pd.DataFrame(rows)


def _scoreboard_payload(
    league: int | str,
    date: str | None,
    scoreboard_file: str | Path | None,
    fetcher: Fetcher | None,
) -> dict[str, Any]:
    if scoreboard_file is not None:
        return json.loads(Path(scoreboard_file).read_text())
    if date is None:
        raise ValueError("pass date='YYYYMMDD' (ESPN rejects date ranges) or scoreboard_file=")
    slug = LEAGUES.get(str(league), league)
    fetcher = fetcher or default_fetcher()
    return fetcher.json(
        f"{SITE}/{slug}/scoreboard?dates={date}", f"espn_rugby/scoreboard_{slug}_{date}.json"
    )


# --------------------------------------------------------------------------------------
# events
# --------------------------------------------------------------------------------------


def load_events(
    event: int | str | None = None,
    *,
    league: int | str = "six_nations",
    date: str | None = None,
    summary_file: str | Path | None = None,
    scoreboard_file: str | Path | None = None,
    fetcher: Fetcher | None = None,
) -> pd.DataFrame:
    """Load ESPN rugby play-by-play as canonical events.

    Args:
        event: an ESPN event (match) id. Loads that match's ``summary``.
        league: league slug or name from :data:`LEAGUES`, used with ``date``.
        date: ``YYYYMMDD``; with no ``event``, loads every match played that day.
        summary_file: read one ``summary`` JSON from disk instead of fetching.
        scoreboard_file: read one ``scoreboard`` JSON from disk instead of fetching. The
            scoreboard's play shape is thinner -- no period, no running score -- and is
            handled, but ``summary`` is the better source.
    """
    if summary_file is not None:
        return finish_events(_from_summary(json.loads(Path(summary_file).read_text())))

    if scoreboard_file is not None or (event is None and date is not None):
        payload = _scoreboard_payload(league, date, scoreboard_file, fetcher)
        frames = [_from_scoreboard_event(e, payload) for e in payload.get("events") or []]
        return finish_events(concat_events(frames))

    if event is None:
        raise ValueError("pass event=<espn event id>, or date='YYYYMMDD'")
    slug = LEAGUES.get(str(league), league)
    fetcher = fetcher or default_fetcher()
    payload = fetcher.json(
        f"{SITE}/{slug}/summary?event={event}", f"espn_rugby/summary_{event}.json"
    )
    return finish_events(_from_summary(payload))


def _from_summary(payload: dict[str, Any]) -> pd.DataFrame:
    header = payload.get("header") or {}
    competition = (header.get("competitions") or [{}])[0]
    match_id = str(header.get("id") or competition.get("id") or "")
    league_name = (header.get("league") or {}).get("name")
    season = (header.get("season") or {}).get("year")
    half = float(
        (((payload.get("format") or {}).get("regulation")) or {}).get("clock") or _HALF_SECONDS
    )
    rosters = _roster_index(payload.get("rosters") or [])
    details = competition.get("details") or []
    return _details_frame(
        details,
        match_id=match_id,
        competition=league_name,
        season=None if season is None else str(season),
        half=half,
        rosters=rosters,
        team_names=_team_names(competition),
    )


def _from_scoreboard_event(event: dict[str, Any], payload: dict[str, Any]) -> pd.DataFrame:
    competition = (event.get("competitions") or [{}])[0]
    league_name = ((payload.get("leagues") or [{}])[0]).get("name")
    season = (event.get("season") or {}).get("year")
    return _details_frame(
        competition.get("details") or [],
        match_id=str(event.get("id") or ""),
        competition=league_name,
        season=None if season is None else str(season),
        half=_HALF_SECONDS,
        rosters={},
        team_names=_team_names(competition),
        infer_period=True,
    )


def _team_names(competition: dict[str, Any]) -> dict[str, str]:
    out: dict[str, str] = {}
    for competitor in competition.get("competitors") or []:
        team = competitor.get("team") or {}
        if team.get("id"):
            out[str(team["id"])] = team.get("displayName") or team.get("name") or ""
    return out


def _roster_index(rosters: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    """Jersey numbers and positions live only in ``$.rosters``; join on ``athlete.id``."""
    out: dict[str, dict[str, Any]] = {}
    for side in rosters:
        for entry in side.get("roster") or []:
            athlete = entry.get("athlete") or {}
            if not athlete.get("id"):
                continue
            out[str(athlete["id"])] = {
                "jersey": entry.get("jersey"),
                "position": (entry.get("position") or {}).get("abbreviation"),
                "starter": entry.get("starter"),
            }
    return out


_EVENT_KEYS = (
    "match_id", "competition", "season", "team_id", "team", "player_id", "player",
    "t", "period", "type", "subtype", "x", "y", "end_x", "end_y", "outcome",
    "pressure", "body_part", "extra",
)


def _details_frame(
    details: list[dict[str, Any]],
    *,
    match_id: str,
    competition: str | None,
    season: str | None,
    half: float,
    rosters: dict[str, dict[str, Any]],
    team_names: dict[str, str],
    infer_period: bool = False,
) -> pd.DataFrame:
    partners = _substitution_partners(details)
    rows = [
        _detail_row(
            detail, i, match_id, competition, season, half, rosters, team_names,
            partners, infer_period,
        )
        for i, detail in enumerate(details)
    ]
    return pd.DataFrame(rows, columns=list(_EVENT_KEYS))


def _detail_row(
    detail: dict[str, Any],
    index: int,
    match_id: str,
    competition: str | None,
    season: str | None,
    half: float,
    rosters: dict[str, dict[str, Any]],
    team_names: dict[str, str],
    partners: dict[int, str],
    infer_period: bool,
) -> dict[str, Any]:
    type_id = str((detail.get("type") or {}).get("id") or "")
    kind, subtype, outcome = _TYPE_MAP.get(type_id, ("unknown", None, None))

    clock = detail.get("clock") or {}
    raw_clock = _float(clock.get("value"))
    # clock.value counts from kickoff and does NOT reset at half time, and first-half added
    # time overruns the nominal boundary, so period comes from period.number wherever it
    # exists. The scoreboard shape omits it, and then the clock is the only signal there is.
    stated = (detail.get("period") or {}).get("number")
    inferred = stated is None and infer_period and raw_clock is not None
    if stated is not None:
        period = int(stated)
    elif inferred:
        period = 1 if raw_clock <= half else 2
    else:
        period = 1
    t = None if raw_clock is None else raw_clock - (period - 1) * half

    athlete = _athlete(detail)
    player_id = _str(athlete.get("id"))
    roster = rosters.get(player_id or "", {})

    team = detail.get("team") or {}
    team_id = _str(team.get("id"))
    team_name = team.get("displayName") or team.get("name") or team_names.get(team_id or "")

    extra = {
        "espn_type_id": type_id or None,
        "espn_type_text": (detail.get("type") or {}).get("text"),
        "order": index,
        "clock_value": raw_clock,
        "clock_display": clock.get("displayValue"),
        "added_clock": _float((detail.get("addedClock") or {}).get("value")),
        "home_score": detail.get("homeScore"),
        "away_score": detail.get("awayScore"),
        "jersey": roster.get("jersey"),
        "position": roster.get("position"),
        "substitution_partner": partners.get(index),
        "type_mapping": "unverified" if type_id in _UNVERIFIED_TYPE_IDS else None,
        # Near half time the clock is genuinely ambiguous, so say when period was guessed.
        "period_inferred": True if inferred else None,
    }

    return {
        "match_id": match_id,
        "competition": competition,
        "season": season,
        "team_id": team_id,
        "team": team_name or None,
        "player_id": player_id,
        "player": athlete.get("displayName") or athlete.get("fullName"),
        "t": t,
        "period": period,
        "type": kind,
        "subtype": subtype,
        # ESPN rugby carries no positional data whatsoever; see the module docstring.
        "x": None,
        "y": None,
        "end_x": None,
        "end_y": None,
        "outcome": outcome,
        "pressure": False,
        "body_part": None,
        "extra": encode_extra({k: v for k, v in extra.items() if v is not None}),
    }


def _athlete(detail: dict[str, Any]) -> dict[str, Any]:
    """``summary`` nests the athlete under ``participants``; ``scoreboard`` uses a flat list."""
    participants = detail.get("participants") or []
    if participants:
        return participants[0].get("athlete") or {}
    involved = detail.get("athletesInvolved") or []
    return involved[0] if involved else {}


def _substitution_partners(details: list[dict[str, Any]]) -> dict[int, str]:
    """Match each ``substitute on`` to the ``player substituted`` it replaces, and vice versa.

    They always share ``(team.id, period.number, clock.value)``. Joining on that is robust to
    two simultaneous substitutions by the same team, which array adjacency is not.
    """
    groups: dict[tuple[str, int, float], dict[str, tuple[int, str]]] = {}
    for i, detail in enumerate(details):
        type_id = str((detail.get("type") or {}).get("id") or "")
        if type_id not in {"7", "8"}:
            continue
        key = (
            str((detail.get("team") or {}).get("id") or ""),
            int(((detail.get("period") or {}).get("number")) or 1),
            _float((detail.get("clock") or {}).get("value")) or 0.0,
        )
        player_id = _str(_athlete(detail).get("id"))
        if player_id is None:
            continue
        groups.setdefault(key, {})[type_id] = (i, player_id)

    partners: dict[int, str] = {}
    for members in groups.values():
        on, off = members.get("8"), members.get("7")
        if on and off:
            partners[on[0]] = off[1]
            partners[off[0]] = on[1]
    return partners


def _float(value: Any) -> float | None:
    try:
        out = float(value)
    except (TypeError, ValueError):
        return None
    return None if out != out else out


def _str(value: Any) -> str | None:
    return None if value is None else str(value)


# --------------------------------------------------------------------------------------
# rugbypy (box scores, for match discovery only)
# --------------------------------------------------------------------------------------


def load_rugbypy(kind: str = "match", key: str | None = None, *, fetcher: Fetcher | None = None):
    """Read one of ``seanyboi/rugbydata``'s parquet tables directly.

    These are **box-score aggregates, not events** -- no timestamp, no sequence, no coordinate.
    They are useful for match discovery and team/player season context only.

    Args:
        kind: ``"competition"``, ``"match"``, ``"player"``, ``"team"``, ``"venue"`` or ``"dates"``.
        key: a match/player/team id, or a ``YYYYMMDD`` date for ``kind="dates"``. Omit for the
            registry table of that kind.

    Requires ``pyarrow``, which sportio does not depend on.
    """
    try:
        import pyarrow  # noqa: F401
    except ImportError as exc:  # pragma: no cover - depends on the caller's env
        raise ImportError(
            "reading rugbydata parquet needs pyarrow: `uv pip install pyarrow`"
        ) from exc

    if kind == "dates":
        if key is None:
            raise ValueError("kind='dates' needs key='YYYYMMDD'")
        rel = f"dates/{key}.parquet"
    elif key is None:
        rel = f"{kind}/{kind}_registry.parquet"
    else:
        rel = f"{kind}/{key}.parquet"

    fetcher = fetcher or default_fetcher()
    path = fetcher.download(f"{RUGBYDATA}/{rel}", f"rugbypy/{rel.replace('/', '_')}")
    return pd.read_parquet(path)

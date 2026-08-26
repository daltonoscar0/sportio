"""SkillCorner open data -- broadcast tracking, plus their derived "dynamic events".

Repo: https://github.com/SkillCorner/opendata (branch ``master``).

Two things bite here and both are handled below:

* the tracking JSONL is stored in **Git LFS**, so ``raw.githubusercontent.com`` hands back a
  133-byte pointer stub instead of data -- the real bytes come from ``media.githubusercontent.com``;
* frames outside live play carry ``period: null`` with an empty ``player_data`` and an all-null
  ``ball_data``, and every match has its own ``match_periods[].start_frame`` (10, 2210, 2300,
  2510 or 4040 depending on the match), so ``t`` must be derived per match, never assumed.

See ``docs/schema_notes/skillcorner.md`` for the full measured schema.
"""

from __future__ import annotations

import json
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

from ..http import Fetcher, default_fetcher
from ..pitch import centered
from ..schema import (
    LINEUP_COLUMNS,
    conform_events,
    conform_lineups,
    conform_tracking,
    encode_extra,
)
from ..transform import flip_events, flip_tracking
from ._common import finish_events, finish_tracking, snake

__all__ = ["MATCH_IDS", "load_events", "load_lineups", "load_matches", "load_tracking"]

RAW = "https://raw.githubusercontent.com/SkillCorner/opendata/master"
MEDIA = "https://media.githubusercontent.com/media/SkillCorner/opendata/master"
LFS_STUB = b"version https://git-lfs.github.com/spec/v1"

FPS = 10.0

#: The ten A-League 2024/25 matches published as of 2025-10.
MATCH_IDS: tuple[int, ...] = (
    1886347,
    1899585,
    1925299,
    1953632,
    1996435,
    2006229,
    2011166,
    2013725,
    2015213,
    2017461,
)

_COMPETITION = "A-League"


# --------------------------------------------------------------------------------------
# metadata
# --------------------------------------------------------------------------------------


def load_matches(*, fetcher: Fetcher | None = None) -> pd.DataFrame:
    """The published match index (id, date, teams, competition/season ids)."""
    fetcher = fetcher or default_fetcher()
    payload = fetcher.json(f"{RAW}/data/matches.json", "skillcorner/matches.json")
    return pd.json_normalize(payload)


def _match_meta(match: int | str, fetcher: Fetcher, path: str | Path | None) -> dict[str, Any]:
    if path is not None:
        return json.loads(Path(path).read_text())
    return fetcher.json(
        f"{RAW}/data/matches/{match}/{match}_match.json",
        f"skillcorner/{match}_match.json",
    )


def _roster(meta: dict[str, Any]) -> dict[int, dict[str, Any]]:
    home_id = (meta.get("home_team") or {}).get("id")
    out: dict[int, dict[str, Any]] = {}
    for player in meta.get("players") or []:
        out[int(player["id"])] = {
            "team": "home" if player.get("team_id") == home_id else "away",
            "jersey": player.get("number"),
            "name": player.get("short_name") or player.get("last_name"),
        }
    return out


def load_lineups(
    match: int | str = MATCH_IDS[0],
    *,
    match_file: str | Path | None = None,
    fetcher: Fetcher | None = None,
) -> pd.DataFrame:
    """Squad list with shirt numbers, roles and minutes played.

    SkillCorner is the easy case: its match metadata already carries a measured
    ``playing_time.total.minutes_played`` per player, so nothing here is inferred and
    ``minutes_estimated`` is always false.
    """
    fetcher = fetcher or default_fetcher()
    meta = _match_meta(match, fetcher, match_file)
    home_id = (meta.get("home_team") or {}).get("id")
    names = {
        home_id: (meta.get("home_team") or {}).get("name"),
        (meta.get("away_team") or {}).get("id"): (meta.get("away_team") or {}).get("name"),
    }
    match_id = str(meta.get("id", match))

    rows = []
    for player in meta.get("players") or []:
        playing = ((player.get("playing_time") or {}).get("total")) or {}
        role = (player.get("player_role") or {}).get("acronym")
        minutes = playing.get("minutes_played")
        rows.append(
            {
                "match_id": match_id,
                "team_id": _str(player.get("team_id")),
                "team": names.get(player.get("team_id")),
                "player_id": _str(player.get("id")),
                "player": player.get("short_name")
                or " ".join(filter(None, (player.get("first_name"), player.get("last_name")))),
                "nickname": player.get("short_name"),
                "jersey": player.get("number"),
                "position": role,
                # start_time is the match clock at which the player came on, so "00:00:00"
                # is a starter and a null means they never played.
                "starter": player.get("start_time") == "00:00:00",
                "on_at_full_time": player.get("end_time") is not None
                and player.get("start_time") is not None,
                "minutes": 0.0 if minutes is None else float(minutes),
                "minutes_estimated": False,
                "yellow_cards": player.get("yellow_card") or 0,
                "red_cards": player.get("red_card") or 0,
                "positions": encode_extra(
                    {"role": player.get("player_role"), "playing_time": player.get("playing_time")}
                ),
            }
        )
    return conform_lineups(pd.DataFrame(rows, columns=list(LINEUP_COLUMNS)))


def _period_starts(meta: dict[str, Any]) -> dict[int, int]:
    return {int(p["period"]): int(p["start_frame"]) for p in meta.get("match_periods") or []}


def _home_sides(meta: dict[str, Any]) -> dict[int, str]:
    sides = meta.get("home_team_side") or []
    return {i + 1: str(side) for i, side in enumerate(sides)}


# --------------------------------------------------------------------------------------
# tracking
# --------------------------------------------------------------------------------------


def load_tracking(
    match: int | str = MATCH_IDS[0],
    *,
    match_file: str | Path | None = None,
    tracking_file: str | Path | None = None,
    max_frames: int | None = None,
    hz: float | None = None,
    velocities: bool = True,
    direction: str = "home_ltr",
    fetcher: Fetcher | None = None,
) -> pd.DataFrame:
    """Load one SkillCorner match as canonical tracking.

    Args:
        match: SkillCorner match id (see :data:`MATCH_IDS`).
        match_file: read metadata from this file instead of downloading it.
        tracking_file: read the JSONL from this file instead of downloading 85 MB.
        max_frames: stop after this many *live* frames -- handy for a quick look.
        hz: resample target; ``None`` keeps the native 10 Hz.
        velocities: fill ``vx``/``vy``.
        direction: ``"home_ltr"`` (default) or ``"raw"``.
    """
    fetcher = fetcher or default_fetcher()
    meta = _match_meta(match, fetcher, match_file)
    roster = _roster(meta)
    starts = _period_starts(meta)
    spec = centered(
        float(meta.get("pitch_length") or 105.0),
        float(meta.get("pitch_width") or 68.0),
        name=f"skillcorner:{match}",
    )
    match_id = str(meta.get("id", match))

    rows: list[dict[str, Any]] = []
    for frame in _iter_frames(match, fetcher, tracking_file, max_frames):
        period = frame.get("period")
        if period is None:
            continue
        period = int(period)
        t = (int(frame["frame"]) - starts.get(period, 0)) / FPS
        common = {"match_id": match_id, "t": t, "period": period, "frame": int(frame["frame"])}

        ball = frame.get("ball_data") or {}
        if ball.get("x") is not None:
            bx, by = spec.to_canonical(float(ball["x"]), float(ball["y"]))
            rows.append(
                {
                    **common,
                    "team": "ball",
                    "player_id": None,
                    "jersey": None,
                    "x": bx,
                    "y": by,
                    "vx": None,
                    "vy": None,
                    "confidence": 1.0 if ball.get("is_detected") else 0.5,
                }
            )
        for player in frame.get("player_data") or []:
            info = roster.get(int(player["player_id"]))
            if info is None or player.get("x") is None:
                continue
            px, py = spec.to_canonical(float(player["x"]), float(player["y"]))
            rows.append(
                {
                    **common,
                    "team": info["team"],
                    "player_id": str(player["player_id"]),
                    "jersey": info["jersey"],
                    "x": px,
                    "y": py,
                    "vx": None,
                    "vy": None,
                    # SkillCorner extrapolates off-camera players; is_detected marks the
                    # ~63% of positions that a camera actually saw.
                    "confidence": 1.0 if player.get("is_detected") else 0.5,
                }
            )

    df = conform_tracking(pd.DataFrame(rows, columns=list(_TRACKING_KEYS)))
    sides = _home_sides(meta)
    if direction == "home_ltr" and sides:
        df = _apply_metadata_direction(df, sides)
        direction = "raw"
    return finish_tracking(df, hz=hz, velocities=velocities, direction=direction)


_TRACKING_KEYS = (
    "match_id",
    "t",
    "period",
    "frame",
    "team",
    "player_id",
    "jersey",
    "x",
    "y",
    "vx",
    "vy",
    "confidence",
)


def _apply_metadata_direction(df: pd.DataFrame, sides: dict[int, str]) -> pd.DataFrame:
    """Flip the periods in which the home team attacks -x, per the match metadata.

    Trusting ``home_team_side`` beats inferring from goalkeeper positions, which is what
    :func:`sportio.transform.normalize_direction` has to do when there is no metadata.
    """
    if df.empty:
        return df
    flip_periods = [p for p, side in sides.items() if side == "right_to_left"]
    if not flip_periods:
        return df
    return flip_tracking(df, df["period"].isin(flip_periods))


def _iter_frames(
    match: int | str,
    fetcher: Fetcher,
    tracking_file: str | Path | None,
    max_frames: int | None,
) -> Iterator[dict[str, Any]]:
    """Yield tracking frames, streaming the 85 MB JSONL rather than loading it whole."""
    if tracking_file is not None:
        with Path(tracking_file).open("rb") as fh:
            _reject_lfs_stub(fh, Path(tracking_file))
            yield from _iter_lines(fh, max_frames)
        return
    name = f"{match}_tracking_extrapolated.jsonl"
    path = fetcher.download(
        f"{MEDIA}/data/matches/{match}/{name}", f"skillcorner/{name}", desc=name
    )
    with path.open("rb") as fh:
        _reject_lfs_stub(fh, path)
        yield from _iter_lines(fh, max_frames)


def _reject_lfs_stub(fh: Any, path: Path) -> None:
    """A pointer stub is 133 bytes of valid text, so nothing downstream would notice it."""
    head = fh.readline()
    fh.seek(0)
    if head.startswith(LFS_STUB):
        raise ValueError(
            f"{path} is a Git LFS pointer, not tracking data. Delete it and re-fetch from "
            "media.githubusercontent.com."
        )


def _iter_lines(fh: Any, max_frames: int | None) -> Iterator[dict[str, Any]]:
    seen = 0
    for line in fh:
        line = line.strip()
        if not line:
            continue
        frame = json.loads(line)
        if frame.get("period") is None:
            continue
        yield frame
        seen += 1
        if max_frames is not None and seen >= max_frames:
            return


# --------------------------------------------------------------------------------------
# dynamic events
# --------------------------------------------------------------------------------------

#: ``event_type`` has only four values; the real action verb lives in ``end_type``.
_END_TYPE_TO_EVENT = {
    "pass": "pass",
    "shot": "shot",
    "clearance": "clearance",
    "possession_loss": "dispossessed",
    "indirect_regain": "recovery",
    "direct_disruption": "duel",
    "foul_committed": "foul_committed",
    "foul_suffered": "foul_won",
}

_PRESSURE_SUBTYPES = frozenset({"pressure", "pressing", "counter_press", "recovery_press"})

#: The one event_type whose acting team is the team *out* of possession -- pressing and
#: engaging the ball carrier. Everything else (player_possession, passing_option,
#: off_ball_run) is an action by the team on the ball.
_OUT_OF_POSSESSION_TYPES = frozenset({"on_ball_engagement"})

#: ``start_type`` is where SkillCorner records the restart that began a possession.
_START_TYPE_TO_SETPIECE = {
    "corner_reception": "corner",
    "throw_in_reception": "throw_in",
    "goal_kick_reception": "goal_kick",
    "free_kick_reception": "free_kick",
    "kick_off_reception": "kick_off",
    "penalty_reception": "penalty",
}


def load_events(
    match: int | str = MATCH_IDS[0],
    *,
    match_file: str | Path | None = None,
    events_file: str | Path | None = None,
    frame: str = "possession",
    fetcher: Fetcher | None = None,
) -> pd.DataFrame:
    """Load SkillCorner's tracking-derived "dynamic events" as canonical events.

    This is Game Intelligence output, not a conventional event feed: ``event_type`` is one of
    ``player_possession``, ``passing_option``, ``off_ball_run``, ``on_ball_engagement``. Where a
    possession ends in a recognisable action the canonical ``type`` becomes that action
    (``pass``, ``shot``, ...); otherwise the SkillCorner type is carried through as-is.

    Args:
        frame: like the StatsBomb loader. SkillCorner already writes each row in the **acting
            team's** attacking frame -- verified by joining ``x_start`` against the tracking
            position of the same player in the same frame, where a ``right_to_left`` row comes
            back negated on both axes. ``"possession"`` (default) additionally rotates the
            out-of-possession rows so the team on the ball always attacks +x, as the canonical
            schema requires; ``"acting"`` leaves every row in its own team's frame.
    """
    if frame not in {"possession", "acting"}:
        raise ValueError(f"unknown frame {frame!r}; use 'possession' or 'acting'")
    fetcher = fetcher or default_fetcher()
    meta = _match_meta(match, fetcher, match_file)
    starts = _period_starts(meta)
    spec = centered(
        float(meta.get("pitch_length") or 105.0),
        float(meta.get("pitch_width") or 68.0),
        name=f"skillcorner:{match}",
    )
    match_id = str(meta.get("id", match))
    season = ((meta.get("competition_edition") or {}).get("season") or {}).get("name", "")
    competition = ((meta.get("competition_edition") or {}).get("competition") or {}).get(
        "name"
    ) or _COMPETITION

    if events_file is not None:
        raw = pd.read_csv(events_file, low_memory=False)
    else:
        name = f"{match}_dynamic_events.csv"
        path = fetcher.download(
            f"{RAW}/data/matches/{match}/{name}", f"skillcorner/{name}", desc=name
        )
        raw = pd.read_csv(path, low_memory=False)

    if raw.empty:
        return finish_events(pd.DataFrame(columns=list(_EVENT_KEYS)))

    rows = [
        _event_row(rec, match_id, competition, season, starts, spec)
        for rec in raw.to_dict(orient="records")
    ]
    out = conform_events(pd.DataFrame(rows, columns=list(_EVENT_KEYS)))
    if frame == "possession":
        event_types = raw.get("event_type")
        mirror = (
            event_types.astype("string").map(snake).isin(_OUT_OF_POSSESSION_TYPES).to_numpy()
            if event_types is not None
            else np.zeros(len(out), dtype=bool)
        )
        out = flip_events(out, mirror)
    return finish_events(out)


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

_EXTRA_COLUMNS = (
    "event_type",
    "event_subtype",
    "end_type",
    "start_type",
    "attacking_side",
    "xthreat",
    "xpass_completion",
    "duration",
    "fully_extrapolated",
    "phase_index",
    "player_position",
    "player_targeted_id",
    "player_targeted_name",
)


def _event_row(
    rec: dict[str, Any],
    match_id: str,
    competition: str,
    season: str,
    starts: dict[int, int],
    spec: Any,
) -> dict[str, Any]:
    period = _int(rec.get("period")) or 1
    frame = _int(rec.get("frame_start"))
    t = (frame - starts.get(period, 0)) / FPS if frame is not None else _float(rec.get("duration"))

    end_type = snake(rec.get("end_type"))
    event_type = snake(rec.get("event_type"))
    kind = _END_TYPE_TO_EVENT.get(end_type or "", event_type) or "unknown"

    subtype = _START_TYPE_TO_SETPIECE.get(snake(rec.get("start_type")) or "")
    if subtype is None:
        subtype = snake(rec.get("event_subtype"))

    x, y = _to_pitch(spec, rec.get("x_start"), rec.get("y_start"))
    end_x, end_y = _to_pitch(spec, rec.get("x_end"), rec.get("y_end"))

    header = rec.get("is_header")
    body_part = "head" if header is True or str(header).lower() == "true" else None
    if str(rec.get("hand_pass")).lower() == "true":
        body_part = "hand"

    return {
        "match_id": match_id,
        "competition": competition,
        "season": season,
        "team_id": _str(rec.get("team_id")),
        "team": _str(rec.get("team_shortname")),
        "player_id": _str(rec.get("player_id")),
        "player": _str(rec.get("player_name")),
        "t": t,
        "period": period,
        "type": kind,
        "subtype": subtype,
        "x": x,
        "y": y,
        "end_x": end_x,
        "end_y": end_y,
        "outcome": snake(rec.get("pass_outcome")),
        "pressure": snake(rec.get("event_subtype")) in _PRESSURE_SUBTYPES,
        "body_part": body_part,
        "extra": encode_extra(
            {
                **{k: _clean(rec.get(k)) for k in _EXTRA_COLUMNS if _clean(rec.get(k)) is not None},
                **({"mirrored": True} if event_type in _OUT_OF_POSSESSION_TYPES else {}),
            }
        ),
    }


def _to_pitch(spec: Any, x: Any, y: Any) -> tuple[float | None, float | None]:
    fx, fy = _float(x), _float(y)
    if fx is None or fy is None:
        return None, None
    return spec.to_canonical(fx, fy)


def _clean(value: Any) -> Any:
    if value is None or (isinstance(value, float) and value != value):
        return None
    if isinstance(value, str) and not value.strip():
        return None
    return value


def _float(value: Any) -> float | None:
    try:
        out = float(value)
    except (TypeError, ValueError):
        return None
    return None if out != out else out


def _int(value: Any) -> int | None:
    out = _float(value)
    return None if out is None else int(out)


def _str(value: Any) -> str | None:
    cleaned = _clean(value)
    if cleaned is None:
        return None
    if isinstance(cleaned, float) and cleaned.is_integer():
        return str(int(cleaned))
    return str(cleaned)

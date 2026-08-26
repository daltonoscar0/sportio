"""Write canonical tracking back out in SkillCorner's current (post-2025-10) open-data shape.

Two files come out, because SkillCorner's tracking is unreadable on its own:

* ``{path}`` -- the JSONL, one frame object per line;
* ``{match_id}_match.json`` beside it -- the roster that says which side each ``player_id``
  is on, the ``match_periods[].start_frame`` that anchors the clock, and the pitch
  dimensions the coordinates are measured against.

The metadata is therefore not decoration: without ``players[].team_id`` every row loads
with no side, and without ``start_frame`` every ``t`` is off by the pre-kickoff frames.

Two conventions are worth stating because they look arbitrary in the output:

* ``home_team_side`` is written as ``left_to_right`` for every period. That is not a guess --
  the canonical frame has already been normalised so home attacks +x throughout, so any
  other value would ask the loader to rotate data that is already the right way round.
* ``pitch_length``/``pitch_width`` are the canonical 105x68, not whatever the original
  stadium measured. The coordinates in the frame have been rescaled onto that pitch and the
  source dimensions are not part of the canonical schema, so 105x68 is what they now mean.
* Coordinates keep full float precision where upstream rounds to 2 decimals. Rounding here
  would put a 5 mm step into every position, and re-reading the file would no longer give
  back the frame that was written.
"""

from __future__ import annotations

import json
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pandas as pd

from ..pitch import PITCH_LENGTH, PITCH_WIDTH, SKILLCORNER

__all__ = ["skillcorner_paths", "to_skillcorner"]

FPS = 10.0

#: SkillCorner's ``timestamp`` is a match clock: period 2 starts at a flat +45:00 however
#: long stoppage time actually ran. Only periods 1 and 2 occur in the published data; the
#: rest follow the same convention (90/105/120 minutes) so the field is never left blank.
_CLOCK_OFFSET = {1: 0.0, 2: 2700.0, 3: 5400.0, 4: 6300.0, 5: 7200.0}

#: The canonical frame carries sides, not team identities, so the two teams are given the
#: smallest ids that keep home and away distinguishable.
_TEAM_IDS = {"home": 1, "away": 2}


def skillcorner_paths(path: str | Path, match_id: str) -> dict[str, Path]:
    """Derive the JSONL and companion metadata paths from a single base path.

    ``out.jsonl`` -> ``out.jsonl`` / ``{match_id}_match.json`` in the same directory.
    """
    path = Path(path)
    if not path.suffix:
        path = path.with_suffix(".jsonl")
    return {"tracking": path, "match": path.with_name(f"{match_id}_match.json")}


def to_skillcorner(tracking: pd.DataFrame, path: str | Path) -> dict[str, Path]:
    """Write a canonical tracking frame as SkillCorner tracking JSONL plus its metadata.

    Args:
        tracking: canonical tracking frame (105x68 metres, home attacking +x).
        path: destination for the JSONL; see :func:`skillcorner_paths` for the companion.

    Returns:
        Mapping of ``"tracking"``/``"match"`` to the files actually written.
    """
    if tracking.empty:
        raise ValueError("refusing to write an empty tracking frame")
    match_ids = set(tracking["match_id"].dropna().unique())
    if len(match_ids) > 1:
        raise ValueError(f"one match per SkillCorner file; got {sorted(match_ids)}")
    if tracking["frame"].isna().any():
        raise ValueError("SkillCorner tracking is keyed by frame number; some rows have none")
    match_id = str(next(iter(match_ids))) if match_ids else "0"

    targets = skillcorner_paths(path, match_id)
    # Built before anything is opened, so an unwritable player id fails without leaving half
    # a tracking file behind.
    meta = _meta(tracking, match_id)

    targets["tracking"].parent.mkdir(parents=True, exist_ok=True)
    with targets["tracking"].open("w") as fh:
        for frame in _frames(tracking):
            fh.write(json.dumps(frame, separators=(",", ":")))
            fh.write("\n")
    targets["match"].write_text(json.dumps(meta, separators=(",", ":")))
    return targets


# --------------------------------------------------------------------------------------
# tracking frames
# --------------------------------------------------------------------------------------


def _frames(tracking: pd.DataFrame) -> Iterator[dict[str, Any]]:
    """One frame object per (period, frame), yielded so a full 59 k-frame match streams out."""
    for (period, frame), block in tracking.groupby(["period", "frame"], sort=True):
        ball = block.loc[block["team"] == "ball"]
        players = block.loc[block["team"].isin(("home", "away")) & block["player_id"].notna()]
        yield {
            "frame": int(frame),
            "timestamp": _timestamp(float(block["t"].iloc[0]), int(period)),
            "period": int(period),
            "ball_data": _ball(ball),
            # Neither the ball carrier nor the team on the ball is part of the canonical
            # tracking schema, so there is nothing honest to put here.
            "possession": {"player_id": None, "group": None},
            "player_data": [_player(row) for row in players.to_dict(orient="records")],
        }


def _ball(ball: pd.DataFrame) -> dict[str, Any]:
    if ball.empty or pd.isna(ball["x"].iloc[0]):
        return {"x": None, "y": None, "z": None, "is_detected": False}
    row = ball.iloc[0]
    x, y = SKILLCORNER.from_canonical(float(row["x"]), float(row["y"]))
    # Ball height has no canonical column, and a fabricated 0.0 would read as "on the deck".
    return {"x": x, "y": y, "z": None, "is_detected": _detected(row["confidence"])}


def _player(row: dict[str, Any]) -> dict[str, Any]:
    x, y = SKILLCORNER.from_canonical(float(row["x"]), float(row["y"]))
    return {
        "x": x,
        "y": y,
        "player_id": _player_id(row["player_id"]),
        "is_detected": _detected(row["confidence"]),
    }


def _detected(confidence: Any) -> bool:
    """SkillCorner extrapolates off-camera players; the loader reads 1.0 as seen, 0.5 as not."""
    return bool(pd.notna(confidence) and float(confidence) >= 1.0)


def _timestamp(t: float, period: int) -> str:
    """Seconds within the period -> ``"HH:MM:SS.ss"`` on SkillCorner's match clock."""
    # Centiseconds, not milliseconds: rounding after the divmod would let 59.999 s print as
    # ":60.00".
    total_cs = round((t + _CLOCK_OFFSET.get(period, 0.0)) * 100.0)
    hours, rest = divmod(total_cs, 360_000)
    minutes, rest = divmod(rest, 6_000)
    return f"{hours:02d}:{minutes:02d}:{rest / 100.0:05.2f}"


# --------------------------------------------------------------------------------------
# companion metadata
# --------------------------------------------------------------------------------------


def _meta(tracking: pd.DataFrame, match_id: str) -> dict[str, Any]:
    periods = _match_periods(tracking)
    last = max((p["period"] for p in periods), default=1)
    return {
        "id": _numeric(match_id),
        "home_team": {"id": _TEAM_IDS["home"], "name": "Home", "short_name": "Home"},
        "away_team": {"id": _TEAM_IDS["away"], "name": "Away", "short_name": "Away"},
        "players": _players(tracking),
        "pitch_length": PITCH_LENGTH,
        "pitch_width": PITCH_WIDTH,
        "match_periods": periods,
        "home_team_side": ["left_to_right"] * last,
    }


def _match_periods(tracking: pd.DataFrame) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for period, block in tracking.groupby("period", sort=True):
        first = block.loc[block["t"].astype("float64").idxmin()]
        # start_frame is recovered from t rather than assumed to be the first frame present:
        # a sliced or resampled frame need not begin on the period's own kickoff.
        start = round(float(first["frame"]) - float(first["t"]) * FPS)
        end = int(block["frame"].max())
        out.append(
            {
                "period": int(period),
                "name": f"period_{int(period)}",
                "start_frame": start,
                "end_frame": end,
                "duration_frames": end - start,
            }
        )
    return out


def _players(tracking: pd.DataFrame) -> list[dict[str, Any]]:
    block = tracking.loc[tracking["team"].isin(("home", "away")) & tracking["player_id"].notna()]
    # Collapsed to one row per identity first: a full match is ~1.3 M tracking rows and ~36
    # players, and the roster only needs the latter.
    seen = block.loc[:, ["team", "player_id", "jersey"]].drop_duplicates()
    out: dict[str, dict[str, Any]] = {}
    for team, player_id, jersey in zip(
        seen["team"], seen["player_id"], seen["jersey"], strict=True
    ):
        entry = out.get(str(player_id))
        if entry is None:
            entry = {"id": _player_id(player_id), "team_id": _TEAM_IDS[str(team)], "number": None}
            out[str(player_id)] = entry
        if entry["number"] is None and pd.notna(jersey):
            entry["number"] = int(jersey)
    return list(out.values())


def _player_id(value: Any) -> int:
    """The canonical string id as the integer SkillCorner keys players by.

    SkillCorner's own loader calls ``int()`` on this value, so a non-numeric canonical id has
    to fail here, loudly, rather than on the way back in.
    """
    text = str(value)
    try:
        return int(text)
    except ValueError as exc:
        raise ValueError(
            f"SkillCorner tracking keys players by integer id; {text!r} cannot be written. "
            "Use sportio.writers.to_csv or to_parquet for sources with named players."
        ) from exc


def _numeric(value: str) -> int | str:
    try:
        return int(value)
    except ValueError:
        return value

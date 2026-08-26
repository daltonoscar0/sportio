"""Fill gaps in an events frame using the matching tracking frame.

Two things event feeds routinely omit are recoverable when you also hold the tracking:

* **where a set piece was taken from.** Metrica records every ``SET PIECE`` row with null
  coordinates -- all 62 of them in game 1, including all 10 corners -- but the ball is right
  there in the tracking at that frame.
* **whether the player was under pressure.** Metrica has no such flag at all, and neither does
  SkillCorner's feed in a directly usable form, but "how far away was the nearest opponent"
  is a measurement, not a judgement call.

Both functions assume ``events`` and ``tracking`` share a coordinate frame **and** a clock. That
is not automatic -- see ``metrica.period_starts`` for the one source where the two clocks differ
by default -- so prefer calling these through a loader's own ``enrich=`` argument, which wires
the two together correctly.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from .setpieces import extra_field

__all__ = [
    "add_pressure_from_tracking",
    "enrich_from_tracking",
    "fill_coordinates_from_tracking",
    "nearest_opponent_distance",
]

#: Beyond this many seconds from a real tracking sample, no position is borrowed.
_MAX_DT = 0.5


def _frame_lookup(tracking: pd.DataFrame) -> dict[tuple[int, int], np.ndarray]:
    keys = ["period", "frame"]
    return tracking.groupby(keys, dropna=True, sort=False).indices


def _time_index(tracking: pd.DataFrame) -> dict[int, tuple[np.ndarray, np.ndarray]]:
    """Per period, the sorted distinct sample times and the frame number at each."""
    out: dict[int, tuple[np.ndarray, np.ndarray]] = {}
    for period, block in tracking.groupby("period", dropna=True, sort=False):
        pairs = (
            block.loc[:, ["t", "frame"]]
            .dropna()
            .drop_duplicates(subset="frame")
            .sort_values("t")
        )
        out[int(period)] = (
            pairs["t"].astype("float64").to_numpy(),
            pairs["frame"].astype("int64").to_numpy(),
        )
    return out


def _event_frames(events: pd.DataFrame, tracking: pd.DataFrame) -> np.ndarray:
    """The tracking frame each event belongs to, as float (NaN where unmatched).

    Uses the source's own frame reference when the loader preserved one, because that is exact;
    otherwise falls back to the nearest sample in time within the same period.
    """
    stated = pd.to_numeric(extra_field(events, "start_frame"), errors="coerce")
    # to_numpy can hand back a read-only view of the backing array; this gets written to.
    out = np.array(stated.to_numpy(dtype="float64"), copy=True)

    times = _time_index(tracking)
    periods = events["period"].astype("Int64").to_numpy()
    event_t = events["t"].astype("float64").to_numpy()

    missing = np.isnan(out)
    for i in np.flatnonzero(missing):
        period = periods[i]
        if period is pd.NA or np.isnan(event_t[i]):
            continue
        index = times.get(int(period))
        if index is None:
            continue
        sample_t, frames = index
        pos = int(np.clip(np.searchsorted(sample_t, event_t[i]), 0, sample_t.size - 1))
        # searchsorted lands on the sample after the event; the one before may be nearer.
        candidates = [pos] if pos == 0 else [pos - 1, pos]
        best = min(candidates, key=lambda j: abs(sample_t[j] - event_t[i]))
        if abs(sample_t[best] - event_t[i]) <= _MAX_DT:
            out[i] = frames[best]
    return out


def fill_coordinates_from_tracking(
    events: pd.DataFrame,
    tracking: pd.DataFrame,
    *,
    only_missing: bool = True,
) -> pd.DataFrame:
    """Give events with no location the ball's position at their frame.

    Args:
        only_missing: leave rows that already have coordinates alone. Turning this off
            overwrites every row from the ball, which is a good way to check the two frames
            really are in sync and a bad way to keep the vendor's own numbers.
    """
    out = events.copy()
    if events.empty or tracking.empty:
        return out

    ball = tracking.loc[tracking["team"] == "ball"]
    if ball.empty:
        return out
    ball_at = (
        ball.dropna(subset=["frame"])
        .drop_duplicates(subset=["period", "frame"])
        .set_index(["period", "frame"])
    )

    frames = _event_frames(events, tracking)
    target = out["x"].isna() if only_missing else pd.Series(True, index=out.index)

    xs = out["x"].astype("Float64").to_numpy(dtype="object")
    ys = out["y"].astype("Float64").to_numpy(dtype="object")
    periods = out["period"].astype("Int64").to_numpy()
    filled = 0
    for i in np.flatnonzero(target.to_numpy()):
        if np.isnan(frames[i]) or periods[i] is pd.NA:
            continue
        try:
            row = ball_at.loc[(int(periods[i]), int(frames[i]))]
        except KeyError:
            continue
        if pd.isna(row["x"]):
            continue
        xs[i], ys[i] = float(row["x"]), float(row["y"])
        filled += 1

    out["x"] = pd.array(xs, dtype="Float64")
    out["y"] = pd.array(ys, dtype="Float64")
    return out


def nearest_opponent_distance(
    events: pd.DataFrame,
    tracking: pd.DataFrame,
    *,
    sides: dict[str, str] | None = None,
) -> pd.Series:
    """Metres from the acting player to the closest opponent, at the event's frame.

    ``<NA>`` where the actor is not identifiable in the tracking at that moment -- which is the
    honest answer, and is why this is separate from the boolean that consumes it.
    """
    if events.empty or tracking.empty:
        return pd.Series(pd.NA, index=events.index, dtype="Float64")

    frames = _event_frames(events, tracking)
    lookup = _frame_lookup(tracking)
    # Empty string as the missing sentinel: the ball has no player_id, and comparing an
    # object array that still contains pd.NA raises rather than returning False.
    track_team = tracking["team"].astype("string").fillna("").to_numpy(dtype=object)
    track_player = tracking["player_id"].astype("string").fillna("").to_numpy(dtype=object)
    track_x = tracking["x"].astype("float64").to_numpy()
    track_y = tracking["y"].astype("float64").to_numpy()

    side_of = _sides(events, sides)
    actors = events["player_id"].astype("string").fillna("").to_numpy(dtype=object)
    periods = events["period"].astype("Int64").to_numpy()

    out = np.full(len(events), np.nan)
    for i in range(len(events)):
        side = side_of[i]
        if side is None or not actors[i] or np.isnan(frames[i]) or periods[i] is pd.NA:
            continue
        rows = lookup.get((int(periods[i]), int(frames[i])))
        if rows is None:
            continue
        here_player = track_player[rows]
        actor_rows = rows[here_player == actors[i]]
        if actor_rows.size == 0:
            continue
        ax, ay = track_x[actor_rows[0]], track_y[actor_rows[0]]
        if np.isnan(ax) or np.isnan(ay):
            continue
        opponent = "away" if side == "home" else "home"
        opponents = rows[track_team[rows] == opponent]
        if opponents.size == 0:
            continue
        distances = np.hypot(track_x[opponents] - ax, track_y[opponents] - ay)
        if np.all(np.isnan(distances)):
            continue
        out[i] = float(np.nanmin(distances))

    return pd.Series(out, index=events.index, dtype="Float64")


def _sides(events: pd.DataFrame, sides: dict[str, str] | None) -> list[str | None]:
    team_id = events["team_id"].astype("string")
    if sides:
        mapping = {str(k): v for k, v in sides.items()}
        resolved = team_id.map(mapping)
    else:
        lowered = team_id.str.lower()
        resolved = lowered.where(lowered.isin(("home", "away")))
    return [None if pd.isna(v) else str(v) for v in resolved]


def add_pressure_from_tracking(
    events: pd.DataFrame,
    tracking: pd.DataFrame,
    *,
    radius: float = 3.0,
    sides: dict[str, str] | None = None,
    overwrite: bool = False,
) -> pd.DataFrame:
    """Set ``pressure`` where an opponent was within ``radius`` metres of the actor.

    The distance itself is kept in ``extra["opponent_distance"]``, because a boolean throws away
    the thing most consumers actually want to threshold themselves.

    Args:
        radius: metres. 3 m is the usual "engaged" distance; StatsBomb's own under_pressure is
            roughly a 5 m cone, so tune this if you are trying to match that feed.
        overwrite: replace a flag the source already supplied instead of only filling gaps.
    """
    out = events.copy()
    if events.empty or tracking.empty:
        return out

    distance = nearest_opponent_distance(events, tracking, sides=sides)
    pressured = (distance <= radius).fillna(False)

    if overwrite:
        out["pressure"] = pressured.astype("boolean")
    else:
        existing = out["pressure"].astype("boolean").fillna(False)
        out["pressure"] = (existing | pressured).astype("boolean")

    out["extra"] = _merge_extra(out["extra"], "opponent_distance", distance)
    return out


def _merge_extra(extra: pd.Series, key: str, values: pd.Series) -> pd.Series:
    import json

    merged = []
    for blob, value in zip(extra.astype("string").fillna("{}"), values, strict=True):
        try:
            payload = json.loads(blob)
        except json.JSONDecodeError:  # pragma: no cover - conform_events guarantees valid JSON
            payload = {}
        if not pd.isna(value):
            payload[key] = round(float(value), 3)
        merged.append(json.dumps(payload, separators=(",", ":"), sort_keys=True))
    return pd.Series(merged, index=extra.index, dtype="string")


def enrich_from_tracking(
    events: pd.DataFrame,
    tracking: pd.DataFrame,
    *,
    coordinates: bool = True,
    pressure: bool = True,
    radius: float = 3.0,
    sides: dict[str, str] | None = None,
) -> pd.DataFrame:
    """Both enrichments in the order that matters: positions first, then pressure."""
    out = events
    if coordinates:
        out = fill_coordinates_from_tracking(out, tracking)
    if pressure:
        out = add_pressure_from_tracking(out, tracking, radius=radius, sides=sides)
    return out

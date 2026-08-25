"""Convenience slices over a canonical events frame.

Loaders normalise every set-piece marker into ``events.subtype``, so these helpers work
identically whatever vendor the rows came from.
"""

from __future__ import annotations

import json
from collections.abc import Iterable

import numpy as np
import pandas as pd

__all__ = [
    "SET_PIECE_SUBTYPES",
    "corners",
    "extra_field",
    "freeze_frame_size",
    "freeze_frames",
    "set_pieces",
]

#: Canonical set-piece markers written into ``events.subtype`` by every loader.
SET_PIECE_SUBTYPES: frozenset[str] = frozenset(
    {"corner", "free_kick", "throw_in", "goal_kick", "kick_off", "penalty", "lineout", "scrum"}
)


def extra_field(ev: pd.DataFrame, key: str) -> pd.Series:
    """Pull one key out of the JSON-encoded ``extra`` column as an object Series."""
    return ev["extra"].map(lambda blob: _get(blob, key))


def _get(blob: object, key: str) -> object:
    if not isinstance(blob, str) or not blob:
        return None
    try:
        return json.loads(blob).get(key)
    except (json.JSONDecodeError, AttributeError):
        return None


def set_pieces(
    ev: pd.DataFrame,
    kinds: Iterable[str] | None = None,
    *,
    window: float = 0.0,
) -> pd.DataFrame:
    """Rows whose ``subtype`` is a set piece.

    Args:
        kinds: restrict to these subtypes (default: every entry of :data:`SET_PIECE_SUBTYPES`).
        window: also include events occurring within this many seconds after each set piece,
            in the same match and period -- the usual way to grab a whole delivery sequence.
    """
    wanted = SET_PIECE_SUBTYPES if kinds is None else {k.strip().lower() for k in kinds}
    unknown = wanted - SET_PIECE_SUBTYPES
    if unknown:
        raise ValueError(f"unknown set-piece kinds: {sorted(unknown)}")

    subtype = ev["subtype"].astype("string").str.lower()
    seeds = ev.loc[subtype.isin(wanted)]
    if window <= 0 or seeds.empty:
        return seeds.reset_index(drop=True)
    return _expand_window(ev, seeds, window)


def _expand_window(ev: pd.DataFrame, seeds: pd.DataFrame, window: float) -> pd.DataFrame:
    """Union of ``[start, start + window]`` around every seed, per match and period."""
    keep = np.zeros(len(ev), dtype=bool)
    times = ev["t"].astype("float64").to_numpy()
    match_ids, periods = ev["match_id"], ev["period"]

    # Matching on values rather than groupby keys, because a null key is spelled differently
    # on the two sides (pandas hands back float('nan') from .indices and pd.NA from a group
    # key), and a mismatch would silently drop every set piece in that group.
    for (match_id, period), seed_block in seeds.groupby(["match_id", "period"], dropna=False):
        rows = np.flatnonzero(_matches(match_ids, match_id) & _matches(periods, period))
        if rows.size == 0:
            continue
        order = np.argsort(times[rows], kind="stable")
        rows, block_times = rows[order], times[rows][order]
        for start in seed_block["t"].astype("float64"):
            lo = int(np.searchsorted(block_times, start, side="left"))
            hi = int(np.searchsorted(block_times, start + window, side="right"))
            keep[rows[lo:hi]] = True

    out = ev.loc[keep].sort_values(["match_id", "period", "t"], kind="stable")
    return out.reset_index(drop=True)


def _matches(values: pd.Series, wanted: object) -> np.ndarray:
    """Boolean mask for ``values == wanted``, with NA compared by identity, not equality."""
    if pd.isna(wanted):
        return values.isna().to_numpy(dtype=bool)
    return values.eq(wanted).fillna(False).to_numpy(dtype=bool)


def corners(
    ev: pd.DataFrame, *, window: float = 0.0, with_freeze_frame: bool = False
) -> pd.DataFrame:
    """Corner deliveries (and optionally the seconds that follow).

    Args:
        window: seconds of follow-on play to include after each corner.
        with_freeze_frame: drop rows that carry no 360 freeze frame in ``extra``.
    """
    out = set_pieces(ev, ["corner"], window=window)
    if with_freeze_frame and not out.empty:
        out = out.loc[freeze_frame_size(out) > 0].reset_index(drop=True)
    return out


def freeze_frame_size(ev: pd.DataFrame) -> pd.Series:
    """Number of players in each row's 360 freeze frame (0 when there is none)."""
    frames = extra_field(ev, "freeze_frame")
    return frames.map(lambda ff: len(ff) if isinstance(ff, list) else 0).astype("int64")


def freeze_frames(ev: pd.DataFrame) -> pd.DataFrame:
    """Explode 360 freeze frames into one row per tracked player.

    Columns: ``match_id, period, t, event_id, type, subtype, team, teammate, actor,
    keeper, x, y`` -- with ``x``/``y`` already on the canonical 105x68 pitch.
    """
    rows: list[dict[str, object]] = []
    payloads = extra_field(ev, "freeze_frame")
    event_ids = extra_field(ev, "id")
    for (_, row), players, event_id in zip(ev.iterrows(), payloads, event_ids, strict=True):
        if not isinstance(players, list):
            continue
        for player in players:
            if not isinstance(player, dict):
                continue
            location = player.get("location") or [None, None]
            rows.append(
                {
                    "match_id": row["match_id"],
                    "period": row["period"],
                    "t": row["t"],
                    "event_id": event_id,
                    "type": row["type"],
                    "subtype": row["subtype"],
                    "team": row["team"],
                    "teammate": player.get("teammate"),
                    "actor": bool(player.get("actor", False)),
                    "keeper": bool(player.get("keeper", False)),
                    "x": location[0] if len(location) > 0 else None,
                    "y": location[1] if len(location) > 1 else None,
                }
            )
    if not rows:
        return pd.DataFrame(
            columns=[
                "match_id", "period", "t", "event_id", "type", "subtype",
                "team", "teammate", "actor", "keeper", "x", "y",
            ]
        )
    out = pd.DataFrame(rows)
    out["teammate"] = out["teammate"].astype("boolean")
    out["x"] = pd.to_numeric(out["x"], errors="coerce").astype("Float64")
    out["y"] = pd.to_numeric(out["y"], errors="coerce").astype("Float64")
    return out

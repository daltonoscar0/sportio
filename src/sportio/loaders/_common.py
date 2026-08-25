"""Helpers every loader shares, so the canonical guarantees are made in exactly one place."""

from __future__ import annotations

import re
from collections.abc import Mapping

import pandas as pd

from ..schema import conform_events, conform_tracking
from ..transform import add_velocities, native_hz, normalize_direction, resample_tracking

__all__ = ["finish_events", "finish_tracking", "snake"]

_NON_WORD = re.compile(r"[^a-z0-9]+")


def snake(value: object, mapping: Mapping[str, str] | None = None) -> str | None:
    """Normalise a vendor label to lowercase snake_case, optionally through a synonym map.

    ``"Throw-in"`` -> ``"throw_in"``, ``"BALL LOST"`` -> ``"ball_lost"``, ``None`` -> ``None``.
    """
    if value is None or (isinstance(value, float) and value != value):
        return None
    text = _NON_WORD.sub("_", str(value).strip().lower()).strip("_")
    if not text:
        return None
    if mapping:
        return mapping.get(text, text)
    return text


def finish_events(df: pd.DataFrame) -> pd.DataFrame:
    """Conform, sort and hand back an events frame ready to leave the library."""
    out = conform_events(df)
    return out.sort_values(["match_id", "period", "t"], kind="stable").reset_index(drop=True)


def finish_tracking(
    df: pd.DataFrame,
    *,
    hz: float | None = None,
    velocities: bool = True,
    direction: str = "home_ltr",
    smooth: int = 7,
) -> pd.DataFrame:
    """Conform, optionally resample, normalise direction of play and fill velocities.

    Args:
        hz: target sampling rate. ``None`` keeps the source rate when it already meets the
            canonical 10 Hz minimum, and upsamples to 10 Hz when it does not.
        velocities: fill ``vx``/``vy`` by differentiating the (possibly resampled) track.
        direction: ``"home_ltr"`` flips whole periods so the home team always attacks +x;
            ``"raw"`` leaves the source geometry alone.
        smooth: moving-average window, in frames, for the velocity estimate.
    """
    out = conform_tracking(df)
    if out.empty:
        return out

    target = hz
    if target is None:
        rate = native_hz(out)
        target = 10.0 if rate is not None and rate < 10.0 - 1e-6 else None
    if target is not None:
        out = resample_tracking(out, hz=target)

    out = normalize_direction(out, convention=direction)  # type: ignore[arg-type]
    if velocities:
        out = add_velocities(out, smooth=smooth)
    order = ["match_id", "period", "t", "team", "player_id"]
    return out.sort_values(order, kind="stable").reset_index(drop=True)

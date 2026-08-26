"""Operations on canonical tracking frames: resampling, velocities, direction of play.

Time convention (both canonical frames): ``t`` is **seconds since the start of the
current period**, so ``(period, t)`` orders a match unambiguously without anyone having
to know how long the previous period ran.
"""

from __future__ import annotations

from typing import Literal

import numpy as np
import pandas as pd

from .pitch import PITCH_LENGTH, PITCH_WIDTH
from .schema import conform_tracking

__all__ = [
    "add_velocities",
    "flip_events",
    "flip_tracking",
    "native_hz",
    "normalize_direction",
    "resample_tracking",
]

_ENTITY = ["team", "player_id"]


def native_hz(df: pd.DataFrame) -> float | None:
    """Estimate the sampling rate of a tracking frame from its modal frame interval."""
    if df.empty:
        return None
    times = np.sort(df["t"].astype("float64").dropna().unique())
    if times.size < 3:
        return None
    deltas = np.diff(times)
    deltas = deltas[(deltas > 1e-6) & (deltas < 5.0)]
    if deltas.size == 0:
        return None
    # Modal delta, bucketed to 1e-4 s, is robust to the odd dropped frame.
    values, counts = np.unique(np.round(deltas, 4), return_counts=True)
    step = float(values[int(np.argmax(counts))])
    return round(1.0 / step, 3) if step > 0 else None


def resample_tracking(
    df: pd.DataFrame,
    hz: float = 10.0,
    *,
    max_gap: float = 0.5,
    method: str = "linear",
) -> pd.DataFrame:
    """Resample onto a uniform ``hz`` grid, per period.

    Samples further than ``max_gap`` seconds from a real observation are left as NaN
    rather than invented, which matters for broadcast tracking where players leave frame.

    Args:
        method: ``"linear"`` (default) or ``"pchip"``. Linear interpolation puts a corner at
            every observation, so differentiating it gives a velocity that jumps between
            constants. ``"pchip"`` fits a shape-preserving cubic instead, which is smoother
            through an occlusion and -- unlike a natural spline -- cannot overshoot past the
            surrounding observations and invent a position off the pitch.
    """
    if method not in {"linear", "pchip"}:
        raise ValueError(f"unknown method {method!r}; use 'linear' or 'pchip'")
    if df.empty:
        return df
    if hz <= 0:
        raise ValueError("hz must be positive")

    out: list[pd.DataFrame] = []
    step = 1.0 / hz
    frame_offset = 0
    for period, block in df.sort_values(["period", "t"]).groupby("period", sort=True):
        t = block["t"].astype("float64")
        grid = np.arange(float(t.min()), float(t.max()) + step / 2.0, step)
        if grid.size == 0:
            continue
        pieces = []
        for (team, player_id), track in block.groupby(_ENTITY, dropna=False, sort=False):
            pieces.append(_resample_track(track, grid, team, player_id, max_gap, method))
        block_df = pd.concat(pieces, ignore_index=True)
        block_df["period"] = period
        block_df["frame"] = frame_offset + np.tile(
            np.arange(grid.size), len(block_df) // grid.size if grid.size else 1
        )
        frame_offset += grid.size
        out.append(block_df)

    if not out:
        return df.iloc[0:0]
    resampled = pd.concat(out, ignore_index=True)
    resampled = resampled.dropna(subset=["x", "y"], how="all")
    resampled = conform_tracking(resampled)
    order = ["period", "t", "team", "player_id"]
    return resampled.sort_values(order, kind="stable").reset_index(drop=True)


def _resample_track(
    track: pd.DataFrame,
    grid: np.ndarray,
    team: str,
    player_id: object,
    max_gap: float,
    method: str,
) -> pd.DataFrame:
    track = track.sort_values("t")
    ts = track["t"].astype("float64").to_numpy()
    piece = pd.DataFrame({"t": grid})
    piece["match_id"] = track["match_id"].iloc[0]
    piece["team"] = team
    piece["player_id"] = player_id
    piece["jersey"] = track["jersey"].iloc[0]

    for col in ("x", "y", "confidence"):
        values = track[col].astype("float64").to_numpy()
        # confidence is a flag, not a trajectory, so it is never smoothed.
        how = "linear" if col == "confidence" else method
        piece[col] = _interp_with_gaps(grid, ts, values, max_gap, how)
    piece["vx"] = np.nan
    piece["vy"] = np.nan
    return piece


def _interp_with_gaps(
    grid: np.ndarray,
    ts: np.ndarray,
    values: np.ndarray,
    max_gap: float,
    method: str = "linear",
) -> np.ndarray:
    ok = ~np.isnan(values)
    if ok.sum() == 0:
        return np.full(grid.shape, np.nan)
    ts_ok, v_ok = ts[ok], values[ok]
    if method == "pchip" and ts_ok.size >= 3:
        out = _pchip(grid, ts_ok, v_ok)
    else:
        out = np.interp(grid, ts_ok, v_ok, left=np.nan, right=np.nan)
    # Blank out grid points that sit inside a gap longer than max_gap.
    idx = np.searchsorted(ts_ok, grid)
    left = np.clip(idx - 1, 0, ts_ok.size - 1)
    right = np.clip(idx, 0, ts_ok.size - 1)
    span = ts_ok[right] - ts_ok[left]
    # A grid point sitting exactly on a real observation is not inside anything; only blank
    # points that genuinely fall in the interior of an over-long gap.
    on_sample = (grid == ts_ok[left]) | (grid == ts_ok[right])
    out[(span > max_gap) & ~on_sample] = np.nan
    return out


def _pchip(grid: np.ndarray, x: np.ndarray, y: np.ndarray) -> np.ndarray:
    """Shape-preserving piecewise cubic Hermite interpolation (Fritsch-Carlson slopes).

    Written out rather than taken from scipy, which sportio does not depend on. The point of
    choosing this over a natural cubic spline is monotonicity: between two observations the
    curve stays within their range, so a smoothed track can never place a player somewhere
    neither of the surrounding frames saw them.
    """
    h = np.diff(x)
    delta = np.diff(y) / h
    n = x.size
    slopes = np.zeros(n, dtype="float64")

    # Interior slopes: a weighted harmonic mean, forced to zero at a local extremum so the
    # curve turns without overshooting.
    left, right = delta[:-1], delta[1:]
    h_left, h_right = h[:-1], h[1:]
    w1 = 2.0 * h_right + h_left
    w2 = h_right + 2.0 * h_left
    with np.errstate(divide="ignore", invalid="ignore"):
        harmonic = (w1 + w2) / (w1 / left + w2 / right)
    slopes[1:-1] = np.where(left * right > 0.0, harmonic, 0.0)
    slopes[np.isnan(slopes)] = 0.0

    far_h = h[1] if n > 2 else h[0]
    far_d = delta[1] if n > 2 else delta[0]
    slopes[0] = _edge_slope(h[0], far_h, delta[0], far_d)
    slopes[-1] = _edge_slope(h[-1], h[-2], delta[-1], delta[-2])

    idx = np.clip(np.searchsorted(x, grid, side="right") - 1, 0, n - 2)
    dx = x[idx + 1] - x[idx]
    s = (grid - x[idx]) / dx
    s2, s3 = s * s, s * s * s
    out = (
        y[idx] * (2.0 * s3 - 3.0 * s2 + 1.0)
        + slopes[idx] * dx * (s3 - 2.0 * s2 + s)
        + y[idx + 1] * (-2.0 * s3 + 3.0 * s2)
        + slopes[idx + 1] * dx * (s3 - s2)
    )
    out[(grid < x[0]) | (grid > x[-1])] = np.nan
    return out


def _edge_slope(h0: float, h1: float, d0: float, d1: float) -> float:
    """One-sided endpoint slope, clipped so the end segment cannot overshoot either."""
    slope = ((2.0 * h0 + h1) * d0 - h0 * d1) / (h0 + h1)
    if slope * d0 <= 0.0:
        return 0.0
    if abs(slope) > 3.0 * abs(d0):
        return 3.0 * d0
    return float(slope)


def add_velocities(
    df: pd.DataFrame,
    *,
    smooth: int = 7,
    max_speed: float = 12.0,
    max_gap: float = 1.0,
) -> pd.DataFrame:
    """Fill ``vx``/``vy`` by differencing each track, with a moving-average smooth.

    Args:
        smooth: window length in frames for the moving average; ``<= 1`` disables it.
        max_speed: speeds above this (m/s) are treated as tracking glitches and dropped.
        max_gap: no velocity is emitted across a time gap longer than this (seconds).
            Grouping by period alone is not enough -- a truncated file, a substitution or a
            stretch of lost tracking leaves a hole *inside* a period, and differencing
            across it manufactures a several-hundred-m/s spike.
    """
    if df.empty:
        return df
    df = df.sort_values(["period", *_ENTITY, "t"], kind="stable").copy()
    keys = ["period", *_ENTITY]
    grouped = df.groupby(keys, dropna=False, sort=False)

    dt = grouped["t"].diff().astype("float64")
    vx = grouped["x"].diff().astype("float64") / dt
    vy = grouped["y"].diff().astype("float64") / dt

    speed = np.hypot(vx.to_numpy(dtype="float64"), vy.to_numpy(dtype="float64"))
    bad = (speed > max_speed) | (dt > max_gap)
    vx = vx.mask(bad)
    vy = vy.mask(bad)

    if smooth > 1:
        vx = _smooth(df, keys, vx, smooth)
        vy = _smooth(df, keys, vy, smooth)

    df["vx"] = vx.astype("Float64")
    df["vy"] = vy.astype("Float64")
    return conform_tracking(df).reset_index(drop=True)


def _smooth(df: pd.DataFrame, keys: list[str], values: pd.Series, window: int) -> pd.Series:
    tmp = df[keys].copy()
    tmp["_v"] = values.to_numpy(dtype="float64")
    rolled = tmp.groupby(keys, dropna=False, sort=False)["_v"].transform(
        lambda s: s.rolling(window, center=True, min_periods=1).mean()
    )
    return rolled


# --------------------------------------------------------------------------------------
# direction of play
# --------------------------------------------------------------------------------------


def flip_tracking(df: pd.DataFrame, mask: pd.Series | np.ndarray | None = None) -> pd.DataFrame:
    """Rotate the selected rows 180 degrees about the centre spot (positions and velocities)."""
    df = df.copy()
    if mask is None:
        mask = pd.Series(True, index=df.index)
    df.loc[mask, "x"] = PITCH_LENGTH - df.loc[mask, "x"]
    df.loc[mask, "y"] = PITCH_WIDTH - df.loc[mask, "y"]
    df.loc[mask, "vx"] = -df.loc[mask, "vx"]
    df.loc[mask, "vy"] = -df.loc[mask, "vy"]
    return df


def flip_events(df: pd.DataFrame, mask: pd.Series | np.ndarray | None = None) -> pd.DataFrame:
    """Rotate the selected event rows 180 degrees about the centre spot."""
    df = df.copy()
    if mask is None:
        mask = pd.Series(True, index=df.index)
    for xc, yc in (("x", "y"), ("end_x", "end_y")):
        df.loc[mask, xc] = PITCH_LENGTH - df.loc[mask, xc]
        df.loc[mask, yc] = PITCH_WIDTH - df.loc[mask, yc]
    return df


def attacking_sign(df: pd.DataFrame, team: str = "home") -> dict[int, int]:
    """Per period, ``+1`` if ``team`` attacks toward +x, ``-1`` otherwise.

    Both goalkeepers are found at once: across *both* teams, the player with the lowest mean
    x is the keeper defending the left goal and the one with the highest is defending the
    right. Whichever team owns the leftmost player is attacking toward +x.

    Looking at one team in isolation does not work -- a keeper playing a high line while his
    own winger camps on the opposite byline is more "central" than that winger, and a
    single-team heuristic then picks the wrong end.
    """
    signs: dict[int, int] = {}
    mid = PITCH_LENGTH / 2.0
    players = df.loc[df["team"].isin(("home", "away")) & df["player_id"].notna()]
    for period, block in players.groupby("period", sort=True):
        means = block.groupby(["team", "player_id"], dropna=True)["x"].mean().astype("float64")
        means = means.dropna()
        if means.empty:
            signs[int(period)] = 1
            continue
        left_team = str(means.idxmin()[0])
        right_team = str(means.idxmax()[0])
        if left_team != right_team:
            signs[int(period)] = 1 if left_team == team else -1
            continue
        # Only one side is present (or both keepers are on the same flank of the data);
        # fall back to which half that side's most extreme player occupies.
        lo, hi = float(means.min()), float(means.max())
        keeper_x = lo if (mid - lo) >= (hi - mid) else hi
        own = 1 if left_team == team else -1
        signs[int(period)] = own * (1 if keeper_x < mid else -1)
    return signs


def normalize_direction(
    df: pd.DataFrame,
    *,
    convention: Literal["home_ltr", "raw", "possession"] = "home_ltr",
    spans: pd.DataFrame | None = None,
) -> pd.DataFrame:
    """Rotate whole periods, or whole possessions, so the right team attacks toward +x.

    Args:
        convention:
            ``"home_ltr"`` (default) flips periods so the **home** team always attacks +x.
            ``"raw"`` returns ``df`` untouched, for callers who need the source geometry.
            ``"possession"`` additionally rotates each away-team possession, so the team **on
            the ball** always attacks +x -- the same convention canonical *events* already use,
            which is what you want when comparing the two.
        spans: required by ``"possession"``. Build it with
            :func:`sportio.possession.possession_spans`; columns ``match_id, period, start_t,
            end_t, side``. Frames not covered by any span keep the home-attacks-+x orientation,
            because "nobody is in possession" has no attacking direction to speak of.
            Intervals are closed at both ends, so where two spans touch, the away one wins and
            that single boundary frame is rotated.
    """
    if convention == "raw" or df.empty:
        return df
    if convention not in {"home_ltr", "possession"}:
        raise ValueError(f"unknown convention {convention!r}")

    signs = attacking_sign(df, "home")
    flip_periods = [p for p, s in signs.items() if s < 0]
    out = flip_tracking(df, df["period"].isin(flip_periods)) if flip_periods else df

    if convention == "home_ltr":
        return out
    if spans is None:
        raise ValueError(
            "convention='possession' needs spans=; build them with "
            "sportio.possession.possession_spans(events)"
        )
    return flip_tracking(out, _away_possession_mask(out, spans))


def _away_possession_mask(df: pd.DataFrame, spans: pd.DataFrame) -> np.ndarray:
    """Rows whose timestamp falls inside an away-team possession."""
    required = {"match_id", "period", "start_t", "end_t", "side"}
    missing = required - set(spans.columns)
    if missing:
        raise KeyError(f"spans is missing columns: {sorted(missing)}")

    mask = np.zeros(len(df), dtype=bool)
    away = spans.loc[spans["side"].astype("string").str.lower() == "away"]
    if away.empty:
        return mask

    times = df["t"].astype("float64").to_numpy()
    blocks = df.groupby(["match_id", "period"], dropna=False, sort=False).indices
    for key, block in away.groupby(["match_id", "period"], dropna=False, sort=False):
        rows = blocks.get(key)
        if rows is None:
            continue
        starts = block["start_t"].astype("float64").to_numpy()
        ends = block["end_t"].astype("float64").to_numpy()
        inside = (times[rows][:, None] >= starts) & (times[rows][:, None] <= ends)
        mask[rows[inside.any(axis=1)]] = True
    return mask

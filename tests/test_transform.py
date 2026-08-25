"""Resampling, velocities and direction-of-play normalisation."""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from sportio.pitch import PITCH_LENGTH, PITCH_WIDTH
from sportio.schema import conform_tracking
from sportio.transform import (
    add_velocities,
    attacking_sign,
    native_hz,
    normalize_direction,
    resample_tracking,
)


def _synthetic(hz: float = 25.0, seconds: float = 4.0, periods: tuple[int, ...] = (1,)) -> pd.DataFrame:
    """One home player walking right at 1 m/s, one away keeper parked, and a ball."""
    rows = []
    step = 1.0 / hz
    frame = 1
    for period in periods:
        # In period 2 the teams have swapped ends.
        offset = 0.0 if period == 1 else PITCH_LENGTH
        sign = 1.0 if period == 1 else -1.0
        for i in range(int(seconds * hz)):
            t = round((i + 1) * step, 6)
            rows += [
                {
                    "match_id": "1", "t": t, "period": period, "frame": frame,
                    "team": "home", "player_id": "Player1", "jersey": 1,
                    "x": offset + sign * (10.0 + i * step), "y": 34.0,
                    "vx": None, "vy": None, "confidence": None,
                },
                {
                    "match_id": "1", "t": t, "period": period, "frame": frame,
                    "team": "home", "player_id": "Player11", "jersey": 11,
                    "x": offset + sign * 4.0, "y": 34.0,
                    "vx": None, "vy": None, "confidence": None,
                },
                {
                    "match_id": "1", "t": t, "period": period, "frame": frame,
                    "team": "away", "player_id": "Player21", "jersey": 1,
                    "x": offset + sign * 101.0, "y": 34.0,
                    "vx": None, "vy": None, "confidence": None,
                },
                {
                    "match_id": "1", "t": t, "period": period, "frame": frame,
                    "team": "ball", "player_id": None, "jersey": None,
                    "x": 52.5, "y": 34.0,
                    "vx": None, "vy": None, "confidence": None,
                },
            ]
            frame += 1
    return conform_tracking(pd.DataFrame(rows))


def test_native_hz_reads_the_sampling_rate() -> None:
    assert native_hz(_synthetic(hz=25.0)) == pytest.approx(25.0)
    assert native_hz(_synthetic(hz=10.0)) == pytest.approx(10.0)


def test_resample_lands_on_a_uniform_grid() -> None:
    out = resample_tracking(_synthetic(hz=25.0, seconds=2.0), hz=10.0)
    assert native_hz(out) == pytest.approx(10.0)
    times = np.sort(out["t"].astype("float64").unique())
    assert np.allclose(np.diff(times), 0.1)


def test_resample_preserves_positions_of_a_linear_track() -> None:
    src = _synthetic(hz=25.0, seconds=2.0)
    out = resample_tracking(src, hz=10.0)
    walker = out.loc[out["player_id"] == "Player1"].sort_values("t")
    # x = 10 + (t - 0.04) exactly, because the player moves at 1 m/s from t=0.04.
    expected = 10.0 + (walker["t"].astype("float64") - 0.04)
    assert walker["x"].astype("float64").to_numpy() == pytest.approx(expected.to_numpy(), abs=1e-9)


def test_resample_refuses_to_invent_positions_across_a_long_gap() -> None:
    src = _synthetic(hz=10.0, seconds=4.0)
    holed = src.loc[~((src["t"].astype("float64") > 1.0) & (src["t"].astype("float64") < 3.0))]
    out = resample_tracking(holed, hz=10.0, max_gap=0.5)
    inside = out.loc[
        (out["player_id"] == "Player1")
        & (out["t"].astype("float64") > 1.2)
        & (out["t"].astype("float64") < 2.8)
    ]
    assert inside["x"].isna().all()


def test_velocities_recover_a_known_speed() -> None:
    out = add_velocities(_synthetic(hz=25.0, seconds=4.0), smooth=1)
    walker = out.loc[out["player_id"] == "Player1"].sort_values("t")
    vx = walker["vx"].astype("float64").dropna()
    assert vx.to_numpy() == pytest.approx(np.ones(len(vx)), abs=1e-6)
    assert walker["vy"].astype("float64").dropna().to_numpy() == pytest.approx(0.0, abs=1e-9)


def test_velocities_are_not_differenced_across_a_gap() -> None:
    src = _synthetic(hz=25.0, seconds=4.0)
    # Excise a whole second in the middle of the period, as a truncated file would.
    t = src["t"].astype("float64")
    holed = src.loc[(t <= 1.0) | (t >= 2.0)]
    out = add_velocities(holed, smooth=1, max_gap=0.5)
    resumed = out.loc[(out["player_id"] == "Player1") & (out["t"].astype("float64") == 2.0)]
    assert resumed["vx"].isna().all()
    # ...and the frames after the gap recover normally.
    later = out.loc[(out["player_id"] == "Player1") & (out["t"].astype("float64") > 2.1)]
    assert later["vx"].astype("float64").dropna().to_numpy() == pytest.approx(1.0, abs=1e-6)


def test_velocities_drop_teleports() -> None:
    src = _synthetic(hz=25.0, seconds=2.0).copy()
    jump = (src["player_id"] == "Player1") & (src["frame"] == 25)
    src.loc[jump, "x"] = 90.0
    out = add_velocities(src, smooth=1, max_speed=12.0)
    row = out.loc[(out["player_id"] == "Player1") & (out["frame"] == 25), "vx"]
    assert row.isna().all()


def test_attacking_sign_and_direction_normalisation() -> None:
    src = _synthetic(hz=10.0, seconds=2.0, periods=(1, 2))
    signs = attacking_sign(src, "home")
    assert signs == {1: 1, 2: -1}

    fixed = normalize_direction(src, convention="home_ltr")
    assert attacking_sign(fixed, "home") == {1: 1, 2: 1}

    # The flip is a rigid rotation: the away keeper stays 4 m from the goal he defends.
    keeper = fixed.loc[(fixed["team"] == "away") & (fixed["period"] == 2), "x"].astype("float64")
    assert keeper.to_numpy() == pytest.approx(101.0)


def test_direction_normalisation_flips_velocities_too() -> None:
    src = add_velocities(_synthetic(hz=10.0, seconds=2.0, periods=(1, 2)), smooth=1)
    fixed = normalize_direction(src)
    walker = fixed.loc[(fixed["player_id"] == "Player1") & (fixed["period"] == 2)]
    vx = walker["vx"].astype("float64").dropna()
    assert (vx > 0).all()


def test_raw_convention_is_a_no_op() -> None:
    src = _synthetic(hz=10.0, seconds=1.0, periods=(1, 2))
    pd.testing.assert_frame_equal(normalize_direction(src, convention="raw"), src)


def test_flip_keeps_points_on_the_pitch() -> None:
    fixed = normalize_direction(_synthetic(hz=10.0, seconds=1.0, periods=(1, 2)))
    xs = fixed["x"].astype("float64")
    ys = fixed["y"].astype("float64")
    assert xs.between(0, PITCH_LENGTH).all()
    assert ys.between(0, PITCH_WIDTH).all()

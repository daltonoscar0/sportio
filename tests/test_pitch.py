"""Coordinate normalisation. Getting an axis backwards here poisons every downstream tool."""

from __future__ import annotations

import numpy as np
import pytest

from sportio.pitch import (
    METRICA,
    PITCH_LENGTH,
    PITCH_WIDTH,
    SKILLCORNER,
    STATSBOMB,
    PitchSpec,
    centered,
    flip,
    flip_velocity,
)


@pytest.mark.parametrize("spec", [STATSBOMB, METRICA, SKILLCORNER])
def test_corners_map_to_corners(spec: PitchSpec) -> None:
    x0, x1 = spec.x_range
    y0, y1 = spec.y_range
    assert spec.to_canonical(x0, y0)[0] == pytest.approx(0.0)
    assert spec.to_canonical(x1, y1)[0] == pytest.approx(PITCH_LENGTH)
    ys = {round(spec.to_canonical(x0, y)[1], 6) for y in (y0, y1)}
    assert ys == {0.0, PITCH_WIDTH}


@pytest.mark.parametrize("spec", [STATSBOMB, METRICA, SKILLCORNER])
def test_centre_spot_maps_to_centre_spot(spec: PitchSpec) -> None:
    cx = (spec.x_range[0] + spec.x_range[1]) / 2
    cy = (spec.y_range[0] + spec.y_range[1]) / 2
    x, y = spec.to_canonical(cx, cy)
    assert (x, y) == pytest.approx((PITCH_LENGTH / 2, PITCH_WIDTH / 2))


@pytest.mark.parametrize("spec", [STATSBOMB, METRICA, SKILLCORNER])
def test_round_trip_through_from_canonical(spec: PitchSpec) -> None:
    rng = np.random.default_rng(0)
    xs = rng.uniform(*spec.x_range, size=64)
    ys = rng.uniform(*spec.y_range, size=64)
    back_x, back_y = spec.from_canonical(*spec.to_canonical(xs, ys))
    assert back_x == pytest.approx(xs)
    assert back_y == pytest.approx(ys)


def test_video_sources_have_a_top_left_origin() -> None:
    # y=0 in StatsBomb/Metrica is the *top* touchline, which is canonical y=68.
    assert STATSBOMB.to_canonical(0.0, 0.0)[1] == pytest.approx(PITCH_WIDTH)
    assert METRICA.to_canonical(0.0, 0.0)[1] == pytest.approx(PITCH_WIDTH)
    # ...whereas a centred, y-up source puts its minimum y at canonical 0.
    assert SKILLCORNER.to_canonical(-52.5, -34.0)[1] == pytest.approx(0.0)


def test_statsbomb_penalty_spot() -> None:
    # 12 yards from goal on a 120x80 pitch, centred.
    x, y = STATSBOMB.to_canonical(108.0, 40.0)
    assert x == pytest.approx(94.5)
    assert y == pytest.approx(PITCH_WIDTH / 2)


def test_centered_uses_real_pitch_dimensions() -> None:
    spec = centered(100.0, 64.0)
    assert spec.to_canonical(50.0, 32.0) == pytest.approx((PITCH_LENGTH, PITCH_WIDTH))
    assert spec.to_canonical(0.0, 0.0) == pytest.approx((PITCH_LENGTH / 2, PITCH_WIDTH / 2))


def test_flip_is_a_180_degree_rotation() -> None:
    assert flip(*flip(10.0, 20.0)) == pytest.approx((10.0, 20.0))
    assert flip(0.0, 0.0) == pytest.approx((PITCH_LENGTH, PITCH_WIDTH))
    assert flip_velocity(1.5, -2.0) == pytest.approx((-1.5, 2.0))


def test_degenerate_spec_is_rejected() -> None:
    with pytest.raises(ValueError, match="degenerate"):
        PitchSpec(x_range=(1.0, 1.0), y_range=(0.0, 1.0), y_increases_up=True)

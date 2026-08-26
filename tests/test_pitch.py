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
    STATSBOMB_LANDMARK,
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


def test_the_landmark_spec_puts_real_pitch_furniture_where_it_belongs() -> None:
    # The linear rescale shrinks the box and goal by 5-7% because StatsBomb's nominal 120x80
    # is not 105x68 in proportion. These are the real dimensions of the markings.
    for statsbomb_x, real_x in (
        (120.0, 105.0),   # goal line
        (114.0, 99.5),    # goal area, 5.5 m
        (108.0, 94.0),    # penalty spot, 11 m
        (102.0, 88.5),    # penalty area, 16.5 m
        (60.0, 52.5),     # halfway
    ):
        assert STATSBOMB_LANDMARK.to_canonical(statsbomb_x, 40.0)[0] == pytest.approx(real_x)

    # 7.32 m goal and 40.32 m penalty area, centred on the pitch. StatsBomb y runs downward,
    # so its 36 is the higher canonical y -- compare widths, not signed differences.
    posts = [STATSBOMB_LANDMARK.to_canonical(120.0, y)[1] for y in (36.0, 44.0)]
    assert abs(posts[1] - posts[0]) == pytest.approx(7.32)
    assert sum(posts) / 2 == pytest.approx(PITCH_WIDTH / 2)

    box = [STATSBOMB_LANDMARK.to_canonical(102.0, y)[1] for y in (18.0, 62.0)]
    assert abs(box[1] - box[0]) == pytest.approx(40.32)
    assert sum(box) / 2 == pytest.approx(PITCH_WIDTH / 2)


def test_the_linear_spec_really_does_shrink_the_box() -> None:
    # Stated in TODO.md as the reason the landmark option exists; assert it rather than
    # trusting the note.
    posts = [STATSBOMB.to_canonical(120.0, y)[1] for y in (36.0, 44.0)]
    linear_goal = abs(posts[1] - posts[0])
    assert linear_goal == pytest.approx(6.8)
    assert linear_goal < 7.32


def test_landmark_mapping_round_trips_and_extrapolates() -> None:
    rng = np.random.default_rng(1)
    xs = rng.uniform(0.0, 120.0, size=64)
    ys = rng.uniform(0.0, 80.0, size=64)
    back_x, back_y = STATSBOMB_LANDMARK.from_canonical(*STATSBOMB_LANDMARK.to_canonical(xs, ys))
    assert back_x == pytest.approx(xs)
    assert back_y == pytest.approx(ys)

    # Off-pitch points must keep going, not clamp onto the goal line -- a shot crossing it is
    # legitimate data.
    assert STATSBOMB_LANDMARK.to_canonical(123.0, 40.0)[0] > 105.0


def test_landmarks_must_be_monotonic() -> None:
    with pytest.raises(ValueError, match="monotonic"):
        PitchSpec(
            x_range=(0.0, 120.0),
            y_range=(0.0, 80.0),
            y_increases_up=True,
            x_landmarks=((0.0, 0.0), (60.0, 0.9), (120.0, 0.5)),
        )


def test_degenerate_spec_is_rejected() -> None:
    with pytest.raises(ValueError, match="degenerate"):
        PitchSpec(x_range=(1.0, 1.0), y_range=(0.0, 1.0), y_increases_up=True)

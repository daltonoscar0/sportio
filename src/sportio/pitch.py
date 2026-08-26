"""Pitch geometry and coordinate normalisation.

The canonical pitch is 105 x 68 metres with the origin at the **bottom-left corner**:
``x`` runs 0 -> 105 to the right, ``y`` runs 0 -> 68 upward. Every source is described by
a :class:`PitchSpec` giving its own axis ranges and y direction, and
:func:`PitchSpec.to_canonical` does the rest.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd

__all__ = [
    "METRICA",
    "PITCH_LENGTH",
    "PITCH_WIDTH",
    "SKILLCORNER",
    "STATSBOMB",
    "STATSBOMB_LANDMARK",
    "PitchSpec",
    "centered",
    "flip",
    "flip_velocity",
]

PITCH_LENGTH = 105.0
PITCH_WIDTH = 68.0

Numeric = float | np.ndarray | pd.Series


@dataclass(frozen=True, slots=True)
class PitchSpec:
    """How one source lays out its coordinates.

    Attributes:
        x_range: ``(x_at_left_goal_line, x_at_right_goal_line)`` in source units.
        y_range: ``(y_at_one_touchline, y_at_other_touchline)`` in source units.
        y_increases_up: ``True`` when a larger ``y`` is further "up" the pitch as drawn
            with the attacking direction to the right. Video-derived sources
            (StatsBomb, Metrica) put the origin top-left, so this is ``False`` for them.
        name: human label used in error messages and docs.
    """

    x_range: tuple[float, float]
    y_range: tuple[float, float]
    y_increases_up: bool
    name: str = "custom"
    x_landmarks: tuple[tuple[float, float], ...] | None = None
    y_landmarks: tuple[tuple[float, float], ...] | None = None

    def __post_init__(self) -> None:
        if self.x_range[0] == self.x_range[1] or self.y_range[0] == self.y_range[1]:
            raise ValueError(f"{self.name}: degenerate pitch range")
        for axis, pairs in (("x", self.x_landmarks), ("y", self.y_landmarks)):
            if pairs is None:
                continue
            if len(pairs) < 2:
                raise ValueError(f"{self.name}: {axis} needs at least two landmarks")
            sources = [p[0] for p in pairs]
            fractions = [p[1] for p in pairs]
            if sorted(sources) != sources or sorted(fractions) != fractions:
                raise ValueError(f"{self.name}: {axis} landmarks must be sorted and monotonic")

    def to_canonical(self, x: Numeric, y: Numeric) -> tuple[Numeric, Numeric]:
        """Map source coordinates onto the canonical 105x68 pitch."""
        fx = self._fraction(x, self.x_range, self.x_landmarks)
        fy = self._fraction(y, self.y_range, self.y_landmarks)
        if not self.y_increases_up:
            fy = 1.0 - fy
        return fx * PITCH_LENGTH, fy * PITCH_WIDTH

    def from_canonical(self, x: Numeric, y: Numeric) -> tuple[Numeric, Numeric]:
        """Inverse of :meth:`to_canonical`; used by the writers for round-tripping."""
        fx = x / PITCH_LENGTH
        fy = y / PITCH_WIDTH
        if not self.y_increases_up:
            fy = 1.0 - fy
        return (
            self._source(fx, self.x_range, self.x_landmarks),
            self._source(fy, self.y_range, self.y_landmarks),
        )

    @staticmethod
    def _fraction(
        value: Numeric,
        span: tuple[float, float],
        landmarks: tuple[tuple[float, float], ...] | None,
    ) -> Numeric:
        if landmarks is None:
            lo, hi = span
            return (value - lo) / (hi - lo)
        xs = np.array([p[0] for p in landmarks], dtype="float64")
        ys = np.array([p[1] for p in landmarks], dtype="float64")
        return _interp_extrapolate(value, xs, ys)

    @staticmethod
    def _source(
        fraction: Numeric,
        span: tuple[float, float],
        landmarks: tuple[tuple[float, float], ...] | None,
    ) -> Numeric:
        if landmarks is None:
            lo, hi = span
            return lo + fraction * (hi - lo)
        xs = np.array([p[0] for p in landmarks], dtype="float64")
        ys = np.array([p[1] for p in landmarks], dtype="float64")
        return _interp_extrapolate(fraction, ys, xs)


def _interp_extrapolate(value: Numeric, xs: np.ndarray, ys: np.ndarray) -> Numeric:
    """``np.interp`` that keeps going straight past the ends instead of clamping.

    Clamping would pin every off-pitch point onto the touchline, and off-pitch points are
    legitimate -- a shot crossing the goal line, a throw-in taken from behind it.
    """
    values = np.asarray(value, dtype="float64")
    out = np.interp(values, xs, ys)
    left_slope = (ys[1] - ys[0]) / (xs[1] - xs[0])
    right_slope = (ys[-1] - ys[-2]) / (xs[-1] - xs[-2])
    out = np.where(values < xs[0], ys[0] + (values - xs[0]) * left_slope, out)
    out = np.where(values > xs[-1], ys[-1] + (values - xs[-1]) * right_slope, out)
    if np.isscalar(value) or getattr(values, "ndim", 0) == 0:
        return float(out)
    if isinstance(value, pd.Series):
        return pd.Series(out, index=value.index)
    return out


#: StatsBomb: 120x80 "yards", origin top-left, y increasing downward.
STATSBOMB = PitchSpec(
    x_range=(0.0, 120.0), y_range=(0.0, 80.0), y_increases_up=False, name="statsbomb"
)

#: StatsBomb, but mapping its fixed pitch furniture onto the real thing instead of scaling
#: linearly. The plain rescale shrinks the penalty box and goal by 5-7% (goal 6.80 m against a
#: real 7.32 m, penalty spot 10.50 m against 11.00 m) because StatsBomb's nominal 120x80 is not
#: 105x68 in proportion. Landmarks pin the goal line, goal area, penalty area, penalty spot and
#: halfway line to their true positions and interpolate in between, which is what you want if
#: box-relative distances matter. It is NOT the default: mplsoccer, socceraction and kloppy all
#: rescale linearly, so the linear spec is what matches published numbers.
STATSBOMB_LANDMARK = PitchSpec(
    x_range=(0.0, 120.0),
    y_range=(0.0, 80.0),
    y_increases_up=False,
    name="statsbomb-landmark",
    x_landmarks=(
        (0.0, 0.0),                 # goal line
        (6.0, 5.5 / PITCH_LENGTH),  # goal area
        (12.0, 11.0 / PITCH_LENGTH),  # penalty spot
        (18.0, 16.5 / PITCH_LENGTH),  # penalty area
        (60.0, 0.5),                # halfway
        (102.0, 1.0 - 16.5 / PITCH_LENGTH),
        (108.0, 1.0 - 11.0 / PITCH_LENGTH),
        (114.0, 1.0 - 5.5 / PITCH_LENGTH),
        (120.0, 1.0),
    ),
    y_landmarks=(
        (0.0, 0.0),                                       # touchline
        (18.0, (PITCH_WIDTH - 40.32) / 2 / PITCH_WIDTH),  # penalty area, 40.32 m wide
        (30.0, (PITCH_WIDTH - 18.32) / 2 / PITCH_WIDTH),  # goal area, 18.32 m wide
        (36.0, (PITCH_WIDTH - 7.32) / 2 / PITCH_WIDTH),   # near post, 7.32 m goal
        (40.0, 0.5),                                      # goal centre
        (44.0, 1.0 - (PITCH_WIDTH - 7.32) / 2 / PITCH_WIDTH),
        (50.0, 1.0 - (PITCH_WIDTH - 18.32) / 2 / PITCH_WIDTH),
        (62.0, 1.0 - (PITCH_WIDTH - 40.32) / 2 / PITCH_WIDTH),
        (80.0, 1.0),
    ),
)

#: Metrica: both axes normalised to 0-1, origin top-left, y increasing downward.
METRICA = PitchSpec(x_range=(0.0, 1.0), y_range=(0.0, 1.0), y_increases_up=False, name="metrica")


def centered(pitch_length: float, pitch_width: float, name: str = "centered") -> PitchSpec:
    """A spec for sources measured in metres from the centre spot, y increasing upward."""
    return PitchSpec(
        x_range=(-pitch_length / 2.0, pitch_length / 2.0),
        y_range=(-pitch_width / 2.0, pitch_width / 2.0),
        y_increases_up=True,
        name=name,
    )


#: SkillCorner default; real pitch dimensions come from each match's ``match_data.json``.
SKILLCORNER = centered(105.0, 68.0, name="skillcorner")


def flip(x: Numeric, y: Numeric) -> tuple[Numeric, Numeric]:
    """Rotate a point 180 degrees about the centre spot (i.e. swap attacking direction)."""
    return PITCH_LENGTH - x, PITCH_WIDTH - y


def flip_velocity(vx: Numeric, vy: Numeric) -> tuple[Numeric, Numeric]:
    """The velocity counterpart of :func:`flip`."""
    return -vx, -vy

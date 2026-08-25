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

    def __post_init__(self) -> None:
        if self.x_range[0] == self.x_range[1] or self.y_range[0] == self.y_range[1]:
            raise ValueError(f"{self.name}: degenerate pitch range")

    def to_canonical(self, x: Numeric, y: Numeric) -> tuple[Numeric, Numeric]:
        """Map source coordinates onto the canonical 105x68 pitch."""
        x0, x1 = self.x_range
        y0, y1 = self.y_range
        fx = (x - x0) / (x1 - x0)
        fy = (y - y0) / (y1 - y0)
        if not self.y_increases_up:
            fy = 1.0 - fy
        return fx * PITCH_LENGTH, fy * PITCH_WIDTH

    def from_canonical(self, x: Numeric, y: Numeric) -> tuple[Numeric, Numeric]:
        """Inverse of :meth:`to_canonical`; used by the writers for round-tripping."""
        x0, x1 = self.x_range
        y0, y1 = self.y_range
        fx = x / PITCH_LENGTH
        fy = y / PITCH_WIDTH
        if not self.y_increases_up:
            fy = 1.0 - fy
        return x0 + fx * (x1 - x0), y0 + fy * (y1 - y0)


#: StatsBomb: 120x80 "yards", origin top-left, y increasing downward.
STATSBOMB = PitchSpec(
    x_range=(0.0, 120.0), y_range=(0.0, 80.0), y_increases_up=False, name="statsbomb"
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

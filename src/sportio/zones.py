"""Pitch grids.

A zone id is a coarse location token -- the thing you reach for when raw metres are too
fine-grained to count or embed. Downstream tools should take their grid from here rather
than each inventing an 18-zone scheme, because two tools that number their zones
differently produce numbers that silently cannot be compared.

Numbering is column-major from the **defending end**, so zone 1 is always the corner the
attacking team starts furthest from::

    y=68  +------+------+------+------+------+------+
          |  3   |  6   |  9   |  12  |  15  |  18  |
          +------+------+------+------+------+------+
          |  2   |  5   |  8   |  11  |  14  |  17  |
          +------+------+------+------+------+------+
          |  1   |  4   |  7   |  10  |  13  |  16  |
    y=0   +------+------+------+------+------+------+
         x=0                                      x=105
                    attacking direction ->

Because canonical events already attack left-to-right for the team in possession, zone 16-18
is always the attacking corner-to-corner band, whichever team and whichever half.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd

from .pitch import PITCH_LENGTH, PITCH_WIDTH

__all__ = [
    "CHANNELS",
    "THIRDS",
    "ZONES_12",
    "ZONES_18",
    "ZONES_24",
    "Grid",
    "add_zones",
    "zone_centres",
    "zone_labels",
    "zones",
]


@dataclass(frozen=True, slots=True)
class Grid:
    """A ``cols`` x ``rows`` rectangular partition of the canonical pitch.

    Attributes:
        cols: divisions along the attacking direction (x).
        rows: divisions across the pitch (y).
        name: label used in error messages and by :func:`zone_labels`.
    """

    cols: int
    rows: int
    name: str = "grid"

    def __post_init__(self) -> None:
        if self.cols < 1 or self.rows < 1:
            raise ValueError(f"{self.name}: a grid needs at least one column and one row")

    @property
    def size(self) -> int:
        return self.cols * self.rows

    @property
    def cell(self) -> tuple[float, float]:
        """Cell dimensions in metres."""
        return PITCH_LENGTH / self.cols, PITCH_WIDTH / self.rows

    def of(self, x: object, y: object) -> np.ndarray:
        """Zone ids (1-based) for arrays of coordinates; NaN in gives NaN out.

        Points off the pitch are clamped into the edge cell rather than dropped -- a shot
        crossing the goal line belongs to the attacking band, not to nowhere.
        """
        xs = pd.to_numeric(pd.Series(x), errors="coerce").to_numpy(dtype="float64")
        ys = pd.to_numeric(pd.Series(y), errors="coerce").to_numpy(dtype="float64")
        with np.errstate(invalid="ignore"):
            col = np.clip((xs / PITCH_LENGTH * self.cols).astype("float64"), 0, self.cols - 1e-9)
            row = np.clip((ys / PITCH_WIDTH * self.rows).astype("float64"), 0, self.rows - 1e-9)
        zone = np.floor(col) * self.rows + np.floor(row) + 1.0
        zone[np.isnan(xs) | np.isnan(ys)] = np.nan
        return zone

    def label(self, zone: int) -> str:
        """``"c3r2"`` -- column 3, row 2, both 1-based."""
        if not 1 <= zone <= self.size:
            raise ValueError(f"{self.name}: zone {zone} is outside 1..{self.size}")
        col, row = divmod(int(zone) - 1, self.rows)
        return f"c{col + 1}r{row + 1}"

    def centre(self, zone: int) -> tuple[float, float]:
        """Centre point of a zone, in canonical metres."""
        if not 1 <= zone <= self.size:
            raise ValueError(f"{self.name}: zone {zone} is outside 1..{self.size}")
        col, row = divmod(int(zone) - 1, self.rows)
        width, height = self.cell
        return (col + 0.5) * width, (row + 0.5) * height


#: The common 18-zone grid: six bands along the pitch, three across.
ZONES_18 = Grid(cols=6, rows=3, name="zones18")

#: Four bands by three, when 18 is too fine.
ZONES_12 = Grid(cols=4, rows=3, name="zones12")

#: Six bands by four, when 18 is too coarse across the pitch.
ZONES_24 = Grid(cols=6, rows=4, name="zones24")

#: Defensive, middle and attacking thirds.
THIRDS = Grid(cols=3, rows=1, name="thirds")

#: The five vertical channels (left wing, left half-space, centre, right half-space, right wing).
CHANNELS = Grid(cols=1, rows=5, name="channels")


def zones(
    events: pd.DataFrame,
    grid: Grid = ZONES_18,
    *,
    end: bool = False,
) -> pd.Series:
    """Zone id per event row, as a nullable ``Int16`` Series.

    Args:
        events: a canonical events frame.
        grid: which partition to use.
        end: read ``end_x``/``end_y`` instead of ``x``/``y``.
    """
    xcol, ycol = ("end_x", "end_y") if end else ("x", "y")
    for column in (xcol, ycol):
        if column not in events.columns:
            raise KeyError(f"events frame has no {column!r} column")
    values = grid.of(events[xcol], events[ycol])
    return pd.Series(values, index=events.index, dtype="Float64").round().astype("Int16")


def add_zones(events: pd.DataFrame, grid: Grid = ZONES_18) -> pd.DataFrame:
    """``events`` plus ``zone`` and ``end_zone`` columns.

    These are *not* part of the canonical schema -- they are derived, and adding them is the
    caller's choice -- so this returns a copy rather than mutating in place.
    """
    out = events.copy()
    out["zone"] = zones(events, grid)
    out["end_zone"] = zones(events, grid, end=True)
    return out


def zone_labels(grid: Grid = ZONES_18) -> list[str]:
    """Every zone label in id order, for building a lookup or a legend."""
    return [grid.label(z) for z in range(1, grid.size + 1)]


def zone_centres(grid: Grid = ZONES_18) -> pd.DataFrame:
    """One row per zone: ``zone``, ``label``, ``x``, ``y`` -- handy for plotting."""
    rows = []
    for zone in range(1, grid.size + 1):
        x, y = grid.centre(zone)
        rows.append({"zone": zone, "label": grid.label(zone), "x": x, "y": y})
    return pd.DataFrame(rows)

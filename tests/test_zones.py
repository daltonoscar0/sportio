"""The shared pitch grid. If two tools number zones differently their numbers cannot be compared."""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

import sportio
from sportio.zones import CHANNELS, THIRDS, ZONES_12, ZONES_18, ZONES_24, Grid


def _events(points: list[tuple[float | None, float | None]]) -> pd.DataFrame:
    rows = [
        {
            "match_id": "m", "competition": "c", "season": "s", "team_id": "home",
            "team": "Home", "player_id": "p", "player": "P", "t": float(i), "period": 1,
            "type": "pass", "subtype": None, "x": x, "y": y, "end_x": y, "end_y": x,
            "outcome": None, "pressure": False, "body_part": None, "extra": "{}",
        }
        for i, (x, y) in enumerate(points)
    ]
    return sportio.conform_events(pd.DataFrame(rows))


def test_the_eighteen_zone_grid_is_six_by_three() -> None:
    assert ZONES_18.size == 18
    assert (ZONES_18.cols, ZONES_18.rows) == (6, 3)
    assert ZONES_18.cell == pytest.approx((17.5, 68 / 3))


def test_zone_one_is_the_defending_corner_and_zone_eighteen_the_attacking_one() -> None:
    assert ZONES_18.of([0.0], [0.0])[0] == 1
    assert ZONES_18.of([105.0], [68.0])[0] == 18
    # Because canonical events attack left-to-right for the team in possession, the high
    # zone numbers are always the attacking end, whichever team and whichever half.
    assert ZONES_18.of([104.0], [1.0])[0] == 16


def test_the_centre_spot_is_the_middle_zone() -> None:
    assert ZONES_18.of([52.5], [34.0])[0] == 11
    x, y = ZONES_18.centre(11)
    assert (x, y) == pytest.approx((61.25, 34.0))


def test_every_zone_id_round_trips_through_its_own_centre() -> None:
    for grid in (ZONES_12, ZONES_18, ZONES_24, THIRDS, CHANNELS):
        for zone in range(1, grid.size + 1):
            x, y = grid.centre(zone)
            assert grid.of([x], [y])[0] == zone, (grid.name, zone)


def test_off_pitch_points_clamp_into_the_edge_zone_and_nulls_stay_null() -> None:
    # A shot crossing the goal line belongs to the attacking band, not to nowhere.
    assert ZONES_18.of([110.0], [70.0])[0] == 18
    assert ZONES_18.of([-4.0], [-2.0])[0] == 1
    assert np.isnan(ZONES_18.of([np.nan], [3.0])[0])


def test_zones_reads_the_event_frame_and_keeps_the_index() -> None:
    events = _events([(1.0, 1.0), (104.0, 67.0), (None, None)])
    start = sportio.zones(events)
    assert list(start.index) == list(events.index)
    assert start.tolist()[:2] == [1, 18]
    assert start.isna().iloc[2]
    assert str(start.dtype) == "Int16"


def test_end_zones_come_from_the_end_coordinates() -> None:
    # _events puts the end point at (y, x), so (1, 67) starts in the defending-left corner
    # (column 1, row 3 -> zone 3) and ends at (67, 1) in column 4, row 1 -> zone 10.
    events = _events([(1.0, 67.0)])
    assert sportio.zones(events).iloc[0] == 3
    assert sportio.zones(events, end=True).iloc[0] == 10


def test_add_zones_does_not_mutate_the_canonical_frame() -> None:
    events = _events([(10.0, 10.0)])
    out = sportio.add_zones(events)
    assert "zone" in out.columns and "end_zone" in out.columns
    # The canonical schema has no zone column and adding one is the caller's choice.
    assert tuple(events.columns) == sportio.EVENT_COLUMNS
    assert "zone" not in events.columns


def test_labels_and_centres_line_up_with_the_ids() -> None:
    labels = sportio.zone_labels()
    assert len(labels) == 18
    assert labels[0] == "c1r1"
    assert labels[-1] == "c6r3"

    centres = sportio.zone_centres()
    assert list(centres["zone"]) == list(range(1, 19))
    assert centres["x"].between(0, 105).all()
    assert centres["y"].between(0, 68).all()


def test_a_degenerate_grid_is_rejected() -> None:
    with pytest.raises(ValueError, match="at least one column"):
        Grid(cols=0, rows=3)
    with pytest.raises(ValueError, match=r"outside 1\.\.18"):
        ZONES_18.label(19)

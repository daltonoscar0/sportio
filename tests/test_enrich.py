"""Filling event gaps from tracking: set-piece positions and a pressure flag."""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

import sportio
from sportio.loaders import metrica

from .conftest import fixture_path

HOME = "Sample_Game_1_RawTrackingData_Home_Team.trunc.csv"
AWAY = "Sample_Game_1_RawTrackingData_Away_Team.trunc.csv"
EVENTS = "Sample_Game_1_RawEventsData.trunc.csv"


# --------------------------------------------------------------------------------------
# exact behaviour, on a frame small enough to reason about by hand
# --------------------------------------------------------------------------------------


def _tracking(rows: list[dict[str, object]]) -> pd.DataFrame:
    return sportio.conform_tracking(pd.DataFrame(rows))


def _synthetic() -> tuple[pd.DataFrame, pd.DataFrame]:
    """One frame: the ball on the corner arc, an actor, a near and a far opponent."""
    tracking = _tracking(
        [
            {"match_id": "m", "t": 4.0, "period": 1, "frame": 100, "team": "ball",
             "player_id": None, "jersey": None, "x": 105.0, "y": 68.0,
             "vx": None, "vy": None, "confidence": None},
            {"match_id": "m", "t": 4.0, "period": 1, "frame": 100, "team": "home",
             "player_id": "H1", "jersey": 7, "x": 100.0, "y": 60.0,
             "vx": None, "vy": None, "confidence": None},
            {"match_id": "m", "t": 4.0, "period": 1, "frame": 100, "team": "away",
             "player_id": "A1", "jersey": 4, "x": 102.0, "y": 60.0,
             "vx": None, "vy": None, "confidence": None},
            {"match_id": "m", "t": 4.0, "period": 1, "frame": 100, "team": "away",
             "player_id": "A2", "jersey": 5, "x": 60.0, "y": 20.0,
             "vx": None, "vy": None, "confidence": None},
        ]
    )
    events = sportio.conform_events(
        pd.DataFrame(
            [
                {
                    "match_id": "m", "competition": "c", "season": "s", "team_id": "home",
                    "team": "Home", "player_id": "H1", "player": "H1", "t": 4.0, "period": 1,
                    "type": "set_piece", "subtype": "corner", "x": None, "y": None,
                    "end_x": None, "end_y": None, "outcome": None, "pressure": False,
                    "body_part": None, "extra": '{"start_frame":100}',
                }
            ]
        )
    )
    return events, tracking


def test_a_set_piece_takes_the_balls_position_at_its_frame() -> None:
    events, tracking = _synthetic()
    assert events["x"].isna().all()
    out = sportio.fill_coordinates_from_tracking(events, tracking)
    assert float(out.loc[0, "x"]) == pytest.approx(105.0)
    assert float(out.loc[0, "y"]) == pytest.approx(68.0)


def test_rows_that_already_have_a_position_are_left_alone() -> None:
    events, tracking = _synthetic()
    events.loc[0, "x"] = 50.0
    events.loc[0, "y"] = 30.0
    out = sportio.fill_coordinates_from_tracking(events, tracking)
    assert float(out.loc[0, "x"]) == pytest.approx(50.0)

    overwritten = sportio.fill_coordinates_from_tracking(events, tracking, only_missing=False)
    assert float(overwritten.loc[0, "x"]) == pytest.approx(105.0)


def test_the_distance_is_to_the_nearest_opponent_not_the_nearest_player() -> None:
    events, tracking = _synthetic()
    # A1 is 2 m away, A2 is far; the actor's own team-mates must not count.
    distance = sportio.nearest_opponent_distance(events, tracking)
    assert float(distance.iloc[0]) == pytest.approx(2.0)


def test_pressure_thresholds_that_distance_and_keeps_it() -> None:
    events, tracking = _synthetic()
    tight = sportio.add_pressure_from_tracking(events, tracking, radius=3.0)
    loose = sportio.add_pressure_from_tracking(events, tracking, radius=1.0)
    assert bool(tight.loc[0, "pressure"]) is True
    assert bool(loose.loc[0, "pressure"]) is False
    # The measurement survives, because a boolean throws away what most consumers want.
    assert float(sportio.extra_field(tight, "opponent_distance").iloc[0]) == pytest.approx(2.0)


def test_an_unidentifiable_actor_gets_no_distance_rather_than_a_guess() -> None:
    events, tracking = _synthetic()
    events.loc[0, "player_id"] = "NOBODY"
    assert sportio.nearest_opponent_distance(events, tracking).isna().all()
    out = sportio.add_pressure_from_tracking(events, tracking)
    assert bool(out.loc[0, "pressure"]) is False


def test_a_source_flag_is_not_overwritten_unless_asked() -> None:
    events, tracking = _synthetic()
    events.loc[0, "pressure"] = True
    kept = sportio.add_pressure_from_tracking(events, tracking, radius=0.1)
    assert bool(kept.loc[0, "pressure"]) is True
    replaced = sportio.add_pressure_from_tracking(events, tracking, radius=0.1, overwrite=True)
    assert bool(replaced.loc[0, "pressure"]) is False


def test_events_without_a_frame_reference_fall_back_to_the_nearest_sample() -> None:
    events, tracking = _synthetic()
    events.loc[0, "extra"] = "{}"
    events.loc[0, "t"] = 4.02  # 20 ms off the only sample
    out = sportio.fill_coordinates_from_tracking(events, tracking)
    assert float(out.loc[0, "x"]) == pytest.approx(105.0)

    far = events.copy()
    far.loc[0, "t"] = 40.0  # far outside the tracked window
    untouched = sportio.fill_coordinates_from_tracking(far, tracking)
    assert untouched["x"].isna().all()


# --------------------------------------------------------------------------------------
# against the real Metrica files
# --------------------------------------------------------------------------------------


@pytest.fixture(scope="module")
def enriched() -> pd.DataFrame:
    return metrica.load_events(
        1,
        events_file=fixture_path("metrica", EVENTS),
        enrich=True,
        home_file=fixture_path("metrica", HOME),
        away_file=fixture_path("metrica", AWAY),
    )


def test_enriching_metrica_stays_inside_the_canonical_schema(enriched: pd.DataFrame) -> None:
    assert tuple(enriched.columns) == sportio.EVENT_COLUMNS
    sportio.validate_events(enriched, sample=None)


def test_enrichment_only_adds_and_never_removes(enriched: pd.DataFrame) -> None:
    plain = metrica.load_events(1, events_file=fixture_path("metrica", EVENTS))
    assert len(enriched) == len(plain)
    assert int(enriched["x"].notna().sum()) >= int(plain["x"].notna().sum())
    # Metrica records no pressure at all, so anything true here was measured from tracking.
    assert not plain["pressure"].any()


def test_measured_distances_are_physically_plausible(enriched: pd.DataFrame) -> None:
    distance = pd.to_numeric(sportio.extra_field(enriched, "opponent_distance")).dropna()
    assert len(distance) > 0
    assert (distance >= 0).all()
    # Two players cannot be more than a pitch diagonal apart.
    assert distance.max() < float(np.hypot(105.0, 68.0))


def test_enrichment_needs_the_tracking_files() -> None:
    # Without them the loader would have to download 65 MB behind the caller's back, so the
    # offline lock is what surfaces here rather than a silent no-op.
    with pytest.raises(Exception, match=r"OFFLINE|not cached|offline"):
        metrica.load_events(1, events_file=fixture_path("metrica", EVENTS), enrich=True)

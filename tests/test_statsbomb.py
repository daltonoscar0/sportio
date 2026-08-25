"""StatsBomb specifics: the possession-frame mirror, set pieces and 360 freeze frames."""

from __future__ import annotations

import json

import numpy as np
import pandas as pd
import pytest

import sportio
from sportio.loaders import statsbomb

from .conftest import fixture_path

MATCH = 3943043


@pytest.fixture(scope="module")
def events() -> pd.DataFrame:
    return statsbomb.load_events(
        match=MATCH,
        competition="UEFA Euro",
        season="2024",
        events_file=fixture_path("statsbomb", "events_3943043_slice.json"),
        three_sixty_file=fixture_path("statsbomb", "three-sixty_3943043_slice.json"),
    )


@pytest.fixture(scope="module")
def competitions() -> pd.DataFrame:
    return pd.DataFrame(json.loads(fixture_path("statsbomb", "competitions.json").read_text()))


# --------------------------------------------------------------------------------------
# acceptance: corners carry 360 freeze frames
# --------------------------------------------------------------------------------------


def test_corners_carry_a_360_freeze_frame_of_at_least_15_players(events: pd.DataFrame) -> None:
    with_frames = sportio.corners(events, with_freeze_frame=True)
    assert len(with_frames) > 0
    sizes = sportio.freeze_frame_size(with_frames)
    assert (sizes >= 15).all(), f"freeze frame sizes: {sizes.tolist()}"


def test_corners_are_the_deliveries_not_the_whole_sequence(events: pd.DataFrame) -> None:
    corners = sportio.corners(events)
    assert len(corners) == 2
    # Every delivery is taken from a corner flag: the attacking end, on a touchline.
    assert corners["x"].astype("float64").to_numpy() == pytest.approx(105.0)
    y = corners["y"].astype("float64")
    assert (y.between(-0.2, 0.2) | y.between(67.8, 68.2)).all(), y.tolist()
    # play_pattern marks the whole possession chain that followed a corner, which is a far
    # bigger set -- the two must not be confused.
    followed = (sportio.extra_field(events, "play_pattern") == "from_corner").sum()
    assert followed > len(corners) * 5


def test_corner_window_pulls_in_the_following_play(events: pd.DataFrame) -> None:
    wide = sportio.corners(events, window=10.0)
    assert len(wide) > len(sportio.corners(events))
    assert set(sportio.corners(events)["t"]) <= set(wide["t"])


def test_freeze_frames_explode_onto_the_canonical_pitch(events: pd.DataFrame) -> None:
    players = sportio.freeze_frames(sportio.corners(events, with_freeze_frame=True))
    assert len(players) >= 15
    assert players["x"].astype("float64").between(-10, 115).all()
    assert players["y"].astype("float64").between(-8, 76).all()
    # Exactly one actor per frame, and the actor stands where the event happened.
    assert players["actor"].sum() == 1
    actor = players.loc[players["actor"]].iloc[0]
    corner = sportio.corners(events, with_freeze_frame=True).iloc[0]
    assert float(actor["x"]) == pytest.approx(float(corner["x"]), abs=0.2)
    assert float(actor["y"]) == pytest.approx(float(corner["y"]), abs=0.2)


# --------------------------------------------------------------------------------------
# the per-event-team mirror
# --------------------------------------------------------------------------------------


def test_off_possession_events_are_mirrored_into_the_possession_frame(
    events: pd.DataFrame,
) -> None:
    mirrored = sportio.extra_field(events, "mirrored").map(bool)
    assert mirrored.sum() > 0, "the fixture is supposed to contain off-possession events"

    # A goalkeeper defending against the team in possession must be at the attacked end.
    keepers = events.loc[events["type"] == "goal_keeper"]
    defending = keepers.loc[sportio.extra_field(keepers, "mirrored").map(bool)]
    assert len(defending) > 0
    assert (defending["x"].astype("float64") > 90.0).all()


def test_acting_frame_keeps_statsbombs_own_convention() -> None:
    acting = statsbomb.load_events(
        match=MATCH,
        events_file=fixture_path("statsbomb", "events_3943043_slice.json"),
        frame="acting",
    )
    keepers = acting.loc[acting["type"] == "goal_keeper"]
    # In StatsBomb's native frame the acting team always attacks +x, so its own keeper
    # sits near x = 0.
    assert (keepers["x"].astype("float64") < 15.0).all()
    assert not sportio.extra_field(acting, "mirrored").map(bool).any()


def test_unknown_frame_is_rejected() -> None:
    with pytest.raises(ValueError, match="unknown frame"):
        statsbomb.load_events(
            match=MATCH,
            events_file=fixture_path("statsbomb", "events_3943043_slice.json"),
            frame="sideways",
        )


# --------------------------------------------------------------------------------------
# field mapping
# --------------------------------------------------------------------------------------


def test_a_missing_pass_outcome_means_the_pass_was_completed(events: pd.DataFrame) -> None:
    passes = events.loc[events["type"] == "pass"]
    assert (passes["outcome"] == "complete").any()
    assert passes["outcome"].notna().all(), "every pass must state an outcome"


def test_shot_height_is_kept_when_end_location_has_three_components(
    events: pd.DataFrame,
) -> None:
    shots = events.loc[events["type"] == "shot"]
    heights = sportio.extra_field(shots, "end_z").dropna()
    assert len(heights) > 0
    assert all(0.0 <= float(z) < 10.0 for z in heights)


def test_goalkeeper_events_keep_their_payload(events: pd.DataFrame) -> None:
    # "Goal Keeper" is the one type whose sub-dict StatsBomb spells differently from its
    # type name ("goalkeeper", not "goal_keeper"). Looking it up by the snake-cased name
    # silently drops the whole payload on every keeper event.
    keepers = events.loc[events["type"] == "goal_keeper"]
    assert len(keepers) > 0
    assert keepers["subtype"].notna().all()
    assert set(keepers["subtype"]) <= {
        "shot_faced", "shot_saved", "goal_conceded", "collected", "punch", "smother",
        "keeper_sweeper", "save", "penalty_saved", "penalty_conceded",
    }
    # Shot Faced events carry an end_location; at least one must have survived.
    assert keepers["end_x"].notna().any()


def test_pass_length_and_angle_are_recomputed_in_canonical_space(events: pd.DataFrame) -> None:
    # The 120x80 -> 105x68 rescale is anisotropic (0.875 vs 0.85), so StatsBomb's own
    # pass.length (yards) and pass.angle (y-down axes) cannot simply be copied across.
    passes = events.loc[(events["type"] == "pass") & events["end_x"].notna()]
    assert len(passes) > 0
    length = sportio.extra_field(passes, "length").astype("float64")
    angle = sportio.extra_field(passes, "angle").astype("float64")
    dx = passes["end_x"].astype("float64") - passes["x"].astype("float64")
    dy = passes["end_y"].astype("float64") - passes["y"].astype("float64")
    assert length.to_numpy() == pytest.approx(np.hypot(dx, dy).to_numpy(), abs=1e-9)
    assert angle.to_numpy() == pytest.approx(np.arctan2(dy, dx).to_numpy(), abs=1e-9)
    assert length.max() < 110.0  # metres, not yards on a 120-unit pitch


def test_under_pressure_absence_means_false(events: pd.DataFrame) -> None:
    assert events["pressure"].notna().all()
    assert events["pressure"].any()


def test_timestamp_becomes_seconds_within_the_period(events: pd.DataFrame) -> None:
    # The fixture is a period-2 slice around 19:16-25:08 on the period clock, while the
    # wall clock reads 64-70 minutes. Using minute/second would be ~2700 s out.
    assert set(events["period"]) == {2}
    t = events["t"].astype("float64")
    assert 1100.0 < t.min() < 1200.0
    assert 1500.0 < t.max() < 1600.0
    minutes = sportio.extra_field(events, "minute").dropna().astype(int)
    assert minutes.min() >= 60


def test_event_type_names_are_snake_cased(events: pd.DataFrame) -> None:
    # "Ball Receipt*" carries a literal asterisk and "50/50" starts with a digit.
    assert "ball_receipt" in set(events["type"])
    assert events["type"].str.match(r"^[a-z0-9_]+$").all()


# --------------------------------------------------------------------------------------
# competition lookup
# --------------------------------------------------------------------------------------


def test_find_competition_resolves_a_human_name(competitions: pd.DataFrame) -> None:
    assert statsbomb.find_competition("Euro 2024", competitions=competitions) == (55, 282)
    assert statsbomb.find_competition("UEFA Euro 2024", competitions=competitions) == (55, 282)
    assert statsbomb.find_competition("UEFA Euro", "2024", competitions=competitions) == (55, 282)
    assert statsbomb.EURO_2024 == (55, 282)


def test_find_competition_reports_ambiguity_rather_than_guessing(
    competitions: pd.DataFrame,
) -> None:
    rows = competitions.to_dict(orient="records")[:1] * 2
    rows[1] = dict(rows[1], season_id=999, season_name="1999")
    with pytest.raises(LookupError):
        statsbomb.find_competition("Euro", competitions=pd.DataFrame(rows))


def test_unknown_competition_is_an_error(competitions: pd.DataFrame) -> None:
    with pytest.raises(LookupError, match="no StatsBomb competition"):
        statsbomb.find_competition("Hyperliga 3000", competitions=competitions)

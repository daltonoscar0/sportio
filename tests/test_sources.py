"""SkillCorner, SoccerNet and rugby specifics."""

from __future__ import annotations

import warnings

import numpy as np
import pandas as pd
import pytest

import sportio
from sportio.loaders import rugby, skillcorner, soccernet
from sportio.transform import attacking_sign

from .conftest import fixture_path

SC = "skillcorner"
MATCH_FILE = ("1886347_match.json",)


def _sc_tracking(name: str, **kwargs: object) -> pd.DataFrame:
    return skillcorner.load_tracking(
        1886347,
        match_file=fixture_path(SC, "1886347_match.json"),
        tracking_file=fixture_path(SC, name),
        **kwargs,
    )


# --------------------------------------------------------------------------------------
# SkillCorner
# --------------------------------------------------------------------------------------


def test_skillcorner_skips_frames_outside_live_play() -> None:
    # The head fixture opens with ten frames of period: null, empty player_data and an
    # all-null ball_data before kickoff at frame 10.
    tracking = _sc_tracking("1886347_tracking_head.jsonl")
    assert tracking["period"].notna().all()
    assert tracking["frame"].min() == 10
    assert float(tracking["t"].min()) == 0.0


def test_skillcorner_derives_t_from_the_period_start_frame() -> None:
    # The period-2 fixture starts at frame 31783 with the source's match clock reading
    # 00:51:38.30 -- a flat +45:00 offset. Using the timestamp would put t 2700 s out.
    tracking = _sc_tracking("1886347_tracking_period2.jsonl")
    assert set(tracking["period"]) == {2}
    assert float(tracking["t"].min()) == pytest.approx(398.3, abs=0.05)


def test_skillcorner_uses_the_matchs_own_pitch_dimensions() -> None:
    tracking = _sc_tracking("1886347_tracking_head.jsonl")
    # Match 1886347 is played on a 104 m pitch, so a hard-coded 105 would misplace x.
    x = tracking["x"].astype("float64")
    assert x.between(-5, 110).all()
    assert x.max() > 80.0


def test_skillcorner_direction_comes_from_metadata_not_inference() -> None:
    period_one = _sc_tracking("1886347_tracking_head.jsonl")
    # home_team_side[0] is "right_to_left" for this match, so the loader must flip period 1.
    assert attacking_sign(period_one, "home") == {1: 1}
    raw = _sc_tracking("1886347_tracking_head.jsonl", direction="raw")
    assert attacking_sign(raw, "home") == {1: -1}


def test_skillcorner_confidence_records_what_the_camera_actually_saw() -> None:
    tracking = _sc_tracking("1886347_tracking_head.jsonl")
    confidence = tracking["confidence"].astype("float64")
    # The feed is extrapolated: every player has a position every frame, but only the
    # detected ones are measurements. Both values must be present.
    assert set(np.round(confidence.dropna().unique(), 2)) == {1.0, 0.5}


def test_skillcorner_events_are_derived_not_a_conventional_feed() -> None:
    events = skillcorner.load_events(
        1886347,
        match_file=fixture_path(SC, "1886347_match.json"),
        events_file=fixture_path(SC, "1886347_dynamic_events_head.csv"),
    )
    sportio.validate_events(events, sample=None)
    # A pass is a player_possession row whose end_type is "pass"; there is no top-level
    # pass event type in this source.
    assert "pass" in set(events["type"])
    assert {"passing_option", "off_ball_run"} & set(events["type"])
    assert events["competition"].iloc[0] == "A-League"


def test_skillcorner_events_are_rotated_by_their_own_attacking_side() -> None:
    events = skillcorner.load_events(
        1886347,
        match_file=fixture_path(SC, "1886347_match.json"),
        events_file=fixture_path(SC, "1886347_dynamic_events_head.csv"),
    )
    assert events["x"].astype("float64").between(-5, 110).all()
    sides = set(sportio.extra_field(events, "attacking_side").dropna())
    # Both directions occur in the source rows, so the flip is genuinely exercised.
    assert sides == {"left_to_right", "right_to_left"}


def test_skillcorner_pressure_is_derived_from_the_engagement_subtype() -> None:
    events = skillcorner.load_events(
        1886347,
        match_file=fixture_path(SC, "1886347_match.json"),
        events_file=fixture_path(SC, "1886347_dynamic_events_head.csv"),
    )
    pressured = events.loc[events["pressure"]]
    assert len(pressured) > 0
    assert set(pressured["subtype"].dropna()) <= {
        "pressure", "pressing", "counter_press", "recovery_press",
    }


# --------------------------------------------------------------------------------------
# SoccerNet
# --------------------------------------------------------------------------------------


def test_soccernet_reads_metric_pitch_coordinates() -> None:
    tracking = soccernet.load_tracking(fixture_path("soccernet", "gsr", "SNGS-056"))
    sportio.validate_tracking(tracking, sample=None)
    assert set(tracking["period"]) == {2}
    # clip_start is 2208000 ms into the half, and t is seconds within the period.
    assert float(tracking["t"].min()) == pytest.approx(2208.0)
    assert tracking["x"].astype("float64").between(0, 105).all()


def test_soccernet_drops_detections_with_no_camera_calibration() -> None:
    # SNGS-035 straddles a calibration loss: frame 376 is clean, 377 and 378 have
    # bbox_pitch null on every object.
    tracking = soccernet.load_tracking(fixture_path("soccernet", "gsr", "SNGS-035"))
    assert set(tracking["frame"]) == {376}

    kept = soccernet.load_tracking(
        fixture_path("soccernet", "gsr", "SNGS-035"), keep_uncalibrated=True
    )
    assert len(kept) > len(tracking)
    assert kept.loc[kept["frame"] > 376, "x"].isna().all()


def test_soccernet_drops_unprojection_blow_ups() -> None:
    _, det = soccernet.read_gsr(fixture_path("soccernet", "gsr", "SNGS-035"))
    # The raw labels contain positions hundreds of metres off the pitch.
    assert det["pitch_y"].astype("float64").abs().max() > 200.0
    tracking = soccernet.load_tracking(fixture_path("soccernet", "gsr", "SNGS-035"))
    assert tracking["y"].astype("float64").between(-15, 83).all()

    unfiltered = soccernet.load_tracking(
        fixture_path("soccernet", "gsr", "SNGS-035"), margin=None
    )
    assert len(unfiltered) > len(tracking)


def test_soccernet_direction_is_left_alone_by_default() -> None:
    # team is left/right w.r.t. the camera and a clip is 30 s with no goal context, so
    # there is nothing to normalise direction against.
    a = soccernet.load_tracking(fixture_path("soccernet", "gsr", "SNGS-056"))
    b = soccernet.load_tracking(fixture_path("soccernet", "gsr", "SNGS-056"), direction="raw")
    pd.testing.assert_frame_equal(a, b)


def test_soccernet_mot_is_image_space_and_says_so() -> None:
    with pytest.warns(UserWarning, match="image-space only"):
        tracking = soccernet.load_tracking(fixture_path("soccernet", "mot", "SNMOT-116"))
    sportio.validate_tracking(tracking, sample=None)
    assert tracking["x"].isna().all()
    assert tracking["y"].isna().all()
    # Roles, teams and jerseys still come through from gameinfo.ini.
    assert set(tracking["team"]) <= {"home", "away", "ball"}
    assert tracking["jersey"].notna().any()


def test_soccernet_rejects_a_directory_that_is_neither_format(tmp_path) -> None:
    with pytest.raises(FileNotFoundError, match="neither a GSR sequence"):
        soccernet.load_tracking(tmp_path)


# --------------------------------------------------------------------------------------
# rugby
# --------------------------------------------------------------------------------------


@pytest.fixture(scope="module")
def rugby_events() -> pd.DataFrame:
    return rugby.load_events(
        summary_file=fixture_path("rugby", "espn_summary_180659_600252.json")
    )


def test_rugby_has_no_coordinates_and_does_not_pretend_otherwise(
    rugby_events: pd.DataFrame,
) -> None:
    assert rugby_events[["x", "y", "end_x", "end_y"]].isna().all().all()
    assert not rugby_events["pressure"].any()
    assert rugby_events["body_part"].isna().all()


def test_rugby_types_come_from_the_canonical_vocabulary(rugby_events: pd.DataFrame) -> None:
    assert set(rugby_events["type"]) <= set(rugby.RUGBY_EVENT_TYPES)
    assert {"try", "conversion", "penalty_goal", "card", "substitution"} <= set(
        rugby_events["type"]
    )


def test_rugby_clock_is_converted_to_seconds_within_the_period(
    rugby_events: pd.DataFrame,
) -> None:
    # ESPN's clock counts from kickoff and does not reset; first-half added time overruns
    # the nominal 2400 s boundary, so period must come from period.number.
    assert set(rugby_events["period"]) == {1, 2}
    assert float(rugby_events["t"].max()) < 2600.0
    p1 = rugby_events.loc[rugby_events["period"] == 1, "t"].astype("float64")
    p2 = rugby_events.loc[rugby_events["period"] == 2, "t"].astype("float64")
    assert p1.max() > 2400.0  # first-half stoppage time
    assert p2.min() < 10.0


def test_rugby_substitutions_are_paired(rugby_events: pd.DataFrame) -> None:
    subs = rugby_events.loc[rugby_events["type"] == "substitution"]
    assert len(subs) == 44
    assert subs["subtype"].value_counts().to_dict() == {"on": 22, "off": 22}
    partners = sportio.extra_field(subs, "substitution_partner")
    assert partners.notna().all()
    # A player can legitimately appear as both on and off (an HIA reversal), so the pairing
    # must key on (team, period, clock), not on player identity.
    assert subs["player_id"].nunique() < len(subs)


def test_rugby_reads_the_thinner_scoreboard_shape() -> None:
    events = rugby.load_events(
        scoreboard_file=fixture_path("rugby", "espn_scoreboard_180659_20250201.json")
    )
    sportio.validate_events(events, sample=None)
    assert events["match_id"].nunique() == 2
    # The scoreboard nests athletes under athletesInvolved rather than participants.
    assert events["player"].notna().any()


def test_rugby_scoreboard_index() -> None:
    table = rugby.load_scoreboard(
        scoreboard_file=fixture_path("rugby", "espn_scoreboard_180659_20250201.json")
    )
    assert list(table["event_id"]) == ["600251", "600252"]
    assert table["plays"].tolist() == [48, 58]


def test_rugby_needs_something_to_look_up() -> None:
    with pytest.raises(ValueError, match="espn event id"):
        rugby.load_events()
    with pytest.raises(ValueError, match="date ranges"):
        rugby.load_scoreboard("six_nations")


def test_no_stray_warnings_from_the_gsr_path() -> None:
    with warnings.catch_warnings():
        warnings.simplefilter("error")
        soccernet.load_tracking(fixture_path("soccernet", "gsr", "SNGS-056"))

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


def _sc_events(**kwargs: object) -> pd.DataFrame:
    return skillcorner.load_events(
        1886347,
        match_file=fixture_path(SC, "1886347_match.json"),
        events_file=fixture_path(SC, "1886347_dynamic_events_head.csv"),
        **kwargs,
    )


def test_skillcorner_events_are_already_in_the_acting_teams_frame() -> None:
    """Verified against tracking: a right_to_left row's x_start is the negation of the same
    player's tracked position in the same frame, so the feed is pre-rotated. Flipping by
    attacking_side would undo that and leave events in the absolute match frame."""
    import json as _json

    raw = pd.read_csv(fixture_path(SC, "1886347_dynamic_events_head.csv"), low_memory=False)
    positions: dict[int, dict[int, tuple[float, float]]] = {}
    with fixture_path(SC, "1886347_tracking_head.jsonl").open() as fh:
        for line in fh:
            frame = _json.loads(line)
            if frame.get("period") is None:
                continue
            positions[frame["frame"]] = {
                p["player_id"]: (p["x"], p["y"]) for p in frame.get("player_data") or []
            }

    overlap = raw.loc[raw["frame_start"].isin(positions)]
    assert len(overlap) > 0
    checked = 0
    for _, row in overlap.iterrows():
        tracked = positions[int(row["frame_start"])].get(int(row["player_id"]))
        if tracked is None:
            continue
        sign = 1.0 if row["attacking_side"] == "left_to_right" else -1.0
        assert row["x_start"] == pytest.approx(sign * tracked[0], abs=0.01)
        assert row["y_start"] == pytest.approx(sign * tracked[1], abs=0.01)
        checked += 1
    assert checked > 0

    # ...so in "acting" mode the loader must apply no rotation at all.
    acting = _sc_events(frame="acting")
    assert len(acting) == len(raw)


def test_skillcorner_only_out_of_possession_rows_are_mirrored() -> None:
    possession = _sc_events()
    acting = _sc_events(frame="acting")
    mirrored = sportio.extra_field(possession, "mirrored").map(bool)
    source_type = sportio.extra_field(possession, "event_type")
    # on_ball_engagement is the one type whose actor is the team OFF the ball.
    assert set(source_type[mirrored]) == {"on_ball_engagement"}
    assert "on_ball_engagement" not in set(source_type[~mirrored])

    differs = (possession["x"].astype("float64") - acting["x"].astype("float64")).abs() > 1e-9
    assert differs.sum() == mirrored.sum()


def test_skillcorner_rejects_an_unknown_frame() -> None:
    with pytest.raises(ValueError, match="unknown frame"):
        _sc_events(frame="sideways")


def test_skillcorner_pressure_is_derived_from_the_engagement_subtype() -> None:
    events = skillcorner.load_events(
        1886347,
        match_file=fixture_path(SC, "1886347_match.json"),
        events_file=fixture_path(SC, "1886347_dynamic_events_head.csv"),
    )
    pressured = events.loc[events["pressure"]]
    assert len(pressured) > 0
    assert set(pressured["subtype"].dropna()) <= {
        "pressure",
        "pressing",
        "counter_press",
        "recovery_press",
    }


def test_skillcorner_lineups_report_measured_minutes() -> None:
    lineups = skillcorner.load_lineups(
        1886347, match_file=fixture_path(SC, "1886347_match.json")
    )
    assert tuple(lineups.columns) == sportio.LINEUP_COLUMNS
    assert lineups.groupby("team")["starter"].sum().to_dict() == {
        "Auckland FC": 11,
        "Newcastle United Jets FC": 11,
    }
    # SkillCorner measures playing time itself, so none of this is inferred.
    assert not lineups["minutes_estimated"].any()
    assert lineups["minutes"].max() > 80.0
    assert lineups.loc[lineups["starter"], "minutes"].min() > 0.0


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

    unfiltered = soccernet.load_tracking(fixture_path("soccernet", "gsr", "SNGS-035"), margin=None)
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


def test_soccernet_y_axis_is_flipped_to_point_up_the_pitch() -> None:
    """SoccerNet's +y points at the *bottom* of the broadcast image -- the opposite of
    SkillCorner's, though both call themselves "metres from the pitch centre". Canonical y
    runs up, so it must end up anti-correlated with image-space y."""
    _, det = soccernet.read_gsr(fixture_path("soccernet", "gsr", "SNGS-056"))
    det = det.dropna(subset=["pitch_x", "pitch_y", "image_y"])
    assert len(det) > 20

    _, y = soccernet.SOCCERNET_PITCH.to_canonical(
        det["pitch_x"].astype("float64").to_numpy(),
        det["pitch_y"].astype("float64").to_numpy(),
    )
    image_y = det["image_y"].astype("float64").to_numpy()
    correlation = float(np.corrcoef(image_y, y)[0, 1])
    assert correlation < -0.5, f"canonical y tracks image y (r={correlation:.2f}); axis not flipped"


def test_skillcorner_y_axis_keeps_left_on_the_left() -> None:
    """For a team attacking +x, its left back belongs on the +y side. Mirroring y alone
    would keep every player on the pitch while quietly swapping the wings."""
    import json as _json

    meta = _json.loads(fixture_path(SC, "1886347_match.json").read_text())
    roles = {str(p["id"]): (p.get("player_role") or {}).get("name") or "" for p in meta["players"]}
    tracking = _sc_tracking("1886347_tracking_head.jsonl")  # home normalised to attack +x

    home = tracking.loc[tracking["team"] == "home"]
    by_player = home.groupby("player_id")["y"].mean().astype("float64")
    left = [v for pid, v in by_player.items() if roles.get(str(pid), "").startswith("Left")]
    right = [v for pid, v in by_player.items() if roles.get(str(pid), "").startswith("Right")]
    assert left and right, "fixture roster should name left- and right-sided players"
    assert min(left) > max(right), (
        f"left-sided players at y={sorted(left)} are not on the +y side of "
        f"right-sided players at y={sorted(right)}"
    )


def test_soccernet_mot_drops_referees_rather_than_calling_them_home() -> None:
    _, det = soccernet.read_mot(fixture_path("soccernet", "mot", "SNMOT-116"))
    assert (det["role"] == "referee").any(), "fixture should contain referee tracklets"
    with pytest.warns(UserWarning):
        tracking = soccernet.load_tracking(fixture_path("soccernet", "mot", "SNMOT-116"))
    # Referees have no side in the canonical schema; filing them under "home" would put
    # extra bodies on one team.
    assert len(tracking) == int((det["role"] != "referee").sum())
    assert tracking["team"].value_counts()["home"] == tracking["team"].value_counts()["away"]


def test_soccernet_rejects_a_directory_that_is_neither_format(tmp_path) -> None:
    with pytest.raises(FileNotFoundError, match="neither a GSR sequence"):
        soccernet.load_tracking(tmp_path)


# --------------------------------------------------------------------------------------
# rugby
# --------------------------------------------------------------------------------------


@pytest.fixture(scope="module")
def rugby_events() -> pd.DataFrame:
    return rugby.load_events(summary_file=fixture_path("rugby", "espn_summary_180659_600252.json"))


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


def test_rugby_scoreboard_period_is_inferred_and_flagged() -> None:
    events = rugby.load_events(
        scoreboard_file=fixture_path("rugby", "espn_scoreboard_180659_20250201.json")
    )
    # The scoreboard shape omits period.number entirely, so the clock is the only signal.
    # Dumping everything into period 1 would leave t reading 4918 s.
    assert set(events["period"]) == {1, 2}
    assert float(events["t"].max()) < 2600.0
    assert sportio.extra_field(events, "period_inferred").map(bool).all()

    # The summary shape states the period, so nothing is guessed there.
    summary = rugby.load_events(
        summary_file=fixture_path("rugby", "espn_summary_180659_600252.json")
    )
    assert not sportio.extra_field(summary, "period_inferred").map(bool).any()


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

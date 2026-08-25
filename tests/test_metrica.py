"""Metrica specifics, including the round-trip acceptance test."""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

import sportio
from sportio.loaders import metrica
from sportio.transform import attacking_sign

from .conftest import fixture_path

HOME = "Sample_Game_1_RawTrackingData_Home_Team.trunc.csv"
AWAY = "Sample_Game_1_RawTrackingData_Away_Team.trunc.csv"
EVENTS = "Sample_Game_1_RawEventsData.trunc.csv"


@pytest.fixture(scope="module")
def tracking() -> pd.DataFrame:
    return metrica.load_tracking(
        1,
        home_file=fixture_path("metrica", HOME),
        away_file=fixture_path("metrica", AWAY),
    )


@pytest.fixture(scope="module")
def events() -> pd.DataFrame:
    return metrica.load_events(1, events_file=fixture_path("metrica", EVENTS))


# --------------------------------------------------------------------------------------
# acceptance: round-trip
# --------------------------------------------------------------------------------------


def test_round_trip_through_to_metrica_is_frame_identical(
    tracking: pd.DataFrame, tmp_path
) -> None:
    written = sportio.to_metrica(tracking, tmp_path / "out.csv")
    assert set(written) == {"home", "away"}
    assert all(path.exists() for path in written.values())

    back = metrica.load_tracking(1, home_file=written["home"], away_file=written["away"])

    assert list(back.columns) == list(tracking.columns)
    assert back.shape == tracking.shape
    for column in ("match_id", "period", "frame", "team", "player_id", "jersey"):
        pd.testing.assert_series_equal(
            back[column].reset_index(drop=True),
            tracking[column].reset_index(drop=True),
            check_names=False,
        )
    for column in ("t", "x", "y", "vx", "vy"):
        original = tracking[column].astype("float64").to_numpy()
        reloaded = back[column].astype("float64").to_numpy()
        assert np.array_equal(np.isnan(original), np.isnan(reloaded)), column
        assert reloaded == pytest.approx(original, abs=1e-6, nan_ok=True), column


def test_written_file_keeps_metricas_three_row_header(tracking: pd.DataFrame, tmp_path) -> None:
    written = sportio.to_metrica(tracking, tmp_path / "out.csv")
    lines = written["home"].read_text().splitlines()
    teams, jerseys, names = lines[0].split(","), lines[1].split(","), lines[2].split(",")
    assert names[:3] == ["Period", "Frame", "Time [s]"]
    assert "Ball" in names
    # Player labels sit on the x column only; the y column beside them is blank.
    player_idx = names.index("Player11")
    assert names[player_idx + 1] == ""
    assert teams[player_idx] == "Home"
    assert jerseys[player_idx] == "11"


def test_metrica_paths_derive_the_home_away_pair(tmp_path) -> None:
    paths = sportio.writers.metrica.metrica_paths(tmp_path / "game.csv")
    assert paths["home"].name == "game_Home_Team.csv"
    assert paths["away"].name == "game_Away_Team.csv"
    # Passing one of the derived names back must not double the suffix.
    again = sportio.writers.metrica.metrica_paths(paths["home"])
    assert again == paths


def test_writer_refuses_an_empty_frame(tmp_path) -> None:
    with pytest.raises(ValueError, match="empty tracking frame"):
        sportio.to_metrica(sportio.empty_tracking(), tmp_path / "out.csv")


# --------------------------------------------------------------------------------------
# parsing
# --------------------------------------------------------------------------------------


def test_three_row_header_is_parsed_positionally(tracking: pd.DataFrame) -> None:
    # 11 players per side per frame -- substitutes appear as all-NaN column spans and
    # must not become rows.
    counts = (
        tracking.loc[tracking["team"] == "home"].groupby(["period", "frame"]).size().unique()
    )
    assert set(counts) == {11}
    assert set(tracking.loc[tracking["team"] == "home", "player_id"].unique()) >= {"Player11"}


def test_ball_is_taken_from_one_file_only(tracking: pd.DataFrame) -> None:
    ball = tracking.loc[tracking["team"] == "ball"]
    # The home and away files carry identical ball columns; double-counting would give
    # exactly two rows per frame.
    assert ball.groupby(["period", "frame"]).size().max() == 1


def test_time_restarts_each_period(tracking: pd.DataFrame) -> None:
    # Metrica's Time [s] runs straight through half time; the canonical t must not.
    starts = tracking.groupby("period")["t"].min().astype("float64")
    assert starts.to_dict() == {1: 0.0, 2: 0.0}


def test_direction_is_normalised_so_home_always_attacks_positive_x(
    tracking: pd.DataFrame,
) -> None:
    raw = metrica.load_tracking(
        1,
        home_file=fixture_path("metrica", HOME),
        away_file=fixture_path("metrica", AWAY),
        direction="raw",
    )
    # In the source the teams switch ends between the halves...
    assert attacking_sign(raw, "home") == {1: 1, 2: -1}
    # ...and after normalisation they do not.
    assert attacking_sign(tracking, "home") == {1: 1, 2: 1}
    assert attacking_sign(tracking, "away") == {1: -1, 2: -1}


def test_velocities_are_physically_plausible(tracking: pd.DataFrame) -> None:
    players = tracking.loc[tracking["team"] != "ball"]
    speed = np.hypot(
        players["vx"].astype("float64").fillna(0.0), players["vy"].astype("float64").fillna(0.0)
    )
    assert speed.max() <= 12.0
    assert speed.median() < 6.0


def test_the_period_boundary_does_not_produce_a_velocity_spike(tracking: pd.DataFrame) -> None:
    # The fixture stitches frames 2200-2380 straight onto 72100-72280, so period 2 opens
    # across a 69,720-frame hole. Differencing over it would give ~1500 m/s.
    block = tracking.loc[tracking["period"] == 2]
    first = block.loc[block["frame"] == block["frame"].min()]
    speed = np.hypot(
        first["vx"].astype("float64").fillna(0.0), first["vy"].astype("float64").fillna(0.0)
    )
    assert speed.max() < 12.0


# --------------------------------------------------------------------------------------
# events
# --------------------------------------------------------------------------------------


def test_subtype_tags_are_split_not_string_matched(events: pd.DataFrame) -> None:
    # "HEAD-ON TARGET-GOAL" must yield body_part=head and outcome=goal, and the tag order
    # is not stable across games so the whole string can never be matched.
    goals = events.loc[events["outcome"] == "goal"]
    assert len(goals) >= 2
    headers = events.loc[events["body_part"] == "head"]
    assert len(headers) > 0
    tags = sportio.extra_field(events, "tags")
    assert tags.map(lambda v: isinstance(v, list) or v is None).all()


def test_events_are_rotated_into_the_possession_frame(events: pd.DataFrame) -> None:
    # The same team scores into opposite ends in the two halves of the real match. Once
    # every event is expressed left-to-right for the acting team, both goals must end at
    # the attacked goal, i.e. large x.
    goals = events.loc[(events["outcome"] == "goal") & (events["type"] == "shot")]
    assert len(goals) >= 2
    assert set(goals["period"]) == {1, 2}
    assert (goals["end_x"].astype("float64") > 100.0).all()


def test_raw_direction_leaves_the_match_frame_alone() -> None:
    raw = metrica.load_events(1, events_file=fixture_path("metrica", EVENTS), direction="raw")
    goals = raw.loc[(raw["outcome"] == "goal") & (raw["type"] == "shot")]
    ends = goals["end_x"].astype("float64")
    # Untouched, the two goals sit at opposite ends of the pitch.
    assert ends.min() < 20.0
    assert ends.max() > 90.0


def test_set_pieces_are_recognised_despite_having_no_coordinates(events: pd.DataFrame) -> None:
    corners = sportio.corners(events)
    assert len(corners) > 0
    # Metrica records every SET PIECE row with null coordinates; that is a property of the
    # source, and the loader must not invent a position for them.
    assert corners["x"].isna().all()
    assert set(sportio.set_pieces(events)["subtype"].unique()) <= sportio.SET_PIECE_SUBTYPES


def test_pressure_is_false_because_metrica_has_no_such_flag(events: pd.DataFrame) -> None:
    assert not events["pressure"].any()


def test_event_time_restarts_each_period(events: pd.DataFrame) -> None:
    # Metrica's Start Time [s] is cumulative across the match; period 2 begins at 2850.76 s
    # in the full file. Carrying that through would put every second-half event on a match
    # clock while the schema promises seconds-within-period.
    starts = events.groupby("period")["t"].min().astype("float64")
    assert starts.to_dict() == {1: 0.0, 2: 0.0}
    assert float(events["t"].max()) < 4200.0


def test_events_can_be_aligned_onto_the_tracking_clock(tracking: pd.DataFrame) -> None:
    # Tracking restarts t at the period's first *frame*; the events file's first *event* of
    # the second half is later, so by default the two clocks disagree in period 2.
    starts = metrica.period_starts(tracking)
    assert set(starts) == {1, 2}

    aligned = metrica.load_events(
        1, events_file=fixture_path("metrica", EVENTS), starts=starts
    )
    second_half = aligned.loc[aligned["period"] == 2]
    assert len(second_half) > 0

    frames = sportio.extra_field(second_half, "start_frame")
    checked = 0
    for (_, event), frame in zip(second_half.iterrows(), frames, strict=True):
        match = tracking.loc[(tracking["period"] == 2) & (tracking["frame"] == int(frame))]
        if match.empty:
            continue
        assert float(event["t"]) == pytest.approx(float(match["t"].iloc[0]), abs=1e-6)
        checked += 1
    assert checked > 0, "no event fell inside the truncated tracking window"

    # Without alignment the same events sit on a different clock.
    plain = metrica.load_events(1, events_file=fixture_path("metrica", EVENTS))
    assert float(plain.loc[plain["period"] == 2, "t"].min()) != pytest.approx(
        float(second_half["t"].min())
    )


def test_subtype_raw_keeps_its_internal_spaces(events: pd.DataFrame) -> None:
    # Metrica's atomic tags contain spaces ("ON TARGET", "CORNER KICK"). The player-id
    # cleaner strips internal whitespace, which would corrupt them.
    raws = set(sportio.extra_field(events, "subtype_raw").dropna())
    assert any(" " in value for value in raws)
    assert not any(bad in value for value in raws for bad in ("ONTARGET", "CORNERKICK"))


def test_attack_directions_alternate_away_from_a_period_with_evidence() -> None:
    # A period with no shots and no goal kicks must still switch ends, anchored on a period
    # that did have evidence -- not on the parity of whichever period came first.
    events = metrica.load_events(1, events_file=fixture_path("metrica", EVENTS))
    signs = metrica.attack_directions(events)
    home = sorted({team for team, _ in signs})[0]
    assert signs[(home, 1)] == -signs[(home, 2)]

    blinded = events.loc[~((events["period"] == 1) & (events["type"] == "shot"))].copy()
    blinded.loc[blinded["period"] == 1, "subtype"] = None
    blind_signs = metrica.attack_directions(blinded)
    assert blind_signs[(home, 1)] == -blind_signs[(home, 2)]
    assert blind_signs[(home, 2)] == signs[(home, 2)]


def test_player_ids_are_whitespace_normalised() -> None:
    # Game 2 writes "Player 26" with a space for the same player tracking calls "Player26".
    assert metrica._clean_player_id("Player 26") == "Player26"
    assert metrica._clean_player_id(" Player26 ") == "Player26"

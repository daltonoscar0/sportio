"""Metrica sample game 3 -- the FIFA EPTS format.

The interesting property of this format is that the tracking file has no header: which
``playerN`` column belongs to which player is decided by the ``DataFormatSpecification``
block covering that frame, and the layout is rewritten at every substitution. The fixture
``Sample_Game_3_tracking.slice.txt`` is a two-window slice of the real 53 MB stream --
frames 13560-13589 (period 1) and 120193-120352 (period 2) -- chosen because the second
window straddles the real block boundary at 120212/120213 and reaches live ball again.
"""

from __future__ import annotations

import json

import numpy as np
import pandas as pd
import pytest

from sportio.loaders import metrica_epts
from sportio.schema import (
    EVENT_COLUMNS,
    EVENTS_DTYPES,
    TRACKING_COLUMNS,
    TRACKING_DTYPES,
    validate_events,
    validate_tracking,
)

from .conftest import fixture_path

GAME3 = ("metrica", "game3")
METADATA = "Sample_Game_3_metadata.xml"
SLICE = "Sample_Game_3_tracking.slice.txt"
HEAD = "Sample_Game_3_tracking.head.txt"
EVENTS = "Sample_Game_3_events.slice.json"
EVENTS_HEAD = "Sample_Game_3_events.head.json"

#: The substitution the tracking fixture straddles: shirt 21 off, shirt 35 on, at frame
#: 120213, which is where ``DataFormatSpecification`` block 9 replaces block 8.
BOUNDARY = 120212
OFF, ON = "P3588", "P3700"


@pytest.fixture(scope="module")
def meta() -> metrica_epts.Game3Metadata:
    return metrica_epts.read_metadata(fixture_path(*GAME3, METADATA))


@pytest.fixture(scope="module")
def tracking() -> pd.DataFrame:
    return metrica_epts.load_tracking(
        3,
        metadata_file=fixture_path(*GAME3, METADATA),
        tracking_file=fixture_path(*GAME3, SLICE),
    )


@pytest.fixture(scope="module")
def events() -> pd.DataFrame:
    return metrica_epts.load_events(
        3,
        metadata_file=fixture_path(*GAME3, METADATA),
        events_file=fixture_path(*GAME3, EVENTS),
    )


# --------------------------------------------------------------------------------------
# metadata
# --------------------------------------------------------------------------------------


def test_metadata_reports_the_frame_rate_periods_and_squads(
    meta: metrica_epts.Game3Metadata,
) -> None:
    assert meta.frame_rate == 25.0
    # The halves are back to back: 69662 is the second half's first frame, not a gap.
    assert meta.periods == {1: (1, 69661), 2: (69662, 143761)}
    assert (meta.home_id, meta.away_id) == ("FIFATMA", "FIFATMB")
    assert meta.team_names == {"FIFATMA": "Team A", "FIFATMB": "Team B"}
    assert meta.field_size == (105.0, 68.0)
    assert meta.competition == "Demo"
    assert meta.kickoff == "2019-02-21T03:30:07.000Z"
    assert len(meta.players) == 35
    keeper = meta.players["P3578"]
    assert (keeper.team_id, keeper.jersey, keeper.name) == ("FIFATMA", 11, "Player 11")
    assert keeper.position == "Goalkeeper"


def test_metadata_states_the_attacking_direction_so_none_has_to_be_inferred(
    meta: metrica_epts.Game3Metadata,
) -> None:
    assert meta.attack_first_half == {
        "FIFATMA": "right_to_left",
        "FIFATMB": "left_to_right",
    }
    # Home is Team A, so the source's first half is the one that needs flipping.
    assert meta.home_sign(1) == -1
    assert meta.home_sign(2) == 1


def test_metadata_carries_eleven_column_layouts_covering_the_whole_match(
    meta: metrica_epts.Game3Metadata,
) -> None:
    ranges = [(block.start_frame, block.end_frame) for block in meta.blocks]
    assert ranges == [
        (1, 69661),
        (69662, 89697),
        (89698, 93452),
        (93453, 93835),
        (93836, 94657),
        (94658, 98472),
        (98473, 102811),
        (102812, 110298),
        (110299, 120212),
        (120213, 129831),
        (129832, 143761),
    ]
    assert all(len(block.players) == 22 and block.has_ball for block in meta.blocks)
    # Every layout names 22 distinct players, 11 a side.
    for block in meta.blocks:
        sides = [meta.side(meta.players[pid].team_id) for pid in block.players]
        assert len(set(block.players)) == 22
        assert sides.count("home") == 11 and sides.count("away") == 11


def test_the_same_channel_names_different_players_either_side_of_a_boundary(
    meta: metrica_epts.Game3Metadata,
) -> None:
    before, after = meta.block_at(BOUNDARY), meta.block_at(BOUNDARY + 1)
    assert before is not meta.blocks[0]
    assert (before.end_frame, after.start_frame) == (BOUNDARY, BOUNDARY + 1)
    # player16_x / player16_y, i.e. the sixteenth pair of columns in the row.
    assert before.players[15] == OFF
    assert after.players[15] == ON
    # Nothing else moves at this substitution.
    changed = [i for i, pid in enumerate(before.players) if after.players[i] != pid]
    assert changed == [15]


# --------------------------------------------------------------------------------------
# tracking: the block boundary
# --------------------------------------------------------------------------------------


def test_the_loader_follows_the_layout_change_at_the_boundary(tracking: pd.DataFrame) -> None:
    off = tracking.loc[tracking["player_id"] == OFF, "frame"].astype("int64")
    on = tracking.loc[tracking["player_id"] == ON, "frame"].astype("int64")
    assert off.max() == BOUNDARY
    assert on.min() == BOUNDARY + 1
    # The two never coexist: a loader stuck on one layout would show one of them for the
    # whole slice and the other not at all.
    assert not set(off) & set(on)
    assert tracking.loc[tracking["player_id"] == ON, "jersey"].unique().tolist() == [35]
    assert tracking.loc[tracking["player_id"] == OFF, "jersey"].unique().tolist() == [21]


def test_every_frame_still_holds_eleven_players_a_side(tracking: pd.DataFrame) -> None:
    players = tracking.loc[tracking["team"] != "ball"]
    counts = players.groupby(["frame", "team"]).size().unstack()
    assert (counts == 11).all().all()
    swap = players.loc[players["frame"].isin([BOUNDARY, BOUNDARY + 1])]
    on_pitch = swap.groupby("frame")["player_id"].apply(set)
    assert on_pitch[BOUNDARY] - on_pitch[BOUNDARY + 1] == {OFF}
    assert on_pitch[BOUNDARY + 1] - on_pitch[BOUNDARY] == {ON}


def test_a_naive_first_block_decode_would_have_named_the_wrong_player(
    meta: metrica_epts.Game3Metadata, tracking: pd.DataFrame
) -> None:
    """The failure mode this format invites, stated as an assertion."""
    naive = meta.blocks[0].players[15]
    assert naive != ON
    later = tracking.loc[tracking["frame"] > BOUNDARY, "player_id"]
    assert naive not in set(later)


# --------------------------------------------------------------------------------------
# tracking: the canonical contract
# --------------------------------------------------------------------------------------


def test_tracking_has_exactly_the_canonical_columns_and_dtypes(tracking: pd.DataFrame) -> None:
    assert tuple(tracking.columns) == TRACKING_COLUMNS
    assert {col: str(tracking[col].dtype) for col in tracking} == TRACKING_DTYPES
    validate_tracking(tracking, sample=None)
    assert (tracking["match_id"] == "metrica-3").all()


def test_tracking_is_native_twenty_five_hertz(tracking: pd.DataFrame) -> None:
    for _, block in tracking.groupby("period"):
        steps = np.diff(np.sort(block["t"].astype("float64").unique()))
        # The fixture is two windows, so ignore the jump between them.
        assert steps[steps < 1.0] == pytest.approx(0.04)


def test_t_restarts_at_the_first_frame_of_each_period(tracking: pd.DataFrame) -> None:
    frames = tracking["frame"].astype("int64")
    period = tracking["period"].astype("int64")
    expected = np.where(period == 1, (frames - 1) / 25.0, (frames - 69662) / 25.0)
    assert tracking["t"].astype("float64").to_numpy() == pytest.approx(expected)
    # Period 2 is later in the match but earlier on its own clock than the period-1 window.
    assert tracking.loc[period == 1, "t"].min() == pytest.approx(542.36)
    assert tracking.loc[period == 2, "t"].min() == pytest.approx(2021.24)


def test_home_attacks_positive_x_in_both_periods(tracking: pd.DataFrame) -> None:
    keepers = tracking.loc[tracking["player_id"].isin(["P3578", "P3595"])]
    means = keepers.groupby(["player_id", "period"])["x"].mean().astype("float64")
    # A keeper stands in the half his side is defending, so the home keeper must be on the
    # -x side and the away keeper on the +x side in *both* halves once direction is fixed.
    assert means["P3578"].max() < 52.5
    assert means["P3595"].min() > 52.5


def test_direction_raw_leaves_the_source_geometry_alone() -> None:
    raw = metrica_epts.load_tracking(
        3,
        metadata_file=fixture_path(*GAME3, METADATA),
        tracking_file=fixture_path(*GAME3, SLICE),
        direction="raw",
        velocities=False,
    )
    means = raw.loc[raw["player_id"] == "P3578"].groupby("period")["x"].mean().astype("float64")
    # Team A attacks right_to_left in the first half, so untouched its keeper sits at +x
    # there and at -x after the interval -- which is exactly what home_ltr has to undo.
    assert means[1] > 52.5
    assert means[2] < 52.5


def test_the_ball_is_its_own_team_and_never_a_player(tracking: pd.DataFrame) -> None:
    assert set(tracking["team"].dropna()) == {"home", "away", "ball"}
    ball = tracking.loc[tracking["team"] == "ball"]
    assert ball["player_id"].isna().all()
    assert ball["jersey"].isna().all()
    # The literal "NaN,NaN" rows are dropped rather than carried or forward-filled: the ball
    # is untracked for the dead-ball stretch that runs to frame 120304 in this slice.
    assert len(ball) == 78
    assert set(ball["frame"].astype("int64")) == set(range(13560, 13590)) | set(
        range(120305, 120353)
    )


def test_max_frames_truncates_the_stream() -> None:
    short = metrica_epts.load_tracking(
        3,
        metadata_file=fixture_path(*GAME3, METADATA),
        tracking_file=fixture_path(*GAME3, SLICE),
        max_frames=5,
        velocities=False,
    )
    assert short["frame"].nunique() == 5
    assert short["frame"].astype("int64").max() == 13564


def test_the_head_fixture_is_decoded_with_the_first_layout(
    meta: metrica_epts.Game3Metadata,
) -> None:
    head = metrica_epts.load_tracking(
        3,
        metadata_file=fixture_path(*GAME3, METADATA),
        tracking_file=fixture_path(*GAME3, HEAD),
        velocities=False,
    )
    assert set(head["frame"].astype("int64")) == set(range(1, 12))
    assert head["period"].unique().tolist() == [1]
    assert set(head["player_id"].dropna()) == set(meta.blocks[0].players)
    # The ball is the literal NaN,NaN before kick-off, so these frames carry players only.
    assert set(head["team"]) == {"home", "away"}


# --------------------------------------------------------------------------------------
# events
# --------------------------------------------------------------------------------------


def test_events_have_exactly_the_canonical_columns_and_dtypes(events: pd.DataFrame) -> None:
    assert tuple(events.columns) == EVENT_COLUMNS
    assert {col: str(events[col].dtype) for col in events} == EVENTS_DTYPES
    validate_events(events, sample=None)
    assert (events["match_id"] == "metrica-3").all()
    assert set(events["team_id"].dropna()) == {"home", "away"}
    assert set(events["team"].dropna()) == {"Team A", "Team B"}


def test_events_are_joined_to_players_by_id_not_by_name(events: pd.DataFrame) -> None:
    # "Player 10" has a space in it; the id "P3577" is what matches the tracking column.
    row = events.loc[events["extra"].str.contains('"index":1,')].iloc[0]
    assert row["player_id"] == "P3577"
    assert row["player"] == "Player 10"
    assert events["player_id"].dropna().str.match(r"^P\d+$").all()


def test_event_t_lands_on_the_tracking_clock(events: pd.DataFrame) -> None:
    starts = {1: 1, 2: 69662}
    frames = events["extra"].map(lambda blob: json.loads(blob)["start_frame"])
    expected = [
        (frame - starts[period]) / 25.0
        for frame, period in zip(frames, events["period"].astype("int64"), strict=True)
    ]
    assert events["t"].astype("float64").to_list() == pytest.approx(expected)
    # The file's own cumulative clock is kept, but is not what t means.
    assert json.loads(events["extra"].iloc[0])["match_time"] == 14.44
    assert events["t"].iloc[0] == pytest.approx(14.4)


def test_game_three_adds_a_carry_type(events: pd.DataFrame) -> None:
    head = metrica_epts.load_events(
        3,
        metadata_file=fixture_path(*GAME3, METADATA),
        events_file=fixture_path(*GAME3, EVENTS_HEAD),
    )
    assert "carry" in set(head["type"])
    assert set(events["type"]) <= {
        "pass",
        "shot",
        "recovery",
        "fault_received",
        "set_piece",
        "ball_out",
        "ball_lost",
        "card",
        "challenge",
        "carry",
    }


def test_all_three_shapes_of_subtypes_parse(events: pd.DataFrame) -> None:
    raw = json.loads(fixture_path(*GAME3, EVENTS).read_text())["data"]
    shapes = {type(rec["subtypes"]).__name__ for rec in raw}
    assert shapes == {"NoneType", "dict", "list"}
    by_index = {json.loads(blob)["index"]: row for row, blob in enumerate(events["extra"])}

    # null -> no subtype, no outcome, no tags recorded
    plain = events.iloc[by_index[2]]
    assert pd.isna(plain["subtype"]) and pd.isna(plain["outcome"])
    assert "tags" not in json.loads(plain["extra"])

    # a single object -> one tag, classified as the set piece it is
    single = events.iloc[by_index[1]]
    assert single["subtype"] == "kick_off"
    assert json.loads(single["extra"])["subtype_raw"] == "KICK OFF"

    # a list -> the technique lands in subtype and the result in outcome
    pair = events.iloc[by_index[2073]]
    assert (pair["subtype"], pair["outcome"]) == ("ground", "lost")
    assert json.loads(pair["extra"])["tags"] == ["ground", "lost"]


def test_events_without_coordinates_stay_null(events: pd.DataFrame) -> None:
    missing = events.loc[events["x"].isna()]
    # Six rows in the slice: four kick-offs/throw-ins, a free kick and a yellow card, in
    # both halves -- so the direction flip has to preserve nulls rather than send them to 0.
    assert len(missing) == 6
    assert set(missing["period"]) == {1, 2}
    assert set(missing["type"]) == {"set_piece", "card"}
    for column in ("x", "y", "end_x", "end_y"):
        assert missing[column].isna().all()
        assert not (missing[column] == 0).any()


def test_possession_direction_sends_both_goals_to_the_same_end(events: pd.DataFrame) -> None:
    shots = events.loc[events["outcome"] == "goal"]
    # Team B scores once per half, into opposite ends of the pitch in the source frame.
    assert set(shots["period"]) == {1, 2}
    assert (shots["team_id"] == "away").all()
    assert shots["end_x"].astype("float64").to_numpy() == pytest.approx(106.05)

    raw = metrica_epts.load_events(
        3,
        metadata_file=fixture_path(*GAME3, METADATA),
        events_file=fixture_path(*GAME3, EVENTS),
        direction="raw",
    )
    untouched = raw.loc[raw["outcome"] == "goal"].sort_values("period")["end_x"].astype("float64")
    assert untouched.to_list() == pytest.approx([106.05, -1.05])


def test_an_event_from_an_unknown_team_is_left_where_it_is(tmp_path) -> None:
    payload = json.loads(fixture_path(*GAME3, EVENTS).read_text())
    record = dict(payload["data"][1], team={"name": "Referee", "id": "NOBODY"})
    path = tmp_path / "stray.json"
    path.write_text(json.dumps({"data": [record], "metadata": payload["metadata"]}))

    out = metrica_epts.load_events(
        3, metadata_file=fixture_path(*GAME3, METADATA), events_file=path
    )
    assert pd.isna(out["team_id"].iloc[0])
    # No side means no known attacking direction, so the row keeps the source coordinates.
    expected = record["start"]["x"] * 105.0
    assert out["x"].iloc[0] == pytest.approx(expected)


def test_an_unknown_direction_is_rejected() -> None:
    with pytest.raises(ValueError, match="unknown direction"):
        metrica_epts.load_events(
            3,
            metadata_file=fixture_path(*GAME3, METADATA),
            events_file=fixture_path(*GAME3, EVENTS),
            direction="sideways",
        )

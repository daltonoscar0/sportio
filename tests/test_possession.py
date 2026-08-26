"""Possession chains, normalised across sources that count them completely differently."""

from __future__ import annotations

import pandas as pd
import pytest

import sportio
from sportio.loaders import metrica, skillcorner, statsbomb

from .conftest import fixture_path


@pytest.fixture(scope="module")
def sb_events() -> pd.DataFrame:
    return statsbomb.load_events(
        match=3943043,
        events_file=fixture_path("statsbomb", "events_3943043_slice.json"),
    )


@pytest.fixture(scope="module")
def metrica_events() -> pd.DataFrame:
    return metrica.load_events(
        1, events_file=fixture_path("metrica", "Sample_Game_1_RawEventsData.trunc.csv")
    )


def test_the_vendor_counter_is_used_when_there_is_one(sb_events: pd.DataFrame) -> None:
    # StatsBomb ships a possession chain counter; deriving one would throw it away and
    # would put every defensive Pressure event in its own chain.
    vendor = sportio.extra_field(sb_events, "possession")
    assert vendor.notna().all()
    ids = sportio.possessions(sb_events)
    assert ids.notna().all()
    assert ids.nunique() == vendor.nunique()

    # The grouping must agree with the vendor's, not merely have the same count.
    paired = pd.DataFrame({"ours": ids, "theirs": vendor.astype("string")})
    assert (paired.groupby("theirs")["ours"].nunique() == 1).all()


def test_chains_are_derived_where_the_source_counts_nothing(
    metrica_events: pd.DataFrame,
) -> None:
    assert sportio.extra_field(metrica_events, "possession").isna().all()
    ids = sportio.possessions(metrica_events)
    assert ids.notna().all()
    assert 1 < ids.nunique() < len(metrica_events)

    # Within a chain the acting team never changes -- that is what cut it in the first place.
    tagged = metrica_events.assign(chain=ids)
    assert (tagged.groupby("chain")["team_id"].nunique() == 1).all()


def test_deriving_can_be_switched_off(metrica_events: pd.DataFrame) -> None:
    assert sportio.possessions(metrica_events, derive=False).isna().all()


def test_a_restart_always_begins_a_new_chain(metrica_events: pd.DataFrame) -> None:
    tagged = metrica_events.assign(chain=sportio.possessions(metrica_events))
    restarts = tagged.loc[tagged["subtype"].isin(sportio.SET_PIECE_SUBTYPES)]
    assert len(restarts) > 0
    ordered = tagged.sort_values(["period", "t"], kind="stable").reset_index(drop=True)
    for position in ordered.index[ordered["subtype"].isin(sportio.SET_PIECE_SUBTYPES)]:
        if position == 0:
            continue
        assert ordered.loc[position, "chain"] != ordered.loc[position - 1, "chain"]


def test_ids_never_collide_across_matches(
    sb_events: pd.DataFrame, metrica_events: pd.DataFrame
) -> None:
    # Both sources count from 1 within a match, so a naive pass-through would merge them.
    combined = pd.concat([sb_events, metrica_events], ignore_index=True)
    ids = sportio.possessions(combined)
    per_match = combined.assign(chain=ids).groupby("match_id")["chain"].apply(set)
    assert len(per_match) == 2
    first, second = per_match.tolist()
    assert not (first & second)


def test_add_possession_leaves_the_canonical_frame_alone(sb_events: pd.DataFrame) -> None:
    out = sportio.add_possession(sb_events)
    assert {"possession", "possession_team"} <= set(out.columns)
    assert tuple(sb_events.columns) == sportio.EVENT_COLUMNS
    # StatsBomb names the team on the ball itself, so that label is used rather than guessed.
    assert set(out["possession_team"].dropna()) <= set(sb_events["team"].dropna())


def test_possession_frame_summarises_each_chain(metrica_events: pd.DataFrame) -> None:
    frame = sportio.possession_frame(metrica_events)
    assert len(frame) == sportio.possessions(metrica_events).nunique()
    assert (frame["end_t"] >= frame["start_t"]).all()
    assert (frame["duration"] >= 0).all()
    assert (frame["n_events"] >= 1).all()
    assert frame["n_events"].sum() == len(metrica_events)


def test_possession_spans_need_to_be_told_which_side_is_which() -> None:
    # SkillCorner team ids are vendor numbers, so home/away cannot be guessed from them.
    events = skillcorner.load_events(
        1886347,
        match_file=fixture_path("skillcorner", "1886347_match.json"),
        events_file=fixture_path("skillcorner", "1886347_dynamic_events_head.csv"),
    )
    with pytest.raises(ValueError, match="sides="):
        sportio.possession_spans(events)

    ids = sorted(set(events["team_id"].dropna()))
    spans = sportio.possession_spans(events, sides={ids[0]: "home", ids[1]: "away"})
    assert set(spans["side"]) <= {"home", "away"}
    assert (spans["end_t"] >= spans["start_t"]).all()


def test_spans_are_read_straight_off_metricas_home_away_team_ids(
    metrica_events: pd.DataFrame,
) -> None:
    spans = sportio.possession_spans(metrica_events)
    assert set(spans["side"]) == {"home", "away"}
    assert len(spans) == sportio.possessions(metrica_events).nunique()


def test_an_empty_frame_is_handled(metrica_events: pd.DataFrame) -> None:
    empty = metrica_events.iloc[0:0]
    assert sportio.possessions(empty).empty
    assert sportio.possession_frame(empty).empty
    assert sportio.possession_spans(empty).empty

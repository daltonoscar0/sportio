"""Every loader signs the same contract: exact canonical columns, dtypes and row values.

These run entirely offline against the fixtures under ``tests/fixtures/``.
"""

from __future__ import annotations

import pandas as pd
import pytest

import sportio
from sportio.schema import EVENTS_DTYPES, TRACKING_DTYPES

from .conftest import fixture_path

METRICA = "metrica"
SKILLCORNER = "skillcorner"


def _metrica_tracking_kwargs() -> dict[str, object]:
    return {
        "match": 1,
        "home_file": fixture_path(METRICA, "Sample_Game_1_RawTrackingData_Home_Team.trunc.csv"),
        "away_file": fixture_path(METRICA, "Sample_Game_1_RawTrackingData_Away_Team.trunc.csv"),
    }


EVENT_CASES = {
    "statsbomb": lambda: {
        "match": 3943043,
        "competition": "UEFA Euro",
        "season": "2024",
        "events_file": fixture_path("statsbomb", "events_3943043_slice.json"),
        "three_sixty_file": fixture_path("statsbomb", "three-sixty_3943043_slice.json"),
    },
    "metrica": lambda: {
        "match": 1,
        "events_file": fixture_path(METRICA, "Sample_Game_1_RawEventsData.trunc.csv"),
    },
    "skillcorner": lambda: {
        "match": 1886347,
        "match_file": fixture_path(SKILLCORNER, "1886347_match.json"),
        "events_file": fixture_path(SKILLCORNER, "1886347_dynamic_events_head.csv"),
    },
    "rugby": lambda: {
        "summary_file": fixture_path("rugby", "espn_summary_180659_600252.json"),
    },
}

TRACKING_CASES = {
    "metrica": _metrica_tracking_kwargs,
    "skillcorner": lambda: {
        "match": 1886347,
        "match_file": fixture_path(SKILLCORNER, "1886347_match.json"),
        "tracking_file": fixture_path(SKILLCORNER, "1886347_tracking_head.jsonl"),
    },
    "soccernet": lambda: {"path": fixture_path("soccernet", "gsr", "SNGS-056")},
}


@pytest.fixture(scope="module")
def events() -> dict[str, pd.DataFrame]:
    return {name: sportio.load_events(name, **make()) for name, make in EVENT_CASES.items()}


@pytest.fixture(scope="module")
def tracking() -> dict[str, pd.DataFrame]:
    return {name: sportio.load_tracking(name, **make()) for name, make in TRACKING_CASES.items()}


@pytest.mark.parametrize("source", sorted(EVENT_CASES))
def test_events_match_the_canonical_schema(events: dict[str, pd.DataFrame], source: str) -> None:
    df = events[source]
    assert not df.empty, f"{source} produced no events"
    assert tuple(df.columns) == sportio.EVENT_COLUMNS
    assert dict(df.dtypes.astype(str)) == EVENTS_DTYPES
    sportio.validate_events(df, sample=None)


@pytest.mark.parametrize("source", sorted(TRACKING_CASES))
def test_tracking_matches_the_canonical_schema(
    tracking: dict[str, pd.DataFrame], source: str
) -> None:
    df = tracking[source]
    assert not df.empty, f"{source} produced no tracking"
    assert tuple(df.columns) == sportio.TRACKING_COLUMNS
    assert dict(df.dtypes.astype(str)) == TRACKING_DTYPES
    sportio.validate_tracking(df, sample=None)


@pytest.mark.parametrize("source", sorted(EVENT_CASES))
def test_events_are_ordered_and_timed_per_period(
    events: dict[str, pd.DataFrame], source: str
) -> None:
    df = events[source]
    # t is seconds *within* the period, so every period starts near zero and never runs
    # past a plausible half (a long half plus stoppage).
    for period, block in df.groupby("period"):
        t = block["t"].astype("float64").dropna()
        assert t.min() >= 0.0, f"{source} period {period} has negative t"
        assert t.max() < 4200.0, f"{source} period {period} t looks like a match clock"
        assert t.is_monotonic_increasing, f"{source} period {period} is not sorted by t"


@pytest.mark.parametrize("source", sorted(TRACKING_CASES))
def test_tracking_uses_only_the_three_entity_labels(
    tracking: dict[str, pd.DataFrame], source: str
) -> None:
    df = tracking[source]
    assert set(df["team"].dropna().unique()) <= {"home", "away", "ball"}
    # The ball is not a player and carries no shirt number.
    ball = df.loc[df["team"] == "ball"]
    assert ball["player_id"].isna().all()
    assert ball["jersey"].isna().all()


@pytest.mark.parametrize("source", sorted(TRACKING_CASES))
def test_tracking_meets_the_10hz_minimum(tracking: dict[str, pd.DataFrame], source: str) -> None:
    hz = sportio.native_hz(tracking[source])
    assert hz is not None and hz >= 10.0 - 1e-9, f"{source} sampled at {hz} Hz"


@pytest.mark.parametrize("source", sorted(EVENT_CASES))
def test_event_coordinates_land_on_the_canonical_pitch(
    events: dict[str, pd.DataFrame], source: str
) -> None:
    df = events[source]
    x = df["x"].astype("float64").dropna()
    y = df["y"].astype("float64").dropna()
    if x.empty:
        # Rugby genuinely has no coordinates; that is a documented property, not a bug.
        assert source == "rugby"
        return
    assert x.between(-10, 115).all()
    assert y.between(-8, 76).all()
    # A source that forgot to rescale would sit almost entirely in the left/bottom corner.
    assert x.max() > 60.0
    assert y.max() > 40.0


def test_extra_is_always_parseable_json(events: dict[str, pd.DataFrame]) -> None:
    import json

    for source, df in events.items():
        parsed = df["extra"].map(json.loads)
        assert parsed.map(lambda v: isinstance(v, dict)).all(), source


def test_set_piece_subtypes_use_the_shared_vocabulary(events: dict[str, pd.DataFrame]) -> None:
    seen = set()
    for df in events.values():
        seen |= set(sportio.set_pieces(df)["subtype"].dropna().unique())
    assert seen <= sportio.SET_PIECE_SUBTYPES
    # StatsBomb and Metrica should both contribute corners, from totally different encodings.
    assert "corner" in seen


def test_set_piece_window_survives_a_null_group_key(events: dict[str, pd.DataFrame]) -> None:
    # groupby hands back float('nan') from .indices but pd.NA as a group key, so matching one
    # against the other silently drops that whole group. A single-match, single-period slice
    # stays one group whichever key is nulled, so the row count must not move.
    df = events["metrica"]
    df = df.loc[df["period"] == 1].reset_index(drop=True)
    baseline = len(sportio.set_pieces(df, window=5.0))
    assert baseline > 0
    for column in ("match_id", "period"):
        holed = df.copy()
        holed[column] = pd.NA
        assert len(sportio.set_pieces(holed, window=5.0)) == baseline, column


def test_registry_reports_what_each_source_actually_provides() -> None:
    table = sportio.source_table()
    assert set(table["source"]) == set(sportio.sources())
    for source in EVENT_CASES:
        assert bool(table.loc[table["source"] == source, "events"].iloc[0])
    for source in TRACKING_CASES:
        assert bool(table.loc[table["source"] == source, "tracking"].iloc[0])


def test_asking_a_source_for_data_it_lacks_is_an_error() -> None:
    with pytest.raises(ValueError, match="no tracking data"):
        sportio.load_tracking("statsbomb")
    with pytest.raises(ValueError, match="no event data"):
        sportio.load_events("soccernet")
    with pytest.raises(KeyError, match="unknown source"):
        sportio.load_events("opta")

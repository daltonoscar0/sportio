"""The canonical schema is the contract every loader signs; test it hard."""

from __future__ import annotations

import json

import pandas as pd
import pytest

import sportio
from sportio.schema import EVENTS_DTYPES, TRACKING_DTYPES, SchemaError, encode_extra


def _one_event(**overrides: object) -> pd.DataFrame:
    row = {
        "match_id": 3943043,
        "competition": "UEFA Euro",
        "season": "2024",
        "team_id": 941,
        "team": "Spain",
        "player_id": 30714,
        "player": "Rodri",
        "t": 12.5,
        "period": 1,
        "type": "pass",
        "subtype": "corner",
        "x": 105.0,
        "y": 68.0,
        "end_x": 94.0,
        "end_y": 34.0,
        "outcome": "complete",
        "pressure": True,
        "body_part": "right_foot",
        "extra": encode_extra({"id": "abc"}),
    }
    row.update(overrides)
    return pd.DataFrame([row])


def _one_track(**overrides: object) -> pd.DataFrame:
    row = {
        "match_id": "1",
        "t": 0.04,
        "period": 1,
        "frame": 1,
        "team": "home",
        "player_id": "Player11",
        "jersey": 11,
        "x": 0.09,
        "y": 35.2,
        "vx": None,
        "vy": None,
        "confidence": None,
    }
    row.update(overrides)
    return pd.DataFrame([row])


def test_empty_frames_have_the_canonical_shape() -> None:
    assert tuple(sportio.empty_events().columns) == sportio.EVENT_COLUMNS
    assert tuple(sportio.empty_tracking().columns) == sportio.TRACKING_COLUMNS
    assert dict(sportio.empty_events().dtypes.astype(str)) == EVENTS_DTYPES
    assert dict(sportio.empty_tracking().dtypes.astype(str)) == TRACKING_DTYPES
    sportio.validate_events(sportio.empty_events())
    sportio.validate_tracking(sportio.empty_tracking())


def test_conform_coerces_dtypes_and_column_order() -> None:
    raw = _one_event()[list(reversed(sportio.EVENT_COLUMNS))]
    out = sportio.conform_events(raw)
    assert tuple(out.columns) == sportio.EVENT_COLUMNS
    assert dict(out.dtypes.astype(str)) == EVENTS_DTYPES
    sportio.validate_events(out)


def test_numeric_ids_become_clean_strings() -> None:
    out = sportio.conform_events(_one_event(match_id=3943043, player_id=30714.0))
    assert out.loc[0, "match_id"] == "3943043"
    assert out.loc[0, "player_id"] == "30714"


def test_missing_column_is_an_error() -> None:
    with pytest.raises(SchemaError, match="missing columns"):
        sportio.conform_events(_one_event().drop(columns=["body_part"]))


def test_validate_rejects_off_pitch_coordinates() -> None:
    bad = sportio.conform_events(_one_event(x=150.0))
    with pytest.raises(SchemaError, match="row 0 is invalid"):
        sportio.validate_events(bad, sample=None)


def test_validate_rejects_unknown_tracking_team() -> None:
    bad = sportio.conform_tracking(_one_track(team="Home FC"))
    with pytest.raises(SchemaError):
        sportio.validate_tracking(bad, sample=None)


def test_extra_is_always_a_json_object() -> None:
    out = sportio.conform_events(_one_event(extra=None))
    assert out.loc[0, "extra"] == "{}"
    assert json.loads(out.loc[0, "extra"]) == {}
    with pytest.raises(SchemaError):
        sportio.validate_events(sportio.conform_events(_one_event(extra="[1,2]")), sample=None)


def test_encode_extra_is_stable_and_compact() -> None:
    assert encode_extra({"b": 1, "a": 2}) == '{"a":2,"b":1}'
    assert encode_extra(None) == "{}"
    assert encode_extra({}) == "{}"


def test_pressure_defaults_to_false_not_null() -> None:
    out = sportio.conform_events(_one_event(pressure=None))
    assert out.loc[0, "pressure"] is False or out.loc[0, "pressure"] == False  # noqa: E712
    sportio.validate_events(out, sample=None)

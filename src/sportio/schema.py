"""Canonical dataframe schemas.

Every loader in :mod:`sportio.loaders` returns one of exactly two shapes, defined here
once and enforced by :func:`conform_events` / :func:`conform_tracking`. Nothing
downstream should ever have to know which vendor a row came from.
"""

from __future__ import annotations

import json
from collections.abc import Iterable, Mapping
from typing import Any, Literal

import pandas as pd
from pydantic import BaseModel, ConfigDict, Field, field_validator

__all__ = [
    "EVENTS_DTYPES",
    "EVENT_COLUMNS",
    "TRACKING_COLUMNS",
    "TRACKING_DTYPES",
    "EventRow",
    "SchemaError",
    "TrackingRow",
    "conform_events",
    "conform_tracking",
    "empty_events",
    "empty_tracking",
    "encode_extra",
    "validate_events",
    "validate_tracking",
]


class SchemaError(ValueError):
    """Raised when a dataframe does not match a canonical schema."""


# --------------------------------------------------------------------------------------
# column order and dtypes
# --------------------------------------------------------------------------------------

# Nullable extension dtypes throughout, so "missing" is representable in every column
# without silently promoting ints to floats.
EVENTS_DTYPES: dict[str, str] = {
    "match_id": "string",
    "competition": "string",
    "season": "string",
    "team_id": "string",
    "team": "string",
    "player_id": "string",
    "player": "string",
    "t": "Float64",
    "period": "Int16",
    "type": "string",
    "subtype": "string",
    "x": "Float64",
    "y": "Float64",
    "end_x": "Float64",
    "end_y": "Float64",
    "outcome": "string",
    "pressure": "boolean",
    "body_part": "string",
    "extra": "string",
}

TRACKING_DTYPES: dict[str, str] = {
    "match_id": "string",
    "t": "Float64",
    "period": "Int16",
    "frame": "Int64",
    "team": "string",
    "player_id": "string",
    "jersey": "Int16",
    "x": "Float64",
    "y": "Float64",
    "vx": "Float64",
    "vy": "Float64",
    "confidence": "Float64",
}

EVENT_COLUMNS: tuple[str, ...] = tuple(EVENTS_DTYPES)
TRACKING_COLUMNS: tuple[str, ...] = tuple(TRACKING_DTYPES)

TEAM_SIDES: frozenset[str] = frozenset({"home", "away", "ball"})


# --------------------------------------------------------------------------------------
# pydantic row models
# --------------------------------------------------------------------------------------


class EventRow(BaseModel):
    """One row of the canonical ``events`` frame."""

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    match_id: str
    competition: str
    season: str
    team_id: str | None = None
    team: str | None = None
    player_id: str | None = None
    player: str | None = None
    t: float
    period: int = Field(ge=1, le=5)
    type: str
    subtype: str | None = None
    x: float | None = Field(default=None, ge=-1.0, le=106.0)
    y: float | None = Field(default=None, ge=-1.0, le=69.0)
    end_x: float | None = Field(default=None, ge=-1.0, le=106.0)
    end_y: float | None = Field(default=None, ge=-1.0, le=69.0)
    outcome: str | None = None
    pressure: bool = False
    body_part: str | None = None
    extra: str = "{}"

    @field_validator("extra")
    @classmethod
    def _extra_is_json_object(cls, v: str) -> str:
        try:
            parsed = json.loads(v)
        except json.JSONDecodeError as exc:  # pragma: no cover - defensive
            raise ValueError(f"extra must be a JSON string: {exc}") from exc
        if not isinstance(parsed, dict):
            raise ValueError("extra must encode a JSON object")
        return v


class TrackingRow(BaseModel):
    """One row of the canonical ``tracking`` frame."""

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    match_id: str
    t: float
    period: int = Field(ge=1, le=5)
    frame: int
    team: Literal["home", "away", "ball"]
    player_id: str | None = None
    jersey: int | None = None
    x: float | None = Field(default=None, ge=-20.0, le=125.0)
    y: float | None = Field(default=None, ge=-20.0, le=88.0)
    vx: float | None = None
    vy: float | None = None
    confidence: float | None = Field(default=None, ge=0.0, le=1.0)


# --------------------------------------------------------------------------------------
# frame construction
# --------------------------------------------------------------------------------------


def encode_extra(payload: Mapping[str, Any] | None) -> str:
    """Serialise a per-event payload into the ``extra`` column's JSON string."""
    if not payload:
        return "{}"
    return json.dumps(payload, separators=(",", ":"), sort_keys=True, default=_json_default)


def _json_default(obj: Any) -> Any:
    if isinstance(obj, (set, frozenset)):
        return sorted(obj)
    if hasattr(obj, "item"):  # numpy scalars
        return obj.item()
    if hasattr(obj, "tolist"):  # numpy arrays
        return obj.tolist()
    return str(obj)


def _conform(df: pd.DataFrame, dtypes: Mapping[str, str], kind: str) -> pd.DataFrame:
    missing = [c for c in dtypes if c not in df.columns]
    if missing:
        raise SchemaError(f"{kind} frame is missing columns: {missing}")
    out = df.loc[:, list(dtypes)].copy()
    for col, dtype in dtypes.items():
        try:
            out[col] = _cast(out[col], dtype)
        except (TypeError, ValueError) as exc:
            raise SchemaError(f"{kind}.{col} cannot be cast to {dtype}: {exc}") from exc
    return out.reset_index(drop=True)


def _cast(series: pd.Series, dtype: str) -> pd.Series:
    if dtype == "string":
        # Go through object so that numeric ids (1234) become "1234" rather than "1234.0".
        return series.map(_stringify, na_action="ignore").astype("string")
    if dtype in {"Int16", "Int64"}:
        # float -> Int is only allowed when values are integral; round-trip via Float64.
        return pd.to_numeric(series, errors="coerce").astype("Float64").round().astype(dtype)
    if dtype == "Float64":
        return pd.to_numeric(series, errors="coerce").astype("Float64")
    if dtype == "boolean":
        return series.astype("boolean")
    raise SchemaError(f"unsupported dtype {dtype!r}")  # pragma: no cover - defensive


def _stringify(value: Any) -> Any:
    if isinstance(value, str):
        return value
    if isinstance(value, float) and value.is_integer():
        return str(int(value))
    return str(value)


def conform_events(df: pd.DataFrame) -> pd.DataFrame:
    """Coerce ``df`` to the canonical events schema (exact columns, order and dtypes)."""
    out = _conform(df, EVENTS_DTYPES, "events")
    out["pressure"] = out["pressure"].fillna(False)
    out["extra"] = out["extra"].fillna("{}")
    return out


def conform_tracking(df: pd.DataFrame) -> pd.DataFrame:
    """Coerce ``df`` to the canonical tracking schema (exact columns, order and dtypes)."""
    return _conform(df, TRACKING_DTYPES, "tracking")


def empty_events() -> pd.DataFrame:
    """An events frame with zero rows and the canonical columns/dtypes."""
    return _empty(EVENTS_DTYPES)


def empty_tracking() -> pd.DataFrame:
    """A tracking frame with zero rows and the canonical columns/dtypes."""
    return _empty(TRACKING_DTYPES)


def _empty(dtypes: Mapping[str, str]) -> pd.DataFrame:
    return pd.DataFrame({col: pd.Series([], dtype=dt) for col, dt in dtypes.items()})


def concat_events(frames: Iterable[pd.DataFrame]) -> pd.DataFrame:
    """Concatenate events frames, preserving the canonical schema for an empty input."""
    return _concat(frames, empty_events())


def concat_tracking(frames: Iterable[pd.DataFrame]) -> pd.DataFrame:
    """Concatenate tracking frames, preserving the canonical schema for an empty input."""
    return _concat(frames, empty_tracking())


def _concat(frames: Iterable[pd.DataFrame], empty: pd.DataFrame) -> pd.DataFrame:
    frames = [f for f in frames if len(f)]
    if not frames:
        return empty
    return pd.concat(frames, ignore_index=True)


# --------------------------------------------------------------------------------------
# validation
# --------------------------------------------------------------------------------------


def _validate(
    df: pd.DataFrame,
    dtypes: Mapping[str, str],
    model: type[BaseModel],
    kind: str,
    sample: int | None,
) -> pd.DataFrame:
    if tuple(df.columns) != tuple(dtypes):
        raise SchemaError(
            f"{kind} columns are {tuple(df.columns)}; expected exactly {tuple(dtypes)}"
        )
    wrong = {
        col: str(df[col].dtype) for col, dt in dtypes.items() if str(df[col].dtype) != dt
    }
    if wrong:
        raise SchemaError(f"{kind} dtypes are wrong: {wrong} (expected {dict(dtypes)})")

    rows = df if sample is None or len(df) <= sample else df.sample(sample, random_state=0)
    for idx, record in zip(rows.index, rows.to_dict(orient="records"), strict=True):
        payload = {k: (None if v is pd.NA or v != v else v) for k, v in record.items()}  # noqa: PLR0124
        try:
            model.model_validate(payload)
        except Exception as exc:  # pydantic.ValidationError
            raise SchemaError(f"{kind} row {idx} is invalid: {exc}") from exc
    return df


def validate_events(df: pd.DataFrame, sample: int | None = 500) -> pd.DataFrame:
    """Validate columns, dtypes and (a sample of) row values. Returns ``df`` unchanged."""
    df = _validate(df, EVENTS_DTYPES, EventRow, "events", sample)
    bad = df.loc[df["team"].notna() & df["match_id"].isna()]
    if len(bad):
        raise SchemaError(f"{len(bad)} events rows have no match_id")
    return df


def validate_tracking(df: pd.DataFrame, sample: int | None = 500) -> pd.DataFrame:
    """Validate columns, dtypes and (a sample of) row values. Returns ``df`` unchanged."""
    df = _validate(df, TRACKING_DTYPES, TrackingRow, "tracking", sample)
    sides = set(df["team"].dropna().unique()) - TEAM_SIDES
    if sides:
        raise SchemaError(f"tracking.team contains unexpected values: {sorted(sides)}")
    return df

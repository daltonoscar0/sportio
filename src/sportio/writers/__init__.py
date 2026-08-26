"""Writers, for round-tripping canonical frames back out to disk."""

from __future__ import annotations

from pathlib import Path

import pandas as pd

from .metrica import metrica_paths, to_metrica
from .skillcorner import skillcorner_paths, to_skillcorner
from .statsbomb import to_statsbomb

__all__ = [
    "metrica_paths",
    "skillcorner_paths",
    "to_csv",
    "to_metrica",
    "to_parquet",
    "to_skillcorner",
    "to_statsbomb",
]


def to_csv(df: pd.DataFrame, path: str | Path) -> Path:
    """Write a canonical frame as plain CSV, preserving the JSON ``extra`` column verbatim."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    df.to_csv(path, index=False)
    return path


def to_parquet(df: pd.DataFrame, path: str | Path) -> Path:
    """Write a canonical frame as Parquet. Requires ``pyarrow``, which sportio does not pin."""
    try:
        import pyarrow  # noqa: F401
    except ImportError as exc:  # pragma: no cover - depends on the caller's env
        raise ImportError(
            "to_parquet needs pyarrow, which sportio deliberately does not depend on. "
            "Install it with `uv pip install pyarrow`."
        ) from exc
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    df.to_parquet(path, index=False)
    return path

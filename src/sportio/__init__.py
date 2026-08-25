"""sportio -- shared data layer for the sports tools suite.

Every open soccer and rugby source the suite uses is normalised into exactly two
dataframes, ``events`` and ``tracking``. Downstream tools import this and nothing else
touches a vendor schema.

    >>> import sportio
    >>> ev = sportio.load_events("statsbomb", competition="Euro 2024")
    >>> tr = sportio.load_tracking("metrica", match=1)
    >>> corners = sportio.corners(ev)
    >>> sportio.to_metrica(tr, "out.csv")
"""

from __future__ import annotations

from .pitch import PITCH_LENGTH, PITCH_WIDTH, PitchSpec
from .registry import SourceInfo, get_source, load_events, load_tracking, source_table, sources
from .schema import (
    EVENT_COLUMNS,
    TRACKING_COLUMNS,
    SchemaError,
    conform_events,
    conform_tracking,
    empty_events,
    empty_tracking,
    validate_events,
    validate_tracking,
)
from .setpieces import (
    SET_PIECE_SUBTYPES,
    corners,
    extra_field,
    freeze_frame_size,
    freeze_frames,
    set_pieces,
)
from .transform import add_velocities, native_hz, normalize_direction, resample_tracking
from .writers import to_csv, to_metrica, to_parquet

__version__ = "0.1.0"

__all__ = [
    "EVENT_COLUMNS",
    "PITCH_LENGTH",
    "PITCH_WIDTH",
    "SET_PIECE_SUBTYPES",
    "TRACKING_COLUMNS",
    "PitchSpec",
    "SchemaError",
    "SourceInfo",
    "__version__",
    "add_velocities",
    "conform_events",
    "conform_tracking",
    "corners",
    "empty_events",
    "empty_tracking",
    "extra_field",
    "freeze_frame_size",
    "freeze_frames",
    "get_source",
    "load_events",
    "load_tracking",
    "native_hz",
    "normalize_direction",
    "resample_tracking",
    "set_pieces",
    "source_table",
    "sources",
    "to_csv",
    "to_metrica",
    "to_parquet",
    "validate_events",
    "validate_tracking",
]

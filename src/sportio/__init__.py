"""sportio -- shared data layer for the sports tools suite.

Every open soccer and rugby source the suite uses is normalised into exactly two
dataframes, ``events`` and ``tracking``, with a third auxiliary ``lineups`` frame for the
squad metadata neither of them can carry. Downstream tools import this and nothing else
touches a vendor schema.

    >>> import sportio
    >>> ev = sportio.load_events("statsbomb", competition="Euro 2024")
    >>> tr = sportio.load_tracking("metrica", match=1)
    >>> corners = sportio.corners(ev)
    >>> sportio.to_metrica(tr, "out.csv")
"""

from __future__ import annotations

from .enrich import (
    add_pressure_from_tracking,
    enrich_from_tracking,
    fill_coordinates_from_tracking,
    nearest_opponent_distance,
)
from .pitch import PITCH_LENGTH, PITCH_WIDTH, STATSBOMB_LANDMARK, PitchSpec
from .possession import add_possession, possession_frame, possession_spans, possessions
from .registry import (
    SourceInfo,
    get_source,
    load_events,
    load_lineups,
    load_tracking,
    source_table,
    sources,
)
from .schema import (
    EVENT_COLUMNS,
    LINEUP_COLUMNS,
    TRACKING_COLUMNS,
    SchemaError,
    conform_events,
    conform_lineups,
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
from .writers import to_csv, to_metrica, to_parquet, to_skillcorner, to_statsbomb
from .zones import (
    CHANNELS,
    THIRDS,
    ZONES_12,
    ZONES_18,
    ZONES_24,
    Grid,
    add_zones,
    zone_centres,
    zone_labels,
    zones,
)

__version__ = "0.1.0"

__all__ = [
    "CHANNELS",
    "EVENT_COLUMNS",
    "LINEUP_COLUMNS",
    "PITCH_LENGTH",
    "PITCH_WIDTH",
    "SET_PIECE_SUBTYPES",
    "STATSBOMB_LANDMARK",
    "THIRDS",
    "TRACKING_COLUMNS",
    "ZONES_12",
    "ZONES_18",
    "ZONES_24",
    "Grid",
    "PitchSpec",
    "SchemaError",
    "SourceInfo",
    "__version__",
    "add_possession",
    "add_pressure_from_tracking",
    "add_velocities",
    "add_zones",
    "conform_events",
    "conform_lineups",
    "conform_tracking",
    "corners",
    "empty_events",
    "empty_tracking",
    "enrich_from_tracking",
    "extra_field",
    "fill_coordinates_from_tracking",
    "freeze_frame_size",
    "freeze_frames",
    "get_source",
    "load_events",
    "load_lineups",
    "load_tracking",
    "native_hz",
    "nearest_opponent_distance",
    "normalize_direction",
    "possession_frame",
    "possession_spans",
    "possessions",
    "resample_tracking",
    "set_pieces",
    "source_table",
    "sources",
    "to_csv",
    "to_metrica",
    "to_parquet",
    "to_skillcorner",
    "to_statsbomb",
    "validate_events",
    "validate_tracking",
    "zone_centres",
    "zone_labels",
    "zones",
]

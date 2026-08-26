"""Source registry: the one place that knows which loaders exist."""

from __future__ import annotations

import importlib
from dataclasses import dataclass, field
from types import ModuleType
from typing import Any

import pandas as pd

__all__ = [
    "SourceInfo",
    "get_source",
    "load_events",
    "load_lineups",
    "load_tracking",
    "source_table",
    "sources",
]


@dataclass(frozen=True, slots=True)
class SourceInfo:
    """Static description of a data source, used by ``sportio info`` and the README."""

    name: str
    module: str
    title: str
    url: str
    license: str
    events: bool
    tracking: bool
    lineups: bool = False
    notes: str = ""
    extras: tuple[str, ...] = field(default=())


SOURCES: dict[str, SourceInfo] = {
    "statsbomb": SourceInfo(
        name="statsbomb",
        module="sportio.loaders.statsbomb",
        title="StatsBomb Open Data",
        url="https://github.com/statsbomb/open-data",
        license="StatsBomb Open Data User Agreement (non-commercial, attribution)",
        events=True,
        tracking=False,
        lineups=True,
        notes="Events plus 360 freeze frames; freeze frames land in events.extra['freeze_frame'].",
    ),
    "metrica": SourceInfo(
        name="metrica",
        module="sportio.loaders.metrica",
        title="Metrica Sports Sample Data",
        url="https://github.com/metrica-sports/sample-data",
        license="CC BY-NC-SA 4.0",
        events=True,
        tracking=True,
        notes="Three fully-tracked sample matches at 25 Hz; game 3 is the FIFA EPTS format.",
    ),
    "skillcorner": SourceInfo(
        name="skillcorner",
        module="sportio.loaders.skillcorner",
        title="SkillCorner Open Data",
        url="https://github.com/SkillCorner/opendata",
        license="CC BY-NC-SA 4.0",
        events=True,
        tracking=True,
        lineups=True,
        notes="Ten A-League matches: 10 Hz broadcast tracking plus derived dynamic events.",
    ),
    "soccernet": SourceInfo(
        name="soccernet",
        module="sportio.loaders.soccernet",
        title="SoccerNet Game State Reconstruction (SN-GSR-2025)",
        url="https://huggingface.co/datasets/SoccerNet/SN-GSR-2025",
        license="GPL-3.0 (GSR, public). SoccerNet-Tracking MOT is separate and NDA-gated.",
        events=False,
        tracking=True,
        notes="Labels are range-fetched from the split zip: 192 MB, not the archive's 11.2 GB.",
    ),
    "rugby": SourceInfo(
        name="rugby",
        module="sportio.loaders.rugby",
        title="Rugby play-by-play (ESPN / rugbypy)",
        url="https://github.com/seanyboi/rugbypy",
        license="see source; ESPN content is used under fair-use for research",
        events=True,
        tracking=False,
        notes="Commentary-derived events; positional columns are mostly null (see docs).",
    ),
}


def sources() -> list[str]:
    """Names of every registered source."""
    return sorted(SOURCES)


def get_source(name: str) -> SourceInfo:
    try:
        return SOURCES[name.strip().lower()]
    except KeyError:
        raise KeyError(f"unknown source {name!r}; known sources: {sources()}") from None


def _module(name: str) -> ModuleType:
    return importlib.import_module(get_source(name).module)


def load_events(source: str, **kwargs: Any) -> pd.DataFrame:
    """Load canonical events from ``source``. See each loader for its keyword arguments."""
    info = get_source(source)
    if not info.events:
        raise ValueError(f"source {info.name!r} has no event data")
    return _module(info.name).load_events(**kwargs)


def load_tracking(source: str, **kwargs: Any) -> pd.DataFrame:
    """Load canonical tracking from ``source``. See each loader for its keyword arguments."""
    info = get_source(source)
    if not info.tracking:
        raise ValueError(f"source {info.name!r} has no tracking data")
    return _module(info.name).load_tracking(**kwargs)


def load_lineups(source: str, **kwargs: Any) -> pd.DataFrame:
    """Load the auxiliary squad frame from ``source`` (shirt numbers, positions, minutes)."""
    info = get_source(source)
    if not info.lineups:
        raise ValueError(f"source {info.name!r} publishes no squad data")
    return _module(info.name).load_lineups(**kwargs)


def source_table() -> pd.DataFrame:
    """One row per source: what it provides and under what licence."""
    return pd.DataFrame(
        [
            {
                "source": s.name,
                "title": s.title,
                "events": s.events,
                "tracking": s.tracking,
                "lineups": s.lineups,
                "license": s.license,
                "url": s.url,
                "notes": s.notes,
            }
            for s in (SOURCES[k] for k in sources())
        ]
    )

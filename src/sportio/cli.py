"""``sportio`` command line: fetch, validate, info."""

from __future__ import annotations

import argparse
import json
import logging
import sys
from pathlib import Path
from typing import Any

import pandas as pd

from . import __version__
from .paths import data_root
from .registry import SOURCES, get_source, load_events, load_tracking, source_table, sources
from .schema import (
    EVENT_COLUMNS,
    TRACKING_COLUMNS,
    SchemaError,
    conform_events,
    conform_tracking,
    validate_events,
    validate_tracking,
)
from .setpieces import corners
from .writers import to_csv, to_parquet

__all__ = ["main"]

log = logging.getLogger("sportio")


def main(argv: list[str] | None = None) -> int:
    parser = _parser()
    args = parser.parse_args(argv)
    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(levelname)s %(name)s: %(message)s",
    )
    try:
        return int(args.handler(args) or 0)
    except (SchemaError, LookupError, ValueError, FileNotFoundError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="sportio",
        description="Shared data layer for the sports tools suite.",
    )
    parser.add_argument("--version", action="version", version=f"sportio {__version__}")
    parser.add_argument("-v", "--verbose", action="store_true", help="debug logging")
    sub = parser.add_subparsers(dest="command", required=True)

    info = sub.add_parser("info", help="list sources, licences and what each provides")
    info.add_argument("source", nargs="?", help="show detail for one source")
    info.add_argument("--json", action="store_true", help="machine-readable output")
    info.set_defaults(handler=_cmd_info)

    fetch = sub.add_parser("fetch", help="download a source and normalise it")
    fetch.add_argument("source", choices=sources())
    fetch.add_argument("--competition", help='e.g. "Euro 2024" (statsbomb)')
    fetch.add_argument("--season", help="season label, to disambiguate a competition")
    fetch.add_argument("--match", help="a single match id")
    fetch.add_argument("--date", help="YYYYMMDD (rugby)")
    fetch.add_argument(
        "--split", help="soccernet split: train, valid, test or challenge (default valid)"
    )
    fetch.add_argument("--limit", type=int, help="cap how many matches are loaded")
    fetch.add_argument(
        "--kind",
        choices=("events", "tracking", "both"),
        default="both",
        help="what to load; defaults to whatever the source provides",
    )
    fetch.add_argument("--out", type=Path, help="write the canonical frame here (.csv/.parquet)")
    fetch.set_defaults(handler=_cmd_fetch)

    validate = sub.add_parser("validate", help="check a file against the canonical schema")
    validate.add_argument("path", type=Path)
    validate.add_argument("--source", choices=sources(), help="override source detection")
    validate.add_argument("--kind", choices=("events", "tracking"), help="override kind detection")
    validate.set_defaults(handler=_cmd_validate)

    return parser


# --------------------------------------------------------------------------------------
# info
# --------------------------------------------------------------------------------------


def _cmd_info(args: argparse.Namespace) -> int:
    if args.source:
        info = get_source(args.source)
        payload = {
            "source": info.name,
            "title": info.title,
            "events": info.events,
            "tracking": info.tracking,
            "license": info.license,
            "url": info.url,
            "notes": info.notes,
            "extras": list(info.extras),
        }
        print(json.dumps(payload, indent=2) if args.json else _describe(payload))
        return 0

    table = source_table()
    if args.json:
        print(table.to_json(orient="records", indent=2))
        return 0
    print(f"sportio {__version__}   cache: {data_root(create=False)}")
    print()
    print(_render(table[["source", "events", "tracking", "lineups", "title", "license"]]))
    print()
    print(f"canonical events columns:   {', '.join(EVENT_COLUMNS)}")
    print(f"canonical tracking columns: {', '.join(TRACKING_COLUMNS)}")
    return 0


def _describe(payload: dict[str, Any]) -> str:
    width = max(len(k) for k in payload)
    return "\n".join(f"{k.ljust(width)}  {v}" for k, v in payload.items())


def _render(table: pd.DataFrame) -> str:
    return table.to_string(index=False, max_colwidth=60)


# --------------------------------------------------------------------------------------
# fetch
# --------------------------------------------------------------------------------------


def _cmd_fetch(args: argparse.Namespace) -> int:
    info = get_source(args.source)
    if info.name == "soccernet":
        return _fetch_soccernet(args)
    kwargs = _fetch_kwargs(info.name, args)

    wanted = args.kind
    frames: dict[str, pd.DataFrame] = {}
    if info.events and wanted in ("events", "both"):
        frames["events"] = load_events(info.name, **kwargs)
    if info.tracking and wanted in ("tracking", "both"):
        frames["tracking"] = load_tracking(info.name, **_drop(kwargs, ("competition", "season")))
    if not frames:
        raise ValueError(f"{info.name} provides no {wanted} data")

    for kind, frame in frames.items():
        validator = validate_events if kind == "events" else validate_tracking
        validator(frame)
        print(f"{info.name} {kind}: {len(frame):,} rows, {frame['match_id'].nunique()} match(es)")
        if kind == "events":
            print(f"  corners: {len(corners(frame)):,}")
        if args.out:
            path = _out_path(args.out, kind, len(frames))
            (to_parquet if path.suffix == ".parquet" else to_csv)(frame, path)
            print(f"  wrote {path}")
    print(f"cache: {data_root(create=False)}")
    return 0


def _fetch_kwargs(source: str, args: argparse.Namespace) -> dict[str, Any]:
    kwargs: dict[str, Any] = {}
    if source == "statsbomb":
        if args.competition:
            kwargs["competition"] = args.competition
        if args.season:
            kwargs["season"] = args.season
        if args.match:
            kwargs["match"] = args.match
        if args.limit:
            kwargs["limit"] = args.limit
        if not kwargs:
            raise ValueError('statsbomb needs --competition (e.g. --competition "Euro 2024")')
    elif source in {"metrica", "skillcorner"}:
        if args.match:
            kwargs["match"] = args.match
    elif source == "rugby":
        if args.match:
            kwargs["event"] = args.match
        if args.date:
            kwargs["date"] = args.date
        if not kwargs:
            raise ValueError("rugby needs --match <espn event id> or --date YYYYMMDD")
    return kwargs


def _fetch_soccernet(args: argparse.Namespace) -> int:
    """Pull only the annotation members out of the split archive.

    The zip is 11.2 GB but its labels are 192 MB, and sportio never reads the images, so this
    range-fetches the members it wants instead of downloading the archive.
    """
    from .loaders import soccernet

    split = args.split or "valid"
    sequences = [args.match] if args.match else None
    paths = soccernet.download_labels(split, sequences, limit=args.limit)
    print(f"soccernet {split}: {len(paths)} sequence(s) of labels")

    if len(paths) == 1:
        name, path = next(iter(paths.items()))
        frame = soccernet.load_tracking(path.parent)
        validate_tracking(frame)
        print(f"  {name}: {len(frame):,} tracking rows")
        if args.out:
            written = (to_parquet if args.out.suffix == ".parquet" else to_csv)(frame, args.out)
            print(f"  wrote {written}")
    else:
        print(f"  under {paths[next(iter(paths))].parent.parent}")
        print("  load one with: sportio.load_tracking('soccernet', split=..., sequence=...)")
    print(f"cache: {data_root(create=False)}")
    return 0


def _drop(kwargs: dict[str, Any], keys: tuple[str, ...]) -> dict[str, Any]:
    return {k: v for k, v in kwargs.items() if k not in keys}


def _out_path(base: Path, kind: str, count: int) -> Path:
    if count == 1:
        return base
    return base.with_name(f"{base.stem}_{kind}{base.suffix or '.csv'}")


# --------------------------------------------------------------------------------------
# validate
# --------------------------------------------------------------------------------------


def _cmd_validate(args: argparse.Namespace) -> int:
    path: Path = args.path
    if not path.exists():
        raise FileNotFoundError(path)

    frame, kind, how = _load_for_validation(path, args.source, args.kind)
    validator = validate_events if kind == "events" else validate_tracking
    validator(frame, sample=None)
    print(f"ok: {path}")
    print(f"  read as: {how}")
    print(f"  {kind}: {len(frame):,} rows x {len(frame.columns)} canonical columns")
    if len(frame):
        matches = frame["match_id"].nunique()
        periods = sorted(int(p) for p in frame["period"].dropna().unique())
        print(f"  matches: {matches}   periods: {periods}")
        if kind == "events":
            top = frame["type"].value_counts().head(5).to_dict()
            print(f"  top types: {top}")
        else:
            print(f"  entities: {frame['team'].value_counts().to_dict()}")
    return 0


def _load_for_validation(
    path: Path, source: str | None, kind: str | None
) -> tuple[pd.DataFrame, str, str]:
    canonical = _read_canonical(path)
    if canonical is not None:
        frame, detected = canonical
        return frame, kind or detected, "canonical CSV"

    source = source or _detect_source(path)
    if source is None:
        raise ValueError(
            f"cannot tell which source {path} belongs to; pass --source "
            f"({', '.join(sources())})"
        )
    info = get_source(source)
    kind = kind or _detect_kind(path, info.events, info.tracking)
    kwargs = _validation_kwargs(source, path, kind)
    frame = load_events(source, **kwargs) if kind == "events" else load_tracking(source, **kwargs)
    return frame, kind, f"{source} {kind} loader"


def _read_canonical(path: Path) -> tuple[pd.DataFrame, str] | None:
    """Recognise a frame sportio itself wrote, by its exact column list."""
    if path.suffix.lower() not in {".csv", ".parquet"}:
        return None
    try:
        if path.suffix.lower() == ".parquet":
            table = pd.read_parquet(path)
        else:
            if tuple(pd.read_csv(path, nrows=0).columns) not in {
                EVENT_COLUMNS,
                TRACKING_COLUMNS,
            }:
                return None
            table = pd.read_csv(path)
    except (OSError, ValueError, ImportError, pd.errors.ParserError):
        return None  # not a table we can read; fall through to the source loaders
    columns = tuple(table.columns)
    if columns == EVENT_COLUMNS:
        return conform_events(table), "events"
    if columns == TRACKING_COLUMNS:
        return conform_tracking(table), "tracking"
    return None


def _detect_source(path: Path) -> str | None:
    parts = {part.lower() for part in path.resolve().parts}
    for name in SOURCES:
        if name in parts:
            return name
    stem = path.name.lower()
    if "sngs-" in stem or "snmot-" in stem or "gamestate" in stem:
        return "soccernet"
    if "espn" in stem:
        return "rugby"
    if "sample_game" in stem:
        return "metrica"
    return None


def _detect_kind(path: Path, events: bool, tracking: bool) -> str:
    name = path.name.lower()
    # "events" wins over "tracking" because Metrica's files are named
    # Sample_Game_1_RawEventsData.csv and Sample_Game_1_RawTrackingData_*.csv -- only one of
    # the two words appears in each, but a directory name could contribute the other.
    if "event" in name or "summary" in name or "scoreboard" in name:
        return "events" if events else "tracking"
    if "tracking" in name or "gamestate" in name or path.is_dir():
        return "tracking" if tracking else "events"
    return "events" if events else "tracking"


def _validation_kwargs(source: str, path: Path, kind: str) -> dict[str, Any]:
    if source == "statsbomb":
        return {"events_file": path}
    if source == "rugby":
        key = "scoreboard_file" if "scoreboard" in path.name.lower() else "summary_file"
        return {key: path}
    if source == "soccernet":
        return {"path": path}
    if source == "metrica":
        if _is_metrica_game3(path):
            return _metrica_game3_kwargs(path, kind)
        if kind == "events":
            return {"events_file": path}
        home, away = _metrica_pair(path)
        return {"home_file": home, "away_file": away}
    if source == "skillcorner":
        match_file = _sibling(path, "_match.json")
        if match_file is None:
            # Without the sibling the loader would fall back to its default match id and
            # happily validate this file against a different match's roster and pitch.
            raise FileNotFoundError(
                f"{path} needs its metadata sibling; expected "
                f"{path.with_name(path.name.split('_')[0] + '_match.json')}"
            )
        key = "events_file" if kind == "events" else "tracking_file"
        match_id = path.name.split("_")[0]
        return {key: path, "match_file": match_file, "match": match_id}
    return {"path": path}  # pragma: no cover - every source is covered above


def _is_metrica_game3(path: Path) -> bool:
    """Game 3 is the EPTS format, which shares nothing with the game 1-2 CSVs."""
    parts = {part.lower() for part in path.parts}
    return "game3" in parts or "sample_game_3" in path.name.lower()


def _metrica_game3_kwargs(path: Path, kind: str) -> dict[str, Any]:
    metadata = _find_beside(path, "metadata")
    if metadata is None:
        raise FileNotFoundError(
            f"{path} is Metrica game 3 (EPTS), which needs its metadata XML alongside it; "
            "expected a *_metadata.xml in the same directory"
        )
    if kind == "events":
        return {"match": 3, "metadata_file": metadata, "events_file": path}
    return {"match": 3, "metadata_file": metadata, "tracking_file": path}


def _find_beside(path: Path, needle: str) -> Path | None:
    for candidate in sorted(path.parent.glob("*.xml")):
        if needle in candidate.name.lower():
            return candidate
    return None


def _metrica_pair(path: Path) -> tuple[Path, Path]:
    """Metrica tracking always comes as a Home/Away pair; find the sibling."""
    for mine, theirs in (("Home", "Away"), ("Away", "Home")):
        if mine in path.name:
            sibling = path.with_name(path.name.replace(mine, theirs))
            if sibling.exists():
                return (path, sibling) if mine == "Home" else (sibling, path)
            raise FileNotFoundError(f"{path} has no {theirs} counterpart at {sibling}")
    raise ValueError(f"{path} does not look like a Metrica Home/Away tracking file")


def _sibling(path: Path, suffix: str) -> Path | None:
    match_id = path.name.split("_")[0]
    candidate = path.with_name(f"{match_id}{suffix}")
    return candidate if candidate.exists() else None


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())

"""Write canonical tracking back out in Metrica Sports' raw CSV format.

Metrica's tracking CSV has a three-row header that most parsers choke on::

    ,,,Home,,Home,,...                      <- team name, on the first column of each x/y pair
    ,,,11,,1,,...                           <- shirt number, likewise
    Period,Frame,Time [s],Player11,,...,Ball,   <- column names, y column left blank

This module reproduces it byte-for-byte-ish, so anything written here loads straight back
through :func:`sportio.loaders.metrica.read_tracking` and round-trips.
"""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd

from ..pitch import METRICA
from ..transform import native_hz

__all__ = ["metrica_paths", "to_metrica"]

_META_COLUMNS = ["Period", "Frame", "Time [s]"]


def metrica_paths(path: str | Path) -> dict[str, Path]:
    """Derive the Home/Away file paths Metrica would use from a single base path.

    ``out.csv`` -> ``out_Home_Team.csv`` / ``out_Away_Team.csv``.
    """
    path = Path(path)
    suffix = path.suffix or ".csv"
    stem = path.with_suffix("").name
    for tail in ("_Home_Team", "_Away_Team"):
        if stem.endswith(tail):
            stem = stem[: -len(tail)]
            break
    return {
        "home": path.with_name(f"{stem}_Home_Team{suffix}"),
        "away": path.with_name(f"{stem}_Away_Team{suffix}"),
    }


def to_metrica(
    tracking: pd.DataFrame,
    path: str | Path,
    *,
    fps: float | None = None,
    float_format: str = "%.5f",
) -> dict[str, Path]:
    """Write a canonical tracking frame as Metrica Home/Away CSVs.

    Args:
        tracking: canonical tracking frame (105x68 metres).
        path: base path; see :func:`metrica_paths` for how Home/Away names are derived.
        fps: frame rate to encode in ``Time [s]``. Inferred from the data when omitted.
        float_format: coordinate precision. Metrica ships 5 decimals.

    Returns:
        Mapping of ``"home"``/``"away"`` to the files actually written.
    """
    if tracking.empty:
        raise ValueError("refusing to write an empty tracking frame")
    rate = fps or native_hz(tracking) or 25.0
    targets = metrica_paths(path)
    ball = tracking.loc[tracking["team"] == "ball"]

    written: dict[str, Path] = {}
    for side in ("home", "away"):
        block = tracking.loc[tracking["team"] == side]
        if block.empty:
            continue
        target = targets[side]
        target.parent.mkdir(parents=True, exist_ok=True)
        _write_side(block, ball, side, target, rate, float_format)
        written[side] = target
    if not written:
        raise ValueError("tracking frame contains no home or away rows")
    return written


def _write_side(
    block: pd.DataFrame,
    ball: pd.DataFrame,
    side: str,
    target: Path,
    fps: float,
    float_format: str,
) -> None:
    grid = _frame_index(pd.concat([block, ball]), fps)
    players = _player_order(block)
    jerseys = _jerseys(block, players)

    wide = pd.DataFrame(index=grid.index)
    for player in players:
        track = block.loc[block["player_id"] == player].set_index("frame")
        x, y = METRICA.from_canonical(
            track["x"].astype("float64"), track["y"].astype("float64")
        )
        wide[f"{player}__x"] = x.reindex(grid.index)
        wide[f"{player}__y"] = y.reindex(grid.index)

    if not ball.empty:
        btrack = ball.drop_duplicates(subset="frame").set_index("frame")
        bx, by = METRICA.from_canonical(
            btrack["x"].astype("float64"), btrack["y"].astype("float64")
        )
        wide["Ball__x"] = bx.reindex(grid.index)
        wide["Ball__y"] = by.reindex(grid.index)

    body = pd.concat([grid, wide], axis=1)
    names = [*_META_COLUMNS]
    teams = ["", "", ""]
    numbers = ["", "", ""]
    for player in players:
        names += [player, ""]
        teams += [side.capitalize(), ""]
        numbers += [_fmt_jersey(jerseys.get(player)), ""]
    if "Ball__x" in wide.columns:
        names += ["Ball", ""]
        teams += ["", ""]
        numbers += ["", ""]

    lines = [
        ",".join(teams),
        ",".join(numbers),
        ",".join(names),
    ]
    csv_body = body.to_csv(index=False, header=False, float_format=float_format, na_rep="NaN")
    with target.open("w", newline="") as fh:
        fh.write("\n".join(lines))
        fh.write("\n")
        fh.write(csv_body)


def _frame_index(block: pd.DataFrame, fps: float) -> pd.DataFrame:
    frames = (
        block.loc[:, ["frame", "period"]]
        .dropna(subset=["frame"])
        .drop_duplicates(subset="frame")
        .astype({"frame": "int64", "period": "int64"})
        .sort_values("frame")
    )
    grid = pd.DataFrame(
        {
            "Period": frames["period"].to_numpy(),
            "Frame": frames["frame"].to_numpy(),
            "Time [s]": np.round(frames["frame"].to_numpy() / fps, 6),
        },
        index=frames["frame"].to_numpy(),
    )
    grid.index.name = "frame"
    return grid


def _player_order(block: pd.DataFrame) -> list[str]:
    """Players ordered by first appearance, which is how Metrica lays out its columns."""
    seen = block.dropna(subset=["player_id"]).sort_values(["frame"], kind="stable")
    return list(dict.fromkeys(seen["player_id"].astype("string").tolist()))


def _jerseys(block: pd.DataFrame, players: list[str]) -> dict[str, int | None]:
    out: dict[str, int | None] = {}
    for player, group in block.groupby("player_id", dropna=True):
        numbers = group["jersey"].dropna()
        out[str(player)] = int(numbers.iloc[0]) if len(numbers) else None
    return {p: out.get(p) for p in players}


def _fmt_jersey(value: int | None) -> str:
    return "" if value is None else str(int(value))

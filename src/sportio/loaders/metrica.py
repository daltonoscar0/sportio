"""Metrica Sports sample data -- games 1 and 2 (CSV tracking + CSV events).

Repo: https://github.com/metrica-sports/sample-data (branch ``master``).

The tracking CSV carries a three-row header in which only the **x** column of each player is
labelled, so the y column has to be taken positionally. ``Time [s]`` is cumulative across the
whole match rather than per period, teams switch ends at half time, and the data is anonymous:
there is no match id, competition, season or real name anywhere, so sportio synthesises them.

Game 3 is a completely different (FIFA EPTS) format and is not handled here; see
``docs/schema_notes/metrica.md`` for its layout and TODO.md for the status.
"""

from __future__ import annotations

import csv
import re
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

from ..http import Fetcher, default_fetcher
from ..pitch import METRICA
from ..schema import conform_events, conform_tracking, encode_extra
from ..transform import flip_events
from ._common import finish_events, finish_tracking, snake

__all__ = [
    "GAMES",
    "load_events",
    "load_tracking",
    "period_starts",
    "read_events",
    "read_tracking",
]

BASE = "https://raw.githubusercontent.com/metrica-sports/sample-data/master/data"
FPS = 25.0

#: Games that ship in the CSV format this loader understands.
GAMES: tuple[int, ...] = (1, 2)

COMPETITION = "Metrica Sample Data"

_WHITESPACE = re.compile(r"\s+")


# --------------------------------------------------------------------------------------
# tracking
# --------------------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class _Column:
    """One entity's pair of coordinate columns in a Metrica tracking CSV."""

    entity: str
    team: str
    jersey: int | None
    x_col: str
    y_col: str


def _parse_header(path: Path) -> tuple[list[str], list[str], list[str]]:
    with path.open(newline="") as fh:
        reader = csv.reader(fh)
        return next(reader), next(reader), next(reader)


def _columns(path: Path, side: str, frame: pd.DataFrame) -> list[_Column]:
    _, jerseys, names = _parse_header(path)
    out: list[_Column] = []
    for i, name in enumerate(names):
        if i < 3 or not name:
            continue
        # The away file labels the Ball's x column "Away" in row 1, so team membership comes
        # from the file we are reading, never from that row.
        is_ball = name.strip().lower() == "ball"
        jersey = jerseys[i].strip() if i < len(jerseys) else ""
        out.append(
            _Column(
                entity="ball" if is_ball else _clean_player_id(name),
                team="ball" if is_ball else side,
                jersey=int(jersey) if jersey.isdigit() and not is_ball else None,
                x_col=frame.columns[i],
                y_col=frame.columns[i + 1],
            )
        )
    return out


def _clean_player_id(name: str) -> str:
    """``"Player 26"`` (game 2) and ``"Player26"`` (game 1) are the same player."""
    return _WHITESPACE.sub("", name.strip())


def read_tracking(path: str | Path, side: str, match_id: str) -> pd.DataFrame:
    """Melt one Metrica tracking CSV (home or away) into canonical long form."""
    path = Path(path)
    wide = pd.read_csv(path, skiprows=2)
    columns = _columns(path, side, wide)

    period = wide["Period"].astype("int64")
    frame = wide["Frame"].astype("int64")
    clock = wide["Time [s]"].astype("float64")
    # Time [s] runs straight through half time; the canonical t restarts each period.
    t = clock - clock.groupby(period).transform("min")

    pieces = []
    for col in columns:
        x, y = METRICA.to_canonical(
            wide[col.x_col].astype("float64").to_numpy(),
            wide[col.y_col].astype("float64").to_numpy(),
        )
        pieces.append(
            pd.DataFrame(
                {
                    "match_id": match_id,
                    "t": t.to_numpy(),
                    "period": period.to_numpy(),
                    "frame": frame.to_numpy(),
                    "team": col.team,
                    "player_id": None if col.team == "ball" else col.entity,
                    "jersey": col.jersey,
                    "x": x,
                    "y": y,
                    "vx": np.nan,
                    "vy": np.nan,
                    "confidence": np.nan,
                }
            )
        )
    long = pd.concat(pieces, ignore_index=True)
    # Substitutes are all-NaN column spans rather than absent columns; drop those rows so a
    # frame holds 11 players per side, not 14.
    long = long.dropna(subset=["x", "y"], how="all")
    return conform_tracking(long)


def load_tracking(
    match: int | str = 1,
    *,
    home_file: str | Path | None = None,
    away_file: str | Path | None = None,
    hz: float | None = None,
    velocities: bool = True,
    direction: str = "home_ltr",
    fetcher: Fetcher | None = None,
) -> pd.DataFrame:
    """Load one Metrica sample game as canonical tracking.

    Args:
        match: game number (1 or 2), or any label when explicit files are given.
        home_file, away_file: read these CSVs instead of downloading ~65 MB.
        hz: resample target; ``None`` keeps the native 25 Hz.
        velocities: fill ``vx``/``vy``.
        direction: ``"home_ltr"`` (default) flips period 2 so the home team always attacks +x.
    """
    fetcher = fetcher or default_fetcher()
    match_id = _match_id(match)
    home = Path(home_file) if home_file else _download(match, "Home", fetcher)
    away = Path(away_file) if away_file else _download(match, "Away", fetcher)

    home_df = read_tracking(home, "home", match_id)
    away_df = read_tracking(away, "away", match_id)
    # The two files carry identical ball columns; keep one copy.
    away_df = away_df.loc[away_df["team"] != "ball"]

    both = pd.concat([home_df, away_df], ignore_index=True)
    return finish_tracking(both, hz=hz, velocities=velocities, direction=direction)


def _match_id(match: int | str) -> str:
    return f"metrica-{match}"


def _download(match: int | str, side: str, fetcher: Fetcher) -> Path:
    name = f"Sample_Game_{match}_RawTrackingData_{side}_Team.csv"
    return fetcher.download(f"{BASE}/Sample_Game_{match}/{name}", f"metrica/{name}", desc=name)


# --------------------------------------------------------------------------------------
# events
# --------------------------------------------------------------------------------------

#: Atomic ``Subtype`` tags that mark a restart, mapped to the canonical set-piece vocabulary.
_SET_PIECE_TAGS = {
    "corner_kick": "corner",
    "free_kick": "free_kick",
    "throw_in": "throw_in",
    "kick_off": "kick_off",
    "goal_kick": "goal_kick",
    "penalty": "penalty",
}

#: Remaining tags that describe *how* the action was played, most specific first.
_TECHNIQUE_TAGS = (
    "cross", "through_ball", "deep_ball", "clearance", "tackle", "dribble",
    "aerial", "ground", "interception", "theft", "hand_ball", "referee_hit",
    "direct", "indirect", "retaken", "voluntary", "forced", "end_half",
)

#: Tags that describe how the action ended, most decisive first.
_OUTCOME_TAGS = (
    "goal", "saved", "blocked", "woodwork", "off_target", "on_target",
    "won", "lost", "offside", "out", "advantage", "fault", "yellow", "red",
)


def period_starts(tracking: pd.DataFrame) -> dict[int, int]:
    """First tracked frame of each period, for aligning events onto the tracking clock.

    Pass the result to :func:`load_events` as ``period_starts=``. Without it the two frames
    disagree in the second half: tracking restarts its clock at the period's first *frame*,
    while the events file's first *event* of the half comes some seconds later.
    """
    grouped = tracking.dropna(subset=["frame"]).groupby("period")["frame"]
    return {int(period): int(first) for period, first in grouped.min().items()}


def read_events(
    path: str | Path,
    match_id: str,
    starts: Mapping[int, int] | None = None,
) -> pd.DataFrame:
    """Parse a Metrica events CSV into canonical events, still in the raw pitch frame."""
    raw = pd.read_csv(path)
    period = raw["Period"].astype("int64")
    clock = raw["Start Time [s]"].astype("float64")
    if starts:
        # Anchor on the same frame the tracking loader anchors on, so the two clocks agree.
        base = period.map(starts)
        t = (raw["Start Frame"].astype("float64") - base) / FPS
    else:
        t = clock - clock.groupby(period).transform("min")

    tags = raw["Subtype"].map(_split_tags)
    x, y = METRICA.to_canonical(
        raw["Start X"].astype("float64").to_numpy(), raw["Start Y"].astype("float64").to_numpy()
    )
    end_x, end_y = METRICA.to_canonical(
        raw["End X"].astype("float64").to_numpy(), raw["End Y"].astype("float64").to_numpy()
    )

    out = pd.DataFrame(
        {
            "match_id": match_id,
            "competition": COMPETITION,
            "season": None,
            "team_id": raw["Team"].astype("string").str.lower(),
            "team": raw["Team"].astype("string"),
            "player_id": raw["From"].map(_clean_optional),
            "player": raw["From"].map(_clean_optional),
            "t": t.to_numpy(),
            "period": period.to_numpy(),
            "type": raw["Type"].map(snake),
            "subtype": [_subtype(tag_set) for tag_set in tags],
            "x": x,
            "y": y,
            "end_x": end_x,
            "end_y": end_y,
            "outcome": [_outcome(tag_set) for tag_set in tags],
            # Metrica has no under-pressure flag; pressing context must come from tracking.
            "pressure": False,
            "body_part": ["head" if "head" in tag_set else None for tag_set in tags],
            "extra": [
                encode_extra(payload)
                for payload in _extras(raw, tags)
            ],
        }
    )
    return conform_events(out)


def _split_tags(value: Any) -> frozenset[str]:
    """``"HEAD-ON TARGET-GOAL"`` -> ``{"head", "on_target", "goal"}``; order is not stable."""
    if value is None or (isinstance(value, float) and value != value):
        return frozenset()
    return frozenset(filter(None, (snake(part) for part in str(value).split("-"))))


def _subtype(tags: frozenset[str]) -> str | None:
    for tag, canonical in _SET_PIECE_TAGS.items():
        if tag in tags:
            return canonical
    for tag in _TECHNIQUE_TAGS:
        if tag in tags:
            return tag
    return None


def _outcome(tags: frozenset[str]) -> str | None:
    for tag in _OUTCOME_TAGS:
        if tag in tags:
            return tag
    return None


def _extras(raw: pd.DataFrame, tags: pd.Series) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for rec, tag_set in zip(raw.to_dict(orient="records"), tags, strict=True):
        end_frame = rec.get("End Frame")
        payload: dict[str, Any] = {
            "start_frame": _int(rec.get("Start Frame")),
            # The opening kick-off is the one row with End Frame 0, which is not a valid
            # 1-based frame index.
            "end_frame": _int(end_frame) or None,
            "to": _clean_optional(rec.get("To")),
            # _clean_optional strips *internal* whitespace too, which is right for player
            # ids and wrong here: "ON TARGET" would become "ONTARGET".
            "subtype_raw": _text_or_none(rec.get("Subtype")),
            "tags": sorted(tag_set),
        }
        out.append({k: v for k, v in payload.items() if v not in (None, [])})
    return out


def _text_or_none(value: Any) -> str | None:
    """Trim the ends only, preserving a value's internal spaces."""
    if value is None or (isinstance(value, float) and value != value):
        return None
    return str(value).strip() or None


def _clean_optional(value: Any) -> str | None:
    if value is None or (isinstance(value, float) and value != value):
        return None
    text = _WHITESPACE.sub("", str(value).strip())
    return text or None


def _int(value: Any) -> int | None:
    try:
        out = int(float(value))
    except (TypeError, ValueError):
        return None
    return out


def load_events(
    match: int | str = 1,
    *,
    events_file: str | Path | None = None,
    direction: str = "possession",
    starts: Mapping[int, int] | None = None,
    fetcher: Fetcher | None = None,
) -> pd.DataFrame:
    """Load one Metrica sample game as canonical events.

    Args:
        match: game number (1 or 2), or any label when ``events_file`` is given.
        events_file: read this CSV instead of downloading it.
        direction: ``"possession"`` (default) rotates each event so the acting team attacks +x,
            as the canonical schema requires; ``"raw"`` keeps Metrica's fixed match frame.
        starts: ``{period: first_frame}`` from :func:`period_starts`, so ``t`` lands on the
            same clock the tracking loader uses. Without it the second half is offset by the
            gap between the period's first tracked frame and its first recorded event -- join
            on ``extra["start_frame"]`` instead if you cannot supply this. Note that if the
            tracking is a truncated slice, events preceding its first frame get a negative
            ``t``, which is the honest answer rather than a clamp.
    """
    fetcher = fetcher or default_fetcher()
    match_id = _match_id(match)
    if events_file is None:
        name = f"Sample_Game_{match}_RawEventsData.csv"
        events_file = fetcher.download(
            f"{BASE}/Sample_Game_{match}/{name}", f"metrica/{name}", desc=name
        )

    out = read_events(events_file, match_id, starts)
    if direction == "possession":
        signs = attack_directions(out)
        pairs = zip(out["team_id"], out["period"], strict=True)
        mask = np.array([signs.get((team, period), 1) < 0 for team, period in pairs])
        out = flip_events(out, mask)
    elif direction != "raw":
        raise ValueError(f"unknown direction {direction!r}")
    return finish_events(out)


def attack_directions(events: pd.DataFrame) -> dict[tuple[str, int], int]:
    """Infer, per ``(team_id, period)``, whether the team attacks +x (``1``) or -x (``-1``).

    Metrica ships no metadata, so this reads the pitch itself: a team's shots end at the goal
    it is attacking, and its goal kicks are taken from the goal it is defending. The two
    signals are combined and then made self-consistent (the two teams attack opposite ends,
    and every team switches at half time).
    """
    votes: dict[tuple[str, int], float] = {}
    shots = events.loc[events["type"] == "shot"]
    for (team, period), block in shots.groupby(["team_id", "period"], dropna=True):
        end_x = block["end_x"].astype("float64").dropna()
        if len(end_x):
            votes[(str(team), int(period))] = float(end_x.mean()) - 52.5

    kicks = events.loc[events["subtype"] == "goal_kick"]
    for (team, period), block in kicks.groupby(["team_id", "period"], dropna=True):
        start_x = block["x"].astype("float64").dropna()
        if len(start_x):
            key = (str(team), int(period))
            # A goal kick is taken from the goal the team DEFENDS, so the sign is inverted.
            votes.setdefault(key, 0.0)
            votes[key] += (52.5 - float(start_x.mean())) * 0.5

    teams = sorted({str(v) for v in events["team_id"].dropna().unique()})
    periods = sorted({int(p) for p in events["period"].dropna().unique()})
    if not teams or not periods:
        return {}

    home = teams[0]
    scores: dict[int, float] = {}
    for period in periods:
        score = votes.get((home, period), 0.0)
        for other in teams[1:]:
            score -= votes.get((other, period), 0.0)
        scores[period] = score

    voted = [p for p, score in scores.items() if score != 0.0]
    signs: dict[tuple[str, int], int] = {}
    for period in periods:
        score = scores[period]
        if score == 0.0:
            if not voted:
                home_sign = 1  # nothing anywhere in the file to go on
            else:
                # Teams change ends every period, so alternate away from the nearest period
                # that did have evidence.
                anchor = min(voted, key=lambda p: abs(p - period))
                flips = abs(period - anchor) % 2
                home_sign = (1 if scores[anchor] > 0 else -1) * (-1 if flips else 1)
        else:
            home_sign = 1 if score > 0 else -1
        signs[(home, period)] = home_sign
        for other in teams[1:]:
            signs[(other, period)] = -home_sign
    return signs

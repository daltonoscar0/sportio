"""Metrica Sports sample game 3 -- FIFA EPTS metadata plus a raw positional stream.

Repo: https://github.com/metrica-sports/sample-data (branch ``master``).

Game 3 shares nothing with games 1 and 2 except the normalised 0-1 top-left coordinate frame,
so it gets its own loader; see :mod:`sportio.loaders.metrica` for the CSV games.

Three things about the format are load-bearing and all three are handled below:

* ``Sample_Game_3_tracking.txt`` has **no header**. A row is
  ``frame : p1_x,p1_y ; ... ; p22_x,p22_y : ball_x,ball_y`` and the only thing that says which
  player ``pN`` is, is the ``DataFormatSpecification`` block whose ``[startFrame, endFrame]``
  contains that frame. There are eleven such blocks -- the layout is rewritten at every
  substitution -- so decoding a row means finding its block first. Reusing block 1 for the
  whole match silently attributes ten players' second-half tracks to the men they replaced.
* Direction of play is stated outright (``attack_direction_first_half`` per team), so unlike
  games 1-2 nothing has to be inferred from goalkeeper positions.
* ``Sample_Game_3_events.json`` stores ``subtypes`` as ``null``, a single object *or* a list of
  objects, and leaves ``x``/``y`` null on set pieces and cards.

See ``docs/schema_notes/metrica.md`` section 9 for the measured schema.
"""

from __future__ import annotations

import bisect
import json
from collections.abc import Iterator, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from xml.etree import ElementTree as ET

import numpy as np
import pandas as pd

from ..http import Fetcher, default_fetcher
from ..pitch import METRICA
from ..schema import conform_events, conform_tracking, encode_extra
from ..transform import flip_events, flip_tracking
from ._common import finish_events, finish_tracking, snake

# Game 3's SUBTYPE code list is the same 39 tags games 1-2 spell in their ``Subtype`` column,
# so the canonical mapping lives once, in the CSV loader.
from .metrica import BASE, COMPETITION, _outcome, _subtype

__all__ = [
    "FormatBlock",
    "Game3Metadata",
    "PlayerInfo",
    "load_events",
    "load_tracking",
    "read_metadata",
]

#: The only sample game published in this format.
MATCH = 3

#: Separators declared by every ``DataFormatSpecification`` in the shipped metadata. They are
#: verified against the XML in :func:`read_metadata` rather than trusted blindly.
ROW_SEP = ":"
ENTITY_SEP = ";"
AXIS_SEP = ","

#: EPTS names the halves; sportio numbers them.
_PERIOD_PREFIXES = ("first_half", "second_half", "first_extra_half", "second_extra_half")

#: Frames per parse chunk. The stream is 143,761 rows x 46 floats; chunking keeps the
#: intermediate arrays bounded without giving up vectorised conversion.
_CHUNK = 20_000


# --------------------------------------------------------------------------------------
# metadata
# --------------------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class PlayerInfo:
    """One ``<Player>``: identity plus the nominal position EPTS records for them."""

    player_id: str
    team_id: str
    name: str
    jersey: int | None
    position: str | None


@dataclass(frozen=True, slots=True)
class FormatBlock:
    """One ``<DataFormatSpecification>``: the column layout in force over a frame range.

    ``players[i]`` is the player id whose ``x``/``y`` occupy tracking columns ``2i`` and
    ``2i+1`` of a row in ``[start_frame, end_frame]``.
    """

    start_frame: int
    end_frame: int
    players: tuple[str, ...]
    has_ball: bool

    def covers(self, frame: int) -> bool:
        return self.start_frame <= frame <= self.end_frame


@dataclass(frozen=True, slots=True)
class Game3Metadata:
    """Everything ``Sample_Game_3_metadata.xml`` says that the loaders need.

    Attributes:
        frame_rate: samples per second (25).
        periods: ``{period: (first_frame, last_frame)}``, inclusive, from the
            ``*_half_start``/``*_half_end`` provider parameters. Halves are back to back --
            frame 69662 is the second half's first frame -- so there is no gap to detect.
        home_id, away_id: EPTS team ids; ``idLocalTeam`` on ``<Score>`` is the home side.
        team_names: ``{team_id: "Team A"}``.
        attack_first_half: ``{team_id: "left_to_right" | "right_to_left"}`` in the source's
            own coordinate frame.
        players: ``{player_id: PlayerInfo}`` for all 35 squad members, starters and subs.
        blocks: the eleven column layouts, in frame order.
        field_size: ``(width, height)`` in metres as stated by ``<FieldSize>``. Positions are
            normalised, so this is documentation rather than a scale factor.
        competition, kickoff: the ``<Competition>`` label and ``<Session><Start>`` timestamp.
    """

    frame_rate: float
    periods: dict[int, tuple[int, int]]
    home_id: str
    away_id: str
    team_names: dict[str, str]
    attack_first_half: dict[str, str]
    players: dict[str, PlayerInfo]
    blocks: tuple[FormatBlock, ...]
    field_size: tuple[float, float]
    competition: str | None
    kickoff: str | None

    def side(self, team_id: str | None) -> str | None:
        """``"home"``/``"away"`` for an EPTS team id, or ``None`` if it is not one."""
        if team_id == self.home_id:
            return "home"
        if team_id == self.away_id:
            return "away"
        return None

    def period_at(self, frame: int) -> int | None:
        for period, (start, end) in self.periods.items():
            if start <= frame <= end:
                return period
        return None

    def block_at(self, frame: int) -> FormatBlock | None:
        starts = [block.start_frame for block in self.blocks]
        index = bisect.bisect_right(starts, frame) - 1
        if index < 0:
            return None
        block = self.blocks[index]
        return block if block.covers(frame) else None

    def home_sign(self, period: int) -> int:
        """``+1`` when the home team attacks +x in ``period``, in the source's own frame."""
        base = -1 if self.attack_first_half.get(self.home_id) == "right_to_left" else 1
        # Ends are swapped at the interval. Extra time would break this alternation (the toss
        # is retaken), but game 3's extra-half parameters are empty so no period 3 exists.
        return base if period % 2 else -base


def read_metadata(path: str | Path) -> Game3Metadata:
    """Parse ``Sample_Game_3_metadata.xml`` into a :class:`Game3Metadata`."""
    root = ET.parse(Path(path)).getroot()
    meta = root.find("Metadata")
    if meta is None:
        raise ValueError(f"{path}: not FIFA EPTS metadata (no <Metadata> under <{root.tag}>)")

    globals_ = _provider_params(meta.find("GlobalConfig/ProviderGlobalParameters"))
    periods: dict[int, tuple[int, int]] = {}
    for number, prefix in enumerate(_PERIOD_PREFIXES, start=1):
        start, end = globals_.get(f"{prefix}_start"), globals_.get(f"{prefix}_end")
        # The two extra-time pairs are present but empty in every shipped file.
        if start and end:
            periods[number] = (int(start), int(end))
    if not periods:
        raise ValueError(f"{path}: no *_half_start/_end provider parameters")

    session = meta.find("Sessions/Session")
    score = session.find("MatchParameters/Score") if session is not None else None
    home_id = score.get("idLocalTeam") if score is not None else None
    away_id = score.get("idVisitingTeam") if score is not None else None

    team_names: dict[str, str] = {}
    attack: dict[str, str] = {}
    for team in meta.findall("Teams/Team"):
        team_id = team.get("id")
        if not team_id:
            continue
        team_names[team_id] = (team.findtext("Name") or team_id).strip()
        direction = _provider_params(team.find("ProviderTeamsParameters")).get(
            "attack_direction_first_half"
        )
        if direction:
            attack[team_id] = direction
    if home_id is None or away_id is None:
        # Without <Score> there is nothing but document order to go on.
        ordered = list(team_names)
        home_id = home_id or (ordered[0] if ordered else "home")
        away_id = away_id or (ordered[1] if len(ordered) > 1 else "away")

    players = {info.player_id: info for info in map(_player, meta.findall("Players/Player"))}
    channels = {
        channel.get("id"): (channel.get("playerId"), channel.get("channelId"))
        for channel in meta.findall("PlayerChannels/PlayerChannel")
    }
    blocks = _blocks(root, channels, path)

    return Game3Metadata(
        frame_rate=float(meta.findtext("GlobalConfig/FrameRate") or 25.0),
        periods=periods,
        home_id=home_id,
        away_id=away_id,
        team_names=team_names,
        attack_first_half=attack,
        players=players,
        blocks=blocks,
        field_size=_field_size(session),
        competition=_text(session.find("Competition")) if session is not None else None,
        kickoff=session.findtext("Start") if session is not None else None,
    )


def _provider_params(node: ET.Element | None) -> dict[str, str]:
    if node is None:
        return {}
    out: dict[str, str] = {}
    for param in node.findall("ProviderParameter"):
        name = (param.findtext("Name") or "").strip()
        value = (param.findtext("Value") or "").strip()
        if name:
            out[name] = value
    return out


def _player(node: ET.Element) -> PlayerInfo:
    player_id = node.get("id") or ""
    shirt = (node.findtext("ShirtNumber") or "").strip()
    return PlayerInfo(
        player_id=player_id,
        team_id=node.get("teamId") or "",
        name=(node.findtext("Name") or player_id).strip(),
        jersey=int(shirt) if shirt.isdigit() else None,
        position=_provider_params(node.find("ProviderPlayerParameters")).get("position_type")
        or None,
    )


def _field_size(session: ET.Element | None) -> tuple[float, float]:
    node = session.find("FieldSize") if session is not None else None
    if node is None:
        return 105.0, 68.0
    return float(node.findtext("Width") or 105.0), float(node.findtext("Height") or 68.0)


def _blocks(
    root: ET.Element,
    channels: Mapping[str | None, tuple[str | None, str | None]],
    path: str | Path,
) -> tuple[FormatBlock, ...]:
    out: list[FormatBlock] = []
    for spec in root.findall("DataFormatSpecifications/DataFormatSpecification"):
        _check_separator(spec.get("separator"), ROW_SEP, path)
        players: list[str] = []
        for group in spec.iter("SplitRegister"):
            refs = group.findall("PlayerChannelRef")
            if not refs:
                continue
            _check_separator(group.get("separator"), AXIS_SEP, path)
            players.append(_player_of(refs, channels, path))
        outer = spec.find("SplitRegister")
        if outer is not None:
            _check_separator(outer.get("separator"), ENTITY_SEP, path)
        out.append(
            FormatBlock(
                start_frame=int(spec.get("startFrame") or 1),
                end_frame=int(spec.get("endFrame") or 0),
                players=tuple(players),
                has_ball=spec.find(".//BallChannelRef") is not None,
            )
        )
    if not out:
        raise ValueError(f"{path}: no <DataFormatSpecification> blocks")
    return tuple(sorted(out, key=lambda block: block.start_frame))


def _player_of(
    refs: Sequence[ET.Element],
    channels: Mapping[str | None, tuple[str | None, str | None]],
    path: str | Path,
) -> str:
    """Resolve an ``x``/``y`` ``PlayerChannelRef`` pair to the player it belongs to."""
    seen: dict[str | None, str] = {}
    for ref in refs:
        player_id, axis = channels.get(ref.get("playerChannelId"), (None, None))
        if player_id is None:
            raise ValueError(f"{path}: unknown playerChannelId {ref.get('playerChannelId')!r}")
        seen[axis] = player_id
    if set(seen) != {"x", "y"} or seen["x"] != seen["y"]:
        raise ValueError(f"{path}: a channel pair does not describe one player's x and y")
    return seen["x"]


def _check_separator(found: str | None, expected: str, path: str | Path) -> None:
    if found is not None and found != expected:
        raise ValueError(f"{path}: separator {found!r} is not the expected {expected!r}")


def _text(node: ET.Element | None) -> str | None:
    if node is None or node.text is None:
        return None
    return node.text.strip() or None


# --------------------------------------------------------------------------------------
# tracking
# --------------------------------------------------------------------------------------


def load_tracking(
    match: int | str = MATCH,
    *,
    metadata_file: str | Path | None = None,
    tracking_file: str | Path | None = None,
    max_frames: int | None = None,
    hz: float | None = None,
    velocities: bool = True,
    direction: str = "home_ltr",
    fetcher: Fetcher | None = None,
) -> pd.DataFrame:
    """Load Metrica sample game 3 as canonical tracking.

    Args:
        match: game number, or any label when explicit files are given; ``match_id`` becomes
            ``"metrica-<match>"``.
        metadata_file, tracking_file: read these instead of downloading 53 MB.
        max_frames: stop after this many frames -- handy for a quick look at a 143,761-frame
            stream.
        hz: resample target; ``None`` keeps the native 25 Hz.
        velocities: fill ``vx``/``vy``.
        direction: ``"home_ltr"`` (default) uses ``attack_direction_first_half`` to flip the
            periods in which the home team attacks -x; ``"raw"`` keeps the source geometry.
    """
    fetcher = fetcher or default_fetcher()
    meta = read_metadata(metadata_file or _fetch("metadata.xml", match, fetcher))
    path = Path(tracking_file) if tracking_file else _fetch("tracking.txt", match, fetcher)
    match_id = _match_id(match)

    pieces = [
        _chunk_frame(block, frames, coords, meta, match_id)
        for block, frames, coords in _iter_chunks(path, meta, max_frames)
    ]
    long = (
        pd.concat(pieces, ignore_index=True)
        if pieces
        else pd.DataFrame(columns=list(_TRACKING_KEYS))
    )
    # The ball is untracked for 46,325 of the 143,761 frames (dead ball, half time). Those
    # rows are literal "NaN" text, not absent columns; drop them rather than carry them.
    long = long.dropna(subset=["x", "y"], how="all")

    out = conform_tracking(long)
    if direction == "home_ltr" and not out.empty:
        flip = [p for p in out["period"].dropna().unique() if meta.home_sign(int(p)) < 0]
        if flip:
            out = flip_tracking(out, out["period"].isin(flip))
        # The metadata has already settled it; skip the goalkeeper heuristic downstream.
        direction = "raw"
    return finish_tracking(out, hz=hz, velocities=velocities, direction=direction)


_TRACKING_KEYS = (
    "match_id",
    "t",
    "period",
    "frame",
    "team",
    "player_id",
    "jersey",
    "x",
    "y",
    "vx",
    "vy",
    "confidence",
)


def _iter_chunks(
    path: Path,
    meta: Game3Metadata,
    max_frames: int | None,
) -> Iterator[tuple[FormatBlock, list[int], list[list[float]]]]:
    """Stream the positional file, grouping consecutive rows that share a column layout.

    A chunk never spans two ``DataFormatSpecification`` blocks, which is what lets the caller
    decode a whole chunk with one column-to-player mapping.
    """
    current: FormatBlock | None = None
    frames: list[int] = []
    coords: list[list[float]] = []
    seen = 0

    with path.open() as fh:
        for line in fh:
            line = line.strip()
            if not line:
                continue
            frame, values = _parse_row(line, meta)
            if frame is None:
                continue
            # Rows arrive in frame order, so the block only has to be looked up when the
            # frame leaves the one already in hand -- eleven searches, not 143,761.
            block = current if current is not None and current.covers(frame) else None
            block = block or meta.block_at(frame)
            if block is None or len(values) < 2 * len(block.players):
                continue
            if block is not current or len(frames) >= _CHUNK:
                if current is not None and frames:
                    yield current, frames, coords
                current, frames, coords = block, [], []
            frames.append(frame)
            coords.append(values)
            seen += 1
            if max_frames is not None and seen >= max_frames:
                break

    if current is not None and frames:
        yield current, frames, coords


def _parse_row(line: str, meta: Game3Metadata) -> tuple[int | None, list[float]]:
    """``"361:0.5,0.4;...:0.5,0.5"`` -> ``(361, [0.5, 0.4, ..., 0.5, 0.5])``."""
    head, _, rest = line.partition(ROW_SEP)
    try:
        frame = int(head)
    except ValueError:
        return None, []
    if meta.period_at(frame) is None:
        return None, []
    # Entity and axis separators only ever delimit numbers, so flattening them to one
    # separator is safe and saves 23 splits per row on a 143,761-row file.
    flat = rest.replace(ROW_SEP, AXIS_SEP).replace(ENTITY_SEP, AXIS_SEP)
    return frame, [float(value) for value in flat.split(AXIS_SEP)]


def _chunk_frame(
    block: FormatBlock,
    frames: list[int],
    coords: list[list[float]],
    meta: Game3Metadata,
    match_id: str,
) -> pd.DataFrame:
    values = np.asarray(coords, dtype="float64")
    frame_no = np.asarray(frames, dtype="int64")
    period = np.zeros(frame_no.size, dtype="int64")
    t = np.full(frame_no.size, np.nan)
    for number, (start, end) in meta.periods.items():
        inside = (frame_no >= start) & (frame_no <= end)
        period[inside] = number
        # Frame `start` is t = 0, so t is seconds since the period began, not since kick-off.
        t[inside] = (frame_no[inside] - start) / meta.frame_rate

    pieces = []
    for index, player_id in enumerate(block.players):
        info = meta.players.get(player_id)
        x, y = METRICA.to_canonical(values[:, 2 * index], values[:, 2 * index + 1])
        pieces.append(
            _entity_frame(
                match_id,
                t,
                period,
                frame_no,
                team=meta.side(info.team_id) if info else None,
                player_id=player_id,
                jersey=info.jersey if info else None,
                x=x,
                y=y,
            )
        )
    if block.has_ball and values.shape[1] >= 2 * len(block.players) + 2:
        bx, by = METRICA.to_canonical(values[:, -2], values[:, -1])
        pieces.append(
            _entity_frame(
                match_id, t, period, frame_no, team="ball", player_id=None, jersey=None, x=bx, y=by
            )
        )
    return pd.concat(pieces, ignore_index=True)


def _entity_frame(
    match_id: str,
    t: np.ndarray,
    period: np.ndarray,
    frame_no: np.ndarray,
    *,
    team: str | None,
    player_id: str | None,
    jersey: int | None,
    x: np.ndarray,
    y: np.ndarray,
) -> pd.DataFrame:
    return pd.DataFrame(
        {
            "match_id": match_id,
            "t": t,
            "period": period,
            "frame": frame_no,
            "team": team,
            "player_id": player_id,
            "jersey": jersey,
            "x": x,
            "y": y,
            "vx": np.nan,
            "vy": np.nan,
            # EPTS carries no per-sample quality figure; leave it missing rather than invent 1.0.
            "confidence": np.nan,
        }
    )


# --------------------------------------------------------------------------------------
# events
# --------------------------------------------------------------------------------------


def load_events(
    match: int | str = MATCH,
    *,
    metadata_file: str | Path | None = None,
    events_file: str | Path | None = None,
    direction: str = "possession",
    fetcher: Fetcher | None = None,
) -> pd.DataFrame:
    """Load Metrica sample game 3 as canonical events.

    ``t`` is derived from ``start.frame`` and the metadata's period start frames, so it lands
    on exactly the clock :func:`load_tracking` uses; the file's own ``time`` field runs
    straight through half time and is kept in ``extra`` only.

    Args:
        match: game number, or any label when explicit files are given.
        metadata_file, events_file: read these instead of downloading them.
        direction: ``"possession"`` (default) rotates each event so the acting team attacks
            +x, per ``attack_direction_first_half``; ``"raw"`` keeps the source frame.
    """
    if direction not in {"possession", "raw"}:
        raise ValueError(f"unknown direction {direction!r}; use 'possession' or 'raw'")
    fetcher = fetcher or default_fetcher()
    meta = read_metadata(metadata_file or _fetch("metadata.xml", match, fetcher))
    if events_file is None:
        events_file = _fetch("events.json", match, fetcher)
    payload = json.loads(Path(events_file).read_text())
    records = payload.get("data") or []

    out = conform_events(
        pd.DataFrame(
            [_event_row(rec, meta, _match_id(match)) for rec in records], columns=list(_EVENT_KEYS)
        )
    )
    if direction == "possession" and not out.empty:
        pairs = zip(out["team_id"], out["period"], strict=True)
        mask = np.array([_sign(meta, team, period) < 0 for team, period in pairs])
        # 105 - NA is NA, so the set pieces and cards that carry no coordinates stay null.
        out = flip_events(out, mask)
    return finish_events(out)


_EVENT_KEYS = (
    "match_id",
    "competition",
    "season",
    "team_id",
    "team",
    "player_id",
    "player",
    "t",
    "period",
    "type",
    "subtype",
    "x",
    "y",
    "end_x",
    "end_y",
    "outcome",
    "pressure",
    "body_part",
    "extra",
)


def _sign(meta: Game3Metadata, team_id: Any, period: Any) -> int:
    """``+1`` when this row's team attacks +x; ``1`` (no flip) for rows with no team."""
    # team_id and period arrive as masked-array scalars, where `pd.NA in (...)` raises.
    if pd.isna(period) or pd.isna(team_id) or team_id not in ("home", "away"):
        return 1
    home = meta.home_sign(int(period))
    return home if team_id == "home" else -home


def _event_row(rec: Mapping[str, Any], meta: Game3Metadata, match_id: str) -> dict[str, Any]:
    period = int(rec.get("period") or 1)
    start, end = rec.get("start") or {}, rec.get("end") or {}
    names = _subtype_names(rec.get("subtypes"))
    tags = frozenset(filter(None, (snake(name) for name in names)))
    # from.name is "Player 10" with a space, so the join key has to be from.id.
    actor = rec.get("from") or {}
    target = rec.get("to") or {}

    x, y = _point(start)
    end_x, end_y = _point(end)
    return {
        "match_id": match_id,
        "competition": COMPETITION,
        # EPTS names the competition "Demo" and gives no season; see Game3Metadata for both.
        "season": None,
        # "home"/"away" rather than "FIFATMA", so events join straight onto tracking.team the
        # way games 1-2 do; the EPTS id is preserved in extra.
        "team_id": meta.side((rec.get("team") or {}).get("id")),
        "team": (rec.get("team") or {}).get("name"),
        "player_id": actor.get("id"),
        "player": actor.get("name"),
        "t": _event_t(start, period, meta),
        "period": period,
        "type": snake(_name(rec.get("type"))),
        "subtype": _subtype(tags),
        "x": x,
        "y": y,
        "end_x": end_x,
        "end_y": end_y,
        "outcome": _outcome(tags),
        # No under-pressure flag exists in any Metrica format.
        "pressure": False,
        "body_part": "head" if "head" in tags else None,
        "extra": encode_extra(
            {
                key: value
                for key, value in {
                    "index": rec.get("index"),
                    "team_ref": (rec.get("team") or {}).get("id"),
                    "start_frame": _int(start.get("frame")),
                    "end_frame": _int(end.get("frame")),
                    "match_time": start.get("time"),
                    "to": target.get("id"),
                    "to_name": target.get("name"),
                    "subtype_raw": "-".join(names) or None,
                    "tags": sorted(tags),
                }.items()
                if value not in (None, [], "")
            }
        ),
    }


def _subtype_names(value: Any) -> list[str]:
    """``subtypes`` is null on 2,750 events, one object on 477 and a list on 393."""
    if value is None:
        return []
    entries = [value] if isinstance(value, Mapping) else value
    if not isinstance(entries, Sequence):
        return []
    return [
        str(entry["name"]) for entry in entries if isinstance(entry, Mapping) and entry.get("name")
    ]


def _point(node: Mapping[str, Any]) -> tuple[float | None, float | None]:
    x, y = node.get("x"), node.get("y")
    if x is None or y is None:
        return None, None
    return METRICA.to_canonical(float(x), float(y))


def _event_t(start: Mapping[str, Any], period: int, meta: Game3Metadata) -> float | None:
    first = meta.periods.get(period, (1, 0))[0]
    frame = _int(start.get("frame"))
    if frame is not None:
        return (frame - first) / meta.frame_rate
    clock = start.get("time")
    # Metrica writes time == frame / frame_rate, so the same anchor works either way.
    return None if clock is None else float(clock) - first / meta.frame_rate


def _name(node: Any) -> str | None:
    return node.get("name") if isinstance(node, Mapping) else None


def _int(value: Any) -> int | None:
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


# --------------------------------------------------------------------------------------
# plumbing
# --------------------------------------------------------------------------------------


def _match_id(match: int | str) -> str:
    return f"metrica-{match}"


def _fetch(kind: str, match: int | str, fetcher: Fetcher) -> Path:
    name = f"Sample_Game_{match}_{kind}"
    return fetcher.download(f"{BASE}/Sample_Game_{match}/{name}", f"metrica/{name}", desc=name)

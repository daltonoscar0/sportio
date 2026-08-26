"""Write canonical events back out in StatsBomb's open-data JSON shape.

The canonical frame keeps most of a StatsBomb event alive: the identifiers, the possession
chain, the wall clock and every leftover key of the type sub-dict all survive in ``extra``,
so the original object can be largely rebuilt. Four reconstructions are less obvious than
they look:

* **The mirror is carried by ids, not by a flag.** ``sportio.loaders.statsbomb`` decides
  whether to rotate an event by comparing ``team.id`` against ``possession_team.id``, so it
  is not enough to put the possession team's *name* back -- the two ids have to differ again
  for exactly the rows that ``extra["mirrored"]`` marks, or one event in six reloads on the
  wrong half.
* **``length`` and ``angle`` in ``extra`` are metres and radians on the canonical pitch**,
  recomputed by the loader precisely because StatsBomb's own values live in 120x80 y-down
  axes. Writing them out unchanged would hand a StatsBomb consumer a number in the wrong
  units, so they are recomputed here in the source's axes instead.
* **360 freeze frames are a separate file upstream** (``three-sixty/{match_id}.json``) and
  are only written when ``three_sixty_path`` is given. Without it ``extra["freeze_frame"]``
  and ``extra["visible_area"]`` are the round trip's one lossy pair.
* **``pitch`` has to match whatever the frame was read with.** The loader's ``"landmark"``
  rescale is not the inverse of the ``"linear"`` one anywhere except at the landmarks
  themselves, so writing a landmark-read frame as linear moves every coordinate near the box.
"""

from __future__ import annotations

import json
import math
from pathlib import Path
from typing import Any

import pandas as pd

from ..pitch import PITCH_WIDTH, STATSBOMB, STATSBOMB_LANDMARK, PitchSpec

__all__ = ["to_statsbomb"]

#: Must mirror ``sportio.loaders.statsbomb``'s own choice: a frame read with the landmark map
#: and written with the linear one lands up to 5-7% out around the box.
_PITCH_SPECS = {"linear": STATSBOMB, "landmark": STATSBOMB_LANDMARK}

_SB_LENGTH = 120.0
_SB_WIDTH = 80.0

#: The loader rescales a shot height with the y axis; undo exactly that.
_Z_SCALE = PITCH_WIDTH / _SB_WIDTH

#: ``extra`` keys that came off the event itself rather than out of the type sub-dict, plus
#: the ones this module rebuilds by hand. Everything else in ``extra`` is a leftover sub-dict
#: key and goes straight back into the sub-dict.
_HANDLED = frozenset(
    {
        "angle",
        "counterpress",
        "duration",
        "end_z",
        "freeze_frame",
        "id",
        "index",
        "length",
        "minute",
        "mirrored",
        "off_camera",
        "out",
        "play_pattern",
        "position",
        "possession",
        "possession_team",
        "related_events",
        "second",
        "shot_freeze_frame",
        "visible_area",
    }
)

#: Types whose sub-dict has a ``position`` of its own. The loader writes the event-level
#: position into ``extra["position"]`` first and then lets the sub-dict overwrite it, so for
#: these types the value that survived is the sub-dict's and belongs back inside it.
_SUBDICT_POSITION = frozenset({"goal_keeper"})

#: Sub-dict key spellings that are not just ``snake(type.name)``; mirrors the loader's map.
_SUBDICT_ALIASES = {"goal_keeper": "goalkeeper"}

#: Used only when the frame holds a single team and a mirrored row still needs an opponent id
#: distinct from the acting team's.
_UNKNOWN_OPPONENT = "sportio-opponent"

#: Coordinates are rounded far below the metre-level tolerance anyone can measure, purely so
#: a location StatsBomb wrote as 69.2 comes back as 69.2 rather than 69.19999999999999.
_PRECISION = 9


def to_statsbomb(
    events: pd.DataFrame,
    path: str | Path,
    *,
    three_sixty_path: str | Path | None = None,
    pitch: str = "linear",
) -> Path:
    """Write a canonical events frame as a StatsBomb-shaped events JSON file.

    Args:
        events: canonical events frame, in the possession frame the loader produces.
        path: destination for the flat list of event objects.
        three_sixty_path: also write the companion ``three-sixty`` file there, so that
            ``extra["freeze_frame"]`` and ``extra["visible_area"]`` survive a reload.
        pitch: the rescale the frame was *read* with -- ``"linear"`` or ``"landmark"``, as in
            :func:`sportio.loaders.statsbomb.load_events`.

    Returns:
        The events file actually written.
    """
    if events.empty:
        raise ValueError("refusing to write an empty events frame")
    if pitch not in _PITCH_SPECS:
        raise ValueError(f"unknown pitch {pitch!r}; use 'linear' or 'landmark'")
    spec = _PITCH_SPECS[pitch]

    team_ids = _team_ids(events)
    payload: list[dict[str, Any]] = []
    frames: list[dict[str, Any]] = []
    for record in events.to_dict(orient="records"):
        extra = json.loads(_value(record.get("extra")) or "{}")
        payload.append(_event(record, extra, team_ids, spec))
        blob = _three_sixty(extra, spec)
        if blob is not None:
            frames.append(blob)

    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, separators=(",", ":")))

    if three_sixty_path is not None:
        target = Path(three_sixty_path)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(json.dumps(frames, separators=(",", ":")))
    return path


# --------------------------------------------------------------------------------------
# one event
# --------------------------------------------------------------------------------------


def _event(
    record: dict[str, Any],
    extra: dict[str, Any],
    team_ids: dict[str, str],
    spec: PitchSpec,
) -> dict:
    key = _value(record.get("type")) or "unknown"
    mirror = bool(extra.get("mirrored"))
    team_id = _value(record.get("team_id"))

    x, y = _to_source(_value(record.get("x")), _value(record.get("y")), mirror, spec)
    end = _end_location(record, extra, mirror, spec)

    event: dict[str, Any] = {}
    if extra.get("id") is not None:
        event["id"] = extra["id"]
    if extra.get("index") is not None:
        event["index"] = extra["index"]
    period = _value(record.get("period"))
    if period is not None:
        event["period"] = int(period)
    t = _value(record.get("t"))
    if t is not None:
        event["timestamp"] = _timestamp(float(t))
    for name in ("minute", "second"):
        if extra.get(name) is not None:
            event[name] = extra[name]

    event["type"] = {"name": _label(key)}
    if extra.get("possession") is not None:
        event["possession"] = extra["possession"]
    event["possession_team"] = {
        "id": _numeric(_possession_id(team_id, extra.get("possession_team"), mirror, team_ids)),
        "name": extra.get("possession_team"),
    }
    if extra.get("play_pattern") is not None:
        event["play_pattern"] = {"name": _label(extra["play_pattern"])}
    event["team"] = {"id": _numeric(team_id), "name": _value(record.get("team"))}

    player = _value(record.get("player"))
    player_id = _value(record.get("player_id"))
    if player is not None or player_id is not None:
        event["player"] = {"id": _numeric(player_id), "name": player}
    if extra.get("position") is not None and key not in _SUBDICT_POSITION:
        event["position"] = {"name": extra["position"]}
    if x is not None:
        event["location"] = [x, y]
    if extra.get("duration") is not None:
        event["duration"] = extra["duration"]
    # under_pressure and friends are written only when true; StatsBomb never emits false.
    if bool(_value(record.get("pressure"))):
        event["under_pressure"] = True
    for flag in ("counterpress", "off_camera", "out"):
        if extra.get(flag):
            event[flag] = True
    if extra.get("related_events"):
        event["related_events"] = extra["related_events"]

    body = _sub_dict(record, extra, key, x, y, end, mirror, spec)
    if body is not None:
        event[_SUBDICT_ALIASES.get(key, key)] = body
    return event


def _sub_dict(
    record: dict[str, Any],
    extra: dict[str, Any],
    key: str,
    x: float | None,
    y: float | None,
    end: list[float] | None,
    mirror: bool,
    spec: PitchSpec,
) -> dict[str, Any] | None:
    body: dict[str, Any] = {}
    subtype = _value(record.get("subtype"))
    if subtype is not None:
        body["type"] = {"name": _label(subtype)}

    outcome = _value(record.get("outcome"))
    # A completed pass is spelled by the *absence* of pass.outcome, which is how the loader
    # recognises it; writing {"name": "Complete"} would reload as a literal outcome instead.
    completed_pass = key == "pass" and outcome == "complete"
    if outcome is not None and not completed_pass:
        body["outcome"] = {"name": _label(outcome)}

    body_part = _value(record.get("body_part"))
    if body_part is not None:
        body["body_part"] = {"name": _label(body_part)}
    if end is not None:
        body["end_location"] = end
    if key in _SUBDICT_POSITION and extra.get("position") is not None:
        body["position"] = {"name": extra["position"]}

    for name, value in extra.items():
        if name not in _HANDLED:
            body[name] = value
    if extra.get("shot_freeze_frame") is not None:
        body["freeze_frame"] = [
            _shot_player(p, mirror, spec) for p in extra["shot_freeze_frame"]
        ]

    if key == "pass" and x is not None and y is not None and end is not None:
        # Recomputed in 120x80 y-down axes: extra["length"]/["angle"] are canonical metres
        # and radians, which would be a lie in a file a StatsBomb consumer reads.
        dx, dy = end[0] - x, end[1] - y
        body["length"] = round(math.hypot(dx, dy), _PRECISION)
        body["angle"] = round(math.atan2(dy, dx), _PRECISION)

    if body or completed_pass:
        return body
    return None


def _end_location(
    record: dict[str, Any], extra: dict[str, Any], mirror: bool, spec: PitchSpec
) -> list[float] | None:
    end_x, end_y = _to_source(
        _value(record.get("end_x")), _value(record.get("end_y")), mirror, spec
    )
    if end_x is None or end_y is None:
        return None
    end = [end_x, end_y]
    if extra.get("end_z") is not None:
        end.append(round(float(extra["end_z"]) / _Z_SCALE, _PRECISION))
    return end


# --------------------------------------------------------------------------------------
# 360 freeze frames
# --------------------------------------------------------------------------------------


def _three_sixty(extra: dict[str, Any], spec: PitchSpec) -> dict[str, Any] | None:
    """One entry of the companion ``three-sixty`` file, or None when the event has no frame."""
    if "freeze_frame" not in extra or extra.get("id") is None:
        return None
    mirror = bool(extra.get("mirrored"))
    blob: dict[str, Any] = {"event_uuid": extra["id"]}
    area = extra.get("visible_area")
    if area:
        # Upstream stores the polygon as a flat [x1,y1,x2,y2,...] run, not as pairs.
        flat: list[float] = []
        for point in area:
            px, py = _to_source(point[0], point[1], mirror, spec)
            flat.extend([px, py])
        blob["visible_area"] = flat
    blob["freeze_frame"] = [_freeze_player(p, mirror, spec) for p in extra["freeze_frame"]]
    return blob


def _freeze_player(player: dict[str, Any], mirror: bool, spec: PitchSpec) -> dict[str, Any]:
    out: dict[str, Any] = {
        "teammate": bool(player.get("teammate")),
        "actor": bool(player.get("actor")),
        "keeper": bool(player.get("keeper")),
    }
    location = _location(player, mirror, spec)
    if location is not None:
        out["location"] = location
    return out


def _shot_player(player: dict[str, Any], mirror: bool, spec: PitchSpec) -> dict[str, Any]:
    out: dict[str, Any] = {"teammate": bool(player.get("teammate"))}
    location = _location(player, mirror, spec)
    if location is not None:
        out["location"] = location
    if player.get("player") is not None or player.get("player_id") is not None:
        out["player"] = {"id": player.get("player_id"), "name": player.get("player")}
    if player.get("position") is not None:
        out["position"] = {"name": player["position"]}
    return out


def _location(player: dict[str, Any], mirror: bool, spec: PitchSpec) -> list[float] | None:
    """The location of one freeze-frame player, in source axes.

    A player with no location loses the key entirely rather than gaining a ``[null, null]``,
    which the loader would try to ``float()``.
    """
    point = player.get("location") or []
    if len(point) < 2:
        return None
    x, y = _to_source(point[0], point[1], mirror, spec)
    return None if x is None else [x, y]


# --------------------------------------------------------------------------------------
# small conversions
# --------------------------------------------------------------------------------------


def _to_source(
    x: float | None, y: float | None, mirror: bool, spec: PitchSpec
) -> tuple[float | None, float | None]:
    if x is None or y is None:
        return None, None
    sx, sy = spec.from_canonical(float(x), float(y))
    if mirror:
        sx, sy = _SB_LENGTH - sx, _SB_WIDTH - sy
    return round(sx, _PRECISION), round(sy, _PRECISION)


def _team_ids(events: pd.DataFrame) -> dict[str, str]:
    """Team name -> team id, so a possession team named in ``extra`` can be given its id back."""
    pairs = events.loc[events["team"].notna() & events["team_id"].notna(), ["team", "team_id"]]
    return {str(name): str(team_id) for name, team_id in pairs.drop_duplicates().to_numpy()}


def _possession_id(
    team_id: str | None, name: str | None, mirror: bool, team_ids: dict[str, str]
) -> str | None:
    if not mirror:
        # Equal ids are what tells the loader this row was never rotated.
        return team_id
    other = team_ids.get(str(name)) if name is not None else None
    if other is None or other == team_id:
        other = next((v for v in team_ids.values() if v != team_id), None)
    return other if other is not None else _UNKNOWN_OPPONENT


def _label(key: str) -> str:
    """Un-snake a vocabulary term: ``"goal_keeper"`` -> ``"Goal Keeper"``.

    Cosmetic but not optional -- a file full of ``"right_foot"`` is not one another StatsBomb
    consumer can read. It is also lossless in the direction that matters: the loader applies
    ``snake`` to every one of these fields, and ``snake`` of the title-cased form is always
    the original key back.
    """
    return key.replace("_", " ").title()


def _timestamp(seconds: float) -> str:
    """Seconds within the period -> ``"HH:MM:SS.mmm"``, StatsBomb's period clock."""
    total_ms = round(seconds * 1000.0)
    hours, rest = divmod(total_ms, 3_600_000)
    minutes, rest = divmod(rest, 60_000)
    return f"{hours:02d}:{minutes:02d}:{rest / 1000.0:06.3f}"


def _numeric(value: str | None) -> int | str | None:
    """StatsBomb ids are integers; the canonical frame stringifies them."""
    if value is None:
        return None
    text = str(value)
    try:
        return int(text)
    except ValueError:
        return text


def _value(value: Any) -> Any:
    """Unwrap pandas' nullable missing values to plain ``None``."""
    if value is None or value is pd.NA:
        return None
    if isinstance(value, float) and value != value:
        return None
    return value

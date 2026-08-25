"""SoccerNet Game State Reconstruction (GSR) and SoccerNet-Tracking (MOT).

Two different datasets with two different on-disk formats:

* **SN-GSR-2025** (https://huggingface.co/datasets/SoccerNet/SN-GSR-2025) is public -- no
  token, no NDA -- and each 30-second clip ships a ``Labels-GameState.json`` carrying
  *metric pitch coordinates* per detection. This is the format sportio can turn into real
  tracking, and it is what :func:`load_tracking` reads by default.
* **SoccerNet-Tracking** (the MOT-style ``gt/gt.txt`` + ``seqinfo.ini`` + ``gameinfo.ini``
  layout) is NDA-gated and, more importantly, is **image-space only**: bounding boxes in
  pixels with no camera calibration, so pitch coordinates cannot be recovered from it.
  :func:`read_mot` parses it faithfully and :func:`load_tracking` will emit canonical rows
  from it with ``x``/``y`` null rather than inventing a homography.

Neither path downloads anything: a GSR split is 11.2 GB and sportio will not pull that
behind your back. Point the loader at an already-extracted sequence directory. TODO.md
records the manual step.
"""

from __future__ import annotations

import configparser
import json
import logging
import warnings
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

from ..pitch import PitchSpec
from ..schema import conform_tracking
from ._common import finish_tracking

__all__ = [
    "GSR_URL",
    "SOCCERNET_PITCH",
    "load_tracking",
    "read_gsr",
    "read_mot",
]

log = logging.getLogger("sportio.soccernet")

GSR_URL = "https://huggingface.co/datasets/SoccerNet/SN-GSR-2025"
LABELS_NAME = "Labels-GameState.json"

#: SoccerNet pitch coordinates are already metres on a 105x68 pitch centred on the spot,
#: but +y points toward the *bottom* of the broadcast image, so y has to be flipped.
SOCCERNET_PITCH = PitchSpec(
    x_range=(-52.5, 52.5), y_range=(-34.0, 34.0), y_increases_up=False, name="soccernet"
)

#: ``attributes.team`` is left/right relative to the camera, not a club. Home/away is a
#: naming convention only; see the direction note in :func:`load_tracking`.
_SIDES = {"left": "home", "right": "away"}

# --------------------------------------------------------------------------------------
# GSR
# --------------------------------------------------------------------------------------


def _labels_path(path: str | Path) -> Path:
    path = Path(path)
    if path.is_dir():
        candidate = path / LABELS_NAME
        if not candidate.is_file():
            raise FileNotFoundError(f"{path} contains no {LABELS_NAME}; see {GSR_URL}")
        return candidate
    return path


def read_gsr(path: str | Path) -> tuple[dict[str, Any], pd.DataFrame]:
    """Parse one GSR sequence into ``(info, detections)`` without canonicalising.

    ``detections`` keeps everything the labels carry, including referees and
    uncalibrated frames, so callers who need more than the canonical schema can get it.
    """
    payload = json.loads(_labels_path(path).read_text())
    info = payload.get("info") or {}
    rows = []
    for ann in payload.get("annotations") or []:
        if ann.get("supercategory") != "object":
            continue
        attributes = ann.get("attributes") or {}
        pitch = ann.get("bbox_pitch")
        image = ann.get("bbox_image") or {}
        image_id = str(ann.get("image_id") or "")
        rows.append(
            {
                "image_id": image_id,
                # image_id is <split><seq><frame>; the frame is the last six digits.
                "frame": int(image_id[-6:]) if len(image_id) >= 6 else None,
                "track_id": ann.get("track_id"),
                "role": attributes.get("role"),
                "team": _clean_team(attributes.get("team")),
                "jersey": _jersey(attributes.get("jersey")),
                "pitch_x": None if pitch is None else pitch.get("x_bottom_middle"),
                "pitch_y": None if pitch is None else pitch.get("y_bottom_middle"),
                "image_x": image.get("x_center"),
                "image_y": image.get("y_center"),
                "image_w": image.get("w"),
                "image_h": image.get("h"),
            }
        )
    return info, pd.DataFrame(rows)


def _clean_team(value: Any) -> str | None:
    """``team`` is ``"left"``, ``"right"``, ``null`` -- or, per sn-trackeval, ``"nan"``."""
    if value is None:
        return None
    text = str(value).strip().lower()
    return None if text in {"", "nan", "none"} else text


def _jersey(value: Any) -> int | None:
    if value is None:
        return None
    text = str(value).strip()
    return int(text) if text.isdigit() else None


def _gsr_tracking(
    path: str | Path, *, keep_uncalibrated: bool, margin: float | None
) -> pd.DataFrame:
    info, det = read_gsr(path)
    name = str(info.get("name") or Path(path).name)
    fps = float(info.get("frame_rate") or 25.0)
    period = _period(info)
    # clip_start is milliseconds into the half, so t stays "seconds within the period".
    offset = float(info.get("clip_start") or 0.0) / 1000.0

    if det.empty:
        return conform_tracking(pd.DataFrame(columns=list(_TRACKING_KEYS)))

    calibrated = det["pitch_x"].notna()
    if not keep_uncalibrated:
        dropped = int((~calibrated).sum())
        if dropped:
            # Whole stretches of a clip lose camera calibration; those detections have no
            # pitch position at all, so they are dropped rather than faked.
            log.info("%s: dropping %d detections with no pitch calibration", name, dropped)
        det = det.loc[calibrated]
    if det.empty:
        return conform_tracking(pd.DataFrame(columns=list(_TRACKING_KEYS)))

    keep = det["role"].isin(("player", "goalkeeper", "ball"))
    det = det.loc[keep]

    x, y = SOCCERNET_PITCH.to_canonical(
        det["pitch_x"].astype("float64").to_numpy(),
        det["pitch_y"].astype("float64").to_numpy(),
    )
    is_ball = det["role"].eq("ball")
    side = det["team"].map(_SIDES)

    out = pd.DataFrame(
        {
            "match_id": name,
            "t": offset + (det["frame"].astype("float64") - 1.0) / fps,
            "period": period,
            "frame": det["frame"].astype("Int64"),
            "team": np.where(is_ball, "ball", side.fillna("home")),
            "player_id": np.where(is_ball, None, name + "-" + det["track_id"].astype("string")),
            "jersey": np.where(is_ball, None, det["jersey"]),
            "x": x,
            "y": y,
            "vx": np.nan,
            "vy": np.nan,
            # These are ground-truth annotations, so anything that survives the sanity
            # filter below is fully trusted.
            "confidence": 1.0,
        }
    )
    # A player with no team label cannot be assigned a side; drop rather than guess.
    keep_row = is_ball.to_numpy() | side.notna().to_numpy()
    if margin is not None:
        # Unprojection is unbounded, so a detection near the horizon can land hundreds of
        # metres off the pitch. Those are numerical artefacts, not positions.
        sane = _on_pitch(x, y, margin)
        if (~sane).any():
            log.info("%s: dropping %d unprojection blow-ups", name, int((~sane).sum()))
        keep_row &= sane
    return conform_tracking(out.loc[keep_row])


def _on_pitch(x: np.ndarray, y: np.ndarray, margin: float) -> np.ndarray:
    inside = (
        (x > -margin)
        & (x < 105.0 + margin)
        & (y > -margin)
        & (y < 68.0 + margin)
    )
    # A missing position is not a blow-up; keep_uncalibrated decides its fate elsewhere.
    return inside | ~(np.isfinite(x) & np.isfinite(y))


def _period(info: dict[str, Any]) -> int:
    """``game_time_start`` is ``"<half> - <MM:SS>"``."""
    raw = str(info.get("game_time_start") or "")
    head = raw.split(" - ")[0].strip()
    return int(head) if head.isdigit() else 1


_TRACKING_KEYS = (
    "match_id", "t", "period", "frame", "team", "player_id",
    "jersey", "x", "y", "vx", "vy", "confidence",
)


# --------------------------------------------------------------------------------------
# MOT
# --------------------------------------------------------------------------------------

_MOT_COLUMNS = (
    "frame", "track_id", "bbox_left", "bbox_top", "bbox_width", "bbox_height",
    "conf", "x", "y", "z",
)


def read_mot(path: str | Path) -> tuple[dict[str, Any], pd.DataFrame]:
    """Parse a SoccerNet-Tracking MOT sequence directory into ``(info, detections)``.

    Reads ``gt/gt.txt`` plus whichever of ``seqinfo.ini`` / ``gameinfo.ini`` are present.
    Detections are **image space only** -- the archive ships no calibration.
    """
    directory = Path(path)
    gt = directory / "gt" / "gt.txt"
    if not gt.is_file():
        raise FileNotFoundError(f"{directory} contains no gt/gt.txt")

    det = pd.read_csv(gt, header=None, names=list(_MOT_COLUMNS))
    info: dict[str, Any] = {}
    for name in ("seqinfo.ini", "gameinfo.ini"):
        candidate = directory / name
        if candidate.is_file():
            info.update(_read_ini(candidate))

    tracklets = _tracklets(info)
    det["role"] = det["track_id"].map(lambda t: (tracklets.get(int(t)) or {}).get("role"))
    det["team"] = det["track_id"].map(lambda t: (tracklets.get(int(t)) or {}).get("team"))
    det["jersey"] = det["track_id"].map(lambda t: (tracklets.get(int(t)) or {}).get("jersey"))
    return info, det


def _read_ini(path: Path) -> dict[str, Any]:
    """Tolerant INI read: values may contain ``=``, and blank lines are fine."""
    parser = configparser.ConfigParser(strict=False)
    parser.optionxform = str  # keys are case-sensitive (imDir, seqLength, ...)
    text = path.read_text()
    if not text.lstrip().startswith("["):
        text = "[DEFAULT]\n" + text
    parser.read_string(text)
    out: dict[str, Any] = {}
    for section in parser.sections():
        out.update(dict(parser.items(section)))
    out.update(dict(parser.defaults()))
    return out


def _tracklets(info: dict[str, Any]) -> dict[int, dict[str, Any]]:
    """``trackletID_<i> = "<role phrase>; <extra>"``, e.g. ``"player team left; 10"``."""
    out: dict[int, dict[str, Any]] = {}
    for key, value in info.items():
        if not key.startswith("trackletID_"):
            continue
        try:
            track_id = int(key.split("_", 1)[1])
        except ValueError:  # pragma: no cover - defensive
            continue
        text = str(value)
        head, _, tail = text.partition(";")
        head = head.strip().lower()
        role = "ball" if "ball" in head else head.split(" ")[0] or None
        team = "left" if "left" in head else ("right" if "right" in head else None)
        # Upstream forgets to strip here and loses every jersey written as "; 10".
        jersey = tail.strip()
        out[track_id] = {
            "role": role,
            "team": team,
            "jersey": int(jersey) if jersey.isdigit() else None,
        }
    return out


def _mot_tracking(path: str | Path) -> pd.DataFrame:
    info, det = read_mot(path)
    name = str(info.get("name") or Path(path).name)
    fps = float(info.get("frameRate") or 25.0)
    period_raw = str(info.get("gameTimeStart") or "").split(" - ")[0].strip()
    period = int(period_raw) if period_raw.isdigit() else 1
    offset = float(info.get("clipStart") or 0.0) / 1000.0

    warnings.warn(
        f"{name}: SoccerNet-Tracking MOT data is image-space only, so canonical x/y are "
        "null. Use SN-GSR-2025 for metric pitch positions.",
        UserWarning,
        stacklevel=3,
    )

    # Referees, "other" tracklets and track_ids missing from gameinfo.ini have no side in
    # the canonical schema; dropping them beats filing them under "home".
    det = det.loc[det["role"].isin(("player", "goalkeeper", "ball")) | det["team"].notna()]
    is_ball = det["role"].eq("ball")
    side = det["team"].map(_SIDES)
    det = det.loc[is_ball.to_numpy() | side.notna().to_numpy()]
    is_ball = det["role"].eq("ball")
    side = det["team"].map(_SIDES)
    out = pd.DataFrame(
        {
            "match_id": name,
            "t": offset + (det["frame"].astype("float64") - 1.0) / fps,
            "period": period,
            "frame": det["frame"].astype("Int64"),
            "team": np.where(is_ball, "ball", side),
            "player_id": np.where(is_ball, None, name + "-" + det["track_id"].astype("string")),
            "jersey": np.where(is_ball, None, det["jersey"]),
            "x": np.nan,
            "y": np.nan,
            "vx": np.nan,
            "vy": np.nan,
            "confidence": det["conf"].astype("float64").clip(0.0, 1.0),
        }
    )
    return conform_tracking(out)


# --------------------------------------------------------------------------------------
# public entry point
# --------------------------------------------------------------------------------------


def load_tracking(
    path: str | Path,
    *,
    format: str | None = None,
    keep_uncalibrated: bool = False,
    margin: float | None = 15.0,
    hz: float | None = None,
    velocities: bool = True,
    direction: str = "raw",
) -> pd.DataFrame:
    """Load one already-downloaded SoccerNet sequence as canonical tracking.

    Args:
        path: a GSR sequence directory (or its ``Labels-GameState.json``), or a MOT
            sequence directory containing ``gt/gt.txt``.
        format: ``"gsr"`` or ``"mot"``; auto-detected from the directory contents.
        keep_uncalibrated: GSR clips can lose camera calibration for hundreds of
            consecutive frames, leaving ``bbox_pitch`` null. Those detections are dropped
            by default; set this to keep them with null coordinates.
        margin: drop detections whose unprojected position falls more than this many metres
            outside the pitch. Unprojection near the horizon is unbounded and produces
            positions hundreds of metres away. ``None`` keeps every point.
        hz: resample target; ``None`` keeps the native 25 Hz.
        velocities: fill ``vx``/``vy``.
        direction: defaults to ``"raw"``. A GSR clip is 30 seconds with no goal or
            possession context, so attacking direction genuinely cannot be inferred --
            and ``team`` is "left"/"right" w.r.t. the camera, not a club. Normalising
            direction here would be a guess, so it is left to the caller.
    """
    kind = format or _detect(path)
    if kind == "gsr":
        df = _gsr_tracking(path, keep_uncalibrated=keep_uncalibrated, margin=margin)
    elif kind == "mot":
        df = _mot_tracking(path)
    else:
        raise ValueError(f"unknown SoccerNet format {kind!r}; use 'gsr' or 'mot'")
    return finish_tracking(df, hz=hz, velocities=velocities, direction=direction)


def _detect(path: str | Path) -> str:
    path = Path(path)
    if path.is_file() and path.name == LABELS_NAME:
        return "gsr"
    if (path / LABELS_NAME).is_file():
        return "gsr"
    if (path / "gt" / "gt.txt").is_file():
        return "mot"
    raise FileNotFoundError(
        f"{path} looks like neither a GSR sequence ({LABELS_NAME}) nor a MOT sequence "
        f"(gt/gt.txt). Download a split from {GSR_URL} and extract one sequence."
    )

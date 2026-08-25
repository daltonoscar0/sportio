"""Acceptance checks against the live sources.

Deselected by default (``-m "not network"`` in ``pyproject.toml``) so the standard suite
stays offline and fast. Run them with::

    uv run pytest -m network

They hit real hosts at sportio's one-request-per-second rate limit and cache everything
under ``data/raw/``, so a second run is free.
"""

from __future__ import annotations

import os

import pytest

import sportio
from sportio.loaders import statsbomb

pytestmark = pytest.mark.network


@pytest.fixture(autouse=True)
def _online(monkeypatch: pytest.MonkeyPatch) -> None:
    """Undo the session-wide offline lock, but keep the repo's own download cache."""
    monkeypatch.delenv("SPORTIO_OFFLINE", raising=False)
    monkeypatch.delenv("SPORTIO_DATA_DIR", raising=False)
    os.environ.pop("SPORTIO_OFFLINE", None)


def test_euro_2024_resolves_and_lists_matches() -> None:
    competition_id, season_id = statsbomb.find_competition("Euro 2024")
    assert (competition_id, season_id) == statsbomb.EURO_2024
    matches = statsbomb.load_matches(competition_id, season_id)
    assert len(matches) == 51
    assert (matches["match_status_360"] == "available").all()


def test_corners_on_euro_2024_carry_360_freeze_frames() -> None:
    """The spec's acceptance test, on the real competition.

    Note the ``with_freeze_frame`` filter: 360 coverage is ~87% of events overall but only
    a minority of *corner deliveries* carry a frame -- 3 of 12 in the final. Every corner
    that does have one comfortably clears 15 players.
    """
    events = sportio.load_events("statsbomb", competition="Euro 2024", limit=3)
    assert len(events) > 5_000

    corners = sportio.corners(events)
    assert len(corners) > 0

    with_frames = sportio.corners(events, with_freeze_frame=True)
    assert len(with_frames) > 0
    sizes = sportio.freeze_frame_size(with_frames)
    assert (sizes >= 15).all(), f"freeze frame sizes: {sorted(sizes)}"

    players = sportio.freeze_frames(with_frames)
    assert len(players) >= 15 * len(with_frames)
    assert players["x"].astype("float64").between(-10, 115).all()


def test_metrica_game_one_round_trips_in_full(tmp_path) -> None:
    tracking = sportio.load_tracking("metrica", match=1)
    assert len(tracking) > 3_000_000
    assert sportio.native_hz(tracking) == pytest.approx(25.0)

    written = sportio.to_metrica(tracking, tmp_path / "game1.csv")
    back = sportio.load_tracking(
        "metrica", match=1, home_file=written["home"], away_file=written["away"]
    )
    assert back.shape == tracking.shape
    for column in ("t", "x", "y"):
        original = tracking[column].astype("float64").to_numpy()
        reloaded = back[column].astype("float64").to_numpy()
        assert reloaded == pytest.approx(original, abs=1e-6, nan_ok=True), column


def test_skillcorner_tracking_streams_from_the_lfs_media_host() -> None:
    # raw.githubusercontent.com returns a 133-byte Git LFS pointer for these files.
    tracking = sportio.load_tracking("skillcorner", match=1886347, max_frames=200)
    sportio.validate_tracking(tracking)
    assert len(tracking) > 200
    assert sportio.native_hz(tracking) == pytest.approx(10.0)


def test_rugby_six_nations_day() -> None:
    events = sportio.load_events("rugby", date="20250201")
    sportio.validate_events(events)
    assert events["match_id"].nunique() == 2
    assert "try" in set(events["type"])

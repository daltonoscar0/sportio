"""Shared test setup.

The whole suite runs offline: ``SPORTIO_OFFLINE`` is forced on and the download cache is
redirected into a tmp dir, so a test that forgets to use a fixture fails loudly instead of
quietly hitting the network.
"""

from __future__ import annotations

import os
from pathlib import Path

import pytest

FIXTURES = Path(__file__).parent / "fixtures"


@pytest.fixture(scope="session", autouse=True)
def _offline(tmp_path_factory: pytest.TempPathFactory) -> None:
    os.environ["SPORTIO_OFFLINE"] = "1"
    os.environ["SPORTIO_DATA_DIR"] = str(tmp_path_factory.mktemp("sportio-cache"))


@pytest.fixture(scope="session")
def fixtures() -> Path:
    return FIXTURES


def fixture_path(*parts: str) -> Path:
    """Path to a committed fixture, skipping the test if it is not present."""
    path = FIXTURES.joinpath(*parts)
    if not path.exists():
        pytest.skip(f"fixture missing: {path.relative_to(FIXTURES.parent)}")
    return path

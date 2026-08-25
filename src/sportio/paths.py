"""Where sportio keeps its downloads.

Resolution order for the raw-data cache:

1. ``$SPORTIO_DATA_DIR`` if set;
2. ``<repo root>/data/raw`` when running from inside a checkout (``pyproject.toml`` above us);
3. ``./data/raw`` relative to the current working directory.
"""

from __future__ import annotations

import os
from functools import lru_cache
from pathlib import Path

__all__ = ["cache_path", "data_root", "fixtures_root", "repo_root"]


@lru_cache(maxsize=1)
def repo_root() -> Path | None:
    """Nearest ancestor directory of the CWD that looks like the sportio checkout."""
    here = Path.cwd().resolve()
    for candidate in (here, *here.parents):
        if (candidate / "pyproject.toml").is_file() and (candidate / "src" / "sportio").is_dir():
            return candidate
    return None


def data_root() -> Path:
    """Root of the gitignored raw-download cache. Created on first use."""
    env = os.environ.get("SPORTIO_DATA_DIR")
    if env:
        root = Path(env).expanduser()
    else:
        base = repo_root() or Path.cwd()
        root = base / "data" / "raw"
    root.mkdir(parents=True, exist_ok=True)
    return root


def cache_path(*parts: str) -> Path:
    """A path under the raw cache, with parent directories created."""
    path = data_root().joinpath(*parts)
    path.parent.mkdir(parents=True, exist_ok=True)
    return path


def fixtures_root() -> Path:
    """The committed test fixtures directory (only meaningful inside a checkout)."""
    root = repo_root()
    if root is None:  # pragma: no cover - only hit outside a checkout
        raise FileNotFoundError("fixtures are only available inside a sportio checkout")
    return root / "tests" / "fixtures"

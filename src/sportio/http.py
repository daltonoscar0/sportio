"""Polite, cached HTTP.

One request per second per host, exponential backoff on transient failures, and every
byte that comes back is written under :func:`sportio.paths.data_root` so a second run is
offline and free. Set ``SPORTIO_OFFLINE=1`` to forbid the network entirely.
"""

from __future__ import annotations

import json
import logging
import os
import random
import threading
import time
from collections.abc import Mapping
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

import requests
from tqdm.auto import tqdm

from .paths import cache_path

__all__ = ["Fetcher", "OfflineError", "default_fetcher", "is_offline"]

log = logging.getLogger("sportio.http")

USER_AGENT = "sportio/0.1.0 (+https://github.com/daltonoscar0/sportio)"
RETRY_STATUS = frozenset({408, 425, 429, 500, 502, 503, 504})


class OfflineError(RuntimeError):
    """Raised when data is not cached and the network is disabled."""


def is_offline() -> bool:
    return os.environ.get("SPORTIO_OFFLINE", "").strip().lower() in {"1", "true", "yes"}


class Fetcher:
    """Rate-limited, retrying, disk-caching HTTP client.

    Args:
        min_interval: minimum seconds between requests to the *same* host.
        max_retries: attempts per URL before giving up.
        timeout: per-request socket timeout in seconds.
    """

    def __init__(
        self,
        min_interval: float = 1.0,
        max_retries: int = 5,
        timeout: float = 30.0,
        session: requests.Session | None = None,
    ) -> None:
        self.min_interval = min_interval
        self.max_retries = max_retries
        self.timeout = timeout
        self.session = session or requests.Session()
        self.session.headers.update({"User-Agent": USER_AGENT})
        self._last_hit: dict[str, float] = {}
        self._lock = threading.Lock()

    # -- rate limiting ------------------------------------------------------------------

    def _wait_turn(self, url: str) -> None:
        host = urlsplit(url).netloc
        with self._lock:
            last = self._last_hit.get(host)
            now = time.monotonic()
            if last is not None:
                delay = self.min_interval - (now - last)
                if delay > 0:
                    time.sleep(delay)
                    now = time.monotonic()
            self._last_hit[host] = now

    # -- fetching -----------------------------------------------------------------------

    def get(
        self,
        url: str,
        *,
        params: Mapping[str, Any] | None = None,
        stream: bool = False,
    ) -> requests.Response:
        """GET ``url`` with rate limiting and exponential backoff. Not cached."""
        if is_offline():
            raise OfflineError(f"SPORTIO_OFFLINE is set; refusing to fetch {url}")
        last_exc: Exception | None = None
        for attempt in range(self.max_retries):
            self._wait_turn(url)
            try:
                resp = self.session.get(url, params=params, timeout=self.timeout, stream=stream)
            except requests.RequestException as exc:
                last_exc = exc
            else:
                if resp.status_code not in RETRY_STATUS:
                    resp.raise_for_status()
                    return resp
                last_exc = requests.HTTPError(f"{resp.status_code} for {url}", response=resp)
                retry_after = _retry_after(resp)
                if retry_after is not None:
                    time.sleep(min(retry_after, 60.0))
                    continue
            backoff = min(self.min_interval * (2**attempt), 60.0)
            backoff += random.uniform(0, self.min_interval)  # noqa: S311 - jitter, not crypto
            log.warning("retry %d/%d for %s in %.1fs", attempt + 1, self.max_retries, url, backoff)
            time.sleep(backoff)
        raise requests.RequestException(f"giving up on {url} after {self.max_retries} attempts") from last_exc

    def bytes(self, url: str, cache: str | Path, *, force: bool = False) -> bytes:
        """Return the body of ``url``, caching it at ``cache`` (relative to the data root)."""
        path = cache if isinstance(cache, Path) else cache_path(*Path(cache).parts)
        if path.exists() and path.stat().st_size > 0 and not force:
            return path.read_bytes()
        if is_offline():
            raise OfflineError(f"{path} is not cached and SPORTIO_OFFLINE is set")
        payload = self.get(url).content
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_suffix(path.suffix + ".part")
        tmp.write_bytes(payload)
        tmp.replace(path)
        return payload

    def text(self, url: str, cache: str | Path, *, force: bool = False) -> str:
        return self.bytes(url, cache, force=force).decode("utf-8")

    def json(self, url: str, cache: str | Path, *, force: bool = False) -> Any:
        raw = self.bytes(url, cache, force=force)
        try:
            return json.loads(raw)
        except json.JSONDecodeError as exc:
            path = cache if isinstance(cache, Path) else cache_path(*Path(cache).parts)
            raise ValueError(f"cached file {path} is not valid JSON: {exc}") from exc

    def download(
        self,
        url: str,
        cache: str | Path,
        *,
        force: bool = False,
        desc: str | None = None,
    ) -> Path:
        """Stream a (potentially large) file to the cache and return its path."""
        path = cache if isinstance(cache, Path) else cache_path(*Path(cache).parts)
        if path.exists() and path.stat().st_size > 0 and not force:
            return path
        if is_offline():
            raise OfflineError(f"{path} is not cached and SPORTIO_OFFLINE is set")
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_suffix(path.suffix + ".part")
        with self.get(url, stream=True) as resp:
            total = int(resp.headers.get("Content-Length") or 0)
            bar = tqdm(
                total=total or None,
                unit="B",
                unit_scale=True,
                desc=desc or path.name,
                leave=False,
            )
            with tmp.open("wb") as fh, bar:
                for chunk in resp.iter_content(chunk_size=1 << 16):
                    fh.write(chunk)
                    bar.update(len(chunk))
        tmp.replace(path)
        return path


def _retry_after(resp: requests.Response) -> float | None:
    value = resp.headers.get("Retry-After")
    if not value:
        return None
    try:
        return float(value)
    except ValueError:
        return None


_DEFAULT: Fetcher | None = None


def default_fetcher() -> Fetcher:
    """Process-wide fetcher, so the per-host rate limit is actually global."""
    global _DEFAULT
    if _DEFAULT is None:
        _DEFAULT = Fetcher()
    return _DEFAULT

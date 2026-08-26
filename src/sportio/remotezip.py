"""Read selected members out of a remote ZIP without downloading it.

A zip's index lives at the *end* of the file, so given a server that honours byte ranges you
can read the central directory, pick the members you want, and fetch only those. For the
SoccerNet game-state archive that is the difference between 192 MB of annotations and an
11.2 GB download whose bulk is JPEGs nothing here ever opens.

Only the parts of the format that this needs are implemented: ZIP64 end-of-central-directory,
stored and deflated members. Encryption, spanned archives and the zip64 "version 2" directory
are not supported and say so rather than mis-decoding.
"""

from __future__ import annotations

import struct
import zlib
from dataclasses import dataclass
from functools import cached_property
from pathlib import Path

from .http import Fetcher, default_fetcher
from .paths import cache_path

__all__ = ["RemoteZip", "ZipEntry"]

_EOCD = b"PK\x05\x06"
_EOCD64_LOCATOR = b"PK\x06\x07"
_CENTRAL = b"PK\x01\x02"
_LOCAL = b"PK\x03\x04"

#: 32-bit fields use this as "look in the ZIP64 extra field instead".
_ZIP64_SENTINEL = 0xFFFFFFFF

_STORED = 0
_DEFLATED = 8

#: How much of the tail to read when hunting for the end-of-central-directory record. The
#: record itself is 22 bytes plus up to 64 KB of archive comment.
_TAIL = 70_000

#: A local file header is 30 bytes plus a name and an extra field, both bounded in practice.
#: Over-reading by this much lets one request cover the header and the payload together.
_LOCAL_HEADER_SLACK = 1024


@dataclass(frozen=True, slots=True)
class ZipEntry:
    """One member of the archive, as described by the central directory."""

    name: str
    offset: int
    compressed_size: int
    uncompressed_size: int
    method: int


class RemoteZip:
    """Random access to a zip over HTTP range requests.

    Args:
        url: the archive. The server must send ``Accept-Ranges: bytes`` and a
            ``Content-Length``; :class:`sportio.http.Fetcher` rejects a server that answers a
            range request with the whole body.
        cache_key: directory under the sportio data root for the cached central directory,
            which is worth keeping -- it is megabytes and never changes for a given archive.
    """

    def __init__(self, url: str, *, cache_key: str, fetcher: Fetcher | None = None) -> None:
        self.url = url
        self.cache_key = cache_key
        self.fetcher = fetcher or default_fetcher()

    @cached_property
    def entries(self) -> dict[str, ZipEntry]:
        """Every member, by name."""
        return _parse_central_directory(self._central_directory())

    def namelist(self) -> list[str]:
        return sorted(self.entries)

    def read(self, name: str) -> bytes:
        """Fetch and decompress one member."""
        try:
            entry = self.entries[name]
        except KeyError:
            raise KeyError(f"{name!r} is not in {self.url}") from None
        if entry.method not in (_STORED, _DEFLATED):
            raise NotImplementedError(
                f"{name} uses compression method {entry.method}, which sportio does not decode"
            )

        # One request usually covers the local header and the payload; the header's own name
        # and extra lengths can differ from the central directory's, so they must be read here.
        want = 30 + _LOCAL_HEADER_SLACK + entry.compressed_size
        buffer = self.fetcher.byte_range(self.url, entry.offset, entry.offset + want - 1)
        if buffer[:4] != _LOCAL:
            raise ValueError(f"{name}: no local file header at offset {entry.offset}")
        name_len, extra_len = struct.unpack("<HH", buffer[26:30])
        start = 30 + name_len + extra_len
        end = start + entry.compressed_size
        if end > len(buffer):  # the header was unusually long; go back for the rest
            tail = self.fetcher.byte_range(
                self.url, entry.offset + len(buffer), entry.offset + end - 1
            )
            buffer += tail
        payload = buffer[start:end]

        data = payload if entry.method == _STORED else zlib.decompressobj(-15).decompress(payload)
        if len(data) != entry.uncompressed_size:
            raise ValueError(
                f"{name}: decompressed {len(data)} bytes, directory said "
                f"{entry.uncompressed_size}"
            )
        return data

    def extract(self, name: str, destination: str | Path) -> Path:
        """Read a member and write it out, atomically."""
        path = Path(destination)
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_suffix(path.suffix + ".part")
        tmp.write_bytes(self.read(name))
        tmp.replace(path)
        return path

    # -- central directory --------------------------------------------------------------

    def _central_directory(self) -> bytes:
        cached = cache_path(self.cache_key, "central-directory.bin")
        if cached.exists() and cached.stat().st_size > 0:
            return cached.read_bytes()
        # No offline check here on purpose: the fetcher owns that policy, and keeping it in one
        # place is what makes this class testable with an injected fetcher.
        total = self.fetcher.content_length(self.url)
        tail = self.fetcher.byte_range(self.url, max(0, total - _TAIL))
        offset, size = _locate_central_directory(tail, total)
        directory = self.fetcher.byte_range(self.url, offset, offset + size - 1)

        cached.parent.mkdir(parents=True, exist_ok=True)
        tmp = cached.with_suffix(".part")
        tmp.write_bytes(directory)
        tmp.replace(cached)
        return directory


def _locate_central_directory(tail: bytes, total: int) -> tuple[int, int]:
    """``(offset, size)`` of the central directory, preferring the ZIP64 record."""
    locator = tail.rfind(_EOCD64_LOCATOR)
    if locator >= 0:
        eocd64_offset = struct.unpack("<Q", tail[locator + 8 : locator + 16])[0]
        # The ZIP64 record sits just before the locator, so the tail already holds it unless
        # the archive comment is enormous.
        start = eocd64_offset - (total - len(tail))
        if 0 <= start <= len(tail) - 56:
            record = tail[start : start + 56]
            if record[:4] == b"PK\x06\x06":
                size, offset = struct.unpack("<QQ", record[40:56])
                return offset, size

    end = tail.rfind(_EOCD)
    if end < 0:
        raise ValueError("no end-of-central-directory record; is this a zip?")
    size, offset = struct.unpack("<II", tail[end + 12 : end + 20])
    if offset == _ZIP64_SENTINEL or size == _ZIP64_SENTINEL:
        raise ValueError("archive needs its ZIP64 record and it was not found in the tail")
    return offset, size


def _parse_central_directory(blob: bytes) -> dict[str, ZipEntry]:
    entries: dict[str, ZipEntry] = {}
    i = 0
    while i + 46 <= len(blob) and blob[i : i + 4] == _CENTRAL:
        method = struct.unpack("<H", blob[i + 10 : i + 12])[0]
        compressed, uncompressed = struct.unpack("<II", blob[i + 20 : i + 28])
        name_len, extra_len, comment_len = struct.unpack("<HHH", blob[i + 28 : i + 34])
        offset = struct.unpack("<I", blob[i + 42 : i + 46])[0]

        name = blob[i + 46 : i + 46 + name_len].decode("utf-8", errors="replace")
        extra = blob[i + 46 + name_len : i + 46 + name_len + extra_len]
        uncompressed, compressed, offset = _apply_zip64(extra, uncompressed, compressed, offset)

        entries[name] = ZipEntry(name, offset, compressed, uncompressed, method)
        i += 46 + name_len + extra_len + comment_len
    if not entries:
        raise ValueError("central directory held no entries")
    return entries


def _apply_zip64(
    extra: bytes, uncompressed: int, compressed: int, offset: int
) -> tuple[int, int, int]:
    """Pull whichever of the three fields overflowed out of the 0x0001 extra field.

    They appear in a fixed order -- uncompressed, compressed, offset, disk -- but *only* the
    ones whose 32-bit slot held the sentinel are present, so they have to be consumed in that
    order rather than read by position. Getting this wrong reads the offset as a size and sends
    the range request to nowhere.
    """
    overflowed = [
        value == _ZIP64_SENTINEL for value in (uncompressed, compressed, offset)
    ]
    if not any(overflowed):
        return uncompressed, compressed, offset

    i = 0
    while i + 4 <= len(extra):
        header_id, size = struct.unpack("<HH", extra[i : i + 4])
        body = extra[i + 4 : i + 4 + size]
        if header_id == 0x0001:
            values = list(struct.unpack("<" + "Q" * (len(body) // 8), body[: (len(body) // 8) * 8]))
            taken = iter(values)
            if overflowed[0]:
                uncompressed = next(taken, uncompressed)
            if overflowed[1]:
                compressed = next(taken, compressed)
            if overflowed[2]:
                offset = next(taken, offset)
            break
        i += 4 + size
    return uncompressed, compressed, offset

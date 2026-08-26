"""Reading selected members out of a remote zip.

The whole point is not downloading the archive, so the tests build real zips locally and serve
them through a fetcher that only ever answers byte ranges -- if the reader asked for the whole
file, these would still pass but the network test would be pulling 11.2 GB.
"""

from __future__ import annotations

import io
import os
import struct
import zipfile
from dataclasses import replace

import pytest

from sportio.http import Fetcher
from sportio.remotezip import RemoteZip, _apply_zip64, _locate_central_directory


class SlicingFetcher:
    """Serves ranges out of an in-memory archive and counts what was asked for."""

    def __init__(self, blob: bytes) -> None:
        self.blob = blob
        self.requests: list[tuple[int, int | None]] = []

    def content_length(self, url: str) -> int:
        return len(self.blob)

    def byte_range(self, url: str, start: int, end: int | None = None) -> bytes:
        self.requests.append((start, end))
        if start < 0:
            return self.blob[start:]
        return self.blob[start : len(self.blob) if end is None else end + 1]


def _archive(members: dict[str, bytes], compression: int = zipfile.ZIP_DEFLATED) -> bytes:
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", compression) as archive:
        for name, payload in members.items():
            archive.writestr(name, payload)
    return buffer.getvalue()


@pytest.fixture
def sample() -> tuple[bytes, dict[str, bytes]]:
    members = {
        "SNGS-001/Labels-GameState.json": b'{"info":{"name":"SNGS-001"}}' * 300,
        # Incompressible, and far bigger than the tail probe -- this is the bulk a real
        # archive is made of and the bulk that must never be fetched.
        "SNGS-001/img1/000001.jpg": os.urandom(400_000),
        "SNGS-002/Labels-GameState.json": b'{"info":{"name":"SNGS-002"}}' * 50,
        "SNGS-002/img1/000001.jpg": os.urandom(400_000),
    }
    return _archive(members), members


def test_the_index_alone_lists_every_member(sample) -> None:
    blob, members = sample
    fetcher = SlicingFetcher(blob)
    remote = RemoteZip("memory://a.zip", cache_key="rz-list", fetcher=fetcher)
    assert remote.namelist() == sorted(members)
    # Reading the index must not have pulled the payloads.
    assert sum(len(blob[s : len(blob) if e is None else e + 1]) for s, e in fetcher.requests) < len(
        blob
    )


def test_members_come_back_byte_identical(sample) -> None:
    blob, members = sample
    remote = RemoteZip("memory://b.zip", cache_key="rz-read", fetcher=SlicingFetcher(blob))
    for name, payload in members.items():
        assert remote.read(name) == payload
    # ...and agree with the stdlib's own reader, not merely with themselves.
    with zipfile.ZipFile(io.BytesIO(blob)) as reference:
        for name in members:
            assert remote.read(name) == reference.read(name)


def test_reading_one_member_does_not_fetch_the_others(sample) -> None:
    blob, _ = sample
    fetcher = SlicingFetcher(blob)
    remote = RemoteZip("memory://c.zip", cache_key="rz-cost", fetcher=fetcher)

    target = "SNGS-002/Labels-GameState.json"
    remote.read(target)
    served = sum(
        len(blob[s : len(blob) if e is None else e + 1]) for s, e in fetcher.requests
    )
    # The index plus one small member, against an archive dominated by two 400 KB images.
    assert served < len(blob) / 2


def test_stored_members_are_handled_too() -> None:
    blob = _archive({"plain.txt": b"no compression here"}, compression=zipfile.ZIP_STORED)
    remote = RemoteZip("memory://d.zip", cache_key="rz-stored", fetcher=SlicingFetcher(blob))
    assert remote.read("plain.txt") == b"no compression here"


def test_a_missing_member_says_so(sample) -> None:
    blob, _ = sample
    remote = RemoteZip("memory://e.zip", cache_key="rz-missing", fetcher=SlicingFetcher(blob))
    with pytest.raises(KeyError, match="is not in"):
        remote.read("SNGS-999/Labels-GameState.json")


def test_the_index_is_cached_so_a_second_read_costs_nothing_extra(sample) -> None:
    blob, _ = sample
    fetcher = SlicingFetcher(blob)
    RemoteZip("memory://f.zip", cache_key="rz-cache", fetcher=fetcher).namelist()
    first = len(fetcher.requests)

    again = SlicingFetcher(blob)
    RemoteZip("memory://f.zip", cache_key="rz-cache", fetcher=again).namelist()
    assert first > 0
    assert again.requests == []


def test_a_truncated_archive_is_rejected_rather_than_misread() -> None:
    remote = RemoteZip(
        "memory://g.zip", cache_key="rz-broken", fetcher=SlicingFetcher(b"not a zip at all")
    )
    with pytest.raises(ValueError, match="end-of-central-directory"):
        remote.namelist()


def test_a_member_that_decompresses_to_the_wrong_size_is_rejected(sample) -> None:
    # The directory says how big a member should be. If the two disagree the slice boundaries
    # were wrong, and returning the bytes anyway hands the caller a silently truncated file.
    blob, _ = sample
    remote = RemoteZip("memory://h.zip", cache_key="rz-size", fetcher=SlicingFetcher(blob))
    name = "SNGS-002/Labels-GameState.json"
    original = remote.entries[name]
    remote.entries[name] = replace(original, uncompressed_size=original.uncompressed_size + 1)

    with pytest.raises(ValueError, match="directory said"):
        remote.read(name)


def test_a_server_that_ignores_the_range_header_is_refused() -> None:
    """The guard that stops an accidental full download.

    Ask for 64 KB of an 11.2 GB archive, get a 200 back, and treating it as a slice means
    streaming the whole thing into memory. A 206 is the only acceptable answer.
    """

    class _Response:
        status_code = 200
        content = b"the entire archive"

        def __init__(self) -> None:
            self.headers: dict[str, str] = {}

        def raise_for_status(self) -> None:
            return None

    class _Session:
        def __init__(self) -> None:
            self.headers: dict[str, str] = {}

        def get(self, url, **kwargs):
            return _Response()

    monkey = os.environ.pop("SPORTIO_OFFLINE", None)
    try:
        fetcher = Fetcher(session=_Session())
        with pytest.raises(ValueError, match="ignored Range"):
            fetcher.byte_range("http://example.invalid/big.zip", 0, 65535)
    finally:
        if monkey is not None:
            os.environ["SPORTIO_OFFLINE"] = monkey


# --------------------------------------------------------------------------------------
# ZIP64: the part a small local archive cannot exercise
# --------------------------------------------------------------------------------------

SENTINEL = 0xFFFFFFFF


def _zip64_extra(*values: int) -> bytes:
    body = b"".join(struct.pack("<Q", v) for v in values)
    return struct.pack("<HH", 0x0001, len(body)) + body


def test_zip64_fields_are_consumed_in_order_and_only_when_they_overflowed() -> None:
    """The extra field holds *only* the fields that overflowed, in a fixed order.

    Reading them positionally instead of in order is the classic bug: a member past 4 GB then
    gets its offset read as a size, and the range request goes to the wrong place.
    """
    # Only the offset overflowed: the single value in the extra field is the offset.
    assert _apply_zip64(_zip64_extra(9_689_796_299), 100, 40, SENTINEL) == (
        100,
        40,
        9_689_796_299,
    )
    # Only the uncompressed size overflowed.
    assert _apply_zip64(_zip64_extra(5_000_000_000), SENTINEL, 40, 7) == (5_000_000_000, 40, 7)
    # Sizes overflowed but the offset did not: two values, offset untouched.
    assert _apply_zip64(_zip64_extra(6_000_000_000, 5_000_000_000), SENTINEL, SENTINEL, 7) == (
        6_000_000_000,
        5_000_000_000,
        7,
    )
    # All three.
    assert _apply_zip64(
        _zip64_extra(6_000_000_000, 5_000_000_000, 9_000_000_000), SENTINEL, SENTINEL, SENTINEL
    ) == (6_000_000_000, 5_000_000_000, 9_000_000_000)


def test_nothing_is_touched_when_no_field_overflowed() -> None:
    assert _apply_zip64(_zip64_extra(1, 2, 3), 10, 20, 30) == (10, 20, 30)
    assert _apply_zip64(b"", 10, 20, 30) == (10, 20, 30)


def test_other_extra_fields_are_skipped_to_reach_the_zip64_one() -> None:
    # Extra fields are a tag-length-value chain; an unrelated tag must not be misread as ZIP64.
    unrelated = struct.pack("<HH", 0x5455, 5) + b"\x03\x00\x00\x00\x00"
    extra = unrelated + _zip64_extra(9_000_000_000)
    assert _apply_zip64(extra, 100, 40, SENTINEL) == (100, 40, 9_000_000_000)


def test_the_zip64_directory_record_wins_over_the_legacy_one() -> None:
    # A ZIP64 archive keeps a legacy record with sentinel values for old readers; taking those
    # at face value points the reader at offset 4294967295.
    eocd64 = b"PK\x06\x06" + struct.pack("<Q", 44) + b"\x00" * 28
    eocd64 += struct.pack("<QQ", 4096, 8_000_000_000)
    locator = b"PK\x06\x07" + struct.pack("<I", 0) + struct.pack("<Q", 0) + struct.pack("<I", 1)
    legacy = b"PK\x05\x06" + b"\x00" * 8 + struct.pack("<II", SENTINEL, SENTINEL) + b"\x00\x00"

    tail = eocd64 + locator + legacy
    offset, size = _locate_central_directory(tail, len(tail))
    assert (offset, size) == (8_000_000_000, 4096)

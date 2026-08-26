"""Round-trip acceptance tests for the StatsBomb and SkillCorner writers.

Every test here is the same shape as ``test_metrica.py``: load a committed fixture into the
canonical schema, write it back out in the vendor's own format, load *that* with the vendor's
own loader, and demand the two frames agree column by column. Anything a writer cannot carry
across is asserted explicitly, so the lossy set is documented executably rather than in prose.
"""

from __future__ import annotations

import collections
import json
import math
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
import pytest

from sportio.loaders import skillcorner, statsbomb
from sportio.writers.skillcorner import skillcorner_paths, to_skillcorner
from sportio.writers.statsbomb import to_statsbomb

from .conftest import fixture_path

SB_MATCH = 3943043
SC_MATCH = 1886347

#: The two ``extra`` keys StatsBomb keeps in a *separate* file (``three-sixty/{match}.json``).
#: They survive only when :func:`to_statsbomb` is given somewhere to put that file.
SB_THREE_SIXTY_KEYS = {"freeze_frame", "visible_area"}


# --------------------------------------------------------------------------------------
# fixtures
# --------------------------------------------------------------------------------------


def _load_statsbomb(events_file: str | Path, three_sixty_file: str | Path | None) -> pd.DataFrame:
    return statsbomb.load_events(
        match=SB_MATCH,
        competition="UEFA Euro",
        season="2024",
        events_file=events_file,
        three_sixty_file=three_sixty_file,
    )


@pytest.fixture(scope="module")
def events() -> pd.DataFrame:
    return _load_statsbomb(
        fixture_path("statsbomb", "events_3943043_slice.json"),
        fixture_path("statsbomb", "three-sixty_3943043_slice.json"),
    )


@pytest.fixture(scope="module")
def tracking(tmp_path_factory: pytest.TempPathFactory) -> pd.DataFrame:
    # The two tracking slices are consecutive JSONL from the same match, so concatenating
    # them gives a frame with both periods -- which is what makes the writer prove it can
    # rebuild per-period start_frames and the +45:00 second-half match clock.
    joined = tmp_path_factory.mktemp("skillcorner") / "both.jsonl"
    joined.write_bytes(
        fixture_path("skillcorner", "1886347_tracking_head.jsonl").read_bytes()
        + fixture_path("skillcorner", "1886347_tracking_period2.jsonl").read_bytes()
    )
    return skillcorner.load_tracking(
        SC_MATCH,
        match_file=fixture_path("skillcorner", "1886347_match.json"),
        tracking_file=joined,
    )


# --------------------------------------------------------------------------------------
# comparison helpers
# --------------------------------------------------------------------------------------


def assert_frames_round_tripped(
    original: pd.DataFrame, reloaded: pd.DataFrame, *, drop_extra: set[str] = frozenset()
) -> None:
    """Every column identical, floats to 1e-6, ``extra`` compared as parsed JSON."""
    assert list(reloaded.columns) == list(original.columns)
    assert reloaded.shape == original.shape
    for column in original.columns:
        if column == "extra":
            continue
        if str(original[column].dtype) == "Float64":
            before = original[column].astype("float64").to_numpy()
            after = reloaded[column].astype("float64").to_numpy()
            assert np.array_equal(np.isnan(before), np.isnan(after)), column
            assert after == pytest.approx(before, abs=1e-6, nan_ok=True), column
        else:
            pd.testing.assert_series_equal(
                reloaded[column].reset_index(drop=True),
                original[column].reset_index(drop=True),
                check_names=False,
            )
    if "extra" not in original.columns:
        return
    for row, (before_raw, after_raw) in enumerate(
        zip(original["extra"], reloaded["extra"], strict=True)
    ):
        before = {k: v for k, v in json.loads(before_raw).items() if k not in drop_extra}
        assert_json_close(before, json.loads(after_raw), f"row {row} extra")


def assert_json_close(before: Any, after: Any, where: str) -> None:
    """Structural equality with a float tolerance, so coordinate noise is not a failure."""
    if isinstance(before, dict):
        assert isinstance(after, dict), where
        assert sorted(before) == sorted(after), where
        for key in before:
            assert_json_close(before[key], after[key], f"{where}.{key}")
    elif isinstance(before, list):
        assert isinstance(after, list), where
        assert len(before) == len(after), where
        for i, (b, a) in enumerate(zip(before, after, strict=True)):
            assert_json_close(b, a, f"{where}[{i}]")
    elif isinstance(before, float) and not isinstance(before, bool):
        assert math.isclose(before, float(after), abs_tol=1e-6), f"{where}: {before} != {after}"
    else:
        assert before == after, f"{where}: {before!r} != {after!r}"


def extra_keys(frame: pd.DataFrame) -> set[str]:
    keys: set[str] = set()
    for raw in frame["extra"]:
        keys |= set(json.loads(raw))
    return keys


# --------------------------------------------------------------------------------------
# acceptance: StatsBomb round trip
# --------------------------------------------------------------------------------------


def test_round_trip_through_to_statsbomb_is_frame_identical(
    events: pd.DataFrame, tmp_path: Path
) -> None:
    written = to_statsbomb(events, tmp_path / "events.json", three_sixty_path=tmp_path / "360.json")
    assert written.exists()
    assert (tmp_path / "360.json").exists()

    back = _load_statsbomb(written, tmp_path / "360.json")
    assert_frames_round_tripped(events, back)


def test_statsbomb_360_is_the_only_thing_lost_without_its_own_file(
    events: pd.DataFrame, tmp_path: Path
) -> None:
    # The events JSON has nowhere to put a 360 frame: upstream keeps them in a sibling file.
    # Written alone it is still a complete events feed, and this is exactly what it costs.
    written = to_statsbomb(events, tmp_path / "events.json")
    assert not (tmp_path / "three-sixty.json").exists()

    back = _load_statsbomb(written, None)
    assert extra_keys(events) & SB_THREE_SIXTY_KEYS == SB_THREE_SIXTY_KEYS
    assert extra_keys(back) & SB_THREE_SIXTY_KEYS == set()
    assert extra_keys(events) - extra_keys(back) == SB_THREE_SIXTY_KEYS
    assert_frames_round_tripped(events, back, drop_extra=SB_THREE_SIXTY_KEYS)


def test_statsbomb_round_trip_honours_the_landmark_pitch_map(tmp_path: Path) -> None:
    # The loader offers a landmark rescale that pins the box and goal to their real sizes
    # instead of shrinking them 5-7%. It is not invertible with the linear map, so a writer
    # that assumed "linear" would put every shot back several yards from where it was taken.
    source = fixture_path("statsbomb", "events_3943043_slice.json")
    landmark = statsbomb.load_events(
        match=SB_MATCH, events_file=source, three_sixty=False, pitch="landmark"
    )
    linear = statsbomb.load_events(match=SB_MATCH, events_file=source, three_sixty=False)
    # The two maps agree only on the landmarks themselves (goal line, halfway), so their
    # x columns must not be interchangeable.
    assert not np.allclose(
        landmark["x"].astype("float64"), linear["x"].astype("float64"), atol=1e-3, equal_nan=True
    )

    written = to_statsbomb(landmark, tmp_path / "events.json", pitch="landmark")
    back = statsbomb.load_events(
        match=SB_MATCH, events_file=written, three_sixty=False, pitch="landmark"
    )
    assert_frames_round_tripped(landmark, back)


def test_statsbomb_writer_rejects_an_unknown_pitch(events: pd.DataFrame, tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="unknown pitch"):
        to_statsbomb(events, tmp_path / "events.json", pitch="sideways")


def test_written_statsbomb_events_are_back_in_the_acting_team_frame(
    events: pd.DataFrame, tmp_path: Path
) -> None:
    # The canonical frame rotated the defending team's events so the team in possession
    # attacks +x. StatsBomb's own file does not: a keeper defending his goal sits near x = 0.
    written = to_statsbomb(events, tmp_path / "events.json")
    raw = json.loads(written.read_text())
    keepers = [e for e in raw if e["type"]["name"] == "Goal Keeper"]
    assert len(keepers) == 6
    assert all(e["location"][0] < 15.0 for e in keepers), [e["location"] for e in keepers]

    # ...and the rotation is carried by the two ids alone, because that comparison is the
    # only thing the loader looks at. A possession_team *name* would not bring it back.
    mirrored = {e["id"] for e in raw if e["team"]["id"] != e["possession_team"]["id"]}
    expected = {
        json.loads(row)["id"]
        for row in events["extra"]
        if json.loads(row).get("mirrored")
    }
    assert len(expected) == 40
    assert mirrored == expected
    assert {e["id"] for e in keepers} <= mirrored


def test_written_statsbomb_coordinates_match_the_original_bytes(
    events: pd.DataFrame, tmp_path: Path
) -> None:
    # Nothing about the two rescales (120x80 <-> 105x68, and the 180-degree mirror) may leak
    # into the numbers: every location must come back as the yard value StatsBomb published,
    # including the third component of a shot that left the ground.
    raw = json.loads(fixture_path("statsbomb", "events_3943043_slice.json").read_text())
    source = {e["id"]: e for e in raw}
    written = json.loads(to_statsbomb(events, tmp_path / "events.json").read_text())

    starts = ends = 0
    for event in written:
        original = source[event["id"]]
        if "location" in original:
            assert event["location"] == pytest.approx(original["location"], abs=1e-6), event["id"]
            starts += 1
        for key in ("pass", "carry", "shot", "goalkeeper"):
            if key in original and "end_location" in original[key]:
                assert event[key]["end_location"] == pytest.approx(
                    original[key]["end_location"], abs=1e-6
                ), event["id"]
                ends += 1
    assert (starts, ends) == (138, 64)


def test_statsbomb_pass_length_and_angle_are_written_in_120x80_units(
    events: pd.DataFrame, tmp_path: Path
) -> None:
    # extra["length"]/["angle"] are canonical metres on a y-up pitch. Copying them into a
    # StatsBomb file would label a metre value as yards and flip the sign of every angle.
    written = json.loads(to_statsbomb(events, tmp_path / "events.json").read_text())
    passes = [e for e in written if "pass" in e and "end_location" in e["pass"]]
    assert len(passes) > 0
    for event in passes:
        (x, y), (ex, ey) = event["location"], event["pass"]["end_location"][:2]
        assert event["pass"]["length"] == pytest.approx(math.hypot(ex - x, ey - y), abs=1e-6)
        assert event["pass"]["angle"] == pytest.approx(math.atan2(ey - y, ex - x), abs=1e-6)

    canonical = events.loc[events["type"] == "pass"].iloc[0]
    metres = json.loads(canonical["extra"])["length"]
    yards = next(e for e in passes if e["id"] == json.loads(canonical["extra"])["id"])["pass"][
        "length"
    ]
    assert yards == pytest.approx(metres / 0.875, rel=0.05)
    assert yards != pytest.approx(metres, abs=1e-3)


def test_a_completed_pass_is_written_with_no_pass_outcome(
    events: pd.DataFrame, tmp_path: Path
) -> None:
    # "Complete" is not a StatsBomb outcome; a completed pass is one with no pass.outcome
    # at all, and that absence is the loader's only way to tell it from an unknown one.
    written = json.loads(to_statsbomb(events, tmp_path / "events.json").read_text())
    complete = {
        json.loads(row["extra"])["id"]
        for _, row in events.loc[
            (events["type"] == "pass") & (events["outcome"] == "complete")
        ].iterrows()
    }
    assert len(complete) > 0
    for event in written:
        if event["id"] in complete:
            assert "outcome" not in event["pass"]
    # The 11 passes that did carry an outcome keep StatsBomb's own spelling of it.
    outcomes = collections.Counter(
        e["pass"]["outcome"]["name"] for e in written if "pass" in e and "outcome" in e["pass"]
    )
    assert outcomes == collections.Counter({"Incomplete": 9, "Out": 2})


def test_an_acting_frame_round_trips_but_pays_for_it_in_possession_team_ids(
    tmp_path: Path,
) -> None:
    # frame="acting" keeps StatsBomb's own geometry and so carries no extra["mirrored"].
    # The writer has no way to tell "this row was never rotated" from "this row belongs to
    # the other team", and the loader only ever reads the ids -- so it writes them equal.
    # The frame survives intact; the possession team's *id* is what is paid for it.
    source = fixture_path("statsbomb", "events_3943043_slice.json")
    acting = statsbomb.load_events(
        match=SB_MATCH, events_file=source, three_sixty=False, frame="acting"
    )
    written = to_statsbomb(acting, tmp_path / "events.json")

    for reload_frame in ("acting", "possession"):
        back = statsbomb.load_events(
            match=SB_MATCH, events_file=written, three_sixty=False, frame=reload_frame
        )
        assert_frames_round_tripped(acting, back)

    raw = json.loads(written.read_text())
    off_possession = [e for e in raw if e["possession_team"]["name"] != e["team"]["name"]]
    assert len(off_possession) == 40
    assert all(e["possession_team"]["id"] == e["team"]["id"] for e in off_possession)


def test_statsbomb_writer_refuses_an_empty_frame(tmp_path: Path) -> None:
    from sportio.schema import empty_events

    with pytest.raises(ValueError, match="empty events frame"):
        to_statsbomb(empty_events(), tmp_path / "events.json")


# --------------------------------------------------------------------------------------
# acceptance: SkillCorner round trip
# --------------------------------------------------------------------------------------


def test_round_trip_through_to_skillcorner_is_frame_identical(
    tracking: pd.DataFrame, tmp_path: Path
) -> None:
    written = to_skillcorner(tracking, tmp_path / "out.jsonl")
    assert set(written) == {"tracking", "match"}
    assert all(path.exists() for path in written.values())
    assert written["match"].name == f"{SC_MATCH}_match.json"

    # Loaded from the written pair alone -- no fixture metadata in sight.
    back = skillcorner.load_tracking(
        SC_MATCH, match_file=written["match"], tracking_file=written["tracking"]
    )
    assert_frames_round_tripped(tracking, back)
    assert set(back["period"]) == {1, 2}


def test_skillcorner_metadata_rebuilds_the_period_clock(
    tracking: pd.DataFrame, tmp_path: Path
) -> None:
    written = to_skillcorner(tracking, tmp_path / "out.jsonl")
    meta = json.loads(written["match"].read_text())

    # start_frame is recovered from t, not assumed: this slice begins at frame 31783 in a
    # period whose real kickoff was frame 27800, and getting that wrong shifts t by 398 s.
    starts = {p["period"]: p["start_frame"] for p in meta["match_periods"]}
    assert starts == {1: 10, 2: 27800}
    assert meta["id"] == SC_MATCH
    assert meta["pitch_length"] == 105.0 and meta["pitch_width"] == 68.0
    assert len(meta["players"]) == 22
    assert {p["team_id"] for p in meta["players"]} == {
        meta["home_team"]["id"],
        meta["away_team"]["id"],
    }

    # The canonical frame already has home attacking +x in every period, so any other value
    # would ask the loader to rotate data that is already the right way round.
    assert meta["home_team_side"] == ["left_to_right", "left_to_right"]


def test_skillcorner_timestamp_keeps_the_plus_45_minute_match_clock(
    tracking: pd.DataFrame, tmp_path: Path
) -> None:
    written = to_skillcorner(tracking, tmp_path / "out.jsonl")
    lines = [json.loads(line) for line in written["tracking"].read_text().splitlines()]
    source = {
        frame["frame"]: frame["timestamp"]
        for name in ("1886347_tracking_head.jsonl", "1886347_tracking_period2.jsonl")
        for frame in map(json.loads, fixture_path("skillcorner", name).read_text().splitlines())
        if frame["period"] is not None
    }
    # SkillCorner's timestamp is a match clock with a flat +45:00 in the second half, while
    # the canonical t restarts at 0 each period. Rebuilt from t alone, every line must land
    # back on the string the published file carries -- including 00:51:38.30 at frame 31783,
    # which is 398.3 s into a half that the clock insists began at 45:00.
    assert lines[0]["frame"] == 10 and lines[0]["period"] == 1
    assert [f["timestamp"] for f in lines] == [source[f["frame"]] for f in lines]
    assert source[31783] == "00:51:38.30"


def test_skillcorner_confidence_becomes_the_is_detected_flag(
    tracking: pd.DataFrame, tmp_path: Path
) -> None:
    written = to_skillcorner(tracking, tmp_path / "out.jsonl")
    lines = [json.loads(line) for line in written["tracking"].read_text().splitlines()]
    detected = sum(p["is_detected"] for f in lines for p in f["player_data"])
    total = sum(len(f["player_data"]) for f in lines)
    players = tracking.loc[tracking["team"] != "ball"]
    assert detected == int((players["confidence"].astype("float64") == 1.0).sum())
    assert total - detected == int((players["confidence"].astype("float64") == 0.5).sum())
    # And those counts are the published file's own: this feed is extrapolated, so 22 rows a
    # frame but only 999 of the 2178 positions in these two slices were seen by a camera.
    assert (detected, total) == (999, 2178)


def test_skillcorner_writer_cannot_carry_ball_height_or_possession(
    tracking: pd.DataFrame, tmp_path: Path
) -> None:
    # Neither has a canonical column, so there is nothing to write back. Emitting a plausible
    # 0.0 for z would read as "ball on the deck" in every frame, which is worse than null.
    written = to_skillcorner(tracking, tmp_path / "out.jsonl")
    lines = [json.loads(line) for line in written["tracking"].read_text().splitlines()]
    balls = [f["ball_data"] for f in lines if f["ball_data"]["x"] is not None]
    assert len(balls) > 0
    assert all(b["z"] is None for b in balls)
    assert all(f["possession"] == {"player_id": None, "group": None} for f in lines)


def test_skillcorner_writer_rejects_a_named_player_id(tracking: pd.DataFrame, tmp_path: Path) -> None:
    # SkillCorner's own loader does int(player["id"]); a Metrica-style "Player11" would blow
    # up on the way back in, so the writer has to refuse it on the way out.
    renamed = tracking.copy()
    renamed.loc[renamed["team"] == "home", "player_id"] = "Player11"
    with pytest.raises(ValueError, match="integer id"):
        to_skillcorner(renamed, tmp_path / "out.jsonl")
    # ...and it refuses before writing, rather than leaving half a tracking file behind.
    assert list(tmp_path.iterdir()) == []


def test_skillcorner_writer_refuses_an_empty_frame(tmp_path: Path) -> None:
    from sportio.schema import empty_tracking

    with pytest.raises(ValueError, match="empty tracking frame"):
        to_skillcorner(empty_tracking(), tmp_path / "out.jsonl")


def test_skillcorner_paths_derive_the_metadata_companion(tmp_path: Path) -> None:
    paths = skillcorner_paths(tmp_path / "game", "1886347")
    assert paths["tracking"].name == "game.jsonl"
    assert paths["match"].name == "1886347_match.json"
    assert paths["match"].parent == paths["tracking"].parent

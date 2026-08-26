"""The ``sportio`` command line."""

from __future__ import annotations

import json

import pytest

import sportio
from sportio.cli import main
from sportio.loaders import metrica

from .conftest import fixture_path


def run(*argv: str) -> int:
    return main(list(argv))


def test_info_lists_every_source(capsys: pytest.CaptureFixture[str]) -> None:
    assert run("info") == 0
    out = capsys.readouterr().out
    for source in sportio.sources():
        assert source in out
    assert "canonical events columns" in out
    assert "match_id" in out


def test_info_json_is_machine_readable(capsys: pytest.CaptureFixture[str]) -> None:
    assert run("info", "--json") == 0
    payload = json.loads(capsys.readouterr().out)
    assert {row["source"] for row in payload} == set(sportio.sources())


def test_info_for_one_source(capsys: pytest.CaptureFixture[str]) -> None:
    assert run("info", "statsbomb", "--json") == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["source"] == "statsbomb"
    assert payload["events"] is True
    assert payload["tracking"] is False


def test_info_rejects_an_unknown_source(capsys: pytest.CaptureFixture[str]) -> None:
    assert run("info", "opta") == 1
    assert "unknown source" in capsys.readouterr().err


@pytest.mark.parametrize(
    ("parts", "expected"),
    [
        (("statsbomb", "events_3943043_slice.json"), "statsbomb events loader"),
        (("metrica", "Sample_Game_1_RawEventsData.trunc.csv"), "metrica events loader"),
        (
            ("metrica", "Sample_Game_1_RawTrackingData_Home_Team.trunc.csv"),
            "metrica tracking loader",
        ),
        (("skillcorner", "1886347_tracking_head.jsonl"), "skillcorner tracking loader"),
        (("rugby", "espn_summary_180659_600252.json"), "rugby events loader"),
        (("soccernet", "gsr", "SNGS-056"), "soccernet tracking loader"),
        (("metrica", "game3", "Sample_Game_3_events.slice.json"), "metrica events loader"),
        (("metrica", "game3", "Sample_Game_3_tracking.slice.txt"), "metrica tracking loader"),
    ],
)
def test_validate_detects_the_source_from_the_path(
    parts: tuple[str, ...], expected: str, capsys: pytest.CaptureFixture[str]
) -> None:
    assert run("validate", str(fixture_path(*parts))) == 0
    out = capsys.readouterr().out
    assert out.startswith("ok:")
    assert expected in out


def test_info_reports_which_sources_publish_squads(capsys: pytest.CaptureFixture[str]) -> None:
    assert run("info") == 0
    out = capsys.readouterr().out
    assert "lineups" in out


def test_validate_tells_you_when_game_three_is_missing_its_metadata(
    tmp_path, capsys: pytest.CaptureFixture[str]
) -> None:
    # EPTS tracking is undecodable without the XML: the column layout is defined there, and
    # it changes at every substitution.
    orphan = tmp_path / "Sample_Game_3_tracking.slice.txt"
    orphan.write_text(
        fixture_path("metrica", "game3", "Sample_Game_3_tracking.slice.txt").read_text()
    )
    assert run("validate", str(orphan), "--source", "metrica") == 1
    assert "metadata XML" in capsys.readouterr().err


def test_validate_round_trips_a_frame_sportio_wrote(
    tmp_path, capsys: pytest.CaptureFixture[str]
) -> None:
    events = metrica.load_events(
        1, events_file=fixture_path("metrica", "Sample_Game_1_RawEventsData.trunc.csv")
    )
    path = tmp_path / "events.csv"
    sportio.to_csv(events, path)
    assert run("validate", str(path)) == 0
    out = capsys.readouterr().out
    assert "canonical CSV" in out
    assert f"{len(events):,} rows" in out


def test_validate_reports_a_missing_file(capsys: pytest.CaptureFixture[str]) -> None:
    assert run("validate", "no/such/file.csv") == 1
    assert "error:" in capsys.readouterr().err


def test_validate_asks_for_help_when_the_source_is_unguessable(
    tmp_path, capsys: pytest.CaptureFixture[str]
) -> None:
    orphan = tmp_path / "mystery.json"
    orphan.write_text("[]")
    assert run("validate", str(orphan)) == 1
    assert "pass --source" in capsys.readouterr().err


def test_validate_refuses_a_skillcorner_file_without_its_metadata(
    tmp_path, capsys: pytest.CaptureFixture[str]
) -> None:
    # Without the _match.json sibling the loader would fall back to its default match id and
    # cheerfully report "ok" for a file measured against a different match's roster and pitch.
    orphan = tmp_path / "1899585_tracking_head.jsonl"
    orphan.write_text(fixture_path("skillcorner", "1886347_tracking_head.jsonl").read_text())
    assert run("validate", str(orphan), "--source", "skillcorner") == 1
    assert "needs its metadata sibling" in capsys.readouterr().err


def test_info_does_not_create_a_cache_directory(tmp_path, monkeypatch) -> None:
    # Reporting where the cache lives must not be what brings it into existence.
    monkeypatch.setenv("SPORTIO_DATA_DIR", str(tmp_path / "nowhere"))
    assert run("info") == 0
    assert not (tmp_path / "nowhere").exists()


def test_fetch_needs_to_know_what_to_fetch(capsys: pytest.CaptureFixture[str]) -> None:
    assert run("fetch", "statsbomb") == 1
    assert "--competition" in capsys.readouterr().err


def test_fetch_soccernet_is_a_real_download_now(capsys: pytest.CaptureFixture[str]) -> None:
    # It used to refuse outright on the grounds that a split is 11.2 GB. It is not a full
    # download any more -- only the label members are fetched -- so the only thing that should
    # stop it here is the suite's offline lock.
    with pytest.raises(Exception, match=r"OFFLINE|not cached|offline"):
        main(["fetch", "soccernet", "--split", "valid", "--match", "SNGS-021"])


def test_fetch_soccernet_rejects_a_bad_split(capsys: pytest.CaptureFixture[str]) -> None:
    assert run("fetch", "soccernet", "--split", "preseason") == 1
    assert "unknown split" in capsys.readouterr().err


def test_fetch_is_blocked_offline(capsys: pytest.CaptureFixture[str]) -> None:
    # conftest forces SPORTIO_OFFLINE, so a fetch that is not cached must fail loudly
    # rather than quietly reaching the network during the test run.
    with pytest.raises(Exception, match=r"OFFLINE|not cached|offline"):
        main(["fetch", "rugby", "--match", "600252"])

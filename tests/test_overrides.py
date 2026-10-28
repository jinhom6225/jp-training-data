"""東京 予告 overrides (research §3.1, plan Phase 1)."""

from __future__ import annotations

import copy
import json
from datetime import date
from pathlib import Path

import pytest

from scraper import overrides
from tests.conftest import load_rule_cases

BASES = load_rule_cases()["bases"]
TODAY = date(2026, 11, 10)


def entry(**changes) -> dict:
    item = copy.deepcopy(BASES["override"])
    item.update(changes)
    return item


def hwis(**changes) -> dict:
    item = copy.deepcopy(BASES["hwis"])
    item.update(changes)
    return item


def write(tmp_path: Path, data) -> Path:
    path = tmp_path / "overrides.json"
    path.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
    return path


def test_valid_file_loads(tmp_path: Path) -> None:
    loaded = overrides.load(write(tmp_path, {"entries": [entry()]}))
    assert loaded.problems == []
    assert [e["id"] for e in loaded.entries] == ["tokyo-toritsu-johoku-202704"]


@pytest.mark.parametrize(
    "bad",
    [
        {"entries": [entry(id="01-08-13-0001")]},
        {"entries": [entry(origin="hwis")]},
        {"entries": [entry(sourceUrl="https://example.com/")]},
        {"entries": [entry(entryMonth=None)]},
        {"entries": [entry(), entry()]},
        {"entries": "x"},
        [],
    ],
)
def test_bad_entries_are_rejected(tmp_path: Path, bad) -> None:
    loaded = overrides.load(write(tmp_path, bad))
    assert loaded.problems != []


def test_broken_json_is_a_problem(tmp_path: Path) -> None:
    path = tmp_path / "overrides.json"
    path.write_text("{", encoding="utf-8")
    assert overrides.load(path).problems != []


def test_missing_file_is_empty(tmp_path: Path) -> None:
    loaded = overrides.load(tmp_path / "none.json")
    assert (loaded.entries, loaded.problems) == ([], [])


def test_hwis_course_of_same_school_and_month_hides_the_notice() -> None:
    course = hwis(provider="城北職業能力開発センター", trainingStart="2027-04-08", trainingEnd="2027-09-30")
    result = overrides.merge([course], [entry()], today=TODAY)
    assert result.added == []
    assert result.hidden == ["tokyo-toritsu-johoku-202704"]


def test_other_month_or_school_keeps_the_notice() -> None:
    other_month = hwis(provider="城北職業能力開発センター", trainingStart="2027-01-08", trainingEnd="2027-03-30")
    other_school = hwis(provider="城東職業能力開発センター", trainingStart="2027-04-08", trainingEnd="2027-09-30")
    result = overrides.merge([other_month, other_school], [entry()], today=TODAY)
    assert [e["id"] for e in result.added] == ["tokyo-toritsu-johoku-202704"]


def test_past_rounds_are_dropped_and_ended_notices_skipped() -> None:
    two_rounds = entry(rounds=[
        {"no": 1, "start": "2026-10-01", "end": "2026-10-20"},
        {"no": 2, "start": "2027-01-07", "end": "2027-01-29"},
    ])
    result = overrides.merge([], [two_rounds], today=TODAY)
    assert result.added[0]["rounds"] == [{"no": 2, "start": "2027-01-07", "end": "2027-01-29"}]
    ended = entry(rounds=[{"no": 1, "start": "2026-10-01", "end": "2026-11-09"}])
    result = overrides.merge([], [ended], today=TODAY)
    assert (result.added, result.expired) == ([], ["tokyo-toritsu-johoku-202704"])


def test_merge_does_not_mutate_input() -> None:
    item = entry(rounds=[
        {"no": 1, "start": "2026-10-01", "end": "2026-10-20"},
        {"no": 2, "start": "2027-01-07", "end": "2027-01-29"},
    ])
    before = copy.deepcopy(item)
    overrides.merge([], [item], today=TODAY)
    assert item == before


def test_check_cli(tmp_path: Path, capsys) -> None:
    assert overrides.main(["--check", str(write(tmp_path, {"entries": [entry()]}))]) == 0
    assert overrides.main(["--check", str(write(tmp_path, {"entries": [entry(phone="x")]}))]) == 1
    assert "phone" in capsys.readouterr().out


def test_repository_file_is_valid() -> None:
    loaded = overrides.load(overrides.DEFAULT_PATH)
    assert loaded.problems == []

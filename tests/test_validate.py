"""Validator behaviour beyond the shared cases: JSON shape (the Dart
parser's type rules), file-level rules, meta.json and per-course drops."""

from __future__ import annotations

import copy
import json
from datetime import datetime, timedelta, timezone
from typing import Any

import pytest

from scraper import validate
from tests.conftest import load_rule_cases

NOW = datetime(2026, 11, 10, tzinfo=timezone.utc)
BASES = load_rule_cases()["bases"]


def hwis(**changes: Any) -> dict[str, Any]:
    course = copy.deepcopy(BASES["hwis"])
    course.update(changes)
    return course


def pref_file(courses: list[dict[str, Any]], pref: str = "13", **top: Any) -> dict[str, Any]:
    data: dict[str, Any] = {
        "schemaVersion": 1,
        "pref": pref,
        "generatedAt": "2026-11-10T06:41:00+09:00",
        "courses": courses,
    }
    data.update(top)
    return data


def errors(data: Any, pref: str = "13") -> list[str]:
    return validate.validate_pref_text(json.dumps(data, ensure_ascii=False), expected_pref=pref, now=NOW)


def test_base_file_is_clean() -> None:
    assert errors(pref_file([hwis()])) == []


@pytest.mark.parametrize(
    ("key", "value"),
    [
        ("capacity", True),
        ("capacity", 20.0),
        ("capacity", "20"),
        ("childcare", 1),
        ("childcare", None),
        ("name", 5),
        ("fields", "office"),
        ("fields", ["office", 1]),
        ("fields", ["cooking"]),
        ("kind", "other"),
        ("origin", "manual"),
        ("rounds", {"no": 1}),
        ("trainingStart", "2027/01/08"),
        ("checkedAt", "2026-11-10T06:35:00"),
        ("targetCourses", "x"),
        ("entryMonth", "2027-4"),
    ],
)
def test_shape_errors(key: str, value: Any) -> None:
    assert errors(pref_file([hwis(**{key: value})])) != []


def test_round_shape_errors() -> None:
    bad_rounds: list[Any] = [
        [{"no": True, "start": "2026-11-05", "end": "2026-11-26"}],
        [{"no": 1, "start": "2026-11-05"}],
        [{"no": 1.0, "start": "2026-11-05", "end": "2026-11-26"}],
        ["x"],
    ]
    for rounds in bad_rounds:
        assert errors(pref_file([hwis(rounds=rounds)])) != [], rounds


@pytest.mark.parametrize(
    ("change", "message"),
    [
        ({"capacity": 0}, "capacity"),
        ({"capacity": 1000}, "capacity"),
        ({"fields": []}, "fields"),
        ({"fields": ["it"] * 9}, "fields"),
        ({"fields": ["it", "it"]}, "fields"),
        ({"trainingStart": "2027-05-01"}, "trainingEnd"),
        ({"sourceUrl": "http://www.hellowork.mhlw.go.jp/"}, "sourceUrl"),
        ({"sourceUrl": "https://example.com/"}, "sourceUrl"),
        ({"phone": "0612345678"}, "phone"),
        ({"name": "  "}, "name"),
        ({"name": "第２期"}, "name"),
        ({"hours": "9:30\t15:40"}, "hours"),
        ({"id": "01-08-27-0001"}, "id"),
        ({"targetCourses": ["x"] * 21}, "targetCourses"),
    ],
)
def test_rule_errors(change: dict[str, Any], message: str) -> None:
    found = errors(pref_file([hwis(**change)]))
    assert any(message in e for e in found), found


def test_duplicate_ids_reject() -> None:
    assert any("repeated" in e for e in errors(pref_file([hwis(), hwis()])))


def test_unknown_keys_are_not_errors() -> None:
    assert errors(pref_file([hwis(extra="x")], extra=1)) == []


def test_file_level_rules() -> None:
    assert errors(pref_file([hwis()]), pref="27") != []
    assert errors(pref_file([hwis()], schemaVersion=2)) != []
    assert errors(pref_file([hwis()], schemaVersion=0)) != []
    assert errors(pref_file([hwis()], generatedAt="2030-01-01T00:00:00+09:00")) != []
    no_courses = pref_file([hwis()])
    no_courses["courses"] = None
    assert errors(no_courses) != []
    assert errors([1, 2]) != []


def test_file_too_large_or_bad_json() -> None:
    assert validate.validate_pref_text("{", expected_pref="13", now=NOW) != []
    big = "x" * (validate.MAX_PREF_BYTES + 1)
    assert validate.validate_pref_text(big, expected_pref="13", now=NOW) != []


def test_too_many_courses(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(validate, "MAX_PREF_BYTES", 10 * 1024 * 1024)
    courses = [hwis(id=f"01-08-13-{i:04d}") for i in range(validate.MAX_COURSES_PER_FILE + 1)]
    assert any("over" in e for e in errors(pref_file(courses)))


def test_utf16_length_counts_surrogates() -> None:
    assert validate.utf16_len("𠮷") == 2
    name = "𠮷" * 50
    assert errors(pref_file([hwis(name=name)])) == []
    assert errors(pref_file([hwis(name=name + "a")])) != []


def test_course_problems_reports_one_course() -> None:
    assert validate.course_problems(hwis(), "13") == []
    assert validate.course_problems(hwis(phone="+81"), "13") != []
    assert validate.course_problems("x", "13") != []  # type: ignore[arg-type]


def meta(**changes: Any) -> dict[str, Any]:
    data: dict[str, Any] = {
        "schemaVersion": 1,
        "generatedAt": "2026-11-10T06:41:00+09:00",
        "prefs": {"13": {"count": 2, "generatedAt": "2026-11-10T06:41:00+09:00"}},
    }
    data.update(changes)
    return data


def meta_errors(data: Any) -> list[str]:
    return validate.validate_meta_text(json.dumps(data), now=NOW)


def test_meta_rules() -> None:
    assert meta_errors(meta()) == []
    assert meta_errors(meta(prefs={"48": {"count": 1, "generatedAt": "2026-11-10T06:41:00+09:00"}})) != []
    assert meta_errors(meta(prefs={"13": {"count": 2001, "generatedAt": "2026-11-10T06:41:00+09:00"}})) != []
    assert meta_errors(meta(prefs={"13": {"count": -1, "generatedAt": "2026-11-10T06:41:00+09:00"}})) != []
    assert meta_errors(meta(prefs={"13": {"count": 1}})) != []
    assert meta_errors(meta(prefs={"13": {"count": 1, "generatedAt": "2030-01-01T00:00:00Z"}})) != []
    assert meta_errors(meta(schemaVersion=2)) != []
    assert meta_errors(meta(prefs=[])) != []
    assert meta_errors(meta(extra=1)) == []
    assert validate.validate_meta_text("[]", now=NOW) != []
    assert validate.validate_meta_text("x" * (validate.MAX_META_BYTES + 1), now=NOW) != []


def test_is_too_far_ahead_boundary() -> None:
    assert not validate.is_too_far_ahead(NOW + timedelta(days=7), NOW)
    assert validate.is_too_far_ahead(NOW + timedelta(days=7, seconds=1), NOW)


def test_hidden_and_digit_listing() -> None:
    assert validate.text_ok("a\nb")
    assert not validate.text_ok("a b")
    assert not validate.text_ok("﻿a")
    assert not validate.text_ok("a b")

"""Every case of the shared rule file (plan D8), the same cases the app's
Dart tests assert (test/data/rule_cases_test.dart, url_rules_test.dart).
If one fails, the pipeline and the app disagree and the app would reject a
whole pref file."""

from __future__ import annotations

import copy
import json
from datetime import datetime, timezone
from typing import Any

import pytest

from scraper import validate
from tests.conftest import load_rule_cases

CASES = load_rule_cases()
NOW = datetime(2026, 11, 10, tzinfo=timezone.utc)


def _ids(items: list[dict[str, Any]], key: str = "value") -> list[str]:
    return [f"{i}:{json.dumps(item.get(key, item.get('note')), ensure_ascii=False)[:40]}" for i, item in enumerate(items)]


def test_every_section_is_present() -> None:
    for name in [
        "hosts", "phones", "dates", "dateTimes", "entryMonths", "courseIds",
        "fieldIds", "texts", "rounds", "bases", "originFields", "lengths",
        "instantsAhead",
    ]:
        assert CASES.get(name), name


@pytest.mark.parametrize("item", CASES["hosts"]["cases"], ids=_ids(CASES["hosts"]["cases"], "url"))
def test_hosts(item: dict[str, Any]) -> None:
    assert validate.host_allowed(item["url"], CASES["hosts"]["domains"]) is item["allowed"]


@pytest.mark.parametrize("item", CASES["phones"], ids=_ids(CASES["phones"]))
def test_phones(item: dict[str, Any]) -> None:
    assert validate.phone_ok(item["value"]) is item["ok"]


@pytest.mark.parametrize("item", CASES["dates"], ids=_ids(CASES["dates"]))
def test_dates(item: dict[str, Any]) -> None:
    assert (validate.parse_iso_date(item["value"]) is not None) is item["ok"]


@pytest.mark.parametrize("item", CASES["dateTimes"], ids=_ids(CASES["dateTimes"]))
def test_date_times(item: dict[str, Any]) -> None:
    parsed = validate.parse_iso_instant(item["value"])
    assert (parsed is not None) is item["ok"]
    if parsed is not None:
        expected = datetime.fromisoformat(item["utc"].replace("Z", "+00:00"))
        assert parsed == expected
        assert parsed.tzinfo == timezone.utc


@pytest.mark.parametrize("item", CASES["entryMonths"], ids=_ids(CASES["entryMonths"]))
def test_entry_months(item: dict[str, Any]) -> None:
    assert validate.is_year_month(item["value"]) is item["ok"]


@pytest.mark.parametrize("item", CASES["courseIds"], ids=_ids(CASES["courseIds"]))
def test_course_ids(item: dict[str, Any]) -> None:
    assert validate.course_id_ok(item["value"], item["pref"], item["origin"]) is item["ok"]


@pytest.mark.parametrize("item", CASES["fieldIds"], ids=_ids(CASES["fieldIds"]))
def test_field_ids(item: dict[str, Any]) -> None:
    assert (item["value"] in validate.FIELD_IDS) is item["ok"]


@pytest.mark.parametrize("item", CASES["texts"], ids=_ids(CASES["texts"]))
def test_texts(item: dict[str, Any]) -> None:
    assert validate.text_ok(item["value"]) is item["ok"], item["note"]


@pytest.mark.parametrize("item", CASES["rounds"], ids=_ids(CASES["rounds"], "note"))
def test_rounds(item: dict[str, Any]) -> None:
    rounds = [
        validate.Round(no=r[0], start=validate.parse_iso_date(r[1]), end=validate.parse_iso_date(r[2]))
        for r in item["rounds"]
    ]
    assert (validate.round_problems(rounds) == []) is item["ok"]


def _course_file(item: dict[str, Any]) -> dict[str, Any]:
    course = copy.deepcopy(CASES["bases"][item["base"]])
    for key in item.get("unset") or []:
        course.pop(key, None)
    for key, value in (item.get("set") or {}).items():
        course[key] = value
    return {
        "schemaVersion": 1,
        "pref": "13",
        "generatedAt": "2026-11-10T06:41:00+09:00",
        "courses": [course],
    }


def _decodes_clean(data: dict[str, Any]) -> bool:
    text = json.dumps(data, ensure_ascii=False)
    return validate.validate_pref_text(text, expected_pref="13", now=NOW) == []


@pytest.mark.parametrize("item", CASES["originFields"], ids=_ids(CASES["originFields"], "note"))
def test_origin_fields(item: dict[str, Any]) -> None:
    assert _decodes_clean(_course_file(item)) is item["ok"]


def test_length_limits_match() -> None:
    assert CASES["lengthLimits"] == validate.TEXT_LIMITS


@pytest.mark.parametrize("item", CASES["lengths"], ids=[f"{c['key']}x{c['length']}" for c in CASES["lengths"]])
def test_lengths(item: dict[str, Any]) -> None:
    text = "あ" * item["length"]
    value: Any = [text] if item["key"] == "targetCourses" else text
    data = _course_file({"base": item["base"], "set": {item["key"]: value}})
    assert _decodes_clean(data) is item["ok"]


def test_future_limit_matches() -> None:
    assert CASES["futureLimitDays"] == validate.MAX_FUTURE_SKEW.days


@pytest.mark.parametrize("item", CASES["instantsAhead"], ids=_ids(CASES["instantsAhead"], "note"))
def test_instants_ahead(item: dict[str, Any]) -> None:
    value = validate.parse_iso_instant(item["value"])
    now = validate.parse_iso_instant(item["now"])
    assert value is not None and now is not None
    assert (not validate.is_too_far_ahead(value, now)) is item["ok"]

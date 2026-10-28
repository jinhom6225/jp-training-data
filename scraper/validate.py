"""Validator for pref/NN.json and meta.json (data_schema.md, plan D8).

A port of the app's ``pref_data_parser.dart`` (shape: types, required keys,
closed sets, formats) and ``pref_data_validator.dart`` / ``course_rules.dart``
(rules between values). The app rejects a whole file on any error, so the
pipeline drops a failing course before publishing (``course_problems``) and
checks every finished file again (``validate_pref_text``).

Python's ``bool`` is an ``int`` and JSON ``20.0`` is a ``float``; Dart's
``value is int`` rejects both, so ``_is_int`` does too.
"""

from __future__ import annotations

import json
from datetime import datetime
from typing import Any

from scraper.rules import (  # noqa: F401  (re-exported for callers and tests)
    ALLOWED_DOMAINS,
    FIELD_IDS,
    KINDS,
    MAX_CAPACITY,
    MAX_COURSES_PER_FILE,
    MAX_FIELDS_PER_COURSE,
    MAX_FUTURE_SKEW,
    MAX_META_BYTES,
    MAX_PREF_BYTES,
    MAX_TARGET_COURSES,
    ORIGINS,
    PREF_CODES,
    SUPPORTED_SCHEMA_VERSION,
    TEXT_LIMITS,
    Round,
    course_id_ok,
    hidden_characters,
    host_allowed,
    is_too_far_ahead,
    is_year_month,
    non_ascii_digits,
    parse_iso_date,
    parse_iso_instant,
    phone_ok,
    round_problems,
    text_ok,
    url_scheme,
    utf16_len,
)

_OPTIONAL_TEXTS = ("city", "address", "hours", "selfCost", "conditions", "provider", "phone", "sourceName")
_OPTIONAL_DATES = ("trainingStart", "trainingEnd", "selectionDate", "resultDate")
_TEXT_KEYS = ("name", "city", "address", "hours", "selfCost", "conditions", "provider", "sourceName", "sourceUrl")


class _Shape(Exception):
    """The JSON does not have the shape the app's models need."""


def _is_int(value: object) -> bool:
    return isinstance(value, int) and not isinstance(value, bool)


def _required(obj: dict[str, Any], key: str) -> Any:
    if key not in obj:
        raise _Shape(f"{key}: required field missing")
    return obj[key]


def _string(obj: dict[str, Any], key: str) -> str:
    value = _required(obj, key)
    if not isinstance(value, str):
        raise _Shape(f"{key}: expected string")
    return value


def _optional_string(obj: dict[str, Any], key: str) -> str | None:
    value = obj.get(key)
    if value is not None and not isinstance(value, str):
        raise _Shape(f"{key}: expected string or null")
    return value


def _date(obj: dict[str, Any], key: str) -> Any:
    value = parse_iso_date(_required(obj, key))
    if value is None:
        raise _Shape(f"{key}: expected YYYY-MM-DD")
    return value


def _optional_date(obj: dict[str, Any], key: str) -> Any:
    return None if obj.get(key) is None else _date(obj, key)


def _instant(obj: dict[str, Any], key: str) -> datetime:
    value = parse_iso_instant(_required(obj, key))
    if value is None:
        raise _Shape(f"{key}: expected an ISO 8601 instant with offset")
    return value


def _int(obj: dict[str, Any], key: str) -> int:
    value = _required(obj, key)
    if not _is_int(value):
        raise _Shape(f"{key}: expected int")
    return value


def _list(obj: dict[str, Any], key: str) -> list[Any]:
    value = _required(obj, key)
    if not isinstance(value, list):
        raise _Shape(f"{key}: expected list")
    return value


def _enum(obj: dict[str, Any], key: str, allowed: tuple[str, ...]) -> str:
    value = _string(obj, key)
    if value not in allowed:
        raise _Shape(f"{key}: {value!r} not in {list(allowed)}")
    return value


def _read_rounds(course: dict[str, Any]) -> list[Round]:
    rounds = []
    for i, item in enumerate(_list(course, "rounds")):
        if not isinstance(item, dict):
            raise _Shape(f"rounds[{i}]: expected object")
        rounds.append(Round(no=_int(item, "no"), start=_date(item, "start"), end=_date(item, "end")))
    return rounds


def _read_fields(course: dict[str, Any]) -> list[str]:
    fields = _list(course, "fields")
    for item in fields:
        if not isinstance(item, str) or item not in FIELD_IDS:
            raise _Shape(f"fields: {item!r} not a field id")
    return fields


def _read_targets(course: dict[str, Any]) -> list[str]:
    if course.get("targetCourses") is None:
        return []
    targets = _list(course, "targetCourses")
    if not all(isinstance(t, str) for t in targets):
        raise _Shape("targetCourses: expected strings")
    return targets


def _read_course(course: Any) -> dict[str, Any]:
    """Shape checks of one course (pref_data_parser.dart ``_course``);
    returns the typed values the rules need."""
    if not isinstance(course, dict):
        raise _Shape("course: expected object")
    values: dict[str, Any] = {
        "id": _string(course, "id"),
        "origin": _enum(course, "origin", ORIGINS),
        "kind": _enum(course, "kind", KINDS),
        "name": _string(course, "name"),
        "fields": _read_fields(course),
        "rounds": _read_rounds(course),
        "sourceUrl": _string(course, "sourceUrl"),
        "checkedAt": _instant(course, "checkedAt"),
        "targetCourses": _read_targets(course),
    }
    if not isinstance(_required(course, "childcare"), bool):
        raise _Shape("childcare: expected bool")
    for key in _OPTIONAL_TEXTS:
        values[key] = _optional_string(course, key)
    for key in _OPTIONAL_DATES:
        values[key] = _optional_date(course, key)
    capacity = course.get("capacity")
    if capacity is not None and not _is_int(capacity):
        raise _Shape("capacity: expected int or null")
    values["capacity"] = capacity
    month = course.get("entryMonth")
    if month is not None and not is_year_month(month):
        raise _Shape("entryMonth: expected YYYY-MM")
    values["entryMonth"] = month
    return values


def _origin_problems(c: dict[str, Any]) -> list[str]:
    problems = []
    if c["origin"] == "override":
        for key, present in (
            ("sourceName", c["sourceName"] is not None),
            ("entryMonth", c["entryMonth"] is not None),
            ("targetCourses", bool(c["targetCourses"])),
        ):
            if not present:
                problems.append(f"{key}: required")
    else:
        for key in ("provider", "trainingStart", "trainingEnd"):
            if c[key] is None:
                problems.append(f"{key}: required")
        for key, present in (
            ("sourceName", c["sourceName"] is not None),
            ("entryMonth", c["entryMonth"] is not None),
            ("targetCourses", bool(c["targetCourses"])),
        ):
            if present:
                problems.append(f"{key}: override-only field")
    if len(c["targetCourses"]) > MAX_TARGET_COURSES:
        problems.append(f"targetCourses: over {MAX_TARGET_COURSES}")
    return problems


def _text_problems(key: str, value: str | None, limit: int) -> list[str]:
    if value is None:
        return []
    if value.strip() == "":
        return [f"{key}: empty text"]
    problems = []
    if utf16_len(value) > limit:
        problems.append(f"{key}: {utf16_len(value)} > {limit}")
    if non_ascii_digits(value):
        problems.append(f"{key}: non-ASCII digits {non_ascii_digits(value)[:5]}")
    if hidden_characters(value):
        problems.append(f"{key}: hidden {hidden_characters(value)[:5]}")
    return problems


def _value_problems(c: dict[str, Any], pref: str) -> list[str]:
    """course_rules.dart ``CourseChecker.check``."""
    problems = []
    if not course_id_ok(c["id"], pref, c["origin"]):
        problems.append(f"id: {c['id']!r} is not a {c['origin']} id of {pref}")
    problems += _origin_problems(c)
    fields = c["fields"]
    if not 1 <= len(fields) <= MAX_FIELDS_PER_COURSE:
        problems.append(f"fields: 1 to {MAX_FIELDS_PER_COURSE}")
    if len(set(fields)) != len(fields):
        problems.append("fields: a field is repeated")
    problems += round_problems(c["rounds"])
    if c["trainingStart"] and c["trainingEnd"] and c["trainingStart"] > c["trainingEnd"]:
        problems.append("trainingEnd: before trainingStart")
    if c["capacity"] is not None and not 1 <= c["capacity"] <= MAX_CAPACITY:
        problems.append(f"capacity: 1 to {MAX_CAPACITY}")
    if url_scheme(c["sourceUrl"]) != "https":
        problems.append("sourceUrl: https only")
    elif not host_allowed(c["sourceUrl"], ALLOWED_DOMAINS):
        problems.append("sourceUrl: host not allowed")
    if c["phone"] is not None and not phone_ok(c["phone"]):
        problems.append(f"phone: {c['phone']!r}")
    for key in _TEXT_KEYS:
        problems += _text_problems(key, c[key], TEXT_LIMITS[key])
    for i, target in enumerate(c["targetCourses"]):
        problems += _text_problems(f"targetCourses[{i}]", target, TEXT_LIMITS["targetCourse"])
    return problems


def course_problems(course: dict[str, Any], pref: str) -> list[str]:
    """Every error of one course in ``pref/<pref>.json`` (empty = valid)."""
    try:
        values = _read_course(course)
    except _Shape as error:
        return [str(error)]
    return _value_problems(values, pref)


def _schema_problems(root: dict[str, Any], now: datetime) -> list[str]:
    problems = []
    version = _int(root, "schemaVersion")
    if version < 1:
        problems.append("schemaVersion: must be >= 1")
    if version > SUPPORTED_SCHEMA_VERSION:
        problems.append(f"schemaVersion: {version} > {SUPPORTED_SCHEMA_VERSION}")
    if is_too_far_ahead(_instant(root, "generatedAt"), now):
        problems.append("generatedAt: more than 7 days ahead of now")
    return problems


def _decode_object(text: str, limit: int) -> dict[str, Any]:
    size = len(text.encode("utf-8"))
    if size > limit:
        raise _Shape(f"$: {size} bytes > {limit}")
    try:
        root = json.loads(text)
    except ValueError as error:
        raise _Shape(f"$: JSON syntax: {error}") from error
    if not isinstance(root, dict):
        raise _Shape("$: expected object")
    return root


def validate_pref_text(text: str, *, expected_pref: str, now: datetime) -> list[str]:
    """Every error the app would report for ``pref/<expected_pref>.json``."""
    try:
        root = _decode_object(text, MAX_PREF_BYTES)
        problems = _schema_problems(root, now)
        pref = _string(root, "pref")
        courses = _list(root, "courses")
    except _Shape as error:
        return [str(error)]
    if pref != expected_pref:
        problems.append(f"pref: {pref!r} is not {expected_pref}")
    if len(courses) > MAX_COURSES_PER_FILE:
        problems.append(f"courses: over {MAX_COURSES_PER_FILE}")
    seen: set[str] = set()
    for i, course in enumerate(courses):
        course_id = course.get("id") if isinstance(course, dict) else None
        if isinstance(course_id, str):
            if course_id in seen:
                problems.append(f"courses[{i}].id: repeated {course_id}")
            seen.add(course_id)
        problems += [f"courses[{i}].{p}" for p in course_problems(course, expected_pref)]
    return problems


def validate_meta_text(text: str, *, now: datetime) -> list[str]:
    """Every error the app would report for ``meta.json``."""
    try:
        root = _decode_object(text, MAX_META_BYTES)
        problems = _schema_problems(root, now)
        prefs = _required(root, "prefs")
        if not isinstance(prefs, dict):
            raise _Shape("prefs: expected object")
        for key, value in prefs.items():
            if key not in PREF_CODES:
                raise _Shape(f"prefs: key {key!r} is not a prefecture code")
            if not isinstance(value, dict):
                raise _Shape(f"prefs.{key}: expected object")
            count = _int(value, "count")
            if is_too_far_ahead(_instant(value, "generatedAt"), now):
                problems.append(f"prefs.{key}.generatedAt: more than 7 days ahead of now")
            if not 0 <= count <= MAX_COURSES_PER_FILE:
                problems.append(f"prefs.{key}.count: 0 to {MAX_COURSES_PER_FILE}")
    except _Shape as error:
        return [str(error)]
    return problems

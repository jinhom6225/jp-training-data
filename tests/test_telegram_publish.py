"""Telegram notices (no-op without secrets) and the published files."""

from __future__ import annotations

import copy
import json
import logging
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from scraper import publish, telegram
from scraper.validate import validate_meta_text, validate_pref_text
from tests.conftest import load_rule_cases

JST = timezone(timedelta(hours=9))
NOW = datetime(2026, 10, 28, 6, 41, tzinfo=JST)
BASES = load_rule_cases()["bases"]


class FakeResponse:
    def __init__(self, status: int) -> None:
        self.status_code = status


def test_telegram_without_secrets_only_logs(caplog: pytest.LogCaptureFixture) -> None:
    caplog.set_level(logging.INFO)
    calls = []
    assert telegram.send("hello", env={}, post=lambda *a, **k: calls.append(a)) is False
    assert calls == []
    assert "hello" in caplog.text


def test_missing_secrets_warn_and_annotate_in_actions(caplog: pytest.LogCaptureFixture, capsys) -> None:
    assert telegram.send("hi", env={"GITHUB_ACTIONS": "true"}, post=lambda *a, **k: None) is False
    assert any(r.levelno == logging.WARNING and "secrets" in r.getMessage() for r in caplog.records)
    assert "::warning::" in capsys.readouterr().out
    telegram.send("hi", env={}, post=lambda *a, **k: None)
    assert "::warning::" not in capsys.readouterr().out


def test_telegram_sends_with_secrets() -> None:
    calls = []

    def post(url, **kwargs):
        calls.append((url, kwargs))
        return FakeResponse(200)

    env = {"TELEGRAM_BOT_TOKEN": "123:abc", "TELEGRAM_CHAT_ID": "42"}
    assert telegram.send("x" * 5000, env=env, post=post) is True
    url, kwargs = calls[0]
    assert url == "https://api.telegram.org/bot123:abc/sendMessage"
    assert kwargs["data"]["chat_id"] == "42"
    assert len(kwargs["data"]["text"]) <= telegram.MAX_LENGTH


def test_telegram_failure_never_raises(caplog: pytest.LogCaptureFixture) -> None:
    env = {"TELEGRAM_BOT_TOKEN": "123:secret", "TELEGRAM_CHAT_ID": "42"}

    def boom(url, **kwargs):
        raise OSError(f"cannot reach {url}")

    assert telegram.send("x", env=env, post=boom) is False
    assert telegram.send("x", env=env, post=lambda *a, **k: FakeResponse(500)) is False
    assert "secret" not in caplog.text


def hwis(course_id: str, fields=("office",)) -> dict:
    course = copy.deepcopy(BASES["hwis"])
    course["id"] = course_id
    course["fields"] = list(fields)
    return course


def site(tmp_path: Path) -> Path:
    courses = {
        "13": [hwis("01-08-13-0002"), hwis("01-08-13-0001", ("other",))],
        "27": [hwis("02-08-27-0001", ("it", "design"))],
    }
    publish.write_site(tmp_path, courses, generated_at=NOW, report={"detailFailures": 0})
    return tmp_path


def test_write_site_files_pass_the_app_rules(tmp_path: Path) -> None:
    out = site(tmp_path)
    check_now = NOW.astimezone(timezone.utc)
    for code in [f"{i:02d}" for i in range(1, 48)]:
        text = (out / "pref" / f"{code}.json").read_text(encoding="utf-8")
        assert validate_pref_text(text, expected_pref=code, now=check_now) == []
    meta_text = (out / "meta.json").read_text(encoding="utf-8")
    assert validate_meta_text(meta_text, now=check_now) == []
    meta = json.loads(meta_text)
    assert set(meta) == {"schemaVersion", "generatedAt", "prefs"}
    assert meta["prefs"]["13"] == {"count": 2, "generatedAt": "2026-10-28T06:41:00+09:00"}
    assert meta["prefs"]["01"]["count"] == 0
    data = json.loads((out / "pref" / "13.json").read_text(encoding="utf-8"))
    assert [c["id"] for c in data["courses"]] == ["01-08-13-0001", "01-08-13-0002"]


def test_stats(tmp_path: Path) -> None:
    stats = json.loads((site(tmp_path) / "stats.json").read_text(encoding="utf-8"))
    assert stats["total"] == 3
    assert stats["byPref"]["13"] == 2
    assert stats["byField"] == {"it": 1, "office": 1, "medical": 0, "care": 0, "design": 1, "building": 0, "manufacturing": 0, "other": 1}
    assert stats["otherRatio"] == pytest.approx(1 / 3, abs=1e-4)
    assert stats["detailFailures"] == 0


def test_write_site_refuses_an_invalid_file(tmp_path: Path) -> None:
    bad = hwis("01-08-13-0001")
    bad["phone"] = "+81"
    with pytest.raises(publish.PublishError):
        publish.write_site(tmp_path, {"13": [bad]}, generated_at=NOW, report={})
    assert not (tmp_path / "meta.json").exists()


def test_load_previous_reads_meta_and_valid_files(tmp_path: Path) -> None:
    out = site(tmp_path)

    def fetch(url: str) -> bytes | None:
        path = out / url.removeprefix("https://example.github.io/data/")
        return path.read_bytes() if path.exists() else None

    previous = publish.load_previous("https://example.github.io/data/", fetch, now=NOW)
    assert previous is not None
    assert previous.counts["13"] == 2
    assert [c["id"] for c in previous.courses["27"]] == ["02-08-27-0001"]
    assert previous.missing == []


def test_load_previous_first_run_and_bad_files(tmp_path: Path) -> None:
    assert publish.load_previous("https://x/", lambda url: None, now=NOW) is None
    assert publish.load_previous("", lambda url: b"{}", now=NOW) is None
    out = site(tmp_path)
    (out / "pref" / "27.json").write_text("{", encoding="utf-8")

    def fetch(url: str) -> bytes | None:
        path = out / url.removeprefix("https://x/")
        return path.read_bytes() if path.exists() else None

    previous = publish.load_previous("https://x/", fetch, now=NOW)
    assert previous is not None
    assert previous.missing == ["27"]
    assert "27" not in previous.courses
    assert previous.counts["27"] == 1


def test_load_previous_with_broken_meta() -> None:
    with pytest.raises(publish.PreviousUnreadable):
        publish.load_previous("https://x/", lambda url: b"[]", now=NOW)
    with pytest.raises(publish.PreviousUnreadable):
        publish.load_previous("https://x/", lambda url: b"\xff{", now=NOW)

"""Shared pytest helpers: fixture paths and the shared rule case file."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

ROOT = Path(__file__).resolve().parent.parent
FIXTURES = Path(__file__).resolve().parent / "fixtures"
RULE_CASES_PATH = ROOT / "scraper" / "rule_cases.json"


def fixture_bytes(name: str) -> bytes:
    """Raw bytes of a saved HWIS page in tests/fixtures."""
    return (FIXTURES / name).read_bytes()


def load_rule_cases() -> dict[str, Any]:
    """The pipeline's copy of the app's tools/rule_cases.json."""
    return json.loads(RULE_CASES_PATH.read_text(encoding="utf-8"))


@pytest.fixture(scope="session")
def rule_cases() -> dict[str, Any]:
    return load_rule_cases()


def five_round_detail() -> bytes:
    """detail_02-09-14-0013.html (3 rounds) with a 4th and 5th round added,
    as HWIS shows for some FY2027 April-intake courses."""
    html = fixture_bytes("detail_02-09-14-0013.html").decode("utf-8")
    extra = "".join(
        f'<table class="normal mb1"><tr><th scope="row">募集期間（{zen}回目）</th><td><div class="input_lable any">'
        f"<span>{start}</span> 〜 <span>{end}</span></div></td></tr>"
        f'<tr><th scope="row">選考日（{zen}回目）</th><td><div class="input_lable any"><div>{sel}</div></div></td></tr></table>'
        for zen, start, end, sel in (
            ("４", "2027年2月23日", "2027年3月10日", "2027年3月15日"),
            ("５", "2027年3月11日", "2027年3月24日", "2027年3月27日"),
        )
    )
    marker = "<th scope=\"row\">訓練対象者の条件</th>"
    head, tail = html.split(marker, 1)
    cut = head.rfind("<table")
    return (head[:cut] + extra + head[cut:] + marker + tail).encode("utf-8")

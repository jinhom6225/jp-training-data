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

"""The pipeline's scraper/rule_cases.json must be a byte-identical copy of
the app's tools/rule_cases.json (plan D8). The app repo path comes from
APP_REPO (default: jp_job_training_alert next to this repo or one level
up). Skipped when the app repo is not on this machine (for example in
Actions)."""

from __future__ import annotations

import os
from pathlib import Path

import pytest

from tests.conftest import ROOT, RULE_CASES_PATH


def _app_rule_cases() -> Path:
    if "APP_REPO" in os.environ:
        return Path(os.environ["APP_REPO"]) / "tools" / "rule_cases.json"
    candidates = [base / "jp_job_training_alert" / "tools" / "rule_cases.json" for base in (ROOT.parent, ROOT.parent.parent)]
    return next((c for c in candidates if c.exists()), candidates[0])


def test_rule_cases_copy_matches_app_repo() -> None:
    app_file = _app_rule_cases()
    if not app_file.exists():
        pytest.skip(f"app repo file not found: {app_file} (set APP_REPO)")
    assert RULE_CASES_PATH.read_bytes() == app_file.read_bytes(), (
        f"{RULE_CASES_PATH} differs from {app_file}; copy the app's file again"
    )

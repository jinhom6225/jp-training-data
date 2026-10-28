"""The pipeline's scraper/rule_cases.json must be a byte-identical copy of
the app's tools/rule_cases.json (plan D8). The app repo path comes from
APP_REPO (default: ../jp_job_training_alert next to this repo). Skipped
when the app repo is not on this machine (for example in Actions)."""

from __future__ import annotations

import os
from pathlib import Path

import pytest

from tests.conftest import ROOT, RULE_CASES_PATH


def _app_rule_cases() -> Path:
    app_repo = Path(os.environ.get("APP_REPO", ROOT.parent / "jp_job_training_alert"))
    return app_repo / "tools" / "rule_cases.json"


def test_rule_cases_copy_matches_app_repo() -> None:
    app_file = _app_rule_cases()
    if not app_file.exists():
        pytest.skip(f"app repo file not found: {app_file} (set APP_REPO)")
    assert RULE_CASES_PATH.read_bytes() == app_file.read_bytes(), (
        f"{RULE_CASES_PATH} differs from {app_file}; copy the app's file again"
    )

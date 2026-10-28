"""Workflow guard rails from the pre-push security review."""

from __future__ import annotations

import yaml

from tests.conftest import ROOT

COLLECT = yaml.safe_load((ROOT / ".github" / "workflows" / "collect.yml").read_text(encoding="utf-8"))


def test_collect_timeout_and_permissions() -> None:
    assert COLLECT["jobs"]["collect"]["timeout-minutes"] == 180
    assert COLLECT["permissions"] == {"contents": "read"}
    assert COLLECT["jobs"]["notify"]["permissions"] == {"contents": "read"}
    assert COLLECT["jobs"]["deploy"]["permissions"] == {"pages": "write", "id-token": "write"}


def test_only_the_bootstrap_input_passes_bootstrap() -> None:
    steps = {s.get("name"): s for s in COLLECT["jobs"]["collect"]["steps"]}
    resolve = steps["Resolve mode"]["run"]
    assert resolve.count("--bootstrap") == 1
    assert 'bootstrap) mode=full; extra="--bootstrap"' in resolve
    assert "--bootstrap" not in steps["Collect"]["run"]
    assert "bootstrap" in COLLECT[True]["workflow_dispatch"]["inputs"]["mode"]["options"]


def test_failures_and_cancellations_notify() -> None:
    steps = {s.get("name"): s for s in COLLECT["jobs"]["collect"]["steps"]}
    assert steps["Notify failure"]["if"].startswith("(failure() || cancelled())")
    notify = COLLECT["jobs"]["notify"]
    assert notify["needs"] == ["collect", "deploy"]
    for clause in ("needs.deploy.result == 'failure'", "needs.deploy.result == 'cancelled'", "needs.collect.result == 'cancelled'"):
        assert clause in notify["if"]
    assert "::warning::" in notify["steps"][0]["run"]


def test_every_action_is_pinned_to_a_commit() -> None:
    for name in ("collect.yml", "smoke.yml"):
        text = (ROOT / ".github" / "workflows" / name).read_text(encoding="utf-8")
        for line in text.splitlines():
            if "uses:" in line:
                ref = line.split("uses:")[1].split("#")[0].strip()
                assert len(ref.split("@")[1]) == 40, line


MORNING = "30 21 * * *"


def test_success_summary_wiring() -> None:
    assert MORNING in [c["cron"] for c in COLLECT[True]["schedule"]]
    steps = {s.get("name"): s for s in COLLECT["jobs"]["collect"]["steps"]}
    resolve = steps["Resolve mode"]
    # Morning vs evening comes from the cron string, not the clock.
    assert resolve["env"]["SCHEDULE"] == "${{ github.event.schedule }}"
    assert resolve["env"]["EVENT"] == "${{ github.event_name }}"
    assert f'"{MORNING}"' in resolve["run"]
    assert "workflow_dispatch" in resolve["run"]
    assert COLLECT["jobs"]["collect"]["outputs"]["summary"] == "${{ steps.summary.outputs.summary }}"
    assert COLLECT["jobs"]["collect"]["outputs"]["announce"] == "${{ steps.mode.outputs.announce }}"
    assert "out/summary.txt" in steps["Summary"]["run"]
    job = COLLECT["jobs"]["summary"]
    assert job["needs"] == ["collect", "deploy"]
    assert job["if"] == "needs.deploy.result == 'success' && needs.collect.outputs.announce == 'true'"
    assert job["permissions"] == {"contents": "read"}
    run = job["steps"][0]["run"]
    assert "::warning::" in run
    assert '--data-urlencode "text=$TEXT"' in run
    assert job["steps"][0]["env"]["SUMMARY"] == "${{ needs.collect.outputs.summary }}"
    assert job["steps"][0]["env"]["TRIGGER"] == "${{ needs.collect.outputs.trigger }}"

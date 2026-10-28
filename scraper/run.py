"""One collection run (plan Phase 1 run order).

    python -m scraper.run [--mode auto|normal|full] [--out out]
                          [--pages-url URL] [--cache DIR [--from-cache]]
                          [--prefs 13,27] [--force-anomaly]

1. Download the previous site from Pages (none → first run → full).
2. Search the list of every prefecture, then the 託児サービスあり list.
3. Fetch details: every course (full: first run, Wednesday JST mornings,
   or --mode full) or only new / changed / near-deadline ones (normal),
   plus the D7 recheck of open courses that left the list.
4. Build, classify and validate courses; merge the 東京 overrides.
5. Anomaly check (D7): on any reason, notify Telegram and publish nothing.
6. Write out/site/{meta.json, stats.json, pref/NN.json}; out/report.json
   is always written.

Exit codes: 0 published, 2 anomaly, 3 blocked by HWIS, 1 other error.
No push is sent (FCM dropped 2026-10-28).
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import sys
import time
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Callable

import requests

from scraper import overrides, telegram
from scraper.anomaly import RunFacts, detect
from scraper.assemble import assemble, detail_targets
from scraper.collect import Cache, collect_childcare, collect_lists, fetch_details
from scraper.errors import BlockedError
from scraper.hwis_client import HwisClient, RequestsTransport
from scraper.publish import Previous, load_previous, write_site
from scraper.rules import PREF_CODES

log = logging.getLogger("scraper.run")
JST = timezone(timedelta(hours=9))
DEFAULT_PAGES_URL = "https://jinhom6225.github.io/jp-training-data/"
EXIT_OK, EXIT_ERROR, EXIT_ANOMALY, EXIT_BLOCKED = 0, 1, 2, 3
WEDNESDAY = 2


@dataclass(frozen=True)
class Config:
    mode: str
    out: Path
    pages_url: str
    cache: Path | None
    from_cache: bool
    force_anomaly: bool
    prefs: tuple[str, ...] = PREF_CODES
    overrides_path: Path = overrides.DEFAULT_PATH


@dataclass(frozen=True)
class Deps:
    client: HwisClient | None
    fetch: Callable[[str], bytes | None]
    notify: Callable[[str], bool]
    now: Callable[[], datetime]


def resolve_mode(requested: str, previous: Previous | None, now: datetime) -> str:
    """full on a first run, on --mode full, and on Wednesday JST mornings
    (the weekly refresh that catches changes the list does not show)."""
    if previous is None or requested == "full":
        return "full"
    if requested == "auto" and now.weekday() == WEDNESDAY and now.hour < 12:
        return "full"
    return "normal"


def _previous_courses(previous: Previous | None) -> dict[str, dict]:
    if previous is None:
        return {}
    return {c["id"]: c for courses in previous.courses.values() for c in courses if c["origin"] == "hwis"}


def _lists_and_childcare(config: Config, deps: Deps, cache: Cache | None):
    if config.from_cache:
        if cache is None:
            raise ValueError("--from-cache needs --cache")
        return cache.load_lists(), cache.load_childcare()
    if deps.client is None:
        raise ValueError("no HWIS client")
    lists = collect_lists(deps.client, config.prefs)
    childcare = collect_childcare(deps.client)
    if cache is not None:
        cache.save_lists(lists)
        cache.save_childcare(childcare)
    return lists, childcare


def _merge_overrides(config: Config, deps: Deps, courses: dict[str, list[dict]], today) -> dict:
    loaded = overrides.load(config.overrides_path)
    if loaded.problems:
        deps.notify("jp-training-data: overrides.json has problems, none merged:\n" + "\n".join(loaded.problems[:10]))
    if "13" not in config.prefs:
        return {"problems": loaded.problems, "added": [], "hidden": [], "expired": []}
    tokyo = courses.get("13", [])
    merged = overrides.merge(tokyo, loaded.entries, today=today)
    courses["13"] = tokyo + merged.added
    return {
        "problems": loaded.problems,
        "added": [c["id"] for c in merged.added],
        "hidden": merged.hidden,
        "expired": merged.expired,
    }


def _write_report(out: Path, report: dict) -> None:
    out.mkdir(parents=True, exist_ok=True)
    (out / "report.json").write_text(json.dumps(report, ensure_ascii=False, indent=1), encoding="utf-8")


def _collect(config: Config, deps: Deps, started: datetime, report: dict) -> int:
    today = started.date()
    previous = load_previous(config.pages_url, deps.fetch, now=started)
    mode = resolve_mode(config.mode, previous, started)
    report["mode"] = mode
    log.info("mode %s (previous publish: %s)", mode, previous.generated_at if previous else "none")
    cache = Cache(config.cache) if config.cache else None
    lists, childcare = _lists_and_childcare(config, deps, cache)
    previous_courses = _previous_courses(previous)
    unknown = set(previous.missing) if previous else set()
    targets = detail_targets(lists.rows, previous_courses, unknown, today, full=mode == "full")
    log.info("details to fetch: %d (+%d recheck)", len(targets.fetch), len(targets.recheck))
    client = None if config.from_cache else deps.client
    fetched = fetch_details(client, targets.fetch + targets.recheck, now=lambda: datetime.now(JST), cache=cache)
    built = assemble(lists.rows, previous_courses, fetched, childcare=childcare, today=today, recheck=targets.recheck)
    courses = {code: list(items) for code, items in built.courses.items()}
    report.update(
        listed=len(lists.rows), announced=lists.announced, listErrors=lists.errors,
        childcareKnown=childcare is not None, detailAttempts=fetched.attempts,
        detailFailures=dict(sorted(fetched.failures.items())), recheck=len(targets.recheck),
        gone=built.gone, built=built.built, reused=built.reused, missingDetail=built.missing,
        ended=len(built.ended), invalid=built.invalid,
    )
    report["overrides"] = _merge_overrides(config, deps, courses, today)
    counts = {code: len(courses.get(code, [])) for code in config.prefs}
    previous_counts = {k: v for k, v in previous.counts.items() if k in config.prefs} if previous else None
    reasons = detect(
        RunFacts(previous_counts, counts, lists.errors, fetched.attempts, len(fetched.failures)),
        force=config.force_anomaly,
    )
    report["anomalies"] = reasons
    if reasons:
        deps.notify("jp-training-data anomaly, nothing published:\n- " + "\n- ".join(reasons))
        return EXIT_ANOMALY
    summary = {k: report[k] for k in ("mode", "built", "reused", "ended", "recheck")}
    summary["detailFailures"] = len(fetched.failures)
    summary["invalid"] = len(built.invalid)
    stats = write_site(config.out / "site", courses, generated_at=started, report=summary)
    report["total"] = stats["total"]
    report["otherRatio"] = stats["otherRatio"]
    log.info("published %d courses (other %.1f%%)", stats["total"], stats["otherRatio"] * 100)
    return EXIT_OK


def execute(config: Config, deps: Deps) -> int:
    started = deps.now().astimezone(JST)
    clock = time.monotonic()
    report: dict = {"startedAt": started.isoformat(timespec="seconds"), "anomalies": []}
    try:
        code = _collect(config, deps, started, report)
    except BlockedError as error:
        report["error"] = str(error)
        deps.notify(f"jp-training-data stopped: HWIS blocked the run ({error}). Nothing published.")
        code = EXIT_BLOCKED
    except Exception as error:  # noqa: BLE001  (report every failure, then exit non-zero)
        log.exception("run failed")
        report["error"] = f"{type(error).__name__}: {error}"
        deps.notify(f"jp-training-data failed: {type(error).__name__}: {error}")
        code = EXIT_ERROR
    if deps.client is not None:
        report["requests"] = deps.client.request_count
    report["durationSec"] = round(time.monotonic() - clock, 1)
    report["exitCode"] = code
    _write_report(config.out, report)
    return code


def _fetch_url(url: str) -> bytes | None:
    response = requests.get(url, timeout=20, allow_redirects=False)
    if response.status_code == 404:
        return None
    response.raise_for_status()
    return response.content


def real_deps(config: Config) -> Deps:  # pragma: no cover  (network)
    client = None if config.from_cache else HwisClient(RequestsTransport())
    return Deps(client=client, fetch=_fetch_url, notify=telegram.send, now=lambda: datetime.now(JST))


def _prefs(text: str) -> tuple[str, ...]:
    codes = tuple(f"{int(p):02d}" for p in text.split(",") if p.strip())
    if not codes or any(c not in PREF_CODES for c in codes):
        raise argparse.ArgumentTypeError(f"prefecture codes 01-47, got {text!r}")
    return codes


def parse_args(argv: list[str] | None) -> Config:
    parser = argparse.ArgumentParser(prog="python -m scraper.run", description=__doc__.split("\n\n")[0])
    parser.add_argument("--mode", choices=("auto", "normal", "full"), default="auto")
    parser.add_argument("--out", type=Path, default=Path("out"))
    parser.add_argument("--pages-url", default=os.environ.get("PAGES_BASE_URL", DEFAULT_PAGES_URL))
    parser.add_argument("--cache", type=Path, default=None)
    parser.add_argument("--from-cache", action="store_true")
    parser.add_argument("--force-anomaly", action="store_true")
    parser.add_argument("--prefs", type=_prefs, default=PREF_CODES)
    parser.add_argument("--overrides", type=Path, default=overrides.DEFAULT_PATH)
    args = parser.parse_args(argv)
    return Config(
        mode=args.mode, out=args.out, pages_url=args.pages_url, cache=args.cache,
        from_cache=args.from_cache, force_anomaly=args.force_anomaly, prefs=args.prefs,
        overrides_path=args.overrides,
    )


def main(argv: list[str] | None = None) -> int:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    config = parse_args(argv)
    return execute(config, real_deps(config))


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())

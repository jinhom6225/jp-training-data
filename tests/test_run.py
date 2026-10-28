"""End-to-end runs over the fake HWIS (no network, no sleeping)."""

from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from scraper import run
from scraper.hwis_client import HwisClient
from scraper.rules import PREF_CODES
from tests.fakes import FakeClock, FakeTransport
from tests.hwis_site import FakeHwis

JST = timezone(timedelta(hours=9))
TUESDAY = datetime(2026, 10, 27, 6, 40, tzinfo=JST)
WEDNESDAY = datetime(2026, 10, 28, 6, 40, tzinfo=JST)


class Harness:
    def __init__(self, tmp_path: Path, site: FakeHwis | None = None, now: datetime = TUESDAY) -> None:
        self.site = site or FakeHwis()
        self.clock = FakeClock()
        self.transport = FakeTransport(self.clock, self.site)
        self.client = HwisClient(self.transport, monotonic=self.clock.monotonic, sleep=self.clock.sleep)
        self.notices: list[str] = []
        self.published: dict[str, bytes] = {}
        self.now = now
        self.tmp = tmp_path

    def deps(self, client: HwisClient | None = "default") -> run.Deps:  # type: ignore[assignment]
        return run.Deps(
            client=self.client if client == "default" else client,
            fetch=lambda url: self.published.get(url),
            notify=lambda text: self.notices.append(text) or True,
            now=lambda: self.now,
        )

    def config(self, **changes) -> run.Config:
        values = dict(mode="auto", out=self.tmp / "out", pages_url="https://pages.test/data/",
                      cache=None, from_cache=False, force_anomaly=False, bootstrap=True, prefs=("13", "31"),
                      overrides_path=self.tmp / "none.json")
        values.update(changes)
        return run.Config(**values)

    def publish_out(self) -> None:
        """Pretend Pages now serves out/site."""
        site = self.tmp / "out" / "site"
        for path in site.rglob("*.json"):
            self.published["https://pages.test/data/" + path.relative_to(site).as_posix()] = path.read_bytes()

    def details_fetched(self) -> int:
        return sum(1 for c in self.transport.calls if (c.params or {}).get("action") == "dispDetailBtn")


def read(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def test_first_run_is_full_and_writes_the_site(tmp_path: Path) -> None:
    h = Harness(tmp_path)
    assert run.execute(h.config(), h.deps()) == 0
    site = tmp_path / "out" / "site"
    assert sorted(p.stem for p in (site / "pref").glob("*.json")) == list(PREF_CODES)
    meta = read(site / "meta.json")
    assert meta["prefs"]["13"]["count"] == 48
    report = read(tmp_path / "out" / "report.json")
    assert report["mode"] == "full" and report["detailAttempts"] == 48
    assert report["anomalies"] == []
    assert h.details_fetched() == 48
    assert h.notices == []


def test_normal_run_fetches_nothing_unchanged(tmp_path: Path) -> None:
    site = FakeHwis(pref_pages={"13": ["list_13_only_0515"]})
    h = Harness(tmp_path, site=site, now=TUESDAY)
    assert run.execute(h.config(), h.deps()) == 0
    h.publish_out()
    assert h.details_fetched() == 1
    assert run.execute(h.config(), h.deps()) == 0
    report = read(tmp_path / "out" / "report.json")
    assert report["mode"] == "normal"
    assert report["detailAttempts"] == 0 and h.details_fetched() == 1
    assert report["reused"] == 1
    # The deadline comes within 14 days → fetched again the next day.
    h.now = TUESDAY + timedelta(days=1)
    h.publish_out()
    assert run.execute(h.config(), h.deps()) == 0
    assert h.details_fetched() == 2


def test_wednesday_morning_is_full(tmp_path: Path) -> None:
    h = Harness(tmp_path, now=datetime(2026, 10, 21, 6, 40, tzinfo=JST))
    run.execute(h.config(), h.deps())
    h.publish_out()
    assert run.execute(h.config(), h.deps()) == 0
    assert read(tmp_path / "out" / "report.json")["mode"] == "full"


def test_vanished_course_is_rechecked_and_dropped_when_gone(tmp_path: Path) -> None:
    h = Harness(tmp_path, now=datetime(2026, 10, 20, 6, 40, tzinfo=JST))
    run.execute(h.config(), h.deps())
    h.publish_out()
    h.site.pref_pages["13"] = ["list_empty.html"]
    h.site.gone.add("02-08-13-0504")
    # 48 → 47 known gone: 13 drops to 47, still above the anomaly limits?
    # No: the list is empty, so 47 others are rechecked and kept (their
    # detail pages still show open rounds).
    assert run.execute(h.config(), h.deps()) == 0
    report = read(tmp_path / "out" / "report.json")
    assert report["recheck"] == 48
    assert report["gone"] == ["02-08-13-0504"]
    assert read(tmp_path / "out" / "site" / "meta.json")["prefs"]["13"]["count"] == 47


def test_big_drop_is_an_anomaly_and_publishes_nothing(tmp_path: Path) -> None:
    h = Harness(tmp_path, now=datetime(2026, 10, 20, 6, 40, tzinfo=JST))
    run.execute(h.config(), h.deps())
    h.publish_out()
    h.site.pref_pages["13"] = ["list_empty.html"]
    h.site.gone.update(f"{c}" for c in _ids(tmp_path))
    site = tmp_path / "out" / "site"
    before = (site / "meta.json").read_bytes()
    assert run.execute(h.config(), h.deps()) == run.EXIT_ANOMALY
    assert (site / "meta.json").read_bytes() == before or not site.exists()
    assert h.notices and "anomaly" in h.notices[-1]
    assert read(tmp_path / "out" / "report.json")["anomalies"]


def _ids(tmp_path: Path) -> list[str]:
    return [c["id"] for c in read(tmp_path / "out" / "site" / "pref" / "13.json")["courses"]]


def test_forced_anomaly(tmp_path: Path) -> None:
    h = Harness(tmp_path)
    assert run.execute(h.config(force_anomaly=True), h.deps()) == run.EXIT_ANOMALY
    assert not (tmp_path / "out" / "site" / "meta.json").exists()
    assert len(h.notices) == 1


def test_list_structure_error_is_an_anomaly(tmp_path: Path) -> None:
    h = Harness(tmp_path, site=FakeHwis(pref_pages={"13": ["system_error.html"]}))
    assert run.execute(h.config(), h.deps()) == run.EXIT_ANOMALY


def test_blocked_stops_and_notifies(tmp_path: Path) -> None:
    h = Harness(tmp_path, site=FakeHwis(status=403))
    assert run.execute(h.config(), h.deps()) == run.EXIT_BLOCKED
    assert "403" in h.notices[-1]


def test_cache_and_offline_rebuild(tmp_path: Path) -> None:
    h = Harness(tmp_path)
    cache = tmp_path / "cache"
    assert run.execute(h.config(cache=cache, mode="full"), h.deps()) == 0
    first = read(tmp_path / "out" / "site" / "pref" / "13.json")["courses"]
    calls = len(h.transport.calls)
    assert run.execute(h.config(cache=cache, from_cache=True, mode="full"), h.deps(client=None)) == 0
    assert len(h.transport.calls) == calls
    assert read(tmp_path / "out" / "site" / "pref" / "13.json")["courses"] == first


def test_overrides_are_merged_into_tokyo(tmp_path: Path) -> None:
    from tests.conftest import load_rule_cases

    notice = load_rule_cases()["bases"]["override"]
    path = tmp_path / "overrides.json"
    path.write_text(json.dumps({"entries": [notice]}, ensure_ascii=False), encoding="utf-8")
    h = Harness(tmp_path)
    assert run.execute(h.config(overrides_path=path), h.deps()) == 0
    ids = _ids(tmp_path)
    assert "tokyo-toritsu-johoku-202704" in ids
    assert read(tmp_path / "out" / "report.json")["overrides"]["added"] == ["tokyo-toritsu-johoku-202704"]


def test_bad_overrides_notify_but_do_not_block(tmp_path: Path) -> None:
    path = tmp_path / "overrides.json"
    path.write_text("{", encoding="utf-8")
    h = Harness(tmp_path)
    assert run.execute(h.config(overrides_path=path), h.deps()) == 0
    assert any("overrides" in n for n in h.notices)


def test_parse_args_and_main(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    config = run.parse_args(["--mode", "full", "--out", str(tmp_path / "o"), "--prefs", "13,27", "--pages-url", ""])
    assert config.mode == "full" and config.prefs == ("13", "27") and config.pages_url == ""
    with pytest.raises(SystemExit):
        run.parse_args(["--prefs", "48"])
    h = Harness(tmp_path)
    monkeypatch.setattr(run, "real_deps", lambda config: h.deps())
    assert run.main(["--out", str(tmp_path / "o"), "--prefs", "13", "--pages-url", ""]) == run.EXIT_ANOMALY
    assert run.main(["--out", str(tmp_path / "o"), "--prefs", "13", "--pages-url", "", "--bootstrap"]) == 0


def test_unexpected_error_notifies(tmp_path: Path) -> None:
    h = Harness(tmp_path)
    deps = h.deps()

    def broken(url: str) -> bytes | None:
        raise RuntimeError("boom")

    deps = run.Deps(client=deps.client, fetch=broken, notify=deps.notify, now=deps.now)
    assert run.execute(h.config(), deps) == run.EXIT_ERROR
    assert "boom" in h.notices[-1]


def test_no_previous_without_bootstrap_is_an_anomaly(tmp_path: Path) -> None:
    h = Harness(tmp_path)
    assert run.execute(h.config(bootstrap=False), h.deps()) == run.EXIT_ANOMALY
    assert "bootstrap" in h.notices[-1]
    assert not (tmp_path / "out" / "site" / "meta.json").exists()
    assert h.details_fetched() == 0


def test_unreadable_previous_meta_is_an_anomaly_unless_bootstrapping(tmp_path: Path) -> None:
    h = Harness(tmp_path)
    h.published["https://pages.test/data/meta.json"] = b"{not json"
    assert run.execute(h.config(bootstrap=False), h.deps()) == run.EXIT_ANOMALY
    assert "unreadable" in h.notices[-1]
    assert run.execute(h.config(bootstrap=True), h.deps()) == 0
    assert read(tmp_path / "out" / "report.json")["mode"] == "full"


def test_missing_previous_pref_file_is_an_anomaly(tmp_path: Path) -> None:
    h = Harness(tmp_path)
    assert run.execute(h.config(), h.deps()) == 0
    h.publish_out()
    del h.published["https://pages.test/data/pref/13.json"]
    assert run.execute(h.config(bootstrap=False), h.deps()) == run.EXIT_ANOMALY
    assert "13" in h.notices[-1]


def test_scheduled_style_run_with_previous_needs_no_bootstrap(tmp_path: Path) -> None:
    h = Harness(tmp_path)
    assert run.execute(h.config(), h.deps()) == 0
    h.publish_out()
    assert run.execute(h.config(bootstrap=False), h.deps()) == 0


class _PagesResponse:
    def __init__(self, status: int, body: bytes = b"") -> None:
        self.status_code = status
        self.content = body


@pytest.mark.parametrize(("status", "expected"), [(200, b"{}"), (404, None)])
def test_fetch_url_ok_and_not_found(monkeypatch: pytest.MonkeyPatch, status: int, expected) -> None:
    calls = {}

    def get(url, **kwargs):
        calls.update(kwargs)
        return _PagesResponse(status, b"{}")

    monkeypatch.setattr(run.requests, "get", get)
    assert run._fetch_url("https://x/meta.json") == expected
    assert calls["allow_redirects"] is False


@pytest.mark.parametrize("status", [301, 302, 304, 403, 500, 503])
def test_fetch_url_other_statuses_fail_the_run(monkeypatch: pytest.MonkeyPatch, status: int) -> None:
    monkeypatch.setattr(run.requests, "get", lambda url, **kwargs: _PagesResponse(status))
    with pytest.raises(run.PagesFetchError, match=str(status)):
        run._fetch_url("https://x/meta.json")


def test_parse_args_bootstrap() -> None:
    assert run.parse_args(["--bootstrap"]).bootstrap is True
    assert run.parse_args([]).bootstrap is False

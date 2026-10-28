"""A fake HWIS built from the saved pages, for collection and run tests."""

from __future__ import annotations

from dataclasses import dataclass, field

import lxml.html

from tests.conftest import fixture_bytes
from tests.fakes import Call

KNOWN_DETAILS = ("01-08-13-0515", "02-08-13-0504", "02-09-14-0013", "03-08-27-0234")


def detail_id(call: Call) -> str:
    p = call.params or {}
    return "-".join(p[k] for k in ("kRNShubetsu_Detail", "shinseiNendo_Detail", "tDFKNo_Detail", "kRNTsuban_Detail"))


def single_row_page(course_id: str) -> bytes:
    """list_13_p2.html cut down to the one row of ``course_id``."""
    html = fixture_bytes("list_13_p2.html").decode("utf-8")
    doc = lxml.html.fromstring(html)
    for table in doc.xpath("//table[contains(concat(' ',@class,' '),' kyujin ')][.//tr[contains(@class,'kyujin_head')]]"):
        if f"kRNTsuban_Detail={course_id[-4:]}" not in lxml.html.tostring(table, encoding="unicode") or course_id[:2] != "01":
            table.getparent().remove(table)
    out = lxml.html.tostring(doc, encoding="unicode")
    return out.replace(">48件<", ">1件<").replace("31～48", "1～1").encode("utf-8")


SYNTHETIC = {"list_13_only_0515": single_row_page("01-08-13-0515")}


def page_bytes(name: str) -> bytes:
    return SYNTHETIC[name] if name in SYNTHETIC else fixture_bytes(name)


@dataclass
class FakeHwis:
    """Serves 東京 (2 pages), an empty result for every other prefecture,
    an empty 託児 search, and detail pages (a saved one when known, the
    0515 page otherwise, the deleted-course page for ``gone`` ids)."""

    gone: set[str] = field(default_factory=set)
    status: int = 200
    pref_pages: dict[str, list[str]] = field(default_factory=lambda: {"13": ["list_13_p1.html", "list_13_p2.html"]})
    childcare_pages: list[str] = field(default_factory=lambda: ["list_empty.html"])
    broken_detail: set[str] = field(default_factory=set)
    _page_index: int = 0
    _current: list[str] = field(default_factory=list)

    def __call__(self, call: Call) -> tuple[int, bytes]:
        if self.status != 200:
            return self.status, b""
        if call.method == "GET" and (call.params or {}).get("action") == "initDisp":
            return 200, fixture_bytes("search_form.html")
        if call.method == "GET":
            key = detail_id(call)
            if key in self.gone:
                return 200, fixture_bytes("detail_02-08-13-9999.html")
            if key in self.broken_detail:
                return 200, fixture_bytes("system_error.html")
            name = key if key in KNOWN_DETAILS else "01-08-13-0515"
            return 200, fixture_bytes(f"detail_{name}.html")
        data = dict(call.data or [])
        if "fwListNaviBtnNext" in data:
            self._page_index += 1
            return 200, page_bytes(self._current[self._page_index])
        if "tJServiceAriCKBox" in data:
            self._current, self._page_index = self.childcare_pages, 0
            return 200, page_bytes(self.childcare_pages[0])
        pref = next((v for k, v in call.data or [] if k.endswith("SCKBox")), "")
        self._current = self.pref_pages.get(f"{int(pref):02d}", ["list_empty.html"])
        self._page_index = 0
        return 200, page_bytes(self._current[0])

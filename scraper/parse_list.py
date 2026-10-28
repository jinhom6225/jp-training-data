"""HWIS 職業訓練検索 result pages → rows (research raw §2-1).

A result page shows 「48件中 1～30 件を表示」 and one ``table.kyujin`` per
course with the kind label (公共職業訓練 / 求職者支援訓練), the name, and
募集状況 / 開講日 / 訓練実施会場所在地. An empty search shows
「ご希望の条件に合致する情報は見つかりませんでした」. Anything else (the
システムエラー page HWIS returns with status 200, the 入力エラー page, a
changed layout) raises ``StructureError``.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import date
from urllib.parse import parse_qs, urlsplit

import lxml.html

from scraper.errors import StructureError
from scraper.textnorm import element_text, japanese_date, normalize, parse_html

__all__ = ["ListPage", "ListRow", "StructureError", "form_fields", "parse_list_page"]

KIND_LABELS: dict[str, str] = {"公共職業訓練": "public", "求職者支援訓練": "kyushoku"}
NO_RESULT = "ご希望の条件に合致する情報は見つかりませんでした"
_COUNT = re.compile(r"([0-9]+)件中 ?([0-9]+) ?[~～〜] ?([0-9]+) ?件を表示")
_ROW_NUMBER = re.compile(r"^No\.[0-9]+ ")
_KEY_PARTS = (("kRNShubetsu_Detail", 2), ("shinseiNendo_Detail", 2), ("tDFKNo_Detail", 2), ("kRNTsuban_Detail", 4))
_SEARCH_FIELDS = re.compile(r"SCKBox$|^courseShubetsuCKBox$|^tJServiceAriCKBox$")


@dataclass(frozen=True)
class ListRow:
    """One course of a result page."""

    course_id: str
    kind: str
    name: str
    status: str | None
    opening: date | None
    address: str | None

    @property
    def pref(self) -> str:
        """JIS code in the id (third group), which may differ from the
        prefecture searched (the form warns that venues across a border
        can appear)."""
        return self.course_id.split("-")[2]


@dataclass(frozen=True)
class ListPage:
    """One parsed result page."""

    total: int
    page: int
    has_next: bool
    rows: list[ListRow] = field(default_factory=list)
    skipped: int = 0


def check_error_pages(doc: lxml.html.HtmlElement) -> None:
    """Raise for the pages HWIS serves with status 200 instead of content."""
    title = doc.findtext(".//title") or ""
    if "システムエラー" in title:
        raise StructureError("HWIS system error page")
    if "入力エラーがあります" in doc.text_content():
        raise StructureError("HWIS input error page")


def detail_key(href: str) -> str:
    """The 4-part course id ``kRNShubetsu-shinseiNendo-tDFKNo-kRNTsuban``
    from a detail link."""
    query = parse_qs(urlsplit(href).query)
    parts = []
    for name, width in _KEY_PARTS:
        value = (query.get(name) or [""])[0]
        if not re.fullmatch(f"[0-9]{{{width}}}", value):
            raise StructureError(f"detail link without {name}: {href[:120]}")
        parts.append(value)
    return "-".join(parts)


def _row_values(table: lxml.html.HtmlElement) -> dict[str, str | None]:
    values: dict[str, str | None] = {}
    for row in table.xpath(".//div[contains(@class,'right-side')]//tr"):
        cells = row.findall("td")
        if len(cells) >= 2:
            label = element_text(cells[0]) or ""
            values[label] = element_text(cells[1])
    return values


def _parse_row(table: lxml.html.HtmlElement) -> ListRow | None:
    labels = table.xpath(".//tr[contains(@class,'kyujin_head')]//span[contains(@class,'nes_label')]")
    links = [a.get("href") for a in table.iter("a") if "action=dispDetailBtn" in (a.get("href") or "")]
    if not labels or not links:
        raise StructureError("result row without kind label or detail link")
    course_id = detail_key(links[0])
    kind = KIND_LABELS.get(element_text(labels[0]) or "")
    if kind is None:
        return None
    head = table.xpath(".//tr[contains(@class,'kyujin_head')]//div[contains(@class,'mt05')]")
    name = _ROW_NUMBER.sub("", element_text(head[0]) or "") if head else ""
    if not name:
        raise StructureError(f"result row {course_id} without a name")
    values = _row_values(table)
    return ListRow(
        course_id=course_id,
        kind=kind,
        name=name,
        status=values.get("募集状況"),
        opening=japanese_date(values.get("開講日")),
        address=values.get("訓練実施会場所在地"),
    )


def _input_value(doc: lxml.html.HtmlElement, name: str) -> str | None:
    found = doc.xpath(f".//input[@name='{name}']")
    return found[0].get("value") if found else None


def parse_list_page(content: bytes) -> ListPage:
    """Rows of one result page; raises ``StructureError`` when the page is
    not a result page or its row count disagrees with its own header."""
    doc = parse_html(content)
    check_error_pages(doc)
    text = normalize(doc.text_content()) or ""
    if NO_RESULT in text:
        return ListPage(total=0, page=1, has_next=False)
    count = _COUNT.search(text)
    if count is None:
        raise StructureError("result page without the 「N件中」 count")
    total, first, last = (int(g) for g in count.groups())
    tables = doc.xpath("//table[contains(concat(' ',@class,' '),' kyujin ')][.//tr[contains(@class,'kyujin_head')]]")
    if len(tables) != last - first + 1:
        raise StructureError(f"{len(tables)} rows on a page announcing {first}-{last}")
    rows = [_parse_row(t) for t in tables]
    kept = [r for r in rows if r is not None]
    nexts = doc.xpath(".//input[@name='fwListNaviBtnNext']")
    has_next = bool(nexts) and nexts[0].get("disabled") is None and last < total
    page = int(_input_value(doc, "fwListNowPage") or "1")
    return ListPage(total=total, page=page, has_next=has_next, rows=kept, skipped=len(rows) - len(kept))


def form_fields(content: bytes) -> list[tuple[str, str]]:
    """The values the page's form would submit, without buttons and the
    list navigation selects (sending fields the page does not have makes
    HWIS answer with its システムエラー page).

    On the search page the area and course-type checkboxes are left out
    so the caller adds its own; on a result page the checked conditions
    are kept, so posting them back with ``fwListNaviBtnNext`` pages on.
    """
    doc = parse_html(content)
    if not doc.forms:
        raise StructureError("page without a form")
    search_page = not doc.xpath(".//input[@name='fwListNowPage']")
    data: list[tuple[str, str]] = []
    for element in doc.forms[0].inputs:
        name = element.name
        if name is None:
            continue
        kind = getattr(element, "type", None)
        if element.tag == "select":
            if not name.startswith("fwListNavi"):
                data.append((name, element.value or ""))
        elif kind in ("hidden", "text"):
            data.append((name, element.value or ""))
        elif kind in ("radio", "checkbox") and element.checked:
            if not (search_page and _SEARCH_FIELDS.search(name)):
                data.append((name, element.value))
    return data

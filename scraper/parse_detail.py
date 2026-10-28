"""HWIS 職業訓練詳細 page → the fact boxes the app shows (research §1-5).

Only short facts are read: name, kind, 分類 string, 募集状況, 訓練期間,
訓練時間, 自己負担額, 募集定員, 募集期間 1-5回目 with their 選考日 and
選考結果通知日, 訓練対象者の条件, 実施機関 / 施設 / 会場所在地. 訓練内容
prose is never read. HWIS detail pages carry no phone number (checked
2026-10-28), so ``phone`` is not parsed.

A deleted course answers 「該当する情報は見つかりませんでした」 → ``None``.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date

import lxml.html

from scraper.errors import StructureError
from scraper.parse_list import KIND_LABELS, check_error_pages
from scraper.textnorm import all_japanese_dates, element_text, japanese_date, normalize, parse_html

__all__ = ["Detail", "DetailRound", "japanese_date", "normalize", "parse_detail_page"]

GONE = "該当する情報は見つかりませんでした"
_ROUND_LABEL = re.compile(r"募集期間\(([0-9])回目\)")
_POSTAL = re.compile(r"^〒?[0-9]{3}-[0-9]{4}\s*")
_SELF_COST_LIMIT = 80


@dataclass(frozen=True)
class DetailRound:
    """募集期間 N回目 with its 選考日 and 選考結果通知日."""

    no: int
    start: date
    end: date
    selection: date | None = None
    result: date | None = None


@dataclass(frozen=True)
class Detail:
    """Facts of one course detail page (all text NFKC-normalized)."""

    name: str
    kind: str | None
    category: str | None
    status: str | None
    rounds: list[DetailRound]
    training_start: date | None
    training_end: date | None
    hours: str | None
    self_cost: str | None
    capacity: int | None
    conditions: str | None
    institution: str | None
    facility: str | None
    address: str | None


def _course_label_spans(doc: lxml.html.HtmlElement, label: str) -> list[str | None]:
    spans = doc.xpath(f"//span[@id='ID_kRNCourseBRUILabel'][contains(., '{label}')]/following-sibling::span")
    return [element_text(s) for s in spans]


def _labelled_div(doc: lxml.html.HtmlElement, label: str) -> lxml.html.HtmlElement | None:
    """The div whose own text starts with 「label：」 (prose such as
    「訓練期間中から…」 in 訓練内容 must not match)."""
    found = doc.xpath(f"//div[starts-with(normalize-space(text()), '{label}：')]")
    return found[0] if found else None


def _row_cells(doc: lxml.html.HtmlElement) -> dict[str, lxml.html.HtmlElement]:
    cells: dict[str, lxml.html.HtmlElement] = {}
    for th in doc.xpath("//th[@scope='row']"):
        td = th.getnext()
        label = element_text(th)
        if td is not None and label and label not in cells:
            cells[label] = td
    return cells


def _dates_in(element: lxml.html.HtmlElement | None, label: str) -> list[date]:
    if element is None:
        return []
    found = []
    for text in all_japanese_dates(element.text_content()):
        parsed = japanese_date(text)
        if parsed is None:
            raise StructureError(f"bad date {text!r} in {label}")
        found.append(parsed)
    return found


def _rounds(cells: dict[str, lxml.html.HtmlElement]) -> list[DetailRound]:
    rounds = []
    for label, td in cells.items():
        match = _ROUND_LABEL.fullmatch(label)
        if match is None:
            continue
        no = int(match.group(1))
        dates = _dates_in(td, label)
        if len(dates) != 2:
            raise StructureError(f"{label} without a start and an end date")
        selection = _dates_in(cells.get(f"選考日({no}回目)"), "選考日")
        result = _dates_in(cells.get(f"選考結果通知日({no}回目)"), "選考結果通知日")
        rounds.append(DetailRound(no, dates[0], dates[1], selection[0] if selection else None, result[0] if result else None))
    if not rounds:
        raise StructureError("detail page without 募集期間")
    return sorted(rounds, key=lambda r: r.no)


def _hours(doc: lxml.html.HtmlElement) -> str | None:
    div = _labelled_div(doc, "訓練時間")
    if div is None:
        return None
    times = [element_text(s) for s in div.findall("span")][:2]
    if len(times) != 2 or not all(times) or times[0] == times[1] == "00:00":
        return None  # e-learning courses show 00:00〜00:00
    return f"{times[0]}〜{times[1]}"


def _self_cost(doc: lxml.html.HtmlElement) -> str | None:
    text = element_text(_labelled_div(doc, "自己負担額"))
    if text is None:
        return None
    text = re.sub(r"^自己負担額\s*:\s*", "", text)
    text = re.sub(r"\s*円", "円", text)
    text = re.sub(r":\s*", ":", text)
    text = re.sub(r"\s*\(\s*", "(", text)
    text = re.sub(r"\s*\)", ")", text)
    if len(text) > _SELF_COST_LIMIT:
        text = text.split("(")[0]
    return normalize(text)


def _training_period(doc: lxml.html.HtmlElement) -> tuple[date | None, date | None]:
    dates = _dates_in(_labelled_div(doc, "訓練期間"), "訓練期間")
    return (dates[0], dates[1]) if len(dates) >= 2 else (None, None)


def _capacity(td: lxml.html.HtmlElement | None) -> int | None:
    match = re.search(r"[0-9]+", element_text(td) or "")
    return int(match.group(0)) if match else None


def _address(td: lxml.html.HtmlElement | None) -> str | None:
    text = element_text(td)
    return normalize(_POSTAL.sub("", text)) if text else None


def parse_detail_page(content: bytes) -> Detail | None:
    """Facts of a detail page, ``None`` for a deleted course, or
    ``StructureError`` when the page is not a detail page."""
    doc = parse_html(content)
    check_error_pages(doc)
    title = doc.xpath("//*[@id='ID_kRNTitle']")
    if not title:
        if GONE in (doc.text_content() or ""):
            return None
        raise StructureError("detail page without the course title")
    name = element_text(title[0])
    if not name:
        raise StructureError("detail page with an empty course title")
    classification = _course_label_spans(doc, "訓練コース分類")
    status = _course_label_spans(doc, "募集状況")
    cells = _row_cells(doc)
    training_start, training_end = _training_period(doc)
    return Detail(
        name=name,
        kind=KIND_LABELS.get(classification[0] or "") if classification else None,
        category=classification[1] if len(classification) > 1 else None,
        status=status[0] if status else None,
        rounds=_rounds(cells),
        training_start=training_start,
        training_end=training_end,
        hours=_hours(doc),
        self_cost=_self_cost(doc),
        capacity=_capacity(cells.get("募集定員")),
        conditions=element_text(cells.get("訓練対象者の条件")),
        institution=element_text(cells.get("訓練実施機関")),
        facility=element_text(cells.get("訓練実施施設")),
        address=_address(cells.get("訓練実施会場所在地")),
    )

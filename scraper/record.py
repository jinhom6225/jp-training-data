"""Parsed HWIS detail → one course object of pref/NN.json (data_schema.md).

Choices the schema leaves open (documented for the app side):

- ``provider`` is the 訓練実施施設 (the school people attend and call), or
  the 訓練実施機関 when the page has no facility.
- ``selectionDate`` / ``resultDate`` are per round on HWIS but single in the
  schema: they come from the first round whose end is today or later, or
  from the last round when every round has ended.
- ``phone`` is always null: HWIS detail pages show no phone number.
- ``childcare`` is true when the course is in HWIS's 託児サービスあり search
  or its name says 託児.
- Text longer than its schema limit is cut and ends with 「…」; an out-of-range
  ``capacity`` becomes null rather than dropping the course.
"""

from __future__ import annotations

import re
from datetime import date, datetime

from scraper.classify import classify
from scraper.hwis_client import HwisClient
from scraper.parse_detail import Detail, DetailRound
from scraper.rules import MAX_CAPACITY, TEXT_LIMITS, utf16_len

PREFECTURES = (
    "北海道", "青森県", "岩手県", "宮城県", "秋田県", "山形県", "福島県", "茨城県", "栃木県",
    "群馬県", "埼玉県", "千葉県", "東京都", "神奈川県", "新潟県", "富山県", "石川県", "福井県",
    "山梨県", "長野県", "岐阜県", "静岡県", "愛知県", "三重県", "滋賀県", "京都府", "大阪府",
    "兵庫県", "奈良県", "和歌山県", "鳥取県", "島根県", "岡山県", "広島県", "山口県", "徳島県",
    "香川県", "愛媛県", "高知県", "福岡県", "佐賀県", "長崎県", "熊本県", "大分県", "宮崎県",
    "鹿児島県", "沖縄県",
)
# Cities whose name holds 市 or 郡 before its end (a plain pattern cuts them).
_ODD_CITIES = ("四日市市", "廿日市市", "野々市市", "大和郡山市", "小郡市", "郡上市", "市川市", "市原市", "郡山市")
_DESIGNATED = (
    "札幌市", "仙台市", "さいたま市", "千葉市", "横浜市", "川崎市", "相模原市", "新潟市", "静岡市",
    "浜松市", "名古屋市", "京都市", "大阪市", "堺市", "神戸市", "岡山市", "広島市", "北九州市",
    "福岡市", "熊本市",
)
_DESIGNATED_WARD = re.compile("(" + "|".join(_DESIGNATED) + r")(.{1,5}?区)")
_DISTRICT = re.compile(r"(.+?郡.+?[町村])")
_CITY = re.compile(r"(.+?市)")
_WARD = re.compile(r"(.+?区)")
_TOWN = re.compile(r"(.+?[町村])")
_ELLIPSIS = "…"


def clip(text: str | None, limit: int) -> str | None:
    """``text`` cut to ``limit`` UTF-16 units, ending in 「…」 when cut."""
    if text is None or utf16_len(text) <= limit:
        return text
    out = ""
    for char in text:
        if utf16_len(out + char) > limit - 1:
            break
        out += char
    return out + _ELLIPSIS


def _without_prefecture(address: str) -> str:
    for name in PREFECTURES:
        if address.startswith(name):
            return address[len(name):]
    return address


def city_from_address(address: str | None) -> str | None:
    """市区町村 at the start of an address (prefecture optional):
    政令市 + 区, 郡 + 町村, 市, 東京 区, or 町村."""
    if not address:
        return None
    rest = _without_prefecture(address.strip())
    for odd in _ODD_CITIES:
        if rest.startswith(odd):
            return odd
    designated = _DESIGNATED_WARD.match(rest)
    if designated:
        return designated.group(0)
    district_first = "郡" in rest and ("市" not in rest or rest.index("郡") < rest.index("市"))
    patterns = (_DISTRICT, _CITY, _WARD, _TOWN) if district_first else (_CITY, _WARD, _TOWN)
    for pattern in patterns:
        match = pattern.match(rest)
        if match:
            return clip(match.group(1), TEXT_LIMITS["city"])
    return None


def _reference_round(rounds: list[DetailRound], today: date) -> DetailRound:
    for round_ in rounds:
        if round_.end >= today:
            return round_
    return rounds[-1]


def _iso(value: date | None) -> str | None:
    return value.isoformat() if value else None


def last_end(course: dict) -> date:
    """The last day of a course's last round."""
    return date.fromisoformat(course["rounds"][-1]["end"])


def build_course(
    course_id: str,
    detail: Detail,
    *,
    childcare: bool,
    checked_at: datetime,
    today: date,
    fallback_kind: str | None = None,
    fallback_address: str | None = None,
) -> dict:
    """The schema object of one HWIS course."""
    reference = _reference_round(detail.rounds, today)
    address = detail.address or fallback_address
    capacity = detail.capacity if detail.capacity and 1 <= detail.capacity <= MAX_CAPACITY else None
    return {
        "id": course_id,
        "origin": "hwis",
        "kind": detail.kind or fallback_kind,
        "name": clip(detail.name, TEXT_LIMITS["name"]),
        "fields": classify(detail.name, detail.category),
        "city": city_from_address(address),
        "address": clip(address, TEXT_LIMITS["address"]),
        "rounds": [{"no": r.no, "start": r.start.isoformat(), "end": r.end.isoformat()} for r in detail.rounds],
        "trainingStart": _iso(detail.training_start),
        "trainingEnd": _iso(detail.training_end),
        "hours": clip(detail.hours, TEXT_LIMITS["hours"]),
        "selfCost": clip(detail.self_cost, TEXT_LIMITS["selfCost"]),
        "capacity": capacity,
        "selectionDate": _iso(reference.selection),
        "resultDate": _iso(reference.result),
        "conditions": clip(detail.conditions, TEXT_LIMITS["conditions"]),
        "childcare": childcare or "託児" in detail.name,
        "provider": clip(detail.facility or detail.institution, TEXT_LIMITS["provider"]),
        "phone": None,
        "sourceUrl": HwisClient.detail_url(course_id),
        "checkedAt": checked_at.isoformat(timespec="seconds"),
    }

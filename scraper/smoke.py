"""Access check from the runner's IP (plan 1-0, D3).

Three requests through the normal client: the search form (cookie), the
東京 list, and the first listed course's detail without cookies. Passes
when all three answer 200, the list has at least one row and the detail
shows 募集期間. The summary goes to the log and Telegram.

    python -m scraper.smoke
"""

from __future__ import annotations

import logging
import sys
from typing import Callable

from scraper import telegram
from scraper.collect import pref_conditions
from scraper.errors import BlockedError, FetchError, StructureError
from scraper.hwis_client import HwisClient, RequestsTransport
from scraper.parse_detail import parse_detail_page
from scraper.parse_list import parse_list_page

log = logging.getLogger("scraper.smoke")


def check(client: HwisClient, *, notify: Callable[[str], object]) -> bool:
    """Run the three requests; True when HWIS is usable from here."""
    try:
        base = client.start_session()
        page = parse_list_page(client.search(base, pref_conditions("13")))
        if not page.rows:
            raise StructureError("東京 list has no rows")
        first = page.rows[0].course_id
        detail = parse_detail_page(client.detail(first))
        if detail is None:
            raise StructureError(f"detail {first} not found")
    except (BlockedError, FetchError, StructureError) as error:
        notify(f"jp-training-data smoke FAILED: {type(error).__name__}: {error}")
        return False
    notify(
        f"jp-training-data smoke OK: 東京 {page.total} courses listed, "
        f"detail {first} has {len(detail.rounds)} 募集期間 round(s), {client.request_count} requests"
    )
    return True


def main() -> int:  # pragma: no cover  (network)
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")

    def notify(text: str) -> None:
        log.info(text)
        telegram.send(text)

    return 0 if check(HwisClient(RequestsTransport()), notify=notify) else 1


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())

"""Telegram notices for anomalies and failures (research §3.1-5).

Uses ``TELEGRAM_BOT_TOKEN`` and ``TELEGRAM_CHAT_ID``. Without them the
message is logged as a warning (and annotated on the Actions run page) but
nothing fails, so local runs work. Sending never raises and never logs the
token.
"""

from __future__ import annotations

import logging
import os
from typing import Any, Callable, Mapping

import requests

log = logging.getLogger(__name__)
MAX_LENGTH = 4000
TIMEOUT = 15.0


def send(
    text: str,
    *,
    env: Mapping[str, str] = os.environ,
    post: Callable[..., Any] = requests.post,
) -> bool:
    """Send ``text``; True only when Telegram accepted it."""
    token = env.get("TELEGRAM_BOT_TOKEN", "").strip()
    chat_id = env.get("TELEGRAM_CHAT_ID", "").strip()
    body = text if len(text) <= MAX_LENGTH else text[: MAX_LENGTH - 1] + "…"
    if not token or not chat_id:
        log.warning("telegram secrets missing, notice not sent: %s", body)
        if env.get("GITHUB_ACTIONS") == "true":
            # Shows as a warning on the Actions run page, not only in the log.
            print("::warning::TELEGRAM_BOT_TOKEN or TELEGRAM_CHAT_ID is not set; Telegram notices are off")
        return False
    try:
        response = post(
            f"https://api.telegram.org/bot{token}/sendMessage",
            data={"chat_id": chat_id, "text": body, "disable_web_page_preview": "true"},
            timeout=TIMEOUT,
        )
    except Exception as error:  # noqa: BLE001  (a notice must never stop the run)
        log.warning("telegram send failed: %s", type(error).__name__)
        return False
    if response.status_code != 200:
        log.warning("telegram answered HTTP %s", response.status_code)
        return False
    return True

"""Send messages to Telegram via Bot API."""
from __future__ import annotations

import logging
import os
from typing import Optional

import requests


log = logging.getLogger(__name__)

API_BASE = "https://api.telegram.org"


def _config() -> tuple[str, str]:
    token = os.environ.get("TELEGRAM_BOT_TOKEN")
    chat_id = os.environ.get("TELEGRAM_CHAT_ID")
    if not token or not chat_id:
        raise RuntimeError(
            "TELEGRAM_BOT_TOKEN and TELEGRAM_CHAT_ID env vars must be set."
        )
    return token, chat_id


def send(text: str, parse_mode: Optional[str] = "Markdown") -> None:
    """Send a single message. Raises on HTTP error."""
    token, chat_id = _config()
    url = f"{API_BASE}/bot{token}/sendMessage"
    payload = {
        "chat_id": chat_id,
        "text": text,
        "disable_web_page_preview": True,
    }
    if parse_mode:
        payload["parse_mode"] = parse_mode
    resp = requests.post(url, json=payload, timeout=15)
    if resp.status_code >= 400:
        log.error("Telegram error %s: %s", resp.status_code, resp.text)
        resp.raise_for_status()

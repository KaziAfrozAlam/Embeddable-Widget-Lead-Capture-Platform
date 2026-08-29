"""Outbound webhook side effect. Raises on failure so the worker can retry."""

import httpx

from ..config import get_settings


def send_webhook(payload: dict) -> None:
    settings = get_settings()
    url = settings.webhook_url
    if not url:
        raise RuntimeError("no WEBHOOK_URL configured")
    resp = httpx.post(url, json=payload, timeout=3.0)
    resp.raise_for_status()
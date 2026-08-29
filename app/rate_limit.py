"""In-memory fixed-window rate limiters for the public submission endpoint.

Per-IP and per-widget budgets are checked independently and both must pass.
A flood returns 429 with a Retry-After header while normal traffic keeps flowing.
"""

import ipaddress
import threading
import time

from fastapi import Request

from .config import get_settings


def _as_ip(value: str) -> str | None:
    """Canonical IP string, or None when the value isn't a valid address."""
    try:
        return str(ipaddress.ip_address(value))
    except ValueError:
        return None


class FixedWindowLimiter:
    def __init__(self, max_requests: int, window_seconds: int):
        self.max_requests = max_requests
        self.window_seconds = window_seconds
        self._buckets: dict[str, tuple[float, int]] = {}
        self._lock = threading.Lock()

    def allowed(self, key: str) -> tuple[bool, int | None]:
        """Return (allowed, retry_after_seconds)."""
        now = time.monotonic()
        with self._lock:
            if len(self._buckets) > 10_000:
                # coarse prune of expired buckets
                cutoff = now - max(self.window_seconds, 5)
                self._buckets = {k: v for k, v in self._buckets.items() if v[0] > cutoff}
            start, count = self._buckets.get(key, (now, 0))
            if now - start >= self.window_seconds:
                start, count = now, 0
            if count >= self.max_requests:
                retry_after = int(max(1.0, start + self.window_seconds - now))
                return False, retry_after
            self._buckets[key] = (start, count + 1)
            return True, None

    def reset(self) -> None:
        with self._lock:
            self._buckets.clear()


def client_ip(request: Request) -> str:
    """Best-effort client address, resistant to header spoofing.

    trust_proxy_count == 0 (default, direct deployment): X-Forwarded-For is
    never trusted -- a header is trivial to forge, so the socket peer address
    is the only honest signal.

    trust_proxy_count == N (behind N trusted reverse proxies): the XFF entry
    at position len(parts) - N is the address our outermost trusted proxy saw
    the connection come from. Entries further left may be attacker-supplied
    and are ignored. Everything is validated as a real IP before use.
    """
    settings = get_settings()
    trust = settings.trust_proxy_count
    if trust > 0:
        forwarded = request.headers.get("x-forwarded-for")
        if forwarded:
            parts = [p.strip() for p in forwarded.split(",") if p.strip()]
            if parts:
                index = len(parts) - trust
                if 0 <= index < len(parts):
                    candidate = _as_ip(parts[index])
                    if candidate is not None:
                        return candidate
    if request.client and request.client.host:
        return request.client.host
    return "unknown"


class RateLimitError(Exception):
    def __init__(self, retry_after: int):
        self.retry_after = retry_after
        super().__init__("rate limit exceeded")
"""Geo providers with a fallback chain.

live mode: real free APIs (ip-api.com, ipapi.co)
mock mode: deterministic canned providers whose availability you toggle via env —
           used by the test suite and EVIDENCE.md so the fallback proof is repeatable.
"""

from dataclasses import dataclass

import httpx

from ..config import get_settings


class ProviderDown(Exception):
    """Raised when a provider is unavailable (network, toggle, or bad response)."""


@dataclass
class GeoResult:
    country: str
    city: str
    provider: str


def _public_mock_response(ip: str) -> dict:
    """Deterministic mock datasets keyed by IP."""
    table = {
        "8.8.8.8": {"country": "US", "city": "Mountain View"},
        "1.1.1.1": {"country": "AU", "city": "Sydney"},
        "9.9.9.9": {"country": "DE", "city": "Frankfurt"},
    }
    return table.get(ip, {"country": "XX", "city": "Mockville"})


class ProviderA:
    """ip-api.com — free, no key, ~45 req/min."""

    name = "ip-api"

    def __init__(self) -> None:
        settings = get_settings()

        def live(ip: str) -> GeoResult | None:
            url = settings.geo_provider_a_url + ip
            resp = httpx.get(
                url,
                params={"fields": "status,message,country,city,query"},
                timeout=settings.geo_timeout_seconds,
            )
            resp.raise_for_status()
            body = resp.json()
            if body.get("status") != "success" or not body.get("country"):
                return None  # private/bogus IP — no data, not an outage
            return GeoResult(country=body["country"], city=body.get("city") or "", provider=self.name)

        def mock(ip: str) -> GeoResult | None:
            if not settings.geo_provider_a_enabled:
                raise ProviderDown("provider A toggled down (mock)")
            row = _public_mock_response(ip)
            return GeoResult(country=row["country"], city=row["city"], provider=self.name)

        self._lookup = live if settings.geo_mode == "live" else mock

    def lookup(self, ip: str) -> GeoResult | None:
        # A hard failure (timeout, 5xx, toggle) is an outage: raise so the chain
        # moves to provider B. A successful response with no data is a miss: return None.
        return self._lookup(ip)


class ProviderB:
    """ipapi.co — free tier ~1,000 lookups/day, optional key."""

    name = "ipapi.co"

    def __init__(self) -> None:
        settings = get_settings()

        def live(ip: str) -> GeoResult | None:
            url = settings.geo_provider_b_url.format(ip=ip)
            headers = {}
            if settings.geo_provider_b_api_key:
                headers["Authorization"] = f"Bearer {settings.geo_provider_b_api_key}"
            resp = httpx.get(url, headers=headers or None, timeout=settings.geo_timeout_seconds)
            resp.raise_for_status()
            body = resp.json()
            if body.get("error") or not body.get("country_name"):
                return None
            return GeoResult(
                country=body["country_name"] if isinstance(body["country_name"], str) else "",
                city=body.get("city") or "",
                provider=self.name,
            )

        def mock(ip: str) -> GeoResult | None:
            if not settings.geo_provider_b_enabled:
                raise ProviderDown("provider B toggled down (mock)")
            row = _public_mock_response(ip)
            return GeoResult(country=row["country"], city=row["city"], provider=self.name)

        self._lookup = live if settings.geo_mode == "live" else mock

    def lookup(self, ip: str) -> GeoResult | None:
        return self._lookup(ip)


def build_chain() -> list:
    return [ProviderA(), ProviderB()]


def enrich(ip: str) -> GeoResult | None:
    """Try provider A, then B, then give up gracefully. Never raises."""
    for provider in build_chain():
        try:
            result = provider.lookup(ip)
        except Exception:
            continue  # provider down — move to the next / degrade
        if result is not None:
            return result
    return None
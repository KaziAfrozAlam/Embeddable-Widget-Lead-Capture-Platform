"""client_ip trust semantics: X-Forwarded-For must not be spoofable.

Default (trust_proxy_count=0, direct deployment) ignores the header entirely
and uses the socket peer. Behind N trusted proxies the entry written by our
outermost proxy wins; everything left of it is treated as forgery.
"""

import types

from fastapi import Request

from app import rate_limit
from app.rate_limit import client_ip


def _scope(client=("203.0.113.7", 12345), headers=()):
    return {
        "type": "http",
        "method": "POST",
        "path": "/submissions",
        "headers": [(k.encode(), v.encode()) for k, v in headers],
        "client": client,
    }


def _settings(trust):
    return types.SimpleNamespace(trust_proxy_count=trust)


def test_direct_deployment_ignores_spoofed_xff(monkeypatch):
    monkeypatch.setattr(rate_limit, "get_settings", lambda: _settings(0))
    req = Request(_scope(headers=[("x-forwarded-for", "1.2.3.4")]))
    assert client_ip(req) == "203.0.113.7"


def test_behind_one_proxy_uses_xff_entry(monkeypatch):
    monkeypatch.setattr(rate_limit, "get_settings", lambda: _settings(1))
    req = Request(_scope(headers=[("x-forwarded-for", "198.51.100.23")]))
    assert client_ip(req) == "198.51.100.23"


def test_forged_entries_before_proxy_entry_ignored(monkeypatch):
    # Attacker stuffing X-Forwarded-For can only add entries to the LEFT of the
    # one our trusted proxy appends; the rightmost entry is the honest one.
    monkeypatch.setattr(rate_limit, "get_settings", lambda: _settings(1))
    req = Request(_scope(headers=[("x-forwarded-for", "1.2.3.4, 198.51.100.23")]))
    assert client_ip(req) == "198.51.100.23"


def test_behind_two_proxies_takes_trusted_chain_entry(monkeypatch):
    monkeypatch.setattr(rate_limit, "get_settings", lambda: _settings(2))
    req = Request(_scope(headers=[("x-forwarded-for", "198.51.100.23, 10.0.0.1")]))
    assert client_ip(req) == "198.51.100.23"


def test_invalid_xff_falls_back_to_peer(monkeypatch):
    monkeypatch.setattr(rate_limit, "get_settings", lambda: _settings(1))
    req = Request(_scope(headers=[("x-forwarded-for", "not-an-ip, 1.2.3.4:65533")]))
    assert client_ip(req) == "203.0.113.7"


def test_proxy_count_larger_than_entries_falls_back_to_peer(monkeypatch):
    monkeypatch.setattr(rate_limit, "get_settings", lambda: _settings(5))
    req = Request(_scope(headers=[("x-forwarded-for", "198.51.100.23")]))
    assert client_ip(req) == "203.0.113.7"


def test_no_client_info_falls_back_to_unknown(monkeypatch):
    monkeypatch.setattr(rate_limit, "get_settings", lambda: _settings(1))
    req = Request(_scope(client=None))
    assert client_ip(req) == "unknown"
"""Test fixtures. Environment is configured BEFORE any app import so the
settings cache is built with test values (mock geo, huge default rate limits,
isolated temp SQLite DB)."""

import os
import tempfile
import uuid
from pathlib import Path

_TMP = Path(tempfile.mkdtemp(prefix="lcp_tests_"))
os.environ.setdefault("DATABASE_URL", f"sqlite:///{_TMP / 'test.db'}")
os.environ.setdefault("GEO_MODE", "mock")
os.environ.setdefault("MAIL_MODE", "console")
os.environ.setdefault("SECRET_KEY", "test-secret-key-1234567890-abcdefghijklmnop")
os.environ.setdefault("API_BASE_URL", "http://testserver")
os.environ.setdefault("RATE_LIMIT_IP_MAX", "100000")
os.environ.setdefault("RATE_LIMIT_WIDGET_MAX", "100000")
# Tests emulate a single trusted reverse proxy in front of the app (they set
# x-forwarded-for to name the visitor). trust_proxy_count=1 makes client_ip
# read the proxy's entry; with the default 0 the header would be ignored.
os.environ.setdefault("TRUST_PROXY_COUNT", "1")

import pytest
from fastapi.testclient import TestClient

from app import models  # noqa: F401  (register tables)
from app.api import public as public_api
from app.config import get_settings
from app.db import Base, SessionLocal, engine
from app.main import app
from app.rate_limit import FixedWindowLimiter


@pytest.fixture(scope="session", autouse=True)
def _schema():
    Base.metadata.create_all(engine)
    yield
    engine.dispose()


@pytest.fixture()
def client():
    with TestClient(app) as c:
        yield c
    # Keep the DB tidy across tests: drop all rows so lists/stats are isolated.
    with SessionLocal() as db:
        for table in reversed(Base.metadata.sorted_tables):
            db.execute(table.delete())
        db.commit()


@pytest.fixture()
def settings():
    return get_settings()


def _unique(prefix: str) -> str:
    return f"{prefix}-{uuid.uuid4().hex[:10]}"


@pytest.fixture()
def owner(client):
    data = {
        "name": "Test Owner",
        "email": _unique("owner@test.dev"),
        "password": "password-123",
    }
    res = client.post("/api/auth/register", json=data)
    assert res.status_code == 201, res.text
    return res.json()


@pytest.fixture()
def auth(owner):
    return {"Authorization": "Bearer " + owner["access_token"]}


def _base_widget_payload():
    return {
        "type": "signup",
        "title": "Test signup",
        "description": "A signup form",
        "fields": [
            {"name": "name", "label": "Full name", "type": "text", "required": True},
            {"name": "email", "label": "Email", "type": "email", "required": True},
            {
                "name": "topic",
                "label": "Topic",
                "type": "select",
                "required": False,
                "options": ["A", "B"],
            },
        ],
        "button_text": "Go",
        "styles": {"accent_color": "#000000"},
    }


@pytest.fixture()
def make_widget(client, auth):
    def _make(**overrides):
        payload = _base_widget_payload()
        payload.update(overrides)
        res = client.post("/api/widgets", headers=auth, json=payload)
        assert res.status_code == 201, res.text
        return res.json()

    return _make


@pytest.fixture()
def valid_submission(client, make_widget):
    """Returns a (widget, submit callable)."""
    widget = make_widget()

    def _submit(token="tok", ip="8.8.8.8", **data_overrides):
        data = {"name": "Ada", "email": "ada@example.com", "topic": "A"}
        data.update(data_overrides)
        headers = {"x-forwarded-for": ip}
        return client.post(
            "/submissions",
            headers=headers,
            json={"widget_id": widget["id"], "client_token": token, "data": data},
        )

    return widget, _submit


@pytest.fixture()
def low_limits(monkeypatch):
    """Swap the module-level limiters for a tiny budget (3/min) — used only by
    the rate-limit test so other tests don't collide on counters."""
    monkeypatch.setattr(public_api, "_limiter_ip", FixedWindowLimiter(3, 60))
    monkeypatch.setattr(public_api, "_limiter_widget", FixedWindowLimiter(3, 60))


@pytest.fixture()
def second_owner(client):
    data = {
        "name": "Tenant B",
        "email": _unique("b@test.dev"),
        "password": "password-123",
    }
    res = client.post("/api/auth/register", json=data)
    assert res.status_code == 201, res.text
    return {"token": res.json()["access_token"], "owner": res.json()["owner"]}
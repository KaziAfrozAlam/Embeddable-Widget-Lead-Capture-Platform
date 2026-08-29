"""Auth + widget CRUD + tenant isolation + embed snippet generation."""

import re


def test_register_login_and_me(client, owner):
    res = client.get("/api/auth/me", headers={"Authorization": "Bearer " + owner["access_token"]})
    assert res.status_code == 200
    assert res.json()["email"] == owner["owner"]["email"]

    res = client.post(
        "/api/auth/login",
        json={"email": owner["owner"]["email"], "password": "password-123"},
    )
    assert res.status_code == 200
    assert res.json()["access_token"]

    res = client.post(
        "/api/auth/login",
        json={"email": owner["owner"]["email"], "password": "wrong-password"},
    )
    assert res.status_code == 401


def test_register_rejects_duplicate_email(client, owner):
    res = client.post(
        "/api/auth/register",
        json={"name": "Dup", "email": owner["owner"]["email"], "password": "password-123"},
    )
    assert res.status_code == 409
    assert "already" in res.json()["detail"]


def test_concurrent_register_same_email_returns_409_not_500(client, monkeypatch):
    """Two concurrent registers for one email: the loser hits
    UNIQUE(owners.email) on INSERT and must get a clean 409."""
    from app import models
    from app.api import auth as auth_api
    from app.db import SessionLocal

    email = "race@test.dev"
    with SessionLocal() as db:
        db.add(models.Owner(email=email, name="First", password_hash="x"))
        db.commit()

    def _blind_precheck(db_session, candidate_email):
        return None  # simulate the losing request that did not see the row

    monkeypatch.setattr(auth_api, "_owner_by_email", _blind_precheck)

    res = client.post(
        "/api/auth/register",
        json={"name": "Cloner", "email": email, "password": "password-123"},
    )
    assert res.status_code == 409
    assert "already" in res.json()["detail"]


def test_register_validates_password_and_email(client):
    assert client.post("/api/auth/register", json={"name": "X", "email": "x@y.dev", "password": "short"}).status_code == 422
    assert client.post("/api/auth/register", json={"name": "X", "email": "not-an-email", "password": "password-123"}).status_code == 422


def test_widget_crud_requires_auth(client):
    assert client.get("/api/widgets").status_code == 401
    assert client.post("/api/widgets", json={}).status_code == 401


def test_widget_create_list_get_update_delete(client, auth, make_widget):
    me = client.get("/api/auth/me", headers=auth).json()
    created = make_widget(title="Orig title")
    assert created["type"] == "signup"
    assert created["owner_id"] == me["id"]

    # list shows our widget
    listing = client.get("/api/widgets", headers=auth).json()
    assert any(w["id"] == created["id"] for w in listing)

    # get
    got = client.get(f"/api/widgets/{created['id']}", headers=auth)
    assert got.status_code == 200
    assert got.json()["title"] == "Orig title"

    # update (PATCH, partial)
    patched = client.patch(
        f"/api/widgets/{created['id']}",
        headers=auth,
        json={"title": "New title", "styles": {"accent_color": "#ff00ff"}},
    )
    assert patched.status_code == 200
    assert patched.json()["title"] == "New title"
    assert patched.json()["styles"] == {"accent_color": "#ff00ff"}
    # untouched fields survive
    assert patched.json()["type"] == "signup"

    # delete
    assert client.delete(f"/api/widgets/{created['id']}", headers=auth).status_code == 204
    assert client.get(f"/api/widgets/{created['id']}", headers=auth).status_code == 404


def test_widget_validation_errors(client, auth):
    # duplicate field names
    res = client.post(
        "/api/widgets",
        headers=auth,
        json={
            "type": "signup",
            "title": "dup",
            "fields": [
                {"name": "email", "label": "a", "type": "email", "required": True},
                {"name": "email", "label": "b", "type": "email", "required": True},
            ],
        },
    )
    assert res.status_code == 422
    # select must have options
    res = client.post(
        "/api/widgets",
        headers=auth,
        json={
            "type": "signup",
            "title": "sel",
            "fields": [{"name": "pick", "label": "p", "type": "select", "options": []}],
        },
    )
    assert res.status_code == 422
    # bad widget type
    res = client.post(
        "/api/widgets",
        headers=auth,
        json={"type": "nonsense", "title": "x", "fields": []},
    )
    assert res.status_code == 422


def test_tenant_isolation_for_widgets(client, auth, make_widget, second_owner):
    widget_a = make_widget(title="A private widget")

    headers_b = {"Authorization": "Bearer " + second_owner["token"]}
    # B cannot read A's widget
    assert client.get(f"/api/widgets/{widget_a['id']}", headers=headers_b).status_code == 404
    # B cannot update/delete it (and updating does not secretly work)
    assert client.patch(f"/api/widgets/{widget_a['id']}", headers=headers_b, json={"title": "hacked"}).status_code == 404
    assert client.delete(f"/api/widgets/{widget_a['id']}", headers=headers_b).status_code == 404
    # B's listing contains none of A's widgets
    res = client.get("/api/widgets", headers=headers_b)
    assert res.status_code == 200
    assert res.json() == []
    # B cannot fetch A's embed snippet either
    assert client.get(f"/api/widgets/{widget_a['id']}/embed", headers=headers_b).status_code == 404


def test_embed_snippet_is_versioned(client, auth, make_widget):
    from app.version import WIDGET_SCRIPT_VERSION

    widget = make_widget()
    res = client.get(f"/api/widgets/{widget['id']}/embed", headers=auth)
    assert res.status_code == 200
    data = res.json()
    assert data["widget_id"] == widget["id"]
    assert f"/embed/{WIDGET_SCRIPT_VERSION}/widget.js?id={widget['id']}" in data["script_url"]
    match = re.search(r'<script src="([^"]+)" async defer></script>', data["snippet"])
    assert match
    assert match.group(1) == data["script_url"]
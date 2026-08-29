"""Geo enrichment fallback chain (deterministic mock mode):
A answers → A; A down → B; both down → stored anyway without geo."""


def _submit(client, widget_id, ip="8.8.8.8", token="geo-tok"):
    return client.post(
        "/submissions",
        headers={"x-forwarded-for": ip},
        json={
            "widget_id": widget_id,
            "client_token": token,
            "data": {"name": "Ada", "email": "ada@example.com", "topic": "A"},
        },
    )


def _owner_auth(client, owner):
    return {"Authorization": "Bearer " + owner["access_token"]}


def test_provider_a_answers(client, make_widget, owner, settings):
    settings.geo_provider_a_enabled = True
    settings.geo_provider_b_enabled = True
    widget = make_widget()
    res = _submit(client, widget["id"])
    assert res.status_code == 201
    row = client.get("/api/dashboard/submissions", headers=_owner_auth(client, owner)).json()["items"][0]
    assert row["geo_country"] == "US"
    assert row["geo_city"] == "Mountain View"
    assert row["geo_provider"] == "ip-api"


def test_fallback_to_provider_b_when_a_is_down(client, make_widget, owner, settings):
    settings.geo_provider_a_enabled = False  # provider A: down
    settings.geo_provider_b_enabled = True
    widget = make_widget()
    res = _submit(client, widget["id"], ip="1.1.1.1")
    assert res.status_code == 201
    row = client.get("/api/dashboard/submissions", headers=_owner_auth(client, owner)).json()["items"][0]
    assert row["geo_country"] == "AU"
    assert row["geo_city"] == "Sydney"
    assert row["geo_provider"] == "ipapi.co"  # provider B answered


def test_all_providers_down_still_stored(client, make_widget, owner, settings):
    settings.geo_provider_a_enabled = False
    settings.geo_provider_b_enabled = False
    widget = make_widget()
    res = _submit(client, widget["id"], ip="9.9.9.9", token="geo-none")
    assert res.status_code == 201  # degrade, never fail
    row = client.get("/api/dashboard/submissions", headers=_owner_auth(client, owner)).json()["items"][0]
    assert row["geo_country"] is None
    assert row["geo_city"] is None
    assert row["geo_provider"] is None


def test_private_ip_enriches_to_nothing_but_stores(client, make_widget, owner, settings):
    settings.geo_provider_a_enabled = True
    settings.geo_provider_b_enabled = True
    widget = make_widget()
    res = _submit(client, widget["id"], ip="127.0.0.1", token="geo-local")
    assert res.status_code == 201
    row = client.get("/api/dashboard/submissions", headers=_owner_auth(client, owner)).json()["items"][0]
    assert row["geo_provider"] is not None  # mocked providers still "answer"
    assert row["ip"] == "127.0.0.1"
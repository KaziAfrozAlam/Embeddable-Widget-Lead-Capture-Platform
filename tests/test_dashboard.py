"""Owner dashboard: submission listing + aggregate stats."""


def _auth(owner):
    return {"Authorization": "Bearer " + owner["access_token"]}


def test_dashboard_empty_state(client, owner):
    res = client.get("/api/dashboard/stats", headers=_auth(owner))
    assert res.status_code == 200
    stats = res.json()
    assert stats["total"] == 0
    assert stats["today"] == 0
    assert stats["daily"]  # non-empty 30-day series


def test_dashboard_requires_auth(client):
    assert client.get("/api/dashboard/submissions").status_code == 401
    assert client.get("/api/dashboard/stats").status_code == 401


def test_dashboard_counts_and_breakdown(client, make_widget, owner, settings):
    settings.geo_provider_a_enabled = True
    settings.geo_provider_b_enabled = True
    w1 = make_widget(title="Signups")
    w2 = make_widget(title="Contacts")

    for i, (wid, ip) in enumerate(((w1["id"], "8.8.8.8"), (w1["id"], "1.1.1.1"), (w2["id"], "9.9.9.9"))):
        client.post(
            "/submissions",
            headers={"x-forwarded-for": ip},
            json={
                "widget_id": wid,
                "client_token": f"stat-{i}",
                "data": {"name": "N", "email": f"n{i}@example.com"},
            },
        )

    res = client.get("/api/dashboard/stats", headers=_auth(owner))
    assert res.status_code == 200
    stats = res.json()
    assert stats["total"] == 3
    assert stats["today"] == 3
    assert stats["last_7_days"] == 3

    by_widget = {w["title"]: w["count"] for w in stats["by_widget"]}
    assert by_widget["Signups"] == 2
    assert by_widget["Contacts"] == 1

    countries = {c["country"]: c["count"] for c in stats["by_country"]}
    assert countries == {"US": 1, "AU": 1, "DE": 1}

    daily = stats["daily"]
    assert len(daily) == 30  # a rolling 30-day series with zero-filled days
    assert sum(d["count"] for d in daily) == 3


def test_dashboard_list_pagination_and_filter(client, make_widget, owner, settings):
    settings.geo_provider_a_enabled = True
    settings.geo_provider_b_enabled = True
    w1 = make_widget(title="W1")
    w2 = make_widget(title="W2")
    for i in range(5):
        client.post(
            "/submissions",
            headers={"x-forwarded-for": "8.8.8.8"},
            json={
                "widget_id": w1["id"] if i < 3 else w2["id"],
                "client_token": f"page-{i}",
                "data": {"name": "N", "email": f"n{i}@example.com"},
            },
        )

    # filtered by widget
    res = client.get(f"/api/dashboard/submissions?widget_id={w1['id']}", headers=_auth(owner))
    body = res.json()
    assert body["total"] == 3
    assert all(i["widget_id"] == w1["id"] for i in body["items"])

    # paged
    res = client.get("/api/dashboard/submissions?page=1&page_size=2", headers=_auth(owner))
    assert res.json()["total"] == 5
    assert len(res.json()["items"]) == 2
    res = client.get("/api/dashboard/submissions?page=3&page_size=2", headers=_auth(owner))
    assert len(res.json()["items"]) == 1

    # filtering by another tenant's widget id → 404
    res = client.get("/api/dashboard/submissions?widget_id=nope", headers=_auth(owner))
    assert res.status_code == 404
"""Abuse protection: per-IP + per-widget rate limiting, 429 semantics."""


def test_rate_limit_returns_429_and_service_survives(client, auth, make_widget, low_limits):
    w1 = make_widget(title="A")
    w2 = make_widget(title="B")

    def _post(widget_id, token, ip="10.99.0.1"):
        return client.post(
            "/submissions",
            headers={"x-forwarded-for": ip},
            json={
                "widget_id": widget_id,
                "client_token": token,
                "data": {"name": "Ada", "email": "ada@example.com", "topic": "A"},
            },
        )

    # Budget is 3/min per IP and per widget. First three fly through.
    for i in range(3):
        assert _post(w1["id"], f"t{i}").status_code in (200, 201)

    # The flood gets 429 with a Retry-After header…
    res = _post(w1["id"], "t-burst")
    assert res.status_code == 429
    assert res.headers.get("retry-after")
    # …and the wrapped detail explains the limit
    assert "Rate limit" in res.json()["detail"]

    # Legit traffic to a different widget/IP still succeeds — the API stayed up.
    ok = _post(w2["id"], "t-ok", ip="10.99.0.2")
    assert ok.status_code == 201
    assert ok.json()["stored"] is True


def test_per_widget_limit_is_independent_of_ip(client, auth, make_widget, low_limits):
    w = make_widget()

    def _post(ip):
        return client.post(
            "/submissions",
            headers={"x-forwarded-for": ip},
            json={
                "widget_id": w["id"],
                "client_token": "tok-" + ip.replace(".", ""),
                "data": {"name": "Ada", "email": "ada@example.com", "topic": "A"},
            },
        )

    assert _post("10.1.0.1").status_code in (200, 201)
    assert _post("10.1.0.2").status_code in (200, 201)
    assert _post("10.1.0.3").status_code in (200, 201)
    # widget budget exhausted even from a brand-new IP
    assert _post("10.1.0.4").status_code == 429


def test_register_and_management_are_not_rate_limited(client):
    # management/auth traffic is untouched by the submission limiter
    for i in range(6):
        res = client.post(
            "/api/auth/register",
            json={"name": "X", "email": f"u{i}@test.dev", "password": "password-123"},
        )
        assert res.status_code == 201
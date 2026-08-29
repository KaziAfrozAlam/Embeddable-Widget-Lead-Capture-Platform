"""Public submission endpoint: validation, status codes, idempotency, honeypot."""


def _valid_payload(widget_id, **overrides):
    payload = {
        "widget_id": widget_id,
        "client_token": "tok-abc",
        "data": {"name": "Ada", "email": "ada@example.com", "topic": "A"},
    }
    payload.update(overrides)
    return payload


def test_valid_cross_origin_submission_is_stored(client, make_widget, owner):
    widget = make_widget()
    res = client.post(
        "/submissions",
        headers={"Origin": "http://customer.example", "x-forwarded-for": "8.8.8.8"},
        json=_valid_payload(widget["id"]),
    )
    assert res.status_code == 201
    body = res.json()
    assert body["accepted"] is True
    assert body["stored"] is True
    assert body["created"] is True
    assert body["id"]

    # enriched with geo in mock mode
    subs = client.get("/api/dashboard/submissions", headers=_auth(owner)).json()
    assert subs["total"] == 1
    row = subs["items"][0]
    assert row["widget_id"] == widget["id"]
    assert row["geo_country"] == "US"
    assert row["geo_provider"] == "ip-api"  # provider A answered


def _auth(owner):
    return {"Authorization": "Bearer " + owner["access_token"]}


def test_unknown_widget_404(client, owner):
    res = client.post(
        "/submissions",
        headers=_auth(owner),
        json=_valid_payload("no-such-widget"),
    )
    assert res.status_code == 404


def test_malformed_json_returns_400(client):
    res = client.post(
        "/submissions",
        content=b'{ "this is": not json ',
        headers={"Content-Type": "application/json", "Origin": "http://customer.example"},
    )
    assert res.status_code == 400
    assert isinstance(res.json()["detail"], str)


def test_oversized_payload_returns_413(client, make_widget):
    from app.config import get_settings

    widget = make_widget()
    limit = get_settings().max_payload_bytes
    name = "x" * limit
    body = '{{"widget_id":"{wid}","data":{{"name":"{name}"}}}}'.format(wid=widget["id"], name=name)
    res = client.post(
        "/submissions",
        content=body.encode(),
        headers={"Content-Type": "application/json", "Origin": "http://customer.example"},
    )
    assert res.status_code == 413
    assert "too large" in res.json()["detail"].lower()


def test_invalid_fields_return_clean_4xx(client, make_widget):
    widget = make_widget()

    cases = [
        _valid_payload(widget["id"], data={"unknown_field": "boom"}),  # unknown field
        _valid_payload(widget["id"], data={"email": "ada@example.com"}),  # missing required name
        _valid_payload(widget["id"], data={"name": "x", "email": "not-an-email", "topic": "A"}),  # bad email
        _valid_payload(widget["id"], data={"name": "x", "email": "a@b.dev", "topic": "ZZZ"}),  # bad option
        _valid_payload(widget["id"], data={"name": "x" * 2000, "email": "a@b.dev", "topic": "A"}),  # value too long
        _valid_payload(widget["id"], client_token="", data={}),  # empty data
    ]
    for body in cases:
        res = client.post(
            "/submissions",
            headers={"Origin": "http://customer.example"},
            json=body,
        )
        assert 400 <= res.status_code < 500, f"{res.status_code} for {body}"
        # never 500, always JSON with a detail
        assert "detail" in res.json()


def test_idempotent_replay_returns_same_row(client, make_widget):
    widget = make_widget()
    first = client.post(
        "/submissions",
        headers={"Origin": "http://customer.example"},
        json=_valid_payload(widget["id"], client_token="idem-1"),
    )
    second = client.post(
        "/submissions",
        headers={"Origin": "http://customer.example"},
        json=_valid_payload(widget["id"], client_token="idem-1"),
    )
    assert first.status_code == 201
    assert first.json()["created"] is True
    assert second.status_code == 200
    assert second.json()["created"] is False
    assert second.json()["idempotent"] is True
    assert second.json()["id"] == first.json()["id"]  # stored once


def test_no_duplicate_rows_from_retry(client, make_widget, owner):
    widget = make_widget()
    for _ in range(2):
        client.post(
            "/submissions",
            headers={"Origin": "http://customer.example"},
            json=_valid_payload(widget["id"], client_token="idem-2"),
        )
    total = client.get("/api/dashboard/submissions", headers=_auth(owner)).json()["total"]
    assert total == 1


def test_concurrent_duplicate_token_reconciles_after_integrity_error(
    client, make_widget, owner, monkeypatch
):
    """Two requests with the same token race: the loser's INSERT trips
    UNIQUE(widget_id, client_token) and must reconcile to the winner's row --
    not crash with a 500."""
    from app import models
    from app.api import public as public_api
    from app.db import SessionLocal

    widget = make_widget()

    # The "winner" row exists, but the loser's pre-check does not see it -- the
    # exact race window. Pre-create it directly, as a concurrent request would.
    with SessionLocal() as db:
        winner = models.Submission(
            widget_id=widget["id"],
            owner_id=owner["owner"]["id"],
            client_token="race-1",
            data={"name": "Winner", "email": "w@example.com", "topic": "A"},
            ip="203.0.113.9",
        )
        db.add(winner)
        db.commit()
        winner_id = winner.id

    real_lookup = public_api._find_by_token
    calls = {"n": 0}

    def _precheck_blind(db_session, widget_id, client_token):
        """Blind only on the first call (the pre-check); reconcile later."""
        calls["n"] += 1
        if calls["n"] == 1:
            return None
        return real_lookup(db_session, widget_id, client_token)

    monkeypatch.setattr(public_api, "_find_by_token", _precheck_blind)

    res = client.post(
        "/submissions",
        headers={"Origin": "http://customer.example"},
        json={
            "widget_id": widget["id"],
            "client_token": "race-1",
            "data": {"name": "Also Ada", "email": "ada@example.com", "topic": "A"},
        },
    )
    assert res.status_code == 200
    body = res.json()
    assert body["idempotent"] is True
    assert body["id"] == winner_id
    # exactly one row was stored
    total = client.get("/api/dashboard/submissions", headers=_auth(owner)).json()["total"]
    assert total == 1


def test_honeypot_spam_is_silently_dropped(client, make_widget, owner):
    widget = make_widget()
    honeypot = "hp_" + widget["id"][:8]

    # bot fills the honeypot along with a payload that would otherwise pass
    data = {"name": "Spammy", "email": "spam@bot.dev", "topic": "A", honeypot: "https://spam.example"}
    res = client.post(
        "/submissions",
        headers={"Origin": "http://customer.example"},
        json=_valid_payload(widget["id"], client_token="bot-1", data=data),
    )
    # accepted-looking response…
    assert res.status_code == 200
    assert res.json()["accepted"] is True
    assert res.json()["stored"] is False
    # …but nothing was persisted
    assert client.get("/api/dashboard/submissions", headers=_auth(owner)).json()["total"] == 0

    # a legitimate visitor (honeypot empty, same widget) still succeeds
    ok = client.post(
        "/submissions",
        headers={"Origin": "http://customer.example"},
        json=_valid_payload(widget["id"], client_token="legit-1"),
    )
    assert ok.status_code == 201
    assert client.get("/api/dashboard/submissions", headers=_auth(owner)).json()["total"] == 1


def test_submission_linked_to_right_owner_tenant_isolation(client, make_widget, second_owner):
    widget_a = make_widget()
    client.post(
        "/submissions",
        headers={"Origin": "http://customer.example"},
        json=_valid_payload(widget_a["id"], client_token="tok-a"),
    )
    headers_b = {"Authorization": "Bearer " + second_owner["token"]}
    # tenant B cannot even list A's submissions via A's widget
    assert client.get(
        f"/api/dashboard/submissions?widget_id={widget_a['id']}", headers=headers_b
    ).status_code == 404
    # and B's unfiltered list lacks A's submission
    assert client.get("/api/dashboard/submissions", headers=headers_b).json()["total"] == 0
"""Side-effect worker: email jobs are queued, retried, and fail cleanly."""

import pytest

from app.db import SessionLocal
from app.models import Job
from app.services import worker as worker_mod
from app.services.worker import worker_poll_once


@pytest.fixture()
def zero_backoff(monkeypatch):
    """Make retries immediate so tests don't wait out the real backoff."""

    def _fast(attempt):
        return 0.0

    monkeypatch.setattr(worker_mod, "_backoff", _fast)


def _set_mail_mode(monkeypatch, settings, mode):
    monkeypatch.setattr(settings, "mail_mode", mode)


def test_email_job_queued_after_submission(client, make_widget, settings, monkeypatch):
    _set_mail_mode(monkeypatch, settings, "console")
    widget = make_widget()
    res = client.post(
        "/submissions",
        headers={"x-forwarded-for": "8.8.8.8"},
        json={
            "widget_id": widget["id"],
            "client_token": "email-tok-1",
            "data": {"name": "Ada", "email": "ada@example.com", "topic": "A"},
        },
    )
    assert res.status_code == 201
    with SessionLocal() as db:
        jobs = db.query(Job).all()
    assert any(j.kind == "email" and j.status == "pending" for j in jobs)


def test_worker_drains_email_job_successfully(client, make_widget, settings, monkeypatch):
    _set_mail_mode(monkeypatch, settings, "console")
    widget = make_widget()
    client.post(
        "/submissions",
        headers={"x-forwarded-for": "8.8.8.8"},
        json={
            "widget_id": widget["id"],
            "client_token": "email-drain",
            "data": {"name": "Ada", "email": "ada@example.com"},
        },
    )
    processed = worker_poll_once(max_jobs=10)
    assert processed >= 1
    with SessionLocal() as db:
        jobs = db.query(Job).all()
    assert all(j.status == "done" for j in jobs)


def test_failing_mailer_retries_then_fails(
    client, make_widget, settings, monkeypatch, zero_backoff
):
    _set_mail_mode(monkeypatch, settings, "fail")  # always raises
    monkeypatch.setattr(settings, "worker_max_attempts", 3)
    widget = make_widget()
    client.post(
        "/submissions",
        headers={"x-forwarded-for": "8.8.8.8"},
        json={
            "widget_id": widget["id"],
            "client_token": "email-fail-1",
            "data": {"name": "Ada", "email": "ada@example.com"},
        },
    )
    # Each poll retries (backoff zeroed): 1→attempts=1, 2→attempts=2, 3→attempts=3, failed
    for _ in range(3):
        worker_poll_once(max_jobs=1)
    with SessionLocal() as db:
        job = db.query(Job).first()
    assert job.status == "failed"
    assert job.attempts >= 3
    assert job.last_error


def test_failing_side_effect_never_blocks_submission(client, make_widget):
    """Submission returns 201 even when the enqueue itself fails."""
    from app.services import sideeffects

    original = sideeffects.enqueue_after_submit

    def _bomb(*a, **kw):
        raise RuntimeError("enqueue exploded")

    sideeffects.enqueue_after_submit = _bomb
    try:
        widget = make_widget()
        res = client.post(
            "/submissions",
            headers={"x-forwarded-for": "8.8.8.8"},
            json={
                "widget_id": widget["id"],
                "client_token": "enqueue-fail",
                "data": {"name": "Ada", "email": "ada@example.com"},
            },
        )
        assert res.status_code == 201  # main path succeeds regardless
    finally:
        sideeffects.enqueue_after_submit = original


def test_retry_then_success(client, make_widget, settings, monkeypatch, zero_backoff):
    """Job fails once, succeeds on the next poll."""
    _set_mail_mode(monkeypatch, settings, "fail")
    widget = make_widget()
    client.post(
        "/submissions",
        headers={"x-forwarded-for": "8.8.8.8"},
        json={
            "widget_id": widget["id"],
            "client_token": "retry-ok",
            "data": {"name": "Ada", "email": "ada@example.com"},
        },
    )
    worker_poll_once(max_jobs=1)
    with SessionLocal() as db:
        job = db.query(Job).first()
    assert job.status == "pending"
    assert job.attempts == 1

    # the mailer is fixed — next poll succeeds
    _set_mail_mode(monkeypatch, settings, "console")
    worker_poll_once(max_jobs=1)
    with SessionLocal() as db:
        job = db.query(Job).first()
    assert job.status == "done"
"""Enqueues non-critical side effects AFTER the submission is committed.

The submission path never depends on these succeeding: if the enqueue itself
fails we log and move on — the main response was already written."""

import logging

from sqlalchemy.orm import Session

from ..config import get_settings
from ..models import Job, Submission, Widget
from .mailer import render_confirmation

logger = logging.getLogger("capstone.sideeffects")


def _find_recipient(widget: Widget, data: dict) -> str | None:
    for field in widget.fields:
        if field.get("type") == "email":
            value = (data.get(field.get("name")) or "").strip()
            if value:
                return value
    return None


def enqueue_after_submit(db: Session, submission: Submission, widget: Widget) -> None:
    """Create email + webhook jobs post-commit. Never raises."""
    settings = get_settings()
    try:
        desired = []
        recipient = _find_recipient(widget, submission.data)
        if recipient:
            subject, body = render_confirmation(recipient, widget.title, widget.type)
            desired.append(
                Job(
                    kind="email",
                    payload={
                        "to": recipient,
                        "subject": subject,
                        "body": body,
                        "submission_id": submission.id,
                        "widget_id": widget.id,
                    },
                    max_attempts=settings.worker_max_attempts,
                )
            )
        if settings.webhook_url:
            desired.append(
                Job(
                    kind="webhook",
                    payload={
                        "url": settings.webhook_url,
                        "event": "submission.created",
                        "submission_id": submission.id,
                        "widget_id": widget.id,
                        "owner_id": submission.owner_id,
                    },
                    max_attempts=settings.worker_max_attempts,
                )
            )
        if desired:
            db.add_all(desired)
            db.commit()
    except Exception as exc:  # side effects are non-critical
        logger.warning("failed to enqueue side-effect jobs: %s", exc)
        db.rollback()
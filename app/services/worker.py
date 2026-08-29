"""Background worker: drains the jobs table.

Side effects (email / webhook) are enqueued AFTER the submission commit so a
failure can never roll back the main path. The worker retries with backoff and
emits an ALERT when a job exhausts its attempts.

Run standalone:  python -m app.services.worker
"""

import time
from datetime import timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..config import get_settings
from ..db import SessionLocal
from ..models import (
    JOB_STATUS_DONE,
    JOB_STATUS_FAILED,
    JOB_STATUS_PENDING,
    JOB_STATUS_PROCESSING,
    Job,
    utcnow,
)
from .mailer import send_email
from .webhook import send_webhook

BACKOFF_BASE_SECONDS = 2.0


def _backoff(attempt: int) -> float:
    return BACKOFF_BASE_SECONDS * (2 ** (attempt - 1))


def run_job(job: Job) -> None:
    if job.kind == "email":
        send_email(job.payload["to"], job.payload["subject"], job.payload["body"])
    elif job.kind == "webhook":
        send_webhook(job.payload)
    else:
        raise RuntimeError(f"unknown job kind: {job.kind}")


def _claim_next(db: Session) -> Job | None:
    now = utcnow()
    stmt = (
        select(Job)
        .where(
            Job.status == JOB_STATUS_PENDING,
            (Job.next_run_at.is_(None)) | (Job.next_run_at <= now),
        )
        .order_by(Job.created_at.asc())
        .limit(1)
    )
    job = db.execute(stmt).scalar_one_or_none()
    if job is None:
        return None
    job.status = JOB_STATUS_PROCESSING
    job.updated_at = utcnow()
    db.commit()
    return job


def worker_poll_once(session_factory=SessionLocal, max_jobs: int = 10) -> int:
    """Process up to `max_jobs` due jobs; returns the number attempted."""
    processed = 0
    for _ in range(max_jobs):
        db = session_factory()
        try:
            job = _claim_next(db)
            if job is None:
                return processed
            processed += 1
            try:
                run_job(job)
                job.status = JOB_STATUS_DONE
                job.last_error = None
            except Exception as exc:  # side effect failed — retry / alert
                job.attempts += 1
                job.last_error = f"{type(exc).__name__}: {exc}"
                if job.attempts >= job.max_attempts:
                    job.status = JOB_STATUS_FAILED
                    print(
                        f"ALERT [job {job.id}] {job.kind} failed after "
                        f"{job.attempts} attempts: {job.last_error}"
                    )
                else:
                    job.status = JOB_STATUS_PENDING
                    job.next_run_at = utcnow() + timedelta(seconds=_backoff(job.attempts))
                job.updated_at = utcnow()
            db.commit()
        finally:
            db.close()
    return processed


def run_forever() -> None:
    settings = get_settings()
    print(f"[worker] started, polling every {settings.worker_poll_seconds}s")
    while True:
        try:
            done = worker_poll_once()
        except Exception as exc:  # don't kill the loop on a DB hiccup
            print(f"[worker] poll error: {exc}")
            done = 0
        if done == 0:
            time.sleep(settings.worker_poll_seconds)


if __name__ == "__main__":
    run_forever()
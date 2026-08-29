"""SQLAlchemy models: Owner (tenant), Widget, Submission, Job (background queue)."""

from datetime import datetime, timezone
from uuid import uuid4

from sqlalchemy import (
    JSON,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .db import Base

# Widget types supported by the model. The renderer has explicit branches for
# inline (signup/contact) vs floating (cta/popover).
WIDGET_TYPES = ("signup", "contact", "cta", "popover")

FIELD_TYPES = ("text", "email", "phone", "textarea", "select")

JOB_OK = ("pending",)
JOB_STATUS_PENDING = "pending"
JOB_STATUS_PROCESSING = "processing"
JOB_STATUS_DONE = "done"
JOB_STATUS_FAILED = "failed"


def new_id() -> str:
    return str(uuid4())


def utcnow() -> datetime:
    """Naive UTC timestamp, portable across SQLite and Postgres."""
    return datetime.now(timezone.utc).replace(tzinfo=None)


class Owner(Base):
    __tablename__ = "owners"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    email: Mapped[str] = mapped_column(String(255), unique=True, index=True, nullable=False)
    name: Mapped[str] = mapped_column(String(120), nullable=False)
    password_hash: Mapped[str] = mapped_column(String(255), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, nullable=False)

    widgets: Mapped[list["Widget"]] = relationship(
        back_populates="owner", cascade="all, delete-orphan"
    )


class Widget(Base):
    __tablename__ = "widgets"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    owner_id: Mapped[str] = mapped_column(
        ForeignKey("owners.id", ondelete="CASCADE"), index=True, nullable=False
    )
    type: Mapped[str] = mapped_column(String(20), nullable=False)
    title: Mapped[str] = mapped_column(String(120), nullable=False)
    description: Mapped[str | None] = mapped_column(String(500), nullable=True)
    fields: Mapped[list] = mapped_column(JSON, nullable=False, default=list)
    button_text: Mapped[str] = mapped_column(String(60), default="Submit")
    styles: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, default=utcnow, onupdate=utcnow, nullable=False
    )

    owner: Mapped["Owner"] = relationship(back_populates="widgets")
    submissions: Mapped[list["Submission"]] = relationship(
        back_populates="widget", cascade="all, delete-orphan"
    )


class Submission(Base):
    __tablename__ = "submissions"
    __table_args__ = (
        # Idempotency: the same client_token for the same widget is stored once.
        UniqueConstraint("widget_id", "client_token", name="uq_submissions_widget_client_token"),
        Index("ix_submissions_owner_created", "owner_id", "created_at"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    widget_id: Mapped[str] = mapped_column(
        ForeignKey("widgets.id", ondelete="CASCADE"), index=True, nullable=False
    )
    owner_id: Mapped[str] = mapped_column(
        ForeignKey("owners.id", ondelete="CASCADE"), index=True, nullable=False
    )
    client_token: Mapped[str | None] = mapped_column(String(64), nullable=True)
    data: Mapped[dict] = mapped_column(JSON, nullable=False)
    ip: Mapped[str | None] = mapped_column(String(64), nullable=True)
    geo_country: Mapped[str | None] = mapped_column(String(10), nullable=True)
    geo_city: Mapped[str | None] = mapped_column(String(120), nullable=True)
    geo_provider: Mapped[str | None] = mapped_column(String(40), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, nullable=False)

    widget: Mapped["Widget"] = relationship(back_populates="submissions")


class Job(Base):
    """Background job queue row. Side effects (email/webhook) run off the
    request path with retries; hard failures raise an alert (log)."""

    __tablename__ = "jobs"
    __table_args__ = (Index("ix_jobs_pending_due", "status", "next_run_at"),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    kind: Mapped[str] = mapped_column(String(20), nullable=False)  # email | webhook
    payload: Mapped[dict] = mapped_column(JSON, nullable=False)
    status: Mapped[str] = mapped_column(
        String(20), default=JOB_STATUS_PENDING, nullable=False
    )
    attempts: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    max_attempts: Mapped[int] = mapped_column(Integer, default=3, nullable=False)
    next_run_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    last_error: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, default=utcnow, onupdate=utcnow, nullable=False
    )
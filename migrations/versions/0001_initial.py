"""initial schema: owners, widgets, submissions, jobs

Revision ID: 0001_initial
Revises:
Create Date: 2026-08-28
"""
from alembic import op
import sqlalchemy as sa

revision = "0001_initial"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "owners",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("email", sa.String(255), nullable=False),
        sa.Column("name", sa.String(120), nullable=False),
        sa.Column("password_hash", sa.String(255), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.UniqueConstraint("email", name="uq_owners_email"),
    )
    op.create_index("ix_owners_email", "owners", ["email"])

    op.create_table(
        "widgets",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("owner_id", sa.String(36), nullable=False),
        sa.Column("type", sa.String(20), nullable=False),
        sa.Column("title", sa.String(120), nullable=False),
        sa.Column("description", sa.String(500), nullable=True),
        sa.Column("fields", sa.JSON(), nullable=False),
        sa.Column("button_text", sa.String(60), nullable=False),
        sa.Column("styles", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["owner_id"], ["owners.id"], ondelete="CASCADE"),
    )
    op.create_index("ix_widgets_owner_id", "widgets", ["owner_id"])

    op.create_table(
        "submissions",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("widget_id", sa.String(36), nullable=False),
        sa.Column("owner_id", sa.String(36), nullable=False),
        sa.Column("client_token", sa.String(64), nullable=True),
        sa.Column("data", sa.JSON(), nullable=False),
        sa.Column("ip", sa.String(64), nullable=True),
        sa.Column("geo_country", sa.String(10), nullable=True),
        sa.Column("geo_city", sa.String(120), nullable=True),
        sa.Column("geo_provider", sa.String(40), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["widget_id"], ["widgets.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["owner_id"], ["owners.id"], ondelete="CASCADE"),
        sa.UniqueConstraint(
            "widget_id", "client_token", name="uq_submissions_widget_client_token"
        ),
    )
    op.create_index("ix_submissions_widget_id", "submissions", ["widget_id"])
    op.create_index("ix_submissions_owner_id", "submissions", ["owner_id"])
    op.create_index("ix_submissions_owner_created", "submissions", ["owner_id", "created_at"])

    op.create_table(
        "jobs",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("kind", sa.String(20), nullable=False),
        sa.Column("payload", sa.JSON(), nullable=False),
        sa.Column("status", sa.String(20), nullable=False),
        sa.Column("attempts", sa.Integer(), nullable=False),
        sa.Column("max_attempts", sa.Integer(), nullable=False),
        sa.Column("next_run_at", sa.DateTime(), nullable=True),
        sa.Column("last_error", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
    )
    op.create_index("ix_jobs_pending_due", "jobs", ["status", "next_run_at"])


def downgrade() -> None:
    op.drop_table("jobs")
    op.drop_table("submissions")
    op.drop_table("widgets")
    op.drop_table("owners")
"""Seed script — demo tenant + widgets + sample submissions.

Run after migrating:
    python -m app.seed
"""

import json
import sys
from pathlib import Path

from sqlalchemy import select

from .config import get_settings
from .db import SessionLocal
from .models import Owner, Submission, Widget
from .security import hash_password

DEMO_EMAIL = "demo@example.com"
DEMO_PASSWORD = "demo-pass-123"


def seed(wipe: bool = False) -> None:
    db = SessionLocal()
    try:
        existing = db.scalar(select(Owner).where(Owner.email == DEMO_EMAIL))
        if existing is not None and not wipe:
            print(f"[seed] demo owner already exists ({DEMO_EMAIL}) — nothing to do.")
            _write_harness_widget(db, existing)
            _print_snippet(db, existing)
            return
        if existing is not None and wipe:
            db.query(Submission).delete()
            db.query(Owner).delete()
        elif wipe:
            db.query(Submission).delete()

        owner = Owner(
            email=DEMO_EMAIL,
            name="Demo Widgets Inc.",
            password_hash=hash_password(DEMO_PASSWORD),
        )
        db.add(owner)
        db.flush()

        signup = Widget(
            owner_id=owner.id,
            type="signup",
            title="Newsletter signup",
            description="Join the newsletter and get a free guide.",
            fields=[
                {"name": "name", "label": "Full name", "type": "text", "required": True},
                {"name": "email", "label": "Email", "type": "email", "required": True},
            ],
            button_text="Subscribe",
            styles={"accent_color": "#2563eb"},
        )
        contact = Widget(
            owner_id=owner.id,
            type="contact",
            title="Contact us",
            description="Tell us what you need — we reply within a day.",
            fields=[
                {"name": "name", "label": "Full name", "type": "text", "required": True},
                {"name": "email", "label": "Email", "type": "email", "required": True},
                {
                    "name": "topic",
                    "label": "Topic",
                    "type": "select",
                    "required": True,
                    "options": ["Sales", "Support", "Partnership"],
                },
                {"name": "message", "label": "Message", "type": "textarea", "required": True},
            ],
            button_text="Send message",
            styles={"accent_color": "#0f766e"},
        )
        cta = Widget(
            owner_id=owner.id,
            type="cta",
            title="Book a demo",
            description="See the platform in action.",
            fields=[
                {"name": "email", "label": "Work email", "type": "email", "required": True},
            ],
            button_text="Book a demo",
            styles={"accent_color": "#9333ea"},
        )
        db.add_all([signup, contact, cta])
        db.flush()

        samples = [
            (signup, "US", "Mountain View"),
            (signup, "DE", "Berlin"),
            (signup, None, None),
            (contact, "AU", "Sydney"),
            (cta, "FR", "Paris"),
        ]
        for widget, country, city in samples:
            db.add(
                Submission(
                    widget_id=widget.id,
                    owner_id=owner.id,
                    data={
                        "name": "Seed Visitor",
                        "email": "seed@example.com",
                    },
                    ip="8.8.8.8",
                    geo_country=country,
                    geo_city=city,
                    geo_provider="seed",
                )
            )
        db.commit()
        print(f"[seed] created demo owner: {DEMO_EMAIL} / {DEMO_PASSWORD}")
        _write_harness_widget(db, owner)
        _print_snippet(db, owner)
    finally:
        db.close()


def _write_harness_widget(db, owner) -> None:
    """Publish demo widget ids for the customer-site.html harness so it can
    load live widgets without needing cross-origin admin login."""
    try:
        widgets = db.scalars(select(Widget).where(Widget.owner_id == owner.id).order_by(Widget.created_at)).all()
        if not widgets:
            return
        cta = next((w for w in widgets if w.type == "cta"), None)
        target = Path(__file__).resolve().parent.parent / "website" / "_widgets.json"
        target.write_text(
            json.dumps(
                {
                    "widget_id": str(widgets[0].id),
                    "cta_widget_id": str(cta.id) if cta else None,
                }
            ),
            encoding="utf-8",
        )
        print(f"[seed] wrote {target.name} -> {widgets[0].id}")
    except Exception as exc:  # harness marker is non-critical
        print(f"[seed] warn: could not write harness widget file: {exc}")


def _print_snippet(db, owner) -> None:
    from .version import WIDGET_SCRIPT_VERSION

    settings = get_settings()
    widgets = db.scalars(select(Widget).where(Widget.owner_id == owner.id)).all()
    for w in widgets:
        script_url = (
            f"{settings.api_base_url}/embed/{WIDGET_SCRIPT_VERSION}/widget.js?id={w.id}"
        )
        print(f"[seed] widget '{w.title}' ({w.type}) id={w.id}")
        print(f"[seed]   snippet: <script src=\"{script_url}\" async defer></script>")
    print("[seed] done.")


if __name__ == "__main__":
    wipe = "--wipe" in sys.argv
    seed(wipe=wipe)
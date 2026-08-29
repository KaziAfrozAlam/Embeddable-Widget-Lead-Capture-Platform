"""Email delivery abstraction. Failure is ALWAYS surfaced as an exception so the
caller (background worker) can retry — and so tests can prove a failing mailer
never blocks the submission path."""

import smtplib
import sys
from email.message import EmailMessage

from ..config import get_settings


def render_confirmation(to: str, widget_title: str, widget_type: str) -> tuple[str, str]:
    subject = f"Thanks — we received your {widget_type} submission"
    body = (
        f"Hi,\n\n"
        f"We received your submission for \"{widget_title}\".\n"
        f"A human will get back to you shortly.\n\n"
        f"— Lead-Capture Platform (demo)"
    )
    return subject, body


def send_email(to: str, subject: str, body: str) -> None:
    settings = get_settings()
    mode = settings.mail_mode

    if mode == "fail":
        raise RuntimeError("MAIL_MODE=fail — failing email delivery on purpose")

    if mode == "stderr":
        print(f"[MAIL] to={to} subject={subject}\n{body}", file=sys.stderr)
        return

    if mode == "smtp":
        msg = EmailMessage()
        msg["Subject"] = subject
        msg["From"] = settings.mail_from
        msg["To"] = to
        msg.set_content(body)
        with smtplib.SMTP(settings.smtp_host, settings.smtp_port, timeout=5) as smtp:
            if settings.smtp_user:
                smtp.login(settings.smtp_user, settings.smtp_password)
            smtp.send_message(msg)
        return

    # default: console
    print(f"[MAIL] to={to} subject={subject}")
    print(body)
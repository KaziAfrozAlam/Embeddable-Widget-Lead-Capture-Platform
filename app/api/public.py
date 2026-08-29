"""Public endpoints — the parts the open internet actually touches.

1. GET /widgets/{id}/config  — small payload, cache headers + ETag/304
2. GET /embed/{version}/widget.js — versioned, immutable, cacheable bundle
3. GET /widget.js           — unversioned alias (short cache)
4. POST /submissions        — CORS + preflight, boundary validation, rate
                              limiting, honeypot spam control, geo enrichment,
                              idempotency, safe queued side effects.
"""

import hashlib
import json

from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from ..config import get_settings
from ..db import get_db
from ..models import Submission, Widget
from ..rate_limit import FixedWindowLimiter, client_ip
from ..schemas import PublicWidgetConfig, SubmissionCreated, SubmissionIn
from ..services import geo
from ..services.sideeffects import enqueue_after_submit

router = APIRouter(tags=["public"])

settings = get_settings()

_limiter_ip = FixedWindowLimiter(settings.rate_limit_ip_max, settings.rate_limit_ip_window_seconds)
_limiter_widget = FixedWindowLimiter(
    settings.rate_limit_widget_max, settings.rate_limit_widget_window_seconds
)


def honeypot_field(widget_id: str) -> str:
    return "hp_" + widget_id[:8]


def _find_by_token(db: Session, widget_id: str, client_token: str) -> Submission | None:
    """The single source of truth for the idempotency lookup (pre-check and
    post-IntegrityError reconcile use the same query)."""
    return db.scalar(
        select(Submission).where(
            Submission.widget_id == widget_id,
            Submission.client_token == client_token,
        )
    )


def _config_dict(widget: Widget) -> dict:
    return {
        "id": widget.id,
        "type": widget.type,
        "title": widget.title,
        "description": widget.description,
        "fields": widget.fields,
        "honeypot_field": honeypot_field(widget.id),
        "button_text": widget.button_text,
        "styles": widget.styles,
        "api_base_url": settings.api_base_url,
        "mode": "popover" if widget.type == "cta" else "inline",
        "locale": (widget.styles or {}).get("locale", "en"),
    }


@router.get("/widgets/{widget_id}/config", response_model=PublicWidgetConfig)
def get_config(widget_id: str, request: Request, db: Session = Depends(get_db)) -> Response:
    widget = db.get(Widget, widget_id)
    if widget is None:
        raise HTTPException(status_code=404, detail="widget not found")

    body = json.dumps(_config_dict(widget), separators=(",", ":"), ensure_ascii=False)
    etag = '"' + hashlib.sha1(body.encode("utf-8")).hexdigest() + '"'
    headers = {
        "Cache-Control": "public, max-age=300",
        "ETag": etag,
        "Content-Type": "application/json; charset=utf-8",
    }
    if request.headers.get("if-none-match") == etag:
        return Response(status_code=304, headers=headers)
    return Response(content=body, headers=headers)


@router.get("/embed/{version}/widget.js")
def get_immutable_bundle(version: str) -> Response:
    from pathlib import Path

    from ..version import WIDGET_SCRIPT_VERSION

    if version != WIDGET_SCRIPT_VERSION:
        raise HTTPException(status_code=404, detail="unknown widget script version")
    path = Path(__file__).resolve().parent.parent / "renderer" / "widget.js"
    return Response(
        content=path.read_bytes(),
        media_type="application/javascript; charset=utf-8",
        headers={
            "Cache-Control": "public, max-age=31536000, immutable",
            "Vary": "Accept-Encoding",
        },
    )


@router.get("/widget.js")
def get_alias_bundle() -> Response:
    from pathlib import Path

    path = Path(__file__).resolve().parent.parent / "renderer" / "widget.js"
    return Response(
        content=path.read_bytes(),
        media_type="application/javascript; charset=utf-8",
        headers={"Cache-Control": "public, max-age=60"},
    )


def _validate_submission_data(widget: Widget, data: dict) -> None:
    """Reject unknown, missing-required, and type-invalid fields with a clean 422."""
    config_by_name = {f["name"]: f for f in widget.fields}
    errors: list[str] = []
    for name in data:
        if name not in config_by_name:
            errors.append(f"unknown field: {name}")
    for field in widget.fields:
        name = field["name"]
        value = (data.get(name) or "").strip()
        if field.get("required") and not value:
            errors.append(f"field {name} is required")
            continue
        if not value:
            continue
        if field["type"] == "email" and ("@" not in value or "." not in value.rsplit("@", 1)[-1]):
            errors.append(f"field {name} must be a valid email")
        if field["type"] == "select" and value and value not in (field.get("options") or []):
            errors.append(f"field {name} has an invalid option")
    if errors:
        raise HTTPException(status_code=422, detail=errors)


@router.post("/submissions", response_model=SubmissionCreated)
def create_submission(
    payload: SubmissionIn,
    request: Request,
    response: Response,
    db: Session = Depends(get_db),
) -> SubmissionCreated:
    ip = client_ip(request)
    for limiter, key in ((_limiter_ip, ip), (_limiter_widget, payload.widget_id)):
        allowed, retry_after = limiter.allowed(key)
        if not allowed:
            raise HTTPException(
                status_code=429,
                detail=f"Rate limit exceeded. Retry in {retry_after}s.",
                headers={"Retry-After": str(retry_after)},
            )

    widget = db.get(Widget, payload.widget_id)
    if widget is None:
        raise HTTPException(status_code=404, detail="widget not found")

    # Spam control: a filled honeypot is silently dropped (accepted-looking,
    # nothing persisted) so bots think they succeeded.
    if payload.data.get(honeypot_field(widget.id)):
        return SubmissionCreated(id="", stored=False, created=False)

    _validate_submission_data(widget, payload.data)

    client_token = (payload.client_token or "").strip() or None
    if client_token:
        existing = _find_by_token(db, widget.id, client_token)
        if existing is not None:
            return SubmissionCreated(
                id=existing.id, stored=True, created=False, idempotent=True
            )

    location = geo.enrich(ip)
    submission = Submission(
        widget_id=widget.id,
        owner_id=widget.owner_id,
        client_token=client_token,
        data=payload.data,
        ip=ip,
        geo_country=location.country if location else None,
        geo_city=location.city if location else None,
        geo_provider=location.provider if location else None,
    )
    try:
        db.add(submission)
        db.commit()
        db.refresh(submission)
    except IntegrityError:
        # Two concurrent requests with the same token both passed the SELECT
        # above; only one INSERT wins the UNIQUE(widget_id, client_token).
        # Reconcile to the winner's row instead of crashing with a 500.
        db.rollback()
        existing = _find_by_token(db, widget.id, client_token)
        if existing is not None:
            return SubmissionCreated(
                id=existing.id, stored=True, created=False, idempotent=True
            )
        raise

    # Side effects are queued AFTER commit and never block the response.
    enqueue_after_submit(db, submission, widget)

    response.status_code = status.HTTP_201_CREATED
    return SubmissionCreated(id=submission.id, stored=True, created=True)
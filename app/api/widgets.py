"""Authenticated widget management CRUD + embed snippet generation.

Every query is scoped to the JWT owner: cross-tenant access is impossible.
"""

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..config import get_settings
from ..db import get_db
from ..deps import get_current_owner
from ..models import Owner, Widget
from ..schemas import EmbedOut, WidgetCreate, WidgetOut, WidgetUpdate
from ..version import WIDGET_SCRIPT_VERSION

router = APIRouter(prefix="/api/widgets", tags=["widgets"])


def _get_owned_widget(db: Session, owner: Owner, widget_id: str) -> Widget:
    widget = db.scalar(
        select(Widget).where(Widget.id == widget_id, Widget.owner_id == owner.id)
    )
    if widget is None:
        raise HTTPException(status_code=404, detail="widget not found")
    return widget


def _default_button(task: str) -> str:
    return "Get started" if task in ("cta", "popover") else "Submit"


@router.post("", response_model=WidgetOut, status_code=status.HTTP_201_CREATED)
def create_widget(
    payload: WidgetCreate,
    owner: Owner = Depends(get_current_owner),
    db: Session = Depends(get_db),
) -> Widget:
    widget = Widget(
        owner_id=owner.id,
        type=payload.type,
        title=payload.title,
        description=payload.description,
        fields=[f.model_dump() for f in payload.fields],
        button_text=payload.button_text or _default_button(payload.type),
        styles=payload.styles or {},
    )
    db.add(widget)
    db.commit()
    db.refresh(widget)
    return widget


@router.get("", response_model=list[WidgetOut])
def list_widgets(
    owner: Owner = Depends(get_current_owner),
    db: Session = Depends(get_db),
):
    return db.scalars(select(Widget).where(Widget.owner_id == owner.id)).all()


@router.get("/{widget_id}", response_model=WidgetOut)
def get_widget(
    widget_id: str,
    owner: Owner = Depends(get_current_owner),
    db: Session = Depends(get_db),
) -> Widget:
    return _get_owned_widget(db, owner, widget_id)


@router.patch("/{widget_id}", response_model=WidgetOut)
def update_widget(
    widget_id: str,
    payload: WidgetUpdate,
    owner: Owner = Depends(get_current_owner),
    db: Session = Depends(get_db),
) -> Widget:
    widget = _get_owned_widget(db, owner, widget_id)
    updates = payload.model_dump(exclude_unset=True)
    if "fields" in updates:
        if updates["fields"] is None:
            raise HTTPException(status_code=422, detail="fields cannot be null")
        updates["fields"] = [f.model_dump() for f in updates["fields"]]
    if "styles" in updates and updates["styles"] is None:
        updates["styles"] = {}
    if "button_text" in updates and updates["button_text"] is None:
        updates["button_text"] = _default_button(payload.type or widget.type)
    for key, value in updates.items():
        setattr(widget, key, value)
    db.commit()
    db.refresh(widget)
    return widget


@router.delete("/{widget_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_widget(
    widget_id: str,
    owner: Owner = Depends(get_current_owner),
    db: Session = Depends(get_db),
) -> None:
    widget = _get_owned_widget(db, owner, widget_id)
    db.delete(widget)
    db.commit()


@router.get("/{widget_id}/embed", response_model=EmbedOut)
def get_embed(
    widget_id: str,
    owner: Owner = Depends(get_current_owner),
    db: Session = Depends(get_db),
) -> EmbedOut:
    widget = _get_owned_widget(db, owner, widget_id)
    settings = get_settings()
    script_url = (
        f"{settings.api_base_url}/embed/{WIDGET_SCRIPT_VERSION}/widget.js?id={widget.id}"
    )
    snippet = f'<script src="{script_url}" async defer></script>'
    return EmbedOut(
        widget_id=widget.id,
        base_url=settings.api_base_url,
        script_url=script_url,
        snippet=snippet,
    )
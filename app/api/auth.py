"""Owner (tenant) registration, login, and session info."""

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from ..db import get_db
from ..deps import get_current_owner
from ..models import Owner
from ..schemas import LoginIn, OwnerOut, RegisterIn, TokenOut
from ..security import create_access_token, hash_password, verify_password

router = APIRouter(prefix="/api/auth", tags=["auth"])


def _token_payload(owner: Owner) -> TokenOut:
    access_token = create_access_token(owner.id, owner.email)
    return TokenOut(access_token=access_token, owner=OwnerOut.model_validate(owner))


def _owner_by_email(db: Session, email: str) -> Owner | None:
    return db.scalar(select(Owner).where(Owner.email == email))


@router.post("/register", response_model=TokenOut, status_code=status.HTTP_201_CREATED)
def register(payload: RegisterIn, db: Session = Depends(get_db)) -> TokenOut:
    existing = _owner_by_email(db, payload.email)
    if existing is not None:
        raise HTTPException(status_code=409, detail="email already registered")
    owner = Owner(
        email=payload.email,
        name=payload.name,
        password_hash=hash_password(payload.password),
    )
    try:
        db.add(owner)
        db.commit()
        db.refresh(owner)
    except IntegrityError:
        # Concurrent register with the same email won the UNIQUE constraint.
        db.rollback()
        raise HTTPException(status_code=409, detail="email already registered")
    return _token_payload(owner)


@router.post("/login", response_model=TokenOut)
def login(payload: LoginIn, db: Session = Depends(get_db)) -> TokenOut:
    owner = db.scalar(select(Owner).where(Owner.email == payload.email))
    if owner is None or not verify_password(payload.password, owner.password_hash):
        raise HTTPException(status_code=401, detail="invalid email or password")
    return _token_payload(owner)


@router.get("/me", response_model=OwnerOut)
def me(owner: Owner = Depends(get_current_owner)) -> OwnerOut:
    return OwnerOut.model_validate(owner)
"""Pydantic schemas — boundary validation for every request that touches the API."""

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field, field_validator, model_validator

EMAIL_RE = None  # simple str check used below (keeps deps minimal)

MAX_FIELDS = 12
MAX_DATA_KEYS = 50
MAX_FIELD_VALUE_LEN = 1000
MAX_PASSWORD_LEN = 128


def looks_like_email(value: str) -> bool:
    return "@" in value and 3 <= len(value) <= 254


# ------------------------------------------------------------------ auth


class RegisterIn(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    email: str = Field(min_length=3, max_length=254)
    password: str = Field(min_length=8, max_length=128)

    @field_validator("email")
    @classmethod
    def _valid_email(cls, v: str) -> str:
        if not looks_like_email(v):
            raise ValueError("invalid email address")
        return v.strip().lower()


class LoginIn(BaseModel):
    email: str = Field(min_length=3, max_length=254)
    password: str = Field(min_length=1, max_length=128)


class OwnerOut(BaseModel):
    id: str
    email: str
    name: str
    created_at: datetime

    model_config = {"from_attributes": True}


class TokenOut(BaseModel):
    access_token: str
    token_type: str = "bearer"
    owner: OwnerOut


# ------------------------------------------------------------- widgets


class WidgetField(BaseModel):
    name: str = Field(min_length=1, max_length=64, pattern=r"^[a-z0-9_]+$")
    label: str = Field(min_length=1, max_length=120)
    type: Literal["text", "email", "phone", "textarea", "select"] = "text"
    required: bool = False
    options: list[str] | None = Field(default=None, max_length=50)


class WidgetBase(BaseModel):
    type: Literal["signup", "contact", "cta", "popover"]
    title: str = Field(min_length=1, max_length=120)
    description: str | None = Field(default=None, max_length=500)
    fields: list[WidgetField] = Field(default_factory=list, max_length=MAX_FIELDS)
    button_text: str | None = Field(default=None, max_length=60)
    styles: dict | None = None

    @model_validator(mode="after")
    def _check_fields(self):
        names = [f.name for f in self.fields]
        if len(names) != len(set(names)):
            raise ValueError("field names must be unique")
        for f in self.fields:
            if f.type == "select" and (not f.options or not all(f.options)):
                raise ValueError(f'select field "{f.name}" needs non-empty options')
            if f.type != "select" and f.options:
                raise ValueError(f'options only allowed on select field "{f.name}"')
        return self


class WidgetCreate(WidgetBase):
    pass


class WidgetUpdate(BaseModel):
    type: Literal["signup", "contact", "cta", "popover"] | None = None
    title: str | None = Field(default=None, min_length=1, max_length=120)
    description: str | None = Field(default=None, max_length=500)
    fields: list[WidgetField] | None = Field(default=None, max_length=MAX_FIELDS)
    button_text: str | None = Field(default=None, max_length=60)
    styles: dict | None = None

    @model_validator(mode="after")
    def _check_fields(self):
        if self.fields is None:
            return self
        names = [f.name for f in self.fields]
        if len(names) != len(set(names)):
            raise ValueError("field names must be unique")
        for f in self.fields:
            if f.type == "select" and (not f.options or not all(f.options)):
                raise ValueError(f'select field "{f.name}" needs non-empty options')
            if f.type != "select" and f.options:
                raise ValueError(f'options only allowed on select field "{f.name}"')
        return self


class WidgetOut(BaseModel):
    id: str
    owner_id: str
    type: str
    title: str
    description: str | None
    fields: list[WidgetField]
    button_text: str
    styles: dict
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


class EmbedOut(BaseModel):
    widget_id: str
    base_url: str
    script_url: str
    snippet: str


# --------------------------------------------------- public widget API


class PublicWidgetConfig(BaseModel):
    id: str
    type: str
    title: str
    description: str | None
    fields: list[WidgetField]
    honeypot_field: str
    button_text: str
    styles: dict
    api_base_url: str
    mode: str
    locale: str


# --------------------------------------------------------- submissions


class SubmissionIn(BaseModel):
    widget_id: str
    client_token: str | None = Field(default=None, min_length=1, max_length=64)
    data: dict[str, str] = Field(default_factory=dict, max_length=MAX_DATA_KEYS)

    @field_validator("data")
    @classmethod
    def _check_data(cls, v: dict[str, str]) -> dict[str, str]:
        if not all(len(k) <= 64 for k in v):
            raise ValueError("field name too long")
        if not all(len(val) <= MAX_FIELD_VALUE_LEN for val in v.values()):
            raise ValueError(f"field value exceeds {MAX_FIELD_VALUE_LEN} chars")
        return v


class SubmissionCreated(BaseModel):
    id: str
    accepted: bool = True
    stored: bool
    created: bool
    idempotent: bool = False


class SubmissionOut(BaseModel):
    id: str
    widget_id: str
    data: dict
    ip: str | None
    geo_country: str | None
    geo_city: str | None
    geo_provider: str | None
    created_at: datetime

    model_config = {"from_attributes": True}


class SubmissionList(BaseModel):
    total: int
    page: int
    page_size: int
    items: list[SubmissionOut]


# ------------------------------------------------------------ dashboard


class StatsOut(BaseModel):
    total: int
    today: int
    last_7_days: int
    daily: list[dict]
    by_widget: list[dict]
    by_country: list[dict]
from __future__ import annotations

import re
import uuid
from datetime import datetime
from typing import Annotated, Any, Literal

from pydantic import AfterValidator, BaseModel, ConfigDict, Field

EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
KEY_RE = re.compile(r"^[a-z0-9][a-z0-9_-]{0,99}$")
RoleName = Literal["reader", "writer", "admin", "owner"]


def _email(v: str) -> str:
    v = v.strip().lower()
    if not EMAIL_RE.match(v):
        raise ValueError("invalid email address")
    return v


def _key(v: str) -> str:
    if not KEY_RE.match(v):
        raise ValueError("key must be lowercase letters, digits, '_' or '-' (max 100)")
    return v


Email = Annotated[str, AfterValidator(_email)]
Key = Annotated[str, AfterValidator(_key)]


class SignupIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    email: Email
    password: str = Field(min_length=8, max_length=200)
    name: str = Field(min_length=1, max_length=200)
    org_name: str = Field(min_length=1, max_length=200)


class LoginIn(BaseModel):
    email: Email
    password: str


class TokenOut(BaseModel):
    token: str
    user_id: uuid.UUID
    org_id: uuid.UUID | None = None


class OrgOut(BaseModel):
    id: uuid.UUID
    name: str
    role: RoleName


class MeOut(BaseModel):
    id: uuid.UUID
    email: Email
    name: str
    orgs: list[OrgOut]


class ProjectCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    key: Key
    name: str = Field(min_length=1, max_length=200)


class EnvironmentOut(BaseModel):
    id: uuid.UUID
    key: Key
    name: str
    protected: bool
    sort_order: int
    data_version: int


class ProjectOut(BaseModel):
    id: uuid.UUID
    key: Key
    name: str
    environments: list[EnvironmentOut]


class EnvironmentCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    key: Key
    name: str = Field(min_length=1, max_length=200)
    protected: bool = False


class EnvironmentUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    name: str | None = Field(default=None, min_length=1, max_length=200)
    protected: bool | None = None


class SdkKeyOut(BaseModel):
    id: uuid.UUID
    kind: Literal["server", "client"]
    hint: str
    value: str | None = None  # client IDs always; server keys only right after creation
    created_at: datetime
    expires_at: datetime | None


class RotateIn(BaseModel):
    kind: Literal["server", "client"]
    grace_seconds: int = Field(default=0, ge=0, le=7 * 24 * 3600)


class MemberOut(BaseModel):
    user_id: uuid.UUID
    email: Email
    name: str
    role: RoleName


class MemberAdd(BaseModel):
    email: Email
    role: RoleName = "reader"


class MemberUpdate(BaseModel):
    role: RoleName


class AuditOut(BaseModel):
    id: int
    action: str
    resource_type: str
    resource_key: str
    environment_key: str | None
    actor_email: str | None
    before: Any
    after: Any
    created_at: datetime

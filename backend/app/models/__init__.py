"""ORM models. The schema itself (including RLS) is defined in migrations/versions."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import (
    BigInteger,
    Boolean,
    DateTime,
    Float,
    ForeignKey,
    Integer,
    String,
    Text,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    pass


def _uuid_pk() -> Mapped[uuid.UUID]:
    return mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)


def _created() -> Mapped[datetime]:
    return mapped_column(DateTime(timezone=True), server_default=func.now())


def _org_fk() -> Mapped[uuid.UUID]:
    return mapped_column(UUID(as_uuid=True), ForeignKey("organizations.id"), index=True)


class Organization(Base):
    __tablename__ = "organizations"
    id: Mapped[uuid.UUID] = _uuid_pk()
    name: Mapped[str] = mapped_column(String(200))
    created_at: Mapped[datetime] = _created()


class User(Base):
    __tablename__ = "users"
    id: Mapped[uuid.UUID] = _uuid_pk()
    email: Mapped[str] = mapped_column(String(320), unique=True)
    name: Mapped[str] = mapped_column(String(200))
    password_hash: Mapped[str] = mapped_column(Text)
    created_at: Mapped[datetime] = _created()


class Membership(Base):
    __tablename__ = "memberships"
    org_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("organizations.id"), primary_key=True
    )
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id"), primary_key=True
    )
    role: Mapped[str] = mapped_column(String(20))
    created_at: Mapped[datetime] = _created()


class Project(Base):
    __tablename__ = "projects"
    id: Mapped[uuid.UUID] = _uuid_pk()
    org_id: Mapped[uuid.UUID] = _org_fk()
    key: Mapped[str] = mapped_column(String(100))
    name: Mapped[str] = mapped_column(String(200))
    created_at: Mapped[datetime] = _created()


class Environment(Base):
    __tablename__ = "environments"
    id: Mapped[uuid.UUID] = _uuid_pk()
    org_id: Mapped[uuid.UUID] = _org_fk()
    project_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("projects.id"))
    key: Mapped[str] = mapped_column(String(100))
    name: Mapped[str] = mapped_column(String(200))
    protected: Mapped[bool] = mapped_column(Boolean, default=False)
    sort_order: Mapped[int] = mapped_column(Integer, default=0)
    data_version: Mapped[int] = mapped_column(BigInteger, default=0)
    created_at: Mapped[datetime] = _created()


class SdkKey(Base):
    __tablename__ = "sdk_keys"
    id: Mapped[uuid.UUID] = _uuid_pk()
    org_id: Mapped[uuid.UUID] = _org_fk()
    environment_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("environments.id")
    )
    kind: Mapped[str] = mapped_column(String(10))  # server | client
    key_hash: Mapped[str] = mapped_column(String(64), unique=True)
    hint: Mapped[str] = mapped_column(String(20))
    public_value: Mapped[str | None] = mapped_column(Text)  # client-side IDs only
    created_at: Mapped[datetime] = _created()
    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class Flag(Base):
    __tablename__ = "flags"
    id: Mapped[uuid.UUID] = _uuid_pk()
    org_id: Mapped[uuid.UUID] = _org_fk()
    project_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("projects.id"))
    key: Mapped[str] = mapped_column(String(100))
    name: Mapped[str] = mapped_column(String(200))
    description: Mapped[str] = mapped_column(Text, default="")
    kind: Mapped[str] = mapped_column(String(10))
    variations: Mapped[list[Any]] = mapped_column(JSONB)
    salt: Mapped[str] = mapped_column(String(100))
    client_side: Mapped[bool] = mapped_column(Boolean, default=False)
    archived: Mapped[bool] = mapped_column(Boolean, default=False)
    created_by: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))
    created_at: Mapped[datetime] = _created()


class FlagConfig(Base):
    __tablename__ = "flag_configs"
    id: Mapped[uuid.UUID] = _uuid_pk()
    org_id: Mapped[uuid.UUID] = _org_fk()
    flag_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("flags.id"))
    environment_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("environments.id")
    )
    on: Mapped[bool] = mapped_column(Boolean, default=False)
    off_variation: Mapped[int | None] = mapped_column(Integer)
    targets: Mapped[list[Any]] = mapped_column(JSONB, default=list)
    rules: Mapped[list[Any]] = mapped_column(JSONB, default=list)
    fallthrough: Mapped[dict[str, Any]] = mapped_column(JSONB)
    version: Mapped[int] = mapped_column(Integer, default=1)
    updated_by: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )


class AuditEntry(Base):
    __tablename__ = "audit_log"
    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    org_id: Mapped[uuid.UUID] = _org_fk()
    project_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))
    environment_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))
    actor_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))
    action: Mapped[str] = mapped_column(String(50))
    resource_type: Mapped[str] = mapped_column(String(30))
    resource_key: Mapped[str] = mapped_column(String(200))
    before: Mapped[Any] = mapped_column(JSONB)
    after: Mapped[Any] = mapped_column(JSONB)
    created_at: Mapped[datetime] = _created()


class SdkChange(Base):
    __tablename__ = "sdk_change_log"
    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    org_id: Mapped[uuid.UUID] = _org_fk()
    environment_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True))
    env_version: Mapped[int] = mapped_column(BigInteger)
    flag_key: Mapped[str] = mapped_column(String(100))
    data: Mapped[Any] = mapped_column(JSONB)
    created_at: Mapped[datetime] = _created()


class Event(Base):
    __tablename__ = "events"
    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    org_id: Mapped[uuid.UUID] = _org_fk()
    environment_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True))
    kind: Mapped[str] = mapped_column(String(20))
    user_id: Mapped[str] = mapped_column(String(200))
    flag_key: Mapped[str | None] = mapped_column(String(100))
    variation_index: Mapped[int | None] = mapped_column(Integer)
    metric_key: Mapped[str | None] = mapped_column(String(100))
    value: Mapped[float | None] = mapped_column(Float)
    ts: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    received_at: Mapped[datetime] = _created()

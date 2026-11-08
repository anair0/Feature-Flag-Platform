"""Organizations, projects, environments, and SDK keys."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta

from fastapi import HTTPException
from sqlalchemy import func, select, update
from sqlalchemy.orm import Session

from app.core.security import hash_sdk_key, new_sdk_key
from app.db.session import set_tenant
from app.models import (
    Environment,
    Flag,
    FlagConfig,
    Membership,
    Organization,
    Project,
    SdkKey,
    User,
)
from app.schemas.common import EnvironmentOut, ProjectOut, SdkKeyOut
from app.services import audit
from app.services.delivery import publish, wire
from app.services.flags import default_config

DEFAULT_ENVIRONMENTS = [
    ("development", "Development", False),
    ("staging", "Staging", False),
    ("production", "Production", True),
]


def create_org(db: Session, user: User, org_name: str) -> Organization:
    org = Organization(id=uuid.uuid4(), name=org_name)
    set_tenant(db, org_id=org.id)  # RLS: inserts must belong to the current tenant
    db.add(org)
    db.flush()
    db.add(Membership(org_id=org.id, user_id=user.id, role="owner"))
    project = Project(id=uuid.uuid4(), org_id=org.id, key="default", name="Default project")
    db.add(project)
    db.flush()
    for i, (key, name, protected) in enumerate(DEFAULT_ENVIRONMENTS):
        add_environment(
            db, project, key, name, protected, actor_id=user.id, sort_order=i, record_audit=False
        )
    audit.record(
        db,
        org_id=org.id,
        actor_id=user.id,
        action="org.created",
        resource_type="organization",
        resource_key=org_name,
    )
    return org


def create_project(
    db: Session, org_id: uuid.UUID, key: str, name: str, actor_id: uuid.UUID
) -> Project:
    if db.execute(select(Project.id).where(Project.org_id == org_id, Project.key == key)).first():
        raise HTTPException(409, f"project {key!r} already exists")
    project = Project(id=uuid.uuid4(), org_id=org_id, key=key, name=name)
    db.add(project)
    db.flush()
    for i, (k, n, protected) in enumerate(DEFAULT_ENVIRONMENTS):
        add_environment(
            db, project, k, n, protected, actor_id=actor_id, sort_order=i, record_audit=False
        )
    audit.record(
        db,
        org_id=org_id,
        actor_id=actor_id,
        action="project.created",
        resource_type="project",
        resource_key=key,
        project_id=project.id,
        after={"key": key, "name": name},
    )
    db.commit()
    return project


def add_environment(
    db: Session,
    project: Project,
    key: str,
    name: str,
    protected: bool,
    *,
    actor_id: uuid.UUID,
    sort_order: int | None = None,
    record_audit: bool = True,
) -> tuple[Environment, dict[str, str]]:
    if db.execute(
        select(Environment.id).where(Environment.project_id == project.id, Environment.key == key)
    ).first():
        raise HTTPException(409, f"environment {key!r} already exists")
    if sort_order is None:
        sort_order = (
            db.execute(
                select(func.max(Environment.sort_order)).where(Environment.project_id == project.id)
            ).scalar()
            or 0
        ) + 1
    env = Environment(
        id=uuid.uuid4(),
        org_id=project.org_id,
        project_id=project.id,
        key=key,
        name=name,
        protected=protected,
        sort_order=sort_order,
        data_version=0,
    )
    db.add(env)
    db.flush()
    keys = {kind: _issue_key(db, env, kind) for kind in ("server", "client")}
    flags = db.execute(
        select(Flag).where(Flag.project_id == project.id, Flag.archived.is_(False))
    ).scalars()
    for flag in flags:
        cfg = FlagConfig(
            id=uuid.uuid4(),
            org_id=project.org_id,
            flag_id=flag.id,
            environment_id=env.id,
            version=1,
            updated_by=actor_id,
            **default_config(flag),
        )
        db.add(cfg)
        db.flush()
        publish(db, project.org_id, env.id, flag.key, wire(flag, cfg))
    if record_audit:
        audit.record(
            db,
            org_id=project.org_id,
            actor_id=actor_id,
            action="environment.created",
            resource_type="environment",
            resource_key=key,
            project_id=project.id,
            environment_id=env.id,
            after={"key": key, "name": name, "protected": protected},
        )
    return env, keys


def _issue_key(db: Session, env: Environment, kind: str) -> str:
    value = new_sdk_key(kind)
    db.add(
        SdkKey(
            id=uuid.uuid4(),
            org_id=env.org_id,
            environment_id=env.id,
            kind=kind,
            key_hash=hash_sdk_key(value),
            hint=value[:4] + "…" + value[-4:],
            public_value=value if kind == "client" else None,
        )
    )
    return value


def rotate_key(
    db: Session, env: Environment, kind: str, grace_seconds: int, actor_id: uuid.UUID
) -> SdkKeyOut:
    """Issue a new key. Old keys of this kind expire now, or after a grace period
    so running services can be redeployed with the new key without an outage."""
    expires = datetime.now(UTC) + timedelta(seconds=grace_seconds)
    db.execute(
        update(SdkKey)
        .where(
            SdkKey.environment_id == env.id,
            SdkKey.kind == kind,
            (SdkKey.expires_at.is_(None)) | (SdkKey.expires_at > expires),
        )
        .values(expires_at=expires)
    )
    value = _issue_key(db, env, kind)
    db.flush()
    row = db.execute(select(SdkKey).where(SdkKey.key_hash == hash_sdk_key(value))).scalar_one()
    audit.record(
        db,
        org_id=env.org_id,
        actor_id=actor_id,
        action="keys.rotated",
        resource_type="environment",
        resource_key=env.key,
        project_id=env.project_id,
        environment_id=env.id,
        after={"kind": kind, "grace_seconds": grace_seconds, "new_key": row.hint},
    )
    db.commit()
    return SdkKeyOut(
        id=row.id,
        kind=row.kind,
        hint=row.hint,
        value=value,
        created_at=row.created_at,
        expires_at=row.expires_at,
    )


def list_keys(db: Session, env: Environment) -> list[SdkKeyOut]:
    now = datetime.now(UTC)
    rows = db.execute(
        select(SdkKey)
        .where(
            SdkKey.environment_id == env.id,
            (SdkKey.expires_at.is_(None)) | (SdkKey.expires_at > now),
        )
        .order_by(SdkKey.created_at)
    ).scalars()
    return [
        SdkKeyOut(
            id=r.id,
            kind=r.kind,
            hint=r.hint,
            value=r.public_value,
            created_at=r.created_at,
            expires_at=r.expires_at,
        )
        for r in rows
    ]


def project_out(db: Session, project: Project) -> ProjectOut:
    envs = db.execute(
        select(Environment)
        .where(Environment.project_id == project.id)
        .order_by(Environment.sort_order)
    ).scalars()
    return ProjectOut(
        id=project.id,
        key=project.key,
        name=project.name,
        environments=[
            EnvironmentOut(
                id=e.id,
                key=e.key,
                name=e.name,
                protected=e.protected,
                sort_order=e.sort_order,
                data_version=e.data_version,
            )
            for e in envs
        ],
    )

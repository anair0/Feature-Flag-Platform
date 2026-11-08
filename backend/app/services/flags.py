"""Flag lifecycle. Every mutation = change + SDK publication + audit entry, one transaction."""

from __future__ import annotations

import uuid
from typing import Any

from fastapi import HTTPException
from sqlalchemy import select, update
from sqlalchemy.orm import Session

from app.models import Environment, Flag, FlagConfig, Project
from app.schemas.flags import FlagConfigIn, FlagConfigOut, FlagCreate, FlagOut, FlagUpdate
from app.services import audit
from app.services.delivery import publish, wire

CONFIG_FIELDS = ("on", "off_variation", "targets", "rules", "fallthrough")


class VersionConflict(HTTPException):
    def __init__(self, current: dict[str, Any]):
        super().__init__(
            status_code=409,
            detail={
                "message": "This flag was changed by someone else since you loaded it.",
                "current": current,
            },
        )


def config_dict(cfg: FlagConfig) -> dict[str, Any]:
    return {f: getattr(cfg, f) for f in CONFIG_FIELDS} | {"version": cfg.version}


def config_out(cfg: FlagConfig, env_key: str) -> FlagConfigOut:
    return FlagConfigOut(environment_key=env_key, updated_at=cfg.updated_at, **config_dict(cfg))


def default_config(flag: Flag) -> dict[str, Any]:
    """New flags start OFF everywhere. Booleans: off -> false, on (no rules) -> true."""
    if flag.kind == "boolean":
        return {
            "on": False,
            "off_variation": 1,
            "targets": [],
            "rules": [],
            "fallthrough": {"variation": 0},
        }
    return {
        "on": False,
        "off_variation": 0,
        "targets": [],
        "rules": [],
        "fallthrough": {"variation": 0},
    }


def flag_out(db: Session, flag: Flag) -> FlagOut:
    rows = db.execute(
        select(FlagConfig, Environment.key)
        .join(Environment, Environment.id == FlagConfig.environment_id)
        .where(FlagConfig.flag_id == flag.id)
        .order_by(Environment.sort_order)
    ).all()
    return FlagOut(
        id=flag.id,
        key=flag.key,
        name=flag.name,
        description=flag.description,
        kind=flag.kind,
        variations=flag.variations,
        client_side=flag.client_side,
        archived=flag.archived,
        created_at=flag.created_at,
        environments={k: config_out(c, k) for c, k in rows},
    )


def _environments(db: Session, project: Project) -> list[Environment]:
    return list(
        db.execute(
            select(Environment)
            .where(Environment.org_id == project.org_id, Environment.project_id == project.id)
            .order_by(Environment.sort_order)
        ).scalars()
    )


def get_flag(db: Session, project: Project, key: str) -> Flag:
    flag = db.execute(
        select(Flag).where(
            Flag.org_id == project.org_id, Flag.project_id == project.id, Flag.key == key
        )
    ).scalar_one_or_none()
    if flag is None:
        raise HTTPException(404, "flag not found")
    return flag


def get_config(db: Session, flag: Flag, env: Environment) -> FlagConfig:
    return db.execute(
        select(FlagConfig).where(FlagConfig.flag_id == flag.id, FlagConfig.environment_id == env.id)
    ).scalar_one()


def create_flag(db: Session, project: Project, data: FlagCreate, actor_id: uuid.UUID) -> Flag:
    exists = db.execute(
        select(Flag.id).where(Flag.project_id == project.id, Flag.key == data.key)
    ).first()
    if exists:
        raise HTTPException(409, f"a flag with key {data.key!r} already exists")
    flag = Flag(
        id=uuid.uuid4(),
        org_id=project.org_id,
        project_id=project.id,
        key=data.key,
        name=data.name,
        description=data.description,
        kind=data.kind,
        variations=data.variations,
        salt=data.key,
        client_side=data.client_side,
        created_by=actor_id,
    )
    db.add(flag)
    db.flush()
    for env in _environments(db, project):
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
    audit.record(
        db,
        org_id=project.org_id,
        actor_id=actor_id,
        action="flag.created",
        resource_type="flag",
        resource_key=flag.key,
        project_id=project.id,
        after=data.model_dump(),
    )
    db.commit()
    return flag


def update_config(
    db: Session,
    project: Project,
    flag: Flag,
    env: Environment,
    expected_version: int,
    data: FlagConfigIn,
    actor_id: uuid.UUID,
) -> FlagConfig:
    if flag.archived:
        raise HTTPException(409, "archived flags cannot be changed")
    errors = data.semantic_errors(len(flag.variations))
    if errors:
        raise HTTPException(422, {"message": "invalid targeting", "errors": errors})
    cfg = get_config(db, flag, env)
    before = config_dict(cfg)
    new = data.normalized()

    # Optimistic concurrency: the UPDATE only applies if nobody saved in between.
    new_version = db.execute(
        update(FlagConfig)
        .where(FlagConfig.id == cfg.id, FlagConfig.version == expected_version)
        .values(**new, version=FlagConfig.version + 1, updated_by=actor_id)
        .returning(FlagConfig.version)
    ).scalar_one_or_none()
    if new_version is None:
        db.rollback()
        db.refresh(cfg)
        raise VersionConflict(config_dict(cfg))

    db.refresh(cfg)
    publish(db, project.org_id, env.id, flag.key, wire(flag, cfg))
    audit.record(
        db,
        org_id=project.org_id,
        actor_id=actor_id,
        action="config.updated",
        resource_type="flag",
        resource_key=flag.key,
        project_id=project.id,
        environment_id=env.id,
        before=before,
        after=config_dict(cfg),
    )
    db.commit()
    return cfg


def update_flag(
    db: Session, project: Project, flag: Flag, data: FlagUpdate, actor_id: uuid.UUID
) -> Flag:
    changes = data.model_dump(exclude_none=True)
    before = {k: getattr(flag, k) for k in changes}
    for k, v in changes.items():
        setattr(flag, k, v)
    db.flush()
    if "client_side" in changes and before["client_side"] != flag.client_side:
        for env in _environments(db, project):  # client_side is part of the wire format
            publish(db, project.org_id, env.id, flag.key, wire(flag, get_config(db, flag, env)))
    audit.record(
        db,
        org_id=project.org_id,
        actor_id=actor_id,
        action="flag.updated",
        resource_type="flag",
        resource_key=flag.key,
        project_id=project.id,
        before=before,
        after=changes,
    )
    db.commit()
    return flag


def set_archived(
    db: Session, project: Project, flag: Flag, archived: bool, actor_id: uuid.UUID
) -> Flag:
    if flag.archived == archived:
        return flag
    flag.archived = archived
    db.flush()
    for env in _environments(db, project):
        data = None if archived else wire(flag, get_config(db, flag, env))
        publish(db, project.org_id, env.id, flag.key, data)
    audit.record(
        db,
        org_id=project.org_id,
        actor_id=actor_id,
        action="flag.archived" if archived else "flag.restored",
        resource_type="flag",
        resource_key=flag.key,
        project_id=project.id,
        before={"archived": not archived},
        after={"archived": archived},
    )
    db.commit()
    return flag

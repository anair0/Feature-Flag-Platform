"""What SDKs see: the wire format, versioned change publication, and snapshots."""

from __future__ import annotations

import json
import uuid
from typing import Any

from sqlalchemy import delete, select, text, update
from sqlalchemy.orm import Session

from app.models import Environment, Flag, FlagConfig, SdkChange

CHANNEL = "flag_changes"
# Change-log rows only need to live until every API process's listener has read them
# (milliseconds); SDKs that reconnect always get a full snapshot. Keep a generous tail.
CHANGE_LOG_RETAIN = 1000


def wire(flag: Flag, cfg: FlagConfig) -> dict[str, Any]:
    """The flag config format defined in spec/flag-config.md."""
    return {
        "key": flag.key,
        "version": cfg.version,
        "kind": flag.kind,
        "on": cfg.on,
        "variations": flag.variations,
        "off_variation": cfg.off_variation,
        "targets": cfg.targets,
        "rules": cfg.rules,
        "fallthrough": cfg.fallthrough,
        "salt": flag.salt,
        "client_side": flag.client_side,
    }


def publish(
    db: Session, org_id: uuid.UUID, environment_id: uuid.UUID, flag_key: str, data: dict | None
) -> int:
    """Record one change for SDKs, in the caller's transaction.

    Incrementing environments.data_version takes a row lock that is held until
    commit, so concurrent writers to one environment are serialized and their
    env_versions commit in order. pg_notify is transactional too: listeners hear
    about the change only if, and when, it commits.
    """
    env_version = db.execute(
        update(Environment)
        .where(Environment.id == environment_id)
        .values(data_version=Environment.data_version + 1)
        .returning(Environment.data_version)
    ).scalar_one()
    db.add(
        SdkChange(
            org_id=org_id,
            environment_id=environment_id,
            env_version=env_version,
            flag_key=flag_key,
            data=data,
        )
    )
    payload = json.dumps(
        {"org_id": str(org_id), "environment_id": str(environment_id), "env_version": env_version}
    )
    db.execute(text("SELECT pg_notify(:c, :p)"), {"c": CHANNEL, "p": payload})
    if env_version % 100 == 0:  # amortized retention
        db.execute(
            delete(SdkChange).where(
                SdkChange.environment_id == environment_id,
                SdkChange.env_version <= env_version - CHANGE_LOG_RETAIN,
            )
        )
    return env_version


def snapshot(db: Session, environment_id: uuid.UUID) -> dict[str, Any]:
    # Read the version *before* the flags: under READ COMMITTED the flags may then include
    # a change newer than env_version (harmless, the patch is re-applied), never an older one.
    env_version = db.execute(
        select(Environment.data_version).where(Environment.id == environment_id)
    ).scalar_one()
    rows = db.execute(
        select(Flag, FlagConfig)
        .join(FlagConfig, FlagConfig.flag_id == Flag.id)
        .where(FlagConfig.environment_id == environment_id, Flag.archived.is_(False))
    ).all()
    return {"env_version": env_version, "flags": {f.key: wire(f, c) for f, c in rows}}


def load_change(db: Session, environment_id: uuid.UUID, env_version: int) -> SdkChange | None:
    return db.execute(
        select(SdkChange).where(
            SdkChange.environment_id == environment_id, SdkChange.env_version == env_version
        )
    ).scalar_one_or_none()

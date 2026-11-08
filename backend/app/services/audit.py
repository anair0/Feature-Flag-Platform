from __future__ import annotations

import uuid
from typing import Any

from sqlalchemy.orm import Session

from app.models import AuditEntry


def record(
    db: Session,
    *,
    org_id: uuid.UUID,
    actor_id: uuid.UUID | None,
    action: str,
    resource_type: str,
    resource_key: str,
    before: Any = None,
    after: Any = None,
    project_id: uuid.UUID | None = None,
    environment_id: uuid.UUID | None = None,
) -> None:
    """Add an audit entry to the caller's transaction: it commits with the change or not at all."""
    db.add(
        AuditEntry(
            org_id=org_id,
            actor_id=actor_id,
            action=action,
            resource_type=resource_type,
            resource_key=resource_key,
            before=before,
            after=after,
            project_id=project_id,
            environment_id=environment_id,
        )
    )

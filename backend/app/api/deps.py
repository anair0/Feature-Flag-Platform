"""Request context: who is calling, in which tenant, with what role.

Tenancy layer 1 (application): every org-scoped route goes through org_context,
which 404s unless the caller is a member, and every query filters by org_id.
Layer 2 (database): org_context also sets the Postgres tenant, so RLS hides
other tenants' rows even if a query forgets its filter.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass

from fastapi import Depends, HTTPException
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.permissions import Role, can
from app.core.security import decode_token
from app.db.session import get_db, set_tenant
from app.models import Environment, Membership, Project, User

bearer = HTTPBearer(auto_error=False)


def current_user(
    creds: HTTPAuthorizationCredentials | None = Depends(bearer),
    db: Session = Depends(get_db),
) -> User:
    user_id = decode_token(creds.credentials) if creds else None
    if user_id is None:
        raise HTTPException(401, "not authenticated", headers={"WWW-Authenticate": "Bearer"})
    set_tenant(db, user_id=user_id)
    user = db.get(User, user_id)
    if user is None:
        raise HTTPException(401, "not authenticated")
    return user


@dataclass
class OrgContext:
    org_id: uuid.UUID
    user: User
    role: Role
    db: Session

    def require(self, action: str, *, protected_env: bool = False) -> None:
        if not can(self.role, action, protected_env=protected_env):
            extra = " in a protected environment" if protected_env else ""
            raise HTTPException(403, f"your role ({self.role.name}) cannot perform {action}{extra}")


def org_context(
    org_id: uuid.UUID, user: User = Depends(current_user), db: Session = Depends(get_db)
) -> OrgContext:
    set_tenant(db, org_id=org_id)
    m = db.execute(
        select(Membership).where(Membership.org_id == org_id, Membership.user_id == user.id)
    ).scalar_one_or_none()
    if m is None:
        # 404 rather than 403: don't confirm that another tenant's org exists.
        raise HTTPException(404, "organization not found")
    return OrgContext(org_id=org_id, user=user, role=Role[m.role], db=db)


def get_project(ctx: OrgContext, project_key: str) -> Project:
    project = ctx.db.execute(
        select(Project).where(Project.org_id == ctx.org_id, Project.key == project_key)
    ).scalar_one_or_none()
    if project is None:
        raise HTTPException(404, "project not found")
    return project


def get_environment(ctx: OrgContext, project: Project, env_key: str) -> Environment:
    env = ctx.db.execute(
        select(Environment).where(
            Environment.org_id == ctx.org_id,
            Environment.project_id == project.id,
            Environment.key == env_key,
        )
    ).scalar_one_or_none()
    if env is None:
        raise HTTPException(404, "environment not found")
    return env

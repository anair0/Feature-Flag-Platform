"""Projects, environments, SDK keys, members, and the audit log."""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import func, select
from sqlalchemy.orm import aliased

from app.api.deps import OrgContext, get_environment, get_project, org_context
from app.core.permissions import Role, can_change_member
from app.models import AuditEntry, Environment, Membership, Project, User
from app.schemas.common import (
    AuditOut,
    EnvironmentCreate,
    EnvironmentOut,
    EnvironmentUpdate,
    MemberAdd,
    MemberOut,
    MemberUpdate,
    ProjectCreate,
    ProjectOut,
    RotateIn,
    SdkKeyOut,
)
from app.services import audit
from app.services.orgs import add_environment, create_project, list_keys, project_out, rotate_key

router = APIRouter(prefix="/api/orgs/{org_id}", tags=["organization"])


# -------------------------------------------------------------------- projects


@router.get("/projects", response_model=list[ProjectOut])
def list_projects(ctx: OrgContext = Depends(org_context)) -> list[ProjectOut]:
    ctx.require("project.read")
    projects = ctx.db.execute(
        select(Project).where(Project.org_id == ctx.org_id).order_by(Project.created_at)
    ).scalars()
    return [project_out(ctx.db, p) for p in projects]


@router.post("/projects", response_model=ProjectOut, status_code=201)
def new_project(body: ProjectCreate, ctx: OrgContext = Depends(org_context)) -> ProjectOut:
    ctx.require("project.create")
    project = create_project(ctx.db, ctx.org_id, body.key, body.name, ctx.user.id)
    return project_out(ctx.db, project)


@router.get("/projects/{project_key}", response_model=ProjectOut)
def read_project(project_key: str, ctx: OrgContext = Depends(org_context)) -> ProjectOut:
    ctx.require("project.read")
    return project_out(ctx.db, get_project(ctx, project_key))


# ---------------------------------------------------------------- environments


class _EnvCreated(EnvironmentOut):
    server_key: str
    client_id: str


@router.post("/projects/{project_key}/environments", response_model=_EnvCreated, status_code=201)
def new_environment(
    project_key: str, body: EnvironmentCreate, ctx: OrgContext = Depends(org_context)
) -> _EnvCreated:
    ctx.require("environment.create")
    project = get_project(ctx, project_key)
    env, keys = add_environment(
        ctx.db, project, body.key, body.name, body.protected, actor_id=ctx.user.id
    )
    ctx.db.commit()
    return _EnvCreated(
        id=env.id,
        key=env.key,
        name=env.name,
        protected=env.protected,
        sort_order=env.sort_order,
        data_version=env.data_version,
        server_key=keys["server"],
        client_id=keys["client"],
    )


@router.patch("/projects/{project_key}/environments/{env_key}", response_model=EnvironmentOut)
def edit_environment(
    project_key: str, env_key: str, body: EnvironmentUpdate, ctx: OrgContext = Depends(org_context)
) -> EnvironmentOut:
    ctx.require("environment.update")
    env = get_environment(ctx, get_project(ctx, project_key), env_key)
    changes = body.model_dump(exclude_none=True)
    before = {k: getattr(env, k) for k in changes}
    for k, v in changes.items():
        setattr(env, k, v)
    audit.record(
        ctx.db,
        org_id=ctx.org_id,
        actor_id=ctx.user.id,
        action="environment.updated",
        resource_type="environment",
        resource_key=env.key,
        project_id=env.project_id,
        environment_id=env.id,
        before=before,
        after=changes,
    )
    ctx.db.commit()
    return EnvironmentOut(
        id=env.id,
        key=env.key,
        name=env.name,
        protected=env.protected,
        sort_order=env.sort_order,
        data_version=env.data_version,
    )


@router.get("/projects/{project_key}/environments/{env_key}/keys", response_model=list[SdkKeyOut])
def read_keys(
    project_key: str, env_key: str, ctx: OrgContext = Depends(org_context)
) -> list[SdkKeyOut]:
    ctx.require("keys.read")
    return list_keys(ctx.db, get_environment(ctx, get_project(ctx, project_key), env_key))


@router.post("/projects/{project_key}/environments/{env_key}/keys/rotate", response_model=SdkKeyOut)
def rotate(
    project_key: str, env_key: str, body: RotateIn, ctx: OrgContext = Depends(org_context)
) -> SdkKeyOut:
    ctx.require("keys.rotate")
    env = get_environment(ctx, get_project(ctx, project_key), env_key)
    return rotate_key(ctx.db, env, body.kind, body.grace_seconds, ctx.user.id)


# --------------------------------------------------------------------- members


def _member_out(m: Membership, u: User) -> MemberOut:
    return MemberOut(user_id=u.id, email=u.email, name=u.name, role=m.role)


@router.get("/members", response_model=list[MemberOut])
def list_members(ctx: OrgContext = Depends(org_context)) -> list[MemberOut]:
    ctx.require("members.read")
    rows = ctx.db.execute(
        select(Membership, User)
        .join(User, User.id == Membership.user_id)
        .where(Membership.org_id == ctx.org_id)
        .order_by(Membership.created_at)
    ).all()
    return [_member_out(m, u) for m, u in rows]


@router.post("/members", response_model=MemberOut, status_code=201)
def add_member(body: MemberAdd, ctx: OrgContext = Depends(org_context)) -> MemberOut:
    ctx.require("members.manage")
    if not can_change_member(ctx.role, None, Role[body.role]):
        raise HTTPException(403, f"your role cannot grant {body.role}")
    user = ctx.db.execute(select(User).where(User.email == body.email)).scalar_one_or_none()
    if user is None:
        raise HTTPException(404, "no account with that email; ask them to sign up first")
    if ctx.db.get(Membership, (ctx.org_id, user.id)):
        raise HTTPException(409, "already a member")
    m = Membership(org_id=ctx.org_id, user_id=user.id, role=body.role)
    ctx.db.add(m)
    audit.record(
        ctx.db,
        org_id=ctx.org_id,
        actor_id=ctx.user.id,
        action="member.added",
        resource_type="member",
        resource_key=user.email,
        after={"role": body.role},
    )
    ctx.db.commit()
    return _member_out(m, user)


def _target(ctx: OrgContext, user_id: uuid.UUID) -> tuple[Membership, User]:
    row = ctx.db.execute(
        select(Membership, User)
        .join(User, User.id == Membership.user_id)
        .where(Membership.org_id == ctx.org_id, Membership.user_id == user_id)
    ).first()
    if row is None:
        raise HTTPException(404, "member not found")
    return row[0], row[1]


def _owner_count(ctx: OrgContext) -> int:
    return ctx.db.execute(
        select(func.count())
        .select_from(Membership)
        .where(Membership.org_id == ctx.org_id, Membership.role == "owner")
    ).scalar_one()


@router.patch("/members/{user_id}", response_model=MemberOut)
def change_role(
    user_id: uuid.UUID, body: MemberUpdate, ctx: OrgContext = Depends(org_context)
) -> MemberOut:
    ctx.require("members.manage")
    m, u = _target(ctx, user_id)
    if not can_change_member(ctx.role, Role[m.role], Role[body.role]):
        raise HTTPException(403, "your role cannot make this change")
    if m.role == "owner" and body.role != "owner" and _owner_count(ctx) == 1:
        raise HTTPException(409, "an organization must keep at least one owner")
    before = m.role
    m.role = body.role
    audit.record(
        ctx.db,
        org_id=ctx.org_id,
        actor_id=ctx.user.id,
        action="member.role_changed",
        resource_type="member",
        resource_key=u.email,
        before={"role": before},
        after={"role": body.role},
    )
    ctx.db.commit()
    return _member_out(m, u)


@router.delete("/members/{user_id}", status_code=204)
def remove_member(user_id: uuid.UUID, ctx: OrgContext = Depends(org_context)) -> None:
    ctx.require("members.manage")
    m, u = _target(ctx, user_id)
    if not can_change_member(ctx.role, Role[m.role], None):
        raise HTTPException(403, "your role cannot remove this member")
    if m.role == "owner" and _owner_count(ctx) == 1:
        raise HTTPException(409, "an organization must keep at least one owner")
    ctx.db.delete(m)
    audit.record(
        ctx.db,
        org_id=ctx.org_id,
        actor_id=ctx.user.id,
        action="member.removed",
        resource_type="member",
        resource_key=u.email,
        before={"role": m.role},
    )
    ctx.db.commit()


# ----------------------------------------------------------------------- audit


@router.get("/audit", response_model=list[AuditOut])
def read_audit(
    ctx: OrgContext = Depends(org_context),
    project_key: str | None = None,
    flag_key: str | None = None,
    limit: int = Query(50, ge=1, le=500),
    before_id: int | None = None,
) -> list[AuditOut]:
    ctx.require("audit.read")
    actor = aliased(User)
    q = (
        select(AuditEntry, Environment.key, actor.email)
        .outerjoin(Environment, Environment.id == AuditEntry.environment_id)
        .outerjoin(actor, actor.id == AuditEntry.actor_id)
        .where(AuditEntry.org_id == ctx.org_id)
    )
    if project_key:
        q = q.where(AuditEntry.project_id == get_project(ctx, project_key).id)
    if flag_key:
        q = q.where(AuditEntry.resource_type == "flag", AuditEntry.resource_key == flag_key)
    if before_id:
        q = q.where(AuditEntry.id < before_id)
    rows = ctx.db.execute(q.order_by(AuditEntry.id.desc()).limit(limit)).all()
    return [
        AuditOut(
            id=a.id,
            action=a.action,
            resource_type=a.resource_type,
            resource_key=a.resource_key,
            environment_key=ek,
            actor_email=email,
            before=a.before,
            after=a.after,
            created_at=a.created_at,
        )
        for a, ek, email in rows
    ]

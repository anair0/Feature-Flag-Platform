from __future__ import annotations

from fastapi import APIRouter, Depends, Header, HTTPException, Query, Response
from sqlalchemy import select

from app.api.deps import OrgContext, get_environment, get_project, org_context
from app.models import Flag
from app.schemas.flags import (
    EvaluateIn,
    FlagConfigIn,
    FlagConfigOut,
    FlagCreate,
    FlagOut,
    FlagUpdate,
)
from app.services import experiments
from app.services import flags as svc
from app.services.delivery import wire
from featureflags.evaluation import evaluate

router = APIRouter(prefix="/api/orgs/{org_id}/projects/{project_key}/flags", tags=["flags"])


@router.get("", response_model=list[FlagOut])
def list_flags(
    project_key: str, include_archived: bool = False, ctx: OrgContext = Depends(org_context)
) -> list[FlagOut]:
    ctx.require("project.read")
    project = get_project(ctx, project_key)
    q = select(Flag).where(Flag.org_id == ctx.org_id, Flag.project_id == project.id)
    if not include_archived:
        q = q.where(Flag.archived.is_(False))
    return [svc.flag_out(ctx.db, f) for f in ctx.db.execute(q.order_by(Flag.key)).scalars()]


@router.post("", response_model=FlagOut, status_code=201)
def create_flag(
    project_key: str, body: FlagCreate, ctx: OrgContext = Depends(org_context)
) -> FlagOut:
    ctx.require("flag.create")
    flag = svc.create_flag(ctx.db, get_project(ctx, project_key), body, ctx.user.id)
    return svc.flag_out(ctx.db, flag)


@router.get("/{flag_key}", response_model=FlagOut)
def read_flag(project_key: str, flag_key: str, ctx: OrgContext = Depends(org_context)) -> FlagOut:
    ctx.require("project.read")
    return svc.flag_out(ctx.db, svc.get_flag(ctx.db, get_project(ctx, project_key), flag_key))


@router.patch("/{flag_key}", response_model=FlagOut)
def update_flag(
    project_key: str, flag_key: str, body: FlagUpdate, ctx: OrgContext = Depends(org_context)
) -> FlagOut:
    ctx.require("flag.update")
    project = get_project(ctx, project_key)
    flag = svc.update_flag(
        ctx.db, project, svc.get_flag(ctx.db, project, flag_key), body, ctx.user.id
    )
    return svc.flag_out(ctx.db, flag)


@router.post("/{flag_key}/archive", response_model=FlagOut)
def archive_flag(
    project_key: str, flag_key: str, archived: bool = True, ctx: OrgContext = Depends(org_context)
) -> FlagOut:
    ctx.require("flag.archive")
    project = get_project(ctx, project_key)
    flag = svc.set_archived(
        ctx.db, project, svc.get_flag(ctx.db, project, flag_key), archived, ctx.user.id
    )
    return svc.flag_out(ctx.db, flag)


def _parse_if_match(value: str | None) -> int:
    if value is None:
        raise HTTPException(428, "If-Match header with the config version you edited is required")
    try:
        return int(value.strip().removeprefix("W/").strip('"'))
    except ValueError:
        raise HTTPException(400, "If-Match must be a version number") from None


@router.put("/{flag_key}/environments/{env_key}", response_model=FlagConfigOut)
def update_config(
    project_key: str,
    flag_key: str,
    env_key: str,
    body: FlagConfigIn,
    response: Response,
    if_match: str | None = Header(default=None),
    ctx: OrgContext = Depends(org_context),
) -> FlagConfigOut:
    project = get_project(ctx, project_key)
    env = get_environment(ctx, project, env_key)
    ctx.require("config.update", protected_env=env.protected)
    flag = svc.get_flag(ctx.db, project, flag_key)
    cfg = svc.update_config(
        ctx.db, project, flag, env, _parse_if_match(if_match), body, ctx.user.id
    )
    response.headers["ETag"] = f'"{cfg.version}"'
    return svc.config_out(cfg, env.key)


@router.post("/{flag_key}/environments/{env_key}/evaluate")
def test_evaluate(
    project_key: str,
    flag_key: str,
    env_key: str,
    body: EvaluateIn,
    ctx: OrgContext = Depends(org_context),
) -> dict:
    """Dashboard 'test this user' panel: what would this user get, and why?"""
    ctx.require("evaluate.test")
    project = get_project(ctx, project_key)
    env = get_environment(ctx, project, env_key)
    flag = svc.get_flag(ctx.db, project, flag_key)
    return evaluate(wire(flag, svc.get_config(ctx.db, flag, env)), body.user).to_dict()


@router.get("/{flag_key}/environments/{env_key}/experiment")
def experiment_results(
    project_key: str,
    flag_key: str,
    env_key: str,
    metric: str = Query(..., min_length=1),
    control: int = Query(0, ge=0),
    alpha: float = Query(0.05, gt=0, lt=0.5),
    min_sample: int = Query(100, ge=1),
    ctx: OrgContext = Depends(org_context),
) -> dict:
    ctx.require("experiments.read")
    project = get_project(ctx, project_key)
    env = get_environment(ctx, project, env_key)
    flag = svc.get_flag(ctx.db, project, flag_key)
    analysis, error = experiments.results(
        ctx.db, flag, env, svc.get_config(ctx.db, flag, env), metric, control, alpha, min_sample
    )
    if analysis is None:
        raise HTTPException(409, error)
    return {
        "metric": metric,
        "control": control,
        "alpha": alpha,
        "min_sample": min_sample,
        **analysis.__dict__,
    }

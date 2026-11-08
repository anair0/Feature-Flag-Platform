"""Endpoints used by SDKs. Protocol: spec/streaming.md.

Server SDK keys (secret) may download full rules. Client-side IDs (public, shipped
to browsers) only ever receive *evaluated values* of flags marked client_side,
so targeting rules, user lists and unreleased flag names never reach a browser.
"""

from __future__ import annotations

import asyncio
import json
import uuid
from collections.abc import AsyncIterator
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any, Literal

from fastapi import APIRouter, Depends, Header, HTTPException, Query, Request
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field
from sqlalchemy import insert, text
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.security import hash_sdk_key
from app.db.session import SessionLocal, get_db, set_tenant
from app.models import Event
from app.services.broadcaster import broadcaster
from app.services.delivery import snapshot
from featureflags.evaluation import evaluate

router = APIRouter(prefix="/sdk/v1", tags=["sdk"])


@dataclass(frozen=True)
class SdkCaller:
    environment_id: uuid.UUID
    org_id: uuid.UUID
    kind: str


def _resolve(db: Session, raw: str | None) -> SdkCaller | None:
    if not raw:
        return None
    row = db.execute(
        text("SELECT environment_id, org_id, kind FROM resolve_sdk_key(:h)"),
        {"h": hash_sdk_key(raw.strip())},
    ).first()
    if row is None:
        return None
    set_tenant(db, org_id=row.org_id)
    return SdkCaller(row.environment_id, row.org_id, row.kind)


def _require(caller: SdkCaller | None, kind: str | None) -> SdkCaller:
    if caller is None:
        raise HTTPException(401, "invalid or expired SDK key")
    if kind and caller.kind != kind:
        raise HTTPException(403, f"this endpoint requires a {kind} key")
    return caller


def _client_credential(x_client_id: str | None, client_id: str | None) -> str | None:
    return x_client_id or client_id


def server_caller(
    authorization: str | None = Header(default=None), db: Session = Depends(get_db)
) -> SdkCaller:
    return _require(_resolve(db, authorization), "server")


def client_caller(
    x_client_id: str | None = Header(default=None),
    client_id: str | None = Query(default=None),
    db: Session = Depends(get_db),
) -> SdkCaller:
    return _require(_resolve(db, _client_credential(x_client_id, client_id)), "client")


def any_caller(
    authorization: str | None = Header(default=None),
    x_client_id: str | None = Header(default=None),
    client_id: str | None = Query(default=None),
    db: Session = Depends(get_db),
) -> SdkCaller:
    raw = authorization or _client_credential(x_client_id, client_id)
    return _require(_resolve(db, raw), None)


# ---------------------------------------------------------------- server SDKs


@router.get("/flags")
def get_flags(caller: SdkCaller = Depends(server_caller), db: Session = Depends(get_db)) -> dict:
    return snapshot(db, caller.environment_id)


def _short_lived(fn, raw: str | None, kind: str):
    """Run fn(db, caller) in its own session that is closed immediately afterwards."""
    with SessionLocal() as db:
        caller = _require(_resolve(db, raw), kind)
        return caller, fn(db, caller)


def _sse(event: str, data: Any) -> str:
    return f"event: {event}\ndata: {json.dumps(data, separators=(',', ':'))}\n\n"


async def _stream(
    request: Request, raw: str | None, kind: str, initial, render
) -> StreamingResponse:
    # Validate the key up front so a bad key gets a proper 401, not a broken stream.
    caller, _ = await asyncio.to_thread(_short_lived, lambda db, c: None, raw, kind)
    sub = broadcaster.subscribe(caller.environment_id)  # before reading -> nothing is missed

    async def body() -> AsyncIterator[str]:
        try:
            # The initial snapshot is read *after* subscribing, so a change that commits in
            # between is in the queue; SDKs drop it as stale if the snapshot already has it.
            _, data = await asyncio.to_thread(_short_lived, initial, raw, kind)
            yield render(data, initial=True)
            while True:
                try:
                    msg = await asyncio.wait_for(
                        sub.queue.get(), timeout=settings.stream_heartbeat_seconds
                    )
                except TimeoutError:
                    if await request.is_disconnected():
                        return
                    yield ": heartbeat\n\n"
                    continue
                if msg["type"] == "overflow" or sub.overflowed:
                    return  # SDK reconnects and gets a fresh snapshot
                yield render(msg, initial=False)
        finally:
            broadcaster.unsubscribe(sub)

    return StreamingResponse(
        body(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


@router.get("/stream")
async def stream(request: Request, authorization: str | None = Header(default=None)):
    def render(data: dict, initial: bool) -> str:
        if initial:
            return _sse("put", data)
        return _sse("patch", {k: data[k] for k in ("env_version", "key", "flag")})

    return await _stream(
        request, authorization, "server", lambda db, c: snapshot(db, c.environment_id), render
    )


# --------------------------------------------------------------- browser SDKs


class EvaluateBody(BaseModel):
    user: dict[str, Any]


def evaluate_client_side(db: Session, caller: SdkCaller, user: dict) -> dict:
    snap = snapshot(db, caller.environment_id)
    return {
        "env_version": snap["env_version"],
        "flags": {
            k: evaluate(f, user).to_dict() for k, f in snap["flags"].items() if f.get("client_side")
        },
    }


@router.post("/evaluate")
def client_evaluate(
    body: EvaluateBody, caller: SdkCaller = Depends(client_caller), db: Session = Depends(get_db)
) -> dict:
    return evaluate_client_side(db, caller, body.user)


@router.get("/client-stream")
async def client_stream(
    request: Request,
    x_client_id: str | None = Header(default=None),
    client_id: str | None = Query(default=None),
):
    """Change pings only: no flag data. The browser SDK re-calls /evaluate."""

    def version(db: Session, caller: SdkCaller) -> dict:
        return {"env_version": snapshot(db, caller.environment_id)["env_version"]}

    def render(data: dict, initial: bool) -> str:
        return _sse("change", {"env_version": data["env_version"]})

    return await _stream(
        request, _client_credential(x_client_id, client_id), "client", version, render
    )


# --------------------------------------------------------------------- events


class EventIn(BaseModel):
    kind: Literal["exposure", "custom"]
    user_id: str = Field(min_length=1, max_length=200)
    flag_key: str | None = Field(default=None, max_length=100)
    variation_index: int | None = Field(default=None, ge=0)
    metric_key: str | None = Field(default=None, max_length=100)
    value: float | None = None
    timestamp: int | None = None  # ms since epoch


class EventsBody(BaseModel):
    events: list[EventIn] = Field(max_length=1000)


def _ts(ms: int | None, now: datetime) -> datetime:
    if ms is None:
        return now
    try:
        ts = datetime.fromtimestamp(ms / 1000, UTC)
    except (OverflowError, OSError, ValueError):
        return now
    # Don't let skewed client clocks put events in the future.
    return now if ts > now + timedelta(minutes=5) else ts


@router.post("/events", status_code=202)
def ingest_events(
    body: EventsBody, caller: SdkCaller = Depends(any_caller), db: Session = Depends(get_db)
) -> dict:
    now = datetime.now(UTC)
    rows = []
    for e in body.events:
        if e.kind == "exposure" and (e.flag_key is None or e.variation_index is None):
            continue
        if e.kind == "custom" and e.metric_key is None:
            continue
        rows.append(
            {
                "org_id": caller.org_id,
                "environment_id": caller.environment_id,
                "kind": e.kind,
                "user_id": e.user_id,
                "flag_key": e.flag_key,
                "variation_index": e.variation_index,
                "metric_key": e.metric_key,
                "value": e.value,
                "ts": _ts(e.timestamp, now),
            }
        )
    if rows:
        db.execute(insert(Event), rows)
        db.commit()
    return {"accepted": len(rows), "rejected": len(body.events) - len(rows)}

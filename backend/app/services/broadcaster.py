"""Fan-out of flag changes to connected SDK streams.

Each API process LISTENs on a Postgres channel. A committed change anywhere (any
process) produces a NOTIFY carrying (org, environment, env_version). The listener
loads that exact change from sdk_change_log and pushes it to the local subscribers
of that environment. No Redis needed. Postgres delivers notifications in commit
order, and processing them sequentially keeps that order.

Slow consumers are disconnected rather than buffered without limit. Their SDK
reconnects and receives a fresh `put`, which is always correct.
"""

from __future__ import annotations

import asyncio
import contextlib
import json
import logging
import uuid
from dataclasses import dataclass, field

import psycopg

from app.core.config import settings
from app.db.session import SessionLocal, set_tenant
from app.services.delivery import CHANNEL, load_change

log = logging.getLogger("flagplatform.broadcaster")
QUEUE_SIZE = 1000


@dataclass(eq=False)
class Subscriber:
    environment_id: uuid.UUID
    queue: asyncio.Queue = field(default_factory=lambda: asyncio.Queue(QUEUE_SIZE))
    overflowed: bool = False

    def offer(self, message: dict) -> None:
        try:
            self.queue.put_nowait(message)
        except asyncio.QueueFull:
            self.overflowed = True
            with contextlib.suppress(asyncio.QueueFull):
                self.queue.put_nowait({"type": "overflow"})


class Broadcaster:
    def __init__(self) -> None:
        self._subs: dict[uuid.UUID, set[Subscriber]] = {}
        self._task: asyncio.Task | None = None
        self.listening = asyncio.Event()

    # -- subscriptions -------------------------------------------------------
    def subscribe(self, environment_id: uuid.UUID) -> Subscriber:
        sub = Subscriber(environment_id)
        self._subs.setdefault(environment_id, set()).add(sub)
        return sub

    def unsubscribe(self, sub: Subscriber) -> None:
        subs = self._subs.get(sub.environment_id)
        if subs:
            subs.discard(sub)
            if not subs:
                del self._subs[sub.environment_id]

    def connection_count(self) -> int:
        return sum(len(s) for s in self._subs.values())

    # -- lifecycle -------------------------------------------------------------
    async def start(self) -> None:
        self._task = asyncio.create_task(self._run(), name="flag-change-listener")

    async def stop(self) -> None:
        if self._task:
            self._task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self._task

    async def _run(self) -> None:
        dsn = settings.database_url.replace("postgresql+psycopg://", "postgresql://")
        delay = 1.0
        while True:
            try:
                async with await psycopg.AsyncConnection.connect(dsn, autocommit=True) as conn:
                    await conn.execute(f"LISTEN {CHANNEL}")
                    self.listening.set()
                    delay = 1.0
                    # Anything committed while we were disconnected is unknown to us:
                    # tell every stream to resync (their SDKs reconnect and get a `put`).
                    self._broadcast_all({"type": "overflow"})
                    async for note in conn.notifies():
                        await self._dispatch(note.payload)
            except asyncio.CancelledError:
                raise
            except Exception as e:
                self.listening.clear()
                log.warning("change listener failed (%s); retrying in %.0fs", e, delay)
                await asyncio.sleep(delay)
                delay = min(delay * 2, 30.0)

    def _broadcast_all(self, message: dict) -> None:
        for subs in list(self._subs.values()):
            for sub in list(subs):
                sub.offer(message)

    async def _dispatch(self, payload: str) -> None:
        try:
            msg = json.loads(payload)
            env_id = uuid.UUID(msg["environment_id"])
            if env_id not in self._subs:
                return
            change = await asyncio.to_thread(
                _load, uuid.UUID(msg["org_id"]), env_id, int(msg["env_version"])
            )
            if change is None:
                return
            for sub in list(self._subs.get(env_id, ())):
                sub.offer(change)
        except Exception:
            log.exception("failed to dispatch change %s", payload)


def _load(org_id: uuid.UUID, env_id: uuid.UUID, env_version: int) -> dict | None:
    with SessionLocal() as db:
        set_tenant(db, org_id=org_id)
        change = load_change(db, env_id, env_version)
        if change is None:
            return None
        return {
            "type": "patch",
            "env_version": change.env_version,
            "key": change.flag_key,
            "flag": change.data,
        }


broadcaster = Broadcaster()

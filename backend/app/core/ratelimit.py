"""In-process token-bucket rate limiting.

Per-process state is enough for a single-node deployment and for the demo. With
several API processes, move the buckets to Redis (same algorithm, atomic Lua script).
"""

from __future__ import annotations

import time
from collections.abc import Callable
from dataclasses import dataclass

from starlette.requests import Request
from starlette.responses import JSONResponse
from starlette.types import ASGIApp, Receive, Scope, Send


@dataclass
class Bucket:
    tokens: float
    updated: float


class TokenBuckets:
    def __init__(self, rate: float, burst: int, max_keys: int = 100_000):
        self.rate, self.burst, self.max_keys = rate, burst, max_keys
        self._buckets: dict[str, Bucket] = {}

    def allow(self, key: str, now: float | None = None) -> bool:
        now = time.monotonic() if now is None else now
        b = self._buckets.get(key)
        if b is None:
            if len(self._buckets) >= self.max_keys:
                self._buckets.clear()  # crude bound on memory; fails open briefly
            b = self._buckets[key] = Bucket(self.burst, now)
        b.tokens = min(self.burst, b.tokens + (now - b.updated) * self.rate)
        b.updated = now
        if b.tokens >= 1:
            b.tokens -= 1
            return True
        return False


Rule = tuple[Callable[[str, str], bool], TokenBuckets, Callable[[Request], str]]


def client_ip(request: Request) -> str:
    return request.client.host if request.client else "unknown"


def sdk_identity(request: Request) -> str:
    return (
        request.headers.get("x-client-id")
        or request.query_params.get("client_id")
        or request.headers.get("authorization")
        or client_ip(request)
    )


class RateLimitMiddleware:
    def __init__(self, app: ASGIApp, rules: list[Rule], enabled: Callable[[], bool]):
        self.app, self.rules, self.enabled = app, rules, enabled

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] == "http" and self.enabled():
            request = Request(scope)
            for matches, buckets, identity in self.rules:
                if matches(request.method, request.url.path):
                    if not buckets.allow(f"{request.url.path}:{identity(request)}"):
                        response = JSONResponse(
                            {"detail": "rate limit exceeded"},
                            status_code=429,
                            headers={"Retry-After": "1"},
                        )
                        await response(scope, receive, send)
                        return
        await self.app(scope, receive, send)

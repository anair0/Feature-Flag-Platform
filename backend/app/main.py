from __future__ import annotations

from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api import auth, flags, orgs, sdk
from app.core.config import DEV_JWT_SECRET, settings
from app.core.ratelimit import RateLimitMiddleware, TokenBuckets, client_ip, sdk_identity
from app.services.broadcaster import broadcaster


@asynccontextmanager
async def lifespan(app: FastAPI):
    if settings.environment == "production" and settings.jwt_secret == DEV_JWT_SECRET:
        raise RuntimeError("Set JWT_SECRET: refusing to run production with the dev secret")
    await broadcaster.start()
    yield
    await broadcaster.stop()


app = FastAPI(title="Feature Flag Platform", version="0.1.0", lifespan=lifespan)

app.add_middleware(
    RateLimitMiddleware,
    rules=[
        (
            lambda m, p: m == "POST" and p.startswith("/api/auth/"),
            TokenBuckets(settings.auth_rate, settings.auth_burst),
            client_ip,
        ),
        (
            lambda m, p: p == "/sdk/v1/evaluate",
            TokenBuckets(settings.evaluate_rate, settings.evaluate_burst),
            sdk_identity,
        ),
    ],
    enabled=lambda: settings.rate_limit_enabled,
)
# Bearer tokens, not cookies, so a permissive CORS policy doesn't enable CSRF.
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,
    allow_methods=["*"],
    allow_headers=["*"],
    expose_headers=["ETag"],
)

app.include_router(auth.router)
app.include_router(orgs.router)
app.include_router(flags.router)
app.include_router(sdk.router)


@app.get("/health")
def health() -> dict:
    return {
        "status": "ok",
        "change_listener": "up" if broadcaster.listening.is_set() else "down",
        "stream_connections": broadcaster.connection_count(),
    }

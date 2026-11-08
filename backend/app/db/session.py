"""Database sessions with tenant context.

Tenant identity is passed to Postgres with set_config(..., is_local => true), so it
is scoped to the current transaction and can never leak to the next user of a
pooled connection. RLS policies (see migrations) read it via app_org_id() and
app_user_id().

Because the setting is transaction-local, it is stored on the Session and
re-applied at the start of *every* transaction (after_begin). Otherwise a query
issued after commit() would silently run with no tenant and see no rows.
"""

from __future__ import annotations

import uuid
from collections.abc import Iterator

from sqlalchemy import create_engine, event, text
from sqlalchemy.orm import Session, sessionmaker

from app.core.config import settings

engine = create_engine(settings.database_url, pool_pre_ping=True, pool_size=10, max_overflow=20)
SessionLocal = sessionmaker(bind=engine, expire_on_commit=False)

_TENANT_KEYS = ("org_id", "user_id")


def _apply(connection, info: dict) -> None:
    for key in _TENANT_KEYS:
        if info.get(key) is not None:
            connection.execute(
                text("SELECT set_config(:k, :v, true)"), {"k": f"app.{key}", "v": str(info[key])}
            )


@event.listens_for(Session, "after_begin")
def _apply_tenant(session: Session, transaction, connection) -> None:
    _apply(connection, session.info)


def set_tenant(
    db: Session, org_id: uuid.UUID | None = None, user_id: uuid.UUID | None = None
) -> None:
    if org_id is not None:
        db.info["org_id"] = org_id
    if user_id is not None:
        db.info["user_id"] = user_id
    if db.in_transaction():
        _apply(db.connection(), db.info)


def get_db() -> Iterator[Session]:
    db = SessionLocal()
    try:
        yield db
    finally:
        db.rollback()  # no-op if the endpoint committed
        db.close()

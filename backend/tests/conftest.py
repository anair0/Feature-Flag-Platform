"""Test harness: a real Postgres database with the production role layout.

Migrations run as the owner role; the app connects as the non-superuser app role,
so row-level security is enforced in tests exactly as in production.

Set TEST_ADMIN_DATABASE_URL to a superuser connection (default: local postgres).
"""

from __future__ import annotations

import os
import uuid

import psycopg
import pytest

ADMIN_URL = os.environ.get(
    "TEST_ADMIN_DATABASE_URL", "postgresql://postgres:postgres@localhost:5432/postgres"
)
DB = os.environ.get("TEST_DATABASE_NAME", "flags_test")
HOST = psycopg.conninfo.conninfo_to_dict(ADMIN_URL)
HOSTPORT = f"{HOST.get('host', 'localhost')}:{HOST.get('port', 5432)}"
OWNER_URL = f"postgresql+psycopg://flags_owner:flags_owner@{HOSTPORT}/{DB}"
APP_URL = f"postgresql+psycopg://flags_app:flags_app@{HOSTPORT}/{DB}"

os.environ["DATABASE_URL"] = APP_URL
os.environ["MIGRATION_DATABASE_URL"] = OWNER_URL
os.environ["RATE_LIMIT_ENABLED"] = "false"
os.environ["STREAM_HEARTBEAT_SECONDS"] = "1"

TABLES = (
    "events, sdk_change_log, audit_log, flag_configs, flags, sdk_keys, environments, "
    "projects, memberships, organizations, users"
)


def _create_database() -> None:
    with psycopg.connect(ADMIN_URL, autocommit=True) as conn:
        for role in ("flags_owner", "flags_app"):
            exists = conn.execute("SELECT 1 FROM pg_roles WHERE rolname = %s", (role,)).fetchone()
            if not exists:
                conn.execute(f"CREATE ROLE {role} LOGIN PASSWORD '{role}'")
        conn.execute(f"DROP DATABASE IF EXISTS {DB} WITH (FORCE)")
        conn.execute(f"CREATE DATABASE {DB} OWNER flags_owner")

    from alembic import command
    from alembic.config import Config

    cfg = Config(os.path.join(os.path.dirname(__file__), "..", "alembic.ini"))
    cfg.set_main_option(
        "script_location", os.path.join(os.path.dirname(__file__), "..", "migrations")
    )
    cfg.set_main_option("sqlalchemy.url", OWNER_URL)
    command.upgrade(cfg, "head")


_create_database()

from fastapi.testclient import TestClient  # noqa: E402

from app.main import app  # noqa: E402


def owner_conn() -> psycopg.Connection:
    return psycopg.connect(OWNER_URL.replace("+psycopg", ""), autocommit=True)


@pytest.fixture(autouse=True)
def clean_db():
    yield
    with owner_conn() as conn:
        conn.execute(f"TRUNCATE {TABLES} RESTART IDENTITY CASCADE")


@pytest.fixture(scope="session")
def client():
    with TestClient(app) as c:
        yield c


class Account:
    """A signed-up user with their own org, plus helpers for its API."""

    def __init__(self, client: TestClient, email: str | None = None, org: str = "Acme"):
        self.client = client
        self.email = email or f"{uuid.uuid4().hex[:8]}@example.com"
        r = client.post(
            "/api/auth/signup",
            json={
                "email": self.email,
                "password": "correct horse",
                "name": "Test",
                "org_name": org,
            },
        )
        assert r.status_code == 201, r.text
        body = r.json()
        self.token, self.user_id, self.org_id = body["token"], body["user_id"], body["org_id"]

    @property
    def headers(self) -> dict:
        return {"Authorization": f"Bearer {self.token}"}

    def url(self, path: str = "", org_id: str | None = None) -> str:
        return f"/api/orgs/{org_id or self.org_id}{path}"

    def get(self, path, **kw):
        return self.client.get(self.url(path), headers=self.headers, **kw)

    def post(self, path, json=None, **kw):
        return self.client.post(self.url(path), headers=self.headers, json=json, **kw)

    def put(self, path, json=None, headers=None, **kw):
        return self.client.put(
            self.url(path), headers={**self.headers, **(headers or {})}, json=json, **kw
        )

    def patch(self, path, json=None, **kw):
        return self.client.patch(self.url(path), headers=self.headers, json=json, **kw)

    def delete(self, path, **kw):
        return self.client.delete(self.url(path), headers=self.headers, **kw)

    # -- convenience
    def create_flag(self, key="new-checkout", **kw):
        r = self.post("/projects/default/flags", {"key": key, "name": key, **kw})
        assert r.status_code == 201, r.text
        return r.json()

    def config(self, key, env="production"):
        return self.get(f"/projects/default/flags/{key}").json()["environments"][env]

    def set_config(self, key, env, body, version=None):
        if version is None:
            version = self.config(key, env)["version"]
        return self.put(
            f"/projects/default/flags/{key}/environments/{env}",
            body,
            headers={"If-Match": f'"{version}"'},
        )

    def keys(self, env="production"):
        r = self.post(f"/projects/default/environments/{env}/keys/rotate", {"kind": "server"})
        assert r.status_code == 200, r.text
        server = r.json()["value"]
        client_id = next(
            k["value"]
            for k in self.get(f"/projects/default/environments/{env}/keys").json()
            if k["kind"] == "client"
        )
        return server, client_id

    def invite(self, other: Account, role: str):
        r = self.post("/members", {"email": other.email, "role": role})
        assert r.status_code == 201, r.text


@pytest.fixture
def account(client) -> Account:
    return Account(client)


@pytest.fixture
def make_account(client):
    return lambda **kw: Account(client, **kw)


ON = {"on": True, "off_variation": 1, "targets": [], "rules": [], "fallthrough": {"variation": 0}}

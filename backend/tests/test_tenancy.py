"""Attempts to break tenant isolation, at the API and directly in the database."""

import uuid

import psycopg
import pytest

from .conftest import APP_URL, ON


@pytest.fixture
def two_orgs(make_account):
    a, b = make_account(org="Alpha"), make_account(org="Beta")
    a.create_flag("alpha-secret")
    a.set_config("alpha-secret", "production", ON)
    return a, b


def test_cannot_read_another_orgs_resources(two_orgs):
    a, b = two_orgs
    paths = [
        "/projects",
        "/projects/default",
        "/projects/default/flags",
        "/projects/default/flags/alpha-secret",
        "/members",
        "/audit",
        "/projects/default/environments/production/keys",
    ]
    for path in paths:
        r = b.client.get(a.url(path), headers=b.headers)
        assert r.status_code == 404, (path, r.status_code)  # 404: don't confirm existence


def test_cannot_write_another_orgs_resources(two_orgs):
    a, b = two_orgs
    h = {**b.headers, "If-Match": '"2"'}
    attempts = [
        (
            "put",
            "/projects/default/flags/alpha-secret/environments/production",
            {**ON, "on": False},
        ),
        ("post", "/projects/default/flags", {"key": "planted", "name": "x"}),
        ("post", "/projects/default/flags/alpha-secret/archive", None),
        ("post", "/members", {"email": b.email, "role": "owner"}),
        ("post", "/projects/default/environments/production/keys/rotate", {"kind": "server"}),
        ("post", "/projects", {"key": "evil", "name": "x"}),
    ]
    for method, path, body in attempts:
        r = getattr(b.client, method)(a.url(path), headers=h, json=body)
        assert r.status_code == 404, (path, r.status_code)
    assert a.config("alpha-secret")["on"] is True


def test_sdk_key_only_sees_its_own_environment(two_orgs):
    a, b = two_orgs
    b_server, _ = b.keys()
    flags = b.client.get("/sdk/v1/flags", headers={"Authorization": b_server}).json()["flags"]
    assert "alpha-secret" not in flags


def _as_app_role(org_id=None):
    conn = psycopg.connect(APP_URL.replace("+psycopg", ""))
    if org_id:
        conn.execute("SELECT set_config('app.org_id', %s, true)", (str(org_id),))
    return conn


def test_rls_blocks_unfiltered_queries(two_orgs):
    """Layer 2: even a query with NO org filter (an app bug) sees only the current tenant."""
    a, b = two_orgs
    with _as_app_role(b.org_id) as conn:
        keys = [r[0] for r in conn.execute("SELECT key FROM flags")]
        assert "alpha-secret" not in keys
        assert (
            conn.execute(
                "SELECT count(*) FROM audit_log WHERE org_id = %s", (a.org_id,)
            ).fetchone()[0]
            == 0
        )
        assert conn.execute("SELECT count(*) FROM sdk_keys").fetchone()[0] == 3 * 2


def test_rls_without_tenant_sees_nothing(two_orgs):
    with _as_app_role() as conn:
        for table in (
            "flags",
            "flag_configs",
            "projects",
            "environments",
            "sdk_keys",
            "audit_log",
            "events",
            "organizations",
            "memberships",
        ):
            assert conn.execute(f"SELECT count(*) FROM {table}").fetchone()[0] == 0, table


def test_rls_blocks_cross_tenant_writes(two_orgs):
    a, b = two_orgs
    with _as_app_role(b.org_id) as conn:
        # Unfiltered UPDATE: B has no flags, so RLS must leave A's 3 configs untouched.
        assert conn.execute('UPDATE flag_configs SET "on" = false').rowcount == 0
        conn.commit()
    with _as_app_role(b.org_id) as conn:
        with pytest.raises(psycopg.errors.InsufficientPrivilege):
            conn.execute(
                "INSERT INTO projects (id, org_id, key, name) VALUES (%s, %s, 'x', 'x')",
                (uuid.uuid4(), a.org_id),
            )
    assert a.config("alpha-secret")["on"] is True


def test_audit_log_is_append_only_for_the_app(two_orgs):
    a, _ = two_orgs
    with _as_app_role(a.org_id) as conn:
        with pytest.raises(psycopg.errors.InsufficientPrivilege):
            conn.execute("UPDATE audit_log SET action = 'forged'")
    with _as_app_role(a.org_id) as conn:
        with pytest.raises(psycopg.errors.InsufficientPrivilege):
            conn.execute("DELETE FROM audit_log")


def test_app_role_cannot_bypass_rls(two_orgs):
    with _as_app_role() as conn:
        with pytest.raises(psycopg.errors.InsufficientPrivilege):
            conn.execute("ALTER TABLE flags DISABLE ROW LEVEL SECURITY")

"""Initial schema with row-level security.

Revision ID: 0001
Revises:
"""

import os

from alembic import op

revision = "0001"
down_revision = None
branch_labels = None
depends_on = None

APP_ROLE = os.environ.get("APP_DB_ROLE", "flags_app")

# Tables isolated by a plain org_id = current tenant policy.
TENANT_TABLES = [
    "projects",
    "environments",
    "sdk_keys",
    "flags",
    "flag_configs",
    "audit_log",
    "sdk_change_log",
    "events",
]

SCHEMA = """
CREATE TABLE organizations (
    id uuid PRIMARY KEY,
    name varchar(200) NOT NULL,
    created_at timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE users (
    id uuid PRIMARY KEY,
    email varchar(320) NOT NULL UNIQUE,
    name varchar(200) NOT NULL,
    password_hash text NOT NULL,
    created_at timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE memberships (
    org_id uuid NOT NULL REFERENCES organizations(id) ON DELETE CASCADE,
    user_id uuid NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    role varchar(20) NOT NULL CHECK (role IN ('reader', 'writer', 'admin', 'owner')),
    created_at timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (org_id, user_id)
);
CREATE INDEX memberships_user_idx ON memberships(user_id);

CREATE TABLE projects (
    id uuid PRIMARY KEY,
    org_id uuid NOT NULL REFERENCES organizations(id) ON DELETE CASCADE,
    key varchar(100) NOT NULL,
    name varchar(200) NOT NULL,
    created_at timestamptz NOT NULL DEFAULT now(),
    UNIQUE (org_id, key)
);

CREATE TABLE environments (
    id uuid PRIMARY KEY,
    org_id uuid NOT NULL REFERENCES organizations(id) ON DELETE CASCADE,
    project_id uuid NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
    key varchar(100) NOT NULL,
    name varchar(200) NOT NULL,
    protected boolean NOT NULL DEFAULT false,
    sort_order integer NOT NULL DEFAULT 0,
    data_version bigint NOT NULL DEFAULT 0,
    created_at timestamptz NOT NULL DEFAULT now(),
    UNIQUE (project_id, key)
);

CREATE TABLE sdk_keys (
    id uuid PRIMARY KEY,
    org_id uuid NOT NULL REFERENCES organizations(id) ON DELETE CASCADE,
    environment_id uuid NOT NULL REFERENCES environments(id) ON DELETE CASCADE,
    kind varchar(10) NOT NULL CHECK (kind IN ('server', 'client')),
    key_hash varchar(64) NOT NULL UNIQUE,
    hint varchar(20) NOT NULL,
    public_value text,
    created_at timestamptz NOT NULL DEFAULT now(),
    expires_at timestamptz
);

CREATE TABLE flags (
    id uuid PRIMARY KEY,
    org_id uuid NOT NULL REFERENCES organizations(id) ON DELETE CASCADE,
    project_id uuid NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
    key varchar(100) NOT NULL,
    name varchar(200) NOT NULL,
    description text NOT NULL DEFAULT '',
    kind varchar(10) NOT NULL CHECK (kind IN ('boolean', 'string', 'number', 'json')),
    variations jsonb NOT NULL,
    salt varchar(100) NOT NULL,
    client_side boolean NOT NULL DEFAULT false,
    archived boolean NOT NULL DEFAULT false,
    created_by uuid,
    created_at timestamptz NOT NULL DEFAULT now(),
    UNIQUE (project_id, key)
);

CREATE TABLE flag_configs (
    id uuid PRIMARY KEY,
    org_id uuid NOT NULL REFERENCES organizations(id) ON DELETE CASCADE,
    flag_id uuid NOT NULL REFERENCES flags(id) ON DELETE CASCADE,
    environment_id uuid NOT NULL REFERENCES environments(id) ON DELETE CASCADE,
    "on" boolean NOT NULL DEFAULT false,
    off_variation integer,
    targets jsonb NOT NULL DEFAULT '[]',
    rules jsonb NOT NULL DEFAULT '[]',
    fallthrough jsonb NOT NULL,
    version integer NOT NULL DEFAULT 1,
    updated_by uuid,
    updated_at timestamptz NOT NULL DEFAULT now(),
    UNIQUE (flag_id, environment_id)
);

CREATE TABLE audit_log (
    id bigserial PRIMARY KEY,
    org_id uuid NOT NULL REFERENCES organizations(id) ON DELETE CASCADE,
    project_id uuid,
    environment_id uuid,
    actor_id uuid,
    action varchar(50) NOT NULL,
    resource_type varchar(30) NOT NULL,
    resource_key varchar(200) NOT NULL,
    before jsonb,
    after jsonb,
    created_at timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX audit_log_lookup_idx ON audit_log(org_id, project_id, resource_key, created_at DESC);

CREATE TABLE sdk_change_log (
    id bigserial PRIMARY KEY,
    org_id uuid NOT NULL REFERENCES organizations(id) ON DELETE CASCADE,
    environment_id uuid NOT NULL REFERENCES environments(id) ON DELETE CASCADE,
    env_version bigint NOT NULL,
    flag_key varchar(100) NOT NULL,
    data jsonb,
    created_at timestamptz NOT NULL DEFAULT now(),
    UNIQUE (environment_id, env_version)
);

CREATE TABLE events (
    id bigserial PRIMARY KEY,
    org_id uuid NOT NULL REFERENCES organizations(id) ON DELETE CASCADE,
    environment_id uuid NOT NULL REFERENCES environments(id) ON DELETE CASCADE,
    kind varchar(20) NOT NULL CHECK (kind IN ('exposure', 'custom')),
    user_id varchar(200) NOT NULL,
    flag_key varchar(100),
    variation_index integer,
    metric_key varchar(100),
    value double precision,
    ts timestamptz NOT NULL,
    received_at timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX events_exposure_idx ON events(environment_id, flag_key, user_id) WHERE kind = 'exposure';
CREATE INDEX events_metric_idx ON events(environment_id, metric_key, user_id) WHERE kind = 'custom';

-- Tenant context, set per transaction by the app (see app/db/session.py).
-- NULLIF: after a transaction-local setting resets, current_setting returns '' not NULL.
CREATE FUNCTION app_org_id() RETURNS uuid LANGUAGE sql STABLE AS
$$ SELECT NULLIF(current_setting('app.org_id', true), '')::uuid $$;
CREATE FUNCTION app_user_id() RETURNS uuid LANGUAGE sql STABLE AS
$$ SELECT NULLIF(current_setting('app.user_id', true), '')::uuid $$;
"""

RLS = """
-- Organizations: visible if it's the current tenant or the current user is a member.
ALTER TABLE organizations ENABLE ROW LEVEL SECURITY;
ALTER TABLE organizations FORCE ROW LEVEL SECURITY;
CREATE POLICY org_select ON organizations FOR SELECT
    USING (id = app_org_id() OR id IN (SELECT org_id FROM memberships WHERE user_id = app_user_id()));
CREATE POLICY org_insert ON organizations FOR INSERT WITH CHECK (id = app_org_id());
CREATE POLICY org_update ON organizations FOR UPDATE USING (id = app_org_id());
CREATE POLICY org_delete ON organizations FOR DELETE USING (id = app_org_id());

-- Memberships: a tenant sees its members; a user sees their own memberships (to list orgs).
ALTER TABLE memberships ENABLE ROW LEVEL SECURITY;
ALTER TABLE memberships FORCE ROW LEVEL SECURITY;
CREATE POLICY membership_select ON memberships FOR SELECT
    USING (org_id = app_org_id() OR user_id = app_user_id());
CREATE POLICY membership_write ON memberships FOR ALL
    USING (org_id = app_org_id()) WITH CHECK (org_id = app_org_id());
"""


def upgrade() -> None:
    op.execute(SCHEMA)
    op.execute(RLS)
    for table in TENANT_TABLES:
        op.execute(f"ALTER TABLE {table} ENABLE ROW LEVEL SECURITY")
        op.execute(f"ALTER TABLE {table} FORCE ROW LEVEL SECURITY")
        op.execute(
            f"CREATE POLICY tenant_isolation ON {table} "
            "USING (org_id = app_org_id()) WITH CHECK (org_id = app_org_id())"
        )

    # SDK requests arrive with only a key: the tenant is unknown until the key is resolved.
    # This SECURITY DEFINER function is the single, narrow way across the RLS boundary.
    # It runs as the table owner, who gets a SELECT-only policy on sdk_keys.
    op.execute("CREATE POLICY owner_key_lookup ON sdk_keys FOR SELECT TO CURRENT_USER USING (true)")
    op.execute("""
        CREATE FUNCTION resolve_sdk_key(p_hash text)
        RETURNS TABLE (environment_id uuid, org_id uuid, kind varchar)
        LANGUAGE sql STABLE SECURITY DEFINER SET search_path = public AS $$
            SELECT environment_id, org_id, kind FROM sdk_keys
            WHERE key_hash = p_hash AND (expires_at IS NULL OR expires_at > now())
        $$
    """)
    op.execute("REVOKE ALL ON FUNCTION resolve_sdk_key(text) FROM PUBLIC")

    # Runtime role: data access only, no DDL, and the audit log is append-only.
    op.execute(f"""
        DO $$ BEGIN
            IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = '{APP_ROLE}') THEN
                GRANT SELECT, INSERT, UPDATE, DELETE ON ALL TABLES IN SCHEMA public TO {APP_ROLE};
                GRANT USAGE ON ALL SEQUENCES IN SCHEMA public TO {APP_ROLE};
                REVOKE UPDATE, DELETE ON audit_log FROM {APP_ROLE};
                REVOKE UPDATE ON events, sdk_change_log FROM {APP_ROLE};
                GRANT EXECUTE ON FUNCTION resolve_sdk_key(text) TO {APP_ROLE};
                GRANT EXECUTE ON FUNCTION app_org_id(), app_user_id() TO {APP_ROLE};
            END IF;
        END $$
    """)


def downgrade() -> None:
    op.execute("""
        DROP FUNCTION IF EXISTS resolve_sdk_key(text);
        DROP TABLE IF EXISTS events, sdk_change_log, audit_log, flag_configs, flags, sdk_keys,
            environments, projects, memberships, users, organizations CASCADE;
        DROP FUNCTION IF EXISTS app_org_id(), app_user_id();
    """)

# Architecture

```
                     ┌──────────────── Dashboard (React) ────────────────┐
                     │ JWT bearer  /api/...                              │
                     ▼                                                   │
 ┌──────────────────────────────── API process (FastAPI) ×N ─────────────┴───────────┐
 │  auth · RBAC (core/permissions) · tenant context (api/deps)                       │
 │  services/flags: validate → UPDATE … WHERE version = :v → publish → audit → COMMIT│
 │  services/broadcaster: LISTEN flag_changes → load change → push to local streams  │
 │  /sdk/v1/flags  /sdk/v1/stream (SSE)  /sdk/v1/evaluate  /sdk/v1/client-stream     │
 └──────────────┬──────────────────────────────────────────────▲──────────┬─────────┘
                │ one transaction                              │ NOTIFY   │ SSE
                ▼                                              │          ▼
 ┌──────────────────────── PostgreSQL ─────────────────────────┴─┐   ┌─────────────────────┐
 │ flag_configs (version)   environments (data_version)          │   │ Server SDK (Py/Node)│
 │ sdk_change_log           audit_log (append-only for the app)  │   │  in-memory store    │
 │ events                   RLS on every tenant table            │   │  local evaluation   │
 └───────────────────────────────────────────────────────────────┘   └─────────────────────┘
                                                                     ┌─────────────────────┐
                                    POST /evaluate, change pings ───►│ Browser SDK         │
                                                                     │  values only        │
                                                                     └─────────────────────┘
```

## Data model

```
organizations ─┬─ memberships (user, role) ── users
               └─ projects ─┬─ environments ─┬─ sdk_keys (hashed; server | client)
                            │   data_version  └─ sdk_change_log (env_version, flag, data)
                            └─ flags ─────────── flag_configs (one per flag × environment)
                               key, kind,          on, off_variation, targets, rules,
                               variations, salt    fallthrough, version
audit_log   (before/after JSONB, actor, environment)
events      (exposure | custom; for experiments)
```

A **flag** exists once per project: its key, type and variations. Its **targeting** lives in
`flag_configs`, one row per environment, so it can be on in development and off in production.

## The life of a change

1. The PM edits targeting in the dashboard. The editor remembers the config `version` it
   loaded and sends it as `If-Match`.
2. `PUT …/flags/{key}/environments/{env}`:
   - `org_context` checks membership and sets the Postgres tenant (`app.org_id`).
   - `require("config.update", protected_env=…)`: writers can't touch protected environments.
   - Pydantic validates structure; `semantic_errors` validates against the flag's variations
     (indexes exist, weights sum to 100%, no user targeted twice, unique rule ids).
   - `UPDATE flag_configs … WHERE id = :id AND version = :expected` returns zero rows if
     someone saved in between. That raises **409**, and the dashboard shows a diff and lets
     the user choose.
   - `publish()` increments `environments.data_version` (row lock: per-environment
     serialization), inserts the wire-format flag into `sdk_change_log`, and
     `pg_notify`s. NOTIFY is transactional: it's delivered only if the commit succeeds.
   - `audit.record()` adds the before/after entry.
   - **One `COMMIT`** for all of the above.
3. Every API process's `Broadcaster` hears the NOTIFY, reads that exact change row and
   pushes it to that environment's open streams as `event: patch`.
4. Each SDK applies the patch if `env_version == current + 1`, ignores it if older, and
   re-fetches the full snapshot if it detects a gap.
5. The next `client.bool(...)` call evaluates against the new rules in memory, with no network.

## Evaluation

`evaluate(flag, user) -> {value, variation_index, reason}` is a pure function, specified in
[spec/evaluation.md](../spec/evaluation.md) and implemented twice:
`sdks/python/src/featureflags/evaluation.py` and `sdks/typescript/src/evaluation.ts`.
The backend imports the Python one for browser evaluation and the dashboard's "test a user"
panel, so there is no third implementation to drift.

Order: invalid user → off → individual targets → rules (first match) → default rule.
Rollouts hash `salt + "." + user_id` with SHA-1, take the first 32 bits mod 100,000, and walk
cumulative weights. This makes assignment sticky, monotonic as percentages rise, and independent across flags.

## Multi-tenancy, in three layers

1. **Application.** Every org-scoped route resolves `org_context`, which returns 404 (not 403,
   so existence isn't confirmed) for non-members. Every query also filters by `org_id`.
2. **Database.** Row-level security on every tenant table (`org_id = app_org_id()`), with
   `FORCE ROW LEVEL SECURITY` so even the table owner is subject to it. The API connects as
   `flags_app`, which is not a superuser, not the owner, and can't `ALTER TABLE`. The tenant is set with
   transaction-local `set_config` and re-applied at every transaction start
   (`db/session.py`), so a pooled connection can't carry one tenant into another request.
   SDK requests arrive with only a key; `resolve_sdk_key()` is the one narrow
   `SECURITY DEFINER` path across the boundary.
3. **Tests that attack it.** `tests/test_tenancy.py` sends org B's token at every org A URL,
   then connects as the app role and runs *unfiltered* `SELECT`/`UPDATE`/`INSERT`s to
   prove RLS alone holds.

## Access control

| | reader | writer | admin | owner |
|---|---|---|---|---|
| view flags, history, results | ✓ | ✓ | ✓ | ✓ |
| create flags, edit targeting (unprotected envs) | | ✓ | ✓ | ✓ |
| edit targeting in **protected** envs (production) | | | ✓ | ✓ |
| archive flags, environments, SDK keys, members | | | ✓ | ✓ |
| grant or remove owners | | | | ✓ |

The policy is one pure function (`backend/app/core/permissions.py`), unit-tested on its own.
The dashboard mirrors it only to disable controls; the server is the authority.

## Experiments

When a rollout is marked `kind: "experiment"`, evaluations carry `in_experiment: true` and SDKs
send a deduplicated **exposure** event. `track(user, "purchase", 49.99)` sends **metric**
events. Results (`services/experiments.py` + `services/stats.py`):

- Each user counts once, in the variation first seen. Users exposed to several variations are excluded and reported.
- Only conversions *after* first exposure count.
- **SRM check**: a chi-square test of group sizes against the configured split. If p < 0.001,
  results are marked invalid, because assignment is broken.
- **Peeking guard**: nothing is "significant" until each group reaches the planned sample size.
- **Bonferroni** correction across treatment-vs-control comparisons.
- Wilson intervals for rates, two-proportion z-tests for differences. An A/A simulation test
  checks the false-positive rate stays near α.

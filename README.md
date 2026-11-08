# Feature-Flag-Platform

A multi-tenant feature flag platform: a miniature LaunchDarkly. Teams create flags in a
web dashboard, target them by user attributes and percentage rollouts per environment,
and applications evaluate them locally through SDKs that receive changes in real time.

```python
if flags.bool("new-checkout", {"id": user.id, "country": "CA"}, default=False):
    show_new_checkout()
```

Flip the flag in the dashboard and every running SDK picks it up in tens of milliseconds,
without a deploy.

| | |
|---|---|
| **Backend** | FastAPI + PostgreSQL. RBAC, row-level-security multi-tenancy, optimistic concurrency, transactional audit log, SSE fan-out via LISTEN/NOTIFY |
| **Dashboard** | React + TypeScript. Rule builder, rollouts, conflict resolution, "why did this user get this?", audit diffs, experiment results |
| **SDKs** | Python and TypeScript (Node + browser). Local evaluation, streaming updates, never throws, identical answers enforced by shared test vectors and differential fuzzing |
| **Experiments** | Exposure/metric events, conversion stats with SRM detection, a peeking guard, and multiple-comparison correction |

## Measured

| What | Result | How |
|---|---|---|
| Dashboard save → Python SDK sees it | **~33 ms** | `backend/tests/test_streaming_e2e.py` (separate API process, real SDK) |
| Kill switch → browser page re-renders | **~49 ms** | demo app, headless Chromium |
| One change → 1,000 concurrent SDK streams | **p50 48 ms, p99 91 ms**, 0 errors | `scripts/load_test.py`, single API process |
| Python vs TypeScript engine agreement | **20,000 / 20,000** random cases | `scripts/cross_sdk_fuzz.py` (in CI) |

## Quick start

**Everything in Docker:**

```bash
docker compose up --build
```

The dashboard is at http://localhost:8080 and the API at http://localhost:8000 (OpenAPI at `/docs`).
Sign up to create an organization; you get a default project with `development`,
`staging` and a protected `production` environment.

**Demo: flip a switch, watch an app change.** With the stack running:

```bash
python scripts/seed_demo.py
```

```bash
cd demo-app && npm install && npm run dev
```

Open http://localhost:5174, then log into the dashboard with the printed credentials and toggle
`new-checkout` in Development. `python demo-app/server_demo.py <server-key>` shows the same
thing from the Python SDK in a terminal.

**Local development** (Postgres 16 running locally):

```bash
psql -U postgres -f deploy/postgres-init.sql
```

```bash
pip install -e sdks/python -e "backend[dev]"
```

```bash
cd backend && alembic upgrade head && uvicorn app.main:app --reload
```

```bash
cd dashboard && npm install && npm run dev
```

The dashboard dev server is http://localhost:5173 and proxies `/api` to the API.

## Tests

```bash
cd sdks/python && pytest
```

```bash
cd sdks/typescript && npm test
```

```bash
cd backend && pytest
```

```bash
python scripts/cross_sdk_fuzz.py
```

| Suite | Tests | Highlights |
|---|---|---|
| Python SDK | 132 | 111 shared spec vectors, rollout properties, reconnect/resync/outage against a fake server |
| TypeScript SDK | 133 | the same 111 vectors, SHA-1 known answers, Node + browser clients |
| Backend | 83 | real Postgres with production roles; cross-tenant attacks at the API *and* directly in SQL; end-to-end streaming; A/A false-positive simulation |
| Cross-SDK fuzz | 20,000 cases | random flags × users, Python and TypeScript must agree exactly |

The backend tests need a Postgres superuser to create a throwaway database:
`TEST_ADMIN_DATABASE_URL` (default `postgresql://postgres:postgres@localhost:5432/postgres`).

## Repository

```
spec/            The contract: flag format, evaluation algorithm, delivery protocol, test vectors
sdks/python/     Python SDK; its evaluation engine is also used by the backend
sdks/typescript/ TypeScript SDK: Node (local evaluation) and browser (remote evaluation)
backend/         FastAPI app, Alembic migrations (schema + RLS), tests
dashboard/       React app
demo-app/        Demo store (browser SDK) and terminal demo (Python SDK)
scripts/         seed_demo, load_test, cross_sdk_fuzz
deploy/          Postgres role setup
docs/            architecture.md, design-decisions.md, PLAN.md
```

Start with [docs/architecture.md](docs/architecture.md) for how it fits together and
[docs/design-decisions.md](docs/design-decisions.md) for the trade-offs.

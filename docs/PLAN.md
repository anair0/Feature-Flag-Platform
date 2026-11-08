# Implementation plan and status

All phases are implemented. Each row says where the code and tests live.

| Phase | What | Where |
|---|---|---|
| 0. Spec | Flag format, evaluation algorithm, delivery protocol, 111 hand-written vectors | `spec/` |
| 1. Evaluation engine | Pure `evaluate(flag, user)`; Python, then a TypeScript port | `sdks/python/src/featureflags/evaluation.py`, `sdks/typescript/src/evaluation.ts` |
| 2. Backend CRUD + audit | Flags, per-env configs, If-Match/409, audit in the same transaction | `backend/app/services/flags.py`, `backend/tests/test_flags.py` |
| 3. Auth, RBAC, tenancy | scrypt + JWT, role policy, RLS with a non-owner runtime role, attack tests | `backend/app/core/`, `backend/migrations/`, `backend/tests/test_rbac.py`, `test_tenancy.py` |
| 4. SDK delivery | Snapshot, SSE patches with env versions, LISTEN/NOTIFY fan-out, browser evaluate | `backend/app/api/sdk.py`, `backend/app/services/broadcaster.py` |
| 5. SDKs | Python + TypeScript (Node, browser): streaming, resync, backoff, events, never-throw | `sdks/`, plus `scripts/cross_sdk_fuzz.py` |
| 6. Dashboard | Flags, rule builder, rollouts, conflict dialog, evaluator, audit, keys, team | `dashboard/` |
| 7. Demo + hardening | Demo store, seed script, rate limits, key rotation, load test, Docker, CI | `demo-app/`, `scripts/`, `docker-compose.yml`, `.github/workflows/ci.yml` |
| 8. Experiments | Exposure/metric events, SRM, peeking guard, Bonferroni, results UI | `backend/app/services/stats.py`, `experiments.py`, `dashboard/src/components/Experiment.tsx` |

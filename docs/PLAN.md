# Implementation plan

0. **Spec**: config format, evaluation algorithm, shared test vectors (`spec/`)
1. **Evaluation engine**: pure `evaluate(config, user) -> (value, reason)`; Python then TypeScript
2. **Backend CRUD + audit**: flags, per-environment configs, optimistic concurrency, audit in same transaction
3. **Auth, RBAC, multi-tenancy**: roles, production restrictions, Postgres RLS, cross-tenant tests
4. **SDK delivery**: snapshot endpoint, SSE stream, versioned patches, browser evaluate endpoint
5. **SDKs**: Python and TypeScript with local store, streaming, backoff, never-throw guarantees
6. **Dashboard**: flag list, rule builder, rollout slider, test evaluator, audit view, conflict handling
7. **Demo and hardening**: demo app, rate limits, load and failure tests, CI
8. **(Optional) Experiments**: exposure events, stats, SRM check

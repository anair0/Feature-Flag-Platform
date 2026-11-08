# Feature-Flag-Platform

Multi-tenant feature flag platform with a rules engine, live-updating SDKs, and a React dashboard.

## Layout

| Path | Purpose |
|---|---|
| `spec/` | Flag config format, evaluation algorithm, shared test vectors (the contract every SDK must pass) |
| `backend/` | FastAPI + PostgreSQL API: flags, auth/RBAC, audit log, SDK delivery (REST + SSE) |
| `dashboard/` | React + TypeScript web UI |
| `sdks/python/` | Python SDK (local evaluation, streaming updates) |
| `sdks/typescript/` | TypeScript SDK (Node local evaluation + browser remote evaluation) |
| `demo-app/` | Small app that reacts live to flag changes |
| `docs/` | Architecture and design decisions |

## Status

Scaffold only. See [docs/PLAN.md](docs/PLAN.md) for the phased implementation plan.

## Quick start

```bash
cp .env.example .env
docker compose up -d db     # PostgreSQL
```

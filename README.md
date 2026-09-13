# Agent Hub

Agent Hub is a hosted, extensible agent workspace. This repository currently contains the general-purpose foundation; structural-engineering Plugins are later work.

Read [FOUNDATION.md](FOUNDATION.md) for the product direction and [the system architecture](docs/architecture/system-architecture.md) before changing the implementation.

## Prerequisites

- Node.js 22; the Makefile bootstraps the pnpm version declared in `package.json`
- Python 3.12–3.14 and uv 0.11.15 or compatible
- Docker with Compose for the complete local stack

## Developer commands

```sh
make setup             # install from both lockfiles
make dev               # build and run web, API, and PostgreSQL
make contracts         # regenerate Python and TypeScript contracts
make contracts-check   # fail if generated contracts are stale
make format-check
make lint
make typecheck
make test
make build
make acceptance        # run the complete local verification suite
make migrate           # apply API database migrations
```

Copy `.env.example` to `.env` only when running services outside Docker. The foundation health endpoints are:

- API: `/health/live` and `/health/ready`
- Web: `/api/health/live` and `/api/health/ready`

Liveness reports that the process can serve requests. Readiness also checks required dependencies, so it can fail while liveness remains healthy.

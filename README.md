# Agent Hub

Agent Hub is a hosted, extensible agent workspace. This repository currently contains the general-purpose foundation; structural-engineering Plugins are later work.

Read [FOUNDATION.md](FOUNDATION.md) for the product direction, [the system architecture](docs/architecture/system-architecture.md), and [the code structure contract](docs/architecture/code-structure.md) before changing the implementation.

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
make architecture-check
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

Project and Thread management run without a model credential. Set
`AGENT_HUB_OPENAI_API_KEY` (or the conventional `OPENAI_API_KEY`) to execute the
Deep Agent; the key stays behind the same-origin web proxy and is never exposed
to browser code.

Production identity is supplied by the hosting platform. See [the platform identity contract](docs/deployment/identity.md) before exposing Agent Hub through an ingress.

The standalone [IFC viewer MCP App](plugins/ifc-viewer/README.md) renders IFC models,
inspects object properties, and colours metadata or mapped calculation results.

See the [MCP App development guide](docs/architecture/mcp-app-development.md) for
Plugin packaging, agent instructions, viewport layouts and embedded testing.

## PDF and DOCX sources

In **Library**, use **Upload PDF or DOCX**. PDFs open with page navigation and zoom;
**Extracted Markdown** shows searchable text, and **Download original** preserves the
exact upload. DOCX provides extracted text and its original download. Extraction
warnings identify pages requiring OCR or visual inspection; OCR is not automatic.

The agent can discover sources with `list_project_documents`, search generated
`/project/.documents/<id>/` Markdown using normal `glob`/`grep`/`read_file`, and
inspect an original PDF page with `view_project_document_page`. Generated files
are protected from generic edits. Agent Hub owns original bytes and all derived
state; no external document index is required. See [ADR 0018](docs/adr/0018-ingest-documents-into-project-files.md)
for limits, ownership and lifecycle. Apply migrations through `0030_project_documents`.

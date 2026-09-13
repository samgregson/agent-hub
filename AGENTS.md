# Agent guidance

## Coding direction

- The backend is Python and uses LangChain Deep Agents.
- The frontend is React with Next.js and uses assistant-ui's open-source offering.
- Keep the foundation general-purpose, modular, and extensible through MCP and MCP Apps.
- Calculation, diagram, and structural-engineering apps are later work; do not add them to the foundation prematurely.
- No formatting, naming, or code-organization preferences have been specified yet. Do not invent personal preferences for the maintainer.

## Navigating the codebase

- Read `FOUNDATION.md` before planning architecture or implementation.
- Read `docs/architecture/code-structure.md` before adding or moving application code.
- Treat the repository shape in `FOUNDATION.md` as a proposal until the corresponding structure exists.
- Read `CONTEXT.md` and relevant files under `docs/adr/` when they exist, following `docs/agents/domain.md`.
- Read `docs/agents/issue-tracker.md` before creating or updating project work.

## Agent skills

### Issue tracker

Issues and specs are tracked in GitHub Issues. See `docs/agents/issue-tracker.md`.

### Triage labels

Use the default Matt Pocock engineering-skill labels. See `docs/agents/triage-labels.md`.

### Domain docs

This repository uses a single-context domain-doc layout. See `docs/agents/domain.md`.

## Code structure

- Keep Next.js routes and `main.py` as composition roots.
- Put behaviour, state, adapters, and tests beside the Module that owns them.
- Import another Module only through its package-root Interface.
- Do not create ownership-free `services`, `utils`, `helpers`, or `common` dumping grounds.
- Add Modules only when their delivery slice begins; do not scaffold hypothetical layers.

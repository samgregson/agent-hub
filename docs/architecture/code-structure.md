# Code structure contract

## Purpose

This document turns the Modules in `system-architecture.md` into repository rules. It exists to keep feature delivery from moving application behaviour into Next.js routes, FastAPI entrypoints, framework adapters, or generic utility folders.

The rules apply incrementally: create a Module when its owning slice begins, not as an empty placeholder. Prefer a few deep Modules with small Interfaces over many shallow wrappers.

## Vocabulary

- A **Module** owns a cohesive capability behind one small **Interface**.
- The Interface is everything a caller must know: operations, inputs, outputs, invariants, error modes, and relevant performance constraints.
- A **seam** is where an Interface lives and behaviour can be replaced without editing its callers.
- An **adapter** connects an Interface to a framework, database, protocol, or external system.

Depth is measured by leverage, not file size. A Module earns its place when deleting it would spread its hidden complexity across several callers.

## Repository map

```text
apps/web/src/
  app/                         # Next.js routes and composition only
  modules/
    workspace/                 # Project selection, navigation and panel state
    agent-ui/                  # assistant-ui composition and AG-UI adapter
    artifact-view-host/        # trusted chrome, sandbox host and fallback view
  shared/
    config/                    # validated browser/server configuration
    http/                      # shared same-origin backend forwarding
    ui/                        # genuinely shared presentation primitives

apps/api/src/agent_hub_api/
  main.py                      # FastAPI composition root only
  modules/
    identity/                  # trusted request identity
    projects/                  # Projects, Threads metadata and enablement
    agent_execution/           # Deep Agent construction and Run lifecycle
    agent_transport/           # Project-authorized AG-UI orchestration and transport
    project_files/             # project-scoped Deep Agents filesystem
    artifacts/                 # Artifact lifecycle and authority rules
    plugin_gateway/            # MCP transport, policy and resource loading
    persistence/               # shared transaction and database facilities
```

Only directories needed by the current slice are created. Calculation, diagram, unit, and structural-engineering Modules remain Plugin work after the foundation.

## Composition roots

`apps/web/src/app/**` and `apps/api/src/agent_hub_api/main.py` are composition roots. They may:

- read route or deployment configuration;
- construct Modules and adapters;
- pass identifiers and commands into Module Interfaces;
- translate an Interface result into a framework response;
- render a Module's top-level view.

They must not own domain decisions, persistence queries, agent state machines, Project workspace state, MCP policy, or Artifact validation. A growing route should delegate behaviour to its owning Module rather than split that behaviour among route-local helper files.

## Module Interfaces

Each Module exposes one intentional Interface from its package root. Internal files are implementation details and use an underscore prefix where that makes accidental imports less likely.

Web Modules may expose `index.ts` and `server.ts` at the package root when Next.js requires separate browser-safe and server-only entry points. These are runtime-specific views of the same Module Interface; callers must not import underscore-prefixed implementation files.

- Callers import from the Module root, never its implementation files.
- Inputs and results use Module-owned types or generated cross-process contracts, not database rows or framework request objects. An ADR-pinned open protocol may cross an explicitly named seam where it is the product's deliberate compatibility boundary.
- Expected failures are explicit Interface outcomes. Framework-specific status codes and rendering remain in adapters.
- Dependencies are accepted during construction. Implementations do not create hidden global clients.
- Cross-Module work is coordinated through Interfaces at the composition root or an owning application Module.
- A new seam needs real variation, normally a production adapter and a deterministic test adapter. Do not add pass-through abstractions for hypothetical replacements.

## Dependency direction

The allowed direction is:

```text
composition root -> Module Interface -> Module implementation -> adapter
                                      -> generated contract
```

Additionally:

- a Module cannot import another Module's implementation;
- API Modules import another API Module only through its package root; a subpath is an implementation import even when it does not begin with an underscore;
- web Modules cannot import from `app/`;
- API Modules cannot import the FastAPI application instance;
- generated contracts do not import application code;
- the browser never becomes an authority for identity, Project scope, Plugin permissions, or Artifact persistence;
- `shared/`, `utils/`, `helpers/`, `services/`, and `common/` must not become ownership-free dumping grounds. Code remains with its owning Module until there are multiple stable consumers.

These directions should be enforced by TypeScript restricted-import rules, Python import checks, and contract tests as the corresponding Modules appear.

## Frontend ownership

The Workspace Module owns selected Project, activity view, selected Thread, selected Artifact or Source, and panel state. Project-scoped state is keyed by Project so switching Projects clears the visible selection and switching back can restore that Project's state.

Next.js pages render the Workspace Interface. They do not accumulate fetching, selection state, panel coordination, or assistant-ui behaviour. Views, state transitions, hooks, and tests stay beside the Module that owns them. `shared/ui` contains only presentation primitives with no product vocabulary.

## Backend ownership

FastAPI route handlers are adapters. They resolve trusted request context, validate transport input, call one Module Interface, and translate the result. SQL, SQLAlchemy models, psycopg connections, LangGraph checkpoints, Deep Agents objects, and MCP clients do not cross Module Interfaces.

`main.py` constructs the identity, persistence, and application Modules and mounts their adapters. Health checks may inspect required dependencies but do not become a second persistence path.

## Testing contract

The Interface is the primary test surface.

- Module tests are colocated beside the Module or root implementation they exercise, and use the same Interface as production callers.
- Separate test trees are reserved for genuinely cross-Module contract tests, production-adapter integration tests, browser journeys, and end-to-end acceptance tests. Do not mirror the production tree merely to separate tests from source.
- Deterministic adapters replace PostgreSQL, models, LangGraph, or remote MCP at internal seams where needed.
- Contract tests verify language-neutral schemas and protocol mappings.
- Integration tests verify production adapters such as PostgreSQL and AG-UI.
- Browser tests verify cross-Module user journeys and isolation properties.
- Tests should survive implementation reorganisation inside a Module.

Do not preserve lower-level tests that merely duplicate stronger Interface tests. Do not test private state solely to make an implementation shape permanent.

## Adopted protocol seams

AG-UI is the accepted open protocol seam between the Deep Agent runtime and the agent UI. Its pinned `ag_ui` types may cross the Agent Execution and Agent Transport Modules, and only those Modules. They must not become types in Project, Project Files, Artifact, Plugin Gateway, or browser workspace Interfaces. The fixture and adapter tests prove that external protocol compatibility; Agent Hub does not duplicate AG-UI as an internal event model.

## Change checklist

Every build ticket and review should answer:

1. Which Module owns the behaviour?
2. What Interface do callers and tests use?
3. Does any caller reach into another Module's implementation?
4. Does a composition root contain behaviour that should move behind an Interface?
5. Is a new seam backed by real production and test adapters?
6. Are authorization, validation, persistence, and failure semantics enforced by the owning backend Module?
7. Do tests prove the acceptance outcome at the introduced seam?
8. Does the change preserve the general foundation rather than introducing premature engineering-domain behaviour?
9. If ownership or an Interface changed, were the architecture document and an ADR updated?

Arbitrary line-count limits are not an architectural control. Review ownership, Interface depth, dependency direction, and observable tests instead.

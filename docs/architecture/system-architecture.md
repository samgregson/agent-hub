# Foundation system architecture

## Status and scope

This is the decision-complete architecture for the general-purpose Agent Hub foundation. It reconciles the domain model, ADRs, research, security model, and validated workspace prototype. The foundation deliberately excludes production calculation, unit, diagram, and structural-engineering logic.

The word **Module** means a cohesive capability behind one small Interface. Internal classes and packages are implementation details unless they cross a seam described below.

The repository-level dependency rules, composition roots, testing surfaces, and change checklist are defined in `code-structure.md` and form part of this architecture.

## Deployment topology

```text
Internet
   |
platform Nginx ingress
   |  authenticates and replaces the trusted subject header
   +---------------------------+
   |                           |
   v                           v
Next.js web container      Python API container
assistant-ui shell         FastAPI application
same-origin proxy -------->AG-UI transport Module
MCP App host routes ------>application Modules
                               |
                 +-------------+-------------+
                 |                           |
                 v                           v
          PostgreSQL service          remote curated MCP servers
          application tables          tools, resources, MCP Apps
          LangGraph checkpoints
```

The browser calls only same-origin Next.js routes. Next.js proxies authenticated application and AG-UI traffic to the Python API; it contains no domain authority. Provider and Plugin credentials never reach the browser. The Python API and PostgreSQL form one initial deployment and recovery unit. Curated MCP servers are independently deployed remote services reached only through the MCP Gateway.

Production trusts an identity header only from the platform ingress, which must remove any client-supplied copy before setting it. Local development uses one explicitly development-only fixed identity adapter. Agent Hub does not implement sign-in, teams, memberships, or invitations in the foundation.

## Repository and toolchain

```text
agent-hub/
  apps/
    web/                    # Next.js, React, assistant-ui
    api/                    # FastAPI, Deep Agents, LangGraph
  packages/
    contracts/              # language-neutral JSON Schema/OpenAPI sources
  plugins/
    test-fixture/           # trivial portable MCP server and MCP App
  tests/
    contract/
    integration/
    e2e/
  docs/
```

Use `pnpm` for the JavaScript workspace and `uv` for Python project and lockfile management. One root task runner surface exposes setup, development, lint, type-check, test, migration, and acceptance commands. Exact runtime and dependency versions are pinned in lockfiles by the first build slice.

## Domain ownership

| Concept                    | Authority                                       | Persistence                                                                          |
| -------------------------- | ----------------------------------------------- | ------------------------------------------------------------------------------------ |
| User subject               | Platform identity, consumed by Agent Hub        | Agent Hub user record keyed by stable external subject                               |
| Project                    | Agent Hub                                       | Application tables                                                                   |
| Thread metadata            | Agent Hub                                       | Application tables                                                                   |
| Thread runtime state       | LangGraph                                       | PostgreSQL checkpointer tables keyed by the Agent Hub Thread ID                      |
| Agent Run lifecycle        | Agent Hub                                       | Application tables                                                                   |
| Approval                   | Agent Hub policy plus LangGraph interrupt       | Application record and checkpointed interrupt state                                  |
| Project Virtual Filesystem | Agent Hub                                       | Project-scoped PostgreSQL records exposed through a Deep Agents backend              |
| Artifact Document          | Agent Hub envelope and Plugin payload semantics | One canonical current document in the Project VFS plus an indexed catalog projection |
| Plugin definition          | Deployment-controlled catalog                   | Version-controlled manifest                                                          |
| Plugin enablement          | Agent Hub Project configuration                 | Application tables                                                                   |
| Plugin/provider secret     | Secret boundary                                 | Encrypted server-side storage or external secret reference                           |

The Artifact catalog projection may repeat queryable envelope fields, but it is not a second authoritative document. It and the canonical VFS document update in one database transaction. LangGraph checkpoints are runtime history, not Artifact revision history.

## Modules and Interfaces

### Workspace Module — web

Owns the selected Project, activity view, selected Thread, selected Artifact or Source, and panel layout. Project selection sits above the workspace. Chats, Artifacts, Sources, and Plugins are separate project-scoped rail views. A Plugin may contribute a reviewed rail view, but installation alone does not create one.

Its Interface is application state plus navigation commands. It does not know how the agent runs or how a Plugin validates an Artifact.

### Agent UI Module — web

Owns assistant-ui composition for messages, streamed output, tool calls, errors, cancellation, and interrupts. Its external seam is AG-UI. It consumes Agent Hub Thread and Run identifiers supplied by the application shell and does not use assistant-ui's experimental thread list as product persistence.

### Artifact View Host Module — web

Given an authorized Artifact descriptor, it renders trusted Agent Hub chrome and either:

- the responsible MCP App in an isolated sandboxed iframe; or
- a generic safe JSON/document fallback.

It owns loading, empty, stale, unavailable, invalid, and refresh states. The iframe receives only the versioned MCP Apps bridge capabilities allowed by the MCP Gateway. It never receives raw Project storage, cookies, bearer tokens, or unrestricted navigation.

### Project Application Module — API

Owns Project and Thread metadata, Plugin enablement, and project-scoped queries. Every operation receives a trusted request context containing the platform subject and selected Project; a model- or browser-supplied Project ID is a lookup key, never authorization authority.

Its Interface covers creating/listing/loading Projects and Threads and changing Project configuration. It does not expose database rows or LangGraph checkpoint structures.

### Agent Execution Module — API

Owns construction and invocation of the Deep Agent graph, mapping the Agent Hub Thread ID to LangGraph `thread_id`, creation and reconciliation of Agent Runs, interrupt/resume, and cancellation.

Its Interface is conceptually:

```text
start(context, thread, user_input) -> run
resume(context, run, interrupt_response) -> run
cancel(context, run) -> accepted/current_status
reconcile(run) -> durable_status
```

Model construction is localized inside this Module. OpenAI is the initial provider; an Azure-compatible LangChain configuration can be added at the same internal seam without changing application callers.

### Agent Transport Module — API

Owns the AG-UI FastAPI adapter around the compiled Deep Agent graph. It translates transport events, supplies authenticated execution context, propagates cancellation, and maps interrupts. A disconnected HTTP stream does not determine Run status; durable Agent Run state and LangGraph checkpoints do.

The same-origin web proxy and assistant-ui AG-UI runtime are adapters at this seam. Their compatible versions are pinned and tested together.

### Project Files Module — API

Implements Deep Agents' filesystem Interface over a Project-scoped PostgreSQL adapter. Trusted request context determines the namespace. `/project/**` is durable and shared between Threads; `/scratch/**` may remain Thread-local checkpointed state.

Generic file tools can list and read registered Artifact documents under `/project/.artifacts/**`, but cannot write those reserved paths. Artifact mutation crosses the Artifact Module Interface.

### Artifact Module — API

Hides Artifact lookup, Plugin invocation, schema validation, authority rules, concurrency-token checks, provenance, catalog projection, VFS persistence, and change notices behind three operations:

```text
discover(context, query) -> artifact summaries
load(context, artifact_id) -> current Artifact Document
apply(context, artifact_id | new, semantic_operation, expected_version?) -> saved Artifact Document
```

`apply` resolves the responsible Plugin, sends the complete portable document and semantic operation, rejects malformed or invalid replacements, restores host-controlled envelope fields, and commits the updated current document atomically. `documentVersion` is an internal concurrency token; it does not imply retained revisions or a user-facing version browser.

### Plugin Gateway Module — API

Hides MCP transport, catalog resolution, discovery caching, OAuth/secret lookup, tool policy, approvals, timeouts, result validation, UI resource loading, and telemetry. Its Interface is deliberately small:

```text
capabilities(context) -> permitted project capabilities
call(context, plugin_id, tool_name, arguments) -> normalized MCP result
read_ui_resource(context, plugin_id, resource_uri) -> validated UI resource
```

Only this Module makes outbound MCP connections. Tool names and metadata from a server are untrusted until intersected with the deployment catalog and Project enablement. State-changing retries require known idempotency.

The portable Plugin contract remains ordinary MCP: concise `content`, UI-oriented `structuredContent`, a complete Artifact replacement for semantic edits, and an optional standard MCP App resource. Agent Hub persistence and provenance are host enhancements, not Plugin requirements.

### Persistence Module — API

Provides transaction-scoped adapters for Agent Hub application records and the Project VFS. LangGraph uses its supported PostgreSQL checkpointer separately. One PostgreSQL service is used, but ownership and migrations remain explicit.

The application does not claim a cross-library transaction spanning a Run and every checkpoint. It creates the Agent Run before graph invocation, commits each Artifact/VFS mutation independently, marks terminal state idempotently, and reconciles incomplete Runs from checkpoints after interruption or restart.

## Cross-module flows

### Run and stream

1. The browser selects an authorized Project and Thread through the Project Application Module.
2. The Agent UI starts a Run through the same-origin AG-UI route.
3. Agent Execution creates the durable Run, binds the Thread ID, and invokes the graph.
4. Agent Transport streams AG-UI events to assistant-ui.
5. Tools are exposed from the Project Files and Plugin Gateway Modules according to Project policy.
6. Completion, failure, interruption, or cancellation is persisted idempotently.
7. Reload or reconnect hydrates from durable Thread, Run, and checkpoint state.

### Plugin-mediated Artifact edit

1. A Thread or MCP App proposes a semantic operation against an Artifact.
2. Artifact Module authorizes and loads the current Project document.
3. Plugin Gateway calls the responsible portable tool with the complete document.
4. Artifact Module validates the result and host-controlled fields.
5. The current VFS document, index projection, provenance, concurrency token, and compact Project change record commit atomically.
6. The open Artifact view refreshes after the in-Thread result or on focus/reopen. Other Threads receive only a compact later-run change notice.

### Calculation-to-diagram later

The agent discovers a calculation Artifact summary, loads it on demand, and passes the complete document or a validated projection to a compatible diagram tool. The resulting diagram is a separate Artifact with a typed relation to the calculation. Iframes never call one another directly.

## Failure contract

| Failure                                   | Required outcome                                                                  |
| ----------------------------------------- | --------------------------------------------------------------------------------- |
| Missing/untrusted identity                | Reject before Project data is read                                                |
| Unauthorized Project or cross-Project ID  | Indistinguishable not-found/forbidden response; audit the attempt                 |
| Browser stream disconnect                 | Run continues or interrupts independently; reload can reconcile                   |
| Model/provider failure                    | Explicit failed or retryable Run; no fabricated assistant completion              |
| Cancellation                              | Best-effort runtime cancellation followed by durable reconciliation               |
| Pending approval                          | Checkpointed interrupted Run that can resume exactly once per accepted response   |
| MCP timeout/unavailable server            | Normalized retryable/terminal tool error; current Artifact unchanged              |
| Malformed or schema-invalid Plugin result | Reject and quarantine diagnostic metadata; current Artifact unchanged             |
| Stale Artifact token                      | Explicit conflict; reload current document before retrying the semantic operation |
| Database failure during Artifact save     | Transaction rolls back document, index, provenance, and change record together    |
| MCP App resource or bridge failure        | Trusted error state and generic Artifact fallback remain available                |
| Oversized input/result/resource           | Reject at the owning seam with an explicit size error; do not partially persist   |

## Security baseline

- Curated means reviewed, not trusted at runtime.
- Deny arbitrary MCP endpoints and private, loopback, link-local, metadata, or unapproved redirect destinations.
- Keep OAuth and provider credentials server-side, encrypted, audience-bound, and out of logs/model context.
- Validate tool arguments, structured results, schema bindings, resource URIs, MIME types, origins, and sizes.
- Intersect app-declared CSP and capabilities with catalog policy.
- Require policy/approval for consequential actions; the model cannot grant authority.
- Redact payloads by default and record identities, correlation IDs, policy decisions, timing, outcome, and provenance.
- Do not add arbitrary code execution or host filesystem access to the foundation.

## Observability

Use structured logs, metrics, and OpenTelemetry-compatible traces with the same correlation fields: request, user subject hash, Project, Thread, Agent Run, Plugin, tool call, Artifact, and approval IDs where applicable. Record state transitions and durations, not secret values or full Artifact/tool payloads by default.

Minimum operational signals are Run counts/duration/outcome, active and interrupted Runs, stream disconnects, checkpoint and reconciliation failures, MCP latency/errors/timeouts, approval latency, Artifact validation/conflicts, iframe/resource failures, and database latency/errors. Health checks distinguish process liveness from readiness of PostgreSQL and required configuration; remote Plugin failure does not make the core API unready.

## Verification strategy

- Schema/contract tests generate Python and TypeScript consumers from the same language-neutral sources.
- Module tests use deterministic model, checkpointer, persistence, and MCP adapters through the same Interfaces as production.
- AG-UI compatibility tests pin streaming, tool, error, cancellation, state, and interrupt/resume mappings.
- PostgreSQL integration tests cover project scoping, checkpoint recovery, VFS sharing, Artifact atomicity, and stale writes.
- Plugin conformance tests run the fixture in MCP-only, standard MCP Apps, and Agent Hub-enhanced modes.
- Browser tests cover workspace navigation, reload, approval, iframe isolation/fallback, and cross-Thread Artifact discovery.
- Security tests cover forged identity/project scope, SSRF redirects/DNS results, hostile resource metadata, bridge capability denial, malformed results, and secret redaction.
- One end-to-end acceptance suite implements `foundation-acceptance.md`; model quality is replaced with deterministic behavior where possible.

## Deliberately deferred

- Team/multi-user Project collaboration and Agent Hub sign-in.
- Arbitrary user-supplied MCP servers.
- Artifact revision browsing, merging, and live cross-Thread synchronization.
- User-level VFS layers, object storage, and large binary Artifacts.
- Multiple simultaneous Artifact panes and finalized small-screen interaction.
- A workflow/event engine for unattended cross-Plugin pipelines.
- Production calculation, units, diagramming, and engineering assurance.

These are scoped deferrals, not unresolved foundation decisions.

# Foundation implementation plan

## Delivery rule

Build the foundation as thin, deployable vertical slices. Every slice leaves the repository runnable, adds tests at the seam it introduces, and avoids domain-specific engineering code. A later ticket may depend only on slices listed before it.

## Slice 0 — Repository and contract spine

**Outcome:** one reproducible monorepo with empty runnable web/API shells and a language-neutral contract pipeline.

**Work:**

- Create `apps/web`, `apps/api`, `packages/contracts`, `plugins/test-fixture`, and test directories.
- Configure pnpm and uv lockfiles, root developer commands, linting, formatting, type checking, and CI.
- Add Dockerfiles and a local composition with PostgreSQL.
- Define shared identifiers, error envelope, Artifact Document envelope, and Run status schemas; generate Python and TypeScript types.
- Pin a compatibility set for Next.js, assistant-ui, AG-UI, Deep Agents, LangGraph, and MCP Apps packages.
- Add liveness/readiness endpoints and configuration validation.

**Acceptance:** a clean checkout installs from lockfiles, starts both shells and PostgreSQL, runs contract generation/checks, and passes CI without credentials. Generated contracts fail CI when stale.

## Slice 1 — Identity, Projects, and project-scoped shell

**Outcome:** the platform subject can create/select a Project and see the validated workspace shell.

**Work:**

- Implement production trusted-header and development fixed-subject identity adapters.
- Add Project persistence/migrations and Project-scoped request context.
- Implement Project create/list/load commands and authorization tests.
- Build the top-level Project selector and project-scoped activity rail with placeholder Chats, Artifacts, Sources, and Plugins views.
- Ensure the ingress/proxy configuration strips client-supplied identity headers.

**Acceptance:** two development subjects cannot access each other's Project by listing or guessing IDs; switching Project clears/restores scoped workspace selection; forged browser headers do not become authority.

## Slice 2 — Threads, Runs, and streamed Deep Agent

**Outcome:** a persisted Thread can run the simplest Deep Agent and stream into assistant-ui through AG-UI.

**Work:**

- Add Thread and Agent Run application records.
- Configure the PostgreSQL LangGraph checkpointer and map the Agent Hub Thread ID to `thread_id`.
- Build the Deep Agent with the initial OpenAI LangChain model configuration and no domain tools.
- Implement the Agent Execution and Agent Transport Modules.
- Connect assistant-ui through the same-origin Next.js AG-UI proxy.
- Render text, tool events, terminal status, and explicit errors.

**Acceptance:** one Thread executes multiple Runs; another Thread has independent runtime state; streaming survives normal completion; page reload restores messages and durable Run status; provider secrets are absent from browser traffic.

## Slice 3 — Interrupt, cancellation, and recovery

**Outcome:** the open AG-UI seam proves the difficult lifecycle behavior before more tools depend on it.

**Work:**

- Add one deterministic protected test tool that triggers a Deep Agents/LangGraph interrupt.
- Render approval, resume the same checkpoint, and make duplicate responses idempotent.
- Propagate browser cancellation and reconcile final status server-side.
- Reconcile non-terminal Runs after API restart or dropped streams.
- Pin contract fixtures for AG-UI messages, tool calls, state, errors, cancellation, and interrupts.

**Acceptance:** approve and reject paths resume exactly once; cancel is reflected durably; disconnecting and reloading does not fabricate failure or duplicate the Run; an API restart can reconcile an interrupted Run.

## Slice 4 — Project Virtual Filesystem

**Outcome:** two Threads share agent-owned Project files without host filesystem access.

**Work:**

- Implement the Project Files Module as a Deep Agents backend over PostgreSQL.
- Route `/project/**` to durable Project storage and `/scratch/**` to Thread-local state where required.
- Normalize paths, enforce Project context, and add configurable content/operation limits.
- Reserve the Artifact namespace against generic writes.
- Surface file tool errors in the run stream.

**Acceptance:** Thread A writes and Thread B reads a Project file; neither can escape its Project namespace or reach server paths; stale exact-string edits return an explicit error; registered Artifact paths reject generic writes.

## Slice 5 — Curated MCP Gateway and portable fixture Plugin

**Outcome:** an enabled reviewed Plugin contributes an ordinary tool through one hardened server-side gateway.

**Work:**

- Define and validate the deployment-controlled Plugin manifest and Project enablement records.
- Implement catalog capability intersection, namespacing, discovery caching, timeouts, cancellation, size limits, and normalized errors.
- Add outbound origin/redirect/DNS protections and secret-reference plumbing without building a full OAuth UI.
- Build a trivial independently runnable MCP fixture with one read-only tool and useful text/structured output.
- Display the tool call/result through assistant-ui.

**Acceptance:** only enabled catalogued tools reach a Run; arbitrary/private endpoints and unapproved capabilities are denied; unavailable/slow/malformed servers produce explicit outcomes; the fixture works in a generic MCP client.

## Slice 6 — Portable Artifact lifecycle

**Outcome:** the fixture Plugin can create and semantically edit one project-owned portable Artifact.

**Work:**

- Implement the Artifact Module Interface and schema/authority validation.
- Store one canonical current document in the reserved Project VFS namespace with a transactional catalog projection, provenance, concurrency token, and change record.
- Add Artifact discovery/load application queries and a generic safe renderer.
- Extend the fixture Plugin with create, validate, and semantic-edit tools accepting/returning the complete inline document.
- Prevent direct payload persistence from model output or generic file tools.

**Acceptance:** create, reopen, and edit work after reload; malformed Plugin replacements leave the current document untouched; host fields cannot be forged; a stale token conflicts explicitly; generic MCP use remains functional without Agent Hub persistence.

## Slice 7 — Sandboxed MCP App artifact pane

**Outcome:** the same fixture Artifact renders and edits through a standards-compatible MCP App inside the selected Artifact pane.

**Work:**

- Add the fixture's standard MCP App UI resource.
- Implement validated UI-resource loading and the capability-limited MCP Apps bridge through the Plugin Gateway.
- Render trusted Artifact chrome outside an isolated-origin sandboxed iframe.
- Route App semantic edits through Plugin tools and the Artifact Module, then refresh on successful persistence.
- Provide loading, invalid, unavailable, stale, and generic-fallback states.

**Acceptance:** the App renders and can request a valid edit without direct storage access; forbidden bridge capabilities fail closed; CSP/origin/MIME violations do not execute; resource failure preserves a usable generic Artifact view; the same App still renders in a standard MCP Apps host.

## Slice 8 — Cross-Thread discovery and change awareness

**Outcome:** project ownership is demonstrated across two conversations without bloating every prompt.

**Work:**

- Expose compact Artifact summaries through on-demand agent and application queries.
- Let Thread B discover, load, and plugin-edit Thread A's Artifact.
- Append compact Project change notices to later Runs without mutating the static system prompt.
- Mark an already-open stale view and refresh on focus/reopen; do not implement live merging.
- Render provenance linking creating and changing Threads/Runs.

**Acceptance:** Thread B can inspect and edit without the full catalog in its initial context; Thread A learns of the change on a later Run; the current document and provenance are correct; no retained revision browser or live synchronization is implied.

## Slice 9 — Deployment and foundation acceptance

**Outcome:** the complete foundation runs as a hardened hosted vertical slice.

**Work:**

- Finalize production Docker images, migrations, startup/shutdown, health checks, backup/restore instructions, and Nginx integration contract.
- Add structured logging, metrics, trace correlation, redaction, audit records, and operational dashboards/alerts.
- Exercise rate, concurrency, retry/idempotency, payload, and resource limits.
- Run hostile MCP/UI security cases and restore/reconciliation drills.
- Automate the complete `foundation-acceptance.md` scenario in CI and a deployed environment.

**Acceptance:** every foundation acceptance item passes; a PostgreSQL backup restores application and checkpoint state; an API restart reconciles Runs; remote Plugin failure does not fail core readiness; logs/traces contain correlations but no test secrets or unredacted fixture payloads.

## Ticket conversion

Create one parent milestone for slices 0–9. Each slice becomes one primary build ticket with its stated outcome and acceptance criteria; split implementation subtasks only when they can merge behind that slice's Interface without producing an unusable intermediate architecture. Keep the ordering above as the dependency chain, but parallelize frontend presentation, test fixtures, and adapters inside a slice when their contracts are already fixed.

The first engineering Plugin begins only after Slice 9. It gets its own design for quantities, units, calculation semantics, verification, and professional-use constraints rather than extending the trivial fixture.

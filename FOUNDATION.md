# Agent Hub: Foundation and Direction

## Purpose

Agent Hub will be an extensible, general-purpose agent platform. Its first milestone is a dependable agent foundation rather than a structural-engineering product. Once that foundation is stable, domain-specific capabilities can be added for structural engineering without tightly coupling them to the core agent.

The long-term experience should feel closer to a coding environment than a conventional chatbot: the conversation remains central, while rich, inspectable work products can open alongside it in an artifact panel. A calculation should be something the user can inspect, revise, recompute, and pass into another tool—not merely prose embedded in a chat response.

## Product principles

1. **Agent first, domain later.** Build a strong general agent runtime before adding structural-engineering behavior.
2. **Extensible by protocol.** Prefer MCP-compatible tools, resources, prompts, and apps over integrations that are hard-wired into the core.
3. **Artifacts are durable objects.** Calculations, diagrams, reports, and similar outputs should have identities, schemas, versions, provenance, and lifecycle beyond one chat message.
4. **The backend owns trust.** Model calls, MCP connections, credentials, authorization, validation, and persistence belong on the server side.
5. **The frontend is a host, not an app-specific monolith.** It should render conversations, agent activity, and compatible artifact/app surfaces without knowing every future domain capability.
6. **Structured data crosses boundaries.** Apps should exchange validated, versioned data contracts rather than scraping one another's rendered UI or passing ambiguous prose.
7. **Human control is explicit.** Sensitive actions, consequential calculations, and cross-app transfers must be inspectable and capable of requiring approval.
8. **Engineering results remain auditable.** Future calculations must record inputs, units, assumptions, methods, references, warnings, outputs, and software/version provenance.

## Initial scope

The foundation milestone should provide:

- a Python agent backend built with LangChain's open-source `deepagents` package;
- a Next.js/React web application;
- an agent-oriented chat interface built from assistant-ui's open-source packages;
- streaming messages, tool calls, tool results, errors, and approval states;
- persistent projects, threads, agent runs, messages, and artifact documents;
- a server-side MCP client and registry that can connect to multiple configured MCP servers;
- a generic renderer/host path for MCP Apps or an equivalent standards-compatible UI resource;
- a first-class artifact panel shell, initially with placeholder or generic content;
- clear contracts between the agent runtime, MCP tools, artifacts, and the frontend;
- observability, testing seams, permissions, and configuration suitable for later growth.

This milestone does **not** include a production calculation engine, unit-conversion engine, diagram editor, structural design codes, or engineering verification logic.

## High-level architecture

```text
Platform Nginx ingress (sign-in handled outside Agent Hub)
          │
          ▼
Browser
  Next.js + React + assistant-ui
  ├─ conversation and run UI
  ├─ tool/approval UI
  ├─ MCP App host (sandboxed)
  └─ artifact workspace/panel
          │ AG-UI stream + Agent Hub application commands
          ▼
Self-hosted Python backend (Docker image)
  ├─ project/thread/run service
  ├─ artifact service
  ├─ MCP gateway and policy
  └─ AG-UI FastAPI endpoint
       LangChain Deep Agents / LangGraph runtime
          ├─ model provider adapter
          ├─ memory and persistence
          ├─ human-in-the-loop policy
          ├─ built-in/internal tools
          └─ MCP gateway and registry
                 ├─ calculation MCP server/app (later)
                 ├─ diagram MCP server/app (later)
                 └─ other plugins and services
```

### Frontend

Use Next.js with React and TypeScript. assistant-ui should supply the conversation primitives and agent interaction patterns while remaining within its open-source offering. The UI should be composed around two cooperating surfaces:

- **Conversation surface:** messages, streamed agent output, plans/status, tool calls, approvals, and errors.
- **Workspace surface:** a resizable artifact panel able to display an MCP App, a native renderer, or a read-only artifact preview.

The frontend should not receive MCP credentials. A backend route or the Python API should act as the MCP client and authorization boundary. MCP-provided UI must run in an appropriately sandboxed frame with a narrow host bridge and explicit capabilities.

The selected Project sits above the workspace. A left activity rail switches between project-scoped Chats, Artifacts, Sources, Plugin management, and optional reviewed Plugin views; the adjacent navigator shows the selected collection. Thread chat remains central and the Artifact/Sources workspace opens on the right. The right workspace remains selected across Thread switches inside the same Project and can enter an explicit Artifact focus mode. Detailed small-screen interaction is deferred, with one primary surface visible at a time and workspace state preserved. The decision is recorded in `docs/architecture/workspace-interaction.md`.

### Backend

Use Python and the standalone LangChain `deepagents` package. Deep Agents is built on LangChain/LangGraph and provides planning, filesystem/context management, subagents, memory hooks, streaming, and human-in-the-loop capabilities. We should adopt those primitives where they fit rather than reproducing an agent loop ourselves.

The backend needs an application layer around the agent runtime. Deep Agents should not become the whole product persistence model. The application layer owns stable domain concepts such as Project, Thread, Agent Run, Artifact, Plugin selection, and approval. AG-UI is the replaceable agent-to-frontend protocol seam.

The Python backend will be deployed as a Docker image behind the platform's Nginx ingress. Sign-in is supplied by that platform and is not an Agent Hub subsystem. Agent Hub consumes the trusted platform identity and remains responsible for scoping its own Project data and operations.

### Transport and streaming

Run the MIT-licensed LangGraph/Deep Agents runtime inside Agent Hub's Python/FastAPI container and expose it through the open AG-UI protocol using the LangGraph adapter. assistant-ui consumes it through its first-party AG-UI runtime. This avoids the separately licensed LangChain standalone Agent Server and makes either side replaceable by another AG-UI implementation. Use a same-origin Next.js proxy and keep transport configuration inside one deep Module. Because assistant-ui currently labels AG-UI interrupts experimental, interrupt/resume is a required walking-skeleton compatibility test.

## Extensibility model

The word **plugin** can refer to several different extension layers. Agent Hub should keep them distinct:

1. **Agent skills:** reusable instructions and workflows that shape how the agent approaches work.
2. **MCP servers:** external capability providers exposing tools, resources, and prompts.
3. **MCP Apps:** MCP tools paired with interactive UI resources that a compatible host can render.
4. **Internal extensions:** trusted Python modules for capabilities that require tight runtime integration.

The preferred path for independently deployable domain capabilities is an MCP server, optionally with an MCP App UI. Internal extensions should be reserved for core platform concerns or cases where MCP introduces a demonstrated limitation.

### MCP registry responsibilities

The platform-level MCP gateway/registry should:

- store enabled server definitions separately from credentials;
- support multiple servers and stable server identities;
- discover and cache tool/resource metadata with safe invalidation;
- namespace tools to avoid collisions;
- apply user/workspace authorization and per-tool policy;
- expose only permitted tools to each agent run;
- route tool calls and UI resource requests to the owning server;
- normalize errors and telemetry;
- preserve original MCP payloads when needed for compatibility;
- enforce timeouts, size limits, and cancellation;
- record provenance for artifact-producing calls.

## Artifacts and communication between apps

MCP provides discovery and invocation, but seamless app-to-app composition requires an Agent Hub contract above the individual app UIs. Apps should not call one another by reaching into frames or depending on presentation details.

The composition model is:

1. An MCP tool returns a concise model-visible result plus structured output.
2. If the result represents durable work, Agent Hub stores one portable **Artifact Document** containing a host-controlled envelope and plugin-controlled payload.
3. The document declares its type, schema version, producer, provenance, relations, and domain content.
4. The agent can pass an artifact reference—or an explicitly transformed projection of it—to another compatible tool.
5. The receiving tool declares which artifact/schema types it accepts.
6. Agent Hub validates the handoff and records lineage between the input and output artifacts.

A future calculation-to-diagram flow could therefore be:

```text
calculation tool
  -> calculation Artifact Document (typed values, units, equations, metadata)
  -> agent selects compatible diagram tool
  -> validated artifact reference/projection
  -> diagram Artifact linked back to the calculation Artifact
```

The agent is initially the orchestrator. A separate workflow engine or event bus should not be added until there is a concrete requirement for unattended or deterministic multi-app pipelines.

### Artifact Document

The host-controlled envelope and plugin-controlled payload are stored and exported together. A plugin accepts the complete inline document and returns a complete validated replacement, but Agent Hub preserves or recomputes identity, document version, provenance, and Project relationships before persistence. This keeps plugins portable without granting them authority over host state. The detailed boundary and example shape are recorded in `docs/architecture/artifact-contract.md`.

For engineering artifacts, numerical values should never be represented as untyped numbers when units matter. Values should use an explicit quantity representation, and calculation schemas should distinguish input, derived value, result, assumption, and check.

## Initial domain model

- **User:** the person authenticated by the hosting platform.
- **Project:** the durable workspace containing Threads, Artifacts, Sources, Instructions, Plugin selections, and a shared Virtual Filesystem.
- **Thread:** one persisted, resumable LangGraph conversation state within a Project.
- **Agent Run:** one invocation within a Thread.
- **Message:** a user, assistant, system, or tool communication within a Thread and, where applicable, an Agent Run.
- **Approval:** a resumable decision requested by a run before a protected action.
- **Plugin selection:** a catalogued MCP Plugin enabled for a Project with its configuration and policy.
- **Artifact:** a stable logical work product represented by one current portable Artifact Document.
- **Artifact relation:** typed lineage or reference between Artifacts.

These are application concepts. Their ownership, persistence, and Module Interfaces are defined in `docs/architecture/system-architecture.md`.

## Repository shape

```text
agent-hub/
  apps/
    web/                 # Next.js frontend
    api/                 # Python HTTP/streaming application
  packages/
    contracts/           # generated/shared event and artifact schemas
  docs/
    architecture/
    adr/
  tests/
    contract/
    integration/
```

This is the implementation layout. Python and TypeScript share contracts through language-neutral JSON Schema/OpenAPI sources rather than hand-maintained duplicate models. Use pnpm for the JavaScript workspace and uv for Python dependency and lockfile management.

## Security and reliability baseline

- Keep model-provider and MCP credentials server-side and encrypted at rest.
- Treat MCP servers, tool descriptions, results, and app UI as untrusted inputs.
- Sandbox remote UI and allow only an explicit host capability set.
- Consume the platform-authenticated identity and enforce Project scoping, rate limits, and tool allowlists at the MCP gateway boundary.
- Make consequential tool calls eligible for human approval.
- Isolate any filesystem or code execution from the API host.
- Validate structured outputs before persistence or cross-app transfer.
- Preserve Artifact provenance and a current document version token; a retained revision history is deferred.
- Support cancellation, retry policy, idempotency, and recovery from interrupted runs.
- Redact secrets and sensitive content from logs and traces.
- Add domain-specific verification and disclaimers before the product presents structural-engineering outputs as dependable professional work.

## Testing strategy

The first tests should focus on externally visible seams:

- API contract tests for Project, Thread, Agent Run, approval, and Artifact behavior;
- LangGraph adapter tests for streaming, reconnection, completion, and errors;
- agent adapter tests using deterministic fake models/tools;
- MCP contract tests against a small test server;
- artifact schema and lineage validation tests;
- frontend component tests for streamed states and approval flows;
- an end-to-end test from user message to tool result and rendered placeholder artifact;
- security tests for unauthorized MCP access and hostile UI/resource metadata.

Model-quality evaluation should be separate from deterministic software tests. Recorded scenarios and trace-based evaluations can be added once the basic run loop is stable.

## Delivery sequence

The build-ready vertical slices, dependencies, and acceptance gates are defined in `docs/architecture/implementation-plan.md`. The summary phases are:

### Phase 0: decisions and contracts

- Confirm the domain vocabulary and repository layout.
- Choose the Python API framework and package managers.
- Pin the frontend/backend LangGraph adapter versions.
- Define version-one event and artifact envelopes.
- Record decisions as ADRs.

### Phase 1: walking skeleton

- Create the Next.js and Python applications.
- Stream a basic Deep Agent run into assistant-ui.
- Persist a Project, Thread, Agent Run, messages, and checkpoints.
- Provide health checks, local configuration, tests, and developer commands.

### Phase 2: tools and approvals

- Add the MCP registry and one controlled test MCP server.
- Render tool activity and support resumable approval.
- Add policy, timeout, cancellation, telemetry, and error handling.

### Phase 3: artifact host

- Add the Artifact panel and current portable Artifact Document persistence.
- Render a generic artifact from a tool result.
- Host a standards-compatible MCP App UI through a sandboxed bridge.
- Demonstrate one typed artifact handoff between test tools.

### Phase 4: first engineering vertical slice

- Design the calculation artifact schema and quantity/unit contract.
- Build or integrate a calculation MCP server and app.
- Add deterministic numerical verification and audit trails.
- Only then begin structural-engineering-specific calculations and diagram flows.

## Implementation parameters and later decisions

- Exact dependency versions and configured payload limits are selected, pinned, and contract-tested in the first applicable build slice.
- Local development uses an explicitly development-only fixed identity adapter; production trusts only the platform ingress after it replaces client-supplied identity headers.
- Oversized Artifacts are rejected explicitly during the foundation. Object storage is introduced only with a supported large/binary use case.
- Calculation/unit libraries and quantity serialization belong to the later engineering Plugin design, not the general foundation.

## Decisions already made

- The product name is **Agent Hub**.
- The initial product is a general-purpose agent foundation.
- Structural engineering is the intended specialist direction.
- The backend language is Python.
- The agent harness is LangChain Deep Agents.
- The frontend is React with Next.js.
- The agent UI will use assistant-ui's open-source offering.
- Extensibility through MCP and interactive MCP Apps is a primary architectural goal.
- Calculation and diagram apps are future work, not part of the foundation implementation.
- Sign-in is handled by the hosting platform's Nginx proxy rather than by Agent Hub.
- LangGraph and Deep Agents will be self-hosted in a Dockerized Python backend.
- AG-UI is the open agent-to-frontend protocol seam, implemented with the LangGraph and assistant-ui adapters.
- PostgreSQL is the initial durable store, including supported LangGraph checkpoint persistence and a project-scoped Virtual Filesystem adapter.
- Each Artifact is one portable document with a host-controlled envelope and plugin-controlled payload.
- The initial Plugin Catalog is deployment-controlled and excludes arbitrary user-provided servers.

## References

- [LangChain Deep Agents overview](https://docs.langchain.com/oss/python/deepagents/overview)
- [assistant-ui installation](https://www.assistant-ui.com/docs/installation)
- [assistant-ui MCP integration](https://www.assistant-ui.com/docs/tools/mcp)
- [assistant-ui MCP Apps integration](https://www.assistant-ui.com/docs/tools/mcp-apps)
- [OpenAI plugin architecture](https://developers.openai.com/plugins/concepts/plugins)
- [OpenAI MCP server and UI quickstart](https://developers.openai.com/plugins/build/app-quickstart)
- [OpenAI plugin UI reference](https://developers.openai.com/plugins/reference)

# Artifact ownership across Agent Hub, MCP Apps, and Deep Agents

Research date: 2026-09-11

This note separates behaviour defined by the relevant protocols and libraries from architecture proposed for Agent Hub. Sources are limited to specifications, official documentation, and first-party source code.

## Executive conclusion

MCP Apps is a rendering and interaction protocol, not an artifact database. An MCP App UI resource is a reusable HTML template; a tool result supplies the data for one invocation. Neither MCP nor assistant-ui defines a durable, project-owned artifact identity, revision history, or cross-thread ownership model.

For Agent Hub, the smallest sound foundation is therefore a **hybrid model**:

- Agent Hub owns a lightweight, project-scoped Artifact Registry containing identity, title, type, provider, current provider reference, summary, provenance, and timestamps.
- The MCP server that implements an artifact type owns its authoritative domain payload and domain-specific editing tools.
- The Deep Agents project filesystem remains a separate, general-purpose workspace. An artifact may optionally expose a virtual-file representation, but a file is not its canonical identity.
- Initial updates may replace the current provider payload without a user-facing revision system. Store provenance for each mutation now so immutable revisions can be introduced later without confusing LangGraph checkpoints with artifact revisions.

## Established facts

### MCP and MCP Apps

1. MCP distinguishes three server primitives: prompts, resources, and tools. Resources are application-controlled contextual data, while tools are model-controlled actions. This is a protocol-level control distinction, not an ownership or database schema for product artifacts. [MCP server overview](https://modelcontextprotocol.io/specification/2025-11-25/server/index)

2. An MCP App links a tool to a `ui://` resource using `_meta.ui.resourceUri`. When the tool is called, the host fetches the resource, renders it in a sandboxed iframe, and delivers the tool arguments and result to the View. The UI resource is the HTML template; it is separate from the result data. [MCP Apps overview](https://apps.extensions.modelcontextprotocol.io/api/documents/overview.html)

3. Tool results can contain `content` and `structuredContent`. MCP Apps explicitly positions `content` as model-context text and `structuredContent` as data suited to UI rendering; the core MCP tool specification permits an output schema and requires conforming structured results when one is declared. [MCP Apps lifecycle](https://apps.extensions.modelcontextprotocol.io/api/documents/overview.html), [MCP tools specification](https://modelcontextprotocol.io/specification/2025-06-18/server/tools)

4. During its mounted lifetime, a View can call tools, read/list resources, send a conversation message, and update model context through the host bridge. App-only tools can be hidden from the model, allowing UI interactions such as refresh, pagination, or form submission without enlarging the model tool catalog. [MCP Apps overview](https://apps.extensions.modelcontextprotocol.io/api/documents/overview.html)

5. Before unmounting a View, the MCP Apps host must send a teardown request, giving the View an opportunity to save state or release resources. The specification defines this lifecycle opportunity but does not prescribe where domain data is stored, how it is versioned, or which product-level Project or Thread owns it. [MCP Apps `AppBridge` reference](https://apps.extensions.modelcontextprotocol.io/api/classes/app-bridge.AppBridge.html)

6. Core MCP resources have URI identity and optional descriptive/display metadata, and may advertise update/list-change notifications. `file://` resources need not map to a physical filesystem. MCP does not require a particular host UI or add project/thread/artifact ownership semantics to a resource. [MCP resources specification](https://modelcontextprotocol.io/specification/2025-11-25/server/resources)

7. OpenAI's ChatGPT compatibility surface adds `window.openai.widgetState` and `setWidgetState` for a persisted **widget-local snapshot**. OpenAI's own guidance says portable baseline behaviour should use the MCP Apps bridge and treat `window.openai` as additive. Widget state is therefore not a portable or suitable canonical store for an engineering calculation. [OpenAI Apps SDK compatibility guidance](https://github.com/openai/skills/blob/main/skills/.curated/chatgpt-apps/references/window-openai-patterns.md)

8. assistant-ui renders an MCP App when a tool-call part carries the app metadata, loads the `ui://` resource through a server-side host route, and correlates the result to the tool call. Its bridge routes app tool/resource operations back to the configured MCP server. The documented integration does not introduce durable artifact storage or ownership. [assistant-ui MCP Apps documentation](https://www.assistant-ui.com/docs/tools/mcp-apps)

### Deep Agents filesystem behaviour

1. `StoreBackend` stores files in a LangGraph `BaseStore`, is durable across threads, and uses a caller-supplied namespace factory. Namespace tuples can combine isolation keys, so Agent Hub can select a `(user_id, project_id, "filesystem")`-style project scope rather than thread scope. [Deep Agents backends documentation](https://docs.langchain.com/oss/python/deepagents/backends)

2. Backend `write` is create-only and reports a conflict if the path exists. Backend `edit` performs string replacement, requires `old_string` to be unique unless `replace_all=True`, and returns an error if it is absent. These behaviours support an agent read/edit/re-read recovery loop. [Deep Agents backend protocol](https://docs.langchain.com/oss/python/deepagents/backends)

3. This is **not full concurrent-write protection**. The first-party `StoreBackend.edit` implementation reads the current item, performs replacement in memory, then calls `store.put`; it does not pass an expected version or perform a compare-and-swap in that sequence. Two writers can both read the same content and then overwrite one another. Exact-string replacement catches a stale edit only when the earlier write changes the text the later writer is trying to match, and only if that change is observed before the later writer reads. [Deep Agents `StoreBackend` source](https://github.com/langchain-ai/deepagents/blob/main/libs/deepagents/deepagents/backends/store.py)

4. `StateBackend` and `StoreBackend` have different lifetimes: state-backed files live in agent state/checkpoints, while store-backed files support cross-thread durable storage. Project sharing is a namespace choice made by Agent Hub; it is not inferred automatically from a Project concept in Deep Agents. [Deep Agents backends documentation](https://docs.langchain.com/oss/python/deepagents/backends)

### LangGraph checkpoints

1. A checkpointer persists graph execution state under a `thread_id`; stores are the mechanism for durable data shared across threads. Official persistence guidance explicitly separates these roles. [LangGraph persistence](https://docs.langchain.com/oss/python/langgraph/persistence)

2. LangGraph checkpoints are snapshots at graph execution boundaries. Time travel can replay or fork execution from a previous checkpoint; replay may rerun LLM calls and external side effects, and `update_state` creates a new branch rather than rolling the thread back. [LangGraph time travel](https://docs.langchain.com/oss/python/langgraph/use-time-travel)

3. Consequently, checkpoints provide runtime history, debugging, resumption, and branching. They do **not** by themselves provide user-facing artifact identity, artifact revision labels, domain validation, or a safe rollback protocol for external MCP-server data. An external tool mutation is not reversed merely by selecting an older checkpoint.

## Architectural inference for Agent Hub

The following is proposed design, not behaviour supplied by MCP Apps, assistant-ui, Deep Agents, or LangGraph.

### Options considered

#### A. Artifacts are only Deep Agents virtual files

The calculation payload is stored as a project-scoped file and the MCP App renders it.

This is simple and lets the standard filesystem tools edit it, but it makes the generic filesystem the source of truth for every plugin's domain model. It also requires the host to invent a contract for routing arbitrary file content into each app and cannot naturally express provider-managed operations, validation, or private data.

#### B. Artifacts exist only inside each MCP server

The calculation MCP server stores calculations and exposes create/read/update/render tools. Agent Hub keeps only tool-call messages.

This preserves plugin autonomy, but Agent Hub cannot reliably provide a project-wide artifact list, stable navigation, cross-thread discovery, provenance, or lifecycle management unless every plugin happens to implement identical discovery semantics.

#### C. Agent Hub registry plus provider-owned payload (recommended)

Agent Hub stores a small canonical registry record. The provider MCP server stores the domain payload and exposes domain tools. A registry item points to the provider and its opaque object/reference ID.

Suggested foundation fields:

- `artifact_id`: stable Agent Hub identity
- `project_id`: owning Project
- `artifact_type` and `title`
- `provider_id`: MCP server/plugin identity
- `provider_ref`: opaque provider-owned object ID or URI
- `summary`: small, model-safe discovery text
- `created_by_thread_id` and `created_by_run_id`
- `updated_by_thread_id` and `updated_by_run_id`
- `created_at` and `updated_at`
- optional `content_version` or provider ETag when the provider supports one

This keeps the right-panel navigation and cross-thread discovery consistent while leaving calculation semantics, units, validation, and editing with the calculation provider.

### Recommended interaction flow

1. The model calls a calculation provider's create or update tool.
2. The provider validates and durably stores its domain payload, then returns concise `structuredContent` containing at least its provider reference, title/type, summary, and any version token it supports.
3. Agent Hub upserts the project Artifact Registry entry and records Thread/Run provenance.
4. A render tool (or the same tool, where appropriate) links the result to a `ui://` resource. assistant-ui displays that resource in the right workspace panel as a host presentation choice.
5. Other threads receive neither the full artifact nor a stale system-prompt list. They use a project artifact-list/search tool returning compact registry summaries, followed by provider reads for explicitly selected artifacts.
6. A View interaction calls its provider's tools through the host. Successful mutations update the registry's summary, timestamps, provenance, and optional version token.

### App-to-app composition

Do not make one iframe directly discover and control another iframe. Treat tools and typed results as the composition boundary:

- a calculation provider returns a stable artifact reference plus a compact, declared structured schema;
- the agent or Agent Hub orchestration calls a diagram provider with that reference or a deliberately exported representation;
- the diagram becomes its own project-owned registry item with provenance linking it to the source calculation and exact provider version when available.

This follows MCP's tool/resource boundaries, avoids coupling Views, and gives the host one place to enforce project authorization and provenance.

### Initial revision policy

Use a stable Artifact identity with a mutable current payload for the foundation. Do not expose revision browsing yet. This is intentionally simpler than immutable revisions, but it should include mutation provenance and an optional provider version token from day one.

Do not use LangGraph checkpoints as artifact revisions: they are execution-state snapshots and cannot guarantee rollback of MCP-server side effects. When engineering-grade auditability becomes a requirement, add explicit immutable Artifact Revisions (or require provider revision support) as a separate domain feature.

### Concurrency policy

Allow concurrent threads, but document the initial guarantee accurately:

- Deep Agents exact-string editing provides useful stale-edit feedback in many ordinary cases.
- It does not prevent all lost updates in a shared project `StoreBackend`.
- Domain artifact providers should accept an expected version/ETag when mutating authoritative artifacts and reject stale writes.
- If virtual-file lost updates matter in the foundation, Agent Hub needs an explicit version-aware backend or per-path serialization; this is additional architecture, not behaviour to assume from `StoreBackend`.

## Decisions this research supports

- Project-owned artifacts with Thread and Agent Run provenance.
- Project-scoped Deep Agents `StoreBackend`, separate from artifact canonical storage.
- Compact, tool-driven project artifact discovery rather than injecting a changing artifact list into the system prompt.
- Provider-owned domain data behind MCP tools, surfaced consistently through an Agent Hub Artifact Registry.
- Mutable current artifact state initially, with explicit artifact revision semantics deferred.
- No claim that Deep Agents automatically resolves every concurrent file edit.

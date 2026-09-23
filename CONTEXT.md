# Agent Hub

Agent Hub is a web-based workspace for carrying out AI-led work through conversations, tools, and inspectable outputs.

## Language

**Project**:
A durable workspace that groups related threads, artifacts, sources, instructions, plugin selections, and agent-owned state. It is not a folder on the user's computer.
_Avoid_: Local project, project folder

**Artifact**:
A durable, self-describing, serializable work product owned by a project. It carries provenance to either the thread and agent run that produced it or a direct user action, and may be inspected or reused by other threads in the project. A project file becomes an artifact only through an explicit, reviewable elevation action.
_Avoid_: Attachment, thread output, working file

**Project File**:
A durable file in the project's virtual filesystem used as agent working material. It may be linked from chat and previewed without becoming an artifact. Elevation to an artifact is explicit: an agent-initiated elevation requires human approval, while a user-initiated plugin save is direct authorization.
_Avoid_: Artifact, source, local file

**Artifact Document**:
The portable stored representation of an artifact, comprising a host-controlled envelope and a plugin-controlled payload.
_Avoid_: Plugin record, artifact revision

**Artifact Envelope**:
The part of an artifact document whose identity, provenance, relationships, and current concurrency version are authoritative in Agent Hub. The version detects stale writes; it does not imply retained revision history.
_Avoid_: Payload, plugin state

**Artifact Payload**:
The domain-specific part of an artifact document whose schema and semantics are owned by its plugin.
_Avoid_: Envelope, host metadata

**Tool Result Snapshot**:
The canonical, serializable inputs and structured output from one successful MCP tool invocation, saved as an Artifact Payload. It excludes transient MCP App UI state and unsuccessful tool calls.
_Avoid_: MCP server state, tool transcript

**Dataset**:
A durable Project-owned ordered collection of JSON-object Dataset Records. A Dataset is an operational input, not an Artifact or generic Project File.
_Avoid_: Spreadsheet, artifact, file

**Dataset Record**:
One host-identified JSON-object entry in a Dataset. A source key may be retained for user traceability but does not replace the host-issued ID.
_Avoid_: Row, artifact, file

**Batch Definition**:
A durable Project-owned mapping from values in one Dataset Record to the ordinary JSON arguments of one catalogue-approved MCP tool. It is reusable configuration, not a Batch Run or a Plugin protocol.
_Avoid_: Workflow, pipeline, plugin port

**Batch Run**:
One bounded execution of a Batch Definition over a captured Dataset selection. It owns progress, policy, initiator provenance, idempotency, and the immutable input snapshot independently of a browser or agent connection.
_Avoid_: Agent Run, workflow, plugin job

**Result Set**:
The durable, queryable collection of outcomes produced by one Batch Run. It may be incomplete when one or more invocations fail.
_Avoid_: Artifact, Dataset, tool transcript

**Result Record**:
One Result Set entry, retaining normalized input and complete structured output or failure for the captured Dataset Record.
_Avoid_: Dataset Record, log line

**Virtual Filesystem**:
The project-shared hierarchical working state available to agents without providing access to the user's computer filesystem.
_Avoid_: Local filesystem, user filesystem, thread filesystem

**Source**:
A durable project input or reference that a thread or artifact can inspect on demand. A source is not an agent-produced work product and its full contents are not automatically injected into every thread.
_Avoid_: Artifact, attachment in chat context

**Instruction**:
Durable project-scoped guidance applied to agent work in that project. It is configuration for future runs, not a message or source.
_Avoid_: System message, source, chat message

**Thread**:
A resumable agent work stream within a project, backed by one persistent LangGraph thread. It contains a conversation and the agent state accumulated across its runs.
_Avoid_: Session, artifact

**Agent Run**:
One invocation of the agent within a thread, from submission until completion, interruption, cancellation, or failure.
_Avoid_: Thread, conversation, trace run

**Chat**:
The conversational interface through which a user works with a thread. It is a view of the thread, not a separate persisted domain object.
_Avoid_: Session

**Plugin Catalog**:
The platform-curated collection of approved plugins that a user may enable. Users select from this collection rather than connecting arbitrary third-party plugins.
_Avoid_: Open marketplace, user-supplied plugin registry

**Plugin**:
A catalogued extension exposed through a portable MCP server and, optionally, an MCP App interface. Agent Hub may add host conveniences without making them requirements of the plugin.
_Avoid_: Provider-owned artifact store, internal Python module

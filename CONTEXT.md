# Agent Hub

Agent Hub is a web-based workspace for carrying out AI-led work through conversations, tools, and inspectable outputs.

## Language

**Project**:
A durable workspace that groups related threads, artifacts, sources, instructions, plugin selections, and agent-owned state. It is not a folder on the user's computer.
_Avoid_: Local project, project folder

**Artifact**:
A durable, self-describing, serializable work product owned by a project. It carries provenance to either the thread and agent run that produced it or a direct user action, and may be inspected or reused by other threads in the project. A project file becomes an artifact only through an explicit, reviewable elevation action.
_Avoid_: Attachment, thread output, working file

**Dataset**:
A durable project-owned collection of structured input values that an agent or user explicitly saves for later inspection or execution. It is not a generated Artifact merely because it is used in a calculation.
_Avoid_: Chat attachment, temporary tool arguments, result set

**Dataset Record**:
One ordered JSON-object entry in a Dataset, identified by a stable host-issued ID and optionally carrying a user-provided source key.
_Avoid_: Tool call, result record, table row without identity

**Result Set**:
A durable, queryable collection of machine-scale outcomes produced by one Batch Run. It is available to agents and users for inspection and may inform an Artifact, but is not itself automatically a curated Artifact.
_Avoid_: Artifact, chat transcript, plugin-owned database

**Batch Run**:
One bounded host-orchestrated execution of a Plugin tool over a Dataset or explicitly supplied collection of inputs. Agent-proposed execution requires approval; a directly authorized user action does not. It records its completion state and Result Set.
_Avoid_: Plugin, Artifact, retry button

**Batch Definition**:
A durable project-owned execution setup that maps Dataset values to the JSON arguments of one Plugin tool. It may be reused to start Batch Runs, but a Batch Run captures the definition it actually used.
_Avoid_: Plugin protocol, run result, Artifact

**Binding**:
A durable host-owned Project rule that maps an explicitly selected structured value to a declared argument of a target operation. Its mapping and execution policy are inspectable; it is not Plugin-owned code or an iframe-to-iframe connection.
_Avoid_: Plugin protocol extension, arbitrary parser, direct app communication

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

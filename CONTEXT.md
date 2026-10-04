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
A durable, queryable collection of machine-scale outcomes produced by one Batch Run. It is available to agents and users for inspection and may inform an Artifact, but is not itself automatically a curated Artifact. It is retained when its completed Batch Run is archived.
_Avoid_: Artifact, chat transcript, plugin-owned database

**Batch Run**:
One bounded host-orchestrated execution of a Batch Definition over captured Dataset Records. It owns progress, initiator provenance, idempotency, and an immutable input and target snapshot independently of a browser or Agent Run. Agent-proposed execution requires approval; a directly authorized user action does not. Its completed Result Set is retained even when the Run is explicitly archived from normal workspace views.
_Avoid_: Agent Run, Plugin job, Artifact, disposable job

**Batch Definition**:
A durable Project-owned setup that targets either one catalogue-approved MCP tool or one Transform Definition for each Dataset Record. It may be reused to start Batch Runs, but each Run captures the definition and target it actually used.
_Avoid_: Workflow, pipeline, Plugin protocol, run result

**Binding**:
A durable host-owned Project rule that maps an explicitly selected structured value to a declared argument of a target operation. Its mapping and execution policy are inspectable; it is not Plugin-owned code or an iframe-to-iframe connection.
_Avoid_: Plugin protocol extension, arbitrary parser, direct app communication

**Workflow Definition**:
A durable Project-owned plan for a named task. It connects input sources, operations, and Bindings with explicit execution and decision policies. It can be reused for later executions; it does not contain their results.
_Avoid_: Batch Definition, one Run, visual canvas

**Workflow Run**:
One host-orchestrated execution of a Workflow Definition against captured inputs and a captured plan. It records the decisions, child Runs, outputs, and outcome so an earlier execution remains inspectable after inputs or the Definition change.
_Avoid_: Agent Run, Batch Run, mutable result


**Transform Definition**:
A durable project-owned declaration of a user-authored data transformation, including its source, declared inputs, declared output, and runtime identity. It is distinct from a direct Binding and does not grant its source authority to access Project storage, secrets, or the network.
_Avoid_: Binding expression, Plugin-owned state, notebook session

**Input Selection**:
A bounded, ordered choice of values from Project records or retained operation outputs. Its source, derivation, and membership can be inspected and captured for a Run; it need not be an entire Dataset.
_Avoid_: Dataset, untraceable copied JSON, execution mode

**Transform Run**:
One bounded host-orchestrated invocation of a Transform Definition against an immutable selected input snapshot. The selected input may be one value or a collection. The Run records its runtime, inputs, outputs, provenance, and outcome. Repeated invocation over members of a selection is Batch execution.
_Avoid_: Browser preview, Project File, Artifact

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

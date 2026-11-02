---
status: accepted
---

# Use native programmatic tool calling for read-only agent work

Use the pinned `langchain-quickjs` CodeInterpreterMiddleware with the existing
Deep Agents harness. Agent code composes approved read operations using ordinary
MCP arguments and JavaScript variables. This replaces custom file-reference
schemas and selective result-loading adapters. The agent has a small authorized
raw-text read tool because the conversational filesystem reader formats lines
and may truncate output.

PTC's allowlist contains explicit read tool objects, not a general tool dispatcher.
MCP tools require both deployment-reviewed and server-declared read-only status.
Project access, current enablement, schema validation, call limits and read-only
status are checked before dispatch. The programmatic MCP wrappers return typed
`{content, structuredContent}` without calling the ordinary Artifact recorder.
Normal MCP calls outside PTC retain their existing snapshot behaviour.

LangChain's PTC bridge does not enforce per-inner-call `interrupt_on`. Therefore
PTC cannot access file writes/edits/deletion, Artifact/Dataset/Function mutations,
Function execution previews, Workflow authoring/preparation/execution, shell or
subagent delegation. Subagents are disabled explicitly. The allowlist is an
implementation boundary, not a prompt instruction. Existing approval-gated
operations remain available as normal agent tools outside the interpreter.

Use fresh interpreter state per eval, bounded memory/time/call counts, and no
console capture. Intermediate values stay transient and create no Project files,
Artifacts or Workflows. Conversation/checkpoint ownership stays with Agent Hub.
For durable compositions, the main agent leaves eval and proposes a Workflow
with Project File bindings through the existing approval path.

The integration test inspects a real IFC through native PTC, previews metadata,
asserts no durable changes, and requires approval before Workflow creation. It
then exercises normal host Workflow execution. Neither IFC source text nor
intermediate views pass through the model. Tests also prove forbidden tools and
the global subagent bridge are absent, and ordinary file writes still interrupt.

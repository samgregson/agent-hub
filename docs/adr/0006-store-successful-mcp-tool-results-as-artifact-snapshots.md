---
status: accepted
---

# Store successful MCP tool results as Artifact snapshots

Agent Hub persists a Tool Result Snapshot for every successful MCP tool call that returns JSON `structuredContent`; it does not infer a server-wide state or invoke unrelated tools. The host wraps the snapshot in its durable Artifact Envelope, stamping Project placement, identity, version, and provenance. This keeps Plugins stateless and portable while allowing a server to expose unrelated tools such as credits or lookups; each successful invocation is independently saveable. Tool errors create no snapshot, and transient MCP App state is excluded.

## Consequences

The Plugin Catalog need not identify special create, edit, or validate tools. A Plugin's ordinary input and output schemas are its portable contract. Agent Hub validates the Artifact Envelope and configured structured-output shape before persistence; a successful calculation that fails a domain check is represented by its normal result's validation data, rather than a failed tool call. The former complete-document replacement protocol in ADR-0001 and ADR-0003 is superseded for new Plugin integrations, while Agent Hub remains the sole durable owner of Artifact Documents.

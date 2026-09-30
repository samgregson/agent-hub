# Portable Artifact Document and host interface

## Decision

An Artifact is stored as one self-describing JSON-compatible document. Its envelope and payload travel together for portability, but they have different authorities:

- Agent Hub owns Artifact identity, Project placement, the current document version, provenance, and relations.
- The responsible Plugin owns the payload schema, semantic validation, transformations, and optional UI presentation.
- The user may request changes to user-facing metadata through Agent Hub, subject to the same persistence boundary.

The Plugin remains stateless with respect to saved Artifact instances.

## Files, previews, and elevation

A Project File is not automatically an Artifact. Files can be linked from chat and opened in a safe host-provided preview without changing their lifecycle or adding them to the Artifact catalog.

A `/scratch/**` file is Thread-local checkpointed working state rather than a Project File. It can be linked and safely previewed only from its owning Thread, and is never added to the Project file or Artifact catalog.

Creating an Artifact from a Project File is an explicit elevation operation. Initially it can be initiated in either of two ways:

- an agent proposes elevation and the user approves it through the existing human-in-the-loop mechanism; or
- a user explicitly invokes a Plugin save command, which counts as direct authorization and requests creation of an Artifact through the Artifact Module.

Both paths pass through the same Artifact Module validation and persistence boundary. Elevation assigns Artifact identity, envelope, provenance, current document version, and renderer binding. Merely reading, linking, or previewing a file never performs elevation.

Authorization follows the initiator, not merely the tool name. If an agent invokes a Plugin save or elevation tool, the operation pauses for human approval. A save explicitly initiated by the user in Plugin UI does not require a second confirmation.

An Artifact without an available MCP App uses Agent Hub's generic safe renderer. A compatible MCP App is the preferred renderer when present, while the generic renderer remains the fallback. Canonical Artifact documents live under the reserved `/project/.artifacts/**` namespace; generic file tools may read them but cannot write or edit them.

## Illustrative document

```json
{
  "artifact": {
    "id": "art_01J...",
    "type": "example.calculation",
    "documentVersion": 7,
    "title": "Portal frame preliminary check",
    "summary": "Member utilisation and governing case",
    "schema": {
      "id": "com.example.calculation",
      "version": "1.0"
    },
    "plugin": {
      "id": "com.example.calculation-plugin",
      "version": "1.2.0"
    },
    "provenance": {
      "createdBy": { "kind": "agentRun", "threadId": "thr_01J...", "runId": "run_01J..." },
      "lastChangedBy": { "kind": "userAction", "userActionId": "act_01K..." }
    },
    "relations": []
  },
  "payload": {
    "kind": "example-only",
    "inputs": {},
    "results": {},
    "validation": {
      "status": "valid",
      "warnings": []
    }
  }
}
```

This is an architectural example, not the calculation schema. Project ownership and authorization may be indexed outside the exported document so a portable file does not become an access-control token.

## Authority rules

| Region | Authority | Plugin behavior | Agent Hub behavior |
| --- | --- | --- | --- |
| `artifact.id` | Agent Hub | Preserve if supplied | Assign and preserve |
| `artifact.documentVersion` | Agent Hub | Echo expected version | Compare and increment |
| Provenance | Agent Hub | Preserve; may propose operation metadata | Recompute as an authenticated Agent Run or direct User Action |
| Relations | Agent Hub | May propose typed relations | Authorize and persist accepted relations |
| Type and schema binding | Shared contract | Declare supported values | Verify against enabled catalog version |
| Title and summary | User/host | May propose useful updates | Apply through host policy |
| Payload | Plugin | Validate and return canonical replacement | Persist only after successful validation |
| Validation result | Plugin | Compute from the returned payload | Record but do not treat as host authorization |

Unknown envelope fields should be preserved where possible. Agent Hub-specific optional fields must be namespaced and cannot be required by the portable plugin contract.

## Tool Result Snapshots

Plugins expose ordinary MCP tools with declared input and output schemas. Every successful tool call with JSON `structuredContent` becomes an Artifact: Agent Hub records its input and structured output as the Plugin-owned Tool Result Snapshot payload, then assigns the host-controlled envelope. It does not infer or invoke a server-wide state, so unrelated calls such as credits and lookups never become part of another calculation's snapshot.

An MCP App may rehydrate the saved input/output snapshot, invoke the same ordinary tool with changed inputs, and request that Agent Hub replace the current Artifact with the new successful snapshot. Tool failures create no snapshot. A meaningful result that fails a domain check remains a normal structured result with Plugin-owned validation diagnostics; Agent Hub still validates envelope authority and the configured payload shape before persistence.

## Agent Hub edit sequence

1. Invoke one ordinary reviewed MCP tool.
2. On a successful JSON structured result, validate its configured payload shape.
3. Assign or preserve the host-controlled fields, checking the expected document version on replacement.
4. Persist the Tool Result Snapshot payload, host envelope updates, provenance, and project-change notice atomically.
5. Return the saved document and refresh or reopen the MCP App view.

Outside Agent Hub, another MCP client can invoke the same ordinary tool with the same inputs and receive the same calculation, validation, and rendering data. It loses automatic Project lookup, provenance, discovery, and persistence.

## Provenance actors

Every creation and change records one explicit host actor. An `agentRun` actor carries the Thread and Agent Run IDs that initiated the change. A `userAction` actor carries a host-issued action ID for a direct save from Plugin UI; it deliberately does not invent a Thread or Agent Run. The action ID is an audit correlation handle, not an access-control token and not a Plugin requirement.

## Initial limits

- The current document is mutable; a user-facing revision browser is deferred.
- `documentVersion` is a concurrency token, not a promise of retained revision history.
- Cross-Thread live synchronization is deferred; views refresh on focus or reopen initially.
- Large binary payloads will use content references when required rather than embedded base64.
- Raw generic file edits cannot mutate registered Artifact Documents.
- Project Files do not appear in the Artifact catalog until explicitly elevated.
- Chat file links use safe previews and do not imply Artifact creation.

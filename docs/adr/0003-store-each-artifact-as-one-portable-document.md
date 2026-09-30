---
status: accepted
---

# Store each artifact as one portable document

Each Artifact is stored and exported as one self-describing Artifact Document containing a host-controlled envelope and a plugin-controlled payload. Keeping the two authority regions in one portable document lets a stateless MCP Plugin provide and render an Artifact Payload in another compatible client, while Agent Hub preserves identity, provenance, Project relationships, and concurrency metadata when it persists a successful Tool Result Snapshot.

## Consequences

The Artifact Host Adapter validates the Plugin payload's configured shape, assigns or preserves host-controlled fields, increments the host version, records provenance, and then persists the result. A separate indexed catalog may project envelope fields for querying, but it is not a second authoritative Artifact document. ADR-0006 replaces the prior requirement for a Plugin to receive and return a complete Artifact Document for new integrations.

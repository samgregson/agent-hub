---
status: accepted
---

# Store each artifact as one portable document

Each Artifact is stored and exported as one self-describing Artifact Document containing a host-controlled envelope and a plugin-controlled payload. Keeping the two authority regions in one portable document lets a stateless MCP plugin validate, edit, and render the Artifact in another compatible client, while Agent Hub preserves identity, provenance, Project relationships, and concurrency metadata when it accepts a plugin's replacement document.

## Consequences

Plugins receive and return a complete Artifact Document but are not authoritative for every field they echo. The Artifact Host Adapter rejects or replaces changes to host-controlled fields, validates the payload through the responsible plugin, increments the host version, records provenance, and then persists the result. A separate indexed catalog may project envelope fields for querying, but it is not a second authoritative Artifact document.

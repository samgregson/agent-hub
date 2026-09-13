---
status: accepted
---

# Store artifacts in the project Virtual Filesystem

Agent Hub is the sole durable owner of Artifact Documents and stores them in the project Virtual Filesystem. Plugins remain stateless with respect to Artifact data: they own payload schemas, validation, transformations, and UI templates, while Artifact mutations are made through semantic plugin tools that return a complete validated replacement document for Agent Hub to persist. Patches may be added later as an optimization, but are not the only recoverable result.

## Considered options

- Raw file editing was rejected for Artifact mutations because it could bypass domain validation, including future calculation and unit checks.
- Provider-owned persistence was rejected because it would distribute state and databases across plugins and make project-wide discovery, provenance, and lifecycle management inconsistent.

## Consequences

Agent Hub needs an Artifact Host Adapter between its Virtual Filesystem and MCP Apps. Artifact documents may be read through Agent Hub, but writes must pass through the responsible plugin. Initial MCP App refresh may be explicit or occur when the view is focused or reopened; cross-thread live synchronization is not a foundation requirement.

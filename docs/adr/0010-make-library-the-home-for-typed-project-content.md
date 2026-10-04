---
status: accepted
---

# Make Library the home for typed Project content

The Project navigation destination formerly called Work is **Library**. It is the common place to find reusable and produced Project content: ordinary Project Files, registered Datasets, and Artifacts. Each keeps its own identity, lifecycle, and viewer. Operations remain separately managed definitions, and Workflow Definitions bind Library content and operation outputs into executable dependency graphs. An authored MDX calculation or template and a calculation produced from it may both be Library items with separate identities and provenance.

A Dataset is a registered, typed Project File in the Project Virtual Filesystem. The Dataset Module owns its identity, stable ordered Record IDs, validation, and writes; ordinary file operations may read its canonical content but cannot mutate or delete it. A catalog/query projection may index that content but cannot become a second source of truth. A Workflow or Batch Run captures the exact Dataset version, selected Record IDs and values, and any other versioned file input it consumes. Merely storing or viewing a Dataset as a file does not make it an Artifact.

## Considered options

- Keep Datasets in a separate Data destination and database record store. This preserves the current implementation but splits reusable Project content by storage type and makes Work/Library unclear.
- Treat a Dataset as an unrestricted JSON Project File. This would let generic file writes bypass Record identity, validation, and references used by Batch Runs.
- Register a typed file with Dataset-owned writes and a dedicated viewer. This unifies discovery and agent file access while preserving Dataset semantics.

## Consequences

Issue #45 owns migration from the current Dataset tables to canonical typed Project Files, including compatibility, protected writes, and existing Run snapshots. Issue #37 owns Library placement and the eventual rail rework. Until those slices ship, the current Dataset APIs and separate navigation remain functional. Artifact elevation and Result Set ownership do not change. Typed file and Artifact inputs to MCP operations need explicit Binding contracts rather than filename inference.

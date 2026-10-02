---
status: accepted
---

# Make Transform execution scope explicit

A Transform Definition describes a computation, while the selected execution scope determines how often it runs and which durable result owns the outcome. A direct Transform Run invokes the Definition once against one immutable selected input snapshot. Applying that Definition separately to selected Dataset Records uses a Batch Definition and creates a Batch Run with a Result Set. A future whole-Dataset Transform Run will invoke the Definition once against a captured Dataset snapshot to support collection-level work such as aggregation, sorting, or deduplication. These are distinct execution shapes, not separate Python runtimes.

## Considered options

- Treat every whole-Dataset request as a per-record Batch Run. This cannot express computations that need the collection together.
- Let users manually pack Dataset Records into a single JSON input. This loses Dataset provenance and is constrained by the current single-input limits.
- Introduce a second Transform runtime for collection work. That would break the single host-runner decision in [ADR 0007](0007-use-one-deno-hosted-pyodide-runner.md) and make preview and durable behavior diverge.

## Consequences

The existing per-record path remains the Batch Definition and Result Set. Whole-Dataset execution is a future capability, not a claim about the current API: it needs a captured Dataset snapshot, bounded input and output contracts, provenance, and suitable limits before the UI can offer it. Preview and durable execution use the host-side Deno/Pyodide runner in every scope. Completion does not automatically create a Dataset or Artifact. The Project explorer may group these operations for usability while preserving the distinct Definition, Run, and Result Set records.

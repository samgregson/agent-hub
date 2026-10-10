---
status: accepted
---

# Separate input selection from invocation cardinality

An operation's input is a captured, bounded selection of values, not a fixed choice between one item and an entire Dataset. A selection may come from Dataset Records, a filtered or ordered subset, a Result Set, or retained output of an MCP tool or Transform. The host records the selected values and their derivation so later changes do not rewrite a Run's history. Selection and invocation cardinality are separate: a Transform may consume a selected value or collection in one invocation, or the host may invoke the target independently for each selected member. These execution details do not define separate top-level UI destinations.

## Considered options

- A UI choice between “run once,” “apply to Dataset,” and “run on whole Dataset” was rejected as a primary model. It does not describe filtered subsets, sorted top-N selections, or values flowing from earlier operations.
- Manually packing records or prior outputs into JSON loses selection provenance and bypasses a reviewable, bounded input contract.
- A separate runtime for collection work would conflict with the single host-side Deno/Pyodide runner in [ADR 0007](0007-use-one-deno-hosted-pyodide-runner.md).

## Consequences

The existing API remains narrower than this model: a direct Transform Run accepts one explicit JSON input, and a Batch Definition currently applies a target to selected Dataset Records and produces a Batch Run and Result Set. Supporting derived selections, retained output sources, and collection-valued inputs requires explicit capture, limits, validation, and provenance. The UI should show where input came from, which values were selected, how many invocations will occur, and where the outputs went, without presenting a Dataset-wide mode as a special category. Saved filter, sort, and limit defaults are for previews only: they do not alter downstream Bindings or silently select a durable Run's input. A durable Run captures an explicitly chosen input and derivation; downstream operations use their own declared Bindings and captured upstream outputs. Durable results do not automatically create a Dataset or Artifact. Agent-initiated consequential actions retain HITL approval.

---
status: accepted
---

# Make Project Workflows the task entry point

A Project opens on its current Workflow overview when one is present. A Workflow Definition names the user's task and connects sources, operations, and Bindings as a bounded directed acyclic graph. Independent branches may execute and later converge when their declared inputs are available. The host executes that graph as a Workflow Run, pausing at required decisions or approvals. Batch Runs, Transform Runs, Result Sets, and Artifacts remain distinct records linked from the Workflow Run. Projects may contain more than one Workflow, but navigation is optimized for the common case of one active Workflow rather than starting with a list.

The overview must explain dependencies, branches, joins, current state, and where each result came from. It should not imply a numbered linear sequence or require a visual-programming editor. If the user changes inputs and asks to iterate, the host starts another Workflow Run with a new snapshot and keeps earlier Runs inspectable for comparison. A run's completion does not automatically turn Result Sets or Transform outputs into Artifacts. Issue #42 remains a concrete test fixture, not the template for Workflow names or UI structure.

## Considered options

- Start in a catalogue of Datasets, Transform Definitions, and Batch Definitions. This exposes reusable records but leaves the user's engineering task and dataflow implicit.
- Use only a read-only grouping of independently started operations. This does not support the requested “iterate on inputs to drive outputs” behavior as one bounded chain.
- Treat child Batch and Transform Runs as the Workflow Definition itself. That would mix a reusable plan with immutable execution history.

## Consequences

Issue #37's prototype should test a task-first overview with readable DAG dependencies, drill-down into nodes and provenance, and one primary surface on narrow screens before production navigation changes. A durable Workflow Definition and Workflow Run need their own implementation slice; the current Binding cascade in issue #32 is a related capability, not a complete Workflow record or run coordinator. The first UI can foreground one Workflow without imposing a one-Workflow-per-Project limit. A directly authorized user start or an approved agent proposal can execute the displayed bounded chain; unseen expansion and consequential agent actions pause for the appropriate decision. Preview-only filter, sort, and limit defaults remain outside execution semantics as decided in [ADR 0008](0008-separate-input-selection-from-invocation-cardinality.md).

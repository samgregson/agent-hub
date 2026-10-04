---
status: accepted
---

# Make Project Workflows the task entry point

A Project opens on its current Workflow overview when one is present. A Workflow Definition names the user's task and connects sources, operations, and Bindings into a bounded executable plan. The host executes that plan as a Workflow Run, pausing at required decisions or approvals. Batch Runs, Transform Runs, Result Sets, and Artifacts remain distinct records linked from the Workflow Run. Projects may contain more than one Workflow, but the navigation is optimized for the common case of one active Workflow rather than starting with a list.

For the floor-beam example in issue #42, the user opens “Review floor-beam deflection,” sees the beam schedule, the per-beam check, failed-check Transform, sizing step, and draft note as one task, and can inspect each step's captured inputs and outputs. If the user changes the beam inputs and asks to iterate, the host starts another Workflow Run with a new snapshot and keeps the earlier Run inspectable for comparison. A run's completion does not automatically turn Result Sets or Transform outputs into Artifacts.

## Considered options

- Start in a catalogue of Datasets, Transform Definitions, and Batch Definitions. This exposes reusable records but leaves the user's engineering task and dataflow implicit.
- Use only a read-only grouping of independently started operations. This does not support the requested “iterate on inputs to drive outputs” behavior as one bounded chain.
- Treat child Batch and Transform Runs as the Workflow Definition itself. That would mix a reusable plan with immutable execution history.

## Consequences

Issue #37's prototype should test a task-first overview, drill-down into steps and provenance, and one primary surface on narrow screens before production navigation changes. A durable Workflow Definition and Workflow Run need their own implementation slice; the current Binding cascade in issue #32 is a related capability, not a complete Workflow record or run coordinator. The first UI can foreground one Workflow without imposing a one-Workflow-per-Project limit. A directly authorized user start or an approved agent proposal can execute the displayed bounded chain; unseen expansion and consequential agent actions pause for the appropriate decision. Preview-only filter, sort, and limit defaults remain outside execution semantics as decided in [ADR 0008](0008-separate-input-selection-from-invocation-cardinality.md).

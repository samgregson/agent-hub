---
status: accepted
supersedes: [ADR-0006, ADR-0008, ADR-0011, ADR-0012]
---

# Workflow owns bindings and execution

Python Functions define reusable behavior and named input/output contracts. Workflow steps own explicit graph bindings that map whole values or selected fields from Project sources, upstream step outputs, per-run Workflow Inputs, and literal values into declared target inputs. RFC 6901 JSON Pointer paths select source fields and assemble target paths; the empty path means the whole value. Multiple non-overlapping bindings can assemble nested target values. Workflow Inputs declare a JSON Schema and are supplied when a Run is prepared; each Run captures those exact values. Routine field alignment belongs in the graph rather than requiring adapter Functions; calculations and other actual transformations remain Functions. Bindings must be reviewable and checked against the source and target contracts before execution. Filtering, sorting, and other data preparation are ordinary Python Functions connected in the Workflow; there is no separate selection-rule model. Function previews are transient, and saved preview defaults never affect a Workflow Run.

Issue [#50](https://github.com/samgregson/agent-hub/issues/50) tracks implementation of field selection, target assembly, per-run inputs, and binding inspection.

The Workflow Run is the durable execution record for Python and MCP steps. It captures source versions, exact inputs, step outputs, failures, and lineage so prior results remain inspectable and immutable. Separate Batch Definitions, Batch Runs, Result Sets, and user-started Transform Runs are not Workflow concepts. MCP calls execute through the host Plugin Gateway; Python Functions use the shared host-side Deno/Pyodide runner and cannot call MCP tools directly. Consequential Project changes and Workflow execution initiated by an agent remain approval-gated.

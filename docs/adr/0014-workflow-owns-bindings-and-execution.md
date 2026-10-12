---
status: accepted
supersedes: [ADR-0006, ADR-0008, ADR-0011, ADR-0012]
---

# Workflow owns bindings and execution

Python Functions define reusable behavior and named input/output contracts. Workflow steps own connections, shared inputs, and whether a target is called once or mapped over a bounded collection. Filtering, sorting, and other data preparation are ordinary Python Functions connected in the Workflow; there is no separate selection-rule model. Function previews are transient, and saved preview defaults never affect a Workflow Run.

The Workflow Run is the durable execution record for Python and MCP steps. It captures source versions, exact inputs, step outputs, failures, and lineage so prior results remain inspectable and immutable. Separate Batch Definitions, Batch Runs, Result Sets, and user-started Transform Runs are not Workflow concepts. MCP calls execute through the host Plugin Gateway; Python Functions use the shared host-side Deno/Pyodide runner and cannot call MCP tools directly. Consequential Project changes and Workflow execution initiated by an agent remain approval-gated.


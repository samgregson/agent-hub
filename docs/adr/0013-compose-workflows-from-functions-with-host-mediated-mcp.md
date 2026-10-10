---
status: accepted
---

# Compose Workflows from Functions with host-mediated MCP calls

The target Workflow model composes reusable Functions with named, schema-described inputs and outputs as a bounded DAG. A Function can process one item or a collection; the Workflow explicitly maps an item Function over a collection when repeated invocation is intended. Python Functions may request only declared MCP capabilities through reserved callables, while Agent Hub executes those calls outside the isolated runner and applies authorization, approval, bounds, and provenance. The graph shows each Function's purpose, data connections, and declared capabilities; a Run retains actual MCP calls and immutable node inputs and outputs. This provides flexible Python behavior with a reviewable graph and avoids a separate subgraph mechanism in the first slice.

The existing Transform, Batch, Binding, and Input Selection records remain working delivery slices while their user-facing concepts are consolidated. ADR 0012's Dataset-wide and per-Record command describes the current interface; the target graph expresses those cases as a collection-input Function call or an explicit Map call. Preview defaults still have no effect on durable inputs. The implementation must define a bounded runner-to-host call protocol and pause/resume semantics for MCP approvals before enabling Python-originated MCP calls.

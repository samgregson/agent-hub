---
status: accepted
---

# Compose Workflows from Python Functions and MCP tools

The Workflow model composes reusable Python Functions and catalogued MCP tools as distinct call targets in a bounded DAG. A Function owns its Python code, purpose, and named input/output contracts; it does not own where its inputs come from or how many times the Workflow invokes it. Workflow steps own graph connections, input bindings, and invocation policy. A step may call a target once with its declared input (including a collection when that is the Function's ordinary input), or use Map to invoke an item-input target for each member of a bounded collection. Map is a Workflow execution policy, not a Function mode or a separate Batch Definition.

Agent Hub invokes MCP tools through the host Plugin Gateway and applies authorization, approval, bounds, and provenance. The graph exposes each step and its data connections before execution; a Workflow Run retains exact inputs, outputs, and tool calls. Python remains inside the isolated host-side Deno/Pyodide runner without direct MCP, network, credential, or Project storage access. The Functions area is for authoring and testing Python Functions. MCP tools are discovered from enabled Plugins and become available as Workflow call targets; they are not authored as Python Functions.

This keeps external calls statically visible and avoids a runner-to-host callback and mid-Function approval protocol. Python-originated MCP requests are deferred until a concrete Workflow cannot express the need with direct MCP calls and Map. Workflow edges connect Project File, Dataset, and upstream-step outputs to named step inputs. A Map MCP step uses its collection input and may receive additional shared inputs, such as Project File content, which the host merges into every item call after rejecting key collisions and validating the complete MCP schema. Preparation pins source contents and versions. Bindings exist in the graph as visible connections and input configuration; they are not a separate reusable project object. Preview defaults still have no effect on durable inputs.

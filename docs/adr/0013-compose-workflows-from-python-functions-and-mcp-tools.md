---
status: accepted
---

# Compose Workflows from Python Functions and MCP tools

The target Workflow model composes versioned Python Function Definitions and catalogued MCP tools as calls with named, schema-described inputs and outputs in a bounded DAG. A Python Function can process one item or a collection; an explicit Map call applies an item-input Function or MCP tool to each member of a collection. Agent Hub invokes MCP tools through the host Plugin Gateway and applies authorization, approval, bounds, and provenance. The graph exposes each call and its data connections before execution; a Run retains exact inputs, outputs, and tool calls. Python remains inside the isolated host-side Deno/Pyodide runner without direct MCP, network, credential, or Project storage access.

This keeps external calls statically visible and avoids a runner-to-host callback and mid-Function approval protocol. Python-originated MCP requests are deferred until a concrete Workflow cannot express the need with direct MCP calls and Map. Workflow edges connect Project File and Dataset sources to named call inputs. A Map MCP node uses its `items` edge for the collection and may receive additional shared inputs, such as Project File content, which the host merges into every item call after rejecting key collisions and validating the complete MCP schema. Preparation pins the source contents and versions. This replaces the former file Binding record and UI; the Binding Module and its migration were removed once the Workflow path covered the delivered use case. Preview defaults still have no effect on durable inputs.

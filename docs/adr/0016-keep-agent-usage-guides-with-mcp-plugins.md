---
status: accepted
---

# Keep agent usage guides with MCP Plugins

A Plugin owns the instructions for using its domain tools. Keep a versioned
Markdown guide inside the Plugin directory and serve it through an MCP resource.
Expose a small read-only guide tool as the discovery path for agents that consume
tools but do not yet browse MCP resources. IFC is the first implementation:
`AGENT_GUIDE.md`, `resource://agent-hub-ifc-viewer/agent-guide`, and `get_ifc_guide`.

Short tool descriptions point to the guide. The main agent loads relevant guides
on demand; Agent Hub neither imports Plugin files nor duplicates domain recipes
in its global prompt. Guides explain contracts and composition, but cannot grant
permissions, change Project scope or override host approval controls. This uses
ordinary MCP capabilities without introducing a separate host skill registry.
Other Plugins can adopt this pattern independently.

The host must preserve a tool's JSON Schema, including nullable unions and
referenced definitions, when exposing it to the model. Successful captured
structured results return their Artifact ID to the agent so it can load exact
object records for subsequent calls rather than guessing or relying on a terse
model-visible success summary. The result callback now optionally returns that
compact saved-result reference.

An integration test uses the actual main-agent graph, its Project filesystem,
Artifact tools and an independent HTTP IFC service to exercise guide loading,
IFC reading, inspection, result recovery, GlobalId assignment and a saved view.
Its deterministic model verifies integration; live-model task quality remains a
separate evaluation.

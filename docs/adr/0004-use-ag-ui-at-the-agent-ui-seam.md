---
status: accepted
---

# Use AG-UI at the agent-to-UI seam

Agent Hub will expose its self-hosted Deep Agent through AG-UI rather than LangChain's licensed standalone Agent Server or an Agent Hub-specific streaming protocol. Deep Agents produces a compiled LangGraph graph, the open `ag-ui-langgraph` adapter exposes that graph through FastAPI, and assistant-ui provides a first-party AG-UI runtime; either side can therefore be replaced by another AG-UI-compatible implementation without changing the other.

## Consequences

Agent Hub keeps Project and Thread navigation in its own application modules rather than depending on assistant-ui's currently experimental AG-UI thread-list adapter. The first vertical slice must prove interrupt/resume because assistant-ui currently marks that part of its AG-UI runtime experimental. Protocol and adapter versions are pinned together and exercised by contract tests.

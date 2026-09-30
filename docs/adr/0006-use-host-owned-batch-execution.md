---
status: accepted
---

# Use host-owned batch execution

Agent Hub will persist and execute Dataset Batch Runs through a host-owned Batch Execution Module, rather than use Deep Agents asynchronous subagents or a Plugin-owned database. Both direct user actions and approved agent tools create the same durable Batch Run and Result Set; LangGraph interrupts govern agent approval, while AG-UI only provides the conversational hand-off. This keeps high-volume MCP invocations, result provenance, recovery, and queryability independent of a browser connection or conversational Agent Run.

## Considered options

- Deep Agents asynchronous subagents were rejected as the executor because they run background AI-agent work and return job IDs, but do not provide the Dataset snapshot, per-record MCP policy, Result Set, or query contract required here.
- Plugin-owned batch persistence was rejected because it distributes Project data, provenance, and discovery across servers.

## Consequences

The first implementation uses PostgreSQL with explicit size limits. Batch-capable tools are catalogued as safe for repeated execution and return ordinary MCP structured output with declared schemas. A completed Result Set is an immutable execution snapshot; completed Batch Runs may be archived from normal views but are not erased. Native summaries and explicit Artifact elevation avoid producing an Artifact for every result.

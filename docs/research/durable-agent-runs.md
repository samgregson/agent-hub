# Durable Deep Agent runs and browser reconnection

Research checked 18 November 2026. This note describes capabilities and design options, not an adopted architecture decision.

## Supported primitives

Deep Agents supports human approval through LangGraph interrupts and a checkpointer. LangGraph uses the thread ID to find persisted checkpoints. An interrupted graph is resumed with `Command(resume=...)`; to retry unfinished work after an error, the documented graph invocation uses `None` with the same thread configuration. Reusing a thread ID alone does not resume execution. See [Deep Agents human-in-the-loop](https://docs.langchain.com/oss/python/deepagents/human-in-the-loop) and [LangGraph checkpointers](https://docs.langchain.com/oss/python/langgraph/checkpointers).

Checkpointing saves execution state; it does not by itself provide a worker that continues consuming the graph after an HTTP request is cancelled. Interrupted nodes restart from their beginning when resumed, so side effects before an interrupt or retry must be idempotent or otherwise reconciled. See [LangGraph interrupts](https://docs.langchain.com/oss/python/langgraph/interrupts).

## Two hosting approaches

1. **Agent Hub owns background execution.** Keep the existing self-hosted Deep Agent, PostgreSQL checkpointer and AG-UI interface. Introduce a backend-owned worker and durable run lifecycle, separate from client subscriptions. Persist enough state and events for an authorized client to restore a snapshot and follow a running job. Coordinate exclusive thread execution, cancellation, worker recovery, pending approvals and uncertain external tool outcomes. A process-local background task alone survives a browser disconnect but not a process restart or deployment.
2. **Use LangSmith Agent Server.** Its documented deployment uses background workers, PostgreSQL and Redis, and its API can join an existing run's stream. Its ordinary `join_stream` documentation explicitly says earlier output is not buffered, so history and replay behavior must be verified for the selected server configuration and SDK version. The self-hosted data-plane documentation describes license validation; confirm operational and licensing requirements before adopting it. See [LangSmith data plane](https://docs.langchain.com/langsmith/data-plane) and [Streaming API](https://docs.langchain.com/langsmith/streaming#join-and-stream).

These are different from merely installing the open-source `langgraph` library: LangSmith Agent Server is a separate deployment product. Adopting it also needs evaluation against Agent Hub's project authorization, plugin gateway, tool approvals and AG-UI contracts.

## Client integration

Assistant-ui documents an AG-UI durable-thread pattern that loads the saved transcript and reconnects to an active run. Its concrete Python `DurableAGUI` server example is for Pydantic AI; it is not evidence of a drop-in LangGraph adapter. Assistant-ui also documents restoring history through `useAgUiRuntime`'s history adapter and resuming an in-flight run. Check these capabilities against the repository's pinned versions before designing around them. See [assistant-ui durable threads](https://www.assistant-ui.com/docs/runtimes/ag-ui/durable-threads) and [AG-UI runtime options](https://www.assistant-ui.com/docs/runtimes/ag-ui/runtime-options).

## Current Agent Hub boundary and recommended investigation

Agent Hub already constructs a Deep Agent with a PostgreSQL checkpointer, restores thread state and interrupts, and presents assistant-ui through `useAgUiRuntime`. The backend presently drives the agent by iterating the run within the response stream and records cancellation when that iterator closes; startup reconciles nonterminal runs. These are not yet independent background jobs or reattachable event streams. See `apps/api/src/agent_hub_api/modules/agent_execution/_deep_agent.py`, `_execution.py`, and `apps/api/src/agent_hub_api/modules/agent_transport/_http.py`.

For an initial prototype, evaluate host-owned background execution using the existing Postgres deployment and AG-UI boundary. Prove: a browser disconnect while a run continues; reconnect without missing or duplicate messages; restoration and resolution of a pending approval; explicit stop; and worker restart with safe handling of an unknown external tool outcome. Compare that with Agent Server's deployment and adapter cost before committing to either architecture. Do not silently rerun a non-idempotent tool whose outcome is unknown.

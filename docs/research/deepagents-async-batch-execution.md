# Deep Agents, LangGraph, and durable batch execution

Research date: 2026-09-23

## Conclusion

Agent Hub should use a **host-owned Batch Execution Module**, not Deep Agents' async-subagent facility, for Dataset Batch Runs. The two solve different problems:

- Deep Agents `AsyncSubAgent` delegates an AI task to a remote/background LangGraph agent and returns a job identifier immediately.
- A Batch Run executes a declared MCP tool over durable Dataset records and must retain Result Records, provenance, partial failure state, and host policy independently of any conversational Agent Run.

The agent and the direct user should both start the same durable Batch Run. For an agent-proposed run, a LangGraph interrupt obtains approval; resumption calls a host `start_batch_run` tool, which creates the Batch Run and hands it to the executor. The AG-UI stream may remain open only for a short bounded wait for a fast result; it must not own the worker lifetime.

```text
agent tool call -> LangGraph interrupt -> approval -> start_batch_run
                                                    |
direct user action --------------------------------+-> Batch Execution Module
                                                         -> durable Batch Run / Result Set
                                                         -> bounded MCP calls

AG-UI conversation <- immediate Batch Run reference / short-wait result
later agent turn   <- inspect_batch_run / query_result_set host tools
```

## Primary-source findings

LangGraph interrupts are the appropriate approval primitive. `interrupt()` saves graph state through the checkpointer and waits indefinitely for an external JSON-serializable response; invoking the same graph `thread_id` with `Command(resume=...)` resumes it. [LangGraph interrupts](https://docs.langchain.com/oss/python/langgraph/interrupts)

An interrupted node restarts from its beginning when resumed. Therefore a Batch Run must not be created before the approval interrupt unless creation is idempotent; keep the interrupt first, then create the run after approval. [LangGraph interrupt rules](https://docs.langchain.com/oss/python/langgraph/interrupts#rules-of-interrupts)

LangGraph positions checkpointers as thread-scoped graph state for conversation, interrupts, and fault tolerance, while stores are application-defined cross-thread data. Neither should replace Agent Hub's Project-scoped relational persistence for Datasets, Batch Runs, and Result Sets. [LangGraph persistence](https://docs.langchain.com/oss/python/langgraph/persistence)

Deep Agents supports `AsyncSubAgent` specifications. They are remote/background subagent graphs identified by `graph_id` and optional URL/headers, exposed through middleware distinct from synchronous `task` subagents. [Deep Agents graph assembly](https://github.com/langchain-ai/deepagents/blob/main/libs/deepagents/deepagents/graph.py)

LangChain's async-subagent guidance describes this as a separate-process/service background job that returns a job ID while the supervisor continues. Its reference architecture creates a separate LangGraph thread/run for each job and provides launch/check/update/cancel/list operations. [LangChain subagents](https://docs.langchain.com/oss/python/langchain/multi-agent/subagents), [Deep Agents async-subagents reference](https://github.com/langchain-ai/async-deep-agents)

This is useful later for long-running **agent reasoning**—for example, a specialist reviewing a completed Result Set—but it is not an MCP batch executor. It lacks the Batch Run's required Dataset snapshot, MCP tool policy, per-record result persistence, and query contract. Building those responsibilities into a subagent would duplicate Agent Hub's domain model and tie durable engineering data to an agent thread.

## Recommended interaction behaviour

1. The user or agent selects a saved Dataset and Batch Definition.
2. Agent-proposed execution interrupts for the already-agreed batch approval. Direct user execution uses the same command without an agent interrupt.
3. After approval, `start_batch_run` atomically creates a durable Batch Run with its Dataset snapshot, selected record IDs, Batch Definition snapshot, tool identity/schema version, concurrency policy, and initiator provenance.
4. The execution module performs the first real invocation. A failure or invalid structured result stops dispatch before fan-out; otherwise it dispatches the remaining calls within the host concurrency limit.
5. The initiating agent tool returns a Batch Run reference. It may await a short, explicitly bounded completion window and return a compact summary if complete; otherwise it returns “started” and ends the conversational run normally.
6. The workspace receives progress from Agent Hub's application API (polling initially is sufficient). A later user turn lets the agent call host tools to inspect the persisted summary or query Result Records.

Do not automatically reawaken an agent when a Batch Run completes in the first version. The async-subagent reference also treats completion notification as application-owned, rather than a built-in supervisor behaviour. [Async-subagents completion notifications](https://github.com/langchain-ai/async-deep-agents#completion-notifications)

## Constraints and test implications

- The worker must be independently recoverable from AG-UI disconnects, browser reloads, and Agent Run completion.
- Use persistent PostgreSQL records for the Batch domain; use a durable LangGraph checkpointer for the approval/resume path. `MemorySaver`/`InMemorySaver` lose state on restart. [LangGraph persistence](https://docs.langchain.com/oss/python/langgraph/persistence)
- Treat Batch Run creation as idempotent across resumed/replayed graph execution. Record an idempotency key tied to the approved request.
- A completed Batch Run must never write messages or state into an unrelated or superseding Thread. The Deep Agents example's documented async cancellation/interrupt race is a reminder not to use fire-and-forget tasks without an execution generation/ownership check. [Deep Agents example race report](https://github.com/langchain-ai/deepagents/issues/5401)
- Contract-test: approval/resume creates exactly one Batch Run; direct-user and agent starts create equivalent records; AG-UI disconnect does not stop execution; a slow run ends the Agent Run with a reference; a fast run returns a summary; first-item failure prevents fan-out.

## Decision supported

Use **LangGraph interrupts plus a host tool** for agent-initiated Batch Runs, and a **durable host-owned executor** for their lifecycle. Keep Deep Agents async subagents available as a later, separate capability for background reasoning—not as the implementation of Dataset batch calculations.

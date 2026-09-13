# LangChain conversation terminology

This note records the meanings Agent Hub should take from the current official LangChain, LangGraph, Deep Agents, and LangSmith documentation. The terms overlap across runtime, persistence, observability, and product UI, so the layer matters.

## Recommended vocabulary

| Term | Meaning in the LangChain ecosystem | Recommended Agent Hub use |
| --- | --- | --- |
| **Thread** | The durable, thread-scoped execution context identified by `thread_id`. In LangGraph persistence, it contains the accumulated graph state from a sequence of runs; its current and historical state are checkpoints. Agent Server also describes it as a persistent conversation container that retains state between runs. ([LangGraph persistence](https://docs.langchain.com/oss/python/langgraph/persistence), [Agent Server threads](https://docs.langchain.com/langsmith/use-threads)) | Use **Thread** for one resumable agent conversation/work stream inside a project. It is neither an artifact nor merely a screen: it is the persistence boundary for conversation messages, agent state, and the Deep Agents state-backed virtual filesystem. |
| **Run** | In Agent Server, one invocation of an assistant, optionally against a thread; a run has its own input, configuration overrides, and metadata. A threaded run reads and updates thread state, while a stateless run does not persist conversation state. ([Agent Server runs](https://docs.langchain.com/langsmith/runs)) | Use **Run** for one submitted execution within a thread—for example, processing one user turn through completion, interruption, cancellation, or failure. Do not use it as a synonym for the whole conversation. |
| **Checkpoint** | An immutable snapshot of graph state at a particular super-step boundary. A thread has a sequence/history of checkpoints. A checkpoint captures state values, what runs next, metadata, tasks, and links to its preceding checkpoint; updating state creates another checkpoint rather than mutating the old one. ([LangGraph persistence](https://docs.langchain.com/oss/python/langgraph/persistence)) | Treat checkpoints as runtime persistence and recovery/audit records beneath the product model. They support resume, human approval, fault recovery, history, and later branching, but should not be presented as ordinary chat messages. |
| **State** | The graph's typed working data, updated as nodes execute and saved by a checkpointer. Messages can be one state channel, alongside arbitrary application state. Thread-scoped state is short-term memory; a separate Store holds application-defined, cross-thread long-term memory. ([LangGraph persistence](https://docs.langchain.com/oss/python/langgraph/persistence), [LangChain memory](https://docs.langchain.com/oss/python/concepts/memory)) | Keep **thread state** distinct from durable project records. Messages and working files may live in thread state initially. Project-wide instructions, plugin configuration, durable artifacts, and shared memory need explicit product storage rather than being assumed to come from checkpoints. |
| **Conversation / chat** | Descriptive concepts rather than a separate canonical LangGraph persistence resource. Official docs repeatedly equate a thread with a conversation for conversational agents; LangSmith calls a thread a sequence of traces representing one conversation. “Chat” also names a UI/application pattern and message-based interaction. ([LangSmith observability concepts](https://docs.langchain.com/langsmith/observability-concepts), [LangGraph persistence](https://docs.langchain.com/oss/python/langgraph/persistence)) | Use **conversation** in user-facing prose and **chat** for the interaction surface. Back each saved conversation with a LangGraph/Agent Server **Thread** unless there is a specific reason to introduce another product entity. |
| **Session** | Not a single standardized LangGraph domain object. Some docs use “session” informally for a period of interaction or continuity. In LangSmith tracing, `session_id`, `thread_id`, and `conversation_id` are accepted metadata keys for grouping traces into a thread; elsewhere, memory is described as crossing “sessions.” ([Configure LangSmith threads](https://docs.langchain.com/langsmith/threads), [LangChain memory](https://docs.langchain.com/oss/python/concepts/memory)) | Avoid making **Session** a persisted domain entity in the foundation. If needed later, reserve it for an ephemeral browser/authentication/usage session and never use it interchangeably with thread IDs in application code. |

## Relationships

For the Agent Server runtime, the useful hierarchy is:

```text
Project (Agent Hub product boundary; not defined by LangGraph)
└── Thread (persistent state / one resumable conversation)
    ├── Run (one assistant invocation)
    │   └── graph steps / tasks
    └── Checkpoints (successive snapshots of graph state)
```

A run is not necessarily threaded: Agent Server supports stateless runs. For Agent Hub's conversational UI, normal user submissions should be stateful runs on a thread. ([Agent Server runs](https://docs.langchain.com/langsmith/runs))

Deep Agents follows the same persistence boundary. Its default `StateBackend` virtual filesystem is stored in LangGraph state and lasts only within one thread; cross-thread files or memory require a Store-backed backend or another durable backend. ([Deep Agents customization](https://docs.langchain.com/oss/python/deepagents/customization), [Deep Agents context engineering](https://docs.langchain.com/oss/python/deepagents/context-engineering))

## Important ambiguities

### “Run” has two official meanings

Agent Server uses **run** for an assistant invocation. LangSmith Observability also uses **run** for an individual tracing span, so one Agent Server run can produce an observability trace containing a root run plus child runs for model calls, tools, and other units of work. In architecture documents, qualify these as **agent run** and **trace run/span** whenever both layers are discussed. ([Agent Server runs](https://docs.langchain.com/langsmith/runs), [LangSmith observability concepts](https://docs.langchain.com/langsmith/observability-concepts))

### LangSmith threads and Agent Server threads align, but are described differently

Agent Server threads are persistence resources whose runs update graph state. In the observability model, threads group traces by shared metadata; LangSmith accepts `thread_id`, `session_id`, or `conversation_id` for that grouping. Agent Hub should use one canonical `thread_id` and propagate it into tracing metadata, rather than model three identifiers. ([Agent Server threads](https://docs.langchain.com/langsmith/use-threads), [Query LangSmith threads](https://docs.langchain.com/langsmith/query-threads))

### “Conversation” does not imply messages are the entire state

Official examples often call a thread a conversation, but persisted graph state can contain messages plus arbitrary values, tasks, interrupts, and Deep Agents working files. Therefore, the central chat view is a projection of thread state—not the complete definition of a thread. ([LangGraph persistence](https://docs.langchain.com/oss/python/langgraph/persistence), [Deep Agents overview](https://docs.langchain.com/oss/python/deepagents/overview))

## Architecture consequence for Agent Hub

Adopt `Project -> Thread -> Run` as the product/runtime containment model, while treating checkpoints as infrastructure records. Map one saved user-visible conversation to one LangGraph thread. Keep artifacts as separate, first-class project records with provenance links to the originating thread, run, and artifact version; LangChain does not define that artifact ownership model, so it remains an Agent Hub design decision.

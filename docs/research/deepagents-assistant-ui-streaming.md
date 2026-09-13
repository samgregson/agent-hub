# Deep Agents to assistant-ui streaming seam

Research date: 2026-09-12

## Revised conclusion

Use AG-UI as the open protocol seam between Agent Hub's Python backend and assistant-ui.

Deep Agents produces a compiled LangGraph graph. The open `ag-ui-langgraph` integration accepts compiled LangGraph graphs, creates FastAPI endpoints, translates messages/tool calls/state, and supports LangGraph interrupts. assistant-ui provides a first-party `@assistant-ui/react-ag-ui` runtime. Agent Hub therefore does not need LangChain's separately licensed standalone Agent Server or a proprietary streaming protocol. [AG-UI LangGraph Python integration](https://github.com/ag-ui-protocol/ag-ui/tree/main/integrations/langgraph/python), [assistant-ui AG-UI runtime](https://www.assistant-ui.com/docs/runtimes/ag-ui/overview)

This decision preserves replaceability in both directions: another AG-UI frontend can consume Agent Hub's agent endpoint, and assistant-ui can consume another AG-UI agent implementation.

## Primary-source findings

assistant-ui's LangChain runtime is an official adapter over LangChain's `useStream`. It supports streamed messages, tool calls, arbitrary graph state, subagents/subgraphs, interrupts and responses, checkpoint-based editing/regeneration, errors, and cancellation. The official starter template now uses this runtime. [assistant-ui LangChain runtime](https://www.assistant-ui.com/docs/runtimes/langchain)

assistant-ui also maintains `@assistant-ui/react-langgraph`, which talks to `@langchain/langgraph-sdk` directly. Its documented feature set includes streaming, subgraph events, UI messages, metadata, interrupts, checkpoint behavior, and end-to-end cancellation. Both adapters require a LangGraph-compatible API server rather than an arbitrary application event stream. [assistant-ui LangGraph runtime](https://www.assistant-ui.com/docs/runtimes/langgraph/overview)

The production quickstart recommends a same-origin Next.js proxy so LangGraph/LangSmith credentials remain server-side instead of being exposed to the browser. [assistant-ui LangGraph quickstart](https://www.assistant-ui.com/docs/runtimes/langgraph/quickstart)

LangGraph checkpoint persistence is organized by `thread_id` and supports resume after interrupts and failures. This makes the runtime Thread—not the browser stream—the source of truth for continuation. [LangGraph persistence](https://docs.langchain.com/oss/python/langgraph/persistence)

assistant-ui offers both custom transports and a first-party AG-UI runtime. Its AG-UI interrupt support is currently documented as experimental, while the LangChain/LangGraph adapters expose native interrupt behavior through the licensed Agent Server path. [assistant-ui AG-UI runtime options](https://www.assistant-ui.com/docs/runtimes/ag-ui/runtime-options), [assistant-ui custom Assistant Transport](https://www.assistant-ui.com/docs/runtimes/custom/assistant-transport)

LangChain documents its standalone Agent Server as a lightweight self-hosted deployment, but its current prerequisites include PostgreSQL, Redis, `LANGSMITH_API_KEY`, `LANGGRAPH_CLOUD_LICENSE_KEY`, and egress for one-time licence verification. It is therefore not equivalent to packaging only the MIT-licensed LangGraph library. [LangChain standalone Agent Server deployment](https://docs.langchain.com/langsmith/deploy-standalone-server), [LangGraph MIT licence](https://github.com/langchain-ai/langgraph/blob/main/LICENSE)

assistant-ui explicitly documents `AssistantTransport` for open-source LangGraph. The Python `assistant-stream` package accepts commands, streams state snapshots, propagates cancellation, and includes a LangGraph event bridge and reference backend. [assistant-ui Assistant Transport](https://www.assistant-ui.com/docs/runtimes/custom/assistant-transport)

The AG-UI LangGraph Python integration provides a FastAPI endpoint helper around a compiled LangGraph graph and covers streamed text, tool calls, state snapshots, and interrupt translation. Because a Deep Agent is a compiled LangGraph graph, this is a framework-level compatibility path rather than a Deep Agents-specific protocol implementation. [AG-UI LangGraph Python integration](https://github.com/ag-ui-protocol/ag-ui/blob/main/integrations/langgraph/python/README.md)

assistant-ui's AG-UI runtime parses AG-UI text, reasoning, tool, state, subagent, cancellation, and run events. Its current documentation labels interrupt handling and the thread-list adapter experimental. [assistant-ui AG-UI runtime options](https://www.assistant-ui.com/docs/runtimes/ag-ui/runtime-options)

## Decision matrix

| Option | Advantages | Costs and risks | Decision |
| --- | --- | --- | --- |
| `@assistant-ui/react-langchain` + standalone Agent Server | Official current template; native Threads, checkpoints, tools, interrupts, subagents, cancellation | Requires the separately licensed Agent Server and its PostgreSQL/Redis deployment contract | Adopt only if that product dependency is accepted |
| `@assistant-ui/react-langgraph` + standalone Agent Server | Mature direct SDK integration; broad native feature coverage | Same Agent Server product dependency; more adapter-owned plumbing | Fallback within the licensed path |
| `AssistantTransport` + Agent Hub Python backend | Documented open-source LangGraph path; keeps one backend container and Agent Hub-owned persistence | Agent Hub implements a framework-specific command/state-stream adapter | Viable fallback |
| AG-UI + `ag-ui-langgraph` + assistant-ui AG-UI runtime | Open protocol; existing adapters on both sides; replaceable frontend and backend | Interrupt and assistant-ui thread-list support currently experimental; versions require contract tests | Adopt |

## Boundary design

```text
assistant-ui components
        |
@assistant-ui/react-ag-ui
        |
same-origin Next.js proxy
        |
AG-UI FastAPI endpoint (`ag-ui-langgraph`)
        |
Deep Agent graph + PostgreSQL checkpointer
```

The agent-transport Module owns mapping the selected Agent Hub Thread to LangGraph's `thread_id`, applying authenticated Project/Run context, configuring the AG-UI LangGraph adapter, handling interrupt responses, and propagating cancellation. It must not accept client-supplied identity as authority or leak provider keys to the browser.

Agent Hub's ordinary application API separately owns:

- Project and Thread lists and titles;
- Agent Run display metadata;
- artifacts, sources, and project VFS discovery;
- plugin selection and configuration;
- authentication and authorization.

This separation prevents LangGraph runtime records from becoming the whole product domain while retaining the supported streaming implementation.

## Required behavior for the walking skeleton

- A browser can create/select an Agent Hub Thread and bind it to the same LangGraph `thread_id`.
- Text and tool calls stream through the official adapter.
- A Deep Agents interrupt renders an approval/input state and resumes the same checkpoint.
- User cancellation reaches the running graph; the final Agent Run status is reconciled server-side.
- Reloading or switching Threads hydrates from persisted graph state and Agent Hub Thread metadata.
- A dropped browser stream does not define run failure. Reconnection reads durable Thread/run state.
- Version-pinned contract tests cover message conversion, tool result display, one interrupt/resume, cancellation, and reload.

## Version and stability guardrail

Pin compatible versions of assistant-ui, the AG-UI client/core/LangGraph adapter, LangGraph, LangChain, and Deep Agents. Keep adapter configuration in one deep Module and add compatibility tests before dependency upgrades.

## Decision

Adopt **AG-UI over HTTP between the self-hosted Python/LangGraph backend and assistant-ui**. Keep Project and Thread lists in Agent Hub rather than relying on the currently experimental AG-UI thread-list adapter, and make interrupt/resume a walking-skeleton acceptance test.

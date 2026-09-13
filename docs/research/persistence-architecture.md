# Persistence architecture for the Agent Hub foundation

Research date: 2026-09-12

## Conclusion

Use one managed PostgreSQL service as the initial durable persistence boundary, while keeping three logical ownership areas distinct:

1. Agent Hub application tables own Users, Projects, Threads, Agent Runs, artifact metadata, artifact documents, plugin configuration references, and the project file catalog.
2. LangGraph's PostgreSQL checkpointer owns resumable runtime state and checkpoint history for each Thread.
3. A project-namespaced Deep Agents backend projects Agent Hub's PostgreSQL-backed file records as the agent's shared Virtual Filesystem.

Do not introduce object storage until a real payload exceeds the practical database/document limits. When that happens, keep metadata, authorization, hashes, and provenance in PostgreSQL and put only large immutable bytes in object storage.

## Primary-source findings

LangGraph checkpointers save graph state at graph-step boundaries, organize checkpoints by `thread_id`, and enable interrupt/resume, memory, time-travel debugging, and fault recovery. LangGraph documents `AsyncPostgresSaver` as the production-oriented asynchronous PostgreSQL implementation. [LangGraph persistence](https://docs.langchain.com/oss/python/langgraph/persistence)

LangGraph's Store is separate from checkpointed Thread state and is intended for information shared across Threads. The namespace is an arbitrary tuple, and the production implementations listed by LangGraph include PostgreSQL, Redis, and MongoDB. [LangGraph persistence: memory store](https://docs.langchain.com/oss/python/langgraph/persistence#memory-store)

Deep Agents defaults to `StateBackend`, whose files live in the state of one Thread and persist across turns through checkpoints. `StoreBackend` provides cross-Thread storage. `CompositeBackend` can route path prefixes to different backends, and a custom `BackendProtocol` implementation can project PostgreSQL or another remote store as a virtual filesystem. [Deep Agents backends](https://docs.langchain.com/oss/python/deepagents/backends)

The Deep Agents documentation specifically says externally persisted custom backends should perform writes in their own store and omit in-state file updates. This permits Agent Hub to present database records through the standard file tools without exposing a host filesystem. [Deep Agents virtual filesystem guidance](https://docs.langchain.com/oss/python/deepagents/backends#use-a-virtual-filesystem)

## Recommended ownership model

| Data | Authority | Initial storage |
| --- | --- | --- |
| User and authentication subject | Agent Hub | PostgreSQL application tables |
| Project and membership/ownership | Agent Hub | PostgreSQL application tables |
| Thread identity and display metadata | Agent Hub | PostgreSQL application tables |
| Thread runtime state and checkpoint history | LangGraph checkpointer | PostgreSQL checkpointer tables |
| Agent Run lifecycle and user-visible status | Agent Hub | PostgreSQL application tables |
| Project Virtual Filesystem paths and documents | Agent Hub VFS adapter | PostgreSQL application tables |
| Artifact envelope, current document, and provenance | Agent Hub artifact service | PostgreSQL application tables |
| Plugin catalog selection and non-secret configuration | Agent Hub | PostgreSQL application tables |
| Plugin/provider secrets | Agent Hub secret boundary | Encrypted secret store or encrypted PostgreSQL fields initially |
| Large immutable binary content | Agent Hub artifact service | Deferred object storage plus PostgreSQL reference/hash |

The separation above is logical, not a recommendation for three database servers. One PostgreSQL service and one migration/deployment boundary are sufficient initially.

## Virtual Filesystem decision

Use a small Agent Hub implementation of Deep Agents' `BackendProtocol`, scoped from trusted request context to one `project_id`. The model sees absolute virtual paths, but the adapter maps them to rows keyed by Project and normalized path. It must never accept a model-supplied Project identifier as authority.

The project namespace is shared across Threads. Thread-local scratch files may continue to use `StateBackend` if Deep Agents needs them, with `CompositeBackend` routing durable project paths to the Agent Hub backend. A simple initial convention is:

- `/project/**`: durable, project-shared Agent Hub VFS;
- `/scratch/**`: Thread-local checkpointed state;
- artifact documents: durable files under a reserved project path, mutated only through the Artifact Host Adapter and plugin semantic tools.

The exact reserved path names are an implementation detail. The architectural requirement is that authorization and persistence are attached to project context outside model-controlled arguments.

## Transactions and consistency

Treat the Agent Hub application tables as authoritative for product state and the LangGraph checkpointer as authoritative for runtime continuation. Do not pretend that an Agent Run and every checkpoint form one cross-library ACID transaction.

Use these boundaries:

1. Create the Agent Run record before invoking the graph.
2. Give the invocation the existing Agent Hub Thread ID as LangGraph's `thread_id`.
3. Let the checkpointer persist runtime progress independently.
4. Apply each artifact or VFS mutation in one Agent Hub database transaction that includes the current document, file metadata, provenance, and a compact project-change record.
5. Update the Agent Run to a terminal or interrupted state idempotently after the runtime reports its outcome.
6. On recovery, reconcile non-terminal Agent Runs against the latest LangGraph checkpoint rather than guessing from streamed browser events.

An outbox can be added when Agent Hub introduces external event delivery. It is not required merely to stream a currently running HTTP response.

## Concurrency

Keep the current decision not to build custom multi-Thread merge machinery. Store a monotonically increasing file/document version or update token so plugin-mediated writes can reject a clearly stale replacement. If the initial Deep Agents adapter cannot supply an expected version, last completed write wins and the limitation is recorded. Rich diff, merge, and artifact revision browsing remain later work.

## Backup, deletion, and recovery

- Back up the PostgreSQL service as one recovery unit, while testing restoration of both application and LangGraph-owned tables.
- Deleting a Project must explicitly delete or tombstone its application rows, project VFS namespace, relevant Thread checkpoints, and secret references. Do not rely only on relational cascades across library-owned tables.
- Retain stable Agent Hub identifiers independently of storage keys so a backend can change later.
- If object storage is added, write the blob first, then commit its database reference; garbage-collect unreferenced blobs asynchronously.
- Do not use LangGraph checkpoints as artifact revision history. They are runtime snapshots and have different retention and deletion semantics.

## Why not the alternatives initially

- `StateBackend` alone is Thread-scoped and cannot provide the required project-shared VFS.
- A host filesystem conflicts with the hosted product boundary and creates isolation risk.
- A separate document database adds another operational and recovery boundary before the artifact shapes justify it.
- Object storage for every small JSON or Markdown document complicates transactions and querying without solving an observed size problem.
- Plugin-owned databases fragment project lifecycle, authorization, discovery, and provenance.

## Decision

Adopt **PostgreSQL-first, logically separated ownership, with a project-scoped custom Deep Agents VFS backend**. Keep LangGraph's supported PostgreSQL checkpointer rather than reimplementing runtime persistence. Defer object storage until binary or oversized artifacts create a concrete need.

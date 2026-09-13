# Foundation acceptance contract

The foundation is complete when one deployed vertical slice demonstrates the following behavior without any production engineering-domain plugin.

## Required demonstration

1. The platform-authenticated user can create a Project and start two Threads within it.
2. Each Thread maps to one persisted LangGraph thread and can execute multiple Deep Agent Runs.
3. Text, tool calls, results, errors, cancellation, and one interrupt/approval round-trip render through assistant-ui and survive a page reload where applicable.
4. The agent can use a project-scoped Virtual Filesystem that is shared between the two Threads but never exposes the server or user's computer filesystem.
5. A trivial curated MCP server exposes at least one ordinary tool and one MCP App UI.
6. The trivial Plugin can create, validate, semantically edit, and render one portable Artifact Document.
7. Agent Hub persists that Artifact in the Project, records its creating/changing Thread and Agent Run, and can reopen it after reload.
8. The second Thread can discover the Artifact without its full content being injected into the static system prompt, inspect it on demand, and perform a plugin-mediated edit.
9. The first Thread receives a compact later-run notice that the Artifact changed and can reload the current document.
10. The same trivial Plugin remains usable in a standard MCP client without Agent Hub persistence: its tool accepts the inline document and returns a complete replacement plus useful text.
11. A rejected stale edit, malformed plugin result, unauthorized Project lookup, interrupted Run, and unavailable MCP server each produce an explicit recoverable or terminal outcome rather than silent corruption.
12. Contract, integration, and end-to-end tests exercise the preceding seams with deterministic test doubles where model quality is irrelevant.

## Non-goals

- A calculation engine, unit system, diagram editor, structural design method, or engineering assurance claim.
- Arbitrary user-supplied MCP servers.
- Team workspaces, collaboration, or multi-user Project sharing.
- A user-facing Artifact revision browser or custom merge system.
- Live cross-Thread Artifact synchronization.
- Multiple model providers beyond preserving a replaceable provider seam.
- General code execution or access to a host filesystem.

# MCP App portability review

Research date: 2026-09-11

## Conclusion

An Agent Hub artifact plugin can remain useful outside Agent Hub if its portable MCP interface is complete on its own. The plugin should accept an inline serialized Artifact document, perform domain operations without provider-owned persistence, return a complete updated document plus concise text, and attach a standards-compatible MCP App UI. Agent Hub should add project lookup, reference resolution, automatic persistence, provenance, placement, and refresh entirely at the host seam.

Removing the Agent Hub host enhancements should therefore reduce convenience, not remove the plugin's calculation, validation, editing, or rendering capabilities.

## Conformance levels

| Capability | MCP-only client | Standard MCP Apps host | OpenAI-compatible host | Agent Hub |
| --- | --- | --- | --- | --- |
| Discover and call domain tools | Yes | Yes | Yes, when the server is connected | Yes |
| Receive concise textual results | Yes | Yes | Yes | Yes |
| Receive structured tool results | Yes, subject to client presentation | Yes | Yes | Yes |
| Render the interactive UI | No | Yes | Yes when compatible UI metadata/resources are exposed | Yes through assistant-ui |
| Validate or transform an inline Artifact document | Yes | Yes | Yes | Yes |
| Persist an Artifact automatically into a Project | No portable guarantee | No portable guarantee | Host-specific | Yes |
| Open by Agent Hub Artifact ID | No | No | No | Yes; the host resolves it before calling the portable tool |
| Project-wide discovery and provenance | No portable guarantee | No portable guarantee | Host-specific | Yes |
| Live updates from Agent Hub's Virtual Filesystem | No | Not part of stable MCP Apps | Host-specific | Agent Hub enhancement; deferred initially |

The MCP Apps specification connects a tool to a `ui://` resource, delivers tool input/results to a sandboxed View, and allows the View to call same-server tools and read resources. It does not define project artifacts or host-owned durable storage. [MCP Apps specification](https://github.com/modelcontextprotocol/ext-apps/blob/main/specification/2026-01-26/apps.mdx)

Core MCP clients can still use the server's tools when they do not implement the optional app UI. Tool results support model-visible `content` and schema-backed `structuredContent`, so the tool must remain useful without its View. [MCP tools specification](https://modelcontextprotocol.io/specification/2025-06-18/server/tools)

assistant-ui provides an MCP Apps renderer and host bridge but does not add portable persistence semantics. Its documented OpenAI compatibility path also notes that OpenAI UI metadata/resource conventions may need bridging to the standard MCP Apps pointer and MIME convention. [assistant-ui MCP Apps documentation](https://www.assistant-ui.com/docs/tools/mcp-apps)

Official OpenAI documentation describes plugins as packages that may include skills, MCP servers, and optional UI. Availability varies by client surface, so tool-only fallback remains necessary even inside the OpenAI ecosystem. [OpenAI plugin architecture](https://developers.openai.com/plugins/concepts/plugins), [OpenAI Plugins documentation](https://learn.chatgpt.com/docs/plugins)

## Portable plugin interface

The provider MCP server should remain stateless with respect to user Artifacts. Its ordinary MCP tools should:

1. Accept a complete inline Artifact document or a bounded domain projection of it.
2. Validate the input against a declared schema.
3. Perform a semantic operation such as create, calculate, check, or apply edit.
4. Return concise model-readable `content`.
5. Return the complete canonical replacement document in `structuredContent` when state changed.
6. Attach an MCP App UI resource when visual interaction is useful.
7. Produce useful results when the caller ignores the UI metadata.

The provider should not require an `agenthub://` URI, Agent Hub token, Project ID, or Agent Hub storage method in its portable tool interface.

## Agent Hub host enhancements

Agent Hub adds behaviour around the portable call without changing the provider's semantics:

1. Resolve an Agent Hub Artifact ID to the current inline document before invoking the provider tool.
2. Authorize the Project and Artifact operation.
3. Persist a successful replacement document into the project Virtual Filesystem.
4. Record Thread and Agent Run provenance.
5. Maintain compact project discovery metadata.
6. Place the View in the right-hand Artifact workspace.
7. Append compact project-change context to later Agent Runs.
8. Refresh a View when focused or reopened; richer live synchronization can be added later.

These enhancements belong in an Artifact Host Adapter at the host seam. They are not requirements imposed on the portable MCP server.

## Behaviour outside Agent Hub

### In a standard MCP Apps host

The user or agent supplies the current serialized Artifact document to the plugin tool. The tool validates or updates it and the View renders the result. An edit returns a replacement document. Unless that host has its own artifact persistence mechanism, saving is explicit: the agent or user stores the returned document using facilities provided by that client.

The loss relative to Agent Hub is automatic Project storage, Artifact-ID lookup, provenance, project discovery, and refresh. The actual domain behaviour and UI remain available.

### In an MCP-only client

The same tools work, including plugin validation and calculation. The client displays or reasons over the text/structured result but does not mount the app UI. The returned document can still be saved as JSON by an agent with file or storage tools.

### In an OpenAI-compatible host

The tools and their textual/structured results remain the compatibility floor. Interactive rendering depends on exposing the UI metadata/resource convention supported by that host. A distributable plugin can generate both the standard MCP Apps metadata/resource and the OpenAI compatibility variant from the same UI build, then verify both in conformance tests. Neither variant should change the domain tool contract.

## Expected graceful degradation

| Agent Hub feature absent | Fallback |
| --- | --- |
| Automatic Project persistence | Return the complete updated document for explicit saving |
| Artifact ID resolution | Accept the inline document directly |
| Project Artifact catalog | Use the other client's files/resources/history or ask the user for the document |
| Host-side provenance | Preserve any provenance already present in the portable document; do not fabricate it |
| Automatic View refresh | Refresh/reopen manually or invoke the render tool again |
| MCP Apps UI support | Present concise text and structured results through the tool call |
| Right-hand Artifact panel | Render wherever the host places tool UI |

## Compatibility rules

- UI must remain optional for correctness.
- Validation must live in provider tools, not only in the Agent Hub adapter or model prompt.
- Every state-changing result must contain a complete portable replacement document; patches may be included as an optimization but must not be the only recoverable output initially.
- The Artifact envelope and provider payload must be versioned independently.
- Unknown envelope fields must be preserved when possible.
- Model-visible `content` must stay concise; large state belongs in structured results or resources.
- Binary data should be represented by resource/blob references rather than base64 embedded in the JSON Artifact document.
- Agent Hub-specific metadata must be optional and namespaced.
- The same provider conformance suite should run in tool-only, standard MCP Apps, OpenAI-compatible, and Agent Hub-enhanced modes.

## Recommendation

Adopt **standard MCP server + standard MCP App + transparent Agent Hub host adapter**. Do not create an Agent Hub-only plugin protocol. Agent Hub's value is the richer host behaviour around portable tools: automatic project persistence, discovery, provenance, and workspace UX.

# Binding MCP Apps to Agent Hub's virtual filesystem

Research date: 2026-09-11

This note tests one proposed model: Agent Hub owns serialized artifact documents in a project-scoped virtual filesystem; MCP servers remain stateless; MCP App Views render and edit those documents. Sources are limited to the MCP/MCP Apps specifications and assistant-ui's official documentation and source.

## Conclusion

The model is workable, with one important qualification: **it is not supplied end-to-end by the portable MCP Apps protocol**.

Agent Hub can make a serialized virtual file the canonical artifact. A stateless MCP tool can validate or transform that document and return it as structured data for its View. However, the stable MCP Apps protocol gives the View access to tools and resources associated with its MCP server, not a general host-owned data store, and it defines no generic “save this host artifact” operation or artifact-change subscription.

Therefore Agent Hub needs a small, explicit **Artifact Host Adapter** at its MCP Apps boundary. The adapter authorizes project paths, loads current files, persists validated edits, and tells mounted Views when their document changed. The underlying plugin server may remain stateless. The View should retain a portable fallback that loads data from its invoking tool result and submits edits through MCP tools, but automatic VFS persistence and live synchronization will be an Agent Hub host capability.

Use ordinary UTF-8 JSON for structured artifacts. Do not base64-encode JSON; reserve base64 for genuinely binary resource content.

## Facts established by the specifications and implementation

### 1. What a View can read

- Stable MCP Apps (2026-01-26) allows a View to send `resources/read`, and describes `tools/call` as executing a tool “on the MCP server.” The host acts as an MCP server/proxy for the View. The UI template named by a tool must exist on that server, and app-visible tools are scoped to the same server connection. [Stable MCP Apps specification](https://github.com/modelcontextprotocol/ext-apps/blob/main/specification/2026-01-26/apps.mdx#standard-mcp-messages)
- Core MCP defines `resources/read` as a client request to a server. A resource URI may use any scheme, but the receiving server decides how to interpret it. This URI flexibility does not make resources host-global. [MCP resources specification](https://modelcontextprotocol.io/specification/2025-06-18/server/resources)
- assistant-ui's default remote host routes `resources/read`, `resources/list`, `tools/call`, and UI-template loading to the MCP client selected by the tool part's `serverId`. Its documented custom-host interface allows an application to replace `readResource` and the other data-plane operations. [assistant-ui MCP Apps documentation](https://www.assistant-ui.com/docs/tools/mcp-apps)

**Result:** a conforming View can read resources exposed by its associated server. It cannot assume access to arbitrary resources owned by Agent Hub or another server. Agent Hub *can* deliberately make VFS reads available through a custom assistant-ui host/gateway, but that routing is an Agent Hub extension and must enforce project authorization; it is not a portable assumption for the View.

### 2. Resource subscriptions and host-pushed changes

- Core MCP supports optional resource subscriptions: a client sends `resources/subscribe`, then a supporting server can send `notifications/resources/updated`. [MCP resources specification](https://modelcontextprotocol.io/specification/2025-06-18/server/resources#subscriptions)
- Stable MCP Apps exposes only `resources/read` from that resource feature set to Views; it does not include `resources/subscribe`, `resources/unsubscribe`, or `notifications/resources/updated` in the View/Host message subset. [Stable MCP Apps specification](https://github.com/modelcontextprotocol/ext-apps/blob/main/specification/2026-01-26/apps.mdx#standard-mcp-messages)
- The open first-party proposal to add View resource subscriptions explicitly describes their absence from the stable MCP Apps version and identifies polling as the present fallback. It is a proposal, not current portable behaviour. [MCP Apps issue #659](https://github.com/modelcontextprotocol/ext-apps/issues/659)
- assistant-ui currently documents three host-to-View data notifications: tool input changes, tool result arrival, and host-context changes. It does not document a generic arbitrary-data-change notification or View resource subscription. [assistant-ui bridge protocol](https://www.assistant-ui.com/docs/tools/mcp-apps#host--widget-notifications)

**Result:** Views cannot portably listen to a host-owned virtual file today. Polling through an available read path, updating the invoking tool result, remounting, or an Agent Hub-specific bridge extension are the available design families.

### 3. assistant-ui refresh and remount behaviour

- assistant-ui loads a UI resource again when its `resourceUri` or `serverId` changes. The sandbox frame's content key is the server identity plus resource URI. Changing the HTML behind an unchanged URI is therefore not, by itself, a documented refresh signal. [assistant-ui `McpAppRenderer` source](https://github.com/assistant-ui/assistant-ui/blob/main/packages/react/src/mcp-apps/McpAppRenderer.tsx), [assistant-ui `McpAppFrame` source](https://github.com/assistant-ui/assistant-ui/blob/main/packages/react/src/mcp-apps/app-frame.tsx)
- The current frame implementation sends another tool-result notification when its `output` prop changes identity, without keying the iframe on that output. It likewise sends host-context change notifications when host context changes. [assistant-ui `McpAppFrame` source](https://github.com/assistant-ui/assistant-ui/blob/main/packages/react/src/mcp-apps/app-frame.tsx)
- assistant-ui documents re-emitting an AG-UI `ACTIVITY_SNAPSHOT` after message restoration to rehydrate a widget for an existing tool-call ID. It does not document an API that binds an arbitrary VFS change stream to a completed tool part or guarantees that repeated activity snapshots are a supported live-update mechanism. [assistant-ui AG-UI integration](https://www.assistant-ui.com/docs/tools/mcp-apps#ag-ui-integration)

**Verified capability:** if Agent Hub can legitimately update the rendered part's `result`, the mounted View receives the new result without a remount. A changed resource URI/server identity causes resource reload/frame replacement.

**Unresolved:** the clean supported mechanism for mutating a completed assistant-ui/AG-UI tool part in response to an external project-VFS event has not been verified. Treat live updates from another thread as a prototype question, not a foundation guarantee. Poll-on-focus/manual refresh is the safe initial behaviour.

### 4. Tool arguments and results as the portable data path

- MCP tool arguments are JSON objects validated by the tool's JSON Schema. A `CallToolResult` can contain model-visible `content`, UI-oriented `structuredContent`, and `_meta`; MCP Apps delivers the invocation arguments and result to the View. [MCP tools specification](https://modelcontextprotocol.io/specification/2025-06-18/server/tools), [stable MCP Apps data passing](https://github.com/modelcontextprotocol/ext-apps/blob/main/specification/2026-01-26/apps.mdx#data-passing)
- MCP Apps recommends `content` as the concise model/text fallback, `structuredContent` for UI data, and `_meta` for data not intended for model context. assistant-ui preserves that split: its AG-UI history sends saved model-visible text in later requests and does not include `structuredContent` or `_meta`. [MCP Apps specification](https://github.com/modelcontextprotocol/ext-apps/blob/main/specification/2026-01-26/apps.mdx#data-passing), [assistant-ui AG-UI integration](https://www.assistant-ui.com/docs/tools/mcp-apps#ag-ui-integration)
- Neither stable MCP nor MCP Apps specifies a universal byte limit for a tool call/result. Core resource metadata includes an optional raw byte size so hosts can estimate context usage. The MCP Apps draft recommends a 10 MB app-tool result limit, but this is guidance in a draft, not a portable guaranteed allowance. [MCP schema reference](https://modelcontextprotocol.io/specification/2025-06-18/schema), [draft MCP Apps security guidance](https://github.com/modelcontextprotocol/ext-apps/blob/main/specification/draft/apps.mdx#security-considerations)
- MCP resource content represents text as UTF-8 strings and binary content as base64. Base64 increases payload size by roughly one third before JSON framing and provides no benefit for JSON documents. [MCP resources specification](https://modelcontextprotocol.io/specification/2025-06-18/server/resources#resource-contents)

## Portable interaction patterns

### Load an existing artifact

The most portable initial flow is:

1. Agent Hub reads the canonical JSON file from the project VFS after checking project/path access.
2. Agent Hub invokes the plugin's `open` or `render` tool with the document, or with a bounded domain projection of it.
3. The stateless server validates/normalizes it and returns a concise text summary in `content` plus the render model in `structuredContent`; the result points to the plugin's reusable `ui://` template.
4. The View renders from the delivered tool result.

This works in standard MCP Apps hosts because the document travels through the normal tool-call contract. It does mean the plugin server receives the artifact contents, and putting the whole artifact in model-generated tool arguments may also place it in model context. Agent Hub should perform host-side invocation or use opaque, authorized fetch capability only when avoiding model exposure is important.

### Save edits without provider-owned persistence

There is no portable View-to-host artifact-save method. Three patterns are possible:

1. **Agent-mediated portable fallback:** the View uses `ui/message` to ask the agent to apply an edit through Agent Hub's filesystem tools. This is portable but indirect, potentially exposes the payload to the model, and is unsuitable for frequent autosave.
2. **Agent Hub Artifact Host Adapter (recommended):** the View calls an app-visible semantic tool such as `validate_update`; the stateless provider returns a canonical updated document or patch. Agent Hub's custom MCP route/gateway recognizes the successful mutation, performs authorization and VFS persistence, and returns the saved version/hash. This keeps storage in Agent Hub, but the commit hook is host-specific.
3. **Provider calls an Agent Hub storage API:** the provider's `save` tool writes through a scoped Agent Hub API. The provider remains stateless, but now requires Agent Hub credentials/API coupling and sees the full document. This is useful for remotely hosted third-party plugins only if Agent Hub deliberately publishes such an integration contract.

Pattern 2 is the best foundation fit. Define the plugin-facing operation semantically (validate/apply edit), not as unrestricted filesystem access. Keep a manual “Save” and reload-on-conflict path initially; autosave and cross-thread live synchronization can follow after the assistant-ui update mechanism is proven.

## Recommended artifact document contract

Store one canonical UTF-8 JSON document per artifact, with a small envelope such as:

```json
{
  "schemaVersion": "1",
  "artifactType": "calculation",
  "renderer": "calculation-app",
  "title": "Beam check",
  "data": {},
  "provenance": {}
}
```

The exact fields remain an Agent Hub decision, but versioning and renderer/type discrimination should be inside the serialized document so the file is self-describing. Keep binary attachments as separate VFS blobs referenced by path/hash rather than embedding large base64 strings in the JSON.

## Size and security constraints for the foundation

- Put only a short human/model summary in `content`; put render data in `structuredContent` or load it through the authorized adapter. Avoid duplicating the same full document in arguments, result content, structured content, message history, and VFS.
- Impose Agent Hub limits even though MCP has no universal maximum: maximum artifact bytes, tool-argument/result bytes, nesting depth, collection lengths, and execution time. Reject before parsing/rendering where possible.
- Validate against a versioned JSON Schema on every load and save. Treat plugin-returned JSON as untrusted, including titles, paths, links, and HTML-adjacent strings.
- Never accept a project/path solely because the View supplied it. Derive project identity from the authenticated host session and map an opaque artifact ID to an authorized VFS path server-side.
- Use expected content hashes/version tokens for interactive save conflicts when practical, even if general concurrent filesystem conflict hardening is deferred.
- The sandbox limits DOM access, not data disclosure. Any artifact sent to a remote MCP server is disclosed to that provider. Plugin permissions should therefore state which artifact types/content the server can read and which paths it may mutate.
- Enforce the UI resource CSP and the assistant-ui route boundary: authenticate every bridge request, allowlist tools, rate-limit calls, validate `serverId`, and do not let resource URIs become SSRF or path-traversal inputs. [Stable MCP Apps security model](https://github.com/modelcontextprotocol/ext-apps/blob/main/specification/2026-01-26/apps.mdx#security-considerations), [assistant-ui security notes](https://www.assistant-ui.com/docs/tools/mcp-apps#security-notes)

## Decision supported by this research

Adopt **VFS-owned, serialized artifacts** for the foundation, with these explicit boundaries:

- Agent Hub is the sole durable owner.
- The MCP server owns schemas, validation, calculations, transformations, and the reusable UI template, but no artifact database.
- Agent Hub's Artifact Host Adapter bridges validated semantic edits to VFS reads/writes.
- Initial refresh is manual/on-focus or follows an in-thread tool result. Cross-thread push updates remain a documented unresolved integration to prototype.
- The adapter is an Agent Hub extension; plugin Views must not assume that arbitrary host resources or save operations exist in every MCP Apps host.

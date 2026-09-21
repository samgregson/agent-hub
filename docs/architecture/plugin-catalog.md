# Curated Plugin Catalog lifecycle

## Decision

The first Plugin Catalog is a deployment-controlled registry of reviewed Plugin manifests. Users can enable listed Plugins per Project; they cannot enter arbitrary MCP server endpoints.

Catalog definitions are version-controlled with the application initially. Project selections and non-secret configuration are persisted by Agent Hub. Secrets remain in the platform/backend secret boundary and are referenced rather than copied into manifests, model context, browser state, or Artifact Documents.

## Minimum manifest boundary

A catalog entry identifies:

- stable Plugin ID, display name, description, owner, and Plugin version;
- MCP server transport and deployment-controlled endpoint identity;
- supported MCP protocol and optional MCP Apps extension versions;
- tools/resources made available and their risk/approval policy;
- Artifact types and schema versions produced, accepted, or rendered;
- requested outbound/UI resource origins and other capabilities;
- configuration schema and secret-reference slots;
- optional Agent Hub enhancements, clearly separated from portable requirements;
- review status and compatibility constraints.

The exact serialization format is an implementation choice. The manifest is configuration and policy input, not executable Plugin code.

## Tool Result Snapshots

Every successful reviewed MCP tool call with JSON `structuredContent` becomes an Artifact. Agent Hub records the invocation input and structured output as the Plugin-owned Tool Result Snapshot payload and derives its Artifact type from the reviewed Plugin and tool identity. It never calls unrelated tools to assemble a snapshot: a credits or lookup call is independently represented only when it itself returns structured content. Tool errors and transient MCP App UI state are not Artifacts. This is a host persistence policy; it adds no Agent Hub-specific inputs, storage, or callbacks to the portable MCP tool contract.

## Reference Plugin deployment

The reference Plugin server implementation is Python/FastMCP, deployed as an
independent Streamable HTTP service. It may package an optional React/Vite MCP
App as a standard `ui://` resource. This is a developer default rather than a
gateway requirement: the catalog and gateway consume reviewed, standards-
compatible MCP endpoints and do not expose FastMCP-specific behaviour.

## Lifecycle

1. A developer adds or updates a reviewed catalog entry.
2. Deployment validates manifest uniqueness, versions, endpoint policy, and schemas.
3. A user enables an available version for a Project and supplies permitted configuration.
4. Agent Runs see only tools from Plugins enabled for that Project and allowed by policy.
5. Updating a Plugin is explicit. New origins, tools, or permissions require renewed review and must not silently expand an existing grant.
6. Disabling a Plugin prevents new calls but does not delete its existing portable Artifact Documents.
7. Removing a catalog version is separate from deleting user data; existing Artifacts remain exportable and inspectable through generic fallback where possible.

## Portability rule

An Agent Hub enhancement may improve lookup, persistence, provenance, placement, or refresh, but a Plugin's ordinary MCP tools and optional standard MCP App must remain useful without it. Agent Hub IDs, tokens, storage APIs, and proprietary URI schemes cannot be mandatory inputs to the portable tool contract.

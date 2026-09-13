# MCP execution and MCP App security boundaries

Research date: 2026-09-12

## Conclusion

Treat every MCP server, tool description, tool result, resource, and MCP App as untrusted even when it appears in Agent Hub's curated catalog. Curation controls admission and expected configuration; it does not replace runtime authorization, network isolation, output validation, iframe isolation, quotas, or audit trails.

The foundation needs one server-side MCP gateway and one browser-side sandbox host. Plugins receive the least capability required for a call, never Agent Hub database or model-provider credentials.

## Normative and primary-source findings

MCP authorization for HTTP transports is based on OAuth. Current requirements include protected-resource discovery, authorization-server discovery, PKCE, secure token storage, HTTPS, resource/audience binding, and rejection of tokens not intended for the MCP server. The specification forbids passing the MCP client's token through to an upstream API; an MCP server must obtain and use a separate upstream token. [MCP authorization](https://modelcontextprotocol.io/specification/draft/basic/authorization), [MCP authorization security considerations](https://modelcontextprotocol.io/specification/2025-06-18/basic/authorization#security-considerations)

MCP Apps execute UI resources in sandboxed iframes and communicate with the host through an auditable bridge. Network and asset access are declared through UI CSP metadata; applications declare connection and resource domains, and stable origins/CORS remain host-specific. [MCP Apps overview](https://apps.extensions.modelcontextprotocol.io/api/documents/overview.html), [MCP Apps CSP and CORS](https://apps.extensions.modelcontextprotocol.io/api/documents/csp-and-cors.html)

MCP Apps can use per-server or per-tool OAuth authorization. Authorization proves the caller's delegated access to the MCP server; it does not decide whether Agent Hub should expose or execute a particular tool in a particular Project or Agent Run. [MCP Apps authorization](https://apps.extensions.modelcontextprotocol.io/api/documents/authorization.html)

MCP App support is optional: a client without the UI extension can still call the underlying MCP tool. Security-critical validation must therefore live in the server tool, not only in the iframe. [MCP Apps overview](https://apps.extensions.modelcontextprotocol.io/api/documents/overview.html)

## Trust boundaries

```text
Browser
  trusted Agent Hub shell
  └─ sandboxed, untrusted MCP App iframe
          | narrow host bridge
          v
Agent Hub API / MCP gateway
  authentication + Project authorization
  tool policy + approval + validation
  secrets + OAuth token vault
  outbound network policy
          |
          v
untrusted remote MCP server
  └─ separate upstream service credentials
```

The language model is also not an authorization authority. A model request to call a tool is a proposal evaluated by Agent Hub policy.

## Minimum foundation controls

### Catalog and connection

- Catalog entries pin the MCP server identity, allowed HTTPS endpoint origins, supported protocol/UI versions, requested capabilities, owner, and reviewed version.
- Enabling a plugin is Project configuration; establishing user OAuth consent is a separate state.
- Plugin updates that add origins, tools, or material permissions require review before the catalog version becomes available.
- Arbitrary endpoints, redirects to unapproved origins, loopback, link-local, private-network, and cloud-metadata destinations are denied by default.
- Resolve DNS through an SSRF-aware outbound client and re-check the destination after redirects and connection resolution.

### Credentials and OAuth

- Keep model-provider keys, Agent Hub session credentials, OAuth client secrets, and refresh tokens server-side and encrypted at rest.
- Scope stored grants by user, plugin/server, authorization server, and resource/audience.
- Use PKCE and state validation; rotate or revoke tokens when a plugin is disconnected.
- Never send bearer tokens in URLs, logs, model context, tool arguments, tool results, or MCP App messages.
- Never pass an MCP access token through to the plugin's upstream API.

### Tool execution

- Build the tool allowlist from the enabled catalog entry and authenticated Project context, not solely from server-provided discovery metadata.
- Treat server tool annotations and descriptions as hints, not enforceable safety declarations.
- Apply per-tool risk policy. Read-only low-risk calls may execute automatically; writes, external communication, credential use, or consequential engineering actions can require explicit approval.
- Validate tool arguments before dispatch and validate structured results against the declared schema before artifact persistence.
- Bound connection, execution, idle-stream, and total time; cap concurrency, retries, response bytes, resource bytes, and tool-call depth.
- Make retries conditional on known idempotency. Do not blindly retry state-changing tools.
- Record caller, Project, Thread, Agent Run, server/catalog version, tool, approval, timing, result status, and artifact provenance while redacting secrets and sensitive payloads.

### Tool output and resources

- Treat text, structured output, resource URIs, MIME types, filenames, and UI metadata as hostile input.
- Do not interpolate tool text into system/developer instructions or trusted HTML.
- Enforce schema, MIME, size, URI-scheme, and origin checks at the gateway/host boundary.
- Preserve a distinction between model-visible summaries and durable artifact documents.
- Quarantine or reject malformed artifact replacements; do not persist them because the model says they are valid.

### MCP App host

- Render remote UI only in a sandboxed iframe on an isolated origin; do not grant same-origin access to the Agent Hub shell.
- Intersect the app-declared CSP with Agent Hub's catalog policy. A declaration requests access; it does not grant it automatically.
- Expose a small, versioned host bridge with capability checks for each operation. Validate message source, origin where meaningful, shape, size, and correlation identifiers.
- Do not expose cookies, bearer tokens, raw Project storage, unrestricted navigation, popup access, downloads, clipboard, camera, microphone, or geolocation by default.
- Prefer same-server MCP tool calls through the host bridge over direct iframe access to protected APIs.
- Tear down subscriptions and in-flight operations when the view closes or changes Artifact.

## What curation guarantees

Curation may guarantee that Agent Hub reviewed a specific plugin version, operator, endpoint set, declared schemas, and requested capabilities. It cannot guarantee that the remote service is never compromised, that its data is correct, that tool output is non-malicious, or that a future version deserves the same permissions. Runtime defenses remain mandatory.

## Deferred hardening

The foundation does not need arbitrary-code execution, arbitrary user-entered MCP endpoints, private-network connectors, unattended high-consequence workflows, or a full enterprise policy language. Those capabilities require a separate threat model and stronger isolation.

## Decision

Adopt **curated but zero-trust-at-runtime MCP integration**: a server-side egress/auth/policy gateway, schema validation and approval before persistence or consequential action, and sandboxed MCP Apps with a capability-limited bridge. This is the minimum boundary that keeps later engineering plugins from becoming implicit trusted code.

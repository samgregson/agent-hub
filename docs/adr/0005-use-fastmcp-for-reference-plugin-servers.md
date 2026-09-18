---
status: accepted
---

# Use FastMCP for reference Plugin servers

Agent Hub's reference implementation for a portable Plugin is a separately
deployable Python service built with FastMCP. It exposes ordinary MCP tools and
resources over Streamable HTTP. A Plugin may optionally bundle a React/Vite MCP
App as a standard `ui://` resource, but the React application is not the MCP
server.

The Agent Hub Plugin Gateway remains an MCP client and does not depend on
FastMCP types or APIs. This preserves the ability to consume a reviewed Plugin
implemented with another conforming MCP server, while giving Plugin authors a
well-supported Python default suitable for future calculation and validation
work.

## Consequences

Each reference Plugin has its own source root, Python dependency lockfile, and
Docker image. Local Compose runs it as a distinct service; deployed Agent Hub
uses its reviewed Streamable HTTP endpoint. A Plugin's optional Vite build is
packaged with its service and exposed through standard MCP resource handling,
not through a separate production UI server.

The existing fixture becomes a FastMCP service. Its conformance test must prove
that an ordinary MCP client can discover its read-only tool, receive text and
structured output, and load its `ui://` resource. Agent Hub-specific catalog,
Project enablement, persistence, and artifact behaviour remain outside the
portable Plugin contract.

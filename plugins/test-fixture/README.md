# Test fixture Plugin

A deliberately small portable FastMCP server used to verify Agent Hub's Plugin
Gateway. It exposes one read-only `foundation_status` tool with concise text
and structured output, plus a standards-compatible `ui://` MCP App resource.
It has no Agent Hub-specific inputs or persistence, so it remains useful in a
generic MCP client. Clients without MCP Apps support still receive the normal
tool result.

The server runs over Streamable HTTP at `/mcp`; it does not use Agent Hub's API
or database. Its optional app is a static resource packaged into the same
container, not a separate production web server.

## First install

FastMCP cannot currently be resolved from this workspace's network. Once
package access is available, create the lockfile and install the pinned
dependency:

```bash
cd plugins/test-fixture
uv lock
uv sync
```

Then run the fixture locally with `uv run agent-hub-foundation-fixture`, or run
the generic-client conformance test with `uv run pytest`. Build its independent
container with `docker build -t agent-hub-foundation-fixture .`.

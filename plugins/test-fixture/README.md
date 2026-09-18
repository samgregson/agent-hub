# Test fixture Plugin

A deliberately small portable FastMCP 4 server used to verify Agent Hub's Plugin
Gateway. It exposes one read-only `foundation_status` tool with concise text
and structured output, plus a standards-compatible `ui://` MCP App resource.
It has no Agent Hub-specific inputs or persistence, so it remains useful in a
generic MCP client. Clients without MCP Apps support still receive the normal
tool result.

The server runs over Streamable HTTP at `/mcp`; it does not use Agent Hub's API
or database. Its optional app is a static resource packaged into the same
container, not a separate production web server.

## First install

FastMCP 4.0.4 cannot currently be resolved from this workspace's network. Once
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

## Current runtime finding

The pinned FastMCP 4.0.4 dependency starts the fixture under Python 3.14, but
a bare read-only tool call times out in its in-memory and stdio client paths.
The conformance test is a strict expected failure so that the limitation stays
visible and becomes a failure if the behaviour changes unexpectedly. Do not
treat it as completed transport validation; repeat the test against the
container's HTTP endpoint when the FastMCP/Python compatibility issue is
resolved.

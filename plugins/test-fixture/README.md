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

Install the pinned dependency and its lockfile:

```bash
cd plugins/test-fixture
uv lock
uv sync
```

Then run the fixture locally with `uv run agent-hub-foundation-fixture`, or run
the generic-client conformance test with `uv run pytest`. Build its independent
container with `docker build -t agent-hub-foundation-fixture .`.

With the repository Compose stack, the API remains at `http://localhost:8000`
and the fixture MCP endpoint is `http://localhost:8001/mcp`. The latter is a
Streamable HTTP protocol endpoint, rather than a browser-rendered page.

## Runtime compatibility

Under Python 3.14, FastMCP's synchronous handler path did not complete a
tool or resource call. The fixture deliberately uses asynchronous handlers and
its ordinary MCP-client conformance test is required to pass. Keep future
fixture handlers asynchronous unless the pinned FastMCP/Python combination is
revalidated.

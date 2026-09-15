# Test fixture Plugin

A deliberately small portable MCP server used to verify Agent Hub's Plugin
Gateway. It exposes one read-only `foundation_status` tool with concise text,
structured output, and a standards-compatible `ui://` MCP App resource. It has
no Agent Hub-specific inputs or persistence, so it also works in any standard
MCP client that supports stdio transports. Clients without MCP Apps support
still receive the normal text and structured tool result.

Run it locally with `pnpm --filter @agent-hub/test-fixture-plugin start`.
Run its generic-client conformance test with
`pnpm --filter @agent-hub/test-fixture-plugin test`.

import { resolve } from "node:path";
import { pathToFileURL } from "node:url";

import { McpServer } from "@modelcontextprotocol/sdk/server/mcp.js";
import { StdioServerTransport } from "@modelcontextprotocol/sdk/server/stdio.js";

export const FIXTURE_TOOL_NAME = "foundation_status";

export function createFixtureServer() {
  const server = new McpServer({
    name: "agent-hub-foundation-fixture",
    version: "0.1.0",
  });

  server.registerTool(
    FIXTURE_TOOL_NAME,
    {
      title: "Foundation status",
      description:
        "Return a small, read-only structured status from the Agent Hub fixture Plugin.",
      annotations: {
        readOnlyHint: true,
      },
    },
    async () => ({
      content: [
        {
          type: "text",
          text: "Agent Hub's portable MCP fixture is available.",
        },
      ],
      structuredContent: {
        status: "available",
        source: "agent-hub-foundation-fixture",
      },
    }),
  );

  return server;
}

if (import.meta.url === pathToFileURL(resolve(process.argv[1])).href) {
  const server = createFixtureServer();
  await server.connect(new StdioServerTransport());
}

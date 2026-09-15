import { readFile } from "node:fs/promises";
import { resolve } from "node:path";
import { pathToFileURL } from "node:url";

import {
  registerAppResource,
  registerAppTool,
  RESOURCE_MIME_TYPE,
} from "@modelcontextprotocol/ext-apps/server";
import { McpServer } from "@modelcontextprotocol/sdk/server/mcp.js";
import { StdioServerTransport } from "@modelcontextprotocol/sdk/server/stdio.js";

export const FIXTURE_TOOL_NAME = "foundation_status";
export const FIXTURE_APP_RESOURCE_URI = "ui://agent-hub-foundation/status.html";

async function loadFixtureApp() {
  return readFile(
    new URL("./foundation-status-view.html", import.meta.url),
    "utf8",
  );
}

export function createFixtureServer() {
  const server = new McpServer({
    name: "agent-hub-foundation-fixture",
    version: "0.1.0",
  });

  registerAppTool(
    server,
    FIXTURE_TOOL_NAME,
    {
      title: "Foundation status",
      description:
        "Return a small, read-only structured status from the Agent Hub fixture Plugin.",
      annotations: {
        readOnlyHint: true,
      },
      _meta: {
        ui: { resourceUri: FIXTURE_APP_RESOURCE_URI },
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

  registerAppResource(
    server,
    "Foundation status view",
    FIXTURE_APP_RESOURCE_URI,
    {
      description:
        "A small standards-compatible MCP App for the Agent Hub fixture status.",
      _meta: {
        ui: { prefersBorder: true },
      },
    },
    async () => ({
      contents: [
        {
          uri: FIXTURE_APP_RESOURCE_URI,
          mimeType: RESOURCE_MIME_TYPE,
          text: await loadFixtureApp(),
          _meta: {
            ui: { prefersBorder: true },
          },
        },
      ],
    }),
  );

  return server;
}

if (import.meta.url === pathToFileURL(resolve(process.argv[1])).href) {
  const server = createFixtureServer();
  await server.connect(new StdioServerTransport());
}

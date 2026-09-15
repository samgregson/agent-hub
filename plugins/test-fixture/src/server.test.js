import assert from "node:assert/strict";
import test from "node:test";

import { Client } from "@modelcontextprotocol/sdk/client/index.js";
import { InMemoryTransport } from "@modelcontextprotocol/sdk/inMemory.js";

import {
  createFixtureServer,
  FIXTURE_APP_RESOURCE_URI,
  FIXTURE_TOOL_NAME,
} from "./server.js";

test("the fixture is usable by an ordinary MCP client", async () => {
  const [clientTransport, serverTransport] =
    InMemoryTransport.createLinkedPair();
  const client = new Client({ name: "fixture-test-client", version: "0.1.0" });
  const server = createFixtureServer();

  try {
    await server.connect(serverTransport);
    await client.connect(clientTransport);
    const tools = await client.listTools();
    const fixture = tools.tools.find((tool) => tool.name === FIXTURE_TOOL_NAME);
    assert.equal(fixture?.annotations?.readOnlyHint, true);
    assert.equal(fixture?._meta?.["ui/resourceUri"], FIXTURE_APP_RESOURCE_URI);

    const result = await client.callTool({
      name: FIXTURE_TOOL_NAME,
      arguments: {},
    });
    assert.deepEqual(result.structuredContent, {
      source: "agent-hub-foundation-fixture",
      status: "available",
    });
    assert.equal(result.content[0]?.type, "text");

    const resources = await client.listResources();
    assert.equal(
      resources.resources.some(
        (resource) => resource.uri === FIXTURE_APP_RESOURCE_URI,
      ),
      true,
    );
    const app = await client.readResource({ uri: FIXTURE_APP_RESOURCE_URI });
    assert.equal(app.contents[0]?.mimeType, "text/html;profile=mcp-app");
    assert.match(app.contents[0]?.text ?? "", /Foundation fixture available/);
  } finally {
    await clientTransport.close();
  }
});

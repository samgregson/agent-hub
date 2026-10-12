import { readFileSync } from "node:fs";

import { expect, test } from "@playwright/test";

test("Plugins are available through the browser-facing Project API", async ({
  request,
}) => {
  const projectResponse = await request.post("/api/projects", {
    data: { name: "Plugin proxy verification" },
  });
  expect(projectResponse.status()).toBe(201);
  const project = (await projectResponse.json()) as { id: string };

  const pluginsResponse = await request.get(
    `/api/projects/${project.id}/plugins`,
  );

  expect(pluginsResponse.status()).toBe(200);
  await expect(pluginsResponse.json()).resolves.toEqual(
    expect.arrayContaining([
      expect.objectContaining({
        enabled: false,
        id: "foundation-fixture",
        name: "Foundation fixture",
        tools: expect.arrayContaining([
          { name: "foundation_status", readOnly: true },
          { name: "create_status_artifact", readOnly: false },
          { name: "validate_status_artifact", readOnly: true },
          { name: "set_status_artifact_status", readOnly: false },
          { name: "render_template_value", readOnly: true },
        ]),
        version: "0.1.0",
      }),
      {
        enabled: false,
        id: "reference-calculation",
        name: "Reference calculation",
        tools: [{ name: "calculate_cantilever_tip_load", readOnly: false }],
        version: "0.1.0",
      },
    ]),
  );
});

test("Plugin selections can be updated through the browser-facing Project API", async ({
  request,
}) => {
  const projectResponse = await request.post("/api/projects", {
    data: { name: "Plugin selection proxy verification" },
  });
  expect(projectResponse.status()).toBe(201);
  const project = (await projectResponse.json()) as { id: string };
  const selectionUrl = `/api/projects/${project.id}/plugins/foundation-fixture`;

  const enabledResponse = await request.put(selectionUrl);
  expect(enabledResponse.status()).toBe(204);
  const enabledPlugins = await request.get(
    `/api/projects/${project.id}/plugins`,
  );
  await expect(enabledPlugins.json()).resolves.toEqual(
    expect.arrayContaining([
      expect.objectContaining({ enabled: true, id: "foundation-fixture" }),
    ]),
  );

  const disabledResponse = await request.delete(selectionUrl);
  expect(disabledResponse.status()).toBe(204);
});

test("the browser-facing Project API forwards work item deletion", async ({
  request,
}) => {
  const projectResponse = await request.post("/api/projects", {
    data: { name: "Work deletion proxy verification" },
  });
  expect(projectResponse.status()).toBe(201);
  const project = (await projectResponse.json()) as { id: string };

  const fileResponse = await request.delete(
    `/api/projects/${project.id}/files?path=/project/missing.txt`,
  );
  expect(fileResponse.status()).toBe(404);

  const artifactResponse = await request.delete(
    `/api/projects/${project.id}/artifacts/missing-artifact`,
  );
  expect(artifactResponse.status()).toBe(404);
});

test("user can create a Project", async ({ page }) => {
  const project = {
    createdAt: "2026-09-15T00:00:00.000Z",
    id: "project-123",
    name: "Design review",
    updatedAt: "2026-09-15T00:00:00.000Z",
  };

  await page.route("**/api/projects", async (route) => {
    if (route.request().method() === "GET") {
      await route.fulfill({ json: [] });
      return;
    }

    await route.fulfill({ json: project, status: 201 });
  });

  await page.goto("/");
  await page.getByLabel("Selected Project").selectOption({
    label: "New Project…",
  });

  const dialog = page.getByRole("dialog", { name: "New Project" });
  const name = dialog.getByLabel("Project name");
  await expect(name).toBeFocused();
  await name.fill(project.name);
  await name.press("Enter");

  await expect(page.getByLabel("Selected Project")).toHaveValue(project.id);
  await expect(dialog).toBeHidden();
});

test("project creation is unavailable before the workspace hydrates", async ({
  browser,
}) => {
  const context = await browser.newContext({ javaScriptEnabled: false });
  const page = await context.newPage();

  await page.goto("/");
  await expect(page.getByLabel("Selected Project")).toBeDisabled();
  await context.close();
});

test("Project Workflow overview shows final outputs and inspectable DAG lineage", async ({
  page,
}) => {
  const project = {
    createdAt: "2026-10-01T00:00:00.000Z",
    id: "project-workflow",
    name: "Design review",
    updatedAt: "2026-10-01T00:00:00.000Z",
  };
  const workflow = {
    id: "workflow-review",
    name: "Design review",
    version: 3,
    graph: {
      nodes: [
        { id: "inputs", kind: "dataset", refId: "loads", version: 2 },
        {
          id: "screen",
          kind: "python",
          refId: "filter-function",
          version: 1,
          shape: "map",
        },
        {
          id: "calculate",
          kind: "mcp",
          refId: "calculation-plugin",
          version: "0.4.0",
          toolName: "calculate",
        },
        {
          id: "summarize",
          kind: "python",
          refId: "summary-function",
          version: 2,
        },
        { id: "report", kind: "python", refId: "report-function", version: 1 },
      ],
      edges: [
        {
          sourceNode: "inputs",
          sourcePort: "records",
          targetNode: "screen",
          targetPort: "items",
        },
        {
          sourceNode: "screen",
          sourcePort: "result",
          targetNode: "calculate",
          targetPort: "record",
        },
        {
          sourceNode: "screen",
          sourcePort: "result",
          targetNode: "summarize",
          targetPort: "records",
        },
        {
          sourceNode: "calculate",
          sourcePort: "result",
          targetNode: "report",
          targetPort: "check",
        },
        {
          sourceNode: "summarize",
          sourcePort: "result",
          targetNode: "report",
          targetPort: "summary",
        },
      ],
      outputs: [{ name: "Review", node: "report", port: "result" }],
    },
  };
  const run = {
    id: "workflow-run-2",
    workflowId: workflow.id,
    definitionVersion: 3,
    status: "succeeded",
    snapshot: {
      graph: workflow.graph,
      sources: {
        inputs: {
          datasetId: "loads",
          version: 2,
          records: [{ id: "LC-1", position: 0, value: { load: 12.5 } }],
        },
      },
      targets: {
        screen: {
          definitionId: "filter-function",
          revision: 1,
          source: "def transform(record, parameters): return record",
        },
      },
    },
    execution: {
      outputs: {
        Review: { checked: 1, passed: 1 },
      },
      nodes: {
        screen: {
          status: "succeeded",
          inputs: { items: [{ id: "LC-1", load: 12.5 }] },
          output: [{ id: "LC-1", load: 12.5 }],
        },
        calculate: {
          status: "succeeded",
          inputs: { record: { id: "LC-1", load: 12.5 } },
          output: { id: "LC-1", pass: true },
        },
        summarize: {
          status: "succeeded",
          inputs: { records: [{ id: "LC-1", pass: true }] },
          output: { checked: 1, passed: 1 },
        },
        report: {
          status: "succeeded",
          inputs: {
            check: { id: "LC-1", pass: true },
            summary: { checked: 1, passed: 1 },
          },
          output: { checked: 1, passed: 1 },
        },
      },
    },
    initiatorSubject: "owner",
    createdAt: "2026-10-11T09:00:00.000Z",
  };

  await page.setViewportSize({ width: 1440, height: 1000 });
  await page.route("**/api/projects", async (route) => {
    await route.fulfill({ json: [project] });
  });
  await page.route(`**/api/projects/${project.id}/threads`, async (route) => {
    await route.fulfill({ json: [] });
  });
  await page.route(`**/api/projects/${project.id}/datasets`, async (route) => {
    await route.fulfill({
      json: [{ id: "loads-extra", name: "Extra loads", version: 1 }],
    });
  });
  await page.route(
    `**/api/projects/${project.id}/files/index`,
    async (route) => {
      await route.fulfill({ json: { files: [] } });
    },
  );
  await page.route(
    `**/api/projects/${project.id}/transforms`,
    async (route) => {
      await route.fulfill({
        json: [
          {
            id: "summary-function",
            name: "Summarize loads",
            revision: 1,
            inputSelectors: { records: "$" },
          },
        ],
      });
    },
  );
  await page.route(`**/api/projects/${project.id}/plugins`, async (route) => {
    await route.fulfill({
      json: [
        {
          id: "calculation-plugin",
          name: "Calculator",
          version: "0.4.0",
          enabled: true,
          tools: [{ name: "calculate", readOnly: true }],
        },
      ],
    });
  });
  await page.route(
    `**/api/projects/${project.id}/plugins/calculation-plugin/tools`,
    async (route) => {
      await route.fulfill({
        json: [
          {
            name: "calculate",
            version: "0.4.0",
            repeatSafe: true,
            inputSchema: {
              type: "object",
              properties: { record: { type: "object" } },
              required: ["record"],
            },
            outputSchema: { type: "object" },
          },
        ],
      });
    },
  );
  await page.route(`**/api/projects/${project.id}/workflows`, async (route) => {
    await route.fulfill({ json: [workflow] });
  });
  await page.route(
    `**/api/projects/${project.id}/workflows/${workflow.id}/runs`,
    async (route) => {
      await route.fulfill({ json: [run] });
    },
  );
  let preparedRequest: Record<string, unknown> | undefined;
  let revisedRequest: Record<string, unknown> | undefined;
  let savedGraph: unknown;
  await page.route(
    `**/api/projects/${project.id}/workflows/${workflow.id}`,
    async (route) => {
      if (route.request().method() !== "PUT") return route.continue();
      revisedRequest = route.request().postDataJSON() as Record<
        string,
        unknown
      >;
      savedGraph = revisedRequest.graph;
      await route.fulfill({
        json: {
          ...workflow,
          graph: savedGraph,
          name: "Beam review v2",
          version: 4,
        },
      });
    },
  );
  await page.route(
    `**/api/projects/${project.id}/workflows/${workflow.id}/runs/prepare`,
    async (route) => {
      preparedRequest = route.request().postDataJSON() as Record<
        string,
        unknown
      >;
      await route.fulfill({
        json: {
          ...run,
          definitionVersion: 4,
          id: "workflow-run-prepared",
          snapshot: { ...run.snapshot, graph: savedGraph },
          status: "prepared",
        },
        status: 201,
      });
    },
  );
  await page.route(
    `**/api/projects/${project.id}/workflows/${workflow.id}/runs/workflow-run-prepared/execute`,
    async (route) => {
      await route.fulfill({
        json: {
          ...run,
          definitionVersion: 4,
          execution: {
            ...run.execution,
            outputs: { Quality: { checked: 1, passed: 1 } },
          },
          id: "workflow-run-3",
          snapshot: { ...run.snapshot, graph: savedGraph },
          createdAt: "2026-10-11T10:00:00.000Z",
        },
      });
    },
  );

  await page.goto("/");

  await expect(
    page.getByRole("heading", { name: workflow.name }),
  ).toBeVisible();
  await expect(
    page.getByRole("region", { name: "Workflow outputs" }),
  ).toContainText('"checked": 1');
  await expect(
    page.getByRole("region", { name: "Workflow graph" }),
  ).toContainText("Map");
  await page.getByRole("button", { name: "Inspect screen" }).click();
  await expect(
    page.getByRole("region", { name: "Node lineage" }),
  ).toContainText("LC-1");
  await expect(
    page.getByRole("region", { name: "Node lineage" }),
  ).toContainText("Inputs");
  await expect(
    page.getByRole("region", { name: "Node lineage" }),
  ).toContainText("filter-function");
  await page.getByRole("button", { name: "Close details" }).click();
  await page.getByRole("button", { name: "Inspect inputs" }).click();
  await page.getByRole("button", { name: "Open Library" }).click();
  await expect(
    page.getByRole("region", { name: "Library items" }),
  ).toBeVisible();
  await page.getByRole("button", { name: "Workflow", exact: true }).click();
  await page.getByRole("button", { name: "Inspect calculate" }).click();
  await page.getByRole("button", { name: "Open Operations" }).click();
  await expect(
    page
      .getByRole("navigation", { name: "Project views" })
      .getByRole("button", { name: "Operations" }),
  ).toHaveAttribute("aria-pressed", "true");
  await page.getByRole("button", { name: "Workflow", exact: true }).click();
  await page.getByRole("button", { name: "Inspect screen" }).click();
  await page.getByRole("button", { name: "Edit Workflow" }).click();
  await page
    .getByLabel("Library item or call")
    .selectOption("Function · Summarize loads");
  await page.getByLabel("Call shape").selectOption("map");
  await page.getByRole("button", { name: "Add node" }).click();
  await expect(
    page.getByRole("region", { name: "Workflow nodes" }),
  ).toContainText("call-6");
  await page.getByRole("button", { name: "Add connection" }).click();
  await expect(
    page
      .getByRole("region", { name: "Workflow connections" })
      .getByLabel("To node")
      .last(),
  ).toHaveValue("call-6");
  await expect(
    page
      .getByRole("region", { name: "Workflow connections" })
      .getByLabel("Input port")
      .last(),
  ).toHaveValue("items");
  await page
    .getByLabel("Library item or call")
    .selectOption("MCP · Calculator / calculate");
  await page.getByLabel("Call shape").selectOption("single");
  await page.getByRole("button", { name: "Add node" }).click();
  await page.getByRole("button", { name: "Add connection" }).click();
  await expect(
    page
      .getByRole("region", { name: "Workflow connections" })
      .getByLabel("To node")
      .last(),
  ).toHaveValue("call-7");
  await expect(
    page
      .getByRole("region", { name: "Workflow connections" })
      .getByLabel("Input port")
      .last(),
  ).toHaveValue("record");
  await page.getByLabel("Workflow name").fill("Beam review v2");
  await page.getByLabel("Name", { exact: true }).fill("Quality");
  await page
    .getByRole("button", { name: "Save new Definition version" })
    .click();
  await expect(
    page.getByRole("heading", { name: "Beam review v2" }),
  ).toBeVisible();
  await expect.poll(() => revisedRequest?.expectedVersion).toBe(3);
  expect(revisedRequest?.name).toBe("Beam review v2");
  expect(
    (revisedRequest?.graph as { outputs: Array<{ name: string }> }).outputs[0]
      ?.name,
  ).toBe("Quality");
  await page.getByRole("button", { name: "Run Workflow" }).click();
  await expect.poll(() => preparedRequest?.expectedVersion).toBe(4);
  expect(preparedRequest?.idempotencyKey).toEqual(expect.any(String));
  await expect(
    page.getByRole("region", { name: "Workflow outputs" }),
  ).toContainText('"passed": 1');

  await page.setViewportSize({ width: 390, height: 844 });
  await expect(
    page.getByRole("region", { name: "Workflow outputs" }),
  ).toBeVisible();
  await expect(
    page.getByRole("region", { name: "Workflow graph" }),
  ).toBeVisible();
  await expect(
    page.getByRole("list", { name: "Workflow dependencies" }),
  ).toContainText("calculate");
  await page.getByRole("button", { name: "Edit Workflow" }).click();
  await expect(
    page.getByRole("region", { name: "Edit Workflow Definition" }),
  ).toBeVisible();
  await expect
    .poll(() =>
      page.evaluate(
        () => document.documentElement.scrollWidth === window.innerWidth,
      ),
    )
    .toBe(true);
});

test("a Project Workflow can be created from Library and Operations", async ({
  page,
}) => {
  const project = {
    createdAt: "2026-10-01T00:00:00.000Z",
    id: "project-create-workflow",
    name: "Test Project",
    updatedAt: "2026-10-01T00:00:00.000Z",
  };
  let createRequest: Record<string, unknown> | undefined;

  await page.route("**/api/projects", async (route) => {
    await route.fulfill({ json: [project] });
  });
  await page.route(`**/api/projects/${project.id}/threads`, async (route) => {
    await route.fulfill({ json: [] });
  });
  await page.route(`**/api/projects/${project.id}/workflows`, async (route) => {
    if (route.request().method() === "POST") {
      createRequest = route.request().postDataJSON() as Record<string, unknown>;
      await route.fulfill({
        json: {
          id: "workflow-new",
          name: createRequest.name,
          version: 1,
          graph: createRequest.graph,
        },
        status: 201,
      });
      return;
    }
    await route.fulfill({ json: [] });
  });
  await page.route(`**/api/projects/${project.id}/datasets`, async (route) => {
    await route.fulfill({
      json: [{ id: "loads", name: "Loads", version: 2 }],
    });
  });
  await page.route(
    `**/api/projects/${project.id}/files/index`,
    async (route) => {
      await route.fulfill({ json: { files: [] } });
    },
  );
  await page.route(
    `**/api/projects/${project.id}/transforms`,
    async (route) => {
      await route.fulfill({
        json: [
          {
            id: "calculate",
            name: "Calculate loads",
            revision: 2,
            inputSelectors: { records: "$" },
          },
        ],
      });
    },
  );
  await page.route(`**/api/projects/${project.id}/plugins`, async (route) => {
    await route.fulfill({ json: [] });
  });

  await page.setViewportSize({ width: 390, height: 844 });
  await page.goto("/");
  await page.getByRole("button", { name: "Open Project navigation" }).click();
  await page.getByRole("button", { name: "Workflow" }).click();
  await page
    .getByRole("button", { name: "Close Project navigation" })
    .last()
    .click();
  await page.getByRole("button", { name: "Create Workflow" }).click();
  await page.getByLabel("Library item or call").selectOption("Dataset · Loads");
  await page.getByRole("button", { name: "Add node" }).click();
  await page
    .getByLabel("Library item or call")
    .selectOption("Function · Calculate loads");
  await page.getByLabel("Call shape").selectOption("map");
  await page.getByRole("button", { name: "Add node" }).click();
  await page.getByRole("button", { name: "Add connection" }).click();
  await page
    .getByRole("region", { name: "Workflow outputs editor" })
    .getByLabel("From node")
    .selectOption("call-2");
  await page.getByLabel("Workflow name").fill("Load check");
  await page.getByRole("button", { name: "Create Workflow" }).click();

  await expect(page.getByRole("heading", { name: "Load check" })).toBeVisible();
  expect(createRequest?.name).toBe("Load check");
  const graph = createRequest?.graph as {
    nodes: Array<{ kind: string; shape: string }>;
    edges: Array<{ sourcePort: string; targetPort: string }>;
    outputs: Array<{ node: string; port: string }>;
  };
  expect(graph.nodes.map((node) => node.kind)).toEqual(["dataset", "python"]);
  expect(graph.nodes[1]?.shape).toBe("map");
  expect(graph.edges[0]).toMatchObject({
    sourcePort: "records",
    targetPort: "items",
  });
  expect(graph.outputs[0]).toMatchObject({ node: "call-2", port: "result" });
  await expect
    .poll(() =>
      page.evaluate(
        () => document.documentElement.scrollWidth === window.innerWidth,
      ),
    )
    .toBe(true);
});

test("Workflow editor exposes shared Project File inputs on MCP Map nodes", async ({
  page,
}) => {
  const project = {
    createdAt: "2026-10-01T00:00:00.000Z",
    id: "project-mcp-map-file",
    name: "Test Project",
    updatedAt: "2026-10-01T00:00:00.000Z",
  };
  let createRequest: Record<string, unknown> | undefined;

  await page.route("**/api/projects", async (route) => {
    await route.fulfill({ json: [project] });
  });
  await page.route(`**/api/projects/${project.id}/threads`, async (route) => {
    await route.fulfill({ json: [] });
  });
  await page.route(`**/api/projects/${project.id}/workflows`, async (route) => {
    if (route.request().method() === "POST") {
      createRequest = route.request().postDataJSON() as Record<string, unknown>;
      await route.fulfill({
        json: {
          id: "workflow-new",
          name: createRequest.name,
          version: 1,
          graph: createRequest.graph,
        },
        status: 201,
      });
      return;
    }
    await route.fulfill({ json: [] });
  });
  await page.route(`**/api/projects/${project.id}/datasets`, async (route) => {
    await route.fulfill({
      json: [{ id: "loads", name: "Loads", version: 2 }],
    });
  });
  await page.route(
    `**/api/projects/${project.id}/files/index`,
    async (route) => {
      await route.fulfill({
        json: { files: [{ path: "/project/check.py", version: 3 }] },
      });
    },
  );
  await page.route(
    `**/api/projects/${project.id}/transforms`,
    async (route) => {
      await route.fulfill({ json: [] });
    },
  );
  await page.route(`**/api/projects/${project.id}/plugins`, async (route) => {
    await route.fulfill({
      json: [
        {
          enabled: true,
          id: "calculator",
          name: "Calculator",
          tools: [{ name: "check" }],
          version: "v1",
        },
      ],
    });
  });
  await page.route(
    `**/api/projects/${project.id}/plugins/calculator/tools`,
    async (route) => {
      await route.fulfill({
        json: [
          {
            inputSchema: {
              type: "object",
              required: ["load", "template"],
              properties: {
                load: { type: "number" },
                template: { type: "string" },
              },
            },
            name: "check",
            outputSchema: { type: "object" },
            repeatSafe: true,
            version: "v1",
          },
        ],
      });
    },
  );

  await page.goto("/");
  await page.getByRole("button", { name: "Workflow", exact: true }).click();
  await page.getByRole("button", { name: "Create Workflow" }).click();
  await page.getByLabel("Library item or call").selectOption("Dataset · Loads");
  await page.getByRole("button", { name: "Add node" }).click();
  await page
    .getByLabel("Library item or call")
    .selectOption("Project File · /project/check.py");
  await page.getByRole("button", { name: "Add node" }).click();
  await page
    .getByLabel("Library item or call")
    .selectOption("MCP · Calculator / check");
  await page.getByLabel("Call shape").selectOption("map");
  await page.getByRole("button", { name: "Add node" }).click();
  await page.getByRole("button", { name: "Add connection" }).click();
  await page.getByRole("button", { name: "Add connection" }).click();
  const secondConnection = page
    .getByRole("region", { name: "Workflow connections" })
    .locator('[class*="editorRow"]')
    .nth(1);
  await secondConnection.getByLabel("From node").selectOption("input-2");
  await secondConnection.getByLabel("To node").selectOption("call-3");
  await expect(secondConnection.getByLabel("Input port")).toHaveAttribute(
    "list",
    "workflow-input-ports-1",
  );
  await secondConnection.getByLabel("Input port").fill("template");
  await page.getByLabel("Workflow name").fill("Calculate each row");
  await page.getByRole("button", { name: "Create Workflow" }).click();

  const graph = createRequest?.graph as {
    edges: Array<{
      sourceNode: string;
      sourcePort: string;
      targetNode: string;
      targetPort: string;
    }>;
  };
  expect(graph.edges).toEqual([
    {
      sourceNode: "input-1",
      sourcePort: "records",
      targetNode: "call-3",
      targetPort: "items",
    },
    {
      sourceNode: "input-2",
      sourcePort: "content",
      targetNode: "call-3",
      targetPort: "template",
    },
  ]);
});

test("Datasets are created and deleted through Library commands", async ({
  page,
}) => {
  const project = {
    createdAt: "2026-09-24T00:00:00.000Z",
    id: "project-123",
    name: "Design review",
    updatedAt: "2026-09-24T00:00:00.000Z",
  };
  const created = {
    id: "dataset-123",
    name: "Load cases",
    version: 1,
    filePath: "/project/.datasets/dataset-123.json",
    records: [
      {
        id: "record-123",
        position: 0,
        sourceKey: "LC-1",
        value: { load: 12.5 },
      },
    ],
  };
  let deleted = false;
  await page.route("**/api/projects", async (route) => {
    await route.fulfill({ json: [project] });
  });
  await page.route(`**/api/projects/${project.id}/artifacts`, async (route) => {
    await route.fulfill({ json: { artifacts: [] } });
  });
  await page.route(
    `**/api/projects/${project.id}/files/index`,
    async (route) => {
      await route.fulfill({ json: { files: [] } });
    },
  );
  await page.route(
    `**/api/projects/${project.id}/batch-definitions`,
    async (route) => {
      await route.fulfill({ json: [] });
    },
  );
  await page.route(`**/api/projects/${project.id}/datasets`, async (route) => {
    if (route.request().method() === "POST") {
      await route.fulfill({ json: created, status: 201 });
      return;
    }
    await route.fulfill({ json: [] });
  });
  await page.route(
    `**/api/projects/${project.id}/datasets/${created.id}`,
    async (route) => {
      if (route.request().method() === "DELETE") {
        deleted = true;
        await route.fulfill({ status: 204 });
        return;
      }
      await route.fulfill({ json: created });
    },
  );

  await page.goto("/");
  await page.getByRole("button", { name: "Library" }).click();
  await page.getByRole("button", { name: "+ New Dataset" }).click();
  await page.getByLabel("Name").fill(created.name);
  await page
    .getByLabel("Records (JSON array)")
    .fill('[{"sourceKey":"LC-1","value":{"load":12.5}}]');
  await page.getByRole("button", { name: "Save Dataset" }).click();
  await expect(
    page.getByRole("button", { name: "Load cases", exact: true }),
  ).toBeVisible();
  await page.getByRole("button", { name: "Load cases actions" }).click();
  await page.getByRole("menuitem", { name: "Delete" }).click();
  await page
    .getByRole("dialog", { name: "Confirm deletion" })
    .getByRole("button", { name: "Delete" })
    .click();
  await expect.poll(() => deleted).toBe(true);
});

test("navigator catalogs share collection typography at desktop and phone widths", async ({
  page,
}) => {
  const project = {
    createdAt: "2026-09-24T00:00:00.000Z",
    id: "project-123",
    name: "Design review",
    updatedAt: "2026-09-24T00:00:00.000Z",
  };
  await page.route("**/api/projects", async (route) => {
    await route.fulfill({ json: [project] });
  });
  await page.route(`**/api/projects/${project.id}/threads`, async (route) => {
    await route.fulfill({ json: [] });
  });
  await page.route(`**/api/projects/${project.id}/artifacts`, async (route) => {
    await route.fulfill({ json: { artifacts: [] } });
  });
  await page.route(
    `**/api/projects/${project.id}/files/index`,
    async (route) => {
      await route.fulfill({ json: { files: [] } });
    },
  );
  await page.route(`**/api/projects/${project.id}/datasets`, async (route) => {
    await route.fulfill({
      json: [
        {
          id: "dataset-123",
          name: "Load cases",
          version: 1,
          filePath: "/project/.datasets/dataset-123.json",
          records: [],
        },
      ],
    });
  });
  await page.route(`**/api/projects/${project.id}/plugins`, async (route) => {
    await route.fulfill({
      json: [
        {
          enabled: false,
          id: "reference-calculation",
          name: "Reference calculation",
          tools: [{ name: "calculate_cantilever_tip_load", readOnly: false }],
          version: "0.1.0",
        },
      ],
    });
  });

  await page.goto("/");
  await page.getByRole("button", { name: "Library" }).click();
  const datasetTitle = page.getByText("Load cases");
  await expect(datasetTitle).toBeVisible();
  const desktopDatasetStyle = await datasetTitle.evaluate((element) => ({
    color: getComputedStyle(element).color,
    fontSize: getComputedStyle(element).fontSize,
  }));

  await page.getByRole("button", { name: "Plugins" }).click();
  const pluginTitle = page.getByText("Reference calculation");
  await expect(pluginTitle).toBeVisible();
  await expect(pluginTitle).toHaveCSS(
    "font-size",
    desktopDatasetStyle.fontSize,
  );
  await expect(pluginTitle).toHaveCSS("color", desktopDatasetStyle.color);

  await page.setViewportSize({ height: 844, width: 390 });
  await page.getByRole("button", { name: "Open Project navigation" }).click();
  const drawer = page.getByRole("dialog", { name: "Project navigation" });
  await drawer.getByRole("button", { name: "Library" }).click();
  const mobileDatasetTitle = drawer.getByText("Load cases");
  await expect(mobileDatasetTitle).toHaveCSS(
    "font-size",
    desktopDatasetStyle.fontSize,
  );
  await expect(mobileDatasetTitle).toHaveCSS(
    "color",
    desktopDatasetStyle.color,
  );
});

test("Project navigator can be resized with pointer and keyboard without narrow-screen overflow", async ({
  page,
}) => {
  const project = {
    createdAt: "2026-09-24T00:00:00.000Z",
    id: "resize-project",
    name: "A project with a long name that stays inside the header",
    updatedAt: "2026-09-24T00:00:00.000Z",
  };
  await page.route("**/api/projects", async (route) => {
    await route.fulfill({ json: [project] });
  });
  await page.route(`**/api/projects/${project.id}/threads`, async (route) => {
    await route.fulfill({ json: [] });
  });
  await page.route(`**/api/projects/${project.id}/workflows`, async (route) => {
    await route.fulfill({ json: [] });
  });

  await page.setViewportSize({ height: 900, width: 1440 });
  await page.goto("/");
  const separator = page.getByRole("separator", {
    name: "Resize Project navigator",
  });
  const navigator = page.locator("aside").filter({ has: separator });
  const initialWidth = (await navigator.boundingBox())?.width ?? 0;
  await separator.focus();
  await page.keyboard.press("ArrowRight");
  await expect(separator).toHaveAttribute("aria-valuenow", "272");
  const keyboardWidth = (await navigator.boundingBox())?.width ?? 0;
  expect(keyboardWidth).toBeGreaterThan(initialWidth);

  const bounds = await separator.boundingBox();
  const navigatorBounds = await navigator.boundingBox();
  if (!bounds) throw new Error("Navigator resize handle is not visible.");
  await page.mouse.move(bounds.x + bounds.width / 2, bounds.y + 40);
  await page.mouse.down();
  await page.mouse.move((navigatorBounds?.x ?? 0) + 440, bounds.y + 40, {
    steps: 8,
  });
  await page.mouse.up();
  await expect(separator).toHaveAttribute("aria-valuenow", "440");
  await page.getByRole("button", { name: "Library", exact: true }).click();
  await expect(navigator).toContainText("Library");
  await expect
    .poll(() =>
      page.evaluate(
        () => document.documentElement.scrollWidth <= window.innerWidth,
      ),
    )
    .toBe(true);

  await page.setViewportSize({ height: 844, width: 390 });
  await expect(separator).toBeHidden();
  await page.getByRole("button", { name: "Open Project navigation" }).click();
  await expect(
    page.getByRole("dialog", { name: "Project navigation" }),
  ).toBeVisible();
  await expect
    .poll(() =>
      page.evaluate(
        () => document.documentElement.scrollWidth <= window.innerWidth,
      ),
    )
    .toBe(true);
});

test("Library identifies Artifacts, Datasets, and Project Files without duplicates", async ({
  page,
}) => {
  const project = {
    createdAt: "2026-09-18T00:00:00.000Z",
    id: "project-123",
    name: "Design review",
    updatedAt: "2026-09-18T00:00:00.000Z",
  };
  await page.route("**/api/projects", async (route) => {
    await route.fulfill({ json: [project] });
  });
  await page.route(`**/api/projects/${project.id}/artifacts`, async (route) => {
    await route.fulfill({
      json: {
        artifacts: [
          {
            documentVersion: 1,
            id: "artifact-123",
            pluginId: "foundation-fixture",
            pluginVersion: "0.1.0",
            title: "Foundation status",
            type: "agent-hub.fixture.status",
          },
        ],
      },
    });
  });
  await page.route(
    `**/api/projects/${project.id}/files/index`,
    async (route) => {
      await route.fulfill({
        json: {
          files: [
            {
              path: "/project/foundation-notes.md",
              updatedAt: "2026-09-18T00:00:00.000Z",
              version: 1,
            },
            {
              path: "/project/.datasets/dataset-123.json",
              updatedAt: "2026-09-18T00:00:00.000Z",
              version: 2,
            },
          ],
        },
      });
    },
  );

  await page.route(`**/api/projects/${project.id}/datasets`, async (route) => {
    await route.fulfill({
      json: [
        {
          id: "dataset-123",
          name: "Load cases",
          filePath: "/project/.datasets/dataset-123.json",
          version: 2,
        },
      ],
    });
  });

  await page.goto("/");
  await page.getByRole("button", { name: "Library" }).click();

  await expect(
    page.getByRole("button", { exact: true, name: "Foundation status" }),
  ).toBeVisible();
  await expect(page.getByLabel("Library items")).toContainText(
    "Foundation status",
  );
  await expect(page.getByLabel("Library items")).toContainText(
    "/project/foundation-notes.md",
  );
  await expect(page.getByLabel("Library items")).toContainText(
    "Artifact · Version 1",
  );
  await expect(page.getByLabel("Library items")).toContainText(
    "Dataset · Version 2",
  );
  await expect(page.getByLabel("Library items")).toContainText(
    "Project File · Version 1",
  );
  await expect(
    page.getByRole("button", { name: "Load cases", exact: true }),
  ).toHaveCount(1);
  await expect(
    page.getByText(
      "Durable project work products. Project files appear below until elevated.",
    ),
  ).toHaveCount(0);
  await expect(
    page.getByText(
      "Shared working files. Opening one does not create an Artifact.",
    ),
  ).toHaveCount(0);
});

test("Operations keeps Batch and Transform actions under one Project destination", async ({
  page,
}) => {
  const project = {
    createdAt: "2026-09-18T00:00:00.000Z",
    id: "project-operations",
    name: "Design review",
    updatedAt: "2026-09-18T00:00:00.000Z",
  };
  await page.route("**/api/projects", async (route) => {
    await route.fulfill({ json: [project] });
  });
  await page.route(`**/api/projects/${project.id}/threads`, async (route) => {
    await route.fulfill({ json: [] });
  });
  await page.route(`**/api/projects/${project.id}/artifacts`, async (route) => {
    await route.fulfill({ json: { artifacts: [] } });
  });
  await page.route(
    `**/api/projects/${project.id}/files/index`,
    async (route) => {
      await route.fulfill({ json: { files: [] } });
    },
  );
  await page.route(`**/api/projects/${project.id}/datasets`, async (route) => {
    await route.fulfill({ json: [] });
  });
  await page.route(
    `**/api/projects/${project.id}/batch-definitions`,
    async (route) => {
      await route.fulfill({ json: [] });
    },
  );
  await page.route(
    `**/api/projects/${project.id}/batch-runs?**`,
    async (route) => {
      await route.fulfill({ json: { items: [], nextOffset: null } });
    },
  );
  await page.route(
    `**/api/projects/${project.id}/transforms`,
    async (route) => {
      await route.fulfill({ json: [] });
    },
  );
  await page.route(
    `**/api/projects/${project.id}/transforms/runs?**`,
    async (route) => {
      await route.fulfill({ json: { items: [], nextOffset: null } });
    },
  );

  await page.goto("/");
  const projectViews = page.getByRole("navigation", { name: "Project views" });
  await expect(
    projectViews.getByRole("button", { name: "Operations" }),
  ).toBeVisible();
  await expect(
    projectViews.getByRole("button", { name: "Functions" }),
  ).toHaveCount(0);
  await expect(
    projectViews.getByRole("button", { name: "Batch Definitions" }),
  ).toHaveCount(0);

  await projectViews.getByRole("button", { name: "Operations" }).click();
  const operationTypes = page.getByRole("navigation", {
    name: "Operation types",
  });
  await expect(
    page.getByRole("button", { name: "+ New Batch Definition" }),
  ).toBeVisible();
  await operationTypes.getByRole("button", { name: "Functions" }).click();
  await expect(
    page.getByRole("button", { name: "New Function" }),
  ).toBeVisible();
  await projectViews.getByRole("button", { name: "Library" }).click();
  await projectViews.getByRole("button", { name: "Operations" }).click();
  await expect(
    operationTypes.getByRole("button", { name: "Functions" }),
  ).toHaveAttribute("aria-pressed", "true");
});

test("Batch Runs retain their Definition context and can be opened from it", async ({
  page,
}) => {
  const project = {
    createdAt: "2026-10-10T00:00:00.000Z",
    id: "project-batch-context",
    name: "Design review",
    updatedAt: "2026-10-10T00:00:00.000Z",
  };
  const definitions = [
    {
      id: "definition-a",
      name: "Load check",
      datasetId: "dataset-a",
      datasetAvailable: true,
      pluginId: "calculator",
      toolName: "calculate",
      transformDefinitionId: null,
    },
    {
      id: "definition-b",
      name: "Stress check",
      datasetId: "dataset-a",
      datasetAvailable: true,
      pluginId: "calculator",
      toolName: "calculate",
      transformDefinitionId: null,
    },
  ];
  const runs = definitions.map((definition, index) => ({
    archivedAt: null,
    createdAt: "2026-10-10T00:00:00.000Z",
    definitionId: definition.id,
    definitionName: definition.name,
    id: `run-${index}`,
    initiatorSubject: "sam",
    initiation: { kind: "directUser", approval: "notRequired" },
    status: index === 1 ? "partial" : "succeeded",
    recordCount: index === 1 ? 2 : 1,
    succeededCount: 1,
    failedCount: index === 1 ? 1 : 0,
    updatedAt: "2026-10-10T00:00:00.000Z",
  }));
  await page.route("**/api/projects", (route) =>
    route.fulfill({ json: [project] }),
  );
  await page.route(`**/api/projects/${project.id}/threads`, (route) =>
    route.fulfill({ json: [] }),
  );
  await page.route(`**/api/projects/${project.id}/batch-definitions`, (route) =>
    route.fulfill({ json: definitions }),
  );
  await page.route(`**/api/projects/${project.id}/datasets`, (route) =>
    route.fulfill({ json: [] }),
  );
  await page.route(`**/api/projects/${project.id}/transforms`, (route) =>
    route.fulfill({ json: [] }),
  );
  await page.route(`**/api/projects/${project.id}/batch-runs?**`, (route) => {
    const definitionId = new URL(route.request().url()).searchParams.get(
      "definition_id",
    );
    return route.fulfill({
      json: {
        items: runs.filter(
          (run) => !definitionId || run.definitionId === definitionId,
        ),
        nextOffset: null,
      },
    });
  });
  await page.route(
    `**/api/projects/${project.id}/batch-runs/*/results?**`,
    (route) => {
      const query = new URL(route.request().url()).searchParams;
      const filtered =
        query.get("filter_path") === "/structuredOutput/score" &&
        query.get("equals") === "0.8" &&
        query.get("aggregate_path") === "/structuredOutput/score";
      const secondPage = query.get("offset") === "20";
      return route.fulfill({
        json: {
          items: filtered
            ? [
                {
                  datasetRecordId: secondPage ? "record-2" : "record-1",
                  error: null,
                  input: { load: 3 },
                  structuredOutput: { score: 0.8 },
                },
              ]
            : [
                {
                  datasetRecordId: "record-1",
                  error: null,
                  input: { load: 3 },
                  structuredOutput: { score: 0.8 },
                },
                {
                  datasetRecordId: "record-error",
                  error: "Tool timed out",
                  input: { load: 4 },
                  structuredOutput: null,
                },
              ],
          nextOffset: filtered && !secondPage ? 20 : null,
          summary: {
            totalCount: 2,
            succeededCount: filtered ? 2 : 1,
            failedCount: filtered ? 0 : 1,
            numericCount: 2,
            numericSum: 1.6,
            numericMin: 0.8,
            numericMax: 0.8,
            numericAverage: 0.8,
          },
        },
      });
    },
  );

  await page.goto("/");
  await page
    .getByRole("navigation", { name: "Project views" })
    .getByRole("button", { name: "Operations" })
    .click();
  const runsSection = page.getByRole("region", { name: "Recent Batch Runs" });
  await expect(runsSection).toContainText("Load check");
  await expect(runsSection).toContainText("Stress check");
  await page
    .getByRole("button", { name: "Inspect Batch Definition Stress check" })
    .click();
  await expect(page.getByLabel("Batch Run definition")).toHaveValue(
    "definition-b",
  );
  await expect(
    runsSection.getByRole("button", { name: "View Batch Run run-1" }),
  ).toBeVisible();
  await expect(
    runsSection.getByRole("button", { name: "View Batch Run run-0" }),
  ).toHaveCount(0);
  await expect(page.getByLabel("Batch Run results")).toContainText(
    "Stress check",
  );
  const resultView = page.getByLabel("Batch Run results");
  await expect(resultView).toContainText(
    "partial · 2 records · 1 succeeded · 1 failed",
  );
  await expect(resultView).toContainText("Tool timed out");
  await resultView
    .getByLabel("Filter field (JSON Pointer)")
    .fill("/structuredOutput/score");
  await resultView.getByLabel("Exact JSON value").fill("0.8");
  await resultView
    .getByLabel("Aggregate numeric field (JSON Pointer)")
    .fill("/structuredOutput/score");
  await resultView.getByRole("button", { name: "Apply result query" }).click();
  await expect(resultView).toContainText("2 results · 2 succeeded · 0 failed");
  await expect(resultView).toContainText("Average: 0.8");
  await expect(resultView).toContainText("Record record-1");
  await resultView.getByRole("button", { name: "Load more results" }).click();
  await expect(resultView).toContainText("Record record-2");
  await page.setViewportSize({ width: 390, height: 844 });
  await page.getByRole("button", { name: "Open Project navigation" }).click();
  const mobileNavigation = page.getByRole("dialog", {
    name: "Project navigation",
  });
  await mobileNavigation.getByRole("button", { name: "Operations" }).click();
  const mobileResultView = mobileNavigation.getByLabel("Batch Run results");
  await expect(mobileResultView.getByLabel("Result Set query")).toBeVisible();
  expect(
    await page.evaluate(
      () =>
        document.documentElement.scrollWidth >
        document.documentElement.clientWidth,
    ),
  ).toBe(false);
});

test("Transform Definition selection scopes retained Runs while historical Runs remain reachable", async ({
  page,
}) => {
  const project = {
    createdAt: "2026-10-10T00:00:00.000Z",
    id: "project-transform-context",
    name: "Transform review",
    updatedAt: "2026-10-10T00:00:00.000Z",
  };
  const definitions = ["First transform", "Second transform"].map(
    (name, index) => ({
      id: `definition-${index}`,
      name,
      source: "def transform(inputs, parameters): return inputs",
      inputSelectors: {},
      outputSchema: { type: "object" },
      runtime: "pyodide",
      packageHash: null,
      revision: 1,
    }),
  );
  const runs = [
    ...definitions.map((definition, index) => ({
      id: `run-${index}`,
      definitionId: definition.id,
      definitionSnapshot: {
        name: definition.name,
        source: definition.source,
        revision: 1,
      },
    })),
    {
      id: "run-deleted",
      definitionId: "deleted-definition",
      definitionSnapshot: {
        name: "Deleted transform",
        source: "",
        revision: 1,
      },
    },
  ].map((run) => ({
    ...run,
    status: "succeeded",
    inputs: { load: 3 },
    parameters: {},
    inputHash: "12345678",
    sourceHash: "12345678",
    packageHash: null,
    runtime: "pyodide",
    output: { value: 3 },
    outputManifest: {},
    error: null,
    initiation: { kind: "directUser", approval: "notRequired" },
    limits: {},
    createdAt: "2026-10-10T00:00:00.000Z",
  }));
  await page.route("**/api/projects", (route) =>
    route.fulfill({ json: [project] }),
  );
  await page.route(`**/api/projects/${project.id}/threads`, (route) =>
    route.fulfill({ json: [] }),
  );
  await page.route(`**/api/projects/${project.id}/transforms`, (route) =>
    route.fulfill({ json: definitions }),
  );
  await page.route(
    `**/api/projects/${project.id}/transforms/runs?**`,
    (route) => {
      const definitionId = new URL(route.request().url()).searchParams.get(
        "definitionId",
      );
      return route.fulfill({
        json: {
          items: runs.filter(
            (run) => !definitionId || run.definitionId === definitionId,
          ),
          nextOffset: null,
        },
      });
    },
  );

  await page.goto("/");
  await page
    .getByRole("navigation", { name: "Project views" })
    .getByRole("button", { name: "Operations" })
    .click();
  await page
    .getByRole("navigation", { name: "Operation types" })
    .getByRole("button", { name: "Functions" })
    .click();
  const retained = page.getByRole("region", { name: "Retained Runs" });
  const runList = retained.locator("ul").first();
  await expect(runList).toContainText("First transform");
  await expect(runList).not.toContainText("Deleted transform");
  await page
    .getByRole("button", { name: /Second transform Revision 1/ })
    .click();
  await expect(page.getByLabel("Function Run scope")).toHaveValue(
    "definition-1",
  );
  await expect(runList).toContainText("Second transform");
  await expect(runList).not.toContainText("First transform");
  await expect(runList).not.toContainText("Deleted transform");
  await expect(page.getByLabel("Run dataflow")).toContainText(
    "Second transform",
  );
  await page.setViewportSize({ width: 390, height: 844 });
  await expect(page.getByLabel("Function Run scope")).toHaveValue(
    "definition-1",
  );
  expect(
    await page.evaluate(
      () => document.documentElement.scrollWidth <= window.innerWidth,
    ),
  ).toBe(true);
  await page.getByRole("button", { name: "Open Project navigation" }).click();
  const phoneDrawer = page.getByRole("dialog", { name: "Project navigation" });
  await phoneDrawer
    .getByRole("button", { name: /Second transform Revision 1/ })
    .click();
  const phoneScope = phoneDrawer.getByLabel("Function Run scope");
  await expect(phoneScope).toHaveValue("definition-1");
  await phoneDrawer
    .getByRole("button", { name: "Close Project navigation" })
    .click();
  await page.getByRole("button", { name: "Open Project navigation" }).click();
  await expect(phoneDrawer.getByLabel("Function Run scope")).toHaveValue(
    "definition-1",
  );
  await phoneScope.selectOption("all");
  await expect(
    phoneDrawer.getByRole("region", { name: "Retained Runs" }),
  ).toContainText("Deleted transform");
});

test("Library opens a registered Dataset in its table viewer and saves through Dataset commands", async ({
  page,
}) => {
  const project = {
    createdAt: "2026-10-07T00:00:00.000Z",
    id: "project-123",
    name: "Design review",
    updatedAt: "2026-10-07T00:00:00.000Z",
  };
  const dataset = {
    id: "dataset-123",
    name: "Load cases",
    version: 1,
    filePath: "/project/.datasets/dataset-123.json",
    records: [
      {
        id: "record-123",
        position: 0,
        sourceKey: "LC-1",
        value: { load: 12.5, metadata: { unit: "kN" } },
      },
      {
        id: "record-456",
        position: 1,
        sourceKey: "LC-2",
        value: { load: 20, active: true },
      },
    ],
  };
  let savedVersion: number | null = null;
  let currentDataset: Omit<typeof dataset, "records"> & {
    records: Array<{
      id: string;
      position: number;
      sourceKey: string;
      value: Record<string, unknown>;
    }>;
  } = dataset;
  await page.route("**/api/projects", async (route) =>
    route.fulfill({ json: [project] }),
  );
  await page.route(`**/api/projects/${project.id}/artifacts`, async (route) =>
    route.fulfill({ json: { artifacts: [] } }),
  );
  await page.route(`**/api/projects/${project.id}/files/index`, async (route) =>
    route.fulfill({
      json: {
        files: [
          { path: dataset.filePath, version: 1, updatedAt: project.updatedAt },
        ],
      },
    }),
  );
  await page.route(`**/api/projects/${project.id}/datasets`, async (route) =>
    route.fulfill({ json: [currentDataset] }),
  );
  await page.route(
    `**/api/projects/${project.id}/datasets/${dataset.id}`,
    async (route) => {
      if (route.request().method() === "PUT") {
        const body = route.request().postDataJSON() as {
          expectedVersion: number;
          records: Array<{
            value: {
              load: number;
              metadata?: { unit: string };
              active?: boolean;
            };
          }>;
        };
        savedVersion = body.expectedVersion;
        currentDataset = {
          ...dataset,
          version: 2,
          records: dataset.records.map((record, index) => ({
            ...record,
            value: body.records[index].value,
          })),
        };
        await route.fulfill({
          json: currentDataset,
        });
        return;
      }
      await route.fulfill({ json: dataset });
    },
  );

  await page.goto("/");
  await page.getByRole("button", { name: "Library" }).click();
  await page.getByRole("button", { name: "Load cases", exact: true }).click();
  const viewer = page.getByRole("region", { name: "Dataset viewer" });
  await expect(viewer).toContainText("LC-1");
  await expect(viewer).toContainText("12.5");
  await expect(
    viewer.getByRole("columnheader", { name: "load" }),
  ).toBeVisible();
  await expect(
    viewer.getByRole("columnheader", { name: "active" }),
  ).toBeVisible();
  await viewer.getByLabel("Filter records in this view").fill("LC-2");
  await expect(viewer.getByRole("row", { name: /LC-1/ })).toHaveCount(0);
  await expect(viewer.getByRole("row", { name: /LC-2/ })).toBeVisible();
  await expect(viewer.getByRole("status")).toContainText(
    "Showing 1 of 2 Records · View filter only",
  );
  await viewer.getByLabel("Filter records in this view").fill("");
  await viewer
    .getByRole("row", { name: /LC-1/ })
    .getByText("Inspect JSON")
    .click();
  await expect(viewer.getByText('"unit": "kN"')).toBeVisible();
  await page.setViewportSize({ width: 390, height: 844 });
  await expect(viewer).toBeVisible();
  expect(
    await page.evaluate(() => document.documentElement.scrollWidth),
  ).toBeLessThanOrEqual(390);
  await viewer.getByRole("button", { name: "Edit Dataset" }).click();
  await viewer.getByLabel("LC-1 value (JSON)").fill('{"load":13}');
  await viewer.getByRole("button", { name: "Save Dataset" }).click();
  await expect.poll(() => savedVersion).toBe(1);
  await expect(viewer).toContainText("Version 2");
  await expect(viewer).toContainText("13");
  await expect(page.getByLabel("Library items")).toContainText("Version 2");
});

test("a Project file is deleted from its Library item action menu after confirmation", async ({
  page,
}) => {
  const project = {
    createdAt: "2026-09-21T00:00:00.000Z",
    id: "project-123",
    name: "Design review",
    updatedAt: "2026-09-21T00:00:00.000Z",
  };
  const path = "/project/test.txt";
  let deleted = false;

  await page.route("**/api/projects", async (route) => {
    await route.fulfill({ json: [project] });
  });
  await page.route(`**/api/projects/${project.id}/artifacts`, async (route) => {
    await route.fulfill({ json: { artifacts: [] } });
  });
  await page.route(
    `**/api/projects/${project.id}/files/index`,
    async (route) => {
      await route.fulfill({
        json: {
          files: deleted
            ? []
            : [{ path, updatedAt: "2026-09-21T00:00:00.000Z", version: 1 }],
        },
      });
    },
  );
  await page.route(
    `**/api/projects/${project.id}/files?path=${encodeURIComponent(path)}`,
    async (route) => {
      expect(route.request().method()).toBe("DELETE");
      deleted = true;
      await route.fulfill({ status: 204 });
    },
  );
  await page.route(`**/api/projects/${project.id}/datasets`, async (route) => {
    await route.fulfill({ json: [] });
  });

  await page.goto("/");
  await page.getByRole("button", { name: "Library" }).click();
  await page.getByRole("button", { name: `${path} actions` }).click();
  await page.getByRole("menuitem", { name: "Delete" }).click();

  const dialog = page.getByRole("dialog", { name: "Confirm deletion" });
  await expect(dialog).toContainText(path);
  await dialog.getByRole("button", { name: "Cancel" }).click();
  await expect(dialog).toBeHidden();
  await expect(page.getByText(path)).toBeVisible();

  await page.getByRole("button", { name: `${path} actions` }).click();
  await page.getByRole("menuitem", { name: "Delete" }).click();
  await dialog.getByRole("button", { name: "Delete" }).click();

  await expect(dialog).toBeHidden();
  await expect(
    page.getByRole("button", { name: `${path} actions` }),
  ).toHaveCount(0);
});

test("an Artifact changed by another Thread stays open until the user reloads it", async ({
  page,
}) => {
  const project = {
    createdAt: "2026-09-21T00:00:00.000Z",
    id: "project-123",
    name: "Design review",
    updatedAt: "2026-09-21T00:00:00.000Z",
  };
  const artifactId = "artifact-123";
  let documentRequests = 0;
  const artifactDocument = (documentVersion: number, threadId: string) => ({
    artifact: {
      documentVersion,
      id: artifactId,
      plugin: { id: "foundation-fixture", version: "0.1.0" },
      provenance: {
        createdBy: { kind: "agentRun", runId: "run-a", threadId: "thread-a" },
        lastChangedBy: { kind: "agentRun", runId: "run-b", threadId },
      },
      relations: [],
      schema: { id: "agent-hub.fixture.status", version: "1" },
      title: "Foundation status",
      type: "agent-hub.fixture.status",
    },
    payload: { status: documentVersion === 1 ? "available" : "unavailable" },
  });

  await page.route("**/api/projects", async (route) => {
    await route.fulfill({ json: [project] });
  });
  await page.route(`**/api/projects/${project.id}/artifacts`, async (route) => {
    await route.fulfill({
      json: {
        artifacts: [
          {
            documentVersion: 1,
            id: artifactId,
            pluginId: "foundation-fixture",
            pluginVersion: "0.1.0",
            title: "Foundation status",
            type: "agent-hub.fixture.status",
          },
        ],
      },
    });
  });
  await page.route(
    `**/api/projects/${project.id}/files/index`,
    async (route) => {
      await route.fulfill({ json: { files: [] } });
    },
  );
  await page.route(`**/api/projects/${project.id}/datasets`, async (route) => {
    await route.fulfill({ json: [] });
  });
  await page.route(
    `**/api/projects/${project.id}/artifacts/${artifactId}`,
    async (route) => {
      documentRequests += 1;
      await route.fulfill({
        json:
          documentRequests <= 2
            ? artifactDocument(1, "thread-a")
            : artifactDocument(2, "thread-b"),
      });
    },
  );
  await page.route(
    `**/api/projects/${project.id}/artifacts/${artifactId}/app`,
    async (route) => {
      await route.fulfill({ status: 404 });
    },
  );

  await page.goto("/");
  await page.getByRole("button", { name: "Library" }).click();
  await page
    .getByRole("button", { exact: true, name: "Foundation status" })
    .click();
  const artifactPreview = page.locator("aside").last();
  await expect(artifactPreview.getByText("Version 1")).toBeVisible();

  const changedDocumentResponse = page.waitForResponse(
    `**/api/projects/${project.id}/artifacts/${artifactId}`,
  );
  await page.evaluate(() => window.dispatchEvent(new Event("focus")));
  await changedDocumentResponse;

  await expect(
    page.getByText("This Artifact changed in another Thread."),
  ).toBeVisible();
  await expect(artifactPreview.getByText("Version 1")).toBeVisible();
  await page.getByRole("button", { name: "Reload" }).click();
  await expect(artifactPreview.getByText("Version 2")).toBeVisible();
  await expect(
    page.getByText("This Artifact changed in another Thread."),
  ).toBeHidden();
});

test("an Artifact App receives its saved tool result through the MCP App bridge", async ({
  page,
}) => {
  const project = {
    createdAt: "2026-09-22T00:00:00.000Z",
    id: "project-123",
    name: "Design review",
    updatedAt: "2026-09-22T00:00:00.000Z",
  };
  const artifactId = "artifact-123";
  const artifact = {
    artifact: {
      documentVersion: 1,
      id: artifactId,
      plugin: { id: "reference-calculation", version: "0.1.0" },
      provenance: {
        createdBy: { kind: "agentRun", runId: "run-a", threadId: "thread-a" },
        lastChangedBy: {
          kind: "agentRun",
          runId: "run-a",
          threadId: "thread-a",
        },
      },
      relations: [],
      schema: { id: "agent-hub.plugin.tool-result", version: "1" },
      title: "Cantilever moment",
      type: "agent-hub.reference-calculation.calculate-cantilever-tip-load",
    },
    payload: {
      input: { length_m: 6.5, tip_load_kn: 12.5 },
      output: {
        calculation: { maximumMoment: { unit: "kN·m", value: 81.25 } },
      },
    },
  };
  const app = readFileSync(
    "../../plugins/reference-calculation/app/cantilever-view.html",
    "utf8",
  );

  await page.route("**/api/projects", async (route) => {
    await route.fulfill({ json: [project] });
  });
  await page.route(`**/api/projects/${project.id}/artifacts`, async (route) => {
    await route.fulfill({
      json: {
        artifacts: [
          {
            documentVersion: 1,
            id: artifactId,
            pluginId: "reference-calculation",
            pluginVersion: "0.1.0",
            title: artifact.artifact.title,
            type: artifact.artifact.type,
          },
        ],
      },
    });
  });
  await page.route(
    `**/api/projects/${project.id}/files/index`,
    async (route) => {
      await route.fulfill({ json: { files: [] } });
    },
  );
  await page.route(`**/api/projects/${project.id}/datasets`, async (route) => {
    await route.fulfill({ json: [] });
  });
  await page.route(
    `**/api/projects/${project.id}/artifacts/${artifactId}`,
    async (route) => {
      await route.fulfill({ json: artifact });
    },
  );
  await page.route(
    `**/api/projects/${project.id}/artifacts/${artifactId}/app`,
    async (route) => {
      await route.fulfill({ body: app, contentType: "text/html" });
    },
  );

  await page.goto("/");
  await page.getByRole("button", { name: "Library" }).click();
  await page
    .getByRole("button", { exact: true, name: artifact.artifact.title })
    .click();

  const preview = page.frameLocator('iframe[title="Artifact App"]');
  await expect(preview.locator("#length")).toHaveValue("6.5");
  await expect(preview.locator("#load")).toHaveValue("12.5");
  await expect(preview.locator("#result")).toHaveText("81.3 kN·m");
});

test("the foundation fixture App renders a portable status Artifact", async ({
  page,
}) => {
  const project = {
    createdAt: "2026-09-22T00:00:00.000Z",
    id: "project-fixture",
    name: "Foundation",
    updatedAt: "2026-09-22T00:00:00.000Z",
  };
  const artifactId = "artifact-fixture";
  const artifact = {
    artifact: {
      documentVersion: 1,
      id: artifactId,
      plugin: { id: "foundation-fixture", version: "0.1.0" },
      provenance: {
        createdBy: { kind: "agentRun", runId: "run-a", threadId: "thread-a" },
        lastChangedBy: {
          kind: "agentRun",
          runId: "run-a",
          threadId: "thread-a",
        },
      },
      relations: [],
      schema: { id: "agent-hub.fixture.status", version: "1.0" },
      title: "Bridge status",
      type: "agent-hub.fixture.status",
    },
    payload: { status: "available" },
  };
  const app = readFileSync(
    "../../plugins/test-fixture/app/foundation-status-view.html",
    "utf8",
  );

  await page.route("**/api/projects", async (route) => {
    await route.fulfill({ json: [project] });
  });
  await page.route(`**/api/projects/${project.id}/artifacts`, async (route) => {
    await route.fulfill({
      json: {
        artifacts: [
          {
            documentVersion: 1,
            id: artifactId,
            pluginId: "foundation-fixture",
            pluginVersion: "0.1.0",
            title: artifact.artifact.title,
            type: artifact.artifact.type,
          },
        ],
      },
    });
  });
  await page.route(
    `**/api/projects/${project.id}/files/index`,
    async (route) => {
      await route.fulfill({ json: { files: [] } });
    },
  );
  await page.route(`**/api/projects/${project.id}/datasets`, async (route) => {
    await route.fulfill({ json: [] });
  });
  await page.route(
    `**/api/projects/${project.id}/artifacts/${artifactId}`,
    async (route) => {
      await route.fulfill({ json: artifact });
    },
  );
  await page.route(
    `**/api/projects/${project.id}/artifacts/${artifactId}/app`,
    async (route) => {
      await route.fulfill({ body: app, contentType: "text/html" });
    },
  );

  await page.goto("/");
  await page.getByRole("button", { name: "Library" }).click();
  await page
    .getByRole("button", { exact: true, name: "Bridge status" })
    .click();
  await expect(
    page.frameLocator('iframe[title="Artifact App"]').locator("#status"),
  ).toHaveText("available");
});

test("selection planning and runs reach the Project API through the browser", async ({
  request,
}) => {
  for (const endpoint of [
    "output-selection-plan",
    "output-selection-runs",
    "result-set-selection-plan",
    "result-set-selection-runs",
  ]) {
    const response = await request.post(
      `/api/projects/missing/transforms/missing/${endpoint}`,
      { data: {} },
    );
    expect(response.status()).toBe(422);
    expect(response.headers()["content-type"]).toContain("application/json");
  }
});

test("a Dataset Transform runs once over ordered Records", async ({ page }) => {
  const project = {
    id: "project-selection",
    name: "Selection review",
    createdAt: "2026-10-08T00:00:00Z",
    updatedAt: "2026-10-08T00:00:00Z",
  };
  const definition = {
    id: "transform-1",
    name: "Aggregate values",
    source: "def transform(inputs, parameters): pass",
    inputSelectors: { items: "/selection/values" },
    outputSchema: { type: "object" },
    runtime: "pyodide",
    packageHash: "abc",
    revision: 3,
  };
  const selection = {
    sourceKind: "dataset",
    datasetId: "dataset-1",
    datasetVersion: 2,
    datasetPath: "/.datasets/dataset-1.json",
    recordIds: ["record-1", "record-2"],
    records: [
      { id: "record-1", value: { score: 1 } },
      { id: "record-2", value: { score: 3 } },
    ],
    rule: {},
    selectedCount: 2,
    invocationCount: 1,
  };
  const writes: Array<Record<string, unknown>> = [];
  await page.route("**/api/projects", (route) =>
    route.fulfill({ json: [project] }),
  );
  await page.route(`**/api/projects/${project.id}/threads`, (route) =>
    route.fulfill({ json: [] }),
  );
  await page.route(`**/api/projects/${project.id}/datasets`, (route) =>
    route.fulfill({
      json: [{ id: "dataset-1", name: "Measurements", version: 2 }],
    }),
  );
  await page.route(`**/api/projects/${project.id}/transforms`, (route) =>
    route.fulfill({ json: [definition] }),
  );
  await page.route(
    `**/api/projects/${project.id}/transforms/runs?**`,
    (route) => route.fulfill({ json: { items: [], nextOffset: null } }),
  );
  await page.route(
    `**/api/projects/${project.id}/transforms/${definition.id}/dataset-runs/plan`,
    (route) => {
      writes.push(route.request().postDataJSON() as Record<string, unknown>);
      return route.fulfill({
        json: {
          datasetId: "dataset-1",
          datasetVersion: 2,
          transformDefinitionId: definition.id,
          transformRevision: 3,
          recordIds: selection.recordIds,
          mode: (route.request().postDataJSON() as { mode: string }).mode,
          invocationCount: 1,
          outputKind: "transformRun",
        },
      });
    },
  );
  await page.route(
    `**/api/projects/${project.id}/transforms/${definition.id}/dataset-runs`,
    (route) => {
      writes.push(route.request().postDataJSON() as Record<string, unknown>);
      return route.fulfill({
        status: 201,
        json: {
          id: "run-selection",
          status: "succeeded",
          outputKind: "transformRun",
        },
      });
    },
  );
  await page.route(
    `**/api/projects/${project.id}/transforms/runs/run-selection`,
    (route) =>
      route.fulfill({
        json: {
          id: "run-selection",
          definitionId: definition.id,
          status: "succeeded",
          definitionSnapshot: {
            name: definition.name,
            source: definition.source,
            input_selectors: definition.inputSelectors,
            revision: 3,
            selection,
          },
          inputs: { items: [{ score: 1 }, { score: 3 }] },
          parameters: {},
          inputHash: "inputhash",
          sourceHash: "sourcehash",
          packageHash: "abc",
          runtime: "pyodide",
          output: { total: 4 },
          outputManifest: {},
          error: null,
          initiation: {
            kind: "directUser",
            approval: "notRequired",
            threadId: null,
            agentRunId: null,
          },
          limits: {},
          createdAt: "2026-10-08T00:00:00Z",
        },
      }),
  );
  await page.goto("/");
  await page
    .getByRole("navigation", { name: "Project views" })
    .getByRole("button", { name: "Operations" })
    .click();
  await page
    .getByRole("navigation", { name: "Operation types" })
    .getByRole("button", { name: "Functions" })
    .click();
  await page.getByLabel("Input source").selectOption("dataset");
  await page
    .getByRole("combobox", { name: "Dataset", exact: true })
    .selectOption("dataset-1");
  await page.getByRole("button", { name: "Review Run" }).click();
  await expect(
    page.getByRole("region", { name: "Dataset Run plan" }),
  ).toContainText("2 Records · 1 invocation");
  await page.getByRole("button", { name: "Start Run" }).click();
  await expect(
    page.getByRole("article", { name: "Run dataflow" }),
  ).toContainText("Dataset dataset- · v2 · 2 Records");
  expect(writes).toHaveLength(2);
  expect(writes[0]).toMatchObject({
    datasetId: "dataset-1",
    mode: "dataset",
    parameters: {},
  });
  expect(writes[1]).toMatchObject({
    datasetId: "dataset-1",
    mode: "dataset",
    expectedDatasetVersion: 2,
    expectedTransformRevision: 3,
  });
});

test("a retained Transform output selection shows its source and selected values", async ({
  page,
}) => {
  const project = {
    id: "project-output-selection",
    name: "Output selection",
    createdAt: "2026-10-08T00:00:00Z",
    updatedAt: "2026-10-08T00:00:00Z",
  };
  const definition = {
    id: "transform-consumer",
    name: "Consume values",
    source: "def transform(inputs, parameters): pass",
    inputSelectors: { items: "/selection/values" },
    outputSchema: { type: "object" },
    runtime: "pyodide",
    packageHash: "abc",
    revision: 3,
  };
  const upstream = {
    id: "transform-source-run",
    definitionId: "transform-producer",
    status: "succeeded",
    definitionSnapshot: { name: "Produce values", source: "", revision: 1 },
    inputs: {},
    parameters: {},
    inputHash: "inputhash",
    sourceHash: "sourcehash",
    packageHash: "abc",
    runtime: "pyodide",
    output: { items: [{ score: 1 }, { score: 3 }] },
    outputManifest: {},
    error: null,
    initiation: { kind: "directUser", approval: "notRequired" },
    limits: {},
    createdAt: "2026-10-08T00:00:00Z",
  };
  const selection = {
    sourceKind: "transformRun",
    sourceRunId: upstream.id,
    outputPath: "/items",
    outputHash: "outputhash",
    positions: [1],
    values: [{ score: 3 }],
    rule: { sortPath: "/score", limit: 1 },
    selectedCount: 1,
  };
  const writes: Array<Record<string, unknown>> = [];
  await page.route("**/api/projects", (route) =>
    route.fulfill({ json: [project] }),
  );
  await page.route(`**/api/projects/${project.id}/threads`, (route) =>
    route.fulfill({ json: [] }),
  );
  await page.route(`**/api/projects/${project.id}/datasets`, (route) =>
    route.fulfill({ json: [] }),
  );
  await page.route(`**/api/projects/${project.id}/transforms`, (route) =>
    route.fulfill({ json: [definition] }),
  );
  await page.route(
    `**/api/projects/${project.id}/transforms/runs?**`,
    (route) => route.fulfill({ json: { items: [upstream], nextOffset: null } }),
  );
  await page.route(
    `**/api/projects/${project.id}/transforms/${definition.id}/output-selection-plan`,
    (route) => {
      writes.push(route.request().postDataJSON() as Record<string, unknown>);
      return route.fulfill({
        json: {
          selection,
          selectedCount: 1,
          invocationCount: 1,
          outputLocation: "Function Run output",
        },
      });
    },
  );
  await page.route(
    `**/api/projects/${project.id}/transforms/${definition.id}/output-selection-runs`,
    (route) => {
      writes.push(route.request().postDataJSON() as Record<string, unknown>);
      return route.fulfill({
        status: 201,
        json: {
          ...upstream,
          id: "transform-downstream-run",
          definitionId: definition.id,
          definitionSnapshot: { ...definition, selection },
          inputs: { items: [{ score: 3 }] },
          output: { total: 3 },
        },
      });
    },
  );
  await page.goto("/");
  await page
    .getByRole("navigation", { name: "Project views" })
    .getByRole("button", { name: "Operations" })
    .click();
  await page
    .getByRole("navigation", { name: "Operation types" })
    .getByRole("button", { name: "Functions" })
    .click();
  await page.getByLabel("Input source").selectOption("output");
  await page
    .getByRole("combobox", { name: "Function Run", exact: true })
    .selectOption(upstream.id);
  await page.getByLabel("Output path (JSON Pointer)").fill("/items");
  await page.getByLabel("Sort path (JSON Pointer, optional)").fill("/score");
  await page.getByLabel("Maximum records (optional)").fill("1");
  await page.getByRole("button", { name: "Review selection" }).click();
  await expect(
    page.getByRole("region", { name: "Selection plan" }),
  ).toContainText("Function Run transfor → Function Run output");
  await page.getByRole("button", { name: "Start selected Run" }).click();
  await expect(
    page.getByRole("article", { name: "Run dataflow" }),
  ).toContainText("Function Run transfor · 1 values");
  expect(writes).toHaveLength(2);
  expect(writes[0]).toMatchObject({
    sourceRunId: upstream.id,
    outputPath: "/items",
    expectedDefinitionRevision: 3,
    sortPath: "/score",
    limit: 1,
  });
  expect(writes[1]).toEqual(writes[0]);
});

test("a Batch Result Set selection keeps row lineage in the Function Run", async ({
  page,
}) => {
  const project = {
    id: "project-result-selection",
    name: "Result selection",
    createdAt: "2026-10-08T00:00:00Z",
    updatedAt: "2026-10-08T00:00:00Z",
  };
  const definition = {
    id: "transform-consumer",
    name: "Consume results",
    source: "def transform(inputs, parameters): pass",
    inputSelectors: { rows: "/selection/rows" },
    outputSchema: { type: "object" },
    runtime: "pyodide",
    packageHash: "abc",
    revision: 3,
  };
  const selection = {
    sourceKind: "resultSet",
    batchRunId: "batch-source-run",
    outputPath: "/score",
    selectedCount: 1,
    selectedRecords: [
      {
        resultRecordId: "batch-source-run:row-1",
        datasetRecordId: "row-1",
        sourceKey: "beam-A",
        position: 0,
        input: { beam: "A" },
        value: 5,
      },
    ],
    rule: { limit: 1 },
  };
  const retained = {
    id: "transform-result-run",
    definitionId: definition.id,
    status: "succeeded",
    definitionSnapshot: { ...definition, selection },
    inputs: {
      rows: [
        {
          resultRecordId: "batch-source-run:row-1",
          datasetRecordId: "row-1",
          sourceKey: "beam-A",
          position: 0,
          input: { beam: "A" },
          value: 5,
        },
      ],
    },
    parameters: {},
    inputHash: "inputhash",
    sourceHash: "sourcehash",
    packageHash: "abc",
    runtime: "pyodide",
    output: { total: 5 },
    outputManifest: {},
    error: null,
    initiation: { kind: "directUser", approval: "notRequired" },
    limits: {},
    createdAt: "2026-10-08T00:00:00Z",
  };
  const writes: Array<Record<string, unknown>> = [];
  await page.route("**/api/projects", (route) =>
    route.fulfill({ json: [project] }),
  );
  await page.route(`**/api/projects/${project.id}/threads`, (route) =>
    route.fulfill({ json: [] }),
  );
  await page.route(`**/api/projects/${project.id}/datasets`, (route) =>
    route.fulfill({ json: [] }),
  );
  await page.route(`**/api/projects/${project.id}/transforms`, (route) =>
    route.fulfill({ json: [definition] }),
  );
  await page.route(
    `**/api/projects/${project.id}/transforms/runs?**`,
    (route) => route.fulfill({ json: { items: [], nextOffset: null } }),
  );
  await page.route(`**/api/projects/${project.id}/batch-runs?**`, (route) =>
    route.fulfill({
      json: {
        items: [
          {
            id: "batch-source-run",
            definitionId: "batch-definition-1",
            definitionName: "Source results",
            status: "partial",
            archivedAt: null,
            createdAt: "2026-10-08T00:00:00Z",
            updatedAt: "2026-10-08T00:00:00Z",
            initiatorSubject: "sam",
            initiation: { kind: "directUser", approval: "notRequired" },
            recordCount: 2,
            succeededCount: 1,
            failedCount: 1,
          },
        ],
        nextOffset: null,
      },
    }),
  );
  await page.route(
    `**/api/projects/${project.id}/transforms/${definition.id}/result-set-selection-plan`,
    (route) => {
      writes.push(route.request().postDataJSON() as Record<string, unknown>);
      return route.fulfill({
        json: {
          selection,
          selectedCount: 1,
          invocationCount: 1,
          outputLocation: "Function Run output",
        },
      });
    },
  );
  await page.route(
    `**/api/projects/${project.id}/transforms/${definition.id}/result-set-selection-runs`,
    (route) => {
      writes.push(route.request().postDataJSON() as Record<string, unknown>);
      return route.fulfill({
        status: 201,
        json: { id: retained.id, status: "succeeded" },
      });
    },
  );
  await page.route(
    `**/api/projects/${project.id}/transforms/runs/${retained.id}`,
    (route) => route.fulfill({ json: retained }),
  );
  await page.goto("/");
  await page
    .getByRole("navigation", { name: "Project views" })
    .getByRole("button", { name: "Operations" })
    .click();
  await page
    .getByRole("navigation", { name: "Operation types" })
    .getByRole("button", { name: "Functions" })
    .click();
  await page.getByLabel("Input source").selectOption("resultSet");
  await page
    .getByRole("combobox", { name: "Batch Run Result Set" })
    .selectOption("batch-source-run");
  await page.getByLabel(/Value path in each result/).fill("/score");
  await page.getByLabel("Maximum records (optional)").fill("1");
  await page.getByRole("button", { name: "Review selection" }).click();
  await expect(
    page.getByRole("region", { name: "Selection plan" }),
  ).toContainText("Batch Result Set batch-so → Function Run output");
  await page.getByText("Selected source values").click();
  await expect(
    page.getByRole("region", { name: "Selection plan" }),
  ).toContainText('"resultRecordId": "batch-source-run:row-1"');
  await expect(
    page.getByRole("region", { name: "Selection plan" }),
  ).toContainText('"sourceKey": "beam-A"');
  await page.getByRole("button", { name: "Start selected Run" }).click();
  await expect(
    page.getByRole("article", { name: "Run dataflow" }),
  ).toContainText("Batch Result Set batch-so · 1 values");
  expect(writes).toHaveLength(2);
  expect(writes[0]).toMatchObject({
    sourceRunId: "batch-source-run",
    outputPath: "/score",
    expectedDefinitionRevision: 3,
    limit: 1,
  });
  expect(writes[1]).toEqual(writes[0]);
});

test("a retained MCP output selection is reviewable and traceable", async ({
  page,
}) => {
  const project = {
    id: "project-mcp-selection",
    name: "MCP selection",
    createdAt: "2026-10-08T00:00:00Z",
    updatedAt: "2026-10-08T00:00:00Z",
  };
  const definition = {
    id: "transform-mcp-consumer",
    name: "Consume MCP output",
    source: "def transform(inputs, parameters): pass",
    inputSelectors: { items: "/selection/values" },
    outputSchema: { type: "object" },
    runtime: "pyodide",
    packageHash: "abc",
    revision: 3,
  };
  const selection = {
    sourceKind: "mcpToolResult",
    artifactId: "artifact-mcp-output",
    artifactVersion: 2,
    pluginId: "fixture",
    toolName: "measure",
    outputPath: "/measurements",
    selectedValues: [{ position: 1, value: { name: "B", score: 4 } }],
    rule: { limit: 1 },
    selectedCount: 1,
  };
  const retained = {
    id: "transform-mcp-run",
    definitionId: definition.id,
    status: "succeeded",
    definitionSnapshot: { ...definition, selection },
    inputs: { items: [{ name: "B", score: 4 }] },
    parameters: {},
    inputHash: "inputhash",
    sourceHash: "sourcehash",
    packageHash: "abc",
    runtime: "pyodide",
    output: { count: 1 },
    outputManifest: {},
    error: null,
    initiation: { kind: "directUser", approval: "notRequired" },
    limits: {},
    createdAt: "2026-10-08T00:00:00Z",
  };
  const writes: Array<Record<string, unknown>> = [];
  await page.route("**/api/projects", (route) =>
    route.fulfill({ json: [project] }),
  );
  await page.route(`**/api/projects/${project.id}/threads`, (route) =>
    route.fulfill({ json: [] }),
  );
  await page.route(`**/api/projects/${project.id}/datasets`, (route) =>
    route.fulfill({ json: [] }),
  );
  await page.route(`**/api/projects/${project.id}/transforms`, (route) =>
    route.fulfill({ json: [definition] }),
  );
  await page.route(
    `**/api/projects/${project.id}/transforms/runs?**`,
    (route) => route.fulfill({ json: { items: [], nextOffset: null } }),
  );
  await page.route(`**/api/projects/${project.id}/artifacts`, (route) =>
    route.fulfill({
      json: {
        artifacts: [
          {
            id: selection.artifactId,
            title: "fixture: measure",
            type: "fixture.measure",
            schemaId: "agent-hub.tool-result-snapshot",
            documentVersion: 2,
          },
          {
            id: "unrelated-artifact",
            title: "Project note",
            type: "note",
            schemaId: "agent-hub.note",
            documentVersion: 1,
          },
        ],
      },
    }),
  );
  await page.route(
    `**/api/projects/${project.id}/transforms/${definition.id}/artifact-selection-plan`,
    (route) => {
      writes.push(route.request().postDataJSON() as Record<string, unknown>);
      return route.fulfill({
        json: {
          selection,
          selectedCount: 1,
          invocationCount: 1,
          outputLocation: "Function Run output",
        },
      });
    },
  );
  await page.route(
    `**/api/projects/${project.id}/transforms/${definition.id}/artifact-selection-runs`,
    (route) => {
      writes.push(route.request().postDataJSON() as Record<string, unknown>);
      return route.fulfill({
        status: 201,
        json: { id: retained.id, status: "succeeded" },
      });
    },
  );
  await page.route(
    `**/api/projects/${project.id}/transforms/runs/${retained.id}`,
    (route) => route.fulfill({ json: retained }),
  );
  await page.goto("/");
  await page
    .getByRole("navigation", { name: "Project views" })
    .getByRole("button", { name: "Operations" })
    .click();
  await page
    .getByRole("navigation", { name: "Operation types" })
    .getByRole("button", { name: "Functions" })
    .click();
  await page.getByLabel("Input source").selectOption("artifact");
  await expect(
    page.getByRole("combobox", { name: "MCP Tool Result Artifact" }),
  ).not.toContainText("Project note");
  await page
    .getByRole("combobox", { name: "MCP Tool Result Artifact" })
    .selectOption(selection.artifactId);
  await page.getByLabel(/Values path in MCP output/).fill("/measurements");
  await page.getByLabel("Maximum records (optional)").fill("1");
  await page.getByRole("button", { name: "Review selection" }).click();
  await expect(
    page.getByRole("region", { name: "Selection plan" }),
  ).toContainText("MCP Tool Result artifact · v2 → Function Run output");
  await page.getByRole("button", { name: "Start selected Run" }).click();
  await expect(
    page.getByRole("article", { name: "Run dataflow" }),
  ).toContainText("MCP Tool Result artifact · v2 · 1 values");
  expect(writes).toHaveLength(2);
  expect(writes[0]).toMatchObject({
    artifactId: selection.artifactId,
    expectedArtifactVersion: 2,
    outputPath: "/measurements",
    expectedDefinitionRevision: 3,
    limit: 1,
  });
  expect(writes[1]).toEqual(writes[0]);
});

test.describe("at phone width", () => {
  test.use({ viewport: { height: 844, width: 390 } });

  test("Project controls fit without horizontal overflow", async ({ page }) => {
    await page.goto("/");
    await page.getByLabel("Selected Project").waitFor({ state: "visible" });

    const headerWidth = await page.locator("header").evaluate((element) => ({
      clientWidth: element.clientWidth,
      scrollWidth: element.scrollWidth,
    }));
    expect(headerWidth.scrollWidth).toBeLessThanOrEqual(
      headerWidth.clientWidth,
    );
    await expect(page.getByLabel("Selected Project")).toBeInViewport();
    await expect(
      page.getByRole("button", { name: "Open Project navigation" }),
    ).toBeInViewport();
  });

  test("Project navigation exposes Thread and activity controls", async ({
    page,
  }) => {
    const project = {
      createdAt: "2026-09-16T00:00:00.000Z",
      id: "project-123",
      name: "Design review",
      updatedAt: "2026-09-16T00:00:00.000Z",
    };
    const thread = {
      createdAt: "2026-09-16T00:00:00.000Z",
      id: "thread-123",
      projectId: project.id,
      title: "New Thread 1",
      updatedAt: "2026-09-16T00:00:00.000Z",
    };

    await page.route("**/api/projects", async (route) => {
      await route.fulfill({ json: [project] });
    });
    await page.route(`**/api/projects/${project.id}/threads`, async (route) => {
      if (route.request().method() === "POST") {
        await route.fulfill({ json: thread, status: 201 });
        return;
      }
      await route.fulfill({ json: [] });
    });
    await page.route(
      `**/api/projects/${project.id}/artifacts`,
      async (route) => {
        await route.fulfill({ json: { artifacts: [] } });
      },
    );
    await page.route(
      `**/api/projects/${project.id}/files/index`,
      async (route) => {
        await route.fulfill({
          json: {
            files: [
              {
                path: "/project/notes/check.md",
                updatedAt: "2026-09-16T00:00:00.000Z",
                version: 1,
              },
            ],
          },
        });
      },
    );
    await page.route(
      `**/api/projects/${project.id}/files?**`,
      async (route) => {
        await route.fulfill({
          json: {
            content: "# Preview\n",
            path: "/project/notes/check.md",
            version: 1,
          },
        });
      },
    );
    await page.route(
      `**/api/projects/${project.id}/datasets`,
      async (route) => {
        await route.fulfill({ json: [] });
      },
    );

    await page.goto("/");
    await expect(page.getByLabel("Selected Project")).toHaveValue(project.id);

    await page.getByRole("button", { name: "Open Project navigation" }).click();
    const drawer = page.getByRole("dialog", { name: "Project navigation" });
    await expect(drawer).toBeVisible();
    await drawer.getByRole("button", { name: "+ New Thread" }).click();
    await expect(
      drawer.getByRole("button", { name: "New Thread 1", exact: true }),
    ).toBeVisible();

    await drawer.getByRole("button", { name: "Library" }).click();
    await drawer
      .getByRole("button", {
        exact: true,
        name: "/project/notes/check.md",
      })
      .click();
    await expect(drawer).toBeHidden();
    await expect(page.getByText("# Preview")).toBeVisible();
  });

  test("Library Dataset and Batch Definition controls retain their dark, touch-ready treatment", async ({
    page,
  }) => {
    const project = {
      createdAt: "2026-09-16T00:00:00.000Z",
      id: "project-123",
      name: "Design review",
      updatedAt: "2026-09-16T00:00:00.000Z",
    };
    const dataset = {
      id: "dataset-123",
      name: "Load cases",
      version: 1,
      filePath: "/project/.datasets/dataset-123.json",
      records: [{ id: "record-123", sourceKey: "LC-1" }],
    };
    const definition = {
      datasetAvailable: true,
      datasetId: dataset.id,
      id: "definition-123",
      name: "Cantilever check",
      pluginId: "reference-calculation",
      toolName: "calculate_cantilever_tip_load",
    };

    await page.route("**/api/projects", async (route) => {
      await route.fulfill({ json: [project] });
    });
    await page.route(`**/api/projects/${project.id}/threads`, async (route) => {
      await route.fulfill({ json: [] });
    });
    await page.route(
      `**/api/projects/${project.id}/artifacts`,
      async (route) => {
        await route.fulfill({ json: { artifacts: [] } });
      },
    );
    await page.route(
      `**/api/projects/${project.id}/files/index`,
      async (route) => {
        await route.fulfill({
          json: {
            files: [
              {
                path: dataset.filePath,
                version: 1,
                updatedAt: project.updatedAt,
              },
            ],
          },
        });
      },
    );
    await page.route(
      `**/api/projects/${project.id}/datasets`,
      async (route) => {
        await route.fulfill({ json: [dataset] });
      },
    );
    await page.route(
      `**/api/projects/${project.id}/batch-definitions`,
      async (route) => {
        await route.fulfill({ json: [definition] });
      },
    );

    await page.goto("/");
    await page.getByRole("button", { name: "Open Project navigation" }).click();
    const drawer = page.getByRole("dialog", { name: "Project navigation" });

    await drawer.getByRole("button", { name: "Library" }).click();
    await expect(drawer.getByText("Load cases")).toBeVisible();
    await expect(
      drawer.getByRole("button", { name: "Load cases actions" }),
    ).toBeVisible();

    await drawer.getByRole("button", { name: "Operations" }).click();
    await drawer
      .getByRole("navigation", { name: "Operation types" })
      .getByRole("button", { name: "Batch Definitions" })
      .click();
    const recordSelector = drawer.getByLabel("Cantilever check Dataset Record");
    await expect(recordSelector).toBeVisible();
    await expect(recordSelector).toHaveCSS(
      "background-color",
      "rgb(27, 33, 26)",
    );
    await expect(recordSelector).toHaveCSS("color", "rgb(251, 253, 246)");
    const runAllBounds = await drawer
      .getByRole("button", { name: "Run all records" })
      .boundingBox();
    const selectorBounds = await recordSelector.boundingBox();
    expect(runAllBounds).not.toBeNull();
    expect(selectorBounds).not.toBeNull();
    expect(selectorBounds!.y).toBeGreaterThan(
      runAllBounds!.y + runAllBounds!.height,
    );
    expect(selectorBounds!.width).toBeGreaterThan(200);
  });
});

test("approving a tool call resumes through the AG-UI transport contract", async ({
  page,
}) => {
  const project = {
    createdAt: "2026-09-16T00:00:00.000Z",
    id: "project-123",
    name: "Design review",
    updatedAt: "2026-09-16T00:00:00.000Z",
  };
  const thread = {
    createdAt: "2026-09-16T00:00:00.000Z",
    id: "thread-123",
    projectId: project.id,
    title: "New Thread 1",
    updatedAt: "2026-09-16T00:00:00.000Z",
  };
  const resumeRequests: unknown[] = [];

  await page.route(
    `**/api/projects/${project.id}/threads/${thread.id}/agent`,
    async (route) => {
      const input = route.request().postDataJSON() as {
        resume?: unknown[];
        runId: string;
      };
      if (input.resume) {
        resumeRequests.push(input.resume);
        await route.fulfill({
          contentType: "text/event-stream",
          body: sse([
            { type: "RUN_STARTED", threadId: thread.id, runId: input.runId },
            {
              type: "TEXT_MESSAGE_START",
              messageId: "assistant-123",
              role: "assistant",
            },
            {
              type: "TEXT_MESSAGE_CONTENT",
              messageId: "assistant-123",
              delta: "Created [the file](sandbox:/project/example.md).",
            },
            { type: "TEXT_MESSAGE_END", messageId: "assistant-123" },
            {
              type: "RUN_FINISHED",
              threadId: thread.id,
              runId: input.runId,
              outcome: { type: "success" },
            },
          ]),
        });
        return;
      }
      await route.fulfill({
        contentType: "text/event-stream",
        body: sse([
          { type: "RUN_STARTED", threadId: thread.id, runId: input.runId },
          {
            type: "TOOL_CALL_START",
            toolCallId: "tool-123",
            toolCallName: "write_file",
          },
          {
            type: "TOOL_CALL_ARGS",
            toolCallId: "tool-123",
            delta: '{"file_path":"/project/example.md"}',
          },
          { type: "TOOL_CALL_END", toolCallId: "tool-123" },
          {
            type: "RUN_FINISHED",
            threadId: thread.id,
            runId: input.runId,
            outcome: {
              type: "interrupt",
              interrupts: [
                {
                  id: "interrupt-123",
                  reason: "tool_call",
                  toolCallId: "tool-123",
                },
              ],
            },
          },
        ]),
      });
    },
  );
  await page.route("**/api/projects", async (route) => {
    await route.fulfill({ json: [project] });
  });
  await page.route("**/api/projects/**", async (route) => {
    const url = new URL(route.request().url());
    if (url.pathname.endsWith("/agent")) {
      await route.fallback();
      return;
    }
    if (url.pathname === "/api/projects") {
      await route.fulfill({ json: [project] });
      return;
    }
    if (url.pathname.endsWith("/threads")) {
      await route.fulfill({ json: [thread] });
      return;
    }
    if (url.pathname.endsWith("/history")) {
      await route.fulfill({ json: { interrupts: [], messages: [] } });
      return;
    }
    if (url.pathname.endsWith("/runs")) {
      await route.fulfill({ json: [] });
      return;
    }
    if (url.pathname.endsWith("/files")) {
      await route.fulfill({
        json: {
          content: "# Example\n",
          path: "/project/example.md",
          version: 1,
        },
      });
      return;
    }
    await route.fulfill({ json: {} });
  });

  await page.goto("/");
  await page.getByLabel("Message Agent Hub").fill("Create the file");
  await page.getByRole("button", { name: "Send" }).click();
  await expect(page.getByText("Approve Project File change")).toBeVisible();
  await expect(page.getByText("write_file", { exact: true })).toBeHidden();
  await page.getByRole("button", { name: "Approve" }).click();
  await expect(page.getByText("write_file", { exact: true })).toBeHidden();

  await expect
    .poll(() => resumeRequests)
    .toEqual([
      [
        {
          interruptId: "interrupt-123",
          payload: { approved: true },
          status: "resolved",
        },
      ],
    ]);
  await page.getByRole("button", { name: "the file" }).click();
  await expect(page.getByText("# Example")).toBeVisible();
});

test("pending edit_file shows a diff and proposed file in the right preview", async ({
  page,
}) => {
  const project = {
    createdAt: "2026-09-16T00:00:00.000Z",
    id: "project-edit-preview",
    name: "Design review",
    updatedAt: "2026-09-16T00:00:00.000Z",
  };
  const thread = {
    createdAt: "2026-09-16T00:00:00.000Z",
    id: "thread-edit-preview",
    projectId: project.id,
    title: "New Thread 1",
    updatedAt: "2026-09-16T00:00:00.000Z",
  };
  await page.route("**/api/projects", (route) =>
    route.fulfill({ json: [project] }),
  );
  await page.route(
    `**/api/projects/${project.id}/threads/${thread.id}/agent`,
    async (route) => {
      const input = route.request().postDataJSON() as { runId: string };
      await route.fulfill({
        contentType: "text/event-stream",
        body: sse([
          { type: "RUN_STARTED", threadId: thread.id, runId: input.runId },
          {
            type: "TOOL_CALL_START",
            toolCallId: "tool-edit",
            toolCallName: "edit_file",
          },
          {
            type: "TOOL_CALL_ARGS",
            toolCallId: "tool-edit",
            delta: JSON.stringify({
              file_path: "/project/check.md",
              old_string: "# Original",
              new_string: "# Revised",
            }),
          },
          { type: "TOOL_CALL_END", toolCallId: "tool-edit" },
          {
            type: "RUN_FINISHED",
            threadId: thread.id,
            runId: input.runId,
            outcome: {
              type: "interrupt",
              interrupts: [
                {
                  id: "interrupt-edit",
                  reason: "tool_call",
                  toolCallId: "tool-edit",
                },
              ],
            },
          },
        ]),
      });
    },
  );
  await page.route("**/api/projects/**", async (route) => {
    const path = new URL(route.request().url()).pathname;
    if (path.endsWith("/agent")) return route.fallback();
    if (path.endsWith("/threads")) return route.fulfill({ json: [thread] });
    if (path.endsWith("/history"))
      return route.fulfill({
        json: { approvals: [], interrupts: [], messages: [] },
      });
    if (path.endsWith("/runs")) return route.fulfill({ json: [] });
    if (path.endsWith("/files"))
      return route.fulfill({
        json: {
          content: "# Original\nKeep this line.\n",
          path: "/project/check.md",
          version: 3,
        },
      });
    return route.fulfill({ json: {} });
  });

  await page.goto("/");
  await page.getByLabel("Message Agent Hub").fill("Revise the check");
  await page.getByRole("button", { name: "Send" }).click();
  const card = page.getByRole("region", {
    name: "Approve Project File change",
  });
  await expect(card).toContainText("/project/check.md");
  await card.getByText("Review proposed change").click();
  await expect(card.getByText(/-# Original/)).toBeVisible();
  await expect(card.getByText(/\+# Revised/)).toBeVisible();
  await card.getByRole("button", { name: "Open diff in preview" }).click();
  const preview = page.getByRole("region", { name: "Proposed Project File" });
  await expect(preview).toContainText("review snapshot");
  await expect(preview.getByLabel("Proposed file diff")).toContainText(
    "-# Original",
  );
  await preview.getByRole("button", { name: "Proposed file" }).click();
  await expect(preview.getByLabel("Proposed file content")).toContainText(
    "# Revised\nKeep this line.",
  );
  await expect(card.getByRole("button", { name: "Approve" })).toBeVisible();
});

test("rejected Project File approval remains a resolved card after reload", async ({
  page,
}) => {
  const project = {
    createdAt: "2026-09-16T00:00:00.000Z",
    id: "project-rejected",
    name: "Design review",
    updatedAt: "2026-09-16T00:00:00.000Z",
  };
  const thread = {
    createdAt: "2026-09-16T00:00:00.000Z",
    id: "thread-rejected",
    projectId: project.id,
    title: "Rejected change",
    updatedAt: "2026-09-16T00:00:00.000Z",
  };
  await page.route("**/api/projects", (route) =>
    route.fulfill({ json: [project] }),
  );
  await page.route("**/api/projects/**", async (route) => {
    const path = new URL(route.request().url()).pathname;
    if (path.endsWith("/threads")) {
      await route.fulfill({ json: [thread] });
    } else if (path.endsWith("/history")) {
      await route.fulfill({
        json: {
          approvals: [
            {
              approved: false,
              decisionRunId: "decision-run",
              interruptId: "interrupt-rejected",
              resolution: null,
              sourceRunId: "source-run",
              toolCallId: "tool-rejected",
            },
          ],
          interrupts: [],
          messages: [
            {
              content: null,
              id: "assistant-rejected",
              role: "assistant",
              toolCalls: [
                {
                  function: {
                    arguments: JSON.stringify({
                      file_path: "/project/check.md",
                      old_string: "old",
                      new_string: "new",
                    }),
                    name: "edit_file",
                  },
                  id: "tool-rejected",
                  type: "function",
                },
              ],
            },
          ],
        },
      });
    } else if (path.endsWith("/runs")) {
      await route.fulfill({ json: [] });
    } else {
      await route.fulfill({ json: {} });
    }
  });

  await page.goto("/");
  const card = page.getByRole("region", {
    name: "Approve Project File change",
  });
  await expect(card).toContainText("Rejected");
  await expect(card).toContainText("/project/check.md");
  await card.getByText("Review proposed change").click();
  await expect(card).toContainText("old");
  await expect(card).toContainText("new");
  await expect(card.getByRole("button", { name: "Approve" })).toBeHidden();
  await expect(
    card.getByRole("button", { name: "Open Project File" }),
  ).toBeHidden();
});

function sse(events: object[]) {
  return events.map((event) => `data: ${JSON.stringify(event)}\n\n`).join("");
}

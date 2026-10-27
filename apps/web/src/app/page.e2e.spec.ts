import { createServer } from "node:http";
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
        tools: [
          { name: "calculate_cantilever_tip_load", readOnly: false },
          { name: "check_uniform_beam_deflection", readOnly: false },
          { name: "size_for_deflection", readOnly: false },
          { name: "draft_beam_review_note", readOnly: false },
        ],
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
  await dialog.getByRole("button", { name: "Create Project" }).click();

  await expect(page.getByLabel("Selected Project")).toHaveValue(project.id);
  await expect(dialog).toBeHidden();
});

test("a stalled Project request releases the form and explains the timeout", async ({
  page,
}) => {
  await page.clock.install();
  await page.route("**/api/projects", async (route) => {
    if (route.request().method() === "GET") {
      await route.fulfill({ json: [] });
      return;
    }
    await new Promise(() => {});
  });

  await page.goto("/");
  await page.getByLabel("Selected Project").selectOption({
    label: "New Project…",
  });
  const dialog = page.getByRole("dialog", { name: "New Project" });
  await dialog.getByLabel("Project name").fill("Slow project request");
  await dialog.getByLabel("Project name").press("Enter");
  await expect(dialog.getByText("Creating…")).toBeVisible();

  await page.clock.fastForward(15_000);

  await expect(dialog.getByRole("alert")).toHaveText(
    "Project creation timed out. Check your Projects list before trying again.",
  );
  await expect(
    dialog.getByRole("button", { name: "Create Project" }),
  ).toBeEnabled();
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
          shape: "map",
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
          targetPort: "items",
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
          sourceHash: "sha256:map-function",
          mapInput: "record",
          inputSchema: {
            type: "object",
            properties: {
              record: {
                type: "object",
                properties: {
                  id: {
                    type: "string",
                    title: "Case ID",
                    description: "Load case identifier",
                  },
                  load: {
                    type: "number",
                    title: "Applied load",
                    description: "Load applied to beam",
                  },
                },
              },
            },
          },
          outputSchema: {
            type: "object",
            properties: {
              pass: {
                type: "boolean",
                title: "Passed",
                description: "Whether the item passed",
              },
              check_status: {
                type: "string",
                title: "Check status",
                description: "Outcome of the engineering check",
              },
              source_code: { type: "string", title: "Source code" },
              source_hash: { type: "string", title: "Source hash" },
            },
          },
        },
        calculate: {
          pluginId: "calculation-plugin",
          toolName: "calculate",
          version: "0.4.0",
          inputSchema: {
            type: "object",
            properties: {
              length_m: { type: "number", title: "Span" },
              tip_load_kn: { type: "number", title: "Tip load" },
            },
          },
          outputSchema: { type: "object" },
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
          items: [
            {
              index: 0,
              itemId: "LC-1",
              input: { id: "LC-1", load: 12.5 },
              status: "succeeded",
              output: {
                pass: true,
                check_status: "passes",
                source_code: "def calculate(): return 42",
                source_hash: "sha256:fixture",
              },
            },
            {
              index: 1,
              itemId: "LC-2",
              input: { id: "LC-2", load: 20 },
              status: "failed",
              error: "runner_failed",
              diagnostic: {
                message: "The area Function rejected the captured load.",
              },
              output: {
                pass: false,
                check_status: "fails",
                source_code: "def calculate(): return 0",
                source_hash: "sha256:failed",
              },
            },
          ],
        },
        calculate: {
          status: "succeeded",
          inputs: { record: { id: "LC-1", load: 12.5 } },
          output: { id: "LC-1", pass: true },
          items: [
            {
              index: 0,
              itemId: "LC-1",
              input: { length_m: 6.5, tip_load_kn: 12.5 },
              status: "succeeded",
              output: {
                calculation: {
                  maximumMoment: { value: 81.25, unit: "kN·m" },
                },
              },
            },
          ],
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
  await page.route(`**/api/projects/${project.id}/functions`, async (route) => {
    await route.fulfill({
      json: [
        {
          id: "summary-function",
          name: "Summarize loads",
          revision: 1,
          inputSchema: {
            type: "object",
            properties: { records: {} },
            required: ["records"],
            additionalProperties: false,
          },
        },
      ],
    });
  });
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
  const mcpApp = readFileSync(
    "../../plugins/reference-calculation/app/cantilever-view.html",
    "utf8",
  );
  await page.route(
    `**/api/projects/${project.id}/plugins/calculation-plugin/tools/calculate/app?version=0.4.0`,
    async (route) => {
      await route.fulfill({ body: mcpApp, contentType: "text/html" });
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
    page.getByRole("region", { name: "Workflow graph" }).first(),
  ).toContainText("Map");
  await page.getByRole("button", { name: "Inspect screen" }).click();
  const mapResults = page.getByRole("region", { name: "Mapped item results" });
  const mapTable = mapResults.getByRole("table");
  await expect(mapTable).toContainText("LC-1");
  await expect(mapTable).toContainText("LC-2");
  await expect(mapTable).toContainText("passes");
  await expect(mapTable).toContainText("fails");
  await expect(mapTable).toContainText("Yes");
  const failedRow = mapTable.getByRole("row", { name: /LC-2/ });
  await expect(failedRow).toContainText(
    "The Function runner could not complete this item.",
  );

  await page
    .getByRole("region", { name: "Mapped item results" })
    .getByRole("button", { name: "Preview" })
    .first()
    .click();
  await expect(page.getByRole("region", { name: "Node inputs" })).toContainText(
    "Inputs",
  );
  await expect(page.getByRole("dialog", { name: "LC-1" })).toContainText(
    "12.5",
  );
  await expect(page.getByRole("dialog", { name: "LC-1" })).toContainText(
    "Applied load",
  );
  await page
    .getByRole("dialog", { name: "LC-1" })
    .getByText("Technical details and provenance")
    .click();
  await expect(page.getByRole("dialog", { name: "LC-1" })).toContainText(
    "sha256:map-function",
  );
  await page.getByRole("button", { name: "Close", exact: true }).click();
  await expect(
    page.getByRole("region", { name: "screen details" }),
  ).toContainText("filter-function");
  await failedRow.getByRole("button", { name: "Preview" }).click();
  const failedItem = page.getByRole("dialog", { name: "LC-2" });
  await expect(
    failedItem.getByRole("region", { name: "Failure details" }),
  ).toContainText("The Function runner could not complete this item.");
  await expect(failedItem).toContainText("20");
  await failedItem.getByText("Exact error").click();
  await expect(failedItem).toContainText("runner_failed");
  await expect(failedItem).toContainText(
    "The area Function rejected the captured load.",
  );
  await failedItem.getByText("Technical details and provenance").click();
  await expect(failedItem).toContainText("filter-function");
  await page.getByRole("button", { name: "Close", exact: true }).click();
  await page.getByRole("button", { name: "Close preview" }).click();
  await page.getByRole("button", { name: "Inspect inputs" }).click();
  await page.getByRole("button", { name: "Open Library" }).click();
  await expect(
    page.getByRole("region", { name: "Library items" }),
  ).toBeVisible();
  await page
    .getByRole("button", { name: "Workflow graph", exact: true })
    .click();
  await page.getByRole("button", { name: "Inspect calculate" }).click();
  await expect(page.getByRole("button", { name: "Open Function" })).toHaveCount(
    0,
  );
  await page
    .getByRole("region", { name: "Mapped item results" })
    .getByRole("button", { name: "Preview" })
    .first()
    .click();
  await page.getByRole("button", { name: "Open MCP App" }).click();
  const mcpPreview = page.frameLocator(
    'iframe[title="calculate result preview"]',
  );
  await expect(mcpPreview.locator("#length")).toHaveValue("6.5");
  await expect(mcpPreview.locator("#load")).toHaveValue("12.5");
  await expect(mcpPreview.locator("#result")).toHaveText("81.3 kN·m");
  await page.getByRole("button", { name: "Close", exact: true }).click();
  await page
    .getByRole("button", { name: "Workflow graph", exact: true })
    .click();
  await page.getByRole("button", { name: "Inspect screen" }).click();
  await page.getByRole("button", { name: "Open Function" }).click();
  await expect(
    page
      .getByRole("navigation", { name: "Project views" })
      .getByRole("button", { name: "Functions" }),
  ).toHaveAttribute("aria-pressed", "true");
  await page
    .getByRole("button", { name: "Workflow graph", exact: true })
    .click();
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
  await page.getByRole("button", { name: "Add binding" }).click();
  await expect(
    page
      .getByRole("region", { name: "Workflow bindings" })
      .getByLabel("To node")
      .last(),
  ).toHaveValue("call-6");
  await expect(
    page
      .getByRole("region", { name: "Workflow bindings" })
      .getByLabel("Input port")
      .last(),
  ).toHaveValue("items");
  await page
    .getByLabel("Library item or call")
    .selectOption("MCP · Calculator / calculate");
  await page.getByLabel("Call shape").selectOption("single");
  await page.getByRole("button", { name: "Add node" }).click();
  await page.getByRole("button", { name: "Add binding" }).click();
  await expect(
    page
      .getByRole("region", { name: "Workflow bindings" })
      .getByLabel("To node")
      .last(),
  ).toHaveValue("call-7");
  await expect(
    page
      .getByRole("region", { name: "Workflow bindings" })
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
  await expect(
    page.getByRole("region", { name: "Workflow outputs" }),
  ).toContainText('"passed": 1');

  await page.setViewportSize({ width: 390, height: 844 });
  await expect(
    page.getByRole("region", { name: "Workflow outputs" }),
  ).toBeVisible();
  await expect(
    page.getByRole("region", { name: "Workflow graph" }).first(),
  ).toBeVisible();
  await page.getByRole("button", { name: "Inspect screen" }).click();
  await expect(
    page.getByRole("region", { name: "Mapped item results" }),
  ).toBeVisible();
  await expect
    .poll(() =>
      page.evaluate(
        () => document.documentElement.scrollWidth === window.innerWidth,
      ),
    )
    .toBe(true);
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

  const workspaceWidth = await page
    .locator("main")
    .evaluate((main) => Math.round(main.getBoundingClientRect().width));
  expect(workspaceWidth).toBe(390);
  await page.getByRole("button", { name: "Open Project navigation" }).click();
  const mobileNavigation = page.getByRole("dialog", {
    name: "Project navigation",
  });
  await expect(mobileNavigation).toBeVisible();
  expect(
    await page
      .locator("main")
      .evaluate((main) => Math.round(main.getBoundingClientRect().width)),
  ).toBe(workspaceWidth);
  await mobileNavigation
    .getByRole("button", { name: "Close Project navigation" })
    .click();
  await expect(mobileNavigation).toBeHidden();
  expect(
    await page
      .locator("main")
      .evaluate((main) => Math.round(main.getBoundingClientRect().width)),
  ).toBe(workspaceWidth);
  await page.getByRole("button", { name: "Open Project navigation" }).click();
  await page
    .getByRole("dialog", { name: "Project navigation" })
    .getByRole("button", { name: "Chats", exact: true })
    .click();
  await expect(
    page.getByRole("button", { name: "+ New Thread" }),
  ).toBeVisible();
  expect(
    await page
      .locator("main")
      .evaluate((main) => Math.round(main.getBoundingClientRect().width)),
  ).toBe(workspaceWidth);
  await expect
    .poll(() =>
      page.evaluate(
        () => document.documentElement.scrollWidth === window.innerWidth,
      ),
    )
    .toBe(true);

  await page.reload();
  await expect(
    page.getByRole("heading", { name: workflow.name }),
  ).toBeVisible();
  await page.getByRole("button", { name: "Inspect screen" }).click();
  const reloadedMapTable = page
    .getByRole("region", { name: "Mapped item results" })
    .getByRole("table");
  await expect(reloadedMapTable).toContainText("LC-1");
  await expect(reloadedMapTable).toContainText("passes");
  await expect(
    reloadedMapTable.getByRole("row", { name: /LC-2/ }),
  ).toContainText("The Function runner could not complete this item.");
});

test("a Project Workflow can be created from Library and Functions", async ({
  page,
}) => {
  const project = {
    createdAt: "2026-10-01T00:00:00.000Z",
    id: "project-create-workflow",
    name: "Test Project",
    updatedAt: "2026-10-01T00:00:00.000Z",
  };
  let createRequest: Record<string, unknown> | undefined;
  let runRequest: Record<string, unknown> | undefined;
  let savedGraph: unknown;

  await page.route("**/api/projects", async (route) => {
    await route.fulfill({ json: [project] });
  });
  await page.route(`**/api/projects/${project.id}/threads`, async (route) => {
    await route.fulfill({ json: [] });
  });
  await page.route(`**/api/projects/${project.id}/workflows`, async (route) => {
    if (route.request().method() === "POST") {
      createRequest = route.request().postDataJSON() as Record<string, unknown>;
      savedGraph = createRequest.graph;
      await route.fulfill({
        json: {
          id: "workflow-new",
          name: createRequest.name,
          version: 1,
          graph: savedGraph,
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
    `**/api/projects/${project.id}/datasets/loads`,
    async (route) => {
      await route.fulfill({
        json: {
          id: "loads",
          name: "Loads",
          version: 2,
          records: [{ value: { load: 5 } }],
        },
      });
    },
  );
  await page.route(
    `**/api/projects/${project.id}/files/index`,
    async (route) => {
      await route.fulfill({ json: { files: [] } });
    },
  );
  await page.route(`**/api/projects/${project.id}/functions`, async (route) => {
    await route.fulfill({
      json: [
        {
          id: "calculate",
          name: "Calculate loads",
          revision: 2,
          inputSchema: {
            type: "object",
            properties: {
              records: {},
              label: { type: "string" },
              factor: { type: "number" },
            },
            required: ["records", "label", "factor"],
            additionalProperties: false,
          },
        },
      ],
    });
  });
  await page.route(`**/api/projects/${project.id}/plugins`, async (route) => {
    await route.fulfill({ json: [] });
  });
  await page.route(
    `**/api/projects/${project.id}/workflows/workflow-new/runs/prepare`,
    async (route) => {
      runRequest = route.request().postDataJSON() as Record<string, unknown>;
      await route.fulfill({
        json: {
          id: "workflow-run-prepared",
          workflowId: "workflow-new",
          definitionVersion: 1,
          status: "prepared",
          snapshot: {
            graph: savedGraph,
            workflowInputs: runRequest.workflowInputs,
          },
          execution: {},
          initiatorSubject: "owner",
          createdAt: "2026-10-12T09:00:00.000Z",
        },
        status: 201,
      });
    },
  );
  await page.route(
    `**/api/projects/${project.id}/workflows/workflow-new/runs/workflow-run-prepared/execute`,
    async (route) => {
      await route.fulfill({
        json: {
          id: "workflow-run-prepared",
          workflowId: "workflow-new",
          definitionVersion: 1,
          status: "succeeded",
          snapshot: {
            graph: savedGraph,
            workflowInputs: runRequest?.workflowInputs,
          },
          execution: { nodes: {}, outputs: { result: [1] } },
          initiatorSubject: "owner",
          createdAt: "2026-10-12T09:00:00.000Z",
        },
      });
    },
  );

  await page.setViewportSize({ width: 390, height: 844 });
  await page.goto("/");
  await page.getByRole("button", { name: "Open Project navigation" }).click();
  await page.getByRole("button", { name: "Workflow" }).click();
  await page
    .getByRole("button", { name: "Close Project navigation" })
    .last()
    .click();
  await page.getByRole("button", { name: "Create Workflow" }).click();
  await page.getByRole("button", { name: "Add Workflow Input" }).click();
  await page.getByLabel("Library item or call").selectOption("Dataset · Loads");
  await page.getByRole("button", { name: "Add node" }).click();
  await page
    .getByLabel("Library item or call")
    .selectOption("Function · Calculate loads");
  await page.getByLabel("Call shape").selectOption("map");
  await page.getByRole("button", { name: "Add node" }).click();
  await page.getByRole("button", { name: "Add binding" }).click();
  await page.getByRole("button", { name: "Add binding" }).click();
  await page
    .getByLabel("Value comes from")
    .nth(1)
    .selectOption("workflowInput");
  await page
    .getByRole("combobox", { name: "Workflow Input", exact: true })
    .selectOption("input1");
  await page.getByLabel("Input port").nth(1).fill("label");
  await page.getByRole("button", { name: "Add binding" }).click();
  await page.getByLabel("Value comes from").nth(2).selectOption("literal");
  await page.getByLabel("Input port").nth(2).fill("factor");
  await page.getByLabel("Literal for binding 3").fill("2");
  await expect(
    page.getByText(
      "Dataset · Loads · whole value → Function · Calculate loads · Map item items",
    ),
  ).toBeVisible();
  await expect(
    page.getByText(
      "Workflow Input · input1 · whole value → Function · Calculate loads · Shared input label",
    ),
  ).toBeVisible();
  await expect(
    page.getByText(
      "Literal value · whole value → Function · Calculate loads · Shared input factor",
    ),
  ).toBeVisible();
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
    edges: Array<Record<string, unknown>>;
    inputs: Array<Record<string, unknown>>;
    outputs: Array<{ node: string; port: string }>;
  };
  expect(graph.nodes.map((node) => node.kind)).toEqual(["dataset", "python"]);
  expect(graph.nodes[1]?.shape).toBe("map");
  expect(graph.edges[0]).toMatchObject({
    sourcePort: "records",
    targetPort: "items",
  });
  expect(graph.inputs).toEqual([
    { name: "input1", required: true, schema: { type: "string" } },
  ]);
  expect(graph.edges[1]).toMatchObject({
    sourceKind: "workflowInput",
    sourceInput: "input1",
    targetPort: "label",
  });
  expect(graph.edges[2]).toMatchObject({
    sourceKind: "literal",
    literal: 2,
    targetPort: "factor",
  });
  expect(graph.outputs[0]).toMatchObject({ node: "call-2", port: "result" });
  const workflowGraph = page.getByRole("region", { name: "Workflow graph" });
  await expect(
    workflowGraph.getByRole("button", { name: "Inspect input1" }),
  ).toBeVisible();
  await expect(
    workflowGraph.getByRole("button", { name: "Inspect Literal value" }),
  ).toBeVisible();
  await page.getByLabel("Workflow Input input1").fill("test label");
  await page.getByRole("button", { name: "Review next Run" }).click();
  await expect(
    page.getByRole("region", { name: "Review next Run" }),
  ).toBeVisible();
  await page.getByRole("button", { name: "Run Workflow" }).click();
  await expect
    .poll(() => runRequest?.workflowInputs)
    .toEqual({ input1: "test label" });
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
  await page.route(`**/api/projects/${project.id}/functions`, async (route) => {
    await route.fulfill({ json: [] });
  });
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
  await page.getByRole("button", { name: "Workflow graph" }).click();
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
  await page.getByRole("button", { name: "Add binding" }).click();
  await page.getByRole("button", { name: "Add binding" }).click();
  const secondConnection = page
    .getByRole("region", { name: "Workflow bindings" })
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
      sourceKind: string;
      sourceNode: string;
      sourcePort: string;
      targetNode: string;
      targetPort: string;
    }>;
  };
  expect(graph.edges).toEqual([
    {
      sourceKind: "node",
      sourceNode: "input-1",
      sourcePort: "records",
      targetNode: "call-3",
      targetPort: "items",
    },
    {
      sourceKind: "node",
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

test("Functions is a dedicated Project destination and survives navigation", async ({
  page,
}) => {
  const project = {
    createdAt: "2026-09-18T00:00:00.000Z",
    id: "project-functions",
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
  await page.route(`**/api/projects/${project.id}/functions`, async (route) => {
    await route.fulfill({ json: [] });
  });

  await page.goto("/");
  const projectViews = page.getByRole("navigation", { name: "Project views" });
  await expect(
    projectViews.getByRole("button", { name: "Functions" }),
  ).toBeVisible();
  await expect(
    projectViews.getByRole("button", { name: "Operations" }),
  ).toHaveCount(0);
  await projectViews.getByRole("button", { name: "Functions" }).click();
  await expect(
    page.getByRole("button", { name: "New Function" }),
  ).toBeVisible();
  await projectViews.getByRole("button", { name: "Library" }).click();
  await projectViews.getByRole("button", { name: "Functions" }).click();
  await expect(
    page.getByRole("button", { name: "New Function" }),
  ).toBeVisible();
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
    "Showing 1 of 2 Records",
  );
  await viewer.getByLabel("Filter records in this view").fill("");
  await viewer
    .getByRole("row", { name: /LC-1/ })
    .getByText("Inspect record")
    .click();
  await expect(viewer.getByText("kN", { exact: true }).last()).toBeVisible();
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
  let exposeUpdatedVersion = false;
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
      await route.fulfill({
        json: exposeUpdatedVersion
          ? artifactDocument(2, "thread-b")
          : artifactDocument(1, "thread-a"),
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
  exposeUpdatedVersion = true;
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
  await page.getByLabel("Message").fill("Create the file");
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

test("approval waits for the interrupting stream to close before resuming", async ({
  page,
}) => {
  const project = {
    createdAt: "2026-10-18T00:00:00.000Z",
    id: "project-late-approval-snapshot",
    name: "Approval snapshot",
    updatedAt: "2026-10-18T00:00:00.000Z",
  };
  const thread = {
    createdAt: "2026-10-18T00:00:00.000Z",
    id: "thread-late-approval-snapshot",
    projectId: project.id,
    title: "Approve after snapshot",
    updatedAt: "2026-10-18T00:00:00.000Z",
  };
  const resumeRequests: unknown[] = [];
  let closeInitialStream: (() => void) | undefined;
  const streamServer = createServer((_request, response) => {
    response.writeHead(200, {
      "cache-control": "no-cache",
      "content-type": "text/event-stream",
      connection: "keep-alive",
    });
    const events = [
      { type: "RUN_STARTED", threadId: thread.id, runId: "initial-run" },
      {
        type: "TOOL_CALL_START",
        toolCallId: "tool-draining-run",
        toolCallName: "create_project_function",
      },
      {
        type: "TOOL_CALL_ARGS",
        toolCallId: "tool-draining-run",
        delta: JSON.stringify({
          input_schema: {},
          name: "Approved function",
          output_schema: {},
          source: "def run(inputs): return inputs",
        }),
      },
      { type: "TOOL_CALL_END", toolCallId: "tool-draining-run" },
      {
        type: "RUN_FINISHED",
        threadId: thread.id,
        runId: "initial-run",
        outcome: {
          type: "interrupt",
          interrupts: [
            {
              id: "interrupt-draining-run",
              reason: "tool_call",
              message: "Create the proposed Python Function?",
              toolCallId: "tool-draining-run",
              metadata: {
                agentHubLangChainHITL: {
                  rawInterruptId: "interrupt-draining-run",
                  actionIndex: 0,
                  allowedDecisions: ["approve", "reject"],
                },
              },
            },
          ],
        },
      },
    ];
    response.write(sse(events));
    closeInitialStream = () => response.end();
  });
  await new Promise<void>((resolve, reject) => {
    streamServer.once("error", reject);
    streamServer.listen(0, "127.0.0.1", resolve);
  });
  const address = streamServer.address();
  if (!address || typeof address === "string") {
    throw new Error("Approval test stream server did not bind to a port.");
  }

  await page.route("**/api/projects", (route) =>
    route.fulfill({ json: [project] }),
  );
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
              messageId: "assistant-after-late-snapshot",
              role: "assistant",
            },
            {
              type: "TEXT_MESSAGE_CONTENT",
              messageId: "assistant-after-late-snapshot",
              delta: "The approved action completed.",
            },
            {
              type: "TEXT_MESSAGE_END",
              messageId: "assistant-after-late-snapshot",
            },
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
      await route.continue({
        url: `http://127.0.0.1:${address.port}/agent`,
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
    return route.fulfill({ json: {} });
  });

  try {
    await page.goto("/");
    await page.getByLabel("Message").fill("Create a Python Function");
    await page.getByRole("button", { name: "Send" }).click();
    const approval = page.getByRole("region", {
      name: "Approve new Python Function",
    });
    await expect(approval).toContainText(
      "Create the proposed Python Function?",
    );
    await expect(page.getByText("Run: Running")).toBeVisible();
    await expect(
      approval.getByRole("button", { name: "Approve" }),
    ).toBeDisabled();
    expect(resumeRequests).toEqual([]);

    closeInitialStream?.();
    await expect(
      approval.getByRole("button", { name: "Approve" }),
    ).toBeEnabled();
    await approval.getByRole("button", { name: "Approve" }).click();

    await expect
      .poll(() => resumeRequests)
      .toEqual([
        [
          {
            interruptId: "interrupt-draining-run",
            payload: { approved: true },
            status: "resolved",
          },
        ],
      ]);
    await expect(
      page.getByText("The approved action completed."),
    ).toBeVisible();
    await expect(
      page.getByText("The agent run failed. You can try sending again."),
    ).toBeHidden();
  } finally {
    closeInitialStream?.();
    await new Promise<void>((resolve) => streamServer.close(() => resolve()));
  }
});

test("auto-approve mode resumes approval-gated tools in the current thread", async ({
  page,
}) => {
  const project = {
    createdAt: "2026-10-18T00:00:00.000Z",
    id: "project-auto-approve",
    name: "Auto approval",
    updatedAt: "2026-10-18T00:00:00.000Z",
  };
  const thread = {
    createdAt: "2026-10-18T00:00:00.000Z",
    id: "thread-auto-approve",
    projectId: project.id,
    title: "Auto-approve one thread",
    updatedAt: "2026-10-18T00:00:00.000Z",
  };
  const resumeRequests: unknown[] = [];

  await page.route("**/api/projects", (route) =>
    route.fulfill({ json: [project] }),
  );
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
              messageId: "assistant-auto-approved",
              role: "assistant",
            },
            {
              type: "TEXT_MESSAGE_CONTENT",
              messageId: "assistant-auto-approved",
              delta: "The approval-gated action completed.",
            },
            {
              type: "TEXT_MESSAGE_END",
              messageId: "assistant-auto-approved",
            },
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
            toolCallId: "call-auto-approve",
            toolCallName: "create_project_workflow",
          },
          {
            type: "TOOL_CALL_ARGS",
            toolCallId: "call-auto-approve",
            delta: JSON.stringify({ name: "Approved by mode" }),
          },
          { type: "TOOL_CALL_END", toolCallId: "call-auto-approve" },
          {
            type: "RUN_FINISHED",
            threadId: thread.id,
            runId: input.runId,
            outcome: {
              type: "interrupt",
              interrupts: [
                {
                  id: "interrupt-auto-approve",
                  reason: "tool_call",
                  message: "Create this Workflow Definition?",
                  toolCallId: "call-auto-approve",
                  metadata: {
                    agentHubLangChainHITL: {
                      rawInterruptId: "interrupt-auto-approve",
                      actionIndex: 0,
                      allowedDecisions: ["approve", "reject"],
                    },
                  },
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
    return route.fulfill({ json: {} });
  });

  await page.goto("/");
  await page.getByLabel("Approval mode").selectOption("auto");
  await page.getByLabel("Message").fill("Create a workflow");
  await page.getByRole("button", { name: "Send" }).click();

  await expect
    .poll(() => resumeRequests)
    .toEqual([
      [
        {
          interruptId: "interrupt-auto-approve",
          payload: { approved: true },
          status: "resolved",
        },
      ],
    ]);
  await expect(
    page.getByText("The approval-gated action completed."),
  ).toBeVisible();
  await expect(
    page.getByText("The agent run failed. You can try sending again."),
  ).toBeHidden();
});

test("a batch of approvals resumes only after every docked decision", async ({
  page,
}) => {
  const project = {
    createdAt: "2026-10-16T00:00:00.000Z",
    id: "project-approval-batch",
    name: "Approval batch",
    updatedAt: "2026-10-16T00:00:00.000Z",
  };
  const thread = {
    createdAt: "2026-10-16T00:00:00.000Z",
    id: "thread-approval-batch",
    projectId: project.id,
    title: "Approval batch",
    updatedAt: "2026-10-16T00:00:00.000Z",
  };
  const actions = ["uppercase_text", "word_stats", "bullet_summary"].map(
    (name, index) => ({
      args: {
        input_schema: {},
        name,
        output_schema: {},
        source: "def run(inputs): return inputs",
      },
      interruptId: `interrupt-${index + 1}`,
      toolCallId: `tool-${index + 1}`,
    }),
  );
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
              messageId: "assistant-batch-complete",
              role: "assistant",
            },
            {
              type: "TEXT_MESSAGE_CONTENT",
              messageId: "assistant-batch-complete",
              delta: "Approval batch completed.",
            },
            {
              type: "TEXT_MESSAGE_END",
              messageId: "assistant-batch-complete",
            },
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

      const events = [
        { type: "RUN_STARTED", threadId: thread.id, runId: input.runId },
        ...actions.flatMap(({ args, toolCallId }) => [
          {
            type: "TOOL_CALL_START",
            toolCallId,
            toolCallName: "create_project_function",
          },
          {
            type: "TOOL_CALL_ARGS",
            toolCallId,
            delta: JSON.stringify(args),
          },
          { type: "TOOL_CALL_END", toolCallId },
        ]),
        {
          type: "RUN_FINISHED",
          threadId: thread.id,
          runId: input.runId,
          outcome: {
            type: "interrupt",
            interrupts: actions.map(({ interruptId, toolCallId }) => ({
              id: interruptId,
              reason: "tool_call",
              toolCallId,
            })),
          },
        },
      ];
      await route.fulfill({
        contentType: "text/event-stream",
        body: sse(events),
      });
    },
  );
  await page.route("**/api/projects", (route) =>
    route.fulfill({ json: [project] }),
  );
  await page.route("**/api/projects/**", async (route) => {
    const path = new URL(route.request().url()).pathname;
    if (path.endsWith("/agent")) return route.fallback();
    if (path.endsWith("/threads")) return route.fulfill({ json: [thread] });
    if (path.endsWith("/history")) {
      return route.fulfill({
        json: { approvals: [], interrupts: [], messages: [] },
      });
    }
    if (path.endsWith("/runs")) return route.fulfill({ json: [] });
    return route.fulfill({ json: {} });
  });

  await page.goto("/");
  await page.getByLabel("Message").fill("Create three Functions");
  await page.getByRole("button", { name: "Send" }).click();

  const dock = page.getByRole("region", { name: "Pending approvals" });
  await expect(dock.getByRole("region")).toHaveCount(3);
  await expect(page.getByText("Run: Awaiting approval")).toBeVisible();
  await expect(
    page.locator('[data-role="assistant"]').getByRole("region"),
  ).toHaveCount(0);

  await dock
    .getByRole("region")
    .nth(0)
    .getByRole("button", { name: "Approve" })
    .click();
  await expect.poll(() => resumeRequests).toHaveLength(0);
  await expect(dock.getByRole("region")).toHaveCount(2);

  await dock
    .getByRole("region")
    .nth(0)
    .getByRole("button", { name: "Reject" })
    .click();
  await expect.poll(() => resumeRequests).toHaveLength(0);
  await expect(dock.getByRole("region")).toHaveCount(1);

  await dock
    .getByRole("region")
    .getByRole("button", { name: "Approve" })
    .click();
  await expect
    .poll(() => resumeRequests)
    .toEqual([
      [
        {
          interruptId: "interrupt-1",
          payload: { approved: true },
          status: "resolved",
        },
        {
          interruptId: "interrupt-2",
          payload: { approved: false, reason: "Rejected by the user" },
          status: "resolved",
        },
        {
          interruptId: "interrupt-3",
          payload: { approved: true },
          status: "resolved",
        },
      ],
    ]);
  await expect(page.getByText("Approval batch completed.")).toBeVisible();
});

test("composer blocks sending while an approval is pending", async ({
  page,
}) => {
  const project = {
    createdAt: "2026-10-16T00:00:00.000Z",
    id: "project-pending-approval",
    name: "Approval review",
    updatedAt: "2026-10-16T00:00:00.000Z",
  };
  const thread = {
    createdAt: "2026-10-16T00:00:00.000Z",
    id: "thread-pending-approval",
    projectId: project.id,
    title: "Approval review",
    updatedAt: "2026-10-16T00:00:00.000Z",
  };
  const agentRequests: unknown[] = [];

  await page.route(
    `**/api/projects/${project.id}/threads/${thread.id}/agent`,
    async (route) => {
      const input = route.request().postDataJSON() as { runId: string };
      agentRequests.push(input);
      await route.fulfill({
        contentType: "text/event-stream",
        body: sse([
          { type: "RUN_STARTED", threadId: thread.id, runId: input.runId },
          {
            type: "TOOL_CALL_START",
            toolCallId: "tool-pending-approval",
            toolCallName: "create_project_function",
          },
          {
            type: "TOOL_CALL_ARGS",
            toolCallId: "tool-pending-approval",
            delta: JSON.stringify({ name: "Reviewed function" }),
          },
          { type: "TOOL_CALL_END", toolCallId: "tool-pending-approval" },
          {
            type: "RUN_FINISHED",
            threadId: thread.id,
            runId: input.runId,
            outcome: {
              type: "interrupt",
              interrupts: [
                {
                  id: "interrupt-pending-approval",
                  reason: "tool_call",
                  toolCallId: "tool-pending-approval",
                },
              ],
            },
          },
        ]),
      });
    },
  );
  await page.route("**/api/projects", (route) =>
    route.fulfill({ json: [project] }),
  );
  await page.route("**/api/projects/**", async (route) => {
    const path = new URL(route.request().url()).pathname;
    if (path.endsWith("/agent")) return route.fallback();
    if (path.endsWith("/threads")) return route.fulfill({ json: [thread] });
    if (path.endsWith("/history")) {
      return route.fulfill({
        json: { approvals: [], interrupts: [], messages: [] },
      });
    }
    if (path.endsWith("/runs")) return route.fulfill({ json: [] });
    return route.fulfill({ json: {} });
  });

  await page.goto("/");
  await page.getByLabel("Message").fill("Create a Function");
  await page.getByRole("button", { name: "Send" }).click();
  const approval = page.getByRole("region", {
    name: "Approve new Python Function",
  });
  await expect(approval).toBeVisible();
  await expect(
    page.locator('[data-role="assistant"]').getByRole("region"),
  ).toHaveCount(0);

  const composer = page.getByLabel("Message");
  const send = page.getByRole("button", { name: "Send" });
  await composer.fill("Another request while approval is waiting");
  await expect(send).toBeDisabled();
  await expect(agentRequests).toHaveLength(1);
  await expect(
    page.getByText(
      "Respond to the pending approval before sending another message.",
    ),
  ).toBeVisible();
  await expect(
    page.getByText("The agent run failed. You can try sending again."),
  ).toBeHidden();
});

test("process stays expanded while work streams and collapses when the turn ends", async ({
  page,
}) => {
  const project = {
    createdAt: "2026-10-13T00:00:00.000Z",
    id: "project-process-progress",
    name: "Progress review",
    updatedAt: "2026-10-13T00:00:00.000Z",
  };
  const thread = {
    createdAt: "2026-10-13T00:00:00.000Z",
    id: "thread-process-progress",
    projectId: project.id,
    title: "Check progress UI",
    updatedAt: "2026-10-13T00:00:00.000Z",
  };

  await page.addInitScript(() => {
    const nativeFetch = window.fetch.bind(window);
    window.fetch = async (input, init) => {
      const url =
        typeof input === "string"
          ? input
          : input instanceof Request
            ? input.url
            : input.href;
      if (!url.endsWith("/agent") || init?.method !== "POST") {
        return nativeFetch(input, init);
      }

      const body = JSON.parse(String(init.body)) as {
        runId: string;
        threadId: string;
      };
      const events = [
        { type: "RUN_STARTED", threadId: body.threadId, runId: body.runId },
        {
          type: "TOOL_CALL_START",
          toolCallId: "call-read-project-file",
          toolCallName: "read_project_file",
          parentMessageId: "message-progress-tool",
        },
        {
          type: "TOOL_CALL_ARGS",
          toolCallId: "call-read-project-file",
          delta: JSON.stringify({ path: "/project/brief.md" }),
        },
      ];
      const encoder = new TextEncoder();
      const stream = new ReadableStream<Uint8Array>({
        async start(controller) {
          const send = (event: object) =>
            controller.enqueue(
              encoder.encode(`data: ${JSON.stringify(event)}\n\n`),
            );
          const pause = (duration: number) =>
            new Promise((resolve) => setTimeout(resolve, duration));
          for (const event of events) send(event);
          await pause(700);
          send({
            type: "TOOL_CALL_END",
            toolCallId: "call-read-project-file",
          });
          send({
            type: "TOOL_CALL_RESULT",
            messageId: "message-progress-result",
            toolCallId: "call-read-project-file",
            content: "Project brief loaded",
          });
          await pause(700);
          send({
            type: "TEXT_MESSAGE_START",
            messageId: "message-progress-answer",
            role: "assistant",
          });
          send({
            type: "TEXT_MESSAGE_CONTENT",
            messageId: "message-progress-answer",
            delta: "I checked the brief and found the requested details.",
          });
          send({
            type: "TEXT_MESSAGE_END",
            messageId: "message-progress-answer",
          });
          await pause(500);
          send({
            type: "RUN_FINISHED",
            threadId: body.threadId,
            runId: body.runId,
            outcome: { type: "success" },
          });
          controller.close();
        },
      });
      return new Response(stream, {
        headers: { "content-type": "text/event-stream" },
      });
    };
  });

  await page.route("**/api/projects", (route) =>
    route.request().method() === "GET"
      ? route.fulfill({ json: [] })
      : route.fulfill({ json: project, status: 201 }),
  );
  await page.route("**/api/projects/**", async (route) => {
    const path = new URL(route.request().url()).pathname;
    if (path.endsWith("/agent")) return route.fallback();
    if (path.endsWith("/threads")) return route.fulfill({ json: [thread] });
    if (path.endsWith("/history")) {
      return route.fulfill({
        json: { approvals: [], interrupts: [], messages: [] },
      });
    }
    if (path.endsWith("/runs")) return route.fulfill({ json: [] });
    return route.fulfill({ json: {} });
  });

  await page.goto("/");
  const selectedProject = page.getByLabel("Selected Project");
  await selectedProject.selectOption({ label: "New Project…" });
  const projectDialog = page.getByRole("dialog", { name: "New Project" });
  await projectDialog.getByLabel("Project name").fill(project.name);
  await projectDialog.getByRole("button", { name: "Create Project" }).click();
  await expect(selectedProject).toHaveValue(project.id);
  await page.getByLabel("Message").fill("Check the project brief");
  await page.getByRole("button", { name: "Send" }).click();

  const process = page.locator("details").first();
  await expect(process).toHaveAttribute("open", "");
  await expect(process.locator(":scope > summary")).toContainText("Thinking");
  await expect(process.locator(":scope > summary")).toContainText(
    "Using tools",
  );
  const toolCall = process.getByText("Read Project File");
  await expect(toolCall).toBeVisible();
  await expect(process.getByText("Running")).toBeVisible();
  const toolDetails = toolCall.locator("xpath=../..");
  await expect(toolDetails).not.toHaveAttribute("open", "");
  await toolCall.click();
  await expect(toolDetails.getByText("Input", { exact: true })).toBeVisible();
  await expect(toolDetails.getByText("Output", { exact: true })).toBeVisible();
  await expect(toolDetails.getByText("/project/brief.md")).toBeVisible();

  await expect(page.getByText("Thinking", { exact: true })).toBeVisible();
  await expect(process).toHaveAttribute("open", "");
  await expect(
    page.getByText("I checked the brief and found the requested details."),
  ).toBeVisible();
  await expect(page.getByText("Process", { exact: true })).toBeVisible();
  await expect(process).not.toHaveAttribute("open", "");
  await process.locator(":scope > summary").click();
  await expect(process).toHaveAttribute("open", "");
  await expect(toolDetails.getByText("Project brief loaded")).toBeVisible();
});

test("approving an interrupt after a LangGraph message snapshot resumes", async ({
  page,
}) => {
  const project = {
    createdAt: "2026-10-13T00:00:00.000Z",
    id: "project-function-approval",
    name: "Workflow creation",
    updatedAt: "2026-10-13T00:00:00.000Z",
  };
  const thread = {
    createdAt: "2026-10-13T00:00:00.000Z",
    id: "thread-function-approval",
    projectId: project.id,
    title: "Create a workflow",
    updatedAt: "2026-10-13T00:00:00.000Z",
  };
  const functionProposal = {
    input_schema: {
      description: "Calculates rectangular area from two dimensions.",
      examples: [{ length_m: 12, width_m: 5 }],
      properties: {
        length_m: {
          description: "Length in metres.",
          example: 12,
          type: "number",
        },
        width_m: {
          description: "Width in metres.",
          example: 5,
          type: "number",
        },
      },
      required: ["length_m", "width_m"],
      type: "object",
    },
    name: "Rectangle area",
    output_schema: {
      examples: [{ area_m2: 60 }],
      properties: {
        area_m2: {
          description: "Area in square metres.",
          example: 60,
          type: "number",
        },
      },
      required: ["area_m2"],
      type: "object",
    },
    source:
      'def transform(inputs, parameters): return {"area_m2": inputs["length_m"] * inputs["width_m"]}',
  };
  const resumeRequests: unknown[] = [];
  const failureMessages: string[] = [];
  let approvalResolved = false;

  page.on("console", (message) => {
    if (message.type() === "error") failureMessages.push(message.text());
  });
  await page.route("**/api/projects", (route) =>
    route.fulfill({ json: [project] }),
  );
  await page.route(
    `**/api/projects/${project.id}/threads/${thread.id}/agent`,
    async (route) => {
      const input = route.request().postDataJSON() as {
        resume?: unknown[];
        runId: string;
      };
      if (input.resume) {
        resumeRequests.push(input.resume);
        approvalResolved = true;
        await route.fulfill({
          contentType: "text/event-stream",
          body: sse([
            { type: "RUN_STARTED", threadId: thread.id, runId: input.runId },
            {
              type: "TEXT_MESSAGE_START",
              messageId: "assistant-function-approved",
              role: "assistant",
            },
            {
              type: "TEXT_MESSAGE_CONTENT",
              messageId: "assistant-function-approved",
              delta: "Created the proposed Function.",
            },
            {
              type: "TEXT_MESSAGE_END",
              messageId: "assistant-function-approved",
            },
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
            toolCallId: "call-discover-functions",
            toolCallName: "discover_project_functions",
            parentMessageId: "message-discover-functions",
          },
          {
            type: "TOOL_CALL_ARGS",
            toolCallId: "call-discover-functions",
            delta: "{}",
          },
          {
            type: "TOOL_CALL_END",
            toolCallId: "call-discover-functions",
          },
          {
            type: "TOOL_CALL_RESULT",
            messageId: "message-result-functions",
            toolCallId: "call-discover-functions",
            content: "[]",
          },
          {
            type: "TOOL_CALL_START",
            toolCallId: "call-create-function",
            toolCallName: "create_project_function",
            parentMessageId: "message-create-function",
          },
          {
            type: "TOOL_CALL_ARGS",
            toolCallId: "call-create-function",
            delta: JSON.stringify(functionProposal),
          },
          { type: "TOOL_CALL_END", toolCallId: "call-create-function" },
          {
            type: "MESSAGES_SNAPSHOT",
            messages: [
              {
                id: "message-discover-functions",
                role: "assistant",
                content: "",
                toolCalls: [
                  {
                    id: "call-discover-functions",
                    type: "function",
                    function: {
                      name: "discover_project_functions",
                      arguments: "{}",
                    },
                  },
                ],
              },
              {
                id: "message-result-functions",
                role: "tool",
                toolCallId: "call-discover-functions",
                content: "[]",
              },
              {
                id: "message-create-function",
                role: "assistant",
                content: "",
                toolCalls: [
                  {
                    id: "call-create-function",
                    type: "function",
                    function: {
                      name: "create_project_function",
                      arguments: JSON.stringify(functionProposal),
                    },
                  },
                ],
              },
            ],
          },
          {
            type: "RUN_FINISHED",
            threadId: thread.id,
            runId: input.runId,
            outcome: {
              type: "interrupt",
              interrupts: [
                {
                  id: "interrupt-create-function",
                  reason: "tool_call",
                  message: "Create the proposed Python Function?",
                  toolCallId: "call-create-function",
                  metadata: {
                    agentHubLangChainHITL: {
                      rawInterruptId: "interrupt-create-function",
                      actionIndex: 0,
                      allowedDecisions: ["approve", "reject"],
                    },
                  },
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
        json: approvalResolved
          ? {
              approvals: [
                {
                  approved: true,
                  decisionRunId: "decision-run-function",
                  interruptId: "interrupt-create-function",
                  resolution: null,
                  sourceRunId: "source-run-function",
                  toolCallId: "call-create-function",
                },
                {
                  approved: false,
                  decisionRunId: "decision-run-function-rejected",
                  interruptId: "interrupt-rejected-function",
                  resolution: null,
                  sourceRunId: "source-run-function",
                  toolCallId: "call-rejected-function",
                },
              ],
              interrupts: [],
              messages: [
                {
                  content: null,
                  id: "message-create-function",
                  role: "assistant",
                  toolCalls: [
                    {
                      function: {
                        arguments: JSON.stringify(functionProposal),
                        name: "create_project_function",
                      },
                      id: "call-create-function",
                      type: "function",
                    },
                    {
                      function: {
                        arguments: JSON.stringify(functionProposal),
                        name: "update_project_function",
                      },
                      id: "call-rejected-function",
                      type: "function",
                    },
                  ],
                },
              ],
            }
          : { approvals: [], interrupts: [], messages: [] },
      });
    if (path.endsWith("/runs")) return route.fulfill({ json: [] });
    return route.fulfill({ json: {} });
  });

  await page.goto("/");
  await page.getByLabel("Message").fill("Create a workflow");
  await page.getByRole("button", { name: "Send" }).click();
  const card = page.getByRole("region", {
    name: "Approve new Python Function",
  });
  await expect(card).toContainText("Create the proposed Python Function?");
  await expect(card).toContainText("Rectangle area");
  await expect(card).toContainText(
    "Calculates rectangular area from two dimensions.",
  );
  await expect(card).toContainText("length_m");
  await expect(card).toContainText("Length in metres.");
  await expect(card).toContainText("area_m2");
  await expect(card).toContainText("Object (length_m: 12; width_m: 5)");
  await expect(
    card.getByText("Full proposal, including Python source and schemas"),
  ).toBeVisible();
  const proposalDetails = card.locator("details");
  await expect(proposalDetails).not.toHaveAttribute("open", "");
  await card
    .getByText("Full proposal, including Python source and schemas")
    .click();
  await expect(proposalDetails).toHaveAttribute("open", "");
  await expect(proposalDetails).toContainText(
    "def transform(inputs, parameters)",
  );
  await card.getByRole("button", { name: "Approve" }).click();

  await expect
    .poll(() => resumeRequests)
    .toEqual([
      [
        {
          interruptId: "interrupt-create-function",
          payload: { approved: true },
          status: "resolved",
        },
      ],
    ]);
  await expect(page.getByText("Created the proposed Function.")).toBeVisible();
  await expect(
    page.getByText("The agent run failed. You can try sending again."),
  ).toBeHidden();

  await page.reload();
  const resolvedCards = page.getByRole("region", {
    name: "Approve new Python Function",
  });
  const rejectedCards = page.getByRole("region", {
    name: "Approve Python Function revision",
  });
  await expect(resolvedCards).toHaveCount(1);
  await expect(rejectedCards).toHaveCount(1);
  await expect(resolvedCards).toContainText("Approved");
  await expect(resolvedCards).toContainText("Rectangle area");
  await expect(resolvedCards).toContainText(
    "Calculates rectangular area from two dimensions.",
  );
  await expect(rejectedCards).toContainText("Rejected");
  await expect(rejectedCards).toContainText("Rectangle area");
  await rejectedCards
    .getByText("Full proposal, including Python source and schemas")
    .click();
  await expect(rejectedCards).toContainText(
    "def transform(inputs, parameters)",
  );
  expect(
    failureMessages.some((message) =>
      message.includes("respondToToolApproval: no pending interrupts"),
    ),
  ).toBe(false);
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
  await page.getByLabel("Message").fill("Revise the check");
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

test("approving a restored workflow interrupt resumes the AG-UI run", async ({
  page,
}) => {
  const project = {
    createdAt: "2026-09-16T00:00:00.000Z",
    id: "project-restored-workflow",
    name: "Workflow review",
    updatedAt: "2026-09-16T00:00:00.000Z",
  };
  const thread = {
    createdAt: "2026-09-16T00:00:00.000Z",
    id: "thread-restored-workflow",
    projectId: project.id,
    title: "Demo workflow",
    updatedAt: "2026-09-16T00:00:00.000Z",
  };
  const resumeRequests: unknown[] = [];
  await page.route("**/api/projects", (route) =>
    route.fulfill({ json: [project] }),
  );
  await page.route(
    `**/api/projects/${project.id}/threads/${thread.id}/agent`,
    async (route) => {
      const input = route.request().postDataJSON() as {
        resume?: unknown[];
        runId: string;
      };
      resumeRequests.push(input.resume);
      await route.fulfill({
        contentType: "text/event-stream",
        body: sse([
          { type: "RUN_STARTED", threadId: thread.id, runId: input.runId },
          {
            type: "TEXT_MESSAGE_START",
            messageId: "assistant-after-approval",
            role: "assistant",
          },
          {
            type: "TEXT_MESSAGE_CONTENT",
            messageId: "assistant-after-approval",
            delta: "Created the demo workflow.",
          },
          {
            type: "TEXT_MESSAGE_END",
            messageId: "assistant-after-approval",
          },
          {
            type: "RUN_FINISHED",
            threadId: thread.id,
            runId: input.runId,
            outcome: { type: "success" },
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
        json: {
          approvals: [],
          interrupts: [
            {
              id: "interrupt-create-workflow",
              reason: "tool_call",
              toolCallId: "tool-create-workflow",
            },
          ],
          messages: [
            {
              content: null,
              id: "assistant-pending-workflow",
              role: "assistant",
              toolCalls: [
                {
                  function: {
                    arguments: JSON.stringify({
                      graph_json: JSON.stringify({
                        edges: [],
                        nodes: {
                          input: { output: "value", type: "input" },
                        },
                        outputs: { value: "input" },
                      }),
                      name: "Demo workflow",
                    }),
                    name: "create_project_workflow",
                  },
                  id: "tool-create-workflow",
                  type: "function",
                },
              ],
            },
          ],
        },
      });
    if (path.endsWith("/runs")) return route.fulfill({ json: [] });
    return route.fulfill({ json: {} });
  });

  await page.goto("/");
  const card = page.getByRole("region", { name: "Approve protected action" });
  await expect(card).toContainText("Demo workflow");
  await card.getByRole("button", { name: "Approve" }).click();
  await expect
    .poll(() => resumeRequests)
    .toEqual([
      [
        {
          interruptId: "interrupt-create-workflow",
          payload: { approved: true },
          status: "resolved",
        },
      ],
    ]);
});

function sse(events: object[]) {
  return events.map((event) => `data: ${JSON.stringify(event)}\n\n`).join("");
}

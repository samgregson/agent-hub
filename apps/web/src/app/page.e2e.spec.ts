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

test("Library navigation combines Artifacts and Project files into one list", async ({
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
          ],
        },
      });
    },
  );

  await page.route(`**/api/projects/${project.id}/datasets`, async (route) => {
    await route.fulfill({ json: [] });
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
        value: { load: 12.5 },
      },
    ],
  };
  let savedVersion: number | null = null;
  let currentDataset = dataset;
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
          records: Array<{ value: { load: number } }>;
        };
        savedVersion = body.expectedVersion;
        currentDataset = {
          ...dataset,
          version: 2,
          records: [{ ...dataset.records[0], value: body.records[0].value }],
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

  await expect(
    page.getByRole("button", { name: path, exact: true }),
  ).toBeHidden();
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

test("a Project File Binding can be inspected and rebound after its source changes", async ({
  page,
}) => {
  const project = {
    createdAt: "2026-09-24T00:00:00.000Z",
    id: "project-binding",
    name: "Template project",
    updatedAt: "2026-09-24T00:00:00.000Z",
  };
  const definition = {
    id: "definition-binding",
    datasetId: "dataset-binding",
    datasetAvailable: true,
    name: "Render values",
    pluginId: "foundation-fixture",
    toolName: "render_template_value",
    transformDefinitionId: null,
    fileArgument: "template",
    argumentMappings: { value: "/value" },
  };
  let fileVersion = 1;
  let bindingVersion = 0;
  const writes: Array<Record<string, unknown>> = [];
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
      await route.fulfill({
        json: {
          files: [{ path: "/project/template.txt", version: fileVersion }],
        },
      });
    },
  );
  await page.route(`**/api/projects/${project.id}/datasets`, async (route) => {
    await route.fulfill({
      json: [{ id: definition.datasetId, name: "Values", records: [] }],
    });
  });
  await page.route(
    `**/api/projects/${project.id}/transforms`,
    async (route) => {
      await route.fulfill({ json: [] });
    },
  );
  await page.route(
    `**/api/projects/${project.id}/batch-definitions`,
    async (route) => {
      await route.fulfill({ json: [definition] });
    },
  );
  await page.route(
    `**/api/projects/${project.id}/batch-definitions/${definition.id}/file-binding`,
    async (route) => {
      if (route.request().method() === "GET") {
        if (bindingVersion === 0) {
          await route.fulfill({ status: 404 });
          return;
        }
      } else {
        writes.push(route.request().postDataJSON() as Record<string, unknown>);
        bindingVersion += 1;
      }
      await route.fulfill({
        json: {
          id: "binding-1",
          definitionId: definition.id,
          argument: "template",
          sourcePath: "/project/template.txt",
          expectedFileVersion: fileVersion,
          cardinality: "scalar-to-selected-records",
          version: bindingVersion,
        },
        status: route.request().method() === "POST" ? 201 : 200,
      });
    },
  );
  await page.route(
    `**/api/projects/${project.id}/batch-runs?**`,
    async (route) => {
      await route.fulfill({ json: { items: [], nextOffset: null } });
    },
  );

  await page.goto("/");
  await page.getByRole("button", { name: "Batch Definitions" }).click();
  await page
    .getByRole("button", { name: "Inspect Batch Definition Render values" })
    .click();
  const panel = page.getByRole("region", { name: "Project File Binding" });
  await expect(panel.getByText("No file bound yet.")).toBeVisible();
  await panel.getByLabel("Project File").selectOption("/project/template.txt");
  await panel.getByRole("button", { name: "Bind Project File" }).click();
  await expect(panel.getByText(/Binding v1/)).toBeVisible();
  expect(writes[0]).toMatchObject({
    sourcePath: "/project/template.txt",
    expectedFileVersion: 1,
  });

  fileVersion = 2;
  await panel.getByRole("button", { name: "Refresh Project Files" }).click();
  await expect(panel.getByRole("option", { name: /v2/ })).toHaveCount(1);
  await panel
    .getByRole("button", { name: "Rebind current file version" })
    .click();
  await expect(panel.getByText(/Binding v2/)).toBeVisible();
  expect(writes[1]).toMatchObject({
    sourcePath: "/project/template.txt",
    expectedFileVersion: 2,
    expectedBindingVersion: 1,
  });
});

test("selection planning and runs reach the Project API through the browser", async ({
  request,
}) => {
  for (const endpoint of [
    "selection-plan",
    "selection-runs",
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

test("a reviewed Dataset selection starts one captured Transform Run", async ({
  page,
}) => {
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
    datasetId: "dataset-1",
    datasetVersion: 2,
    datasetPath: "/.datasets/dataset-1.json",
    recordIds: ["record-2"],
    records: [{ id: "record-2", value: { score: 3 } }],
    rule: { sortPath: "/score", descending: true, limit: 1 },
    selectedCount: 1,
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
    `**/api/projects/${project.id}/transforms/${definition.id}/selection-plan`,
    (route) => {
      writes.push(route.request().postDataJSON() as Record<string, unknown>);
      return route.fulfill({
        json: {
          selection,
          selectedCount: 1,
          invocationCount: 1,
          outputLocation: "Transform Run output",
        },
      });
    },
  );
  await page.route(
    `**/api/projects/${project.id}/transforms/${definition.id}/selection-runs`,
    (route) => {
      writes.push(route.request().postDataJSON() as Record<string, unknown>);
      return route.fulfill({
        status: 201,
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
          inputs: { items: [{ score: 3 }] },
          parameters: {},
          inputHash: "inputhash",
          sourceHash: "sourcehash",
          packageHash: "abc",
          runtime: "pyodide",
          output: { total: 3 },
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
      });
    },
  );
  await page.goto("/");
  await page.getByRole("button", { name: "Transforms" }).click();
  await page.getByLabel("Input source").selectOption("dataset");
  await page
    .getByRole("combobox", { name: "Dataset", exact: true })
    .selectOption("dataset-1");
  await page.getByLabel("Sort path (JSON Pointer, optional)").fill("/score");
  await page.getByLabel("Descending order").check();
  await page.getByLabel("Maximum records (optional)").fill("1");
  await page.getByRole("button", { name: "Review selection" }).click();
  await expect(
    page.getByRole("region", { name: "Selection plan" }),
  ).toContainText("1 records · 1 Transform invocation");
  await page.getByRole("button", { name: "Start selected Run" }).click();
  await expect(
    page.getByRole("article", { name: "Run dataflow" }),
  ).toContainText("Dataset dataset- · v2 · 1 Records");
  expect(writes).toHaveLength(2);
  expect(writes[0]).toMatchObject({
    datasetId: "dataset-1",
    expectedVersion: 2,
    expectedDefinitionRevision: 3,
    sortPath: "/score",
    descending: true,
    limit: 1,
  });
  expect(writes[1]).toEqual(writes[0]);
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
          outputLocation: "Transform Run output",
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
  await page.getByRole("button", { name: "Transforms" }).click();
  await page.getByLabel("Input source").selectOption("output");
  await page
    .getByRole("combobox", { name: "Transform Run", exact: true })
    .selectOption(upstream.id);
  await page.getByLabel("Output path (JSON Pointer)").fill("/items");
  await page.getByLabel("Sort path (JSON Pointer, optional)").fill("/score");
  await page.getByLabel("Maximum records (optional)").fill("1");
  await page.getByRole("button", { name: "Review selection" }).click();
  await expect(
    page.getByRole("region", { name: "Selection plan" }),
  ).toContainText("Transform Run transfor → Transform Run output");
  await page.getByRole("button", { name: "Start selected Run" }).click();
  await expect(
    page.getByRole("article", { name: "Run dataflow" }),
  ).toContainText("Transform Run transfor · 1 values");
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

test("a Batch Result Set selection keeps row lineage in the Transform Run", async ({ page }) => {
  const project = {
    id: "project-result-selection", name: "Result selection",
    createdAt: "2026-10-08T00:00:00Z", updatedAt: "2026-10-08T00:00:00Z",
  };
  const definition = {
    id: "transform-consumer", name: "Consume results",
    source: "def transform(inputs, parameters): pass",
    inputSelectors: { items: "/selection/values" },
    outputSchema: { type: "object" }, runtime: "pyodide",
    packageHash: "abc", revision: 3,
  };
  const selection = {
    sourceKind: "resultSet", batchRunId: "batch-source-run",
    outputPath: "/score", selectedCount: 1,
    selectedRecords: [{ datasetRecordId: "row-1", position: 0, input: { beam: "A" }, value: 5 }],
    rule: { limit: 1 },
  };
  const retained = {
    id: "transform-result-run", definitionId: definition.id, status: "succeeded",
    definitionSnapshot: { ...definition, selection }, inputs: { items: [5] },
    parameters: {}, inputHash: "inputhash", sourceHash: "sourcehash",
    packageHash: "abc", runtime: "pyodide", output: { total: 5 },
    outputManifest: {}, error: null,
    initiation: { kind: "directUser", approval: "notRequired" },
    limits: {}, createdAt: "2026-10-08T00:00:00Z",
  };
  const writes: Array<Record<string, unknown>> = [];
  await page.route("**/api/projects", (route) => route.fulfill({ json: [project] }));
  await page.route(`**/api/projects/${project.id}/threads`, (route) => route.fulfill({ json: [] }));
  await page.route(`**/api/projects/${project.id}/datasets`, (route) => route.fulfill({ json: [] }));
  await page.route(`**/api/projects/${project.id}/transforms`, (route) => route.fulfill({ json: [definition] }));
  await page.route(`**/api/projects/${project.id}/transforms/runs?**`, (route) =>
    route.fulfill({ json: { items: [], nextOffset: null } }));
  await page.route(`**/api/projects/${project.id}/batch-runs?**`, (route) =>
    route.fulfill({ json: { items: [{
      id: "batch-source-run", definitionId: "batch-definition-1", status: "partial",
      succeededCount: 1, failedCount: 1,
    }], nextOffset: null } }));
  await page.route(`**/api/projects/${project.id}/transforms/${definition.id}/result-set-selection-plan`, (route) => {
    writes.push(route.request().postDataJSON() as Record<string, unknown>);
    return route.fulfill({ json: {
      selection, selectedCount: 1, invocationCount: 1, outputLocation: "Transform Run output",
    } });
  });
  await page.route(`**/api/projects/${project.id}/transforms/${definition.id}/result-set-selection-runs`, (route) => {
    writes.push(route.request().postDataJSON() as Record<string, unknown>);
    return route.fulfill({ status: 201, json: { id: retained.id, status: "succeeded" } });
  });
  await page.route(`**/api/projects/${project.id}/transforms/runs/${retained.id}`, (route) =>
    route.fulfill({ json: retained }));
  await page.goto("/");
  await page.getByRole("button", { name: "Transforms" }).click();
  await page.getByLabel("Input source").selectOption("resultSet");
  await page.getByRole("combobox", { name: "Batch Run Result Set" }).selectOption("batch-source-run");
  await page.getByLabel(/Value path in each result/).fill("/score");
  await page.getByLabel("Maximum records (optional)").fill("1");
  await page.getByRole("button", { name: "Review selection" }).click();
  await expect(page.getByRole("region", { name: "Selection plan" }))
    .toContainText("Batch Result Set batch-so → Transform Run output");
  await page.getByRole("button", { name: "Start selected Run" }).click();
  await expect(page.getByRole("article", { name: "Run dataflow" }))
    .toContainText("Batch Result Set batch-so · 1 values");
  expect(writes).toHaveLength(2);
  expect(writes[0]).toMatchObject({
    sourceRunId: "batch-source-run", outputPath: "/score",
    expectedDefinitionRevision: 3, limit: 1,
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

    await drawer.getByRole("button", { name: "Batch Definitions" }).click();
    const recordSelector = drawer.getByLabel("Cantilever check Dataset Record");
    await expect(recordSelector).toBeVisible();
    await expect(recordSelector).toHaveCSS(
      "background-color",
      "rgb(27, 33, 26)",
    );
    await expect(recordSelector).toHaveCSS("color", "rgb(251, 253, 246)");
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

  await page.route(`**/api/projects/${project.id}/datasets`, async (route) => {
    await route.fulfill({ json: [] });
  });

  await page.goto("/");
  await page.getByRole("button", { name: "Library" }).click();
  await page
    .getByRole("button", { exact: true, name: "Bridge status" })
    .click();
  await expect(
    page.frameLocator('iframe[title="Artifact App"]').locator("#status"),
  ).toHaveText("available");
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

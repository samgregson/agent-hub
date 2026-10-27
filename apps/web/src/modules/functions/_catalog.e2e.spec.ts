import { expect, test, type Locator, type Page } from "@playwright/test";

const project = {
  id: "project-function-preview",
  name: "Function preview",
  createdAt: "2026-10-11T00:00:00Z",
  updatedAt: "2026-10-11T00:00:00Z",
};

const source =
  "def transform(inputs, parameters):\n    return {'value': inputs['load'] * parameters['factor']}\n";

async function prepareFunctionWorkbench(
  page: Page,
  inputSchema: Record<string, unknown> = {
    type: "object",
    description: "Double one load value and return the result.",
    properties: {
      load: {
        type: "number",
        minimum: 0,
        description: "Load in kilonewtons.",
      },
    },
    required: ["load"],
  },
) {
  await page.route("**/api/projects", (route) =>
    route.fulfill({ json: [project] }),
  );
  await page.route(`**/api/projects/${project.id}/threads`, (route) =>
    route.fulfill({ json: [] }),
  );
  await page.route(`**/api/projects/${project.id}/datasets`, (route) =>
    route.fulfill({ json: [] }),
  );
  await page.route(`**/api/projects/${project.id}/functions`, (route) =>
    route.fulfill({
      json: [
        {
          id: "function-1",
          name: "Double load",
          source,
          inputSchema,
          outputSchema: {
            type: "object",
            properties: {
              value: { type: "number", description: "Calculated result." },
            },
          },
          runtime: "deno:2.9.7;pyodide:314.0.7",
          packageHash: "package-hash",
          revision: 2,
        },
      ],
    }),
  );
  await page.goto("/");
}

async function openFunctions(page: Page, phone: boolean) {
  let surface: Page | Locator = page;
  if (phone) {
    await page.setViewportSize({ width: 390, height: 844 });
    await page.getByRole("button", { name: "Open Project navigation" }).click();
    surface = page.getByRole("dialog", { name: "Project navigation" });
  }
  await surface
    .getByRole("navigation", { name: "Project views" })
    .getByRole("button", { name: "Functions" })
    .click();
  return surface;
}

test("Function preview shows its captured source, inputs, and host runtime", async ({
  page,
}) => {
  const previews: Array<Record<string, unknown>> = [];
  let previewCount = 0;
  let releaseSlowPreview = () => {};
  let slowPreviewRequested = false;
  await prepareFunctionWorkbench(page);
  await page.route(
    `**/api/projects/${project.id}/functions/function-1/preview`,
    async (route) => {
      previews.push(route.request().postDataJSON() as Record<string, unknown>);
      previewCount += 1;
      if (previewCount === 1) {
        await new Promise<void>((resolve) => {
          releaseSlowPreview = resolve;
          slowPreviewRequested = true;
        });
        await route.fulfill({
          json: {
            output: { value: 8 },
            runtime: "deno:2.9.7;pyodide:314.0.7",
            sourceHash: "sha256:source-2",
          },
        });
        return;
      }
      if (previewCount === 2) {
        await route.fulfill({
          status: 504,
          json: { detail: "Preview exceeded the time limit." },
        });
        return;
      }
      await route.fulfill({
        json: {
          output: { value: 10 },
          runtime: "deno:2.9.7;pyodide:314.0.7",
          sourceHash: "sha256:source-2",
        },
      });
    },
  );
  const surface = await openFunctions(page, false);
  await expect(
    surface.getByRole("heading", { name: "Double load", exact: true }),
  ).toBeVisible();
  await expect(
    surface.getByRole("region", { name: "Function contract" }),
  ).toContainText("Double one load value and return the result.");
  await expect(
    surface.getByRole("region", { name: "Function contract" }),
  ).toContainText("Load in kilonewtons.");
  await surface.getByLabel("load · required").fill("4");
  await surface.getByText("Advanced: optional Function parameters").click();
  await surface.getByLabel("Parameters (JSON object)").fill('{"factor":2}');
  await surface.getByRole("button", { name: "Preview output" }).click();
  await expect.poll(() => slowPreviewRequested).toBe(true);
  await page.waitForTimeout(5_200);
  await expect(surface.getByRole("status")).toContainText(
    "taking longer than usual",
  );
  releaseSlowPreview();

  const preview = surface.getByRole("region", { name: "Preview output" });
  await expect(preview).toContainText("Preview · transient, not saved");
  await expect(preview).toContainText(
    "Runtime identity: deno:2.9.7;pyodide:314.0.7",
  );
  await expect(preview).toContainText("Source SHA-256: sha256:source-2");
  await preview.getByText("Technical details and full values").click();
  await expect(preview).toContainText(source);
  await expect(preview).toContainText('"load": 4');
  await expect(preview).toContainText('"factor": 2');
  await expect(preview).toContainText('"value": 8');
  await surface.getByLabel("load · required").fill("5");
  await expect(preview).toHaveCount(0);
  await surface.getByRole("button", { name: "Preview output" }).click();
  await expect(surface.locator("p[role=alert]")).toContainText(
    "Preview exceeded the time limit.",
  );
  await expect(surface.getByLabel("load · required")).toHaveValue("5");
  await surface.getByRole("button", { name: "Retry preview" }).click();
  await expect(
    surface.getByRole("region", { name: "Preview output" }),
  ).toContainText('"value": 10');
  expect(previews).toEqual([
    { inputs: { load: 4 }, parameters: { factor: 2 } },
    { inputs: { load: 5 }, parameters: { factor: 2 } },
    { inputs: { load: 5 }, parameters: { factor: 2 } },
  ]);
});

test("Function preview explains invalid schema-driven values beside the field", async ({
  page,
}) => {
  let previewCalls = 0;
  await prepareFunctionWorkbench(page);
  await page.route(
    `**/api/projects/${project.id}/functions/function-1/preview`,
    async (route) => {
      previewCalls += 1;
      await route.fulfill({
        json: { output: { value: 0 }, runtime: "test", sourceHash: "hash" },
      });
    },
  );
  const surface = await openFunctions(page, false);
  await surface.getByLabel("load · required").fill("-1");
  await surface.getByRole("button", { name: "Preview output" }).click();
  await expect(surface.getByText("Use 0 or more.")).toBeVisible();
  expect(previewCalls).toBe(0);
});

test("Function preview form edits nested objects and arrays without JSON", async ({
  page,
}) => {
  let capturedInputs: unknown;
  await prepareFunctionWorkbench(page, {
    type: "object",
    description: "Summarize the named site and its loads.",
    properties: {
      site: {
        type: "object",
        description: "Site details.",
        properties: {
          name: { type: "string", description: "Name shown in the report." },
        },
        required: ["name"],
      },
      loads: {
        type: "array",
        description: "Loads to include.",
        minItems: 1,
        items: {
          type: "number",
          minimum: 0,
          description: "Load in kilonewtons.",
        },
      },
    },
    required: ["site", "loads"],
  });
  await page.route(
    `**/api/projects/${project.id}/functions/function-1/preview`,
    async (route) => {
      capturedInputs = route.request().postDataJSON().inputs;
      await route.fulfill({
        json: { output: { value: 1 }, runtime: "test", sourceHash: "hash" },
      });
    },
  );
  const surface = await openFunctions(page, false);
  await surface.getByLabel("name · required").fill("North site");
  await surface.getByRole("button", { name: "Add item" }).click();
  await surface.getByLabel("Item 3 · required").fill("12.5");
  await surface.getByRole("button", { name: "Preview output" }).click();
  await expect(
    surface.getByRole("region", { name: "Preview output" }),
  ).toBeVisible();
  expect(capturedInputs).toEqual({
    site: { name: "North site" },
    loads: [0, 1, 12.5],
  });
});

test("Function preview workbench remains reachable at phone width", async ({
  page,
}) => {
  await prepareFunctionWorkbench(page);
  await page.route(
    `**/api/projects/${project.id}/functions/function-1/preview`,
    (route) =>
      route.fulfill({
        json: {
          output: { value: 6 },
          runtime: "deno:2.9.7;pyodide:314.0.7",
          sourceHash: "sha256:source-2",
        },
      }),
  );
  const surface = await openFunctions(page, true);
  await surface.getByRole("button", { name: "Preview output" }).click();
  const preview = surface.getByRole("region", { name: "Preview output" });
  await expect(preview).toContainText("Runtime identity");
  expect(
    await page.evaluate(
      () =>
        document.documentElement.scrollWidth >
        document.documentElement.clientWidth,
    ),
  ).toBe(false);
});

test("new Function submissions include their named input schema", async ({
  page,
}) => {
  await prepareFunctionWorkbench(page);
  const surface = await openFunctions(page, false);
  await surface.getByRole("button", { name: "New Function" }).click();
  await surface.getByLabel("Name").fill("Read a load");
  await surface.getByLabel("Input schema (JSON Schema)").fill(
    JSON.stringify({
      type: "object",
      properties: { load: { type: "number", minimum: 0 } },
      required: ["load"],
      additionalProperties: false,
    }),
  );

  let submitted: Record<string, unknown> | null = null;
  await page.route(`**/api/projects/${project.id}/functions`, async (route) => {
    if (route.request().method() !== "POST") {
      await route.fulfill({ json: [] });
      return;
    }
    submitted = route.request().postDataJSON() as Record<string, unknown>;
    await route.fulfill({
      status: 201,
      json: {
        id: "function-new",
        name: "Read a load",
        source,
        inputSchema: submitted.inputSchema,
        outputSchema: { type: "object" },
        runtime: "deno:2.9.7;pyodide:314.0.7",
        packageHash: "package-hash",
        sourceHash: "source-hash",
        revision: 1,
        createdAt: "2026-10-11T00:00:00Z",
        updatedAt: "2026-10-11T00:00:00Z",
      },
    });
  });
  await surface.getByRole("button", { name: "Save Function" }).click();
  await expect(
    surface.getByText("Read a load saved as revision 1.", { exact: true }),
  ).toBeVisible();
  expect(submitted).toMatchObject({
    inputSchema: {
      type: "object",
      properties: { load: { type: "number", minimum: 0 } },
      required: ["load"],
      additionalProperties: false,
    },
  });
});

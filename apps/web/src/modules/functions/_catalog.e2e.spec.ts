import { expect, test, type Locator, type Page } from "@playwright/test";

const project = {
  id: "project-function-preview",
  name: "Function preview",
  createdAt: "2026-10-11T00:00:00Z",
  updatedAt: "2026-10-11T00:00:00Z",
};

const source =
  "def transform(inputs, parameters):\n    return {'value': inputs['load'] * parameters['factor']}\n";

async function prepareFunctionWorkbench(page: Page) {
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
          inputSchema: {
            type: "object",
            properties: { load: { type: "number" } },
            required: ["load"],
          },
          outputSchema: { type: "object" },
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
  await prepareFunctionWorkbench(page);
  await page.route(
    `**/api/projects/${project.id}/functions/function-1/preview`,
    async (route) => {
      previews.push(route.request().postDataJSON() as Record<string, unknown>);
      previewCount += 1;
      if (previewCount === 1) {
        await route.fulfill({
          json: {
            output: { value: 8 },
            runtime: "deno:2.9.7;pyodide:314.0.7",
            sourceHash: "sha256:source-2",
          },
        });
        return;
      }
      await route.fulfill({
        status: 504,
        json: { detail: "Preview exceeded the time limit." },
      });
    },
  );
  const surface = await openFunctions(page, false);
  await expect(
    surface.getByRole("heading", { name: "Double load", exact: true }),
  ).toBeVisible();
  await surface.getByLabel("Function inputs (JSON object)").fill('{"load":4}');
  await surface.getByLabel("Parameters (JSON object)").fill('{"factor":2}');
  await surface.getByRole("button", { name: "Preview output" }).click();

  const preview = surface.getByRole("region", { name: "Preview output" });
  await expect(preview).toContainText("Preview · transient, not saved");
  await expect(preview).toContainText(
    "Runtime identity: deno:2.9.7;pyodide:314.0.7",
  );
  await expect(preview).toContainText("Source SHA-256: sha256:source-2");
  await preview.getByText("Captured source and inputs").click();
  await expect(preview).toContainText(source);
  await expect(preview).toContainText('"load": 4');
  await expect(preview).toContainText('"factor": 2');
  await expect(preview).toContainText('"value": 8');
  expect(previews).toEqual([
    { inputs: { load: 4 }, parameters: { factor: 2 } },
  ]);

  await surface.getByLabel("Function inputs (JSON object)").fill('{"load":5}');
  await expect(preview).toHaveCount(0);
  await surface.getByRole("button", { name: "Preview output" }).click();
  await expect(surface.locator("p[role=alert]")).toContainText(
    "Preview exceeded the time limit.",
  );
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

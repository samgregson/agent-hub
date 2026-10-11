import { expect, test } from "@playwright/test";

const project = {
  id: "project-calls",
  name: "Call review",
  createdAt: "2026-10-11T00:00:00Z",
  updatedAt: "2026-10-11T00:00:00Z",
};

for (const target of ["Python Function", "MCP tool"] as const) {
  for (const shape of ["Single call", "Map Dataset"] as const) {
    test(`${target} ${shape} shares the reviewed call journey`, async ({
      page,
    }) => {
      const writes: Array<{ path: string; body: Record<string, unknown> }> = [];
      await page.route("**/api/projects", (route) =>
        route.fulfill({ json: [project] }),
      );
      await page.route(`**/api/projects/${project.id}/threads`, (route) =>
        route.fulfill({ json: [] }),
      );
      await page.route(`**/api/projects/${project.id}/transforms`, (route) =>
        route.fulfill({
          json: [{ id: "function-1", name: "Normalize", revision: 4 }],
        }),
      );
      await page.route(`**/api/projects/${project.id}/datasets`, (route) =>
        route.fulfill({
          json: [{ id: "dataset-1", name: "Samples", version: 3 }],
        }),
      );
      await page.route(`**/api/projects/${project.id}/plugins`, (route) =>
        route.fulfill({
          json: [
            {
              id: "plugin-1",
              name: "Calculator",
              version: "2",
              enabled: true,
              tools: [{ name: "evaluate", readOnly: true }],
            },
          ],
        }),
      );
      const routeName =
        target === "Python Function"
          ? shape === "Single call"
            ? "transforms/function-1/call"
            : "batch-runs/python-map"
          : shape === "Single call"
            ? "batch-runs/mcp-call"
            : "batch-runs/mcp-map";
      const isMap = shape === "Map Dataset";
      const isPython = target === "Python Function";
      await page.route(
        `**/api/projects/${project.id}/${routeName}/plan`,
        (route) => {
          writes.push({
            path: "plan",
            body: route.request().postDataJSON() as Record<string, unknown>,
          });
          return route.fulfill({
            json: {
              callKind: isPython
                ? isMap
                  ? "pythonMap"
                  : "pythonFunction"
                : isMap
                  ? "mcpMap"
                  : "mcpCall",
              definitionId: isPython ? "function-1" : undefined,
              definitionRevision: isPython ? 4 : undefined,
              name: isPython ? "Normalize" : undefined,
              pluginId: isPython ? undefined : "plugin-1",
              pluginVersion: isPython ? undefined : "2",
              toolName: isPython ? undefined : "evaluate",
              datasetId: isMap ? "dataset-1" : undefined,
              datasetVersion: isMap ? 3 : undefined,
              inputs: isMap
                ? [{ value: 2 }, { value: 3 }]
                : { item: { value: 2 } },
              boundInputs:
                isPython && isMap
                  ? [
                      { recordId: "record-1", inputs: { item: { value: 2 } } },
                      { recordId: "record-2", inputs: { item: { value: 3 } } },
                    ]
                  : undefined,
              recordIds: isMap ? ["record-1", "record-2"] : undefined,
              parameters: isPython ? {} : undefined,
              runtime: isPython ? "pyodide" : undefined,
              sourceHash: isPython && isMap ? "sourcehash" : undefined,
              packageHash: isPython ? "packagehash" : undefined,
              invocationCount: isMap ? 2 : 1,
              outputKind:
                isPython && !isMap ? "transformRun" : "batchResultSet",
              review: {
                target: {
                  kind: isPython ? "python" : "mcp",
                  id: isPython ? "function-1" : "plugin-1/evaluate",
                  version: isPython ? 4 : "2",
                  name: isPython ? "Normalize" : "evaluate",
                },
                shape: isMap ? "map" : "single",
                source: isMap
                  ? { kind: "dataset", id: "dataset-1", version: 3 }
                  : { kind: "direct" },
                inputPorts: { item: {} },
                outputPorts: { result: { type: "object" } },
                bindings: isMap
                  ? [
                      { recordId: "record-1", inputs: { item: { value: 2 } } },
                      { recordId: "record-2", inputs: { item: { value: 3 } } },
                    ]
                  : [{ inputs: { item: { value: 2 } } }],
                invocationCount: isMap ? 2 : 1,
                maxInvocations: isMap ? 100 : 1,
                outputKind:
                  isPython && !isMap ? "transformRun" : "batchResultSet",
                agentApproval: "required",
              },
            },
          });
        },
      );
      await page.route(
        `**/api/projects/${project.id}/${routeName}`,
        (route) => {
          writes.push({
            path: "start",
            body: route.request().postDataJSON() as Record<string, unknown>,
          });
          return route.fulfill({
            status: 201,
            json: {
              id: isPython && !isMap ? "transform-run" : "batch-run",
              status: isPython && !isMap ? "succeeded" : "queued",
            },
          });
        },
      );
      await page.route(
        `**/api/projects/${project.id}/transforms/runs/transform-run`,
        (route) =>
          route.fulfill({
            json: {
              id: "transform-run",
              status: "succeeded",
              inputs: { item: { value: 2 } },
              output: { answer: 4 },
              error: null,
            },
          }),
      );
      await page.route(
        `**/api/projects/${project.id}/batch-runs/batch-run`,
        (route) =>
          route.fulfill({ json: { id: "batch-run", status: "partial" } }),
      );
      await page.route(
        `**/api/projects/${project.id}/batch-runs/batch-run/results?**`,
        (route) =>
          route.fulfill({
            json: {
              items: [
                {
                  datasetRecordId: "record-1",
                  input: { value: 2 },
                  structuredOutput: { answer: 4 },
                  error: null,
                },
                {
                  datasetRecordId: "record-2",
                  input: { value: 3 },
                  structuredOutput: null,
                  error: "Rejected",
                },
              ],
              nextOffset: null,
              summary: { totalCount: 2, succeededCount: 1, failedCount: 1 },
            },
          }),
      );

      await page.goto("/");
      if (isMap && !isPython) {
        await page.setViewportSize({ width: 390, height: 844 });
        await page
          .getByRole("button", { name: "Open Project navigation" })
          .click();
      }
      const surface =
        isMap && !isPython
          ? page.getByRole("dialog", { name: "Project navigation" })
          : page;
      await surface
        .getByRole("navigation", { name: "Project views" })
        .getByRole("button", { name: "Operations" })
        .click();
      await surface
        .getByRole("navigation", { name: "Operation types" })
        .getByRole("button", { name: "Calls" })
        .click();
      await surface
        .getByRole("combobox", { name: "Target kind" })
        .selectOption(target === "Python Function" ? "python" : "mcp");
      await surface
        .getByRole("combobox", { name: "Call shape" })
        .selectOption(isMap ? "map" : "single");
      if (isPython)
        await surface
          .getByRole("combobox", { name: "Function" })
          .selectOption("function-1");
      else {
        await surface
          .getByRole("combobox", { name: "Plugin" })
          .selectOption("plugin-1");
        await surface
          .getByRole("combobox", { name: "Tool" })
          .selectOption("evaluate");
      }
      if (isMap)
        await surface
          .getByRole("combobox", { name: "Dataset" })
          .selectOption("dataset-1");
      else
        await surface
          .getByRole("textbox", {
            name: isPython ? "Inputs (JSON object)" : "Arguments (JSON object)",
          })
          .fill('{"item":{"value":2}}');
      await surface.getByRole("button", { name: "Review Call" }).click();
      const review = surface.getByRole("region", { name: "Call review" });
      await expect(review).toContainText(isPython ? "Normalize" : "evaluate");
      await expect(review).toContainText(
        isMap ? "2 invocations" : "1 invocation",
      );
      if (isMap) await expect(review).toContainText("Samples · Dataset v3");
      await review.getByRole("button", { name: "Start Call" }).click();
      const result = surface.getByRole("region", { name: "Call result" });
      await expect(result).toContainText(
        isPython && !isMap ? '"answer": 4' : "1 succeeded · 1 failed",
      );
      await expect(result).toContainText(isPython ? "Normalize" : "evaluate");
      await result.getByText("Captured call").click();
      await expect(result).toContainText(isMap ? "dataset-1" : "item");
      expect(writes.map((write) => write.path)).toEqual(["plan", "start"]);
      if (isMap) {
        expect(writes[1].body).toMatchObject({ expectedDatasetVersion: 3 });
        expect(writes[1].body).toMatchObject(
          isPython
            ? { expectedDefinitionRevision: 4 }
            : { expectedPluginVersion: "2" },
        );
      } else if (isPython) {
        expect(writes[1].body).toMatchObject({ expectedRevision: 4 });
      } else {
        expect(writes[1].body).toMatchObject({ expectedPluginVersion: "2" });
      }
    });
  }
}

test("invalid arguments and a stale MCP version stay explicit without a Run", async ({
  page,
}) => {
  let reviews = 0;
  let starts = 0;
  await page.route("**/api/projects", (route) =>
    route.fulfill({ json: [project] }),
  );
  await page.route(`**/api/projects/${project.id}/threads`, (route) =>
    route.fulfill({ json: [] }),
  );
  await page.route(`**/api/projects/${project.id}/transforms`, (route) =>
    route.fulfill({ json: [] }),
  );
  await page.route(`**/api/projects/${project.id}/datasets`, (route) =>
    route.fulfill({ json: [] }),
  );
  await page.route(`**/api/projects/${project.id}/plugins`, (route) =>
    route.fulfill({
      json: [
        {
          id: "plugin-1",
          name: "Calculator",
          version: "2",
          enabled: true,
          tools: [{ name: "evaluate", readOnly: true }],
        },
      ],
    }),
  );
  const base = `**/api/projects/${project.id}/batch-runs/mcp-call`;
  await page.route(`${base}/plan`, (route) => {
    reviews += 1;
    return route.fulfill({
      json: {
        callKind: "mcpCall",
        pluginId: "plugin-1",
        pluginVersion: "2",
        toolName: "evaluate",
        inputs: { load: 2 },
        invocationCount: 1,
        outputKind: "batchResultSet",
        review: {
          target: {
            kind: "mcp",
            id: "plugin-1/evaluate",
            version: "2",
            name: "evaluate",
          },
          shape: "single",
          source: { kind: "direct" },
          inputPorts: { load: { type: "number" } },
          outputPorts: { result: { type: "object" } },
          bindings: [{ inputs: { load: 2 } }],
          invocationCount: 1,
          maxInvocations: 1,
          outputKind: "batchResultSet",
          agentApproval: "required",
        },
      },
    });
  });
  await page.route(base, (route) => {
    starts += 1;
    return route.fulfill({
      status: 409,
      json: { detail: "MCP tool version changed; review the call again." },
    });
  });
  await page.goto("/");
  await page
    .getByRole("navigation", { name: "Project views" })
    .getByRole("button", { name: "Operations" })
    .click();
  await page
    .getByRole("navigation", { name: "Operation types" })
    .getByRole("button", { name: "Calls" })
    .click();
  await page.getByRole("combobox", { name: "Target kind" }).selectOption("mcp");
  await page.getByRole("combobox", { name: "Plugin" }).selectOption("plugin-1");
  await page.getByRole("combobox", { name: "Tool" }).selectOption("evaluate");
  const argumentsField = page.getByRole("textbox", {
    name: "Arguments (JSON object)",
  });
  await argumentsField.fill("[2]");
  await page.getByRole("button", { name: "Review Call" }).click();
  await expect(
    page.getByRole("region", { name: "Calls" }).getByRole("alert"),
  ).toContainText("Arguments must be a JSON object.");
  expect(reviews).toBe(0);
  await argumentsField.fill('{"load":2}');
  await page.getByRole("button", { name: "Review Call" }).click();
  await expect(page.getByRole("region", { name: "Call review" })).toContainText(
    "evaluate",
  );
  await page.getByRole("button", { name: "Start Call" }).click();
  await expect(
    page.getByRole("region", { name: "Calls" }).getByRole("alert"),
  ).toContainText("MCP tool version changed");
  await expect(page.getByRole("region", { name: "Call result" })).toHaveCount(
    0,
  );
  expect(reviews).toBe(1);
  expect(starts).toBe(1);
});

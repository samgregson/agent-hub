import { readFileSync, existsSync } from "node:fs";
import { expect, test } from "@playwright/test";

const artifactPath = process.env.AGENT_HUB_IFC_SMOKE_ARTIFACT;
const appPath = "../../plugins/ifc-viewer/app/dist/index.html";
test("the IFC main-agent result renders inside Agent Hub", async ({ page }) => {
  test.skip(
    !artifactPath || !existsSync(appPath),
    "Requires the independent IFC build and main-agent smoke Artifact",
  );
  const document = JSON.parse(readFileSync(artifactPath!, "utf8"));
  const artifactId = document.artifact.id;
  const output = document.payload.output;
  const globalId = output.metadata[0].globalId;
  const project = {
    id: "ifc-smoke-project",
    name: "IFC review",
    createdAt: "2026-10-31T00:00:00Z",
    updatedAt: "2026-10-31T00:00:00Z",
  };
  const errors: string[] = [];
  page.on("pageerror", (error) => errors.push(error.message));
  await page.route("**/api/projects", (route) =>
    route.fulfill({ json: [project] }),
  );
  await page.route(`**/api/projects/${project.id}/**`, (route) => {
    const path = new URL(route.request().url()).pathname;
    if (path.endsWith(`/artifacts/${artifactId}/app`))
      return route.fulfill({
        body: readFileSync(appPath, "utf8"),
        contentType: "text/html",
        headers: {
          "Content-Security-Policy":
            "default-src 'none'; base-uri 'none'; connect-src 'none'; font-src data:; form-action 'none'; frame-ancestors 'self'; frame-src 'none'; img-src data:; script-src 'unsafe-inline' 'wasm-unsafe-eval'; style-src 'unsafe-inline'",
        },
      });
    if (path.endsWith(`/artifacts/${artifactId}`))
      return route.fulfill({ json: document });
    if (path.endsWith("/artifacts"))
      return route.fulfill({
        json: {
          artifacts: [
            {
              id: artifactId,
              title: document.artifact.title,
              type: document.artifact.type,
              documentVersion: 1,
              pluginId: "ifc-viewer",
              pluginVersion: "0.1.0",
            },
          ],
        },
      });
    if (path.endsWith("/files/index"))
      return route.fulfill({ json: { files: [] } });
    if (path.endsWith("/workflows"))
      return route.fulfill({ json: { definitions: [] } });
    return route.fulfill({ json: [] });
  });
  await page.setViewportSize({ width: 1440, height: 1000 });
  await page.goto("/");
  await page.getByRole("button", { name: "Library", exact: true }).click();
  await page
    .getByRole("button", { name: document.artifact.title, exact: true })
    .click();
  const app = page.frameLocator('iframe[title="Artifact App"]');
  await app
    .getByLabel("Object", { exact: true })
    .selectOption(globalId, { timeout: 30000 });
  await expect(app.getByRole("heading", { name: "Beam B-01" })).toBeVisible();
  await expect(app.locator("canvas")).toBeVisible();
  await expect(app.getByLabel("Colour by", { exact: true })).toHaveValue(
    "status",
  );
  await expect(
    app.getByLabel("Object metadata").locator("pre").first(),
  ).toContainText(JSON.stringify(output.metadata[0].values.status));
  if (output.metadata[0].values.deflection_mm !== undefined) {
    await expect(
      app.getByLabel("Object metadata").locator("pre").first(),
    ).toContainText("deflection_mm");
  }
  const iframe = page.locator('iframe[title="Artifact App"]');
  expect((await iframe.boundingBox())!.width).toBeGreaterThan(900);
  expect((await iframe.boundingBox())!.height).toBeGreaterThan(650);
  await app
    .locator("canvas")
    .evaluate(
      () =>
        new Promise<void>((resolve) =>
          requestAnimationFrame(() => requestAnimationFrame(() => resolve())),
        ),
    );
  await page.screenshot({ path: "/tmp/agent-hub-ifc-inline.png" });
  await app.getByLabel("Metadata name", { exact: true }).fill("reviewNote");
  await app.getByLabel("Value", { exact: true }).fill("Check connections");
  await app.getByRole("button", { name: "Assign to selected object" }).click();
  await app.locator("body").evaluate((body) => {
    body.dataset.smokeState = "preserve-frame";
  });
  await page.getByRole("button", { name: "Expand App", exact: true }).click();
  await expect(
    page.getByRole("dialog", { name: document.artifact.title, exact: true }),
  ).toBeVisible();
  expect((await iframe.boundingBox())!.width).toBeGreaterThan(1300);
  expect((await iframe.boundingBox())!.height).toBeGreaterThan(850);
  await expect(app.locator("body")).toHaveAttribute(
    "data-smoke-state",
    "preserve-frame",
  );
  await expect(app.getByLabel("Value", { exact: true })).toHaveValue(
    "Check connections",
  );
  await expect(app.locator("html")).toHaveAttribute("data-theme", "dark");
  await app.locator("canvas").scrollIntoViewIfNeeded();
  await app
    .locator("canvas")
    .evaluate(
      () =>
        new Promise<void>((resolve) =>
          requestAnimationFrame(() => requestAnimationFrame(() => resolve())),
        ),
    );
  await page.screenshot({ path: "/tmp/agent-hub-ifc-expanded.png" });
  await app.getByLabel("Value", { exact: true }).focus();
  await page.keyboard.press("Escape");
  await expect(
    page.getByRole("button", { name: "Expand App", exact: true }),
  ).toBeFocused();
  await expect(app.getByLabel("Value", { exact: true })).toHaveValue(
    "Check connections",
  );
  await expect(app.locator("body")).toHaveAttribute(
    "data-smoke-state",
    "preserve-frame",
  );
  await page.setViewportSize({ width: 390, height: 844 });
  await page.getByRole("button", { name: "Expand App", exact: true }).click();
  await expect(
    page.getByRole("dialog", { name: document.artifact.title, exact: true }),
  ).toBeVisible();
  expect((await iframe.boundingBox())!.width).toBeGreaterThan(350);
  expect(
    await page
      .locator("body")
      .evaluate((body) => body.scrollWidth <= body.clientWidth),
  ).toBe(true);
  expect(
    await app
      .locator("body")
      .evaluate((body) => body.scrollWidth <= body.clientWidth),
  ).toBe(true);
  await app.locator("canvas").scrollIntoViewIfNeeded();
  await page.screenshot({ path: "/tmp/agent-hub-ifc-mobile.png" });
  await page
    .getByRole("button", { name: "Close expanded App", exact: true })
    .click();
  await expect(
    page.getByRole("button", { name: "Expand App", exact: true }),
  ).toBeFocused();
  expect(errors).toEqual([]);
});

test("a saved IFC Workflow output opens its App without rerunning tools", async ({
  page,
}) => {
  const workflowPath = `${artifactPath}.workflow.json`;
  test.skip(
    !artifactPath || !existsSync(workflowPath) || !existsSync(appPath),
    "Requires the real engineering Workflow smoke output",
  );
  const captured = JSON.parse(readFileSync(workflowPath, "utf8"));
  const workflow = { ...captured.workflow, id: captured.workflow.workflowId };
  const run = {
    ...captured.run,
    id: captured.run.runId,
    definitionVersion: workflow.version,
    createdAt: "2026-10-31T00:00:00Z",
  };
  const output = run.execution.outputs.view;
  const project = {
    id: "workflow-app-project",
    name: "IFC Workflow",
    createdAt: "2026-10-31T00:00:00Z",
    updatedAt: "2026-10-31T00:00:00Z",
  };
  const writes: string[] = [];
  let appAvailable = true;
  await page.route("**/api/**", (route) => {
    const path = new URL(route.request().url()).pathname;
    if (route.request().method() !== "GET") {
      writes.push(path);
      return route.fulfill({ status: 405 });
    }
    if (path === "/api/projects") return route.fulfill({ json: [project] });
    if (path.endsWith("/outputs/view/app"))
      return appAvailable
        ? route.fulfill({
            body: readFileSync(appPath, "utf8"),
            contentType: "text/html",
            headers: {
              "Content-Security-Policy":
                "default-src 'none'; base-uri 'none'; connect-src 'none'; font-src data:; form-action 'none'; frame-ancestors 'self'; frame-src 'none'; img-src data:; script-src 'unsafe-inline' 'wasm-unsafe-eval'; style-src 'unsafe-inline'",
            },
          })
        : route.fulfill({
            status: 422,
            json: { detail: "Captured App unavailable" },
          });
    if (path.endsWith("/workflows")) return route.fulfill({ json: [workflow] });
    if (path.endsWith("/runs")) return route.fulfill({ json: [run] });
    if (path.endsWith("/files/index"))
      return route.fulfill({ json: { files: [] } });
    return route.fulfill({ json: [] });
  });
  await page.setViewportSize({ width: 1440, height: 1000 });
  await page.goto("/");
  await expect(
    page.getByRole("heading", { name: workflow.name }),
  ).toBeVisible();
  const outputs = page.getByRole("region", { name: "Workflow outputs" });
  await outputs.getByRole("button", { name: "Open App", exact: true }).click();
  const app = page.frameLocator('iframe[title="Workflow output App"]');
  await app
    .getByLabel("Object", { exact: true })
    .selectOption(output.metadata[0].globalId);
  await expect(app.getByRole("heading", { name: "Beam B-01" })).toBeVisible();
  await expect(app.getByLabel("Colour by", { exact: true })).toHaveValue(
    "status",
  );
  const metadata = app.getByLabel("Object metadata").locator("pre").first();
  await expect(metadata).toContainText('"status": "fails"');
  await expect(metadata).toContainText("deflection_mm");
  await outputs
    .getByRole("button", { name: "Expand App", exact: true })
    .click();
  await expect(
    page.getByRole("dialog", { name: "view", exact: true }),
  ).toBeVisible();
  await expect(metadata).toContainText('"status": "fails"');
  await page.screenshot({ path: "/tmp/agent-hub-ifc-workflow-expanded.png" });
  await page.getByRole("button", { name: "Close expanded App" }).click();
  await outputs.getByText("Output data", { exact: true }).click();
  await expect(outputs).toContainText("ISO-10303-21;");
  await outputs.getByRole("button", { name: "Close App", exact: true }).click();
  appAvailable = false;
  await outputs.getByRole("button", { name: "Open App", exact: true }).click();
  await expect(outputs.getByRole("status")).toContainText("no interactive App");
  await expect(outputs).toContainText("ISO-10303-21;");
  expect(writes).toEqual([]);
});

import { expect, test } from "@playwright/test";

test("Project opens on a branching Workflow and retains iteration history", async ({
  page,
}) => {
  await page.goto("/prototype/project-explorer");
  await expect(
    page.getByRole("button", { name: "E · Workflow first" }),
  ).toHaveAttribute("aria-pressed", "true");
  await expect(
    page.getByRole("heading", { name: "Design review" }),
  ).toBeVisible();
  await expect(page.getByLabel("Read-only dependency map")).toBeVisible();
  await expect(
    page.getByLabel("Read-only dependency map").getByRole("button"),
  ).toHaveCount(6);
  await page.getByRole("button", { name: "Outline", exact: true }).click();
  await expect(page.getByLabel("Dependency outline")).toBeVisible();
  await expect(
    page
      .getByLabel("Dependency outline")
      .getByRole("button", { name: /Draft review/ }),
  ).toContainText("Select findings + Extract criteria");
  await expect(page.getByText("Workflow Run 1", { exact: true })).toBeVisible();
  await page.getByRole("combobox", { name: "Input set" }).selectOption("2");
  await page.getByRole("button", { name: "Run Workflow" }).click();
  await expect(page.getByText("Workflow Run 2", { exact: true })).toBeVisible();
  await expect(
    page.getByText("Completed · 1 finding · no tool errors"),
  ).toBeVisible();
  await expect(page.getByText(/selected findings 2 → 1/)).toBeVisible();
  await page
    .getByLabel("Dependency outline")
    .getByText("Select findings", { exact: true })
    .click();
  await expect(
    page.getByRole("region", { name: "Selected Workflow node" }),
  ).toContainText("1 finding selected");
  await page.getByRole("button", { name: "Inspect captured record" }).click();
  await expect(
    page.getByRole("button", { name: "Close captured record" }),
  ).toBeVisible();
  await page.getByRole("button", { name: /Run 1 · input revision 1/ }).click();
  await expect(page.getByText("Workflow Run 1", { exact: true })).toBeVisible();
  await expect(
    page.getByText("Completed · 2 findings · no tool errors"),
  ).toBeVisible();
});

test("phone Workflow shows dependencies and one primary node detail", async ({
  page,
}) => {
  await page.setViewportSize({ width: 390, height: 844 });
  await page.goto("/prototype/project-explorer?variant=E");
  await expect(
    page.getByRole("region", { name: "Selected Workflow node" }),
  ).toBeHidden();
  await page
    .getByLabel("Dependency outline")
    .getByRole("button", { name: /Draft review/ })
    .click();
  await expect(
    page.getByRole("region", { name: "Selected Workflow node" }),
  ).toBeVisible();
  await expect(
    page.getByRole("region", { name: "Workflow dependencies" }),
  ).toBeHidden();
  await expect(
    page.getByRole("region", { name: "Selected Workflow node" }),
  ).toContainText("Select findings + Extract criteria");
  await page.getByRole("button", { name: "Back to Workflow" }).click();
  await expect(
    page.getByRole("region", { name: "Workflow dependencies" }),
  ).toBeVisible();
  await page.getByRole("button", { name: "Edit workflow" }).click();
  await expect(page.getByLabel("Workflow definition map")).toBeHidden();
  await expect(page.getByLabel("Workflow definition outline")).toBeVisible();
});

test("Workflow creation connects Data definitions to editable dependencies", async ({
  page,
}) => {
  await page.goto("/prototype/project-explorer?variant=E");
  await page.getByRole("button", { name: "Edit workflow" }).click();
  await expect(page.getByLabel("Workflow editor")).toBeVisible();
  await expect(page.getByLabel("Workflow definition map")).toBeVisible();
  await expect(
    page.locator('path[data-from="findings"][data-to="review"]'),
  ).toHaveCount(1);
  await expect(
    page.getByRole("region", { name: "Workflow definition", exact: true }),
  ).toContainText("Select findings + Extract criteria");
  await page
    .getByRole("region", { name: "Workflow definition", exact: true })
    .getByRole("button", { name: /Draft review/ })
    .click();
  await page
    .getByLabel("Add workflow step")
    .getByLabel("Evaluate records")
    .check();
  await page.getByRole("button", { name: "Save step bindings" }).click();
  await expect(
    page.locator('path[data-from="evaluate"][data-to="review"]'),
  ).toHaveCount(1);
  await expect(
    page.getByRole("region", { name: "Workflow definition", exact: true }),
  ).toContainText("Select findings + Extract criteria + Evaluate records");
  await page.getByRole("button", { name: "Browse Data", exact: true }).click();
  await expect(page.getByLabel("Data catalog")).toBeVisible();
  await page.getByRole("button", { name: "Operations", exact: true }).click();
  await page.getByRole("button", { name: "Create Operation" }).click();
  await page.getByLabel("Operation type").selectOption("MCP batch binding");
  await page.getByRole("textbox", { name: "Name" }).fill("Publish summary");
  await page.getByRole("button", { name: "Create draft" }).click();
  await expect(page.getByLabel("Data editor")).toContainText("Publish summary");
  await page.getByRole("button", { name: "Use in workflow" }).click();
  await expect(page.getByLabel("Workflow editor")).toBeVisible();
  await page.getByLabel("Add workflow step").getByLabel("Draft review").check();
  await page.getByRole("button", { name: "Add to definition" }).click();
  await expect(
    page.locator('path[data-from="review"][data-to="step-1"]'),
  ).toHaveCount(1);
  await expect(
    page.getByRole("region", { name: "Workflow definition", exact: true }),
  ).toContainText("Publish summary");
  await page.getByRole("button", { name: "Save definition" }).click();
  await expect(page.getByRole("status")).toContainText(
    "Captured Runs remain unchanged",
  );
  await page.getByRole("button", { name: "View captured Run" }).click();
  await expect(page.getByLabel("Read-only dependency map")).toBeVisible();
  await page.getByRole("button", { name: "Data", exact: true }).first().click();
  await expect(page.getByLabel("Data catalog")).toContainText(
    "Publish summary",
  );
});

test("phone Data keeps catalog and record editor as separate primary surfaces", async ({
  page,
}) => {
  await page.setViewportSize({ width: 390, height: 844 });
  await page.goto("/prototype/project-explorer?variant=E");
  await page.getByRole("button", { name: "Browse Data" }).click();
  await expect(page.getByLabel("Data catalog")).toBeVisible();
  await expect(page.getByLabel("Data editor")).toBeHidden();
  await page
    .getByLabel("Data collections")
    .getByRole("button", { name: /Input set/ })
    .click();
  await expect(page.getByLabel("Data editor")).toBeVisible();
  await expect(page.getByLabel("Data collections")).toBeHidden();
  await page.getByRole("button", { name: "Back to Data" }).click();
  await expect(page.getByLabel("Data collections")).toBeVisible();
});

test("Operations groups definitions while preview settings leave saved dataflow alone", async ({
  page,
}) => {
  await page.goto("/prototype/project-explorer?variant=D");
  await expect(
    page.getByRole("button", { name: "D · Operations" }),
  ).toHaveAttribute("aria-pressed", "true");
  await expect(
    page
      .getByRole("complementary", { name: "Data collections" })
      .getByRole("button", {
        name: /Operations/,
      }),
  ).toBeVisible();
  await expect(
    page.getByRole("heading", { name: "Normalize units" }),
  ).toBeVisible();
  await page
    .getByRole("combobox", { name: "Preview source" })
    .selectOption("tool");
  await page
    .getByRole("combobox", { name: "Preview sort" })
    .selectOption("load");
  await expect(page.getByText("MCP-01, MCP-03")).toBeVisible();
  await expect(
    page.getByRole("region", { name: "Saved operation flow" }),
  ).toContainText("Results for BR-204");
  await page.getByRole("button", { name: "Inspect dataflow" }).click();
  await expect(
    page.getByText("Preview settings do not change these edges."),
  ).toBeVisible();
  await page.getByRole("button", { name: "Close dataflow" }).click();
  await page
    .getByRole("button", { name: /Assess beams Batch Definition/ })
    .click();
  await expect(
    page.getByRole("heading", { name: "Assess beams" }),
  ).toBeVisible();
  await expect(
    page.getByRole("region", { name: "Saved operation flow" }),
  ).toContainText("Result Set");
  await page
    .getByRole("button", { name: /Results for BR-204 Result Set/ })
    .click();
  await expect(
    page
      .getByRole("complementary", { name: "Data collections" })
      .getByRole("button", { name: /Operations/ }),
  ).toHaveAttribute("aria-current", "page");
});

test("Operations keeps one primary surface on a phone", async ({ page }) => {
  await page.setViewportSize({ width: 390, height: 844 });
  await page.goto("/prototype/project-explorer?variant=D");
  await expect(page.getByLabel("Selected Data record")).toBeHidden();
  await page
    .getByRole("button", { name: /Normalize units Transform Definition/ })
    .click();
  await expect(page.getByLabel("Selected Data record")).toBeVisible();
  await expect(
    page.getByRole("combobox", { name: "Preview filter" }),
  ).toBeVisible();
  await page.getByRole("button", { name: "Back to Data" }).click();
  await expect(page.getByLabel("Selected Data record")).toBeHidden();
  await page.getByRole("button", { name: "Open Project navigation" }).click();
  await expect(
    page
      .getByRole("complementary", { name: "Project navigation" })
      .getByRole("button", {
        name: "Operations",
      }),
  ).toBeVisible();
});

test("prototype variants are directly selectable in a built app", async ({
  page,
}) => {
  await page.goto("/prototype/project-explorer?variant=A");
  await expect(
    page.getByRole("button", { name: "B · Expandable outline" }),
  ).toBeVisible();
  await page.getByRole("button", { name: "B · Expandable outline" }).click();
  await expect(page).toHaveURL(/variant=B/);
  await expect(page.getByLabel("Data outline")).toBeVisible();
});

test("prototype keeps Runs and Result Sets contextual under Data definitions", async ({
  page,
}) => {
  await page.goto("/prototype/project-explorer?variant=A");

  await expect(
    page.getByRole("heading", { name: "Data", exact: true }),
  ).toBeVisible();
  await expect(
    page.getByRole("navigation", { name: "Project views" }).getByRole("button"),
  ).toHaveCount(5);
  await page
    .getByRole("complementary", { name: "Data collections" })
    .getByRole("button", { name: /Batch Definitions/ })
    .click();
  await page
    .getByRole("button", { name: /Assess beams Batch Definition/ })
    .click();
  await expect(page.getByRole("heading", { name: "Runs" })).toBeVisible();
  await page.getByRole("button", { name: /Run BR-204 Batch Run/ }).click();
  await expect(page.getByRole("heading", { name: "Result Set" })).toBeVisible();
  await page
    .getByRole("button", { name: /Results for BR-204 Result Set/ })
    .click();
  await expect(page.getByText("126", { exact: true })).toBeVisible();

  await page.getByRole("button", { name: "Inspect dataflow" }).click();
  await expect(page.getByRole("heading", { name: "Dataflow" })).toBeVisible();
  await expect(page.getByText("per-record outcomes")).toBeVisible();
  await page.getByRole("button", { name: "B · Expandable outline" }).click();
  await expect(page).toHaveURL(/variant=B/);
  await expect(page.getByLabel("Data outline")).toBeVisible();
  await page.reload();
  await expect(page.getByLabel("Data outline")).toBeVisible();
  await page.getByRole("button", { name: "C · Overview index" }).click();
  await expect(page).toHaveURL(/variant=C/);
  await expect(page.getByLabel("Data overview")).toBeVisible();
  await page
    .getByRole("navigation", { name: "Project views" })
    .getByRole("button", { name: "Work" })
    .click();
  await expect(
    page.getByRole("heading", { name: "Load summary" }),
  ).toBeVisible();
  await page.getByRole("button", { name: "Inspect dataflow" }).click();
  await expect(page.getByText("one curated Artifact")).toBeVisible();
  await page.getByRole("button", { name: "Close dataflow" }).click();
  await page
    .getByRole("button", { name: /Results for BR-204 Result Set/ })
    .click();
  await expect(
    page.getByRole("heading", { name: "Data", exact: true }),
  ).toBeVisible();
});

test("phone width keeps one primary surface and touch-visible navigation", async ({
  page,
}) => {
  await page.setViewportSize({ width: 390, height: 844 });
  await page.goto("/prototype/project-explorer?variant=A");

  await expect(
    page.getByRole("button", { name: "Open Project navigation" }),
  ).toBeVisible();
  await expect(
    page.getByRole("button", { name: "B · Expandable outline" }),
  ).toBeVisible();
  await expect(page.getByLabel("Selected Data record")).toBeHidden();
  await page.getByRole("button", { name: "Open Project navigation" }).click();
  await expect(
    page.getByRole("complementary", { name: "Project navigation" }),
  ).toBeVisible();
  await page
    .getByRole("complementary", { name: "Project navigation" })
    .getByRole("button", { name: "Batch Definitions" })
    .click();
  await expect(
    page.getByRole("complementary", { name: "Project navigation" }),
  ).toBeHidden();
  await page
    .getByRole("button", { name: /Assess beams Batch Definition/ })
    .click();
  await expect(page.getByLabel("Selected Data record")).toBeVisible();
  await expect(
    page.getByRole("button", { name: "Back to Data" }),
  ).toBeVisible();
  await page.getByRole("button", { name: "Back to Data" }).click();
  await expect(page.getByLabel("Selected Data record")).toBeHidden();
  await expect(
    page.getByRole("button", { name: /Assess beams Batch Definition/ }),
  ).toBeVisible();
});

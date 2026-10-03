import { expect, test } from "@playwright/test";

test("Operations groups definitions while preview settings leave saved dataflow alone", async ({
  page,
}) => {
  await page.goto("/prototype/project-explorer");
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

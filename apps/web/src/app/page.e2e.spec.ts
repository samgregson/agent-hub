import { expect, test } from "@playwright/test";

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
  await page.getByLabel("New Project name").fill(project.name);
  await expect(page.getByRole("button", { name: "Create" })).toBeEnabled();

  await page.getByRole("button", { name: "Create" }).click();

  await expect(page.getByLabel("Selected Project")).toHaveValue(project.id);
});

test("project creation is unavailable before the workspace hydrates", async ({
  browser,
}) => {
  const context = await browser.newContext({ javaScriptEnabled: false });
  const page = await context.newPage();

  await page.goto("/");
  await expect(page.getByLabel("New Project name")).toBeDisabled();
  await expect(page.getByRole("button", { name: "Create" })).toBeDisabled();
  await context.close();
});

test.describe("at phone width", () => {
  test.use({ viewport: { height: 844, width: 390 } });

  test("Project controls fit without horizontal overflow", async ({ page }) => {
    await page.goto("/");
    await page.getByLabel("New Project name").waitFor({ state: "visible" });

    const headerWidth = await page.locator("header").evaluate((element) => ({
      clientWidth: element.clientWidth,
      scrollWidth: element.scrollWidth,
    }));
    expect(headerWidth.scrollWidth).toBeLessThanOrEqual(
      headerWidth.clientWidth,
    );
    await expect(page.getByLabel("New Project name")).toBeInViewport();
    await expect(page.getByRole("button", { name: "Create" })).toBeInViewport();
  });
});

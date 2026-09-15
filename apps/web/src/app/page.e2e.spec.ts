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

test("project creation does not fall back to a query navigation", async ({
  browser,
}) => {
  const context = await browser.newContext({ javaScriptEnabled: false });
  const page = await context.newPage();
  let submitted = false;

  await page.route("**/api/projects", async (route) => {
    submitted = route.request().method() === "POST";
    await route.fulfill({
      headers: { location: "/" },
      status: 303,
    });
  });

  await page.goto("/");
  await page.getByLabel("New Project name").fill("Design review");
  await page.getByRole("button", { name: "Create" }).click();

  await expect.poll(() => submitted).toBe(true);
  await expect(page).toHaveURL("http://localhost:3001/");
  await context.close();
});

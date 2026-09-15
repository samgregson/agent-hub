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

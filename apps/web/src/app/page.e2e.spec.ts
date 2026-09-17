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

    await page.goto("/");
    await expect(page.getByLabel("Selected Project")).toHaveValue(project.id);

    await page.getByRole("button", { name: "Open Project navigation" }).click();
    const drawer = page.getByRole("dialog", { name: "Project navigation" });
    await expect(drawer).toBeVisible();
    await drawer.getByRole("button", { name: "+ New Thread" }).click();
    await expect(
      drawer.getByRole("button", { name: "New Thread 1" }),
    ).toBeVisible();

    await drawer.getByRole("button", { name: "Artifacts" }).click();
    await expect(drawer.getByText("Project files")).toBeVisible();
    await drawer
      .getByRole("button", { name: /\/project\/notes\/check\.md/ })
      .click();
    await expect(drawer).toBeHidden();
    await expect(page.getByText("# Preview")).toBeVisible();
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
  await page.getByRole("button", { name: "Approve" }).click();

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

function sse(events: object[]) {
  return events.map((event) => `data: ${JSON.stringify(event)}\n\n`).join("");
}

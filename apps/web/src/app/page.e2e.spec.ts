import { expect, test } from "@playwright/test";

test("Plugins are available through the browser-facing Project API", async ({
  request,
}) => {
  const projectResponse = await request.post("/api/projects", {
    data: { name: "Plugin proxy verification" },
  });
  expect(projectResponse.status()).toBe(201);
  const project = (await projectResponse.json()) as { id: string };

  const pluginsResponse = await request.get(
    `/api/projects/${project.id}/plugins`,
  );

  expect(pluginsResponse.status()).toBe(200);
  await expect(pluginsResponse.json()).resolves.toEqual([
    {
      enabled: false,
      id: "foundation-fixture",
      name: "Foundation fixture",
      tools: [{ name: "foundation_status", readOnly: true }],
      version: "0.1.0",
    },
    {
      enabled: false,
      id: "reference-calculation",
      name: "Reference calculation",
      tools: [{ name: "calculate_cantilever_tip_load", readOnly: false }],
      version: "0.1.0",
    },
  ]);
});

test("Plugin selections can be updated through the browser-facing Project API", async ({
  request,
}) => {
  const projectResponse = await request.post("/api/projects", {
    data: { name: "Plugin selection proxy verification" },
  });
  expect(projectResponse.status()).toBe(201);
  const project = (await projectResponse.json()) as { id: string };
  const selectionUrl = `/api/projects/${project.id}/plugins/foundation-fixture`;

  const enabledResponse = await request.put(selectionUrl);
  expect(enabledResponse.status()).toBe(204);
  const enabledPlugins = await request.get(
    `/api/projects/${project.id}/plugins`,
  );
  await expect(enabledPlugins.json()).resolves.toMatchObject([
    { enabled: true, id: "foundation-fixture" },
  ]);

  const disabledResponse = await request.delete(selectionUrl);
  expect(disabledResponse.status()).toBe(204);
});

test("the browser-facing Project API forwards work item deletion", async ({
  request,
}) => {
  const projectResponse = await request.post("/api/projects", {
    data: { name: "Work deletion proxy verification" },
  });
  expect(projectResponse.status()).toBe(201);
  const project = (await projectResponse.json()) as { id: string };

  const fileResponse = await request.delete(
    `/api/projects/${project.id}/files?path=/project/missing.txt`,
  );
  expect(fileResponse.status()).toBe(404);

  const artifactResponse = await request.delete(
    `/api/projects/${project.id}/artifacts/missing-artifact`,
  );
  expect(artifactResponse.status()).toBe(404);
});

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

test("Work navigation combines Artifacts and Project files into one list", async ({
  page,
}) => {
  const project = {
    createdAt: "2026-09-18T00:00:00.000Z",
    id: "project-123",
    name: "Design review",
    updatedAt: "2026-09-18T00:00:00.000Z",
  };
  await page.route("**/api/projects", async (route) => {
    await route.fulfill({ json: [project] });
  });
  await page.route(`**/api/projects/${project.id}/artifacts`, async (route) => {
    await route.fulfill({
      json: {
        artifacts: [
          {
            documentVersion: 1,
            id: "artifact-123",
            pluginId: "foundation-fixture",
            pluginVersion: "0.1.0",
            title: "Foundation status",
            type: "agent-hub.fixture.status",
          },
        ],
      },
    });
  });
  await page.route(
    `**/api/projects/${project.id}/files/index`,
    async (route) => {
      await route.fulfill({
        json: {
          files: [
            {
              path: "/project/foundation-notes.md",
              updatedAt: "2026-09-18T00:00:00.000Z",
              version: 1,
            },
          ],
        },
      });
    },
  );

  await page.goto("/");
  await page.getByRole("button", { name: "Work" }).click();

  await expect(
    page.getByRole("button", { exact: true, name: "Foundation status" }),
  ).toBeVisible();
  await expect(page.getByLabel("Work items")).toContainText(
    "Foundation status",
  );
  await expect(page.getByLabel("Work items")).toContainText(
    "/project/foundation-notes.md",
  );
  await expect(
    page.getByText(
      "Durable project work products. Project files appear below until elevated.",
    ),
  ).toHaveCount(0);
  await expect(
    page.getByText(
      "Shared working files. Opening one does not create an Artifact.",
    ),
  ).toHaveCount(0);
});

test("a Project file is deleted from its Work item action menu after confirmation", async ({
  page,
}) => {
  const project = {
    createdAt: "2026-09-21T00:00:00.000Z",
    id: "project-123",
    name: "Design review",
    updatedAt: "2026-09-21T00:00:00.000Z",
  };
  const path = "/project/test.txt";
  let deleted = false;

  await page.route("**/api/projects", async (route) => {
    await route.fulfill({ json: [project] });
  });
  await page.route(`**/api/projects/${project.id}/artifacts`, async (route) => {
    await route.fulfill({ json: { artifacts: [] } });
  });
  await page.route(
    `**/api/projects/${project.id}/files/index`,
    async (route) => {
      await route.fulfill({
        json: {
          files: deleted
            ? []
            : [{ path, updatedAt: "2026-09-21T00:00:00.000Z", version: 1 }],
        },
      });
    },
  );
  await page.route(
    `**/api/projects/${project.id}/files?path=${encodeURIComponent(path)}`,
    async (route) => {
      expect(route.request().method()).toBe("DELETE");
      deleted = true;
      await route.fulfill({ status: 204 });
    },
  );

  await page.goto("/");
  await page.getByRole("button", { name: "Work" }).click();
  await page.getByRole("button", { name: `${path} actions` }).click();
  await page.getByRole("menuitem", { name: "Delete" }).click();

  const dialog = page.getByRole("dialog", { name: "Confirm deletion" });
  await expect(dialog).toContainText(path);
  await dialog.getByRole("button", { name: "Cancel" }).click();
  await expect(dialog).toBeHidden();
  await expect(page.getByText(path)).toBeVisible();

  await page.getByRole("button", { name: `${path} actions` }).click();
  await page.getByRole("menuitem", { name: "Delete" }).click();
  await dialog.getByRole("button", { name: "Delete" }).click();

  await expect(page.getByText(path)).toBeHidden();
});

test("an Artifact changed by another Thread stays open until the user reloads it", async ({
  page,
}) => {
  const project = {
    createdAt: "2026-09-21T00:00:00.000Z",
    id: "project-123",
    name: "Design review",
    updatedAt: "2026-09-21T00:00:00.000Z",
  };
  const artifactId = "artifact-123";
  let documentRequests = 0;
  const artifactDocument = (documentVersion: number, threadId: string) => ({
    artifact: {
      documentVersion,
      id: artifactId,
      plugin: { id: "foundation-fixture", version: "0.1.0" },
      provenance: {
        createdBy: { kind: "agentRun", runId: "run-a", threadId: "thread-a" },
        lastChangedBy: { kind: "agentRun", runId: "run-b", threadId },
      },
      relations: [],
      schema: { id: "agent-hub.fixture.status", version: "1" },
      title: "Foundation status",
      type: "agent-hub.fixture.status",
    },
    payload: { status: documentVersion === 1 ? "available" : "unavailable" },
  });

  await page.route("**/api/projects", async (route) => {
    await route.fulfill({ json: [project] });
  });
  await page.route(`**/api/projects/${project.id}/artifacts`, async (route) => {
    await route.fulfill({
      json: {
        artifacts: [
          {
            documentVersion: 1,
            id: artifactId,
            pluginId: "foundation-fixture",
            pluginVersion: "0.1.0",
            title: "Foundation status",
            type: "agent-hub.fixture.status",
          },
        ],
      },
    });
  });
  await page.route(
    `**/api/projects/${project.id}/files/index`,
    async (route) => {
      await route.fulfill({ json: { files: [] } });
    },
  );
  await page.route(
    `**/api/projects/${project.id}/artifacts/${artifactId}`,
    async (route) => {
      documentRequests += 1;
      await route.fulfill({
        json:
          documentRequests <= 2
            ? artifactDocument(1, "thread-a")
            : artifactDocument(2, "thread-b"),
      });
    },
  );
  await page.route(
    `**/api/projects/${project.id}/artifacts/${artifactId}/app`,
    async (route) => {
      await route.fulfill({ status: 404 });
    },
  );

  await page.goto("/");
  await page.getByRole("button", { name: "Work" }).click();
  await page
    .getByRole("button", { exact: true, name: "Foundation status" })
    .click();
  const artifactPreview = page.locator("aside").last();
  await expect(artifactPreview.getByText("Version 1")).toBeVisible();

  const changedDocumentResponse = page.waitForResponse(
    `**/api/projects/${project.id}/artifacts/${artifactId}`,
  );
  await page.evaluate(() => window.dispatchEvent(new Event("focus")));
  await changedDocumentResponse;

  await expect(
    page.getByText("This Artifact changed in another Thread."),
  ).toBeVisible();
  await expect(artifactPreview.getByText("Version 1")).toBeVisible();
  await page.getByRole("button", { name: "Reload" }).click();
  await expect(artifactPreview.getByText("Version 2")).toBeVisible();
  await expect(
    page.getByText("This Artifact changed in another Thread."),
  ).toBeHidden();
});

test("an Artifact App receives its saved tool result through the MCP App bridge", async ({
  page,
}) => {
  const project = {
    createdAt: "2026-09-22T00:00:00.000Z",
    id: "project-123",
    name: "Design review",
    updatedAt: "2026-09-22T00:00:00.000Z",
  };
  const artifactId = "artifact-123";
  const artifact = {
    artifact: {
      documentVersion: 1,
      id: artifactId,
      plugin: { id: "reference-calculation", version: "0.1.0" },
      provenance: {
        createdBy: { kind: "agentRun", runId: "run-a", threadId: "thread-a" },
        lastChangedBy: {
          kind: "agentRun",
          runId: "run-a",
          threadId: "thread-a",
        },
      },
      relations: [],
      schema: { id: "agent-hub.plugin.tool-result", version: "1" },
      title: "Cantilever moment",
      type: "agent-hub.reference-calculation.calculate-cantilever-tip-load",
    },
    payload: {
      input: { length_m: 6.5, tip_load_kn: 12.5 },
      output: {
        calculation: { maximumMoment: { unit: "kN·m", value: 81.25 } },
      },
    },
  };
  const app = `<!doctype html><body>Waiting<script>
    window.addEventListener("message", (event) => {
      const message = event.data;
      if (message?.method === "ui/notifications/tool-result") {
        document.body.textContent = String(message.params.structuredContent.payload.input.length_m);
      }
    });
    window.parent.postMessage({jsonrpc:"2.0",id:"initialize",method:"ui/initialize",params:{appInfo:{name:"Test App",version:"0.1.0"},appCapabilities:{},protocolVersion:"2026-01-26"}}, "*");
    window.parent.postMessage({jsonrpc:"2.0",method:"ui/notifications/initialized",params:{}}, "*");
  </script>`;

  await page.route("**/api/projects", async (route) => {
    await route.fulfill({ json: [project] });
  });
  await page.route(`**/api/projects/${project.id}/artifacts`, async (route) => {
    await route.fulfill({
      json: {
        artifacts: [
          {
            documentVersion: 1,
            id: artifactId,
            pluginId: "reference-calculation",
            pluginVersion: "0.1.0",
            title: artifact.artifact.title,
            type: artifact.artifact.type,
          },
        ],
      },
    });
  });
  await page.route(
    `**/api/projects/${project.id}/files/index`,
    async (route) => {
      await route.fulfill({ json: { files: [] } });
    },
  );
  await page.route(
    `**/api/projects/${project.id}/artifacts/${artifactId}`,
    async (route) => {
      await route.fulfill({ json: artifact });
    },
  );
  await page.route(
    `**/api/projects/${project.id}/artifacts/${artifactId}/app`,
    async (route) => {
      await route.fulfill({ body: app, contentType: "text/html" });
    },
  );

  await page.goto("/");
  await page.getByRole("button", { name: "Work" }).click();
  await page
    .getByRole("button", { exact: true, name: artifact.artifact.title })
    .click();

  await expect(
    page.frameLocator('iframe[title="Artifact App"]').locator("body"),
  ).toHaveText("6.5");
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
      drawer.getByRole("button", { name: "New Thread 1", exact: true }),
    ).toBeVisible();

    await drawer.getByRole("button", { name: "Work" }).click();
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
          { type: "RUN_STARTED", threadId: thread.id, runId: input.runId },
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
  await page.route("**/api/projects", async (route) => {
    await route.fulfill({ json: [project] });
  });
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
  await expect(page.getByText("Approve Project File change")).toBeVisible();
  await expect(page.getByText("write_file", { exact: true })).toBeHidden();
  await page.getByRole("button", { name: "Approve" }).click();
  await expect(page.getByText("write_file", { exact: true })).toBeHidden();

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

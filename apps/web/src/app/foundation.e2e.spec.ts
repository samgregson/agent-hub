import { randomUUID } from "node:crypto";

import { expect, test, type APIRequestContext } from "@playwright/test";

test.skip(
  process.env.AGENT_HUB_FOUNDATION_E2E !== "1",
  "Runs only with the isolated foundation services",
);

async function runAgent(
  request: APIRequestContext,
  projectId: string,
  threadId: string,
  prompt: string,
  resume?: {
    interruptId: string;
    payload: { approved: boolean };
    status: string;
  }[],
) {
  const runId = randomUUID();
  const response = await request.post(
    `/api/projects/${projectId}/threads/${threadId}/agent`,
    {
      data: {
        threadId,
        runId,
        messages: resume
          ? []
          : [{ id: randomUUID(), role: "user", content: prompt }],
        tools: [],
        context: [],
        forwardedProps: {},
        ...(resume ? { resume } : {}),
      },
    },
  );
  expect(response.status()).toBe(200);
  const stream = await response.text();
  expect(events(stream).filter((event) => event.type === "RUN_ERROR")).toEqual(
    [],
  );
  expect(events(stream).some((event) => event.type === "RUN_FINISHED")).toBe(
    true,
  );
  return { runId, stream };
}

function events(stream: string) {
  return stream
    .split("\n")
    .filter((line) => line.startsWith("data: "))
    .map((line) => JSON.parse(line.slice(6)) as Record<string, unknown>);
}

function messageText(stream: string) {
  return events(stream)
    .filter((event) => event.type === "TEXT_MESSAGE_CONTENT")
    .map((event) => event.delta)
    .join("");
}

function toolNames(stream: string) {
  return events(stream)
    .filter((event) => event.type === "TOOL_CALL_START")
    .map((event) => event.toolCallName);
}

test("two Threads complete the foundation Artifact flow", async ({
  request,
  page,
}) => {
  test.setTimeout(90_000);
  const projectName = `Foundation ${randomUUID()}`;
  await page.goto("/");
  await page
    .getByLabel("Selected Project")
    .selectOption({ label: "New Project…" });
  const projectDialog = page.getByRole("dialog", { name: "New Project" });
  await projectDialog.getByLabel("Project name").fill(projectName);
  await projectDialog.getByLabel("Project name").press("Enter");
  await expect(page.getByLabel("Selected Project")).not.toHaveValue("");
  await expect(projectDialog).toBeHidden();
  const project = {
    id: await page.getByLabel("Selected Project").inputValue(),
  };
  const threadIds: string[] = [];

  for (const title of ["First Thread", "Second Thread"]) {
    const threadResponse = await request.post(
      `/api/projects/${project.id}/threads`,
      { data: { title } },
    );
    expect(threadResponse.status()).toBe(201);
    const thread = (await threadResponse.json()) as { id: string };
    threadIds.push(thread.id);

    const run = await runAgent(
      request,
      project.id,
      thread.id,
      "foundation:hello",
    );
    expect(messageText(run.stream)).toContain("Foundation ready.");

    const runsResponse = await request.get(
      `/api/projects/${project.id}/threads/${thread.id}/runs`,
    );
    expect(runsResponse.status()).toBe(200);
    await expect(runsResponse.json()).resolves.toEqual(
      expect.arrayContaining([
        expect.objectContaining({ id: run.runId, status: "succeeded" }),
      ]),
    );
    const historyResponse = await request.get(
      `/api/projects/${project.id}/threads/${thread.id}/history`,
    );
    expect(historyResponse.status()).toBe(200);
    expect(await historyResponse.text()).toContain("Foundation ready.");
  }

  const enablePlugin = await request.put(
    `/api/projects/${project.id}/plugins/foundation-fixture`,
  );
  expect(enablePlugin.status()).toBe(204);
  const status = await runAgent(
    request,
    project.id,
    threadIds[0],
    "foundation:status",
  );
  expect(toolNames(status.stream)).toContain(
    "foundation_fixture__foundation_status",
  );
  expect(messageText(status.stream)).toContain("Fixture status is available.");

  const write = await runAgent(
    request,
    project.id,
    threadIds[0],
    "foundation:write-file",
  );
  expect(toolNames(write.stream)).toContain("write_file");
  const finish = events(write.stream).find(
    (event) => event.type === "RUN_FINISHED",
  ) as { outcome?: { type: string; interrupts?: { id: string }[] } };
  expect(finish.outcome?.type).toBe("interrupt");
  const interruptId = finish.outcome?.interrupts?.[0]?.id;
  expect(interruptId).toBeTruthy();

  const resumed = await runAgent(request, project.id, threadIds[0], "", [
    {
      interruptId: interruptId!,
      payload: { approved: true },
      status: "resolved",
    },
  ]);
  expect(messageText(resumed.stream)).toContain("Shared foundation note");
  const file = await request.get(
    `/api/projects/${project.id}/files?path=/project/foundation-note.md`,
  );
  expect(file.status()).toBe(200);
  expect(await file.text()).toContain("Shared foundation note");
  const hostPath = await request.get(
    `/api/projects/${project.id}/files?path=${encodeURIComponent("/project/../../etc/passwd")}`,
  );
  expect(hostPath.status()).toBe(404);
  expect(await hostPath.json()).toEqual({ detail: "Project file not found" });

  const read = await runAgent(
    request,
    project.id,
    threadIds[1],
    "foundation:read-file",
  );
  expect(toolNames(read.stream)).toContain("read_file");
  expect(messageText(read.stream)).toContain(
    "Second Thread read Shared foundation note.",
  );

  const create = await runAgent(
    request,
    project.id,
    threadIds[0],
    "foundation:create-artifact",
  );
  expect(toolNames(create.stream)).toContain("create_project_artifact");
  const createFinish = events(create.stream).find(
    (event) => event.type === "RUN_FINISHED",
  ) as { outcome?: { type: string; interrupts?: { id: string }[] } };
  expect(createFinish.outcome?.type).toBe("interrupt");
  const createInterruptId = createFinish.outcome?.interrupts?.[0]?.id;
  expect(createInterruptId).toBeTruthy();
  const created = await runAgent(request, project.id, threadIds[0], "", [
    {
      interruptId: createInterruptId!,
      payload: { approved: true },
      status: "resolved",
    },
  ]);
  expect(messageText(created.stream)).toContain(
    "Bridge status Artifact created.",
  );

  const catalogResponse = await request.get(
    `/api/projects/${project.id}/artifacts`,
  );
  expect(catalogResponse.status()).toBe(200);
  const catalog = (await catalogResponse.json()) as {
    artifacts: { id: string; title: string; documentVersion: number }[];
  };
  const artifact = catalog.artifacts.find(
    (item) => item.title === "Bridge status",
  );
  expect(artifact).toEqual(
    expect.objectContaining({ title: "Bridge status", documentVersion: 1 }),
  );

  const edit = await runAgent(
    request,
    project.id,
    threadIds[1],
    "foundation:edit-artifact",
  );
  expect(toolNames(edit.stream)).toEqual([
    "discover_project_artifacts",
    "load_project_artifact",
    "edit_project_artifact",
  ]);
  const editFinish = events(edit.stream).find(
    (event) => event.type === "RUN_FINISHED",
  ) as { outcome?: { type: string; interrupts?: { id: string }[] } };
  expect(editFinish.outcome?.type).toBe("interrupt");
  const editInterruptId = editFinish.outcome?.interrupts?.[0]?.id;
  expect(editInterruptId).toBeTruthy();
  const edited = await runAgent(request, project.id, threadIds[1], "", [
    {
      interruptId: editInterruptId!,
      payload: { approved: true },
      status: "resolved",
    },
  ]);
  expect(messageText(edited.stream)).toContain(
    "Bridge status Artifact updated.",
  );
  const artifactResponse = await request.get(
    `/api/projects/${project.id}/artifacts/${artifact!.id}`,
  );
  expect(artifactResponse.status()).toBe(200);
  const document = (await artifactResponse.json()) as {
    artifact: {
      documentVersion: number;
      provenance: {
        createdBy: { threadId: string; runId: string };
        lastChangedBy: { threadId: string; runId: string };
      };
    };
    payload: { status: string };
  };
  expect(document.artifact.documentVersion).toBe(2);
  expect(document.payload.status).toBe("unavailable");
  expect(document.artifact.provenance.createdBy.threadId).toBe(threadIds[0]);
  expect(document.artifact.provenance.createdBy.runId).toBe(created.runId);
  expect(document.artifact.provenance.lastChangedBy.threadId).toBe(
    threadIds[1],
  );
  expect(document.artifact.provenance.lastChangedBy.runId).toBe(edited.runId);

  const staleEdit = await request.post(
    `/api/projects/${project.id}/artifacts/${artifact!.id}/app/actions`,
    {
      data: {
        name: "set_status_artifact_status",
        arguments: { status: "available" },
        expectedVersion: 1,
      },
    },
  );
  expect(staleEdit.status()).toBe(409);
  expect(await staleEdit.text()).toContain("reload before editing");

  const notice = await runAgent(
    request,
    project.id,
    threadIds[0],
    "foundation:notice",
  );
  expect(messageText(notice.stream)).toContain(
    "Project change notice received.",
  );

  await page.goto("/");
  await page.getByLabel("Selected Project").selectOption(project.id);
  await page
    .getByRole("button", { name: "First Thread", exact: true })
    .first()
    .click();
  await expect(page.getByText("Project change notice received.")).toBeVisible();
  await expect(
    page.getByRole("region", { name: "Approve Project File change" }),
  ).toContainText("Approved");
  await page.getByRole("button", { name: "Work" }).click();
  await page
    .getByRole("button", { exact: true, name: "Bridge status" })
    .click();
  await expect(
    page.frameLocator('iframe[title="Artifact App"]').locator("#status"),
  ).toHaveText("unavailable");
  await page.reload();
  await page.getByLabel("Selected Project").selectOption(project.id);
  await page.getByRole("button", { name: "Work" }).click();
  await page
    .getByRole("button", { exact: true, name: "Bridge status" })
    .click();
  await expect(
    page.frameLocator('iframe[title="Artifact App"]').locator("#status"),
  ).toHaveText("unavailable");
});

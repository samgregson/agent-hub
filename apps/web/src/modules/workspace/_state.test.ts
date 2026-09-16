import assert from "node:assert/strict";
import test from "node:test";

import { createWorkspaceState, workspaceReducer } from "./_state";

test("project switching restores each project's scoped workspace state", () => {
  let state = createWorkspaceState();
  state = workspaceReducer(state, {
    projectId: "project-a",
    type: "selectProject",
  });
  state = workspaceReducer(state, {
    activity: "artifacts",
    type: "selectActivity",
  });
  state = workspaceReducer(state, {
    threadId: "thread-a",
    type: "selectThread",
  });
  state = workspaceReducer(state, {
    path: "/project/check.md",
    type: "openProjectFile",
  });
  state = workspaceReducer(state, {
    path: "/scratch/notes.md",
    threadId: "thread-a",
    type: "openScratchFile",
  });
  state = workspaceReducer(state, {
    projectId: "project-b",
    type: "selectProject",
  });

  assert.equal(state.projects["project-b"].activity, "chats");

  state = workspaceReducer(state, {
    activity: "sources",
    type: "selectActivity",
  });
  state = workspaceReducer(state, {
    projectId: "project-a",
    type: "selectProject",
  });

  assert.equal(state.projects["project-a"].activity, "artifacts");
  assert.equal(state.projects["project-a"].selectedThreadId, "thread-a");
  assert.equal(
    state.projects["project-a"].selectedFilePath,
    "/scratch/notes.md",
  );
  assert.equal(state.projects["project-a"].selectedScratchThreadId, "thread-a");
  assert.equal(state.projects["project-b"].selectedFilePath, null);
  assert.equal(state.projects["project-b"].selectedScratchThreadId, null);
  assert.equal(state.projects["project-b"].activity, "sources");
});

test("opening a Project file clears a prior Thread-local scratch selection", () => {
  let state = workspaceReducer(createWorkspaceState(), {
    projectId: "project-a",
    type: "selectProject",
  });
  state = workspaceReducer(state, {
    path: "/scratch/notes.md",
    threadId: "thread-a",
    type: "openScratchFile",
  });
  state = workspaceReducer(state, {
    path: "/project/notes.md",
    type: "openProjectFile",
  });

  assert.equal(state.projects["project-a"].selectedScratchThreadId, null);
  assert.equal(state.projects["project-a"].mobileSurface, "artifact");
});

test("opening a virtual file makes the Artifact surface visible on a phone", () => {
  let state = workspaceReducer(createWorkspaceState(), {
    projectId: "project-a",
    type: "selectProject",
  });
  state = workspaceReducer(state, {
    path: "/project/notes.md",
    type: "openProjectFile",
  });
  state = workspaceReducer(state, { type: "showChat" });

  assert.equal(state.projects["project-a"].mobileSurface, "chat");
});

test("activity changes are ignored until a Project is selected", () => {
  const state = createWorkspaceState();
  assert.equal(
    workspaceReducer(state, { activity: "plugins", type: "selectActivity" }),
    state,
  );
});

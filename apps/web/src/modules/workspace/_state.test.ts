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
  assert.equal(state.projects["project-b"].activity, "sources");
});

test("activity changes are ignored until a Project is selected", () => {
  const state = createWorkspaceState();
  assert.equal(
    workspaceReducer(state, { activity: "plugins", type: "selectActivity" }),
    state,
  );
});

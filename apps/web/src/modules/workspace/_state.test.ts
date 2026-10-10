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

test("opening a Project Artifact selects its generic view and clears a file preview", () => {
  let state = workspaceReducer(createWorkspaceState(), {
    projectId: "project-a",
    type: "selectProject",
  });
  state = workspaceReducer(state, {
    path: "/project/notes.md",
    type: "openProjectFile",
  });
  state = workspaceReducer(state, {
    artifactId: "artifact-a",
    type: "openArtifact",
  });

  assert.equal(state.projects["project-a"].selectedArtifactId, "artifact-a");
  assert.equal(state.projects["project-a"].selectedFilePath, null);
  assert.equal(state.projects["project-a"].mobileSurface, "artifact");
});

test("opening a proposed file shows the right panel without selecting the saved file", () => {
  let state = workspaceReducer(createWorkspaceState(), {
    projectId: "project-a",
    type: "selectProject",
  });
  const proposal = {
    kind: "diff" as const,
    path: "/project/check.md",
    proposed: "# Revised\n",
    text: "-# Original\n+# Revised",
  };
  state = workspaceReducer(state, { proposal, type: "openFileProposal" });
  assert.equal(state.projects["project-a"].selectedFileProposal, proposal);
  assert.equal(state.projects["project-a"].selectedFilePath, null);
  assert.equal(state.projects["project-a"].mobileSurface, "artifact");
  state = workspaceReducer(state, {
    path: "/project/check.md",
    type: "openProjectFile",
  });
  assert.equal(state.projects["project-a"].selectedFileProposal, null);
});

test("activity changes are ignored until a Project is selected", () => {
  const state = createWorkspaceState();
  assert.equal(
    workspaceReducer(state, { activity: "plugins", type: "selectActivity" }),
    state,
  );
});

test("Operations choice is restored per Project", () => {
  let state = workspaceReducer(createWorkspaceState(), {
    projectId: "project-a",
    type: "selectProject",
  });
  state = workspaceReducer(state, {
    activity: "operations",
    type: "selectActivity",
  });
  state = workspaceReducer(state, {
    operationKind: "transforms",
    type: "selectOperationKind",
  });
  state = workspaceReducer(state, {
    projectId: "project-b",
    type: "selectProject",
  });

  assert.equal(state.projects["project-b"].operationKind, "batchDefinitions");
  state = workspaceReducer(state, {
    projectId: "project-a",
    type: "selectProject",
  });
  assert.equal(state.projects["project-a"].activity, "operations");
  assert.equal(state.projects["project-a"].operationKind, "transforms");
});

test("Transform navigation selection survives a Project drawer remount", () => {
  let state = workspaceReducer(createWorkspaceState(), {
    projectId: "project-a",
    type: "selectProject",
  });
  state = workspaceReducer(state, {
    definitionId: "transform-b",
    type: "selectTransformDefinition",
  });
  state = workspaceReducer(state, {
    runScope: "transform-c",
    type: "selectTransformRunScope",
  });
  assert.equal(
    state.projects["project-a"].selectedTransformDefinitionId,
    "transform-c",
  );
  state = workspaceReducer(state, {
    runScope: "all",
    type: "selectTransformRunScope",
  });
  assert.equal(
    state.projects["project-a"].selectedTransformDefinitionId,
    "transform-c",
  );
  assert.equal(state.projects["project-a"].transformRunScope, "all");
  state = workspaceReducer(state, {
    projectId: "project-b",
    type: "selectProject",
  });
  assert.equal(state.projects["project-b"].selectedTransformDefinitionId, null);
  state = workspaceReducer(state, {
    projectId: "project-a",
    type: "selectProject",
  });
  assert.equal(
    state.projects["project-a"].selectedTransformDefinitionId,
    "transform-c",
  );
  assert.equal(state.projects["project-a"].transformRunScope, "all");
});

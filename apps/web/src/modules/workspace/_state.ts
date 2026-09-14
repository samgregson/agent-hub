export const activityViews = [
  "chats",
  "artifacts",
  "sources",
  "plugins",
] as const;

export type ActivityView = (typeof activityViews)[number];

export interface ProjectWorkspaceState {
  activity: ActivityView;
  selectedArtifactId: string | null;
  selectedSourceId: string | null;
  selectedThreadId: string | null;
}

export interface WorkspaceState {
  projects: Record<string, ProjectWorkspaceState>;
  selectedProjectId: string | null;
}

export type WorkspaceAction =
  | { projectId: string | null; type: "selectProject" }
  | { activity: ActivityView; type: "selectActivity" };

function initialProjectState(): ProjectWorkspaceState {
  return {
    activity: "chats",
    selectedArtifactId: null,
    selectedSourceId: null,
    selectedThreadId: null,
  };
}

export function createWorkspaceState(): WorkspaceState {
  return { projects: {}, selectedProjectId: null };
}

export function workspaceReducer(
  state: WorkspaceState,
  action: WorkspaceAction,
): WorkspaceState {
  if (action.type === "selectProject") {
    if (action.projectId === null || state.projects[action.projectId]) {
      return { ...state, selectedProjectId: action.projectId };
    }
    return {
      projects: {
        ...state.projects,
        [action.projectId]: initialProjectState(),
      },
      selectedProjectId: action.projectId,
    };
  }

  if (state.selectedProjectId === null) return state;
  return {
    ...state,
    projects: {
      ...state.projects,
      [state.selectedProjectId]: {
        ...state.projects[state.selectedProjectId],
        activity: action.activity,
      },
    },
  };
}

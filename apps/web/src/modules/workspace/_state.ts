export const activityViews = [
  "chats",
  "artifacts",
  "sources",
  "plugins",
] as const;

export type ActivityView = (typeof activityViews)[number];

export interface ProjectWorkspaceState {
  activity: ActivityView;
  mobileSurface: "artifact" | "chat";
  selectedArtifactId: string | null;
  selectedFilePath: string | null;
  selectedScratchThreadId: string | null;
  selectedSourceId: string | null;
  selectedThreadId: string | null;
}

export interface WorkspaceState {
  projects: Record<string, ProjectWorkspaceState>;
  selectedProjectId: string | null;
}

export type WorkspaceAction =
  | { projectId: string | null; type: "selectProject" }
  | { activity: ActivityView; type: "selectActivity" }
  | { artifactId: string | null; type: "openArtifact" }
  | { path: string | null; type: "openProjectFile" }
  | { path: string | null; threadId: string; type: "openScratchFile" }
  | { type: "showChat" }
  | { threadId: string | null; type: "selectThread" };

function initialProjectState(): ProjectWorkspaceState {
  return {
    activity: "chats",
    mobileSurface: "chat",
    selectedArtifactId: null,
    selectedFilePath: null,
    selectedScratchThreadId: null,
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
  if (action.type === "selectThread") {
    return {
      ...state,
      projects: {
        ...state.projects,
        [state.selectedProjectId]: {
          ...state.projects[state.selectedProjectId],
          selectedThreadId: action.threadId,
        },
      },
    };
  }
  if (action.type === "openProjectFile") {
    return {
      ...state,
      projects: {
        ...state.projects,
        [state.selectedProjectId]: {
          ...state.projects[state.selectedProjectId],
          selectedArtifactId: null,
          selectedFilePath: action.path,
          selectedScratchThreadId: null,
          mobileSurface: action.path === null ? "chat" : "artifact",
        },
      },
    };
  }
  if (action.type === "openScratchFile") {
    return {
      ...state,
      projects: {
        ...state.projects,
        [state.selectedProjectId]: {
          ...state.projects[state.selectedProjectId],
          selectedArtifactId: null,
          selectedFilePath: action.path,
          selectedScratchThreadId:
            action.path === null ? null : action.threadId,
          mobileSurface: action.path === null ? "chat" : "artifact",
        },
      },
    };
  }
  if (action.type === "showChat") {
    return {
      ...state,
      projects: {
        ...state.projects,
        [state.selectedProjectId]: {
          ...state.projects[state.selectedProjectId],
          mobileSurface: "chat",
        },
      },
    };
  }
  if (action.type === "openArtifact") {
    return {
      ...state,
      projects: {
        ...state.projects,
        [state.selectedProjectId]: {
          ...state.projects[state.selectedProjectId],
          selectedArtifactId: action.artifactId,
          selectedFilePath: null,
          selectedScratchThreadId: null,
          mobileSurface: action.artifactId === null ? "chat" : "artifact",
        },
      },
    };
  }
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

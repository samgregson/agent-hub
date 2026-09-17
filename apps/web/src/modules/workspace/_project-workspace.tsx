"use client";

import {
  FormEvent,
  useEffect,
  useReducer,
  useRef,
  useState,
  useSyncExternalStore,
} from "react";

import { AgentChat, ScratchFilePreview } from "@/modules/agent-ui";
import {
  ProjectFileCatalog,
  ProjectFilePreview,
} from "@/modules/project-files";
import { Menu, MenuItem } from "@/shared/ui";

import styles from "./workspace.module.css";
import {
  createProject,
  createThread,
  deleteThread,
  listProjects,
  listThreads,
  renameThread,
  type Project,
  type Thread,
} from "./_projects";
import {
  automaticThreadTitle,
  hasProvisionalThreadTitle,
  initialThreadTitle,
} from "./_thread-title";
import {
  type ActivityView,
  activityViews,
  createWorkspaceState,
  workspaceReducer,
} from "./_state";

const activityLabels = {
  artifacts: "Artifacts",
  chats: "Chats",
  plugins: "Plugins",
  sources: "Sources",
} as const;

function subscribeToHydration() {
  return () => {};
}

function clientIsInteractive() {
  return true;
}

function serverIsInteractive() {
  return false;
}

export function ProjectWorkspace() {
  const [projects, setProjects] = useState<Project[]>([]);
  const [workspace, dispatch] = useReducer(
    workspaceReducer,
    undefined,
    createWorkspaceState,
  );
  const [threadsByProject, setThreadsByProject] = useState<
    Record<string, Thread[]>
  >({});
  const isInteractive = useSyncExternalStore(
    subscribeToHydration,
    clientIsInteractive,
    serverIsInteractive,
  );
  const [isCreating, setIsCreating] = useState(false);
  const [isMobileNavigationOpen, setIsMobileNavigationOpen] = useState(false);
  const [autoNamingThreadIds, setAutoNamingThreadIds] = useState<Set<string>>(
    () => new Set(),
  );
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let active = true;
    listProjects()
      .then((loaded) => {
        if (!active) return;
        setProjects(loaded);
        if (loaded[0]) {
          dispatch({ projectId: loaded[0].id, type: "selectProject" });
        }
      })
      .catch(() => {
        if (active) setError("Projects are temporarily unavailable.");
      });
    return () => {
      active = false;
    };
  }, []);

  const selectedProject = projects.find(
    (project) => project.id === workspace.selectedProjectId,
  );
  const selectedWorkspace = workspace.selectedProjectId
    ? workspace.projects[workspace.selectedProjectId]
    : undefined;
  const selectedActivity = selectedWorkspace?.activity ?? "chats";
  const selectedThreads = workspace.selectedProjectId
    ? (threadsByProject[workspace.selectedProjectId] ?? [])
    : [];
  const selectedThread = selectedThreads.find(
    (thread) => thread.id === selectedWorkspace?.selectedThreadId,
  );
  const selectedThreadId = selectedWorkspace?.selectedThreadId;
  const selectedThreadIdRef = useRef(selectedThreadId);

  useEffect(() => {
    selectedThreadIdRef.current = selectedThreadId;
  }, [selectedThreadId]);

  useEffect(() => {
    if (!workspace.selectedProjectId) return;
    const projectId = workspace.selectedProjectId;
    let active = true;
    listThreads(projectId)
      .then((loaded) => {
        if (!active) return;
        setThreadsByProject((current) => ({ ...current, [projectId]: loaded }));
        if (!selectedThreadIdRef.current && loaded[0]) {
          dispatch({ threadId: loaded[0].id, type: "selectThread" });
        }
      })
      .catch(() => {
        if (active) setError("Threads are temporarily unavailable.");
      });
    return () => {
      active = false;
    };
  }, [workspace.selectedProjectId]);

  async function handleCreateProject(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const form = event.currentTarget;
    const submittedName = new FormData(form).get("name");
    const name = typeof submittedName === "string" ? submittedName.trim() : "";
    if (!name) return;

    setIsCreating(true);
    setError(null);
    try {
      const project = await createProject(name);
      setProjects((current) => [project, ...current]);
      dispatch({ projectId: project.id, type: "selectProject" });
      form.reset();
    } catch {
      setError("The Project could not be created.");
    } finally {
      setIsCreating(false);
    }
  }

  async function handleCreateThread() {
    if (!workspace.selectedProjectId) return;
    setError(null);
    try {
      const thread = await createThread(
        workspace.selectedProjectId,
        initialThreadTitle(selectedThreads.length + 1),
      );
      setThreadsByProject((current) => ({
        ...current,
        [thread.projectId]: [thread, ...(current[thread.projectId] ?? [])],
      }));
      dispatch({ threadId: thread.id, type: "selectThread" });
    } catch {
      setError("The Thread could not be created.");
    }
  }

  function replaceThread(updatedThread: Thread) {
    setThreadsByProject((current) => ({
      ...current,
      [updatedThread.projectId]: (current[updatedThread.projectId] ?? []).map(
        (thread) => (thread.id === updatedThread.id ? updatedThread : thread),
      ),
    }));
  }

  async function handleRenameThread(thread: Thread) {
    const title = window.prompt("Rename Thread", thread.title);
    if (title === null) return;
    const normalizedTitle = title.trim();
    if (!normalizedTitle) {
      setError("A Thread title cannot be empty.");
      return;
    }

    setError(null);
    try {
      replaceThread(
        await renameThread(thread.projectId, thread.id, normalizedTitle),
      );
    } catch {
      setError("The Thread could not be renamed.");
    }
  }

  async function handleDeleteThread(thread: Thread) {
    if (!window.confirm(`Delete “${thread.title}”? This cannot be undone.`)) {
      return;
    }

    setError(null);
    try {
      await deleteThread(thread.projectId, thread.id);
      const remaining = selectedThreads.filter((item) => item.id !== thread.id);
      setThreadsByProject((current) => ({
        ...current,
        [thread.projectId]: (current[thread.projectId] ?? []).filter(
          (item) => item.id !== thread.id,
        ),
      }));
      if (selectedThread?.id === thread.id) {
        dispatch({ threadId: remaining[0]?.id ?? null, type: "selectThread" });
      }
    } catch {
      setError("The Thread could not be deleted.");
    }
  }

  function handleSelectActivity(activity: ActivityView) {
    dispatch({ activity, type: "selectActivity" });
  }

  async function handleFirstUserMessage(message: string) {
    if (
      !selectedProject ||
      !selectedThread ||
      !hasProvisionalThreadTitle(selectedThread.title) ||
      autoNamingThreadIds.has(selectedThread.id)
    ) {
      return;
    }
    const title = automaticThreadTitle(message);
    if (!title) return;

    setAutoNamingThreadIds((current) =>
      new Set(current).add(selectedThread.id),
    );
    try {
      replaceThread(
        await renameThread(selectedProject.id, selectedThread.id, title),
      );
    } catch {
      // A title failure must never block the conversational send already in flight.
    } finally {
      setAutoNamingThreadIds((current) => {
        const next = new Set(current);
        next.delete(selectedThread.id);
        return next;
      });
    }
  }

  return (
    <main
      className={`${styles.shell} ${selectedWorkspace?.mobileSurface === "artifact" ? styles.mobileArtifactOpen : ""}`}
    >
      <header className={styles.titlebar}>
        <span aria-hidden="true" className={styles.mark}>
          A
        </span>
        <button
          aria-controls="mobile-project-navigation"
          aria-expanded={isMobileNavigationOpen}
          aria-label="Open Project navigation"
          className={styles.mobileNavigationToggle}
          onClick={() => setIsMobileNavigationOpen(true)}
          type="button"
        >
          ☰ Navigation
        </button>
        <div className={styles.projectControls}>
          <label className={styles.projectPicker}>
            <span className={styles.srOnly}>Selected Project</span>
            <select
              onChange={(event) =>
                dispatch({
                  projectId: event.target.value || null,
                  type: "selectProject",
                })
              }
              value={workspace.selectedProjectId ?? ""}
            >
              <option value="">No Project selected</option>
              {projects.map((project) => (
                <option key={project.id} value={project.id}>
                  {project.name}
                </option>
              ))}
            </select>
          </label>
          <form className={styles.createProject} onSubmit={handleCreateProject}>
            <input
              aria-label="New Project name"
              disabled={!isInteractive}
              maxLength={120}
              name="name"
              placeholder="New Project"
              required
            />
            <button disabled={!isInteractive || isCreating} type="submit">
              {isCreating ? "Creating…" : "Create"}
            </button>
          </form>
        </div>
        <span className={styles.foundation}>
          Foundation · Project workspace
        </span>
      </header>

      <nav aria-label="Project views" className={styles.rail}>
        {activityViews.map((view) => (
          <button
            aria-label={activityLabels[view]}
            aria-pressed={selectedActivity === view}
            className={styles.railButton}
            disabled={!selectedProject}
            key={view}
            onClick={() => dispatch({ activity: view, type: "selectActivity" })}
            title={activityLabels[view]}
            type="button"
          >
            {activityLabels[view].slice(0, 1)}
          </button>
        ))}
      </nav>

      <aside className={styles.navigator}>
        <ProjectNavigator
          onCreateThread={() => void handleCreateThread()}
          onDeleteThread={(thread) => void handleDeleteThread(thread)}
          onRenameThread={(thread) => void handleRenameThread(thread)}
          onOpenProjectFile={(path) => dispatch({ path, type: "openProjectFile" })}
          onSelectThread={(threadId) =>
            dispatch({ threadId, type: "selectThread" })
          }
          project={selectedProject}
          selectedActivity={selectedActivity}
          selectedThreadId={selectedThread?.id}
          threads={selectedThreads}
        />
      </aside>

      {isMobileNavigationOpen ? (
        <>
          <button
            aria-label="Close Project navigation"
            className={styles.mobileNavigationBackdrop}
            onClick={() => setIsMobileNavigationOpen(false)}
            type="button"
          />
          <aside
            aria-label="Project navigation"
            className={styles.mobileNavigationDrawer}
            id="mobile-project-navigation"
            role="dialog"
          >
            <div className={styles.mobileNavigationHeader}>
              <strong>Project navigation</strong>
              <button
                aria-label="Close Project navigation"
                className={styles.mobileNavigationClose}
                onClick={() => setIsMobileNavigationOpen(false)}
                type="button"
              >
                Close
              </button>
            </div>
            <nav aria-label="Project views" className={styles.mobileViewList}>
              {activityViews.map((view) => (
                <button
                  aria-pressed={selectedActivity === view}
                  className={styles.mobileViewButton}
                  disabled={!selectedProject}
                  key={view}
                  onClick={() => handleSelectActivity(view)}
                  type="button"
                >
                  {activityLabels[view]}
                </button>
              ))}
            </nav>
            <div className={styles.mobileNavigatorContent}>
              <ProjectNavigator
                onCreateThread={() => void handleCreateThread()}
                onDeleteThread={(thread) => void handleDeleteThread(thread)}
                onRenameThread={(thread) => void handleRenameThread(thread)}
                onOpenProjectFile={(path) => {
                  dispatch({ path, type: "openProjectFile" });
                  setIsMobileNavigationOpen(false);
                }}
                onSelectThread={(threadId) => {
                  dispatch({ threadId, type: "selectThread" });
                  setIsMobileNavigationOpen(false);
                }}
                project={selectedProject}
                selectedActivity={selectedActivity}
                selectedThreadId={selectedThread?.id}
                threads={selectedThreads}
              />
            </div>
          </aside>
        </>
      ) : null}

      <section className={styles.chat}>
        {selectedProject && selectedThread && selectedActivity === "chats" ? (
          <AgentChat
            key={selectedThread.id}
            onOpenVirtualFile={(path) => {
              if (path.startsWith("/scratch/")) {
                dispatch({
                  path,
                  threadId: selectedThread.id,
                  type: "openScratchFile",
                });
                return;
              }
              dispatch({ path, type: "openProjectFile" });
            }}
            onUserMessage={(message) => void handleFirstUserMessage(message)}
            projectId={selectedProject.id}
            threadId={selectedThread.id}
          />
        ) : (
          <div className={styles.chatPlaceholder}>
            <p className={styles.eyebrow}>Agent Hub</p>
            <h1>{selectedProject?.name ?? "Choose a Project"}</h1>
            <p>
              {selectedProject
                ? selectedActivity === "chats"
                  ? "Create or select a Thread to start a conversation."
                  : `${activityLabels[selectedActivity]} will appear in this Project workspace.`
                : "Projects keep conversations, files, sources, Plugins, and Artifacts together."}
            </p>
            {error ? <p className={styles.error}>{error}</p> : null}
          </div>
        )}
      </section>

      <aside className={styles.artifact}>
        <button
          className={styles.mobileReturnToChat}
          onClick={() => dispatch({ type: "showChat" })}
          type="button"
        >
          Back to chat
        </button>
        {selectedProject &&
        selectedWorkspace?.selectedFilePath &&
        selectedWorkspace.selectedScratchThreadId ? (
          <ScratchFilePreview
            path={selectedWorkspace.selectedFilePath}
            projectId={selectedProject.id}
            threadId={selectedWorkspace.selectedScratchThreadId}
          />
        ) : selectedProject && selectedWorkspace?.selectedFilePath ? (
          <ProjectFilePreview
            path={selectedWorkspace.selectedFilePath}
            projectId={selectedProject.id}
          />
        ) : (
          <>
            <strong>Artifact workspace</strong>
            <p>
              Project file previews open here. MCP App hosting arrives in Slice
              7.
            </p>
          </>
        )}
      </aside>
    </main>
  );
}

interface ProjectNavigatorProps {
  onCreateThread: () => void;
  onDeleteThread: (thread: Thread) => void;
  onOpenProjectFile: (path: string) => void;
  onRenameThread: (thread: Thread) => void;
  onSelectThread: (threadId: string) => void;
  project: Project | undefined;
  selectedActivity: ActivityView;
  selectedThreadId: string | undefined;
  threads: Thread[];
}

function ProjectNavigator({
  onCreateThread,
  onDeleteThread,
  onOpenProjectFile,
  onRenameThread,
  onSelectThread,
  project,
  selectedActivity,
  selectedThreadId,
  threads,
}: ProjectNavigatorProps) {
  return (
    <>
      <strong>{activityLabels[selectedActivity]}</strong>
      {selectedActivity === "chats" && project ? (
        <>
          <button
            className={styles.newThread}
            onClick={onCreateThread}
            type="button"
          >
            + New Thread
          </button>
          <div className={styles.threadList}>
            {threads.map((thread) => (
              <div className={styles.threadRow} key={thread.id}>
                <button
                  aria-pressed={selectedThreadId === thread.id}
                  className={styles.threadButton}
                  onClick={() => onSelectThread(thread.id)}
                  type="button"
                >
                  {thread.title}
                </button>
                <Menu label={`${thread.title} actions`}>
                  <MenuItem onSelect={() => onRenameThread(thread)}>
                    Rename
                  </MenuItem>
                  <MenuItem destructive onSelect={() => onDeleteThread(thread)}>
                    Delete
                  </MenuItem>
                </Menu>
              </div>
            ))}
          </div>
        </>
      ) : selectedActivity === "artifacts" && project ? (
        <ProjectFileCatalog onOpen={onOpenProjectFile} projectId={project.id} />
      ) : (
        <p>
          {project
            ? `${activityLabels[selectedActivity]} in ${project.name}`
            : "Create or select a Project to begin."}
        </p>
      )}
    </>
  );
}

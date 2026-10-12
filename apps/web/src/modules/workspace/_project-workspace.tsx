"use client";

import {
  FormEvent,
  useCallback,
  useEffect,
  useReducer,
  useRef,
  useState,
  useSyncExternalStore,
} from "react";
import type { CSSProperties } from "react";

import {
  AgentChat,
  ProposedFilePreview,
  ScratchFilePreview,
} from "@/modules/agent-ui";
import { ArtifactDocumentPreview } from "@/modules/artifact-view-host";
import { DatasetFilePreview } from "@/modules/datasets";
import { FunctionCatalog } from "@/modules/functions";
import { ProjectFilePreview } from "@/modules/project-files";
import { PluginCatalog } from "@/modules/plugin-gateway";
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
import { LibraryCatalog } from "./_library-catalog";
import { WorkflowOverview } from "@/modules/workflows";

const activityLabels = {
  workflows: "Workflow",
  artifacts: "Library",
  chats: "Chats",
  functions: "Functions",
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
  const selectFunction = useCallback(
    (functionId: string | null) =>
      dispatch({ functionId, type: "selectFunction" }),
    [],
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
  const [isNewProjectDialogOpen, setIsNewProjectDialogOpen] = useState(false);
  const [projectCreationError, setProjectCreationError] = useState<
    string | null
  >(null);
  const [isMobileNavigationOpen, setIsMobileNavigationOpen] = useState(false);
  const [navigatorWidth, setNavigatorWidth] = useState(256);
  const isResizingNavigator = useRef(false);
  const navigatorRef = useRef<HTMLElement>(null);
  const [autoNamingThreadIds, setAutoNamingThreadIds] = useState<Set<string>>(
    () => new Set(),
  );
  const [error, setError] = useState<string | null>(null);
  const [libraryRefreshKey, setLibraryRefreshKey] = useState(0);
  const newProjectNameInput = useRef<HTMLInputElement>(null);
  const projectPicker = useRef<HTMLSelectElement>(null);
  const workflowAvailabilityByProject = useRef(
    new Map<string, Promise<boolean>>(),
  );
  const userSelectedActivityProjects = useRef(new Set<string>());

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
  const isExplorerActivity = ["functions", "plugins", "sources"].includes(
    selectedActivity,
  );
  const isWorkflowActivity = selectedActivity === "workflows";
  const selectedThreads = workspace.selectedProjectId
    ? (threadsByProject[workspace.selectedProjectId] ?? [])
    : [];
  const selectedThread = selectedThreads.find(
    (thread) => thread.id === selectedWorkspace?.selectedThreadId,
  );
  const selectedThreadId = selectedWorkspace?.selectedThreadId;
  const selectedThreadIdRef = useRef(selectedThreadId);
  const selectedProjectIdRef = useRef(workspace.selectedProjectId);

  useEffect(() => {
    selectedThreadIdRef.current = selectedThreadId;
  }, [selectedThreadId]);

  useEffect(() => {
    selectedProjectIdRef.current = workspace.selectedProjectId;
  }, [workspace.selectedProjectId]);

  useEffect(() => {
    const projectId = workspace.selectedProjectId;
    if (!projectId) return;
    let availability = workflowAvailabilityByProject.current.get(projectId);
    if (!availability) {
      availability = fetch(
        `/api/projects/${encodeURIComponent(projectId)}/workflows`,
        { cache: "no-store" },
      )
        .then(async (response) => {
          if (!response.ok) return false;
          const workflows = (await response.json()) as unknown[];
          return workflows.length > 0;
        })
        .catch(() => false);
      workflowAvailabilityByProject.current.set(projectId, availability);
    }
    let active = true;
    void availability.then((hasWorkflows) => {
      if (
        active &&
        hasWorkflows &&
        selectedProjectIdRef.current === projectId &&
        !userSelectedActivityProjects.current.has(projectId)
      ) {
        dispatch({ activity: "workflows", type: "selectActivity" });
      }
    });
    return () => {
      active = false;
    };
  }, [workspace.selectedProjectId]);

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

  useEffect(() => {
    if (!isNewProjectDialogOpen) return;
    newProjectNameInput.current?.focus();
  }, [isNewProjectDialogOpen]);

  async function handleCreateProject(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const form = event.currentTarget;
    const submittedName = new FormData(form).get("name");
    const name = typeof submittedName === "string" ? submittedName.trim() : "";
    if (!name) return;

    const controller = new AbortController();
    const timeout = window.setTimeout(() => controller.abort(), 15_000);
    setIsCreating(true);
    setError(null);
    setProjectCreationError(null);
    try {
      const project = await createProject(name, controller.signal);
      setProjects((current) => [project, ...current]);
      dispatch({ projectId: project.id, type: "selectProject" });
      form.reset();
      setIsNewProjectDialogOpen(false);
    } catch {
      setProjectCreationError(
        controller.signal.aborted
          ? "Project creation timed out. Check your Projects list before trying again."
          : "The Project could not be created. Try again.",
      );
    } finally {
      window.clearTimeout(timeout);
      setIsCreating(false);
    }
  }

  function closeNewProjectDialog() {
    setIsNewProjectDialogOpen(false);
    projectPicker.current?.focus();
  }

  useEffect(() => {
    function resize(event: MouseEvent) {
      const navigator = navigatorRef.current;
      if (!isResizingNavigator.current || !navigator) return;
      const { left } = navigator.getBoundingClientRect();
      setNavigatorWidth(Math.max(208, Math.min(480, event.clientX - left)));
    }
    function stopResizing() {
      isResizingNavigator.current = false;
    }
    window.addEventListener("mousemove", resize);
    window.addEventListener("mouseup", stopResizing);
    return () => {
      window.removeEventListener("mousemove", resize);
      window.removeEventListener("mouseup", stopResizing);
    };
  }, []);

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
    const projectId = workspace.selectedProjectId;
    if (projectId) userSelectedActivityProjects.current.add(projectId);
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
      className={`${styles.shell} ${selectedWorkspace?.mobileSurface === "artifact" ? styles.mobileArtifactOpen : ""} ${isExplorerActivity ? styles.explorerOpen : ""} ${isWorkflowActivity ? styles.workflowOpen : ""}`}
      style={{ "--navigator-width": `${navigatorWidth}px` } as CSSProperties}
    >
      <header className={styles.titlebar}>
        <span aria-hidden="true" className={styles.mark}>
          A
        </span>
        <div className={styles.projectControls}>
          <label className={styles.projectPicker}>
            <span className={styles.srOnly}>Selected Project</span>
            <select
              disabled={!isInteractive}
              onChange={(event) => {
                if (event.target.value === "new-project") {
                  setProjectCreationError(null);
                  setIsNewProjectDialogOpen(true);
                  return;
                }
                dispatch({
                  projectId: event.target.value || null,
                  type: "selectProject",
                });
              }}
              ref={projectPicker}
              value={workspace.selectedProjectId ?? ""}
            >
              <option value="">No Project selected</option>
              {projects.map((project) => (
                <option key={project.id} value={project.id}>
                  {project.name} · {project.id.slice(0, 8)}
                </option>
              ))}
              <option value="new-project">New Project…</option>
            </select>
          </label>
        </div>
        <button
          aria-controls="mobile-project-navigation"
          aria-expanded={isMobileNavigationOpen}
          aria-label="Open Project navigation"
          className={styles.mobileNavigationToggle}
          onClick={() => setIsMobileNavigationOpen(true)}
          type="button"
        >
          Navigation
        </button>
        <span className={styles.foundation}>
          Foundation · Project workspace
        </span>
      </header>

      {isNewProjectDialogOpen ? (
        <div
          aria-labelledby="new-project-title"
          aria-modal="true"
          className={styles.newProjectDialogBackdrop}
          role="dialog"
        >
          <form
            className={styles.newProjectDialog}
            onSubmit={handleCreateProject}
          >
            <div className={styles.newProjectDialogHeading}>
              <div>
                <p className={styles.eyebrow}>Project workspace</p>
                <h2 id="new-project-title">New Project</h2>
              </div>
              <button
                aria-label="Close New Project"
                className={styles.newProjectDialogClose}
                onClick={closeNewProjectDialog}
                type="button"
              >
                Close
              </button>
            </div>
            <label className={styles.newProjectNameField}>
              <span>Project name</span>
              <input
                aria-label="Project name"
                disabled={isCreating}
                maxLength={120}
                name="name"
                placeholder="e.g. Riverside extension"
                ref={newProjectNameInput}
                required
              />
            </label>
            {projectCreationError ? (
              <p className={styles.error} role="alert">
                {projectCreationError}
              </p>
            ) : null}
            <div className={styles.newProjectDialogActions}>
              <button
                className={styles.newProjectCancel}
                disabled={isCreating}
                onClick={closeNewProjectDialog}
                type="button"
              >
                Cancel
              </button>
              <button
                className={styles.newProjectSubmit}
                disabled={isCreating}
                type="submit"
              >
                {isCreating ? "Creating…" : "Create Project"}
              </button>
            </div>
          </form>
        </div>
      ) : null}

      <nav aria-label="Project views" className={styles.rail}>
        {activityViews.map((view) => (
          <button
            aria-label={activityLabels[view]}
            aria-pressed={selectedActivity === view}
            className={styles.railButton}
            disabled={!selectedProject}
            key={view}
            onClick={() => handleSelectActivity(view)}
            title={activityLabels[view]}
            type="button"
          >
            {activityLabels[view]}
          </button>
        ))}
      </nav>

      <aside className={styles.navigator} ref={navigatorRef}>
        <ProjectNavigator
          libraryRefreshKey={libraryRefreshKey}
          onCreateThread={() => void handleCreateThread()}
          onDeleteThread={(thread) => void handleDeleteThread(thread)}
          onOpenArtifact={(artifactId) =>
            dispatch({ artifactId, type: "openArtifact" })
          }
          onRenameThread={(thread) => void handleRenameThread(thread)}
          onOpenProjectFile={(path) =>
            dispatch({ path, type: "openProjectFile" })
          }
          onSelectFunction={selectFunction}
          onSelectThread={(threadId) =>
            dispatch({ threadId, type: "selectThread" })
          }
          project={selectedProject}
          selectedActivity={selectedActivity}
          selectedThreadId={selectedThread?.id}
          selectedFunctionId={selectedWorkspace?.selectedFunctionId ?? null}
          threads={selectedThreads}
        />
        <div
          aria-label="Resize Project navigator"
          aria-orientation="vertical"
          aria-valuemax={480}
          aria-valuemin={208}
          aria-valuenow={navigatorWidth}
          className={styles.navigatorResizeHandle}
          onKeyDown={(event) => {
            if (event.key === "ArrowLeft" || event.key === "ArrowRight") {
              event.preventDefault();
              setNavigatorWidth((current) =>
                Math.max(
                  208,
                  Math.min(
                    480,
                    current + (event.key === "ArrowRight" ? 16 : -16),
                  ),
                ),
              );
            }
          }}
          onMouseDown={() => {
            isResizingNavigator.current = true;
          }}
          role="separator"
          tabIndex={0}
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
            className={`${styles.mobileNavigationDrawer} ${selectedActivity === "functions" ? styles.mobileNavigationDrawerWide : ""}`}
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
                libraryRefreshKey={libraryRefreshKey}
                onCreateThread={() => void handleCreateThread()}
                onDeleteThread={(thread) => void handleDeleteThread(thread)}
                onOpenArtifact={(artifactId) => {
                  dispatch({ artifactId, type: "openArtifact" });
                  setIsMobileNavigationOpen(false);
                }}
                onRenameThread={(thread) => void handleRenameThread(thread)}
                onOpenProjectFile={(path) => {
                  dispatch({ path, type: "openProjectFile" });
                  setIsMobileNavigationOpen(false);
                }}
                onSelectFunction={selectFunction}
                onSelectThread={(threadId) => {
                  dispatch({ threadId, type: "selectThread" });
                  setIsMobileNavigationOpen(false);
                }}
                project={selectedProject}
                selectedActivity={selectedActivity}
                selectedThreadId={selectedThread?.id}
                selectedFunctionId={
                  selectedWorkspace?.selectedFunctionId ?? null
                }
                threads={selectedThreads}
              />
            </div>
          </aside>
        </>
      ) : null}

      <section className={styles.chat}>
        {selectedProject && selectedActivity === "workflows" ? (
          <WorkflowOverview
            onOpenChats={() => handleSelectActivity("chats")}
            onOpenLibrary={() => handleSelectActivity("artifacts")}
            onOpenFunction={(node) => {
              dispatch({
                functionId: node.refId,
                type: "selectFunction",
              });
              handleSelectActivity("functions");
            }}
            projectId={selectedProject.id}
          />
        ) : selectedProject &&
          selectedThread &&
          selectedActivity === "chats" ? (
          <AgentChat
            key={selectedThread.id}
            onOpenFileProposal={(proposal) =>
              dispatch({ proposal, type: "openFileProposal" })
            }
            onOpenArtifact={(artifactId) =>
              dispatch({ artifactId, type: "openArtifact" })
            }
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
        {selectedProject && selectedWorkspace?.selectedFileProposal ? (
          <ProposedFilePreview
            proposal={selectedWorkspace.selectedFileProposal}
          />
        ) : selectedProject && selectedWorkspace?.selectedArtifactId ? (
          <ArtifactDocumentPreview
            artifactId={selectedWorkspace.selectedArtifactId}
            projectId={selectedProject.id}
          />
        ) : selectedProject &&
          selectedWorkspace?.selectedFilePath &&
          selectedWorkspace.selectedScratchThreadId ? (
          <ScratchFilePreview
            onSavedToProject={(path) =>
              dispatch({ path, type: "openProjectFile" })
            }
            path={selectedWorkspace.selectedFilePath}
            projectId={selectedProject.id}
            threadId={selectedWorkspace.selectedScratchThreadId}
          />
        ) : selectedProject &&
          selectedWorkspace?.selectedFilePath?.startsWith(
            "/project/.datasets/",
          ) &&
          selectedWorkspace.selectedFilePath.endsWith(".json") ? (
          <DatasetFilePreview
            datasetId={selectedWorkspace.selectedFilePath
              .split("/")
              .at(-1)!
              .slice(0, -5)}
            key={`${selectedProject.id}:${selectedWorkspace.selectedFilePath}`}
            onSaved={() => setLibraryRefreshKey((current) => current + 1)}
            projectId={selectedProject.id}
          />
        ) : selectedProject && selectedWorkspace?.selectedFilePath ? (
          <ProjectFilePreview
            path={selectedWorkspace.selectedFilePath}
            projectId={selectedProject.id}
          />
        ) : (
          <>
            <strong>Library preview</strong>
            <p>
              Open a Project file, an Artifact, or a Thread-local scratch file
              to inspect it here.
            </p>
          </>
        )}
      </aside>
    </main>
  );
}

interface ProjectNavigatorProps {
  libraryRefreshKey: number;
  onCreateThread: () => void;
  onDeleteThread: (thread: Thread) => void;
  onOpenArtifact: (artifactId: string) => void;
  onOpenProjectFile: (path: string) => void;
  onSelectFunction: (definitionId: string | null) => void;
  onRenameThread: (thread: Thread) => void;
  onSelectThread: (threadId: string) => void;
  project: Project | undefined;
  selectedActivity: ActivityView;
  selectedThreadId: string | undefined;
  selectedFunctionId: string | null;
  threads: Thread[];
}

function ProjectNavigator({
  libraryRefreshKey,
  onCreateThread,
  onDeleteThread,
  onOpenArtifact,
  onOpenProjectFile,
  onSelectFunction,
  onRenameThread,
  onSelectThread,
  project,
  selectedActivity,
  selectedThreadId,
  selectedFunctionId,
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
                <div className={styles.itemActions}>
                  <Menu label={`${thread.title} actions`}>
                    <MenuItem onSelect={() => onRenameThread(thread)}>
                      Rename
                    </MenuItem>
                    <MenuItem
                      destructive
                      onSelect={() => onDeleteThread(thread)}
                    >
                      Delete
                    </MenuItem>
                  </Menu>
                </div>
              </div>
            ))}
          </div>
        </>
      ) : selectedActivity === "artifacts" && project ? (
        <LibraryCatalog
          onOpenArtifact={onOpenArtifact}
          onOpenProjectFile={onOpenProjectFile}
          projectId={project.id}
          refreshKey={libraryRefreshKey}
        />
      ) : selectedActivity === "functions" && project ? (
        <FunctionCatalog
          key={project.id}
          onSelectFunction={onSelectFunction}
          projectId={project.id}
          selectedFunctionId={selectedFunctionId}
        />
      ) : selectedActivity === "plugins" && project ? (
        <PluginCatalog projectId={project.id} />
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

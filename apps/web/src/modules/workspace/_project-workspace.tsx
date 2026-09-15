"use client";

import { FormEvent, useEffect, useReducer, useRef, useState } from "react";

import { AgentChat, ScratchFilePreview } from "@/modules/agent-ui";
import { ProjectFilePreview } from "@/modules/project-files";
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
  const [isCreating, setIsCreating] = useState(false);
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
    <main className={styles.shell}>
      <header className={styles.titlebar}>
        <span aria-hidden="true" className={styles.mark}>
          A
        </span>
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
            maxLength={120}
            name="name"
            placeholder="New Project"
            required
          />
          <button disabled={isCreating} type="submit">
            {isCreating ? "Creating…" : "Create"}
          </button>
        </form>
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
        <strong>{activityLabels[selectedActivity]}</strong>
        {selectedActivity === "chats" && selectedProject ? (
          <>
            <button
              className={styles.newThread}
              onClick={handleCreateThread}
              type="button"
            >
              + New Thread
            </button>
            <div className={styles.threadList}>
              {selectedThreads.map((thread) => (
                <div className={styles.threadRow} key={thread.id}>
                  <button
                    aria-pressed={selectedThread?.id === thread.id}
                    className={styles.threadButton}
                    onClick={() =>
                      dispatch({ threadId: thread.id, type: "selectThread" })
                    }
                    type="button"
                  >
                    {thread.title}
                  </button>
                  <Menu label={`${thread.title} actions`}>
                    <MenuItem onSelect={() => void handleRenameThread(thread)}>
                      Rename
                    </MenuItem>
                    <MenuItem
                      destructive
                      onSelect={() => void handleDeleteThread(thread)}
                    >
                      Delete
                    </MenuItem>
                  </Menu>
                </div>
              ))}
            </div>
          </>
        ) : (
          <p>
            {selectedProject
              ? `${activityLabels[selectedActivity]} in ${selectedProject.name}`
              : "Create or select a Project to begin."}
          </p>
        )}
      </aside>

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

"use client";

import { FormEvent, useEffect, useReducer, useRef, useState } from "react";

import { AgentChat } from "@/modules/agent-ui";
import {
  createProject,
  createThread,
  listProjects,
  listThreads,
  type Project,
  type Thread,
} from "@/modules/projects";

import styles from "./workspace.module.css";
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
  const [newProjectName, setNewProjectName] = useState("");
  const [threadsByProject, setThreadsByProject] = useState<
    Record<string, Thread[]>
  >({});
  const [isCreating, setIsCreating] = useState(false);
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
    const name = newProjectName.trim();
    if (!name) return;

    setIsCreating(true);
    setError(null);
    try {
      const project = await createProject(name);
      setProjects((current) => [project, ...current]);
      dispatch({ projectId: project.id, type: "selectProject" });
      setNewProjectName("");
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
        `New Thread ${selectedThreads.length + 1}`,
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
            onChange={(event) => setNewProjectName(event.target.value)}
            placeholder="New Project"
            value={newProjectName}
          />
          <button disabled={isCreating || !newProjectName.trim()} type="submit">
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
                <button
                  aria-pressed={selectedThread?.id === thread.id}
                  key={thread.id}
                  onClick={() =>
                    dispatch({ threadId: thread.id, type: "selectThread" })
                  }
                  type="button"
                >
                  {thread.title}
                </button>
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
        <strong>Artifact workspace</strong>
        <p>MCP App hosting arrives in Slice 7.</p>
      </aside>
    </main>
  );
}

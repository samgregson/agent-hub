"use client";

import { FormEvent, useEffect, useReducer, useState } from "react";

import { createProject, listProjects, type Project } from "@/modules/projects";

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
        <p>
          {selectedProject
            ? `${activityLabels[selectedActivity]} in ${selectedProject.name}`
            : "Create or select a Project to begin."}
        </p>
      </aside>

      <section className={styles.chat}>
        <div>
          <p className={styles.eyebrow}>Agent Hub</p>
          <h1>{selectedProject?.name ?? "Choose a Project"}</h1>
          <p>
            {selectedProject
              ? "This workspace is scoped to the selected Project. Agent streaming arrives in Slice 2."
              : "Projects keep conversations, files, sources, Plugins, and Artifacts together."}
          </p>
          {error ? <p className={styles.error}>{error}</p> : null}
        </div>
      </section>

      <aside className={styles.artifact}>
        <strong>Artifact workspace</strong>
        <p>MCP App hosting arrives in Slice 7.</p>
      </aside>
    </main>
  );
}

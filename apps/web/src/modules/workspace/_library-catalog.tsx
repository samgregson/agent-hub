"use client";

import { useEffect, useState } from "react";

import type { ArtifactCatalog, ProjectFileCatalog } from "@/contracts";
import { Collection, CollectionItem, Menu, MenuItem } from "@/shared/ui";

import styles from "./workspace.module.css";

type LibraryItem =
  | { id: string; kind: "artifact"; label: string; version: number }
  | { kind: "projectFile"; label: string; path: string; version: number };

type PendingDeletion = LibraryItem | null;

interface LibraryCatalogResult {
  error: string | null;
  items: LibraryItem[] | null;
  projectId: string;
}

function combineLibraryItems(
  artifacts: ArtifactCatalog,
  files: ProjectFileCatalog,
): LibraryItem[] {
  return [
    ...artifacts.artifacts.map((artifact) => ({
      id: artifact.id,
      kind: "artifact" as const,
      label: artifact.title,
      version: artifact.documentVersion,
    })),
    ...files.files.map((file) => ({
      kind: "projectFile" as const,
      label: file.path,
      path: file.path,
      version: file.version,
    })),
  ].sort((left, right) => left.label.localeCompare(right.label));
}

export function LibraryCatalog({
  onOpenArtifact,
  onOpenProjectFile,
  projectId,
}: {
  onOpenArtifact: (artifactId: string) => void;
  onOpenProjectFile: (path: string) => void;
  projectId: string;
}) {
  const [result, setResult] = useState<LibraryCatalogResult>({
    error: null,
    items: null,
    projectId: "",
  });
  const [pendingDeletion, setPendingDeletion] = useState<PendingDeletion>(null);
  const [deleteError, setDeleteError] = useState<string | null>(null);
  const [isDeleting, setIsDeleting] = useState(false);
  const items = result.projectId === projectId ? result.items : null;
  const error = result.projectId === projectId ? result.error : null;

  async function deleteItem(item: LibraryItem) {
    setIsDeleting(true);
    setDeleteError(null);
    try {
      const encodedProjectId = encodeURIComponent(projectId);
      const response =
        item.kind === "artifact"
          ? await fetch(
              `/api/projects/${encodedProjectId}/artifacts/${encodeURIComponent(item.id)}`,
              { method: "DELETE" },
            )
          : await fetch(
              `/api/projects/${encodedProjectId}/files?path=${encodeURIComponent(item.path)}`,
              { method: "DELETE" },
            );
      if (!response.ok) throw new Error(String(response.status));
      setResult((current) =>
        current.projectId !== projectId || current.items === null
          ? current
          : {
              ...current,
              items: current.items.filter((candidate) => candidate !== item),
            },
      );
      setPendingDeletion(null);
    } catch {
      setDeleteError("Deletion failed. Please try again.");
    } finally {
      setIsDeleting(false);
    }
  }

  useEffect(() => {
    let active = true;
    const encodedProjectId = encodeURIComponent(projectId);
    Promise.all([
      fetch(`/api/projects/${encodedProjectId}/artifacts`, {
        cache: "no-store",
      }),
      fetch(`/api/projects/${encodedProjectId}/files/index`, {
        cache: "no-store",
      }),
    ])
      .then(async ([artifactResponse, fileResponse]) => {
        if (!artifactResponse.ok || !fileResponse.ok) {
          throw new Error("Library catalog unavailable");
        }
        return combineLibraryItems(
          (await artifactResponse.json()) as ArtifactCatalog,
          (await fileResponse.json()) as ProjectFileCatalog,
        );
      })
      .then((loaded) => {
        if (active) setResult({ error: null, items: loaded, projectId });
      })
      .catch(() => {
        if (active) {
          setResult({
            error: "Library items are temporarily unavailable.",
            items: null,
            projectId,
          });
        }
      });
    return () => {
      active = false;
    };
  }, [projectId]);

  return (
    <section aria-label="Library items">
      {error ? <p className={styles.error}>{error}</p> : null}
      {!items && !error ? <p>Loading Library…</p> : null}
      <Collection>
        {items?.map((item) => (
          <CollectionItem
            actions={
              <Menu label={`${item.label} actions`}>
                <MenuItem
                  destructive
                  onSelect={() => {
                    setDeleteError(null);
                    setPendingDeletion(item);
                  }}
                >
                  Delete
                </MenuItem>
              </Menu>
            }
            details={`Version ${item.version}`}
            key={item.kind === "artifact" ? item.id : item.path}
            openLabel={item.label}
            onOpen={() =>
              item.kind === "artifact"
                ? onOpenArtifact(item.id)
                : onOpenProjectFile(item.path)
            }
            title={item.label}
          />
        ))}
      </Collection>
      {items?.length === 0 ? <p>No Library items yet.</p> : null}
      {pendingDeletion ? (
        <dialog
          aria-label="Confirm deletion"
          className={styles.deleteDialog}
          open
        >
          <p className={styles.deleteDialogEyebrow}>Permanent removal</p>
          <h2>
            Delete this{" "}
            {pendingDeletion.kind === "artifact" ? "Artifact" : "Project File"}?
          </h2>
          <code>{pendingDeletion.label}</code>
          <p>This cannot be undone.</p>
          {deleteError ? <p className={styles.error}>{deleteError}</p> : null}
          <div className={styles.deleteDialogActions}>
            <button
              disabled={isDeleting}
              onClick={() => setPendingDeletion(null)}
              type="button"
            >
              Cancel
            </button>
            <button
              disabled={isDeleting}
              onClick={() => void deleteItem(pendingDeletion)}
              type="button"
            >
              {isDeleting ? "Deleting…" : "Delete"}
            </button>
          </div>
        </dialog>
      ) : null}
    </section>
  );
}

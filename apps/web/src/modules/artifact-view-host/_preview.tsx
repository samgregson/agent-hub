"use client";

import { useCallback, useEffect, useState } from "react";

import type { ArtifactDocument } from "@/contracts";

import { ArtifactApp } from "./_app";
import styles from "./artifact-view-host.module.css";

interface PreviewResult {
  document: ArtifactDocument | null;
  error: string | null;
  key: string;
}

export function ArtifactDocumentPreview({
  artifactId,
  projectId,
}: {
  artifactId: string;
  projectId: string;
}) {
  const key = `${projectId}:${artifactId}`;
  const [result, setResult] = useState<PreviewResult>({
    document: null,
    error: null,
    key: "",
  });
  const document = result.key === key ? result.document : null;
  const error = result.key === key ? result.error : null;
  const [staleKey, setStaleKey] = useState<string | null>(null);
  const isStale = staleKey === key;

  const load = useCallback(async () => {
    const response = await fetch(
      `/api/projects/${encodeURIComponent(projectId)}/artifacts/${encodeURIComponent(artifactId)}`,
      { cache: "no-store" },
    );
    if (!response.ok) throw new Error(String(response.status));
    return (await response.json()) as ArtifactDocument;
  }, [artifactId, projectId]);

  async function reload() {
    const loaded = await load();
    setResult({ document: loaded, error: null, key });
    setStaleKey(null);
  }

  useEffect(() => {
    let active = true;
    void load()
      .then((loaded) => {
        if (active) setResult({ document: loaded, error: null, key });
      })
      .catch(() => {
        if (active) {
          setResult({
            document: null,
            error: "This Artifact could not be opened.",
            key,
          });
        }
      });
    return () => {
      active = false;
    };
  }, [key, load]);

  useEffect(() => {
    function checkOnFocus() {
      if (!document) return;
      void load()
        .then((loaded) => {
          if (loaded.artifact.documentVersion !== document.artifact.documentVersion) {
            setStaleKey(key);
          }
        })
        .catch(() => {});
    }
    window.addEventListener("focus", checkOnFocus);
    return () => window.removeEventListener("focus", checkOnFocus);
  }, [document, key, load]);

  return (
    <section className={styles.preview}>
      {error ? <p className={styles.error}>{error}</p> : null}
      {!document && !error ? <p>Opening Artifact…</p> : null}
      {document ? (
        <>
          <header>
            <strong>{document.artifact.title}</strong>
            <code>{document.artifact.id}</code>
            <span>Version {document.artifact.documentVersion}</span>
          </header>
          {document.artifact.summary ? <p>{document.artifact.summary}</p> : null}
          {isStale ? (
            <p className={styles.error}>
              This Artifact changed in another Thread. <button onClick={() => void reload()} type="button">Reload</button>
            </p>
          ) : null}
          <dl>
            <div>
              <dt>Type</dt>
              <dd>{document.artifact.type}</dd>
            </div>
            <div>
              <dt>Plugin</dt>
              <dd>
                {document.artifact.plugin.id} {document.artifact.plugin.version}
              </dd>
            </div>
            <div>
              <dt>Created by</dt>
              <dd>{provenanceLabel(document.artifact.provenance.createdBy)}</dd>
            </div>
            <div>
              <dt>Last changed by</dt>
              <dd>{provenanceLabel(document.artifact.provenance.lastChangedBy)}</dd>
            </div>
          </dl>
          <ArtifactApp
            artifactId={artifactId}
            projectId={projectId}
          />
          <details className={styles.fallback}>
            <summary>Generic safe view</summary>
            <pre>{JSON.stringify(document.payload, null, 2)}</pre>
          </details>
        </>
      ) : null}
    </section>
  );
}

function provenanceLabel(actor: ArtifactDocument["artifact"]["provenance"]["createdBy"]) {
  return actor.kind === "agentRun"
    ? `Thread ${actor.threadId} · Run ${actor.runId}`
    : `User action ${actor.userActionId}`;
}

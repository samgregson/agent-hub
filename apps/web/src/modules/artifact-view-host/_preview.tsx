"use client";

import { useEffect, useState } from "react";

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

  useEffect(() => {
    let active = true;
    fetch(
      `/api/projects/${encodeURIComponent(projectId)}/artifacts/${encodeURIComponent(artifactId)}`,
      { cache: "no-store" },
    )
      .then(async (response) => {
        if (!response.ok) throw new Error(String(response.status));
        return (await response.json()) as ArtifactDocument;
      })
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
  }, [artifactId, key, projectId]);

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
          </dl>
          <ArtifactApp
            artifactId={artifactId}
            document={document}
            onSaved={(saved) => setResult({ document: saved, error: null, key })}
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

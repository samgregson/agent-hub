"use client";

import { AppBridge, PostMessageTransport } from "@modelcontextprotocol/ext-apps/app-bridge";
import { useEffect, useRef, useState } from "react";

import type { ArtifactDocument } from "@/contracts";

import styles from "./artifact-view-host.module.css";

function toolError(message: string) {
  return { content: [{ text: message, type: "text" as const }], isError: true };
}

export function ArtifactApp({
  artifactId,
  document,
  onSaved,
  projectId,
}: {
  artifactId: string;
  document: ArtifactDocument;
  onSaved: (document: ArtifactDocument) => void;
  projectId: string;
}) {
  const frame = useRef<HTMLIFrameElement>(null);
  const [error, setError] = useState<string | null>(null);
  const [availability, setAvailability] = useState<
    "available" | "loading" | "unavailable"
  >("loading");
  const documentRef = useRef(document);
  documentRef.current = document;
  const appUrl = `/api/projects/${encodeURIComponent(projectId)}/artifacts/${encodeURIComponent(artifactId)}/app`;

  useEffect(() => {
    let active = true;
    setAvailability("loading");
    setError(null);
    fetch(appUrl, { cache: "no-store" })
      .then((response) => {
        if (!response.ok) throw new Error(String(response.status));
        if (active) setAvailability("available");
      })
      .catch(() => {
        if (active) setAvailability("unavailable");
      });
    return () => {
      active = false;
    };
  }, [appUrl]);

  useEffect(() => {
    if (availability !== "available") return;
    const iframe = frame.current;
    if (!iframe?.contentWindow) return;
    let disposed = false;
    const bridge = new AppBridge(
      null,
      { name: "Agent Hub", version: "0.0.0" },
      { sandbox: { csp: {}, permissions: {} }, serverTools: {} },
      { hostContext: { platform: "web" } },
    );

    bridge.oncalltool = async ({ arguments: toolArguments, name }) => {
      if (name !== "set_status_artifact_status") {
        return toolError("This App tool is not permitted by Agent Hub.");
      }
      const response = await fetch(
        `/api/projects/${encodeURIComponent(projectId)}/artifacts/${encodeURIComponent(artifactId)}/app/actions`,
        {
          body: JSON.stringify({
            arguments: toolArguments ?? {},
            expectedVersion: documentRef.current.artifact.documentVersion,
            name,
          }),
          headers: { "content-type": "application/json" },
          method: "POST",
        },
      );
      if (!response.ok) {
        return toolError(
          response.status === 409
            ? "The Artifact is stale. Reload before editing."
            : "The requested Artifact change was rejected.",
        );
      }
      const saved = (await response.json()) as ArtifactDocument;
      documentRef.current = saved;
      onSaved(saved);
      return {
        content: [{ text: "Artifact change saved.", type: "text" as const }],
        structuredContent: saved,
      };
    };
    bridge.oninitialized = () => {
      void bridge
        .sendToolInput({ arguments: { document: documentRef.current } })
        .then(() =>
          bridge.sendToolResult({
            content: [],
            structuredContent: documentRef.current,
          }),
        )
        .catch(() => {
          if (!disposed) setError("The Artifact App could not be initialized.");
        });
    };

    void bridge
      .connect(new PostMessageTransport(iframe.contentWindow, iframe.contentWindow))
      .then(() => {
        if (!disposed) iframe.src = appUrl;
      })
      .catch(() => {
        if (!disposed) setError("The Artifact App could not be initialized.");
      });
    return () => {
      disposed = true;
      void bridge.teardownResource({}).catch(() => {});
      void bridge.close();
    };
  }, [appUrl, artifactId, availability, projectId]);

  return (
    <section aria-label="Artifact App" className={styles.app}>
      {error ? <p className={styles.error}>{error}</p> : null}
      {availability === "loading" ? <p>Loading compatible Artifact App…</p> : null}
      {availability === "unavailable" ? (
        <p>A compatible Artifact App is unavailable. The generic safe view is shown below.</p>
      ) : null}
      {availability === "available" ? (
        <iframe
          className={styles.appFrame}
          ref={frame}
          referrerPolicy="no-referrer"
          sandbox="allow-scripts"
          title={`${document.artifact.title} App`}
        />
      ) : null}
    </section>
  );
}

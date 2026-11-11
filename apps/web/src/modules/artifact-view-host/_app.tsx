"use client";

import {
  AppBridge,
  PostMessageTransport,
} from "@modelcontextprotocol/ext-apps/app-bridge";
import { useCallback, useEffect, useRef, useState } from "react";

import { Button } from "@/shared/ui";

import type { ArtifactDocument } from "@/contracts";

import styles from "./artifact-view-host.module.css";

function toolError(message: string) {
  return { content: [{ text: message, type: "text" as const }], isError: true };
}

type McpToolResult = {
  content: { type: "text"; text: string }[];
  structuredContent: Record<string, unknown>;
};

interface AppState {
  availability: "available" | "loading" | "unavailable";
  message: string | null;
  key: string;
}

export function McpAppFrame({
  appUrl,
  toolInput,
  toolResult,
  title,
  displayTitle,
}: {
  appUrl: string;
  toolInput: Record<string, unknown>;
  toolResult: McpToolResult;
  title: string;
  displayTitle?: string;
}) {
  const frame = useRef<HTMLIFrameElement>(null);
  const dialog = useRef<HTMLDialogElement>(null);
  const toolbar = useRef<HTMLDivElement>(null);
  const bridgeRef = useRef<AppBridge | null>(null);
  const expandedRef = useRef(false);
  const [expanded, setExpanded] = useState(false);
  const setDisplayMode = useCallback((next: boolean) => {
    const container = dialog.current;
    if (!container || next === expandedRef.current) return;
    container.close();
    if (next) container.showModal();
    else container.show();
    expandedRef.current = next;
    setExpanded(next);
    bridgeRef.current?.setHostContext({
      platform: "web",
      theme: "light",
      displayMode: next ? "fullscreen" : "inline",
      availableDisplayModes: ["inline", "fullscreen"],
    });
    toolbar.current?.querySelector("button")?.focus();
  }, []);
  const payload = useRef({ toolInput, toolResult });
  const [attempt, setAttempt] = useState(0);
  const requestKey = `${appUrl}:${attempt}`;
  const [appState, setAppState] = useState<AppState>({
    availability: "loading",
    message: null,
    key: "",
  });
  const availability =
    appState.key === requestKey ? appState.availability : "loading";
  const message = appState.key === requestKey ? appState.message : null;

  useEffect(() => {
    payload.current = { toolInput, toolResult };
  }, [toolInput, toolResult]);

  useEffect(() => {
    let active = true;
    fetch(appUrl, { cache: "no-store" })
      .then((response) => {
        if (!response.ok) {
          if (response.status === 404 || response.status === 422) {
            throw new Error("unavailable");
          }
          throw new Error("load_failed");
        }
        if (active) {
          setAppState({
            availability: "available",
            message: null,
            key: requestKey,
          });
        }
      })
      .catch((error: unknown) => {
        if (active) {
          setAppState({
            availability: "unavailable",
            message:
              error instanceof Error && error.message === "unavailable"
                ? "This saved result has no interactive App for its captured version. Its data is still available in the surrounding view."
                : "The interactive App could not be loaded. Its data is still available in the surrounding view.",
            key: requestKey,
          });
        }
      });
    return () => {
      active = false;
    };
  }, [appUrl, attempt, requestKey]);

  useEffect(() => {
    if (availability !== "available") return;
    const iframe = frame.current;
    if (!iframe?.contentWindow) return;
    let disposed = false;
    const bridge = new AppBridge(
      null,
      { name: "Agent Hub", version: "0.0.0" },
      { sandbox: { csp: {}, permissions: {} }, serverTools: {} },
      {
        hostContext: {
          platform: "web",
          theme: "light",
          displayMode: expandedRef.current ? "fullscreen" : "inline",
          availableDisplayModes: ["inline", "fullscreen"],
        },
      },
    );

    bridgeRef.current = bridge;
    bridge.onrequestdisplaymode = async ({ mode }) => {
      if (mode === "inline" || mode === "fullscreen")
        setDisplayMode(mode === "fullscreen");
      return { mode: expandedRef.current ? "fullscreen" : "inline" };
    };
    bridge.oncalltool = async () =>
      toolError("This preview cannot run tools or change the saved result.");
    bridge.oninitialized = () => {
      const current = payload.current;
      void bridge
        .sendToolInput({ arguments: current.toolInput })
        .then(() => bridge.sendToolResult(current.toolResult))
        .catch(() => {
          if (!disposed) {
            setAppState({
              availability: "unavailable",
              message:
                "The interactive App could not receive this saved result. Its inputs and output are still available.",
              key: requestKey,
            });
          }
        });
    };

    void bridge
      .connect(
        new PostMessageTransport(iframe.contentWindow, iframe.contentWindow),
      )
      .then(() => {
        if (!disposed) iframe.src = appUrl;
      })
      .catch(() => {
        if (!disposed) {
          setAppState({
            availability: "unavailable",
            message:
              "The interactive App could not be initialized. Its inputs and output are still available.",
            key: requestKey,
          });
        }
      });
    return () => {
      disposed = true;
      bridgeRef.current = null;
      void bridge.teardownResource({}).catch(() => {});
      void bridge.close();
    };
  }, [appUrl, availability, requestKey, setDisplayMode]);

  return (
    <section aria-label={title} className={styles.app}>
      <dialog
        open
        ref={dialog}
        role={expanded ? "dialog" : "region"}
        aria-label={displayTitle ?? title}
        className={`${styles.appDialog} ${expanded ? styles.appExpanded : ""}`}
        onCancel={(event) => {
          event.preventDefault();
          setDisplayMode(false);
        }}
      >
        <div className={styles.appToolbar} ref={toolbar}>
          <strong>{displayTitle ?? title}</strong>
          {(availability === "available" || expanded) && (
            <Button type="button" onClick={() => setDisplayMode(!expanded)}>
              {expanded ? "Close expanded App" : "Expand App"}
            </Button>
          )}
        </div>
        {availability === "loading" ? <p>Loading interactive App…</p> : null}
        {availability === "unavailable" ? (
          <div className={styles.appUnavailable} role="status">
            <p>{message}</p>
            <button
              onClick={() => setAttempt((value) => value + 1)}
              type="button"
            >
              Retry
            </button>
          </div>
        ) : null}
        {availability === "available" ? (
          <iframe
            className={styles.appFrame}
            ref={frame}
            referrerPolicy="no-referrer"
            sandbox="allow-scripts"
            title={title}
          />
        ) : null}
      </dialog>
    </section>
  );
}

export function ArtifactApp({
  artifactId,
  document,
  projectId,
}: {
  artifactId: string;
  document: ArtifactDocument;
  projectId: string;
}) {
  const appUrl = `/api/projects/${encodeURIComponent(projectId)}/artifacts/${encodeURIComponent(artifactId)}/app`;
  return (
    <McpAppFrame
      appUrl={appUrl}
      title="Artifact App"
      displayTitle={document.artifact.title}
      toolInput={{ document }}
      toolResult={{
        content: [],
        structuredContent: document as unknown as Record<string, unknown>,
      }}
    />
  );
}

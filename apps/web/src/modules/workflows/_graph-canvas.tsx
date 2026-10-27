"use client";

import { useCallback, useEffect, useMemo, useRef, useState } from "react";

import styles from "./workflow-graph.module.css";

export type GraphCanvasNode = {
  id: string;
  title: string;
  kind: string;
  status?: string;
  inputs?: string[];
  outputs?: string[];
  outputPreview?: unknown;
};

export type GraphCanvasEdge = {
  id?: string;
  source: string;
  sourcePort: string;
  target: string;
  targetPort: string;
};

export type GraphCanvasProps = {
  workflowId: string;
  version: number | string;
  nodes: GraphCanvasNode[];
  edges: GraphCanvasEdge[];
  selectedNodeId?: string | null;
  onSelectNode?: (nodeId: string | null) => void;
  className?: string;
};

type Point = { x: number; y: number };
type Drag = { id: string; pointerId: number; start: Point; origin: Point };
const NODE_WIDTH = 224;
const NODE_HEIGHT = 104;
const GAP_X = 116;
const GAP_Y = 72;
const BASE = { x: 72, y: 64 };

function safeKey(workflowId: string, version: string | number) {
  return `agent-hub:workflow-graph:layout-2:${encodeURIComponent(workflowId)}:${encodeURIComponent(String(version))}`;
}

function defaultPositions(nodes: GraphCanvasNode[], edges: GraphCanvasEdge[]) {
  const parents = new Map(nodes.map((node) => [node.id, new Set<string>()]));
  const children = new Map(nodes.map((node) => [node.id, new Set<string>()]));
  edges.forEach((edge) => {
    if (!parents.has(edge.target) || !children.has(edge.source)) return;
    parents.get(edge.target)?.add(edge.source);
    children.get(edge.source)?.add(edge.target);
  });
  const layers = new Map(nodes.map((node) => [node.id, 0]));
  for (let pass = 0; pass < nodes.length; pass += 1) {
    let changed = false;
    for (const node of nodes) {
      const layer = Math.max(
        0,
        ...[...(parents.get(node.id) ?? [])].map(
          (id) => (layers.get(id) ?? 0) + 1,
        ),
      );
      if (layer > (layers.get(node.id) ?? 0)) {
        layers.set(node.id, layer);
        changed = true;
      }
    }
    if (!changed) break;
  }
  const columns = new Map<number, GraphCanvasNode[]>();
  nodes.forEach((node) => {
    const column = layers.get(node.id) ?? 0;
    columns.set(column, [...(columns.get(column) ?? []), node]);
  });
  const positions: Record<string, Point> = {};
  for (const column of [...columns.keys()].sort((a, b) => a - b)) {
    const placed = (columns.get(column) ?? []).map((node, row) => {
      const upstream = [...(parents.get(node.id) ?? [])]
        .map((id) => positions[id]?.y)
        .filter((y): y is number => y !== undefined);
      return {
        node,
        desired: upstream.length
          ? upstream.reduce((sum, y) => sum + y, 0) / upstream.length
          : BASE.y + row * (NODE_HEIGHT + GAP_Y),
      };
    });
    placed.sort((a, b) => a.desired - b.desired);
    let previousY = BASE.y - NODE_HEIGHT - GAP_Y;
    for (const { node, desired } of placed) {
      const y = Math.max(BASE.y, desired, previousY + NODE_HEIGHT + GAP_Y);
      positions[node.id] = {
        x: BASE.x + column * (NODE_WIDTH + GAP_X),
        y,
      };
      previousY = y;
    }
  }
  return positions;
}

function pretty(value: unknown) {
  if (value === undefined) return "No output captured yet.";
  try {
    return JSON.stringify(value, null, 2) ?? "null";
  } catch {
    return String(value);
  }
}

export function GraphCanvas({
  workflowId,
  version,
  nodes,
  edges,
  selectedNodeId,
  onSelectNode,
  className,
}: GraphCanvasProps) {
  const viewportRef = useRef<HTMLDivElement>(null);
  const dragRef = useRef<Drag | null>(null);
  const defaults = useMemo(
    () => defaultPositions(nodes, edges),
    [nodes, edges],
  );
  const [positions, setPositions] = useState<Record<string, Point>>({});
  const [editedKey, setEditedKey] = useState<string | null>(null);
  const [zoom, setZoom] = useState(1);
  const [pan, setPan] = useState<Point>({ x: 0, y: 0 });
  const [viewport, setViewport] = useState({ width: 0, height: 0 });
  const [loadedKey, setLoadedKey] = useState<string | null>(null);
  const [focusedId, setFocusedId] = useState<string | null>(null);
  const [panDrag, setPanDrag] = useState<{
    start: Point;
    origin: Point;
    pointerId: number;
  } | null>(null);
  const storageKey = useMemo(
    () => safeKey(workflowId, version),
    [workflowId, version],
  );

  useEffect(() => {
    const frame = window.requestAnimationFrame(() => {
      try {
        const saved = window.localStorage.getItem(storageKey);
        const decoded: unknown = saved ? JSON.parse(saved) : {};
        if (decoded && typeof decoded === "object" && !Array.isArray(decoded)) {
          const valid = Object.fromEntries(
            Object.entries(decoded).filter(
              ([, value]) =>
                value &&
                typeof value === "object" &&
                Number.isFinite((value as Point).x) &&
                Number.isFinite((value as Point).y),
            ),
          ) as Record<string, Point>;
          setPositions(
            Object.fromEntries(
              nodes.map((node) => [
                node.id,
                valid[node.id] ?? defaults[node.id],
              ]),
            ),
          );
        } else setPositions(defaults);
      } catch {
        setPositions(defaults);
      }
      setLoadedKey(storageKey);
    });
    return () => window.cancelAnimationFrame(frame);
  }, [storageKey, defaults, nodes]);

  useEffect(() => {
    const element = viewportRef.current;
    if (!element) return;
    const observer = new ResizeObserver(([entry]) =>
      setViewport({
        width: entry.contentRect.width,
        height: entry.contentRect.height,
      }),
    );
    observer.observe(element);
    return () => observer.disconnect();
  }, []);

  useEffect(() => {
    if (
      loadedKey !== storageKey ||
      editedKey !== storageKey ||
      nodes.length === 0
    )
      return;
    try {
      window.localStorage.setItem(storageKey, JSON.stringify(positions));
    } catch {
      /* Storage may be unavailable in private browsing. */
    }
  }, [positions, storageKey, loadedKey, editedKey, nodes.length]);

  const current = useMemo(
    () =>
      Object.fromEntries(
        nodes.map((node) => [node.id, positions[node.id] ?? defaults[node.id]]),
      ),
    [nodes, positions, defaults],
  );
  const bounds = useMemo(() => {
    const points = Object.values(current);
    return points.length
      ? {
          width:
            Math.max(...points.map((point) => point.x + NODE_WIDTH)) + BASE.x,
          height:
            Math.max(...points.map((point) => point.y + NODE_HEIGHT)) + BASE.y,
        }
      : { width: 0, height: 0 };
  }, [current]);
  const finishPointer = useCallback(
    (event?: React.PointerEvent) => {
      if (
        event &&
        dragRef.current &&
        dragRef.current.pointerId !== event.pointerId &&
        panDrag?.pointerId !== event.pointerId
      )
        return;
      dragRef.current = null;
      setPanDrag(null);
    },
    [panDrag],
  );

  const fit = useCallback(() => {
    if (!viewport.width || !viewport.height || !bounds.width || !bounds.height)
      return;
    const nextZoom = Math.min(
      1.2,
      Math.max(
        0.42,
        Math.min(
          (viewport.width - 72) / bounds.width,
          (viewport.height - 72) / bounds.height,
        ),
      ),
    );
    setZoom(nextZoom);
    setPan({
      x: Math.max(20, (viewport.width - bounds.width * nextZoom) / 2),
      y: Math.max(20, (viewport.height - bounds.height * nextZoom) / 2),
    });
  }, [bounds, viewport]);
  const fitRef = useRef(fit);
  useEffect(() => {
    fitRef.current = fit;
  }, [fit]);
  const nodeSignature = nodes.map((node) => node.id).join("|");
  const lastFittedGraph = useRef<string | null>(null);
  useEffect(() => {
    if (loadedKey !== storageKey || !viewport.width || !viewport.height) return;
    const viewportMode = viewport.width <= 420 ? "compact" : "spacious";
    const graphKey = `${storageKey}:${nodeSignature}:${viewportMode}`;
    if (lastFittedGraph.current === graphKey) return;
    lastFittedGraph.current = graphKey;
    fitRef.current();
  }, [viewport.width, viewport.height, loadedKey, storageKey, nodeSignature]);
  useEffect(() => {
    const cleanup = () => finishPointer();
    window.addEventListener("blur", cleanup);
    return () => window.removeEventListener("blur", cleanup);
  }, [finishPointer]);

  const moveNode = (id: string, dx: number, dy: number) => {
    setEditedKey(storageKey);
    setPositions((existing) => ({
      ...existing,
      [id]: {
        x: Math.max(32, (current[id]?.x ?? defaults[id].x) + dx),
        y: Math.max(32, (current[id]?.y ?? defaults[id].y) + dy),
      },
    }));
  };
  const beginNodeDrag = (event: React.PointerEvent, node: GraphCanvasNode) => {
    if (event.button !== 0) return;
    const target = event.target as HTMLElement;
    const button = target.closest("button");
    if (button && !button.hasAttribute("data-node-drag-surface")) return;
    event.stopPropagation();
    (event.currentTarget as HTMLElement).setPointerCapture(event.pointerId);
    dragRef.current = {
      id: node.id,
      pointerId: event.pointerId,
      start: { x: event.clientX, y: event.clientY },
      origin: current[node.id],
    };
  };
  const updateNodeDrag = (event: React.PointerEvent) => {
    const drag = dragRef.current;
    if (!drag || drag.pointerId !== event.pointerId) return;
    setEditedKey(storageKey);
    setPositions((existing) => ({
      ...existing,
      [drag.id]: {
        x: Math.max(32, drag.origin.x + (event.clientX - drag.start.x) / zoom),
        y: Math.max(32, drag.origin.y + (event.clientY - drag.start.y) / zoom),
      },
    }));
  };
  const startPan = (event: React.PointerEvent) => {
    if (
      event.button !== 0 ||
      (event.target as HTMLElement).closest("button, [data-no-pan]")
    )
      return;
    (event.currentTarget as HTMLElement).setPointerCapture(event.pointerId);
    setPanDrag({
      start: { x: event.clientX, y: event.clientY },
      origin: pan,
      pointerId: event.pointerId,
    });
  };
  const updatePan = (event: React.PointerEvent) => {
    if (!panDrag || panDrag.pointerId !== event.pointerId) return;
    setPan({
      x: panDrag.origin.x + event.clientX - panDrag.start.x,
      y: panDrag.origin.y + event.clientY - panDrag.start.y,
    });
  };
  const zoomAt = (next: number, clientX?: number, clientY?: number) => {
    const value = Math.min(2.2, Math.max(0.38, next));
    if (clientX !== undefined && clientY !== undefined) {
      const rect = viewportRef.current?.getBoundingClientRect();
      if (rect) {
        const origin = { x: clientX - rect.left, y: clientY - rect.top };
        const ratio = value / zoom;
        setPan({
          x: origin.x - (origin.x - pan.x) * ratio,
          y: origin.y - (origin.y - pan.y) * ratio,
        });
      }
    }
    setZoom(value);
  };

  if (!nodes.length)
    return (
      <section
        className={`${styles.canvas} ${className ?? ""}`}
        aria-label="Workflow graph"
      >
        <div className={styles.empty}>
          <span className={styles.emptyMark} aria-hidden="true">
            ＋
          </span>
          <strong>Your workflow is ready to take shape</strong>
          <p>
            Add a source or operation to see how data will move through this
            workflow.
          </p>
        </div>
      </section>
    );

  const activeId = selectedNodeId ?? focusedId;
  const active = nodes.find((node) => node.id === activeId);
  const revealPorts = zoom >= 1.08;
  return (
    <section
      className={`${styles.canvas} ${className ?? ""}`}
      aria-label="Workflow graph"
    >
      <div className={styles.toolbar} aria-label="Graph controls">
        <span className={styles.graphCount}>
          {nodes.length} {nodes.length === 1 ? "node" : "nodes"}
          <span aria-hidden="true"> · </span>
          {edges.length} connections
        </span>
        <div className={styles.zoomControls}>
          <button
            type="button"
            aria-label="Zoom out"
            title="Zoom out"
            onClick={() => zoomAt(zoom - 0.14)}
          >
            −
          </button>
          <output aria-live="polite" aria-label="Zoom level">
            {Math.round(zoom * 100)}%
          </output>
          <button
            type="button"
            aria-label="Zoom in"
            title="Zoom in"
            onClick={() => zoomAt(zoom + 0.14)}
          >
            +
          </button>
          <span className={styles.controlDivider} />
          <button className={styles.fitButton} type="button" onClick={fit}>
            Fit graph
          </button>
          <button
            className={styles.resetButton}
            type="button"
            onClick={() => {
              setEditedKey(null);
              try {
                window.localStorage.removeItem(storageKey);
              } catch {
                /* Storage may be unavailable in private browsing. */
              }
              setPositions(defaults);
              setZoom(1);
              setPan({ x: 32, y: 32 });
            }}
          >
            Reset layout
          </button>
        </div>
      </div>
      <div
        ref={viewportRef}
        className={styles.viewport}
        onPointerDown={startPan}
        onPointerMove={updatePan}
        onPointerUp={() => setPanDrag(null)}
        onPointerCancel={() => setPanDrag(null)}
        onLostPointerCapture={() => setPanDrag(null)}
        onWheel={(event) => {
          event.preventDefault();
          zoomAt(
            zoom * Math.exp(-event.deltaY * 0.001),
            event.clientX,
            event.clientY,
          );
        }}
      >
        <div
          className={styles.world}
          style={{
            width: bounds.width,
            height: bounds.height,
            transform: `translate(${pan.x}px, ${pan.y}px) scale(${zoom})`,
          }}
        >
          <svg
            className={styles.edges}
            width={bounds.width}
            height={bounds.height}
            aria-hidden="true"
          >
            <defs>
              <marker
                id={`arrow-${workflowId.replace(/[^a-zA-Z0-9_-]/g, "-")}`}
                markerWidth="8"
                markerHeight="8"
                refX="7"
                refY="4"
                orient="auto"
              >
                <path d="M0 0 L8 4 L0 8 z" />
              </marker>
            </defs>
            {edges.map((edge, index) => {
              const from = current[edge.source];
              const to = current[edge.target];
              if (!from || !to) return null;
              const fromPorts =
                nodes.find((node) => node.id === edge.source)?.outputs ?? [];
              const toPorts =
                nodes.find((node) => node.id === edge.target)?.inputs ?? [];
              const outIndex = Math.max(0, fromPorts.indexOf(edge.sourcePort));
              const inIndex = Math.max(0, toPorts.indexOf(edge.targetPort));
              const y1 = from.y + 49 + outIndex * 19;
              const y2 = to.y + 49 + inIndex * 19;
              const x1 = from.x + NODE_WIDTH;
              const x2 = to.x;
              const curve = Math.max(40, Math.abs(x2 - x1) * 0.44);
              return (
                <path
                  key={
                    edge.id ??
                    `${edge.source}.${edge.sourcePort}.${edge.target}.${edge.targetPort}.${index}`
                  }
                  d={`M${x1} ${y1} C${x1 + curve} ${y1},${x2 - curve} ${y2},${x2} ${y2}`}
                  markerEnd={`url(#arrow-${workflowId.replace(/[^a-zA-Z0-9_-]/g, "-")})`}
                />
              );
            })}
          </svg>
          {nodes.map((node) => {
            const point = current[node.id];
            const selected = activeId === node.id;
            return (
              <article
                key={node.id}
                data-no-pan="true"
                className={`${styles.node} ${selected ? styles.nodeSelected : ""}`}
                style={{ left: point.x, top: point.y }}
                onPointerDown={(event) => beginNodeDrag(event, node)}
                onPointerMove={updateNodeDrag}
                onPointerUp={(event) => finishPointer(event)}
                onPointerCancel={(event) => finishPointer(event)}
                onLostPointerCapture={(event) => finishPointer(event)}
                onClick={() => {
                  setFocusedId(node.id);
                  onSelectNode?.(node.id);
                }}
              >
                {revealPorts && (node.inputs ?? []).length > 0 ? (
                  <div
                    className={`${styles.ports} ${styles.inputPorts}`}
                    aria-label="Inputs"
                  >
                    {node.inputs?.map((port) => (
                      <span
                        data-port="true"
                        className={styles.port}
                        key={port}
                        title={`Input · ${port}`}
                      >
                        <i aria-hidden="true" />
                        {port}
                      </span>
                    ))}
                  </div>
                ) : null}
                <button
                  className={styles.nodeBody}
                  type="button"
                  data-node-drag-surface="true"
                  aria-label={`Inspect ${node.title}`}
                  aria-pressed={selected}
                  onFocus={() => setFocusedId(node.id)}
                  onClick={(event) => {
                    event.stopPropagation();
                    setFocusedId(node.id);
                    onSelectNode?.(node.id);
                  }}
                >
                  <span className={styles.nodeMeta}>
                    <span className={styles.kind}>{node.kind}</span>
                    <span
                      className={styles.nodeStatus}
                      data-status={node.status?.toLowerCase()}
                    >
                      {node.status ?? "Ready"}
                    </span>
                  </span>
                  <strong>{node.title}</strong>
                  <span className={styles.nodeId}>{node.id}</span>
                </button>
                {revealPorts && (node.outputs ?? []).length > 0 ? (
                  <div
                    className={`${styles.ports} ${styles.outputPorts}`}
                    aria-label="Outputs"
                  >
                    {node.outputs?.map((port) => (
                      <span
                        data-port="true"
                        className={styles.port}
                        key={port}
                        title={`Output · ${port}`}
                      >
                        {port}
                        <i aria-hidden="true" />
                      </span>
                    ))}
                  </div>
                ) : null}
                <div
                  className={styles.moveTools}
                  aria-label={`Move ${node.title}`}
                >
                  <button
                    type="button"
                    title="Move left"
                    aria-label={`Move ${node.title} left`}
                    onClick={(event) => {
                      event.stopPropagation();
                      moveNode(node.id, -28, 0);
                    }}
                  >
                    ←
                  </button>
                  <button
                    type="button"
                    title="Move up"
                    aria-label={`Move ${node.title} up`}
                    onClick={(event) => {
                      event.stopPropagation();
                      moveNode(node.id, 0, -28);
                    }}
                  >
                    ↑
                  </button>
                  <button
                    type="button"
                    title="Move down"
                    aria-label={`Move ${node.title} down`}
                    onClick={(event) => {
                      event.stopPropagation();
                      moveNode(node.id, 0, 28);
                    }}
                  >
                    ↓
                  </button>
                  <button
                    type="button"
                    title="Move right"
                    aria-label={`Move ${node.title} right`}
                    onClick={(event) => {
                      event.stopPropagation();
                      moveNode(node.id, 28, 0);
                    }}
                  >
                    →
                  </button>
                </div>
              </article>
            );
          })}
        </div>
        {!revealPorts ? (
          <p className={styles.zoomHint}>
            Zoom in to inspect named inputs and outputs
          </p>
        ) : null}
        {active && active.outputPreview !== undefined ? (
          <aside
            data-no-pan="true"
            className={styles.preview}
            aria-label={`${active.title} output preview`}
          >
            <div className={styles.previewHeader}>
              <div>
                <span>Step output</span>
                <strong>{active.title}</strong>
              </div>
              <button
                type="button"
                aria-label="Close output preview"
                onClick={() => {
                  setFocusedId(null);
                  onSelectNode?.(null);
                }}
              >
                ×
              </button>
            </div>
            <pre>{pretty(active.outputPreview)}</pre>
          </aside>
        ) : null}
      </div>
      <div className={styles.canvasFooter}>
        <span>Drag steps to arrange the graph</span>
        <span>Use arrow controls to move a focused step</span>
        <span>Scroll to zoom · drag empty space to pan</span>
      </div>
    </section>
  );
}

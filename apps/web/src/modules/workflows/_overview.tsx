"use client";

import { useEffect, useMemo, useState } from "react";

import { WorkflowDefinitionEditor } from "./_editor";
import styles from "./workflow-overview.module.css";

type WorkflowNode = {
  id: string;
  kind: string;
  refId: string;
  version: number | string;
  shape?: string;
  toolName?: string | null;
};

type WorkflowEdge = {
  sourceNode: string;
  sourcePort: string;
  targetNode: string;
  targetPort: string;
};

type WorkflowGraph = {
  nodes: WorkflowNode[];
  edges: WorkflowEdge[];
  outputs: { name: string; node: string; port: string }[];
};

export type WorkflowDefinition = {
  id: string;
  name: string;
  version: number;
  graph: WorkflowGraph;
};

type WorkflowRun = {
  id: string;
  workflowId: string;
  definitionVersion: number;
  status: string;
  snapshot: Record<string, unknown>;
  execution: Record<string, unknown>;
  createdAt: string;
};

type LoadResult = {
  error: string | null;
  projectId: string;
  runsByWorkflow: Record<string, WorkflowRun[]>;
  workflows: WorkflowDefinition[] | null;
};

type NodeProgress = {
  inputs?: unknown;
  output?: unknown;
  items?: unknown;
  error?: unknown;
  status?: string;
};

type SourceSnapshot = Record<string, unknown>;

const emptyResult: LoadResult = {
  error: null,
  projectId: "",
  runsByWorkflow: {},
  workflows: null,
};

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

function graphFrom(value: unknown): WorkflowGraph | null {
  if (!isRecord(value)) return null;
  const nodes = Array.isArray(value.nodes) ? value.nodes : [];
  const edges = Array.isArray(value.edges) ? value.edges : [];
  const outputs = Array.isArray(value.outputs) ? value.outputs : [];
  const validNodes = nodes.every((node) => {
    if (!isRecord(node)) return false;
    return (
      typeof node.id === "string" &&
      typeof node.kind === "string" &&
      typeof (node.refId ?? node.ref_id) === "string"
    );
  });
  const validEdges = edges.every((edge) => {
    if (!isRecord(edge)) return false;
    return (
      typeof (edge.sourceNode ?? edge.source_node) === "string" &&
      typeof (edge.sourcePort ?? edge.source_port) === "string" &&
      typeof (edge.targetNode ?? edge.target_node) === "string" &&
      typeof (edge.targetPort ?? edge.target_port) === "string"
    );
  });
  const validOutputs = outputs.every(
    (output) =>
      isRecord(output) &&
      typeof output.name === "string" &&
      typeof output.node === "string" &&
      typeof output.port === "string",
  );
  if (!validNodes || !validEdges || !validOutputs) {
    return null;
  }
  return {
    nodes: nodes.map((node) => {
      const item = node as Record<string, unknown>;
      return {
        id: item.id as string,
        kind: item.kind as string,
        refId: (item.refId ?? item.ref_id) as string,
        version: item.version as number | string,
        shape: typeof item.shape === "string" ? item.shape : "single",
        toolName:
          typeof (item.toolName ?? item.tool_name) === "string"
            ? ((item.toolName ?? item.tool_name) as string)
            : null,
      };
    }),
    edges: edges.map((edge) => {
      const item = edge as Record<string, unknown>;
      return {
        sourceNode: (item.sourceNode ?? item.source_node) as string,
        sourcePort: (item.sourcePort ?? item.source_port) as string,
        targetNode: (item.targetNode ?? item.target_node) as string,
        targetPort: (item.targetPort ?? item.target_port) as string,
      };
    }),
    outputs: outputs.map((output) => {
      const item = output as Record<string, unknown>;
      return {
        name: item.name as string,
        node: item.node as string,
        port: item.port as string,
      };
    }),
  };
}

function nodeLabel(node: WorkflowNode) {
  if (node.kind === "mcp") return node.toolName ?? node.refId;
  return node.id;
}

function nodeKindLabel(node: WorkflowNode) {
  if (node.kind === "dataset") return "Dataset";
  if (node.kind === "file") return "Project File";
  if (node.kind === "mcp") return "MCP tool";
  return "Function";
}

function graphLayers(graph: WorkflowGraph): WorkflowNode[][] {
  const nodes = new Map(graph.nodes.map((node) => [node.id, node]));
  const layerByNode = new Map<string, number>();
  for (let pass = 0; pass < graph.nodes.length; pass += 1) {
    let changed = false;
    for (const node of graph.nodes) {
      const incoming = graph.edges.filter(
        (edge) => edge.targetNode === node.id,
      );
      if (incoming.some((edge) => !layerByNode.has(edge.sourceNode))) continue;
      const layer = incoming.length
        ? Math.max(
            ...incoming.map((edge) => layerByNode.get(edge.sourceNode) ?? 0),
          ) + 1
        : 0;
      if (layerByNode.get(node.id) !== layer) {
        layerByNode.set(node.id, layer);
        changed = true;
      }
    }
    if (!changed) break;
  }
  const layers: WorkflowNode[][] = [];
  for (const node of graph.nodes) {
    const layer = layerByNode.get(node.id) ?? 0;
    (layers[layer] ??= []).push(nodes.get(node.id)!);
  }
  return layers;
}

function jsonText(value: unknown) {
  return JSON.stringify(value, null, 2) ?? "No captured value";
}

function runLabel(run: WorkflowRun, index: number) {
  const date = new Date(run.createdAt);
  const timestamp = Number.isNaN(date.valueOf())
    ? ""
    : ` · ${date.toLocaleDateString()}`;
  return `Run ${index + 1} · ${run.status}${timestamp}`;
}

export function WorkflowOverview({
  onOpenChats,
  projectId,
}: {
  onOpenChats: () => void;
  projectId: string;
}) {
  const [result, setResult] = useState<LoadResult>(emptyResult);
  const [selectedWorkflowId, setSelectedWorkflowId] = useState<string | null>(
    null,
  );
  const [selectedRunId, setSelectedRunId] = useState<string | null>(null);
  const [selectedNodeId, setSelectedNodeId] = useState<string | null>(null);
  const [editingDefinitionId, setEditingDefinitionId] = useState<string | null>(
    null,
  );
  const [isRunning, setIsRunning] = useState(false);
  const [actionError, setActionError] = useState<string | null>(null);

  useEffect(() => {
    let active = true;
    async function load() {
      try {
        const response = await fetch(
          `/api/projects/${encodeURIComponent(projectId)}/workflows`,
          { cache: "no-store" },
        );
        if (!response.ok) throw new Error("Workflow catalog unavailable");
        const workflows = (await response.json()) as WorkflowDefinition[];
        const runResponses = await Promise.all(
          workflows.map(async (workflow) => {
            const runsResponse = await fetch(
              `/api/projects/${encodeURIComponent(projectId)}/workflows/${encodeURIComponent(workflow.id)}/runs`,
              { cache: "no-store" },
            );
            if (!runsResponse.ok) throw new Error("Workflow Runs unavailable");
            return [
              workflow.id,
              (await runsResponse.json()) as WorkflowRun[],
            ] as const;
          }),
        );
        if (!active) return;
        setResult({
          error: null,
          projectId,
          runsByWorkflow: Object.fromEntries(runResponses),
          workflows,
        });
        setSelectedWorkflowId((current) =>
          workflows.some((workflow) => workflow.id === current)
            ? current
            : (workflows[0]?.id ?? null),
        );
        setSelectedRunId(null);
        setSelectedNodeId(null);
      } catch {
        if (active) {
          setResult({
            error: "Workflows are temporarily unavailable.",
            projectId,
            runsByWorkflow: {},
            workflows: null,
          });
        }
      }
    }
    void load();
    return () => {
      active = false;
    };
  }, [projectId]);

  const workflows = result.projectId === projectId ? result.workflows : null;
  const workflow = workflows?.find((item) => item.id === selectedWorkflowId);
  const runs = workflow ? (result.runsByWorkflow[workflow.id] ?? []) : [];
  const selectedRun = runs.find((run) => run.id === selectedRunId) ?? runs[0];
  const runExecution = isRecord(selectedRun?.execution)
    ? selectedRun.execution
    : {};
  const progressByNode = isRecord(runExecution.nodes)
    ? (runExecution.nodes as Record<string, NodeProgress>)
    : {};
  const graph = useMemo(() => {
    if (selectedRun) {
      const snapshotGraph = graphFrom(selectedRun.snapshot.graph);
      if (snapshotGraph) return snapshotGraph;
    }
    return workflow ? graphFrom(workflow.graph) : null;
  }, [selectedRun, workflow]);
  const layers = graph ? graphLayers(graph) : [];
  const graphNodes = new Map(
    (graph?.nodes ?? []).map((node) => [node.id, node]),
  );
  const maximumLayerSize = Math.max(1, ...layers.map((layer) => layer.length));
  const graphHeight = maximumLayerSize * 120;
  const graphWidth = Math.max(196, layers.length * 242 - 46);
  const graphPosition = new Map<
    string,
    { column: number; row: number; x: number; y: number }
  >();
  layers.forEach((layer, column) => {
    const offset = Math.floor((maximumLayerSize - layer.length) / 2);
    layer.forEach((node, index) => {
      const row = offset + index;
      graphPosition.set(node.id, {
        column,
        row,
        x: column * 242,
        y: row * 120 + 60,
      });
    });
  });
  const selectedNode = graph?.nodes.find((node) => node.id === selectedNodeId);
  const selectedNodeProgress = selectedNode
    ? progressByNode[selectedNode.id]
    : undefined;
  const snapshotSources = isRecord(selectedRun?.snapshot.sources)
    ? (selectedRun.snapshot.sources as Record<string, SourceSnapshot>)
    : {};
  const snapshotTargets = isRecord(selectedRun?.snapshot.targets)
    ? (selectedRun.snapshot.targets as Record<string, SourceSnapshot>)
    : {};
  const finalOutputs = isRecord(runExecution.outputs)
    ? runExecution.outputs
    : {};

  async function runWorkflow() {
    if (!workflow) return;
    setIsRunning(true);
    setActionError(null);
    try {
      const base = `/api/projects/${encodeURIComponent(projectId)}/workflows/${encodeURIComponent(workflow.id)}`;
      const preparedResponse = await fetch(`${base}/runs/prepare`, {
        method: "POST",
        headers: { "content-type": "application/json" },
        body: JSON.stringify({
          idempotencyKey: crypto.randomUUID(),
          expectedVersion: workflow.version,
        }),
      });
      if (!preparedResponse.ok)
        throw new Error("Workflow could not be prepared.");
      const prepared = (await preparedResponse.json()) as WorkflowRun;
      const response = await fetch(
        `${base}/runs/${encodeURIComponent(prepared.id)}/execute`,
        {
          method: "POST",
        },
      );
      if (!response.ok) throw new Error("Workflow Run failed to start.");
      const completed = (await response.json()) as WorkflowRun;
      setResult((current) => ({
        ...current,
        runsByWorkflow: {
          ...current.runsByWorkflow,
          [workflow.id]: [
            completed,
            ...(current.runsByWorkflow[workflow.id] ?? []).filter(
              (run) => run.id !== completed.id,
            ),
          ],
        },
      }));
      setSelectedRunId(completed.id);
    } catch (error) {
      setActionError(
        error instanceof Error
          ? error.message
          : "Workflow Run failed to start.",
      );
    } finally {
      setIsRunning(false);
    }
  }

  function acceptRevisedDefinition(revised: WorkflowDefinition) {
    setResult((current) =>
      current.projectId !== projectId || current.workflows === null
        ? current
        : {
            ...current,
            workflows: current.workflows.map((item) =>
              item.id === revised.id ? revised : item,
            ),
          },
    );
    setEditingDefinitionId(null);
    setSelectedNodeId(null);
  }

  if (workflows === null) {
    return (
      <section aria-label="Workflow overview" className={styles.overview}>
        <h1>Workflow</h1>
        {result.projectId === projectId && result.error ? (
          <p className={styles.error} role="alert">
            {result.error}
          </p>
        ) : (
          <p role="status">Loading Project Workflows…</p>
        )}
      </section>
    );
  }

  if (workflows.length === 0) {
    return (
      <section aria-label="Workflow overview" className={styles.empty}>
        <h1>No Workflow yet</h1>
        <p>
          A Workflow connects Project inputs and reusable calls into one
          inspectable task. Create one in Chat, then return here to review its
          outputs and history.
        </p>
        <button onClick={onOpenChats} type="button">
          Open Chat
        </button>
      </section>
    );
  }

  if (!workflow || !graph) {
    return (
      <section aria-label="Workflow overview" className={styles.overview}>
        <h1>Workflow unavailable</h1>
        <p className={styles.error} role="alert">
          This Workflow graph could not be read. Reload the Project to try
          again.
        </p>
      </section>
    );
  }

  return (
    <section aria-label="Workflow overview" className={styles.overview}>
      <header className={styles.header}>
        <div>
          {workflows.length > 1 ? (
            <label className={styles.workflowPicker}>
              <span>Workflow</span>
              <select
                onChange={(event) => {
                  setSelectedWorkflowId(event.target.value);
                  setSelectedRunId(null);
                  setSelectedNodeId(null);
                }}
                value={workflow.id}
              >
                {workflows.map((item) => (
                  <option key={item.id} value={item.id}>
                    {item.name}
                  </option>
                ))}
              </select>
            </label>
          ) : null}
          <h1>{workflow.name}</h1>
          <p>
            {graph.nodes.length} graph nodes · Definition v{workflow.version}
            {selectedRun ? ` · Run v${selectedRun.definitionVersion}` : ""}
          </p>
        </div>
        <div className={styles.headerActions}>
          <button
            className={styles.secondaryButton}
            onClick={() => setEditingDefinitionId(workflow.id)}
            type="button"
          >
            Edit Workflow
          </button>
          {runs.length > 0 ? (
            <label className={styles.runPicker}>
              <span>Run history</span>
              <select
                aria-label="Workflow run history"
                onChange={(event) => setSelectedRunId(event.target.value)}
                value={selectedRun?.id ?? ""}
              >
                {runs.map((run, index) => (
                  <option key={run.id} value={run.id}>
                    {runLabel(run, runs.length - index - 1)}
                  </option>
                ))}
              </select>
            </label>
          ) : null}
          <button
            className={styles.runButton}
            disabled={isRunning}
            onClick={() => void runWorkflow()}
            type="button"
          >
            {isRunning ? "Starting…" : "Run Workflow"}
          </button>
        </div>
      </header>

      {actionError ? (
        <p className={styles.error} role="alert">
          {actionError}
        </p>
      ) : null}

      {editingDefinitionId === workflow.id ? (
        <WorkflowDefinitionEditor
          definition={workflow}
          onCancel={() => setEditingDefinitionId(null)}
          onSaved={acceptRevisedDefinition}
          projectId={projectId}
        />
      ) : null}

      <section aria-label="Workflow outputs" className={styles.outputs}>
        <div className={styles.sectionHeading}>
          <h2>Final outputs</h2>
          <span>
            {selectedRun ? `Run ${selectedRun.id.slice(0, 8)}` : "No Run yet"}
          </span>
        </div>
        {selectedRun ? (
          <div className={styles.outputList}>
            {graph.outputs.map((output) => (
              <article className={styles.output} key={output.name}>
                <div>
                  <h3>{output.name}</h3>
                  <p>
                    From {graphNodes.get(output.node)?.id ?? output.node} ·{" "}
                    {output.port}
                  </p>
                </div>
                <pre>{jsonText(finalOutputs[output.name])}</pre>
              </article>
            ))}
          </div>
        ) : (
          <p>
            No completed Run yet. Start the Workflow to capture its outputs.
          </p>
        )}
      </section>

      <section aria-label="Workflow graph" className={styles.graphSection}>
        <div className={styles.sectionHeading}>
          <h2>Dependencies</h2>
          {selectedRun ? <span>{selectedRun.status}</span> : null}
        </div>
        <div
          className={styles.graphCanvas}
          style={{ height: graphHeight, width: graphWidth }}
        >
          <svg
            aria-hidden="true"
            className={styles.graphEdges}
            height={graphHeight}
            viewBox={`0 0 ${graphWidth} ${graphHeight}`}
            width={graphWidth}
          >
            <defs>
              <marker
                id="workflow-edge-arrow"
                markerHeight="8"
                markerWidth="8"
                orient="auto"
                refX="7"
                refY="4"
              >
                <path d="M 0 0 L 8 4 L 0 8 z" fill="currentColor" />
              </marker>
            </defs>
            {graph.edges.map((edge) => {
              const source = graphPosition.get(edge.sourceNode);
              const target = graphPosition.get(edge.targetNode);
              if (!source || !target) return null;
              const startX = source.x + 196;
              const endX = target.x;
              const curve = Math.max(12, (endX - startX) / 2);
              return (
                <path
                  d={`M ${startX} ${source.y} C ${startX + curve} ${source.y}, ${endX - curve} ${target.y}, ${endX} ${target.y}`}
                  key={`${edge.sourceNode}:${edge.sourcePort}:${edge.targetNode}:${edge.targetPort}`}
                  markerEnd="url(#workflow-edge-arrow)"
                />
              );
            })}
          </svg>
          {layers.flatMap((layer) =>
            layer.map((node) => {
              const progress = progressByNode[node.id];
              const position = graphPosition.get(node.id);
              return (
                <button
                  aria-label={`Inspect ${node.id}`}
                  aria-pressed={selectedNodeId === node.id}
                  className={styles.graphNode}
                  key={node.id}
                  style={{
                    gridColumn: (position?.column ?? 0) + 1,
                    gridRow: (position?.row ?? 0) + 1,
                  }}
                  onClick={() =>
                    setSelectedNodeId((current) =>
                      current === node.id ? null : node.id,
                    )
                  }
                  type="button"
                >
                  <span className={styles.nodeType}>
                    {node.shape === "map" ? "Map" : nodeKindLabel(node)}
                  </span>
                  <strong>{nodeLabel(node)}</strong>
                  <span className={styles.nodeStatus}>
                    {progress?.status ??
                      (node.kind === "dataset" || node.kind === "file"
                        ? "Captured input"
                        : "Not run")}
                  </span>
                </button>
              );
            }),
          )}
        </div>
        {graph.edges.length > 0 ? (
          <ul aria-label="Workflow dependencies" className={styles.edgeList}>
            {graph.edges.map((edge) => (
              <li
                key={`${edge.sourceNode}:${edge.sourcePort}:${edge.targetNode}:${edge.targetPort}`}
              >
                <span>
                  {graphNodes.get(edge.sourceNode)?.id ?? edge.sourceNode}
                </span>
                <code>{edge.sourcePort}</code>
                <span aria-hidden="true" className={styles.edgeArrow} />
                <span>
                  {graphNodes.get(edge.targetNode)?.id ?? edge.targetNode}
                </span>
                <code>{edge.targetPort}</code>
              </li>
            ))}
          </ul>
        ) : null}
      </section>

      {selectedNode ? (
        <section aria-label="Node lineage" className={styles.lineage}>
          <div className={styles.sectionHeading}>
            <h2>{selectedNode.id}</h2>
            <button onClick={() => setSelectedNodeId(null)} type="button">
              Close details
            </button>
          </div>
          <p>
            {nodeKindLabel(selectedNode)} · {selectedNode.refId} · v
            {selectedNode.version}
          </p>
          <div className={styles.lineageSources}>
            <div>
              <h3>Inputs</h3>
              <pre>
                {jsonText(
                  selectedNodeProgress?.inputs ??
                    snapshotSources[selectedNode.id] ??
                    {},
                )}
              </pre>
            </div>
            <div>
              <h3>Captured target</h3>
              <pre>
                {jsonText(snapshotTargets[selectedNode.id] ?? selectedNode)}
              </pre>
            </div>
            <div>
              <h3>Output</h3>
              <pre>
                {jsonText(
                  selectedNodeProgress?.output ?? selectedNodeProgress?.items,
                )}
              </pre>
            </div>
          </div>
        </section>
      ) : null}
    </section>
  );
}

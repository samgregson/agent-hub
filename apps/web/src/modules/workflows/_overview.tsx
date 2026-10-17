"use client";

import { useEffect, useMemo, useState } from "react";

import { WorkflowDefinitionEditor } from "./_editor";
import { WorkflowMapResults } from "./_map-results";
import {
  DatasetRecordsTable,
  type DatasetTableRecord,
} from "@/modules/datasets";
import {
  ImageOutputPreview,
  imageDataUrl,
  isImageOutput,
  type ImageOutput,
} from "@/modules/media";
import styles from "./workflow-overview.module.css";

type WorkflowNode = {
  id: string;
  kind: string;
  refId: string;
  version: number | string;
  shape?: string;
  toolName?: string | null;
  mapInput?: string | null;
};

type WorkflowEdge = {
  sourceNode: string | null;
  sourcePort: string | null;
  targetNode: string;
  targetPort: string;
  sourceKind?: "node" | "workflowInput" | "literal";
  sourceInput?: string | null;
  sourcePath?: string;
  targetPath?: string;
  literal?: unknown;
};

type WorkflowInput = {
  name: string;
  schema: Record<string, unknown>;
  required: boolean;
};

type WorkflowGraph = {
  nodes: WorkflowNode[];
  edges: WorkflowEdge[];
  outputs: { name: string; node: string; port: string }[];
  inputs: WorkflowInput[];
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
  const inputs = Array.isArray(value.inputs) ? value.inputs : [];
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
      ((edge.sourceNode ?? edge.source_node) == null ||
        typeof (edge.sourceNode ?? edge.source_node) === "string") &&
      ((edge.sourcePort ?? edge.source_port) == null ||
        typeof (edge.sourcePort ?? edge.source_port) === "string") &&
      typeof (edge.targetNode ?? edge.target_node) === "string" &&
      typeof (edge.targetPort ?? edge.target_port) === "string"
    );
  });
  const validInputs = inputs.every(
    (input) =>
      isRecord(input) &&
      typeof input.name === "string" &&
      isRecord(input.schema) &&
      (input.required === undefined || typeof input.required === "boolean"),
  );
  const validOutputs = outputs.every(
    (output) =>
      isRecord(output) &&
      typeof output.name === "string" &&
      typeof output.node === "string" &&
      typeof output.port === "string",
  );
  if (!validNodes || !validEdges || !validOutputs || !validInputs) {
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
        mapInput:
          typeof (item.mapInput ?? item.map_input) === "string"
            ? ((item.mapInput ?? item.map_input) as string)
            : null,
      };
    }),
    edges: edges.map((edge) => {
      const item = edge as Record<string, unknown>;
      return {
        sourceNode:
          typeof (item.sourceNode ?? item.source_node) === "string"
            ? ((item.sourceNode ?? item.source_node) as string)
            : null,
        sourcePort:
          typeof (item.sourcePort ?? item.source_port) === "string"
            ? ((item.sourcePort ?? item.source_port) as string)
            : null,
        targetNode: (item.targetNode ?? item.target_node) as string,
        targetPort: (item.targetPort ?? item.target_port) as string,
        sourceKind:
          (item.sourceKind ?? item.source_kind) === "workflowInput" ||
          (item.sourceKind ?? item.source_kind) === "literal"
            ? ((item.sourceKind ?? item.source_kind) as
                "workflowInput" | "literal")
            : "node",
        sourceInput:
          typeof (item.sourceInput ?? item.source_input) === "string"
            ? ((item.sourceInput ?? item.source_input) as string)
            : null,
        sourcePath:
          typeof (item.sourcePath ?? item.source_path) === "string"
            ? ((item.sourcePath ?? item.source_path) as string)
            : "",
        targetPath:
          typeof (item.targetPath ?? item.target_path) === "string"
            ? ((item.targetPath ?? item.target_path) as string)
            : "",
        literal: item.literal,
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
    inputs: inputs.map((input) => {
      const item = input as Record<string, unknown>;
      return {
        name: item.name as string,
        schema: item.schema as Record<string, unknown>,
        required: typeof item.required === "boolean" ? item.required : true,
      };
    }),
  };
}

function workflowFrom(value: unknown): WorkflowDefinition | null {
  if (
    !isRecord(value) ||
    typeof value.id !== "string" ||
    typeof value.name !== "string" ||
    typeof value.version !== "number"
  ) {
    return null;
  }
  const graph = graphFrom(value.graph);
  return graph
    ? { id: value.id, name: value.name, version: value.version, graph }
    : null;
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
        (edge) =>
          edge.targetNode === node.id &&
          edge.sourceKind === "node" &&
          edge.sourceNode !== null,
      );
      if (incoming.some((edge) => !layerByNode.has(edge.sourceNode ?? "")))
        continue;
      const layer = incoming.length
        ? Math.max(
            ...incoming.map(
              (edge) => layerByNode.get(edge.sourceNode ?? "") ?? 0,
            ),
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

function datasetRows(value: unknown): DatasetTableRecord[] | null {
  const isDatasetEnvelope =
    !Array.isArray(value) && isRecord(value) && Array.isArray(value.records);
  const rawRows: unknown[] | null = Array.isArray(value)
    ? value
    : isRecord(value) && Array.isArray(value.records)
      ? value.records
      : null;
  if (rawRows === null) return null;
  if (rawRows.length > 0 && !rawRows.every(isRecord)) return null;
  return rawRows.flatMap((raw, index) => {
    if (!isRecord(raw)) return [];
    const wrappedValue =
      isDatasetEnvelope && isRecord(raw.value) ? raw.value : raw;
    const position = typeof raw.position === "number" ? raw.position : index;
    return [
      {
        id:
          typeof raw.id === "string" || typeof raw.id === "number"
            ? String(raw.id)
            : `record-${index + 1}`,
        position,
        sourceKey: typeof raw.sourceKey === "string" ? raw.sourceKey : null,
        value: wrappedValue,
      },
    ];
  });
}

function runLabel(run: WorkflowRun, index: number) {
  const date = new Date(run.createdAt);
  const timestamp = Number.isNaN(date.valueOf())
    ? ""
    : ` · ${date.toLocaleDateString()}`;
  return `Run ${index + 1} · ${run.status}${timestamp}`;
}

export function WorkflowOverview({
  onOpenLibrary,
  onOpenFunction,
  onOpenChats,
  projectId,
}: {
  onOpenLibrary: () => void;
  onOpenFunction: (node: WorkflowNode) => void;
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
  const [savedImages, setSavedImages] = useState<Record<string, boolean>>({});
  const [workflowInputText, setWorkflowInputText] = useState<
    Record<string, string>
  >({});

  useEffect(() => {
    let active = true;
    async function load() {
      try {
        const response = await fetch(
          `/api/projects/${encodeURIComponent(projectId)}/workflows`,
          { cache: "no-store" },
        );
        if (!response.ok) throw new Error("Workflow catalog unavailable");
        const workflowPayload: unknown = await response.json();
        const workflows = Array.isArray(workflowPayload)
          ? workflowPayload.map(workflowFrom)
          : null;
        if (!workflows || workflows.some((workflow) => workflow === null)) {
          throw new Error("Workflow catalog has an invalid response.");
        }
        const definitions = workflows as WorkflowDefinition[];
        const runResponses = await Promise.all(
          definitions.map(async (workflow) => {
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
          workflows: definitions,
        });
        setSelectedWorkflowId((current) =>
          definitions.some((workflow) => workflow.id === current)
            ? current
            : (definitions[0]?.id ?? null),
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
  const selectedNodeOutput = selectedNodeProgress?.output;
  const selectedNodeImage: ImageOutput | null = isImageOutput(
    selectedNodeOutput,
  )
    ? selectedNodeOutput
    : null;
  const snapshotSources = isRecord(selectedRun?.snapshot.sources)
    ? (selectedRun.snapshot.sources as Record<string, SourceSnapshot>)
    : {};
  const snapshotTargets = isRecord(selectedRun?.snapshot.targets)
    ? (selectedRun.snapshot.targets as Record<string, SourceSnapshot>)
    : {};
  const finalOutputs = isRecord(runExecution.outputs)
    ? runExecution.outputs
    : {};
  const selectedDatasetInputRows =
    selectedNode?.kind === "dataset"
      ? datasetRows(snapshotSources[selectedNode.id])
      : null;

  function workflowInputKey(name: string) {
    return `${workflow?.id ?? ""}:${workflow?.version ?? 0}:${name}`;
  }

  async function runWorkflow() {
    if (!workflow) return;
    setIsRunning(true);
    setActionError(null);
    try {
      const workflowInputs: Record<string, unknown> = {};
      for (const input of workflow.graph.inputs ?? []) {
        const raw = workflowInputText[workflowInputKey(input.name)] ?? "";
        if (raw.trim() === "" && !input.required) continue;
        if (input.schema.type === "string") {
          workflowInputs[input.name] = raw;
        } else {
          try {
            workflowInputs[input.name] = JSON.parse(raw);
          } catch {
            throw new Error(`Workflow Input ${input.name} must be valid JSON.`);
          }
        }
      }
      const base = `/api/projects/${encodeURIComponent(projectId)}/workflows/${encodeURIComponent(workflow.id)}`;
      const preparedResponse = await fetch(`${base}/runs/prepare`, {
        method: "POST",
        headers: { "content-type": "application/json" },
        body: JSON.stringify({
          idempotencyKey: crypto.randomUUID(),
          expectedVersion: workflow.version,
          workflowInputs,
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

  async function saveImageToLibrary(outputName: string) {
    if (!workflow || !selectedRun) return;
    setActionError(null);
    const key = `${selectedRun.id}:${outputName}`;
    try {
      const response = await fetch(
        `/api/projects/${encodeURIComponent(projectId)}/workflows/${encodeURIComponent(workflow.id)}/runs/${encodeURIComponent(selectedRun.id)}/outputs/${encodeURIComponent(outputName)}/artifact`,
        { method: "POST" },
      );
      if (!response.ok)
        throw new Error("Could not save this image to Library.");
      setSavedImages((current) => ({ ...current, [key]: true }));
    } catch (error) {
      setActionError(
        error instanceof Error
          ? error.message
          : "Could not save this image to Library.",
      );
    }
  }

  function acceptRevisedDefinition(revised: WorkflowDefinition) {
    setResult((current) =>
      current.projectId !== projectId || current.workflows === null
        ? current
        : {
            ...current,
            workflows: current.workflows.some((item) => item.id === revised.id)
              ? current.workflows.map((item) =>
                  item.id === revised.id ? revised : item,
                )
              : [...current.workflows, revised],
          },
    );
    setSelectedWorkflowId(revised.id);
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
    if (editingDefinitionId === "new") {
      return (
        <section aria-label="Workflow overview" className={styles.overview}>
          <WorkflowDefinitionEditor
            definition={{
              id: "",
              name: "New Workflow",
              version: 0,
              graph: { nodes: [], edges: [], outputs: [], inputs: [] },
            }}
            onCancel={() => setEditingDefinitionId(null)}
            onSaved={acceptRevisedDefinition}
            projectId={projectId}
          />
        </section>
      );
    }
    return (
      <section aria-label="Workflow overview" className={styles.empty}>
        <h1>No Workflow yet</h1>
        <p>
          A Workflow connects Project inputs and reusable calls into one
          inspectable task. Add Project inputs and reusable calls, then wire
          their named outputs into a reviewable graph.
        </p>
        <div className={styles.emptyActions}>
          <button onClick={() => setEditingDefinitionId("new")} type="button">
            Create Workflow
          </button>
          <button onClick={onOpenChats} type="button">
            Create with Chat
          </button>
        </div>
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

      {graph.inputs.length > 0 ? (
        <section aria-label="Workflow Inputs" className={styles.outputs}>
          <div className={styles.sectionHeading}>
            <h2>Inputs for the next Run</h2>
            <span>Captured with the Run</span>
          </div>
          <div className={styles.outputList}>
            {workflow.graph.inputs.map((input) => (
              <label className={styles.output} key={input.name}>
                <span>
                  <strong>{input.name}</strong>
                  <small>
                    {input.required ? "Required" : "Optional"} ·{" "}
                    {String(input.schema.type ?? "JSON value")}
                  </small>
                </span>
                {input.schema.type === "string" ? (
                  <input
                    aria-label={`Workflow Input ${input.name}`}
                    onChange={(event) =>
                      setWorkflowInputText((current) => ({
                        ...current,
                        [workflowInputKey(input.name)]: event.target.value,
                      }))
                    }
                    value={
                      workflowInputText[workflowInputKey(input.name)] ?? ""
                    }
                  />
                ) : (
                  <textarea
                    aria-label={`Workflow Input ${input.name}`}
                    onChange={(event) =>
                      setWorkflowInputText((current) => ({
                        ...current,
                        [workflowInputKey(input.name)]: event.target.value,
                      }))
                    }
                    rows={3}
                    value={
                      workflowInputText[workflowInputKey(input.name)] ?? ""
                    }
                  />
                )}
              </label>
            ))}
          </div>
        </section>
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
            {graph.outputs.map((output) => {
              const outputNode = graphNodes.get(output.node);
              const rows = datasetRows(finalOutputs[output.name]);
              const outputValue = finalOutputs[output.name];
              const image: ImageOutput | null = isImageOutput(outputValue)
                ? outputValue
                : null;
              const imageKey = `${selectedRun.id}:${output.name}`;
              const imageUrl = `/api/projects/${encodeURIComponent(projectId)}/workflows/${encodeURIComponent(workflow?.id ?? "")}/runs/${encodeURIComponent(selectedRun.id)}/outputs/${encodeURIComponent(output.name)}/image`;
              return (
                <article className={styles.output} key={output.name}>
                  <div>
                    <h3>{output.name}</h3>
                    <p>
                      From {outputNode?.id ?? output.node} · {output.port}
                    </p>
                  </div>
                  {outputNode?.shape === "map" ? (
                    <WorkflowMapResults
                      items={progressByNode[output.node]?.items}
                      node={outputNode}
                      projectId={projectId}
                      target={snapshotTargets[output.node] ?? {}}
                    />
                  ) : image ? (
                    <>
                      <ImageOutputPreview
                        altText={image.altText}
                        src={imageUrl}
                        title={output.name}
                      />
                      <button
                        className={styles.secondaryButton}
                        disabled={savedImages[imageKey]}
                        onClick={() => void saveImageToLibrary(output.name)}
                        type="button"
                      >
                        {savedImages[imageKey]
                          ? "Saved to Library"
                          : "Save to Library"}
                      </button>
                    </>
                  ) : rows ? (
                    <DatasetRecordsTable
                      ariaLabel={`${output.name} workflow output`}
                      records={rows}
                    />
                  ) : (
                    <pre>{jsonText(finalOutputs[output.name])}</pre>
                  )}
                </article>
              );
            })}
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
              const source =
                edge.sourceKind === "node" && edge.sourceNode
                  ? graphPosition.get(edge.sourceNode)
                  : undefined;
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
                  {edge.sourceKind === "workflowInput"
                    ? `Workflow Input · ${edge.sourceInput ?? "missing"}`
                    : edge.sourceKind === "literal"
                      ? `Literal · ${jsonText(edge.literal)}`
                      : (graphNodes.get(edge.sourceNode ?? "")?.id ??
                        edge.sourceNode)}
                </span>
                {edge.sourceKind === "node" ? (
                  <code>{edge.sourcePort}</code>
                ) : null}
                <span aria-hidden="true" className={styles.edgeArrow} />
                <span>
                  {graphNodes.get(edge.targetNode)?.id ?? edge.targetNode}
                </span>
                <code>{edge.targetPort}</code>
                {edge.sourcePath ? <code>{edge.sourcePath}</code> : null}
                {edge.targetPath ? <code>{edge.targetPath}</code> : null}
              </li>
            ))}
          </ul>
        ) : null}
      </section>

      {selectedNode ? (
        <section aria-label="Node lineage" className={styles.lineage}>
          <div className={styles.sectionHeading}>
            <h2>{selectedNode.id}</h2>
            <div className={styles.lineageActions}>
              {selectedNode.kind === "dataset" ||
              selectedNode.kind === "file" ? (
                <button onClick={onOpenLibrary} type="button">
                  Open Library
                </button>
              ) : selectedNode.kind === "python" ? (
                <button
                  onClick={() => onOpenFunction(selectedNode)}
                  type="button"
                >
                  Open Function
                </button>
              ) : null}
              <button onClick={() => setSelectedNodeId(null)} type="button">
                Close details
              </button>
            </div>
          </div>
          <p>
            {nodeKindLabel(selectedNode)} · {selectedNode.refId} · v
            {selectedNode.version}
          </p>
          {selectedNode.shape === "map" ? (
            <WorkflowMapResults
              items={selectedNodeProgress?.items}
              node={selectedNode}
              projectId={projectId}
              target={snapshotTargets[selectedNode.id] ?? {}}
            />
          ) : (
            <div className={styles.lineageSources}>
              <div>
                <h3>Inputs</h3>
                {selectedNode.kind === "dataset" ? (
                  selectedDatasetInputRows ? (
                    <DatasetRecordsTable
                      ariaLabel="Captured Dataset input records"
                      records={selectedDatasetInputRows}
                    />
                  ) : (
                    <pre>
                      {jsonText(
                        selectedNodeProgress?.inputs ??
                          snapshotSources[selectedNode.id] ??
                          {},
                      )}
                    </pre>
                  )
                ) : (
                  <pre>
                    {jsonText(
                      selectedNodeProgress?.inputs ??
                        snapshotSources[selectedNode.id] ??
                        {},
                    )}
                  </pre>
                )}
              </div>
              <div>
                <h3>Captured target</h3>
                <pre>
                  {jsonText(snapshotTargets[selectedNode.id] ?? selectedNode)}
                </pre>
              </div>
              <div>
                <h3>Output</h3>
                {selectedNodeImage ? (
                  <ImageOutputPreview
                    altText={selectedNodeImage.altText}
                    src={imageDataUrl(selectedNodeImage)}
                    title="Function output"
                  />
                ) : (
                  <pre>{jsonText(selectedNodeProgress?.output)}</pre>
                )}
              </div>
            </div>
          )}
        </section>
      ) : null}
    </section>
  );
}

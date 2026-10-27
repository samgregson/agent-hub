"use client";

import { useEffect, useMemo, useRef, useState } from "react";

import { WorkflowDefinitionEditor } from "./_editor";
import {
  GraphCanvas,
  type GraphCanvasEdge,
  type GraphCanvasNode,
} from "./_graph-canvas";
import { WorkflowMapResults } from "./_map-results";
import {
  WorkflowNodePreview,
  type WorkflowNodePreviewSource,
} from "./_node-preview";
import {
  DatasetRecordsTable,
  type DatasetTableRecord,
} from "@/modules/datasets";
import {
  ImageOutputPreview,
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

type ReviewedSource = {
  nodeId: string;
  kind: "dataset" | "file";
  refId: string;
  expectedVersion: number | string;
  actualVersion?: number;
  name?: string;
  records?: DatasetTableRecord[];
  recordCount?: number;
  content?: string;
  error?: string;
};

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

type BindingPreview = {
  node: WorkflowNode;
  bindings: Array<{
    source: string;
    target: string;
    state: "resolved" | "unavailable" | "invalid";
    value?: unknown;
    note?: string;
  }>;
  invocationInput: Record<string, unknown> | null;
  fullInvocationInput: Record<string, unknown> | null;
  firstMapItem: unknown;
  mapItemCount: number | null;
  mapNote: string | null;
  assemblyNote: string | null;
  blockingIssue: boolean;
};

function pointerTokens(pointer: string): string[] {
  if (pointer === "") return [];
  if (!pointer.startsWith("/")) throw new Error("Invalid JSON Pointer.");
  return pointer
    .slice(1)
    .split("/")
    .map((token) => {
      if (/~(?![01])/.test(token))
        throw new Error("Invalid JSON Pointer escape.");
      return token.replaceAll("~1", "/").replaceAll("~0", "~");
    });
}

function pointerLabel(pointer: string) {
  try {
    return pointerTokens(pointer).join(" / ");
  } catch {
    return pointer;
  }
}

function selectPointer(value: unknown, pointer: string): unknown {
  let current = value;
  for (const token of pointerTokens(pointer)) {
    if (isRecord(current) && Object.hasOwn(current, token)) {
      current = current[token];
    } else if (
      Array.isArray(current) &&
      /^\d+$/.test(token) &&
      Number(token) < current.length
    ) {
      current = current[Number(token)];
    } else {
      throw new Error(`Field ${pointer} is unavailable in the current value.`);
    }
  }
  return current;
}

function setObjectPointer(
  target: Record<string, unknown>,
  tokens: string[],
  value: unknown,
) {
  if (tokens.length === 0)
    throw new Error("Cannot assign an empty nested path.");
  let current = target;
  for (const token of tokens.slice(0, -1)) {
    const existing = current[token];
    if (existing === undefined || existing === null) current[token] = {};
    else if (!isRecord(existing))
      throw new Error("Nested binding paths conflict.");
    current = current[token] as Record<string, unknown>;
  }
  const finalToken = tokens.at(-1)!;
  if (Object.hasOwn(current, finalToken))
    throw new Error("Target field is bound more than once.");
  current[finalToken] = value;
}

function assignPreviewBinding(
  target: Record<string, unknown>,
  port: string,
  pointer: string,
  value: unknown,
  eachItem: boolean,
) {
  const tokens = pointerTokens(pointer);
  if (eachItem && tokens.length > 0) {
    if (!Array.isArray(value))
      throw new Error("Map item binding source is not a collection.");
    const previous = target[port];
    if (
      previous !== undefined &&
      previous !== null &&
      (!Array.isArray(previous) || previous.length !== value.length)
    )
      throw new Error("Map item bindings have different collection lengths.");
    const rows = previous ?? value.map(() => ({}));
    if (!Array.isArray(rows))
      throw new Error("Map item target is not a collection.");
    rows.forEach((row, index) => {
      if (!isRecord(row)) throw new Error("Map item target is not an object.");
      setObjectPointer(row, tokens, value[index]);
    });
    target[port] = rows;
    return;
  }
  if (tokens.length === 0) {
    if (Object.hasOwn(target, port))
      throw new Error("Target input is bound more than once.");
    target[port] = value;
    return;
  }
  const previous = target[port];
  if (previous !== undefined && previous !== null && !isRecord(previous))
    throw new Error("Nested bindings require an object target.");
  const nested = (previous ?? {}) as Record<string, unknown>;
  setObjectPointer(nested, tokens, value);
  target[port] = nested;
}

function sourceNodeLabel(node: WorkflowNode, sources: ReviewedSource[]) {
  if (node.kind === "dataset" || node.kind === "file") {
    const source = sources.find((candidate) => candidate.nodeId === node.id);
    return source?.name ?? node.refId;
  }
  return node.kind === "mcp"
    ? `${node.toolName ?? node.refId} step ${node.id}`
    : `Function step ${node.id}`;
}

function callStepLabel(node: WorkflowNode) {
  return node.kind === "mcp"
    ? `${node.toolName ?? node.refId} · step ${node.id}`
    : `Function step ${node.id}`;
}

function buildBindingPreviews(
  graph: WorkflowGraph,
  sources: ReviewedSource[],
  workflowInputs: Record<string, unknown>,
): BindingPreview[] {
  const nodes = new Map(graph.nodes.map((node) => [node.id, node]));
  return graph.nodes
    .filter((node) => node.kind === "python" || node.kind === "mcp")
    .map((node) => {
      const edges = graph.edges.filter((edge) => edge.targetNode === node.id);
      const assembled: Record<string, unknown> = {};
      let assemblyNote: string | null = null;
      let sourceMapItemCount: number | null = null;
      let blockingIssue = false;
      const mapBindingCounts: number[] = [];
      const bindings = edges.map((edge) => {
        const target = `${edge.targetPort}${edge.targetPath ? ` · ${pointerLabel(edge.targetPath)}` : ""}`;
        let source = "Literal value";
        let state: BindingPreview["bindings"][number]["state"] = "resolved";
        let value: unknown;
        let note: string | undefined;
        let fullCollectionCount: number | null = null;
        try {
          if (edge.sourceKind === "workflowInput") {
            source = `Workflow Input · ${edge.sourceInput ?? "unnamed"}`;
            if (
              !edge.sourceInput ||
              !Object.hasOwn(workflowInputs, edge.sourceInput)
            )
              throw new Error("Not supplied for this Run.");
            value = workflowInputs[edge.sourceInput];
          } else if (edge.sourceKind === "literal") {
            if (!Object.hasOwn(edge, "literal"))
              throw new Error("Literal value is missing.");
            value = edge.literal;
          } else {
            const sourceNode = edge.sourceNode
              ? nodes.get(edge.sourceNode)
              : undefined;
            if (!sourceNode) throw new Error("Source step is unavailable.");
            source = sourceNodeLabel(sourceNode, sources);
            if (sourceNode.kind !== "dataset" && sourceNode.kind !== "file") {
              state = "unavailable";
              note = "Produced by an upstream call step during execution.";
              assemblyNote ??=
                "Some call inputs depend on upstream steps and will resolve during execution.";
              return {
                source: `${source}${edge.sourcePath ? ` · ${pointerLabel(edge.sourcePath)}` : ""}`,
                target,
                state,
                note,
              };
            }
            const sourceSnapshot = sources.find(
              (candidate) => candidate.nodeId === sourceNode.id,
            );
            if (
              !sourceSnapshot ||
              sourceSnapshot.error ||
              String(sourceSnapshot.actualVersion) !==
                String(sourceSnapshot.expectedVersion)
            )
              throw new Error(
                "Current Project source value is unavailable or its version changed.",
              );
            if (sourceNode.kind === "dataset") {
              if (edge.sourcePort !== "records")
                throw new Error("Dataset output port is not records.");
              const isMapItems =
                node.shape === "map" && edge.targetPort === "items";
              if (
                !isMapItems &&
                (sourceSnapshot.recordCount ?? 0) >
                  (sourceSnapshot.records?.length ?? 0)
              ) {
                state = "unavailable";
                note =
                  "Dataset review contains only the first five Records; full collection assembly is withheld.";
                assemblyNote ??=
                  "The Dataset is only partially loaded, so the full call input is withheld.";
                return {
                  source: `${source}${edge.sourcePath ? ` · ${pointerLabel(edge.sourcePath)}` : ""}`,
                  target,
                  state,
                  note,
                };
              }
              value = (sourceSnapshot.records ?? []).map(
                (record) => record.value,
              );
              if (isMapItems) {
                fullCollectionCount = sourceSnapshot.recordCount ?? null;
                sourceMapItemCount =
                  sourceSnapshot.recordCount ??
                  sourceSnapshot.records?.length ??
                  0;
                if (
                  (sourceSnapshot.recordCount ?? 0) >
                  (sourceSnapshot.records?.length ?? 0)
                )
                  note = `Representative sample: first ${sourceSnapshot.records?.length ?? 0} of ${sourceSnapshot.recordCount} Dataset Records.`;
              }
            } else {
              if (edge.sourcePort !== "content")
                throw new Error("Project File output port is not content.");
              value = sourceSnapshot.content;
            }
          }
          const eachItem = node.shape === "map" && edge.targetPort === "items";
          value = eachItem
            ? Array.isArray(value)
              ? value.map((item) => selectPointer(item, edge.sourcePath ?? ""))
              : (() => {
                  throw new Error(
                    "Map item binding source is not a collection.",
                  );
                })()
            : selectPointer(value, edge.sourcePath ?? "");
          if (eachItem && Array.isArray(value))
            mapBindingCounts.push(fullCollectionCount ?? value.length);
          assignPreviewBinding(
            assembled,
            edge.targetPort,
            edge.targetPath ?? "",
            value,
            eachItem,
          );
          return {
            source: `${source}${edge.sourcePath ? ` · ${pointerLabel(edge.sourcePath)}` : ""}`,
            target,
            state,
            value,
          };
        } catch (error) {
          state = "invalid";
          blockingIssue = true;
          note =
            error instanceof Error
              ? error.message
              : "Binding could not be resolved.";
          assemblyNote ??= `Call input is only partially assembled: ${note}`;
          return {
            source: `${source}${edge.sourcePath ? ` · ${pointerLabel(edge.sourcePath)}` : ""}`,
            target,
            state,
            note,
          };
        }
      });
      if (new Set(mapBindingCounts).size > 1) {
        blockingIssue = true;
        assemblyNote ??=
          "Map item bindings have different collection lengths; Run preparation will reject this input.";
      }
      let mapItemCount: number | null = null;
      let mapNote: string | null = null;
      let firstMapItem: unknown;
      let invocationInput: Record<string, unknown> | null = assembled;
      let fullInvocationInput: Record<string, unknown> | null = assembled;
      if (node.shape === "map") {
        const items = assembled.items;
        mapItemCount =
          sourceMapItemCount ?? (Array.isArray(items) ? items.length : null);
        firstMapItem = Array.isArray(items) ? items[0] : undefined;
        const mapInput = node.mapInput;
        const shared = Object.fromEntries(
          Object.entries(assembled).filter(([key]) => key !== "items"),
        );
        invocationInput = shared;
        fullInvocationInput = null;
        if (node.kind === "mcp" && Array.isArray(items)) {
          if (items.length > 0 && isRecord(items[0])) {
            const collisions = Object.keys(items[0]).filter((key) =>
              Object.hasOwn(shared, key),
            );
            if (collisions.length) {
              blockingIssue = true;
              mapNote = `First Map item overlaps shared inputs: ${collisions.join(", ")}.`;
            } else fullInvocationInput = { ...items[0], ...shared };
          } else {
            if (items.length === 0) {
              mapNote = "There are no Map items to preview.";
            } else {
              blockingIssue = true;
              mapNote = "The first MCP Map item is not an object input.";
            }
          }
        } else if (Array.isArray(items) && typeof mapInput === "string") {
          if (items.length > 0) {
            fullInvocationInput = {
              ...shared,
              [mapInput]: items[0],
            };
          } else {
            mapNote =
              "No Map item is available for a representative invocation.";
          }
        } else {
          mapNote = mapInput
            ? "Map items could not be resolved from the available bindings."
            : node.kind === "mcp"
              ? "MCP Map items could not be resolved from the available bindings."
              : "The mapped Function input name is not available in this review; preparation resolves it from the Function contract.";
        }
      }
      return {
        node,
        bindings,
        invocationInput,
        fullInvocationInput,
        firstMapItem,
        mapItemCount,
        mapNote,
        assemblyNote,
        blockingIssue,
      };
    });
}

function readableFields(
  value: unknown,
  prefix = "",
  depth = 0,
): Array<{ path: string; value: unknown }> {
  if (depth > 5)
    return [{ path: prefix || "Value", value: "… nested value omitted" }];
  if (isRecord(value)) {
    const entries = Object.entries(value);
    if (entries.length === 0) return [{ path: prefix || "Value", value: {} }];
    return entries.flatMap(([key, child]) =>
      readableFields(child, prefix ? `${prefix} / ${key}` : key, depth + 1),
    );
  }
  if (Array.isArray(value)) {
    if (value.length === 0) return [{ path: prefix || "Value", value: [] }];
    const fields = value
      .slice(0, 5)
      .flatMap((child, index) =>
        readableFields(
          child,
          `${prefix || "Value"} · item ${index + 1}`,
          depth + 1,
        ),
      );
    if (value.length > 5)
      fields.push({
        path: `${prefix || "Value"} · remaining items`,
        value: `${value.length - 5} more of ${value.length} total`,
      });
    return fields;
  }
  return [{ path: prefix || "Value", value }];
}

function readableValue(value: unknown, path: string) {
  if (
    typeof value === "string" &&
    (value.length > 120 || value.includes("\n"))
  ) {
    const label = path.toLowerCase().endsWith("source")
      ? "Python source"
      : "Text";
    return `${label} · ${value.length} characters`;
  }
  return jsonText(value);
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
  const nodeInspectorRef = useRef<HTMLDivElement>(null);
  const reviewRequestId = useRef(0);
  const [editingDefinitionId, setEditingDefinitionId] = useState<string | null>(
    null,
  );
  const [isRunning, setIsRunning] = useState(false);
  const [reviewingProjectId, setReviewingProjectId] = useState<string | null>(
    null,
  );
  const isReviewing = reviewingProjectId === projectId;
  const [reviewedRun, setReviewedRun] = useState<{
    projectId: string;
    workflowId: string;
    version: number;
    inputs: Record<string, unknown>;
    sources: ReviewedSource[];
  } | null>(null);
  const [actionError, setActionError] = useState<string | null>(null);
  const [savedImages, setSavedImages] = useState<Record<string, boolean>>({});
  const [workflowInputText, setWorkflowInputText] = useState<
    Record<string, string>
  >({});

  useEffect(() => {
    if (selectedNodeId && window.matchMedia("(max-width: 720px)").matches) {
      nodeInspectorRef.current?.scrollIntoView({
        behavior: "smooth",
        block: "nearest",
      });
    }
  }, [selectedNodeId]);

  function discardReview() {
    reviewRequestId.current += 1;
    setReviewedRun(null);
    setReviewingProjectId(null);
  }

  useEffect(() => {
    reviewRequestId.current += 1;
    return () => {
      reviewRequestId.current += 1;
    };
  }, [projectId]);

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
  const graphNodes = new Map(
    (graph?.nodes ?? []).map((node) => [node.id, node]),
  );
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
  const canvasGraph = useMemo(() => {
    const nodes: GraphCanvasNode[] = (graph?.nodes ?? []).map((node) => {
      const progress = isRecord(selectedRun?.execution.nodes)
        ? selectedRun.execution.nodes[node.id]
        : undefined;
      return {
        id: node.id,
        title: nodeLabel(node),
        kind: node.shape === "map" ? "Map" : nodeKindLabel(node),
        status:
          isRecord(progress) && typeof progress.status === "string"
            ? progress.status
            : node.kind === "dataset" || node.kind === "file"
              ? "Captured input"
              : "Not run",
        inputs: [],
        outputs: [],
      };
    });
    const byId = new Map(nodes.map((node) => [node.id, node]));
    const edges: GraphCanvasEdge[] = [];
    const syntheticValues: Record<string, unknown> = {};
    const workflowInputs = isRecord(selectedRun?.snapshot.workflowInputs)
      ? selectedRun.snapshot.workflowInputs
      : {};
    const addPort = (ports: string[] | undefined, port: string) => {
      if (ports && !ports.includes(port)) ports.push(port);
    };
    graph?.edges.forEach((edge, index) => {
      let sourceId = edge.sourceNode;
      let sourcePort = edge.sourcePort ?? "value";
      if (edge.sourceKind === "workflowInput") {
        sourceId = `@workflow-input:${edge.sourceInput ?? index}`;
        sourcePort = "value";
        if (!byId.has(sourceId)) {
          const source: GraphCanvasNode = {
            id: sourceId,
            title: edge.sourceInput ?? "Workflow input",
            kind: "Workflow input",
            status: "Run input",
            inputs: [],
            outputs: ["value"],
          };
          nodes.push(source);
          byId.set(sourceId, source);
          syntheticValues[sourceId] = workflowInputs[edge.sourceInput ?? ""];
        }
      } else if (edge.sourceKind === "literal") {
        sourceId = `@literal:${index}`;
        sourcePort = "value";
        const source: GraphCanvasNode = {
          id: sourceId,
          title: "Literal value",
          kind: "Literal",
          status: "Fixed input",
          inputs: [],
          outputs: ["value"],
        };
        nodes.push(source);
        byId.set(sourceId, source);
        syntheticValues[sourceId] = edge.literal;
      }
      if (!sourceId || !byId.has(sourceId) || !byId.has(edge.targetNode))
        return;
      addPort(byId.get(sourceId)?.outputs, sourcePort);
      addPort(byId.get(edge.targetNode)?.inputs, edge.targetPort);
      edges.push({
        id: `${sourceId}:${sourcePort}:${edge.targetNode}:${edge.targetPort}:${index}`,
        source: sourceId,
        sourcePort,
        target: edge.targetNode,
        targetPort: edge.targetPort,
      });
    });
    graph?.outputs.forEach((output) => {
      addPort(byId.get(output.node)?.outputs, output.port);
    });
    return { nodes, edges, syntheticValues };
  }, [graph, selectedRun]);
  const selectedCanvasNode = canvasGraph.nodes.find(
    (node) => node.id === selectedNodeId,
  );
  const selectedSource = selectedNode
    ? snapshotSources[selectedNode.id]
    : undefined;
  const selectedNodeOutput = selectedNode
    ? selectedNode.kind === "file"
      ? selectedSource?.content
      : selectedNode.kind === "dataset"
        ? selectedSource?.records
        : (selectedNodeProgress?.output ?? selectedNodeProgress?.items)
    : selectedNodeId
      ? canvasGraph.syntheticValues[selectedNodeId]
      : undefined;
  const selectedOutputState =
    selectedNodeProgress?.status === "failed" &&
    selectedNodeOutput === undefined
      ? "error"
      : selectedNodeOutput === undefined
        ? "unavailable"
        : "available";
  const selectedInputSources: WorkflowNodePreviewSource[] = selectedNode
    ? selectedNode.kind === "file" || selectedNode.kind === "dataset"
      ? [
          {
            label: "Captured source",
            value: selectedSource,
            provenance: "Selected Run",
          },
        ]
      : [
          {
            label: "Captured call input",
            value: selectedNodeProgress?.inputs,
            provenance: "Selected Run",
          },
          ...(graph?.edges ?? [])
            .filter((edge) => edge.targetNode === selectedNode.id)
            .map((edge) => {
              const upstream =
                edge.sourceKind === "literal"
                  ? edge.literal
                  : edge.sourceKind === "workflowInput"
                    ? isRecord(selectedRun?.snapshot.workflowInputs)
                      ? selectedRun.snapshot.workflowInputs[
                          edge.sourceInput ?? ""
                        ]
                      : undefined
                    : edge.sourceNode
                      ? (snapshotSources[edge.sourceNode] ??
                        progressByNode[edge.sourceNode]?.output)
                      : undefined;
              let value: unknown = upstream;
              if (
                edge.sourceKind === "node" &&
                edge.sourcePort &&
                isRecord(upstream) &&
                Object.hasOwn(upstream, edge.sourcePort)
              ) {
                value = upstream[edge.sourcePort];
              }
              if (value !== undefined && edge.sourcePath) {
                try {
                  value = selectPointer(value, edge.sourcePath);
                } catch {
                  value = undefined;
                }
              }
              return {
                label: `To ${edge.targetPort}${edge.targetPath ? edge.targetPath : ""}`,
                value,
                provenance:
                  edge.sourceKind === "workflowInput"
                    ? `Workflow input ${edge.sourceInput ?? ""}`
                    : edge.sourceKind === "literal"
                      ? "Literal value"
                      : `From ${edge.sourceNode ?? "source"}${edge.sourcePort ? ` · ${edge.sourcePort}` : ""}`,
              };
            }),
        ]
    : [];
  const reviewedBindings =
    reviewedRun &&
    reviewedRun.projectId === projectId &&
    workflow?.id === reviewedRun.workflowId
      ? buildBindingPreviews(
          workflow.graph,
          reviewedRun.sources,
          reviewedRun.inputs,
        )
      : [];

  function workflowInputKey(name: string) {
    return `${workflow?.id ?? ""}:${workflow?.version ?? 0}:${name}`;
  }

  function collectWorkflowInputs() {
    if (!workflow) return {};
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
    return workflowInputs;
  }

  async function reviewNextRun() {
    if (!workflow) return;
    const requestId = ++reviewRequestId.current;
    const workflowId = workflow.id;
    const workflowVersion = workflow.version;
    const reviewedProjectId = projectId;
    setActionError(null);
    setReviewedRun(null);
    setReviewingProjectId(projectId);
    try {
      const inputs = collectWorkflowInputs();
      const sourceNodes = workflow.graph.nodes.filter(
        (node) => node.kind === "dataset" || node.kind === "file",
      );
      const sources = await Promise.all(
        sourceNodes.map(async (node): Promise<ReviewedSource> => {
          const root = `/api/projects/${encodeURIComponent(projectId)}`;
          try {
            if (node.kind === "dataset") {
              const response = await fetch(
                `${root}/datasets/${encodeURIComponent(node.refId)}`,
                { cache: "no-store" },
              );
              if (!response.ok) throw new Error("Dataset could not be loaded.");
              const dataset: unknown = await response.json();
              if (
                !isRecord(dataset) ||
                typeof dataset.name !== "string" ||
                typeof dataset.version !== "number" ||
                !Array.isArray(dataset.records)
              )
                throw new Error("Dataset response has an invalid shape.");
              const rows = datasetRows({ records: dataset.records });
              if (!rows) throw new Error("Dataset records could not be read.");
              return {
                nodeId: node.id,
                kind: "dataset",
                refId: node.refId,
                expectedVersion: node.version,
                actualVersion: dataset.version,
                name: dataset.name,
                records: rows.slice(0, 5),
                recordCount: rows.length,
              };
            }
            const response = await fetch(
              `${root}/files?path=${encodeURIComponent(node.refId)}`,
              { cache: "no-store" },
            );
            if (!response.ok)
              throw new Error("Project File could not be loaded.");
            const file: unknown = await response.json();
            if (
              !isRecord(file) ||
              typeof file.version !== "number" ||
              typeof file.path !== "string" ||
              typeof file.content !== "string"
            )
              throw new Error("Project File response has an invalid shape.");
            return {
              nodeId: node.id,
              kind: "file",
              refId: node.refId,
              expectedVersion: node.version,
              actualVersion: file.version,
              name: file.path,
              content: file.content,
            };
          } catch (error) {
            return {
              nodeId: node.id,
              kind: node.kind as "dataset" | "file",
              refId: node.refId,
              expectedVersion: node.version,
              error:
                error instanceof Error
                  ? error.message
                  : "Source could not be loaded.",
            };
          }
        }),
      );
      if (requestId !== reviewRequestId.current) return;
      setReviewedRun({
        projectId: reviewedProjectId,
        workflowId,
        version: workflowVersion,
        inputs,
        sources,
      });
    } catch (error) {
      if (
        requestId === reviewRequestId.current &&
        reviewedProjectId === projectId
      )
        setActionError(
          error instanceof Error
            ? error.message
            : "Workflow Inputs are invalid.",
        );
    } finally {
      if (requestId === reviewRequestId.current) setReviewingProjectId(null);
    }
  }

  async function runWorkflow() {
    if (
      !workflow ||
      !reviewedRun ||
      reviewedRun.projectId !== projectId ||
      reviewedRun.workflowId !== workflow.id ||
      reviewedRun.version !== workflow.version ||
      reviewedRun.sources.some(
        (source) =>
          source.error !== undefined ||
          String(source.actualVersion) !== String(source.expectedVersion),
      ) ||
      reviewedBindings.some((preview) => preview.blockingIssue)
    )
      return;
    setIsRunning(true);
    setActionError(null);
    try {
      const workflowInputs = reviewedRun.inputs;
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
      discardReview();
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
    discardReview();
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
                  discardReview();
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
            disabled={isRunning || isReviewing}
            onClick={reviewNextRun}
            type="button"
          >
            {isReviewing ? "Loading review…" : "Review next Run"}
          </button>
        </div>
      </header>

      {actionError ? (
        <p className={styles.error} role="alert">
          {actionError}
        </p>
      ) : null}

      <section aria-label="Workflow graph" className={styles.graphSection}>
        <div className={styles.sectionHeading}>
          <h2>Workflow graph</h2>
          <span>
            {selectedRun
              ? `Selected Run · ${selectedRun.status}`
              : "No Run yet"}
          </span>
        </div>
        <div
          className={`${styles.graphExperience} ${selectedCanvasNode ? styles.graphWithInspector : ""}`}
        >
          <GraphCanvas
            edges={canvasGraph.edges}
            nodes={canvasGraph.nodes}
            onSelectNode={setSelectedNodeId}
            selectedNodeId={selectedNodeId}
            version={selectedRun?.definitionVersion ?? workflow.version}
            workflowId={workflow.id}
          />
          {selectedCanvasNode ? (
            <div className={styles.graphInspector} ref={nodeInspectorRef}>
              <div className={styles.lineageActions}>
                {selectedNode?.kind === "dataset" ||
                selectedNode?.kind === "file" ? (
                  <button onClick={onOpenLibrary} type="button">
                    Open Library
                  </button>
                ) : selectedNode?.kind === "python" ? (
                  <button
                    onClick={() => onOpenFunction(selectedNode)}
                    type="button"
                  >
                    Open Function
                  </button>
                ) : null}
                <button onClick={() => setSelectedNodeId(null)} type="button">
                  Close preview
                </button>
              </div>
              <WorkflowNodePreview
                capturedTarget={
                  selectedNode ? snapshotTargets[selectedNode.id] : undefined
                }
                inputSources={
                  selectedNode
                    ? selectedInputSources
                    : [
                        {
                          label: "Binding source",
                          value: selectedNodeOutput,
                          provenance: selectedCanvasNode.kind,
                        },
                      ]
                }
                kindLabel={selectedCanvasNode.kind}
                node={
                  selectedNode ?? {
                    id: selectedCanvasNode.id,
                    kind: selectedCanvasNode.kind,
                    refId: selectedCanvasNode.title,
                    version: workflow.version,
                  }
                }
                output={selectedNodeOutput}
                outputError={selectedNodeProgress?.error}
                outputState={selectedOutputState}
              />
              {selectedNode?.shape === "map" ? (
                <WorkflowMapResults
                  items={selectedNodeProgress?.items}
                  node={selectedNode}
                  projectId={projectId}
                  target={snapshotTargets[selectedNode.id] ?? {}}
                />
              ) : null}
            </div>
          ) : null}
        </div>
      </section>

      {reviewedRun?.projectId === projectId &&
      reviewedRun.workflowId === workflow.id &&
      reviewedRun.version === workflow.version ? (
        <section aria-label="Review next Run" className={styles.outputs}>
          <div className={styles.sectionHeading}>
            <h2>Review next Run</h2>
            <span>Definition v{reviewedRun.version}</span>
          </div>
          <div className={styles.outputList}>
            <div className={styles.output}>
              <h3>Workflow Inputs</h3>
              {Object.keys(reviewedRun.inputs).length > 0 ? (
                Object.entries(reviewedRun.inputs).map(([name, value]) => (
                  <p key={name}>
                    <strong>{name}</strong>:{" "}
                    {isRecord(value) || Array.isArray(value) ? (
                      <code>{jsonText(value)}</code>
                    ) : (
                      String(value)
                    )}
                  </p>
                ))
              ) : (
                <p>No per-Run inputs.</p>
              )}
            </div>
            <div className={styles.output}>
              <h3>Sources and calls</h3>
              <p>
                {
                  workflow.graph.nodes.filter(
                    (node) => node.kind === "dataset" || node.kind === "file",
                  ).length
                }{" "}
                source(s) ·{" "}
                {
                  workflow.graph.nodes.filter(
                    (node) => node.kind === "python" || node.kind === "mcp",
                  ).length
                }{" "}
                call step(s)
              </p>
              <p>
                Project File and Dataset values are captured when the Run
                starts. Upstream outputs are resolved as their steps finish.
                Review the connections in Edit Workflow before executing.
              </p>
            </div>
          </div>
          <div className={styles.outputList}>
            {reviewedRun.sources.map((source) => {
              const versionMatches =
                source.actualVersion !== undefined &&
                String(source.actualVersion) === String(source.expectedVersion);
              return (
                <article className={styles.output} key={source.nodeId}>
                  <h3>
                    {source.kind === "dataset" ? "Dataset" : "Project File"} ·{" "}
                    {source.name ?? source.refId}
                  </h3>
                  <p>
                    Workflow source <strong>{source.nodeId}</strong> ·
                    configured version {String(source.expectedVersion)}
                    {source.actualVersion !== undefined
                      ? ` · current version ${source.actualVersion}`
                      : ""}
                  </p>
                  {source.error ? (
                    <p className={styles.error} role="alert">
                      {source.error}
                    </p>
                  ) : versionMatches ? (
                    source.kind === "dataset" ? (
                      <>
                        <p>
                          Showing the first {source.records?.length ?? 0} of{" "}
                          {source.recordCount ?? 0} Records.
                        </p>
                        <DatasetRecordsTable
                          ariaLabel={`Review Records for ${source.name ?? source.refId}`}
                          records={source.records ?? []}
                        />
                      </>
                    ) : (
                      <details>
                        <summary>Preview current file content</summary>
                        <pre>
                          {(source.content ?? "").slice(0, 1200)}
                          {(source.content?.length ?? 0) > 1200
                            ? "\n… content preview truncated"
                            : ""}
                        </pre>
                      </details>
                    )
                  ) : (
                    <p className={styles.error} role="alert">
                      This source changed since the Workflow Definition was
                      saved. Review the latest source and update the Definition
                      before running.
                    </p>
                  )}
                </article>
              );
            })}
          </div>
          <section aria-label="Resolved Workflow binding previews">
            <div className={styles.sectionHeading}>
              <h2>Resolved call inputs</h2>
              <span>Read-only spot checks</span>
            </div>
            {reviewedBindings.length > 0 ? (
              <div className={styles.outputList}>
                {reviewedBindings.map((preview) => {
                  const hasUnavailableBinding = preview.bindings.some(
                    (binding) => binding.state !== "resolved",
                  );
                  return (
                    <article className={styles.output} key={preview.node.id}>
                      <h3>{callStepLabel(preview.node)}</h3>
                      <h4>Bindings</h4>
                      {preview.bindings.length > 0 ? (
                        <ul className={styles.bindingReviewList}>
                          {preview.bindings.map((binding, index) => (
                            <li key={`${preview.node.id}-binding-${index}`}>
                              <p>
                                <strong>{binding.source}</strong>
                                <span aria-hidden="true"> → </span>
                                <strong>{binding.target}</strong>
                              </p>
                              {binding.state === "resolved" ? (
                                <>
                                  {binding.note ? (
                                    <p className={styles.bindingHelp}>
                                      {binding.note}
                                    </p>
                                  ) : null}
                                  <details>
                                    <summary>Inspect selected value</summary>
                                    <pre>{jsonText(binding.value)}</pre>
                                  </details>
                                </>
                              ) : (
                                <p className={styles.bindingUnavailable}>
                                  {binding.state === "invalid"
                                    ? "Could not resolve: "
                                    : "Unavailable until execution: "}
                                  {binding.note}
                                </p>
                              )}
                            </li>
                          ))}
                        </ul>
                      ) : (
                        <p>No bindings are configured for this call.</p>
                      )}
                      <h4>
                        {preview.node.shape === "map"
                          ? `Shared inputs for the first Map invocation${preview.mapItemCount === null ? "" : ` · ${preview.mapItemCount} items`}`
                          : "Assembled call input"}
                      </h4>
                      {preview.mapNote ? (
                        <p className={styles.bindingUnavailable}>
                          {preview.mapNote}
                        </p>
                      ) : null}
                      {preview.assemblyNote ? (
                        <p className={styles.bindingUnavailable}>
                          {preview.assemblyNote}
                        </p>
                      ) : null}
                      {preview.blockingIssue ? (
                        <p className={styles.bindingUnavailable} role="alert">
                          Resolve the binding conflict before starting this Run.
                        </p>
                      ) : null}
                      {preview.node.shape === "map" &&
                      preview.firstMapItem !== undefined ? (
                        <>
                          <p>
                            Representative first Map item
                            {preview.mapItemCount === null
                              ? ""
                              : ` of ${preview.mapItemCount}`}
                          </p>
                          <ul className={styles.bindingValueList}>
                            {readableFields(preview.firstMapItem)
                              .slice(0, 20)
                              .map((field) => (
                                <li
                                  key={`${preview.node.id}-map-item-${field.path}`}
                                >
                                  <strong>{field.path}</strong>
                                  <code>
                                    {readableValue(field.value, field.path)}
                                  </code>
                                </li>
                              ))}
                          </ul>
                          {preview.node.shape === "map" ? (
                            <details>
                              <summary>Inspect full first Map item</summary>
                              <pre>{jsonText(preview.firstMapItem)}</pre>
                            </details>
                          ) : null}
                        </>
                      ) : null}
                      {preview.invocationInput ? (
                        <>
                          {hasUnavailableBinding ? (
                            <p>
                              Known fields only; upstream-dependent fields are
                              omitted from this partial preview.
                            </p>
                          ) : null}
                          <ul className={styles.bindingValueList}>
                            {readableFields(preview.invocationInput)
                              .slice(0, 20)
                              .map((field) => (
                                <li key={`${preview.node.id}-${field.path}`}>
                                  <strong>{field.path}</strong>
                                  <code>
                                    {readableValue(field.value, field.path)}
                                  </code>
                                </li>
                              ))}
                          </ul>
                          <details>
                            <summary>
                              {preview.fullInvocationInput
                                ? "Inspect full JSON input"
                                : "Inspect known JSON inputs"}
                            </summary>
                            <pre>
                              {jsonText(
                                preview.fullInvocationInput ??
                                  preview.invocationInput,
                              )}
                            </pre>
                          </details>
                        </>
                      ) : preview.mapNote ? null : (
                        <p>No resolved input values are available yet.</p>
                      )}
                      <p className={styles.bindingHelp}>
                        This preview is not authoritative. Run preparation
                        rechecks and captures source versions; upstream outputs
                        are resolved during execution.
                      </p>
                    </article>
                  );
                })}
              </div>
            ) : (
              <p>No Python Function or MCP call steps need inputs.</p>
            )}
          </section>
          <p className={styles.bindingHelp}>
            These read-only values are spot checks from the current Project
            sources. Run preparation will recheck and capture the source
            versions; review again if a source changes before execution.
          </p>
          <div className={styles.headerActions}>
            <button
              className={styles.secondaryButton}
              onClick={discardReview}
              type="button"
            >
              Back to inputs
            </button>
            <button
              className={styles.runButton}
              disabled={
                isRunning ||
                isReviewing ||
                reviewedRun.sources.some(
                  (source) =>
                    source.error !== undefined ||
                    String(source.actualVersion) !==
                      String(source.expectedVersion),
                ) ||
                reviewedBindings.some((preview) => preview.blockingIssue)
              }
              onClick={() => void runWorkflow()}
              type="button"
            >
              {isRunning ? "Starting…" : "Run Workflow"}
            </button>
          </div>
        </section>
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
                    onChange={(event) => {
                      discardReview();
                      setWorkflowInputText((current) => ({
                        ...current,
                        [workflowInputKey(input.name)]: event.target.value,
                      }));
                    }}
                    value={
                      workflowInputText[workflowInputKey(input.name)] ?? ""
                    }
                  />
                ) : (
                  <textarea
                    aria-label={`Workflow Input ${input.name}`}
                    onChange={(event) => {
                      discardReview();
                      setWorkflowInputText((current) => ({
                        ...current,
                        [workflowInputKey(input.name)]: event.target.value,
                      }));
                    }}
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
    </section>
  );
}

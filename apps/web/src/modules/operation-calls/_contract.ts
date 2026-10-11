export type TargetKind = "python" | "mcp";
export type CallShape = "single" | "map";

export interface CallSelection {
  targetKind: TargetKind;
  shape: CallShape;
  definitionId: string;
  pluginId: string;
  toolName: string;
  datasetId: string;
  inputsJson: string;
  parametersJson: string;
}

export interface CallPlan {
  callKind: "pythonFunction" | "pythonMap" | "mcpCall" | "mcpMap";
  invocationCount: number;
  outputKind: "transformRun" | "batchResultSet";
  definitionId?: string;
  definitionRevision?: number;
  name?: string;
  pluginId?: string;
  pluginVersion?: string;
  toolName?: string;
  datasetId?: string;
  datasetVersion?: number;
  recordIds?: string[];
  inputs?: unknown;
  boundInputs?: unknown;
  datasetRecords?: unknown;
  parameters?: Record<string, unknown>;
  runtime?: string | null;
  sourceHash?: string;
  packageHash?: string | null;
  inputSchema?: Record<string, unknown>;
  outputSchema?: Record<string, unknown>;
}

function jsonObject(raw: string, label: string): Record<string, unknown> {
  let value: unknown;
  try {
    value = JSON.parse(raw);
  } catch {
    throw new Error(`${label} must be a JSON object.`);
  }
  if (!value || typeof value !== "object" || Array.isArray(value)) {
    throw new Error(`${label} must be a JSON object.`);
  }
  return value as Record<string, unknown>;
}

export function reviewRequest(selection: CallSelection): {
  path: string;
  body: Record<string, unknown>;
} {
  const { targetKind, shape, definitionId, pluginId, toolName, datasetId } =
    selection;
  if (targetKind === "python") {
    if (!definitionId) throw new Error("Choose a Function.");
    const parameters = jsonObject(selection.parametersJson, "Parameters");
    if (shape === "single") {
      return {
        path: `transforms/${encodeURIComponent(definitionId)}/call`,
        body: {
          inputs: jsonObject(selection.inputsJson, "Inputs"),
          parameters,
        },
      };
    }
    if (!datasetId) throw new Error("Choose a Dataset.");
    return {
      path: "batch-runs/python-map",
      body: { definitionId, datasetId, parameters },
    };
  }
  if (!pluginId || !toolName)
    throw new Error("Choose an enabled Plugin and tool.");
  if (shape === "single") {
    return {
      path: "batch-runs/mcp-call",
      body: {
        pluginId,
        toolName,
        arguments: jsonObject(selection.inputsJson, "Arguments"),
      },
    };
  }
  if (!datasetId) throw new Error("Choose a Dataset.");
  return {
    path: "batch-runs/mcp-map",
    body: { pluginId, toolName, datasetId },
  };
}

export function startRequest(plan: CallPlan): {
  path: string;
  body: Record<string, unknown>;
} {
  switch (plan.callKind) {
    case "pythonFunction":
      if (!plan.definitionId || !plan.definitionRevision)
        throw new Error("Review a Function call again.");
      return {
        path: `transforms/${encodeURIComponent(plan.definitionId)}/call`,
        body: {
          inputs: plan.inputs,
          parameters: plan.parameters ?? {},
          expectedRevision: plan.definitionRevision,
        },
      };
    case "pythonMap":
      if (
        !plan.definitionId ||
        !plan.definitionRevision ||
        !plan.datasetId ||
        !plan.datasetVersion
      )
        throw new Error("Review the Map again.");
      return {
        path: "batch-runs/python-map",
        body: {
          definitionId: plan.definitionId,
          datasetId: plan.datasetId,
          parameters: plan.parameters ?? {},
          expectedDefinitionRevision: plan.definitionRevision,
          expectedDatasetVersion: plan.datasetVersion,
        },
      };
    case "mcpCall":
      if (!plan.pluginId || !plan.pluginVersion || !plan.toolName)
        throw new Error("Review the MCP call again.");
      return {
        path: "batch-runs/mcp-call",
        body: {
          pluginId: plan.pluginId,
          toolName: plan.toolName,
          arguments: plan.inputs,
          expectedPluginVersion: plan.pluginVersion,
        },
      };
    case "mcpMap":
      if (
        !plan.pluginId ||
        !plan.toolName ||
        !plan.datasetId ||
        !plan.datasetVersion
      )
        throw new Error("Review the MCP Map again.");
      return {
        path: "batch-runs/mcp-map",
        body: {
          pluginId: plan.pluginId,
          toolName: plan.toolName,
          datasetId: plan.datasetId,
          expectedDatasetVersion: plan.datasetVersion,
        },
      };
  }
}

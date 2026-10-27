const approvalOnlyTools = new Set([
  "write_file",
  "edit_file",
  "foundation_protected_action",
  "create_project_dataset",
  "update_project_dataset",
  "delete_project_dataset",
  "create_project_function",
  "update_project_function",
  "delete_project_function",
]);

export function isFunctionApprovalTool(toolName: string): boolean {
  return [
    "create_project_function",
    "update_project_function",
    "delete_project_function",
  ].includes(toolName);
}

export interface FunctionApprovalField {
  name: string;
  type: string;
  description: string;
  required: boolean;
  example?: unknown;
}

export interface FunctionApprovalSummary {
  purpose: string | null;
  inputs: FunctionApprovalField[] | null;
  outputs: FunctionApprovalField[] | null;
  inputExample: string | null;
  outputExample: string | null;
}

export function readableFunctionExample(value: unknown): string {
  const summarize = (item: unknown, depth = 0): string => {
    if (item === null) return "none";
    if (typeof item === "string")
      return item.length > 60 ? `“${item.slice(0, 57)}…”` : `“${item}”`;
    if (typeof item !== "object") return String(item);
    if (Array.isArray(item)) {
      if (depth >= 3) return `List with ${item.length} items`;
      const preview = item
        .slice(0, 3)
        .map((child) => summarize(child, depth + 1));
      return `List (${item.length} items: ${preview.join("; ")}${item.length > preview.length ? "; …" : ""})`;
    }
    const entries = Object.entries(item as Record<string, unknown>);
    if (depth >= 3) return `Object with ${entries.length} fields`;
    const preview = entries
      .slice(0, 3)
      .map(([key, child]) => `${key}: ${summarize(child, depth + 1)}`);
    return `Object (${preview.join("; ")}${entries.length > preview.length ? "; …" : ""})`;
  };
  const summary = summarize(value);
  return summary.length > 180 ? `${summary.slice(0, 177)}…` : summary;
}

function readableSchemaExample(schema: unknown): string | null {
  if (typeof schema !== "object" || schema === null || Array.isArray(schema)) {
    return null;
  }
  const record = schema as Record<string, unknown>;
  const example =
    Array.isArray(record.examples) && record.examples.length > 0
      ? record.examples[0]
      : record.example;
  if (example === undefined) return null;
  return readableFunctionExample(example);
}

function schemaFields(schema: unknown): FunctionApprovalField[] | null {
  if (typeof schema !== "object" || schema === null || Array.isArray(schema)) {
    return null;
  }
  const record = schema as Record<string, unknown>;
  if (
    typeof record.properties !== "object" ||
    record.properties === null ||
    Array.isArray(record.properties)
  ) {
    return [];
  }
  const required = Array.isArray(record.required) ? record.required : [];
  return Object.entries(record.properties as Record<string, unknown>).flatMap(
    ([name, value]) => {
      if (typeof value !== "object" || value === null || Array.isArray(value)) {
        return [];
      }
      const field = value as Record<string, unknown>;
      const type = Array.isArray(field.type)
        ? field.type.join(" or ")
        : String(field.type ?? "value");
      const example = Array.isArray(field.examples)
        ? field.examples[0]
        : field.example;
      return [
        {
          name,
          type,
          description:
            typeof field.description === "string" ? field.description : "",
          required: required.includes(name),
          ...(example !== undefined ? { example } : {}),
        },
      ];
    },
  );
}

export function functionApprovalSummary(
  args: unknown,
): FunctionApprovalSummary {
  if (typeof args !== "object" || args === null || Array.isArray(args)) {
    return {
      purpose: null,
      inputs: null,
      outputs: null,
      inputExample: null,
      outputExample: null,
    };
  }
  const fields = args as Record<string, unknown>;
  const inputSchema = fields.input_schema;
  const outputSchema = fields.output_schema;
  const purpose =
    typeof inputSchema === "object" &&
    inputSchema !== null &&
    !Array.isArray(inputSchema) &&
    typeof (inputSchema as Record<string, unknown>).description === "string"
      ? String((inputSchema as Record<string, unknown>).description)
      : null;
  return {
    purpose,
    inputs: schemaFields(inputSchema),
    outputs: schemaFields(outputSchema),
    inputExample: readableSchemaExample(inputSchema),
    outputExample: readableSchemaExample(outputSchema),
  };
}

export function isFunctionDefinitionApproval(toolName: string): boolean {
  return (
    toolName === "create_project_function" ||
    toolName === "update_project_function"
  );
}

export function functionApprovalName(args: unknown): string {
  if (
    typeof args === "object" &&
    args !== null &&
    !Array.isArray(args) &&
    typeof (args as Record<string, unknown>).name === "string"
  ) {
    return String((args as Record<string, unknown>).name);
  }
  if (
    typeof args === "object" &&
    args !== null &&
    !Array.isArray(args) &&
    typeof (args as Record<string, unknown>).function_id === "string"
  ) {
    return `Function ${String((args as Record<string, unknown>).function_id)}`;
  }
  return "Python Function";
}

export function functionApprovalTechnicalDetails(args: unknown): string {
  return JSON.stringify(args, null, 2) ?? "No proposal details available.";
}

export interface ProposedFileReview {
  kind: "diff" | "preview";
  path: string;
  proposed: string;
  text: string;
}

export function approvalLabel(toolName: string): string {
  if (toolName === "create_project_function")
    return "Approve new Python Function";
  if (toolName === "update_project_function")
    return "Approve Python Function revision";
  if (toolName === "delete_project_function")
    return "Approve Python Function deletion";
  if (toolName === "write_file" || toolName === "edit_file") {
    return "Approve Project File change";
  }
  if (toolName.includes("artifact")) {
    return toolName.startsWith("create_")
      ? "Approve Project Artifact creation"
      : "Approve Project Artifact change";
  }
  if (toolName === "delete_project_dataset") return "Approve Dataset deletion";
  if (toolName.includes("dataset")) return "Approve Dataset change";
  return "Approve protected action";
}

export function isApprovalOnlyTool(toolName: string): boolean {
  return approvalOnlyTools.has(toolName);
}

export function approvalTarget(args: unknown): {
  artifactId?: string;
  path?: string;
  summary: string;
} {
  if (typeof args !== "object" || args === null || Array.isArray(args)) {
    return { summary: "Review this action before the agent continues." };
  }
  const fields = args as Record<string, unknown>;
  const path =
    typeof fields.file_path === "string" ? fields.file_path : undefined;
  if (path?.startsWith("/project/") && !path.split("/").includes("..")) {
    return { path, summary: path };
  }
  const artifactId =
    typeof fields.artifact_id === "string" ? fields.artifact_id : undefined;
  const action =
    typeof fields.semantic_action === "string"
      ? fields.semantic_action
      : typeof fields.operation === "string"
        ? fields.operation
        : undefined;
  if (artifactId) {
    return {
      artifactId,
      summary: `Artifact ${artifactId}${action ? ` · ${action}` : ""}`,
    };
  }
  const name = typeof fields.name === "string" ? fields.name : undefined;
  const datasetId =
    typeof fields.dataset_id === "string" ? fields.dataset_id : undefined;
  if (datasetId) {
    return {
      summary: `Dataset ${name ?? datasetId}${action ? ` · ${action}` : ""}`,
    };
  }
  const definitionId =
    typeof fields.definition_id === "string" ? fields.definition_id : undefined;
  if (definitionId) {
    return { summary: `Definition ${definitionId}` };
  }
  if (action) return { summary: action };
  if (name) return { summary: name };
  return { summary: "Review this action before the agent continues." };
}

export function resolvedApprovalReview(
  toolName: string,
  args: unknown,
): string {
  if (typeof args !== "object" || args === null || Array.isArray(args)) {
    return JSON.stringify(args, null, 2) ?? "No action details available.";
  }
  const fields = args as Record<string, unknown>;
  if (toolName === "write_file" && typeof fields.content === "string") {
    return fields.content;
  }
  if (
    toolName === "edit_file" &&
    typeof fields.old_string === "string" &&
    typeof fields.new_string === "string"
  ) {
    return [
      fields.replace_all === true
        ? "Replace all matches"
        : "Replace first match",
      "--- Original text",
      fields.old_string,
      "+++ Proposed text",
      fields.new_string,
    ].join("\n");
  }
  return JSON.stringify(args, null, 2);
}

export function proposedFileContent(
  toolName: string,
  args: unknown,
  current: string | null,
): string | null {
  if (typeof args !== "object" || args === null || Array.isArray(args))
    return null;
  const fields = args as Record<string, unknown>;
  if (toolName === "write_file" && typeof fields.content === "string") {
    return fields.content;
  }
  if (
    toolName === "edit_file" &&
    current !== null &&
    typeof fields.old_string === "string" &&
    typeof fields.new_string === "string" &&
    fields.old_string.length > 0 &&
    current.includes(fields.old_string)
  ) {
    return fields.replace_all === true
      ? current.replaceAll(fields.old_string, fields.new_string)
      : current.replace(fields.old_string, fields.new_string);
  }
  return null;
}

export function unifiedFileDiff(
  path: string,
  before: string,
  after: string,
): string {
  const oldLines = before.split("\n");
  const newLines = after.split("\n");
  let prefix = 0;
  while (
    prefix < oldLines.length &&
    prefix < newLines.length &&
    oldLines[prefix] === newLines[prefix]
  ) {
    prefix += 1;
  }
  let suffix = 0;
  while (
    suffix < oldLines.length - prefix &&
    suffix < newLines.length - prefix &&
    oldLines[oldLines.length - 1 - suffix] ===
      newLines[newLines.length - 1 - suffix]
  ) {
    suffix += 1;
  }
  if (prefix === oldLines.length && prefix === newLines.length) {
    return "No content change.";
  }
  const contextBefore = Math.max(0, prefix - 3);
  const contextAfter = Math.min(3, suffix);
  const oldEnd = oldLines.length - suffix + contextAfter;
  const newEnd = newLines.length - suffix + contextAfter;
  return [
    `--- a${path}`,
    `+++ b${path}`,
    `@@ -${contextBefore + 1},${oldEnd - contextBefore} +${contextBefore + 1},${newEnd - contextBefore} @@`,
    ...oldLines.slice(contextBefore, prefix).map((line) => ` ${line}`),
    ...oldLines
      .slice(prefix, oldLines.length - suffix)
      .map((line) => `-${line}`),
    ...newLines
      .slice(prefix, newLines.length - suffix)
      .map((line) => `+${line}`),
    ...oldLines
      .slice(oldLines.length - suffix, oldEnd)
      .map((line) => ` ${line}`),
  ].join("\n");
}

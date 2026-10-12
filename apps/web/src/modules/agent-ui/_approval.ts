const approvalOnlyTools = new Set([
  "write_file",
  "edit_file",
  "foundation_protected_action",
  "create_project_dataset",
  "update_project_dataset",
  "delete_project_dataset",
]);

export interface ProposedFileReview {
  kind: "diff" | "preview";
  path: string;
  proposed: string;
  text: string;
}

export function approvalLabel(toolName: string): string {
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

export function approvalTarget(
  args: unknown,
): {
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

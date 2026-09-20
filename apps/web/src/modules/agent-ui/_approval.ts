const artifactApprovalLabels: Record<string, string> = {
  create_foundation_status_artifact: "Approve Project Artifact creation",
  set_foundation_status_artifact_status: "Approve Project Artifact change",
};

const approvalOnlyTools = new Set([
  "write_file",
  "edit_file",
  "foundation_protected_action",
  ...Object.keys(artifactApprovalLabels),
]);

export function approvalLabel(toolName: string): string {
  if (toolName === "write_file" || toolName === "edit_file") {
    return "Approve Project File change";
  }
  return artifactApprovalLabels[toolName] ?? "Approve protected action";
}

export function isApprovalOnlyTool(toolName: string): boolean {
  return approvalOnlyTools.has(toolName);
}

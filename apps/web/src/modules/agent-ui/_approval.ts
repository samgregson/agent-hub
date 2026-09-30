const approvalOnlyTools = new Set([
  "write_file",
  "edit_file",
  "foundation_protected_action",
]);

export function approvalLabel(toolName: string): string {
  if (toolName === "write_file" || toolName === "edit_file") {
    return "Approve Project File change";
  }
  return "Approve protected action";
}

export function isApprovalOnlyTool(toolName: string): boolean {
  return approvalOnlyTools.has(toolName);
}

import "server-only";

import { forwardBackendRequest } from "@/shared/http/server";

export function forwardWorkflowRequest(
  request: Request,
  projectId: string,
  workflowId?: string,
  suffix = "",
): Promise<Response> {
  return forwardBackendRequest(
    request,
    `/api/projects/${encodeURIComponent(projectId)}/workflows${workflowId ? `/${encodeURIComponent(workflowId)}` : ""}${suffix}`,
    "application/json",
  );
}

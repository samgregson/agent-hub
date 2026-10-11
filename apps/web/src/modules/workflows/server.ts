import "server-only";

import { forwardBackendRequest } from "@/shared/http/server";

export function forwardWorkflowRequest(
  request: Request,
  projectId: string,
  workflowId?: string,
): Promise<Response> {
  return forwardBackendRequest(
    request,
    `/api/projects/${encodeURIComponent(projectId)}/workflows${workflowId ? `/${encodeURIComponent(workflowId)}` : ""}`,
    "application/json",
  );
}

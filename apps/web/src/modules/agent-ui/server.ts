import "server-only";

import { forwardBackendRequest } from "@/shared/http/server";

export function forwardAgentRequest(
  request: Request,
  projectId: string,
  threadId: string,
  suffix: "agent" | "history" | "runs" | "scratch" | "scratch/save",
): Promise<Response> {
  const path = `/api/projects/${encodeURIComponent(projectId)}/threads/${encodeURIComponent(threadId)}/${suffix}`;
  return forwardBackendRequest(request, path);
}

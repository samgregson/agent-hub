import "server-only";

import { forwardBackendRequest } from "@/shared/http/server";

export function forwardArtifactRequest(
  request: Request,
  projectId: string,
  artifactPath = "",
): Promise<Response> {
  return forwardBackendRequest(
    request,
    `/api/projects/${encodeURIComponent(projectId)}/artifacts${artifactPath}`,
    "application/json",
  );
}

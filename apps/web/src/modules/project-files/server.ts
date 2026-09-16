import "server-only";

import { forwardBackendRequest } from "@/shared/http/server";

export function forwardProjectFileRequest(
  request: Request,
  projectId: string,
  path = "",
): Promise<Response> {
  const url = new URL(request.url);
  return forwardBackendRequest(
    request,
    `/api/projects/${encodeURIComponent(projectId)}/files${path}${url.search}`,
  );
}

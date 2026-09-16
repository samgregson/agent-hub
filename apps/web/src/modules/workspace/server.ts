import "server-only";

import { forwardBackendRequest } from "@/shared/http/server";

export function forwardProjectRequest(
  request: Request,
  path = "",
): Promise<Response> {
  return forwardBackendRequest(
    request,
    `/api/projects${path}`,
    "application/json",
  );
}

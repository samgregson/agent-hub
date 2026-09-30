import "server-only";

import { forwardBackendRequest } from "@/shared/http/server";

export function forwardDatasetRequest(
  request: Request,
  projectId: string,
  path: "datasets" | "batch-definitions",
  itemId?: string,
): Promise<Response> {
  return forwardBackendRequest(
    request,
    `/api/projects/${encodeURIComponent(projectId)}/${path}${itemId ? `/${encodeURIComponent(itemId)}` : ""}`,
    "application/json",
  );
}

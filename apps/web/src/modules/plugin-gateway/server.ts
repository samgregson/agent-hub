import "server-only";

import { forwardBackendRequest } from "@/shared/http/server";

export function forwardPluginRequest(
  request: Request,
  projectId: string,
  pluginId?: string,
  suffix = "",
): Promise<Response> {
  const pluginPath = pluginId
    ? `/plugins/${encodeURIComponent(pluginId)}${suffix}`
    : "/plugins";
  return forwardBackendRequest(
    request,
    `/api/projects/${encodeURIComponent(projectId)}${pluginPath}`,
    "application/json",
  );
}

import { forwardPluginRequest } from "@/modules/plugin-gateway/server";

interface RouteContext {
  params: Promise<{
    pluginId: string;
    projectId: string;
    toolName: string;
  }>;
}

export async function GET(request: Request, context: RouteContext) {
  const { pluginId, projectId, toolName } = await context.params;
  return forwardPluginRequest(
    request,
    projectId,
    pluginId,
    `/tools/${encodeURIComponent(toolName)}/app${new URL(request.url).search}`,
  );
}

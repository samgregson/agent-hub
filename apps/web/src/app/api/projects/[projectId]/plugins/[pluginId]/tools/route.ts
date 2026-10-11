import { forwardPluginRequest } from "@/modules/plugin-gateway/server";

interface RouteContext {
  params: Promise<{ pluginId: string; projectId: string }>;
}

export async function GET(request: Request, context: RouteContext) {
  const { pluginId, projectId } = await context.params;
  return forwardPluginRequest(request, projectId, pluginId, "/tools");
}

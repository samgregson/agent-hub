import { forwardPluginRequest } from "@/modules/plugin-gateway/server";

interface RouteContext {
  params: Promise<{ pluginId: string; projectId: string }>;
}

async function forwardSelection(
  request: Request,
  context: RouteContext,
): Promise<Response> {
  const { pluginId, projectId } = await context.params;
  return forwardPluginRequest(request, projectId, pluginId);
}

export const PUT = forwardSelection;
export const DELETE = forwardSelection;

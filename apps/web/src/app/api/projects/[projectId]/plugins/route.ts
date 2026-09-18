import { forwardPluginRequest } from "@/modules/plugin-gateway/server";

interface RouteContext {
  params: Promise<{ projectId: string }>;
}

export async function GET(
  request: Request,
  context: RouteContext,
): Promise<Response> {
  const { projectId } = await context.params;
  return forwardPluginRequest(request, projectId);
}

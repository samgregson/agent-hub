import { forwardProjectRequest } from "@/modules/projects/index.server";

interface RouteContext {
  params: Promise<{ projectId: string }>;
}

export async function GET(
  request: Request,
  context: RouteContext,
): Promise<Response> {
  const { projectId } = await context.params;
  return forwardProjectRequest(request, `/${encodeURIComponent(projectId)}`);
}

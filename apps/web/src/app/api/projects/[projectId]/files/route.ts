import { forwardProjectFileRequest } from "@/modules/project-files/server";

interface RouteContext {
  params: Promise<{ projectId: string }>;
}

export async function GET(
  request: Request,
  context: RouteContext,
): Promise<Response> {
  const { projectId } = await context.params;
  return forwardProjectFileRequest(request, projectId);
}

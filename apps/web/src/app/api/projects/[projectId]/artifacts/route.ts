import { forwardArtifactRequest } from "@/modules/artifact-view-host/server";

interface RouteContext {
  params: Promise<{ projectId: string }>;
}

export async function GET(request: Request, context: RouteContext): Promise<Response> {
  const { projectId } = await context.params;
  return forwardArtifactRequest(request, projectId);
}

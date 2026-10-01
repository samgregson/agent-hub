import { forwardBackendRequest } from "@/shared/http/server";

interface RouteContext {
  params: Promise<{ projectId: string; definitionId: string }>;
}

async function forward(request: Request, context: RouteContext): Promise<Response> {
  const { projectId, definitionId } = await context.params;
  return forwardBackendRequest(
    request,
    `/api/projects/${encodeURIComponent(projectId)}/transforms/${encodeURIComponent(definitionId)}`,
    "application/json",
  );
}

export const GET = forward;
export const PUT = forward;
export const DELETE = forward;

import { forwardBackendRequest } from "@/shared/http/server";

interface RouteContext {
  params: Promise<{ definitionId: string; projectId: string }>;
}

async function forward(
  request: Request,
  context: RouteContext,
): Promise<Response> {
  const { definitionId, projectId } = await context.params;
  return forwardBackendRequest(
    request,
    `/api/projects/${encodeURIComponent(projectId)}/batch-definitions/${encodeURIComponent(definitionId)}/file-binding`,
    "application/json",
  );
}

export const GET = forward;
export const POST = forward;
export const PUT = forward;

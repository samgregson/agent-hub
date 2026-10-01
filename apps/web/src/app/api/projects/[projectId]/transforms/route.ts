import { forwardBackendRequest } from "@/shared/http/server";

interface RouteContext {
  params: Promise<{ projectId: string }>;
}

async function forward(request: Request, context: RouteContext): Promise<Response> {
  const { projectId } = await context.params;
  return forwardBackendRequest(
    request,
    `/api/projects/${encodeURIComponent(projectId)}/transforms`,
    "application/json",
  );
}

export const GET = forward;
export const POST = forward;

import { forwardBackendRequest } from "@/shared/http/server";

interface RouteContext { params: Promise<{ projectId: string }> }

export async function POST(request: Request, context: RouteContext): Promise<Response> {
  const { projectId } = await context.params;
  return forwardBackendRequest(request, `/api/projects/${encodeURIComponent(projectId)}/batch-runs`, "application/json");
}

export async function GET(request: Request, context: RouteContext): Promise<Response> {
  const { projectId } = await context.params;
  return forwardBackendRequest(request, `/api/projects/${encodeURIComponent(projectId)}/batch-runs`, "application/json");
}

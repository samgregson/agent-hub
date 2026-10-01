import { forwardBackendRequest } from "@/shared/http/server";

interface RouteContext {
  params: Promise<{ projectId: string; runId: string }>;
}

export async function POST(
  request: Request,
  context: RouteContext,
): Promise<Response> {
  const { projectId, runId } = await context.params;
  return forwardBackendRequest(
    request,
    `/api/projects/${encodeURIComponent(projectId)}/transforms/runs/${encodeURIComponent(runId)}/save-dataset`,
    "application/json",
  );
}

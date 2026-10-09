import { forwardBackendRequest } from "@/shared/http/server";

interface RouteContext {
  params: Promise<{ projectId: string; definitionId: string }>;
}

export async function POST(
  request: Request,
  context: RouteContext,
): Promise<Response> {
  const { projectId, definitionId } = await context.params;
  return forwardBackendRequest(
    request,
    `/api/projects/${encodeURIComponent(projectId)}/transforms/${encodeURIComponent(definitionId)}/result-set-selection-plan`,
    "application/json",
  );
}

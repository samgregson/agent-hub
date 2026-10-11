import { forwardWorkflowRequest } from "@/modules/workflows/server";

interface RouteContext {
  params: Promise<{ projectId: string; workflowId: string; runId: string }>;
}

export async function GET(
  request: Request,
  context: RouteContext,
): Promise<Response> {
  const { projectId, workflowId, runId } = await context.params;
  return forwardWorkflowRequest(
    request,
    projectId,
    workflowId,
    `/runs/${encodeURIComponent(runId)}`,
  );
}

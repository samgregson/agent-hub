import { forwardWorkflowRequest } from "@/modules/workflows/server";

interface RouteContext {
  params: Promise<{
    projectId: string;
    workflowId: string;
    runId: string;
    nodeId: string;
  }>;
}

export async function GET(
  request: Request,
  context: RouteContext,
): Promise<Response> {
  const { projectId, workflowId, runId, nodeId } = await context.params;
  return forwardWorkflowRequest(
    request,
    projectId,
    workflowId,
    `/runs/${encodeURIComponent(runId)}/nodes/${encodeURIComponent(nodeId)}/app`,
  );
}

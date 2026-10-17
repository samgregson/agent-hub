import { forwardWorkflowRequest } from "@/modules/workflows/server";

interface RouteContext {
  params: Promise<{
    projectId: string;
    workflowId: string;
    runId: string;
    outputName: string;
  }>;
}

export async function POST(
  request: Request,
  context: RouteContext,
): Promise<Response> {
  const { projectId, workflowId, runId, outputName } = await context.params;
  return forwardWorkflowRequest(
    request,
    projectId,
    workflowId,
    `/runs/${encodeURIComponent(runId)}/outputs/${encodeURIComponent(outputName)}/artifact`,
  );
}

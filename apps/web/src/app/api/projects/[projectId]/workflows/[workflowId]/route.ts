import { forwardWorkflowRequest } from "@/modules/workflows/server";

interface RouteContext {
  params: Promise<{ projectId: string; workflowId: string }>;
}

export async function GET(
  request: Request,
  context: RouteContext,
): Promise<Response> {
  const { projectId, workflowId } = await context.params;
  return forwardWorkflowRequest(request, projectId, workflowId);
}

export async function PUT(
  request: Request,
  context: RouteContext,
): Promise<Response> {
  const { projectId, workflowId } = await context.params;
  return forwardWorkflowRequest(request, projectId, workflowId);
}

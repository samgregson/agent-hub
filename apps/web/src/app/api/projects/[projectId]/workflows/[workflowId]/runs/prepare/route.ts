import { forwardWorkflowRequest } from "@/modules/workflows/server";

interface RouteContext {
  params: Promise<{ projectId: string; workflowId: string }>;
}

export async function POST(
  request: Request,
  context: RouteContext,
): Promise<Response> {
  const { projectId, workflowId } = await context.params;
  return forwardWorkflowRequest(
    request,
    projectId,
    workflowId,
    "/runs/prepare",
  );
}

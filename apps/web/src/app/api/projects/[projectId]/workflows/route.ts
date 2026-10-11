import { forwardWorkflowRequest } from "@/modules/workflows/server";

interface RouteContext {
  params: Promise<{ projectId: string }>;
}

export async function GET(
  request: Request,
  context: RouteContext,
): Promise<Response> {
  const { projectId } = await context.params;
  return forwardWorkflowRequest(request, projectId);
}

export async function POST(
  request: Request,
  context: RouteContext,
): Promise<Response> {
  const { projectId } = await context.params;
  return forwardWorkflowRequest(request, projectId);
}

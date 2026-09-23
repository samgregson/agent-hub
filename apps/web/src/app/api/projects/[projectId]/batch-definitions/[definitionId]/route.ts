import { forwardDatasetRequest } from "@/modules/datasets/server";

interface RouteContext { params: Promise<{ definitionId: string; projectId: string }> }

async function forward(request: Request, context: RouteContext): Promise<Response> {
  const { definitionId, projectId } = await context.params;
  return forwardDatasetRequest(request, projectId, "batch-definitions", definitionId);
}

export const GET = forward;
export const PUT = forward;
export const DELETE = forward;

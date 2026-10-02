import { forwardDatasetRequest } from "@/modules/datasets/server";

interface RouteContext {
  params: Promise<{ datasetId: string; projectId: string }>;
}

async function forward(
  request: Request,
  context: RouteContext,
): Promise<Response> {
  const { datasetId, projectId } = await context.params;
  return forwardDatasetRequest(request, projectId, "datasets", datasetId);
}

export const GET = forward;
export const PUT = forward;
export const DELETE = forward;

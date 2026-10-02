import { forwardDatasetRequest } from "@/modules/datasets/server";

interface RouteContext {
  params: Promise<{ projectId: string }>;
}

export async function GET(
  request: Request,
  context: RouteContext,
): Promise<Response> {
  const { projectId } = await context.params;
  return forwardDatasetRequest(request, projectId, "datasets");
}

export async function POST(
  request: Request,
  context: RouteContext,
): Promise<Response> {
  const { projectId } = await context.params;
  return forwardDatasetRequest(request, projectId, "datasets");
}

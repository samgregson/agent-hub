import { forwardProjectRequest } from "@/modules/workspace/server";

interface RouteContext {
  params: Promise<{ projectId: string }>;
}

function threadPath(projectId: string): string {
  return `/${encodeURIComponent(projectId)}/threads`;
}

export async function GET(
  request: Request,
  context: RouteContext,
): Promise<Response> {
  const { projectId } = await context.params;
  return forwardProjectRequest(request, threadPath(projectId));
}

export async function POST(
  request: Request,
  context: RouteContext,
): Promise<Response> {
  const { projectId } = await context.params;
  return forwardProjectRequest(request, threadPath(projectId));
}

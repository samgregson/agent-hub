import { forwardProjectRequest } from "@/modules/workspace/server";

interface RouteContext {
  params: Promise<{ projectId: string; threadId: string }>;
}

function threadPath(projectId: string, threadId: string): string {
  return `/${encodeURIComponent(projectId)}/threads/${encodeURIComponent(threadId)}`;
}

export async function PATCH(
  request: Request,
  context: RouteContext,
): Promise<Response> {
  const { projectId, threadId } = await context.params;
  return forwardProjectRequest(request, threadPath(projectId, threadId));
}

export async function DELETE(
  request: Request,
  context: RouteContext,
): Promise<Response> {
  const { projectId, threadId } = await context.params;
  return forwardProjectRequest(request, threadPath(projectId, threadId));
}

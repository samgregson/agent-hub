import { forwardAgentRequest } from "@/modules/agent-ui/index.server";

interface RouteContext {
  params: Promise<{ projectId: string; threadId: string }>;
}

export async function GET(
  request: Request,
  context: RouteContext,
): Promise<Response> {
  const { projectId, threadId } = await context.params;
  return forwardAgentRequest(request, projectId, threadId, "runs");
}

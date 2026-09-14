import { forwardAgentRequest } from "@/modules/agent-ui/server";

interface RouteContext {
  params: Promise<{ projectId: string; threadId: string }>;
}

export async function POST(
  request: Request,
  context: RouteContext,
): Promise<Response> {
  const { projectId, threadId } = await context.params;
  return forwardAgentRequest(request, projectId, threadId, "agent");
}

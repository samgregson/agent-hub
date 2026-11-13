import { forwardProjectFileRequest } from "@/modules/project-files/server";

export async function GET(
  request: Request,
  context: { params: Promise<{ projectId: string }> },
): Promise<Response> {
  const { projectId } = await context.params;
  return forwardProjectFileRequest(request, projectId, "/download");
}

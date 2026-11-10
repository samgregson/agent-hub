import { forwardProjectFileRequest } from "@/modules/project-files/server";
interface Context {
  params: Promise<{ projectId: string }>;
}
export async function GET(request: Request, context: Context) {
  const { projectId } = await context.params;
  return forwardProjectFileRequest(request, projectId, "/documents");
}
export const POST = GET;

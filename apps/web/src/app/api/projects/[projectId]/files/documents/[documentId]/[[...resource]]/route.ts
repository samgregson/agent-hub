import { forwardProjectFileRequest } from "@/modules/project-files/server";
interface Context {
  params: Promise<{
    projectId: string;
    documentId: string;
    resource?: string[];
  }>;
}
export async function GET(request: Request, context: Context) {
  const { projectId, documentId, resource = [] } = await context.params;
  return forwardProjectFileRequest(
    request,
    projectId,
    `/documents/${encodeURIComponent(documentId)}${resource.length ? "/" + resource.map(encodeURIComponent).join("/") : ""}`,
  );
}
export const DELETE = GET;

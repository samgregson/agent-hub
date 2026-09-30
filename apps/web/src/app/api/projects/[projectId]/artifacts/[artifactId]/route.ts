import { forwardArtifactRequest } from "@/modules/artifact-view-host/server";

interface RouteContext {
  params: Promise<{ artifactId: string; projectId: string }>;
}

export async function GET(
  request: Request,
  context: RouteContext,
): Promise<Response> {
  const { artifactId, projectId } = await context.params;
  return forwardArtifactRequest(
    request,
    projectId,
    `/${encodeURIComponent(artifactId)}`,
  );
}

export async function DELETE(
  request: Request,
  context: RouteContext,
): Promise<Response> {
  const { artifactId, projectId } = await context.params;
  return forwardArtifactRequest(
    request,
    projectId,
    `/${encodeURIComponent(artifactId)}`,
  );
}

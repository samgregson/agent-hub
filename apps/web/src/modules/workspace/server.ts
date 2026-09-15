import "server-only";

import { forwardBackendRequest } from "@/shared/http/server";

export function forwardProjectRequest(
  request: Request,
  path = "",
): Promise<Response> {
  return forwardBackendRequest(
    request,
    `/api/projects${path}`,
    "application/json",
  );
}

export async function forwardProjectForm(request: Request): Promise<Response> {
  const formData = await request.formData();
  const submittedName = formData.get("name");
  const name = typeof submittedName === "string" ? submittedName.trim() : "";
  if (!name) {
    return Response.json(
      { detail: "A Project name is required." },
      { status: 400 },
    );
  }

  const headers = new Headers(request.headers);
  headers.set("accept", "application/json");
  headers.set("content-type", "application/json");
  return forwardProjectRequest(
    new Request(request.url, {
      body: JSON.stringify({ name }),
      headers,
      method: "POST",
    }),
  );
}

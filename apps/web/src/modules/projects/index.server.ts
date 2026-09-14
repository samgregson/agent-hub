import "server-only";

import { loadServerConfig } from "@/shared/config/server";

function backendHeaders(request: Request): Headers {
  const { identityHeader } = loadServerConfig();
  const headers = new Headers({ accept: "application/json" });
  const contentType = request.headers.get("content-type");
  const platformSubject = request.headers.get(identityHeader);

  if (contentType) headers.set("content-type", contentType);
  if (platformSubject) headers.set(identityHeader, platformSubject);
  return headers;
}

export async function forwardProjectRequest(
  request: Request,
  path = "",
): Promise<Response> {
  const { apiUrl } = loadServerConfig();
  const response = await fetch(`${apiUrl}/api/projects${path}`, {
    body: request.method === "GET" ? undefined : await request.text(),
    cache: "no-store",
    headers: backendHeaders(request),
    method: request.method,
  });

  return new Response(response.body, {
    headers: {
      "content-type":
        response.headers.get("content-type") ?? "application/json",
    },
    status: response.status,
  });
}

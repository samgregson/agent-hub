import "server-only";

import { loadServerConfig } from "@/shared/config/server";

function backendHeaders(request: Request): Headers {
  const { identityHeader } = loadServerConfig();
  const headers = new Headers();
  for (const name of ["accept", "content-type"]) {
    const value = request.headers.get(name);
    if (value) headers.set(name, value);
  }
  const platformSubject = request.headers.get(identityHeader);
  if (platformSubject) headers.set(identityHeader, platformSubject);
  return headers;
}

export async function forwardAgentRequest(
  request: Request,
  projectId: string,
  threadId: string,
  suffix: "agent" | "history" | "runs",
): Promise<Response> {
  const { apiUrl } = loadServerConfig();
  const response = await fetch(
    `${apiUrl}/api/projects/${encodeURIComponent(projectId)}/threads/${encodeURIComponent(threadId)}/${suffix}`,
    {
      body: request.method === "GET" ? undefined : request.body,
      cache: "no-store",
      duplex: "half",
      headers: backendHeaders(request),
      method: request.method,
    } as RequestInit & { duplex: "half" },
  );

  const headers = new Headers();
  for (const name of ["cache-control", "content-type"]) {
    const value = response.headers.get(name);
    if (value) headers.set(name, value);
  }
  return new Response(response.body, { headers, status: response.status });
}

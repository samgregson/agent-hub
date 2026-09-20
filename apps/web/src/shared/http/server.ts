import "server-only";

import { loadServerConfig } from "@/shared/config/server";

export async function forwardBackendRequest(
  request: Request,
  backendPath: string,
  defaultAccept?: string,
): Promise<Response> {
  const { apiUrl, identityHeader } = loadServerConfig();
  const headers = new Headers();
  const accept = request.headers.get("accept") ?? defaultAccept;
  const contentType = request.headers.get("content-type");
  const platformSubject = request.headers.get(identityHeader);

  if (accept) headers.set("accept", accept);
  if (contentType) headers.set("content-type", contentType);
  if (platformSubject) headers.set(identityHeader, platformSubject);

  const response = await fetch(`${apiUrl}${backendPath}`, {
    body: request.method === "GET" ? undefined : request.body,
    cache: "no-store",
    duplex: "half",
    headers,
    method: request.method,
    signal: request.signal,
  } as RequestInit & { duplex: "half" });

  const responseHeaders = new Headers();
  for (const name of [
    "cache-control",
    "content-security-policy",
    "content-type",
    "referrer-policy",
    "x-content-type-options",
  ]) {
    const value = response.headers.get(name);
    if (value) responseHeaders.set(name, value);
  }
  return new Response(response.body, {
    headers: responseHeaders,
    status: response.status,
  });
}

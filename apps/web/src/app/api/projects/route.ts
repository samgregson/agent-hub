import {
  forwardProjectForm,
  forwardProjectRequest,
} from "@/modules/workspace/server";

export async function GET(request: Request): Promise<Response> {
  return forwardProjectRequest(request);
}

export async function POST(request: Request): Promise<Response> {
  if (
    request.headers
      .get("content-type")
      ?.startsWith("application/x-www-form-urlencoded")
  ) {
    const response = await forwardProjectForm(request);
    if (!response.ok) return response;
    return new Response(null, {
      headers: { location: new URL("/", request.url).toString() },
      status: 303,
    });
  }
  return forwardProjectRequest(request);
}

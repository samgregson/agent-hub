import { forwardProjectRequest } from "@/modules/workspace/server";

export async function GET(request: Request): Promise<Response> {
  return forwardProjectRequest(request);
}

export async function POST(request: Request): Promise<Response> {
  return forwardProjectRequest(request);
}

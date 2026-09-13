import { loadServerConfig } from "@/lib/config";

export async function GET() {
  const { apiUrl } = loadServerConfig();

  try {
    const response = await fetch(`${apiUrl}/health/ready`, {
      cache: "no-store",
      signal: AbortSignal.timeout(2_000),
    });
    const status = response.ok ? 200 : 503;
    return Response.json(
      { status: response.ok ? "ready" : "unavailable" },
      { status },
    );
  } catch {
    return Response.json({ status: "unavailable" }, { status: 503 });
  }
}

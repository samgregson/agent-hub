import "server-only";

import { z } from "zod";

const serverConfigSchema = z.object({
  apiUrl: z.url(),
  identityHeader: z.string().min(1),
});

export type ServerConfig = z.infer<typeof serverConfigSchema>;

export function loadServerConfig(
  environment: NodeJS.ProcessEnv = process.env,
): ServerConfig {
  return serverConfigSchema.parse({
    apiUrl: environment.AGENT_HUB_API_URL ?? "http://localhost:8000",
    identityHeader:
      environment.AGENT_HUB_IDENTITY_HEADER ?? "X-Agent-Hub-Subject",
  });
}

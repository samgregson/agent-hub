import { z } from "zod";

const pluginSelectionSchema = z.object({
  enabled: z.boolean(),
  id: z.string().min(1),
  name: z.string().min(1),
  tools: z.array(
    z.object({
      name: z.string().min(1),
      readOnly: z.boolean(),
    }),
  ),
  version: z.string().min(1),
});

const pluginSelectionsSchema = z.array(pluginSelectionSchema);

async function pluginRequest(
  input: RequestInfo | URL,
  init?: RequestInit,
): Promise<Response> {
  const response = await fetch(input, init);
  if (!response.ok) {
    throw new Error(`Plugin request failed with status ${response.status}`);
  }
  return response;
}

export async function listPluginSelections(
  projectId: string,
): Promise<PluginSelection[]> {
  const response = await pluginRequest(
    `/api/projects/${encodeURIComponent(projectId)}/plugins`,
  );
  return pluginSelectionsSchema.parse(await response.json());
}

export async function setPluginEnabled(
  projectId: string,
  pluginId: string,
  enabled: boolean,
): Promise<void> {
  await pluginRequest(
    `/api/projects/${encodeURIComponent(projectId)}/plugins/${encodeURIComponent(pluginId)}`,
    { method: enabled ? "PUT" : "DELETE" },
  );
}

export type PluginSelection = z.infer<typeof pluginSelectionSchema>;

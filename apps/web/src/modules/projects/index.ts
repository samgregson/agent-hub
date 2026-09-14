import { z } from "zod";

import type { Project } from "@/contracts";

const projectSchema = z.object({
  id: z.string().min(1),
  name: z.string().min(1).max(120),
  createdAt: z.iso.datetime(),
  updatedAt: z.iso.datetime(),
});

const projectListSchema = z.array(projectSchema);

async function projectRequest(
  input: RequestInfo | URL,
  init?: RequestInit,
): Promise<Response> {
  const response = await fetch(input, init);
  if (!response.ok) {
    throw new Error(`Project request failed with status ${response.status}`);
  }
  return response;
}

export async function listProjects(): Promise<Project[]> {
  const response = await projectRequest("/api/projects");
  return projectListSchema.parse(await response.json());
}

export async function createProject(name: string): Promise<Project> {
  const response = await projectRequest("/api/projects", {
    body: JSON.stringify({ name }),
    headers: { "content-type": "application/json" },
    method: "POST",
  });
  return projectSchema.parse(await response.json());
}

export type { Project };

import { z } from "zod";

import type { Project, Thread } from "@/contracts";

const projectSchema = z.object({
  id: z.string().min(1),
  name: z.string().min(1).max(120),
  createdAt: z.iso.datetime(),
  updatedAt: z.iso.datetime(),
});
const projectListSchema = z.array(projectSchema);
const threadSchema = z.object({
  id: z.string().min(1),
  projectId: z.string().min(1),
  title: z.string().min(1).max(160),
  createdAt: z.iso.datetime(),
  updatedAt: z.iso.datetime(),
});
const threadListSchema = z.array(threadSchema);

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

export async function listThreads(projectId: string): Promise<Thread[]> {
  const response = await projectRequest(
    `/api/projects/${encodeURIComponent(projectId)}/threads`,
  );
  return threadListSchema.parse(await response.json());
}

export async function createThread(
  projectId: string,
  title: string,
): Promise<Thread> {
  const response = await projectRequest(
    `/api/projects/${encodeURIComponent(projectId)}/threads`,
    {
      body: JSON.stringify({ title }),
      headers: { "content-type": "application/json" },
      method: "POST",
    },
  );
  return threadSchema.parse(await response.json());
}

export async function renameThread(
  projectId: string,
  threadId: string,
  title: string,
): Promise<Thread> {
  const response = await projectRequest(
    `/api/projects/${encodeURIComponent(projectId)}/threads/${encodeURIComponent(threadId)}`,
    {
      body: JSON.stringify({ title }),
      headers: { "content-type": "application/json" },
      method: "PATCH",
    },
  );
  return threadSchema.parse(await response.json());
}

export async function deleteThread(
  projectId: string,
  threadId: string,
): Promise<void> {
  await projectRequest(
    `/api/projects/${encodeURIComponent(projectId)}/threads/${encodeURIComponent(threadId)}`,
    { method: "DELETE" },
  );
}

export type { Project, Thread };

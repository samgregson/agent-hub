/* Generated from packages/contracts/schema/contracts.schema.json. Do not edit. */

/**
 * An opaque stable Agent Hub identifier. Clients must not parse it.
 */
export type EntityId = string;
export type AgentRunStatus = "queued" | "running" | "interrupted" | "cancelling" | "cancelled" | "succeeded" | "failed";

/**
 * Registry of the language-neutral Agent Hub foundation contracts.
 */
export interface FoundationContracts {
  agentRun?: AgentRun;
  artifactDocument?: ArtifactDocument;
  error?: ErrorEnvelope;
  projectFilePreview?: ProjectFilePreview;
  projectFileCatalog?: ProjectFileCatalog;
  scratchFilePreview?: ScratchFilePreview;
  project?: Project;
  thread?: Thread;
}
export interface AgentRun {
  id: EntityId;
  threadId: EntityId;
  status: AgentRunStatus;
  createdAt: string;
  updatedAt: string;
  error?: ErrorEnvelope;
}
export interface ErrorEnvelope {
  code: string;
  message: string;
  requestId: EntityId;
  retryable: boolean;
  details?: {
    [k: string]: unknown;
  };
}
export interface ArtifactDocument {
  artifact: ArtifactEnvelope;
  payload: {
    [k: string]: unknown;
  };
}
export interface ArtifactEnvelope {
  id: EntityId;
  type: string;
  documentVersion: number;
  title: string;
  summary?: string;
  schema: ArtifactSchemaBinding;
  plugin: ArtifactPluginBinding;
  provenance: ArtifactProvenance;
  relations: ArtifactRelation[];
}
export interface ArtifactSchemaBinding {
  id: string;
  version: string;
}
export interface ArtifactPluginBinding {
  id: string;
  version: string;
}
export interface ArtifactProvenance {
  createdByThreadId: EntityId;
  createdByRunId: EntityId;
  lastChangedByThreadId: EntityId;
  lastChangedByRunId: EntityId;
}
export interface ArtifactRelation {
  type: string;
  targetArtifactId: EntityId;
}
export interface ProjectFilePreview {
  path: string;
  content: string;
  version: number;
}
export interface ProjectFileCatalog {
  files: ProjectFileSummary[];
}
export interface ProjectFileSummary {
  path: string;
  version: number;
  updatedAt: string;
}
export interface ScratchFilePreview {
  path: string;
  content: string;
}
export interface Project {
  id: EntityId;
  name: string;
  createdAt: string;
  updatedAt: string;
}
export interface Thread {
  id: EntityId;
  projectId: EntityId;
  title: string;
  createdAt: string;
  updatedAt: string;
}

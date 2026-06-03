import { apiFetch, jsonBody } from "./client";
import type { ArtifactSurface, ArtifactTreeNode, ArtifactView } from "./types";

export function getArtifactTree(taskId: string, surface: ArtifactSurface, query = ""): Promise<ArtifactTreeNode[]> {
  const params = new URLSearchParams({ surface });
  if (query.trim()) {
    params.set("q", query.trim());
  }
  return apiFetch<ArtifactTreeNode[]>(`/api/tasks/${encodeURIComponent(taskId)}/artifact-tree?${params.toString()}`);
}

export function getArtifactView(artifactId: string): Promise<ArtifactView> {
  return apiFetch<ArtifactView>(`/api/artifacts/${encodeURIComponent(artifactId)}/view`);
}

export function getArtifactTechnical(artifactId: string): Promise<Record<string, unknown>> {
  return apiFetch<Record<string, unknown>>(`/api/artifacts/${encodeURIComponent(artifactId)}/technical`);
}

export function saveArtifactText(artifactId: string, text: string): Promise<Record<string, unknown>> {
  return apiFetch<Record<string, unknown>>(`/api/artifacts/${encodeURIComponent(artifactId)}/save`, {
    method: "POST",
    body: jsonBody({ text })
  });
}

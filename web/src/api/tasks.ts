import { apiFetch, jsonBody } from "./client";
import type { CreateTaskRequest, DeleteTaskPreview, TaskProgress, TaskSummary, WebActionResult } from "./types";

export function getTasks(): Promise<TaskSummary[]> {
  return apiFetch<TaskSummary[]>("/api/tasks");
}

export function createTask(request: CreateTaskRequest): Promise<TaskSummary> {
  return apiFetch<TaskSummary>("/api/tasks", {
    method: "POST",
    body: jsonBody(request)
  });
}

export function getTaskStatus(taskId: string): Promise<TaskProgress> {
  return apiFetch<TaskProgress>(`/api/tasks/${encodeURIComponent(taskId)}/status`);
}

export function selectTask(taskId: string): Promise<WebActionResult> {
  return apiFetch<WebActionResult>(`/api/tasks/${encodeURIComponent(taskId)}/actions`, {
    method: "POST",
    body: jsonBody({ action: "select_task", payload: { task_id: taskId } })
  });
}

export function resetCloseRead(taskId: string): Promise<WebActionResult> {
  return apiFetch<WebActionResult>(`/api/tasks/${encodeURIComponent(taskId)}/reset-close-read`, {
    method: "POST"
  });
}

export function deleteTask(taskId: string, options: { confirm?: boolean; includeRuns?: boolean } = {}): Promise<DeleteTaskPreview> {
  const params = new URLSearchParams({
    confirm: String(Boolean(options.confirm)),
    include_runs: String(Boolean(options.includeRuns))
  });
  return apiFetch<DeleteTaskPreview>(`/api/tasks/${encodeURIComponent(taskId)}?${params.toString()}`, {
    method: "DELETE"
  });
}

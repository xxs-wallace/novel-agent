import { apiFetch, jsonBody } from "./client";
import type { CommandRequest, WebActionRequest, WebActionResult } from "./types";

export function postAction(taskId: string, request: WebActionRequest): Promise<WebActionResult> {
  return apiFetch<WebActionResult>(`/api/tasks/${encodeURIComponent(taskId)}/actions`, {
    method: "POST",
    body: jsonBody({
      action: request.action,
      payload: request.payload ?? {}
    })
  });
}

export function postCommand(taskId: string, request: CommandRequest): Promise<WebActionResult> {
  return apiFetch<WebActionResult>(`/api/tasks/${encodeURIComponent(taskId)}/commands`, {
    method: "POST",
    body: jsonBody({
      command: request.command,
      payload: request.payload ?? {}
    })
  });
}

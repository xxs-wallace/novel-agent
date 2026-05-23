import { apiFetch, jsonBody } from "./client";
import type { ConversationMessage, MessageCreateRequest } from "./types";

export const ANALYZER_MESSAGE_TIMEOUT_MS = 600_000;

export function getMessages(taskId: string): Promise<ConversationMessage[]> {
  return apiFetch<ConversationMessage[]>(`/api/tasks/${encodeURIComponent(taskId)}/messages`);
}

export function postMessage(
  taskId: string,
  request: MessageCreateRequest,
  options: { timeoutMs?: number; timeoutMessage?: string } = {}
): Promise<ConversationMessage> {
  return apiFetch<ConversationMessage>(`/api/tasks/${encodeURIComponent(taskId)}/messages`, {
    method: "POST",
    timeoutMs: options.timeoutMs,
    timeoutMessage: options.timeoutMessage,
    body: jsonBody({
      content: request.content,
      payload: request.payload ?? {}
    })
  });
}

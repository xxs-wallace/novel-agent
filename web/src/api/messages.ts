import { apiFetch, jsonBody } from "./client";
import type { ConversationMessage, MessageCreateRequest } from "./types";

export function getMessages(taskId: string): Promise<ConversationMessage[]> {
  return apiFetch<ConversationMessage[]>(`/api/tasks/${encodeURIComponent(taskId)}/messages`);
}

export function postMessage(taskId: string, request: MessageCreateRequest): Promise<ConversationMessage> {
  return apiFetch<ConversationMessage>(`/api/tasks/${encodeURIComponent(taskId)}/messages`, {
    method: "POST",
    body: jsonBody({
      content: request.content,
      payload: request.payload ?? {}
    })
  });
}

import { apiFetch, jsonBody } from "./client";
import type {
  AnalyzerSessionCreateRequest,
  AnalyzerSessionSummary,
  AnalyzerTurnRollbackPreview,
  ConversationMessage,
  MessageCreateRequest
} from "./types";

export const ANALYZER_MESSAGE_TIMEOUT_MS = 600_000;

export function getMessages(taskId: string, analyzerSessionId = ""): Promise<ConversationMessage[]> {
  const query = analyzerSessionId ? `?analyzer_session_id=${encodeURIComponent(analyzerSessionId)}` : "";
  return apiFetch<ConversationMessage[]>(`/api/tasks/${encodeURIComponent(taskId)}/messages${query}`);
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

export function getAnalyzerSessions(taskId: string): Promise<AnalyzerSessionSummary[]> {
  return apiFetch<AnalyzerSessionSummary[]>(`/api/tasks/${encodeURIComponent(taskId)}/analyzer-sessions`);
}

export function createAnalyzerSession(taskId: string, request: AnalyzerSessionCreateRequest): Promise<AnalyzerSessionSummary> {
  return apiFetch<AnalyzerSessionSummary>(`/api/tasks/${encodeURIComponent(taskId)}/analyzer-sessions`, {
    method: "POST",
    body: jsonBody(request)
  });
}

export function rollbackLatestAnalyzerTurn(
  taskId: string,
  sessionId: string,
  options: { confirm?: boolean } = {}
): Promise<AnalyzerTurnRollbackPreview> {
  const params = new URLSearchParams();
  if (options.confirm) {
    params.set("confirm", "true");
  }
  const query = params.toString() ? `?${params.toString()}` : "";
  return apiFetch<AnalyzerTurnRollbackPreview>(
    `/api/tasks/${encodeURIComponent(taskId)}/analyzer-sessions/${encodeURIComponent(sessionId)}/latest-turn${query}`,
    { method: "DELETE" }
  );
}

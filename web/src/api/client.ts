import type { ApiError } from "./types";

const API_BASE_URL = import.meta.env.VITE_API_BASE_URL ?? "";

interface ApiFetchInit extends RequestInit {
  timeoutMs?: number;
  timeoutMessage?: string;
}

export function apiUrl(path: string): string {
  if (/^https?:\/\//.test(path)) {
    return path;
  }
  return `${API_BASE_URL}${path}`;
}

export async function apiFetch<T>(path: string, init: ApiFetchInit = {}): Promise<T> {
  const { timeoutMs, timeoutMessage, signal: callerSignal, ...fetchInit } = init;
  const headers = new Headers(fetchInit.headers);
  if (!headers.has("Content-Type") && fetchInit.body) {
    headers.set("Content-Type", "application/json");
  }
  headers.set("Accept", "application/json");

  const controller = timeoutMs ? new AbortController() : null;
  let timeoutId: ReturnType<typeof setTimeout> | null = null;
  let timedOut = false;
  const abortFromCaller = () => controller?.abort(callerSignal?.reason);
  if (controller && callerSignal) {
    if (callerSignal.aborted) {
      controller.abort(callerSignal.reason);
    } else {
      callerSignal.addEventListener("abort", abortFromCaller, { once: true });
    }
  }
  if (controller && timeoutMs) {
    timeoutId = setTimeout(() => {
      timedOut = true;
      controller.abort(new DOMException("Request timed out", "TimeoutError"));
    }, timeoutMs);
  }

  let response: Response;
  try {
    response = await fetch(apiUrl(path), {
      ...fetchInit,
      headers,
      signal: controller?.signal ?? callerSignal
    });
  } catch (error) {
    if (timedOut) {
      throw new Error(timeoutMessage || "请求超时，请稍后重试。");
    }
    throw error;
  } finally {
    if (timeoutId) {
      clearTimeout(timeoutId);
    }
    if (controller && callerSignal) {
      callerSignal.removeEventListener("abort", abortFromCaller);
    }
  }

  if (!response.ok) {
    let message = response.statusText;
    try {
      const error = (await response.json()) as ApiError;
      message = error.recovery_suggestion ? `${error.message} ${error.recovery_suggestion}` : error.message;
    } catch {
      message = await response.text();
    }
    throw new Error(message || `Request failed: ${response.status}`);
  }

  if (response.status === 204) {
    return undefined as T;
  }

  return (await response.json()) as T;
}

export function jsonBody(payload: unknown): string {
  return JSON.stringify(payload);
}

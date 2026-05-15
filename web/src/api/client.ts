import type { ApiError } from "./types";

const API_BASE_URL = import.meta.env.VITE_API_BASE_URL ?? "";

export function apiUrl(path: string): string {
  if (/^https?:\/\//.test(path)) {
    return path;
  }
  return `${API_BASE_URL}${path}`;
}

export async function apiFetch<T>(path: string, init: RequestInit = {}): Promise<T> {
  const headers = new Headers(init.headers);
  if (!headers.has("Content-Type") && init.body) {
    headers.set("Content-Type", "application/json");
  }
  headers.set("Accept", "application/json");

  const response = await fetch(apiUrl(path), {
    ...init,
    headers
  });

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

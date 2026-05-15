import { apiFetch, apiUrl } from "./client";
import type { JobEventView, JobSummary } from "./types";

const SSE_EVENT_TYPES = ["queued", "running", "progress", "succeeded", "failed", "error", "cancelled"];

export function getJob(jobId: string): Promise<JobSummary> {
  return apiFetch<JobSummary>(`/api/jobs/${encodeURIComponent(jobId)}`);
}

export function getJobEventsReplay(jobId: string): Promise<JobEventView[]> {
  return apiFetch<JobEventView[]>(`/api/jobs/${encodeURIComponent(jobId)}/events/replay`);
}

export function streamJobEvents(
  jobId: string,
  onEvent: (event: JobEventView) => void,
  onError?: (error: unknown) => void
): () => void {
  let cancelled = false;
  getJobEventsReplay(jobId)
    .then((events) => {
      if (!cancelled) {
        events.forEach(onEvent);
      }
    })
    .catch((error) => {
      if (!cancelled) {
        onError?.(error);
      }
    });

  if (typeof EventSource === "undefined") {
    return () => {
      cancelled = true;
    };
  }

  const eventSource = new EventSource(apiUrl(`/api/jobs/${encodeURIComponent(jobId)}/events`));
  const parseEvent = (event: MessageEvent<string>) => {
    try {
      onEvent(JSON.parse(event.data) as JobEventView);
    } catch (error) {
      onError?.(error);
    }
  };
  eventSource.onmessage = parseEvent;
  SSE_EVENT_TYPES.forEach((type) => eventSource.addEventListener(type, parseEvent as EventListener));
  eventSource.onerror = (error) => onError?.(error);
  return () => {
    cancelled = true;
    eventSource.close();
  };
}

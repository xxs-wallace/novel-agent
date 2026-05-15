export type JobStatus = "queued" | "running" | "succeeded" | "failed" | "cancelled";
export type MessageRole = "user" | "assistant" | "system" | "job" | "error";
export type ArtifactSurface = "close-read" | "writer";

export interface ApiError {
  code: string;
  message: string;
  recovery_suggestion?: string;
}

export interface TaskProgress {
  task_id: string;
  flow: string;
  step: string;
  next_action: string;
  message: string;
  read_progress: Record<string, number>;
  close_read_progress: Record<string, number>;
  modeling_ready: Record<string, boolean>;
  counts: Record<string, number>;
  technical_available: boolean;
}

export interface TaskSummary {
  task_id: string;
  source_path: string;
  documents_count: number;
  chapters_count: number;
  read_completed: number;
  close_read_completed: number;
  total_documents: number;
  close_read_done: boolean;
  active: boolean;
  progress: TaskProgress | null;
  active_job?: JobSummary | null;
}

export interface DecisionAction {
  action: string;
  label: string;
  payload?: Record<string, unknown>;
  description?: string;
  variant?: "primary" | "secondary" | "danger";
  requires_input?: boolean;
}

export interface DecisionCardModel {
  card_id: string;
  title: string;
  body: string;
  actions: DecisionAction[];
}

export interface ConversationMessage {
  message_id: string;
  task_id: string;
  role: MessageRole;
  content: string;
  payload: Record<string, unknown>;
  decision_cards: DecisionCardModel[];
  created_at: string;
}

export interface CreateTaskRequest {
  task_id: string;
  source_path?: string;
}

export interface MessageCreateRequest {
  content: string;
  payload?: Record<string, unknown>;
}

export interface CommandRequest {
  command: string;
  payload?: Record<string, unknown>;
}

export interface WebActionRequest {
  action: string;
  payload?: Record<string, unknown>;
}

export interface JobSummary {
  job_id: string;
  task_id: string;
  type: string;
  status: JobStatus;
  message: string;
  cancel_requested: boolean;
  created_at: string;
  updated_at: string;
  events_url: string;
}

export interface JobEventView {
  event_id: string;
  job_id: string;
  kind: string;
  message: string;
  payload: Record<string, unknown>;
  created_at: string;
}

export interface WebActionResult {
  action: string;
  task_id: string;
  status: string;
  message: string;
  payload: Record<string, unknown>;
  progress: TaskProgress | null;
  job: JobSummary | null;
  decision_cards: DecisionCardModel[];
  technical_details: Record<string, unknown>;
}

export interface ArtifactTreeNode {
  id: string;
  label: string;
  kind: string;
  surface: ArtifactSurface;
  badge: string;
  children: ArtifactTreeNode[];
  has_lazy_children: boolean;
}

export interface ArtifactSection {
  title: string;
  body: string;
}

export interface ArtifactCard {
  title: string;
  subtitle: string;
  body: string;
  fields: Record<string, string>;
}

export interface ArtifactTable {
  title: string;
  columns: string[];
  rows: Record<string, string>[];
}

export interface ArtifactView {
  artifact_id: string;
  title: string;
  kind: string;
  sections: ArtifactSection[];
  cards: ArtifactCard[];
  tables: ArtifactTable[];
  markdown: string;
  technical_available: boolean;
}

export interface DeleteTaskPreview {
  book_id?: string;
  task_id?: string;
  confirm_required?: boolean;
  would_delete?: Record<string, unknown>;
  deleted?: Record<string, unknown>;
  message?: string;
}

from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, Field


JobStatus = Literal["queued", "running", "succeeded", "failed", "cancelled"]
MessageRole = Literal["user", "assistant", "system", "job", "error"]
ArtifactSurface = Literal["close-read", "writer"]


class ApiError(BaseModel):
    code: str
    message: str
    recovery_suggestion: str = ""


class TaskProgress(BaseModel):
    task_id: str
    flow: str
    step: str
    next_action: str = ""
    message: str = ""
    read_progress: dict[str, int] = Field(default_factory=dict)
    close_read_progress: dict[str, int] = Field(default_factory=dict)
    modeling_ready: dict[str, bool] = Field(default_factory=dict)
    counts: dict[str, int] = Field(default_factory=dict)
    technical_available: bool = False


class TaskSummary(BaseModel):
    task_id: str
    source_path: str = ""
    documents_count: int = 0
    chapters_count: int = 0
    read_completed: int = 0
    close_read_completed: int = 0
    total_documents: int = 0
    close_read_done: bool = False
    active: bool = False
    progress: TaskProgress | None = None
    active_job: JobSummary | None = None


class DecisionCard(BaseModel):
    card_id: str
    title: str
    body: str = ""
    actions: list[dict[str, Any]] = Field(default_factory=list)


class WriterQuestion(BaseModel):
    question_id: str
    prompt: str
    required: bool = True
    hint: str = ""
    gap_id: str = ""
    risk_level: str = ""


class WriterQuestionSet(BaseModel):
    schema_version: str = "1.0"
    question_set_id: str
    run_id: str
    stage: str
    status: str = "pending"
    questions: list[WriterQuestion]
    source_artifact_id: str = ""
    artifact_path: str = ""
    actions: dict[str, str] = Field(default_factory=dict)
    submit_action: str = "submit_outline_research_answers"
    defer_action: str = "defer_outline_research_answers"
    technical_available: bool = True


class WriterQuestionAnswer(BaseModel):
    question_id: str
    answer_text: str


class WriterQuestionAnswerMessage(BaseModel):
    channel: Literal["writer_question_answer"] = "writer_question_answer"
    run_id: str
    question_set_id: str
    answer_text: str
    user_answers: list[WriterQuestionAnswer] = Field(default_factory=list)


class WriterReviewAction(BaseModel):
    action: str
    label: str
    payload: dict[str, Any] = Field(default_factory=dict)
    description: str = ""
    variant: Literal["primary", "secondary", "danger"] = "secondary"
    requires_input: bool = False
    input_role: str = ""


class WriterArtifactReview(BaseModel):
    schema_version: str = "1.0"
    run_id: str
    review_id: str
    artifact_kind: str
    artifact_id: str = ""
    title: str
    summary: str = ""
    next_prompt: str = ""
    detail_artifact_id: str = ""
    actions: list[WriterReviewAction] = Field(default_factory=list)
    technical_available: bool = True
    technical_details: dict[str, Any] = Field(default_factory=dict)


class WriterDraftReview(BaseModel):
    schema_version: str = "1.0"
    run_id: str
    review_id: str
    chapter_id: str
    draft_id: str
    title: str = "章节草稿验收"
    preview: str = ""
    word_count: int = 0
    target_word_count: int | None = None
    continuity_summary: str = ""
    detail_artifact_id: str = ""
    actions: list[WriterReviewAction] = Field(default_factory=list)
    technical_available: bool = True
    technical_details: dict[str, Any] = Field(default_factory=dict)


class ConversationMessage(BaseModel):
    message_id: str
    task_id: str
    role: MessageRole
    content: str
    payload: dict[str, Any] = Field(default_factory=dict)
    writer_question_set: WriterQuestionSet | None = None
    writer_artifact_review: WriterArtifactReview | None = None
    writer_draft_review: WriterDraftReview | None = None
    decision_cards: list[DecisionCard] = Field(default_factory=list)
    created_at: datetime


class WebActionRequest(BaseModel):
    action: str
    payload: dict[str, Any] = Field(default_factory=dict)


class JobSummary(BaseModel):
    job_id: str
    task_id: str
    type: str
    status: JobStatus
    message: str = ""
    cancel_requested: bool = False
    created_at: datetime
    updated_at: datetime
    events_url: str = ""


class JobEventView(BaseModel):
    event_id: str
    job_id: str
    kind: str
    message: str
    payload: dict[str, Any] = Field(default_factory=dict)
    created_at: datetime


class WebActionResult(BaseModel):
    action: str
    task_id: str
    status: str = "ok"
    message: str = ""
    payload: dict[str, Any] = Field(default_factory=dict)
    progress: TaskProgress | None = None
    job: JobSummary | None = None
    decision_cards: list[DecisionCard] = Field(default_factory=list)
    technical_details: dict[str, Any] = Field(default_factory=dict)


class ArtifactTreeNode(BaseModel):
    id: str
    label: str
    kind: str
    surface: ArtifactSurface
    badge: str = ""
    children: list["ArtifactTreeNode"] = Field(default_factory=list)
    has_lazy_children: bool = False


class ArtifactSection(BaseModel):
    title: str
    body: str = ""


class ArtifactCard(BaseModel):
    title: str
    subtitle: str = ""
    body: str = ""
    fields: dict[str, str] = Field(default_factory=dict)


class ArtifactTable(BaseModel):
    title: str
    columns: list[str] = Field(default_factory=list)
    rows: list[dict[str, str]] = Field(default_factory=list)


class ArtifactView(BaseModel):
    artifact_id: str
    title: str
    kind: str
    sections: list[ArtifactSection] = Field(default_factory=list)
    cards: list[ArtifactCard] = Field(default_factory=list)
    tables: list[ArtifactTable] = Field(default_factory=list)
    markdown: str = ""
    technical_available: bool = False


class CreateTaskRequest(BaseModel):
    task_id: str
    source_path: str = ""


class MessageCreateRequest(BaseModel):
    content: str
    payload: dict[str, Any] = Field(default_factory=dict)
    writer_question_answer: WriterQuestionAnswerMessage | None = None


class CommandRequest(BaseModel):
    command: str
    payload: dict[str, Any] = Field(default_factory=dict)


class JobCreateRequest(BaseModel):
    type: str
    payload: dict[str, Any] = Field(default_factory=dict)


try:
    TaskSummary.model_rebuild()
    ArtifactTreeNode.model_rebuild()
except AttributeError:
    TaskSummary.update_forward_refs()
    ArtifactTreeNode.update_forward_refs()

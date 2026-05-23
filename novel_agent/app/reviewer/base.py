from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

from ..schemas.reviewer_schema import ResolvedReviewTarget, ReviewerManifest, ReviewReport, ReviewRequest


@dataclass(slots=True)
class ModelPrompt:
    system_prompt: str
    user_prompt: str
    response_format: str = "json"


class BaseReviewer(Protocol):
    reviewer_id: str
    reviewer_version: str
    supported_target_types: set[str]
    dimensions: list[str]

    def manifest(self) -> ReviewerManifest:
        ...

    def build_planning_prompt(self, request: ReviewRequest, resolved_target: ResolvedReviewTarget) -> ModelPrompt:
        ...

    def build_judging_prompt(self, state: "ReviewerLoopState") -> ModelPrompt:
        ...

    def build_self_check_prompt(self, report: ReviewReport, state: "ReviewerLoopState") -> ModelPrompt:
        ...


@dataclass(slots=True)
class ReviewerLoopState:
    request: ReviewRequest
    resolved_target: ResolvedReviewTarget
    reviewer_id: str
    reviewer_version: str
    status: str = "initialized"
    plan: dict | None = None
    tool_calls: list[dict] | None = None
    tool_results: list[dict] | None = None
    loop_trace: list[dict] | None = None
    raw_model_response_paths: list[str] | None = None

    def __post_init__(self) -> None:
        self.tool_calls = list(self.tool_calls or [])
        self.tool_results = list(self.tool_results or [])
        self.loop_trace = list(self.loop_trace or [])
        self.raw_model_response_paths = list(self.raw_model_response_paths or [])

    def record(self, *, status: str | None = None, event: str, payload: dict | None = None) -> None:
        if status is not None:
            self.status = status
        self.loop_trace.append({"status": self.status, "event": event, "payload": dict(payload or {})})

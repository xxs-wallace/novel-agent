from __future__ import annotations

from dataclasses import dataclass
from typing import ClassVar

from ...prompts.reviewer import (
    ReviewerPromptSpec,
    build_judging_prompt,
    build_planning_prompt,
    build_self_check_prompt,
)
from ...schemas.reviewer_schema import ResolvedReviewTarget, ReviewerManifest, ReviewReport, ReviewRequest
from ..base import ModelPrompt, ReviewerLoopState


@dataclass(frozen=True, slots=True)
class ModelOnlyReviewer:
    reviewer_id: ClassVar[str]
    reviewer_version: ClassVar[str] = "1.0.0"
    display_name_zh: ClassVar[str]
    supported_target_types: ClassVar[set[str]]
    allowed_tools: ClassVar[list[str]]
    dimensions: ClassVar[list[str]]
    default_budget: ClassVar[dict[str, int]]
    focus_zh: ClassVar[str]
    boundary_zh: ClassVar[str]
    context_guidance_zh: ClassVar[str]

    def manifest(self) -> ReviewerManifest:
        return ReviewerManifest(
            reviewer_id=self.reviewer_id,
            reviewer_version=self.reviewer_version,
            display_name_zh=self.display_name_zh,
            supported_target_types=sorted(self.supported_target_types),
            dimensions=list(self.dimensions),
            requires_model=True,
            allowed_tools=list(self.allowed_tools),
            default_budget=dict(self.default_budget),
            metadata={"kind": "model_only_reviewer"},
        )

    def build_planning_prompt(self, request: ReviewRequest, resolved_target: ResolvedReviewTarget) -> ModelPrompt:
        return build_planning_prompt(spec=self._prompt_spec(), request=request, resolved_target=resolved_target)

    def build_judging_prompt(self, state: ReviewerLoopState) -> ModelPrompt:
        return build_judging_prompt(spec=self._prompt_spec(), state=state)

    def build_self_check_prompt(self, report: ReviewReport, state: ReviewerLoopState) -> ModelPrompt:
        return build_self_check_prompt(spec=self._prompt_spec(), report=report, state=state)

    def _prompt_spec(self) -> ReviewerPromptSpec:
        return ReviewerPromptSpec(
            reviewer_id=self.reviewer_id,
            reviewer_version=self.reviewer_version,
            display_name_zh=self.display_name_zh,
            supported_target_types=tuple(sorted(self.supported_target_types)),
            dimensions=tuple(self.dimensions),
            allowed_tools=tuple(self.allowed_tools),
            focus_zh=self.focus_zh,
            boundary_zh=self.boundary_zh,
            context_guidance_zh=self.context_guidance_zh,
        )

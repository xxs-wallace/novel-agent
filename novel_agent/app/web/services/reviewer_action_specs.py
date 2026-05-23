from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from ..schemas import ArtifactAction, WriterReviewAction


@dataclass(frozen=True, slots=True)
class ReviewerActionSpec:
    reviewer_id: str
    label: str
    target_type: str
    description: str
    user_focus: str


OUTLINE_PLOT_REVIEWER = ReviewerActionSpec(
    reviewer_id="outline_plot_development",
    label="Reviewer：大纲合理性",
    target_type="outline",
    description="结合前序剧情大纲和 Memory 线索，评估大纲剧情发展的合理性。",
    user_focus="重点评估目标大纲的剧情承接、因果链、阶段推进和长期结构是否合理。",
)

CHAPTER_SYNOPSIS_REVIEWER = ReviewerActionSpec(
    reviewer_id="chapter_synopsis_plot_character",
    label="Reviewer：梗概与人物",
    target_type="chapter_brief",
    description="结合前序大纲和人物档案，评估章节梗概的剧情合理性与人物一致性。",
    user_focus="重点评估章节梗概中的事件推进、人物动机、关系状态和历史设定是否冲突。",
)

DRAFT_REVIEWERS = (
    ReviewerActionSpec(
        reviewer_id="local_draft_continuity",
        label="Reviewer：局部连续性",
        target_type="draft",
        description="结合最近正文窗口，评估草稿的局部承接、剧情连续性和文风切换。",
        user_focus="重点评估最新正文草稿和最近几段正文之间是否有明显剧情错误、发展中断或文风突变。",
    ),
    ReviewerActionSpec(
        reviewer_id="memory_draft_consistency",
        label="Reviewer：历史一致性",
        target_type="draft",
        description="查询 Memory 中相关人物与事件，评估草稿是否和历史正文冲突。",
        user_focus="重点查询草稿提到的人物、事件、关系和状态，判断是否与历史正文或上次续写结果矛盾。",
    ),
    ReviewerActionSpec(
        reviewer_id="kb_draft_style_atmosphere",
        label="Reviewer：文风氛围",
        target_type="draft",
        description="查询 KB 中剧情或场景相似片段，对比文笔、文风和氛围。",
        user_focus="重点比较目标草稿与原作相似场景的文笔细节、节奏、氛围和叙述质感。",
    ),
)


def reviewer_specs_for_stage(stage: str) -> tuple[ReviewerActionSpec, ...]:
    if stage in {"freeze_a_review", "batch_review"}:
        return (OUTLINE_PLOT_REVIEWER,)
    if stage in {"chapter_review", "wait_chapter_review"}:
        return (CHAPTER_SYNOPSIS_REVIEWER,)
    if stage == "wait_chapter_acceptance":
        return DRAFT_REVIEWERS
    return ()


def reviewer_specs_for_writer_kind(kind: str) -> tuple[ReviewerActionSpec, ...]:
    if kind in {"book_plan", "batch_plan"}:
        return (OUTLINE_PLOT_REVIEWER,)
    if kind == "chapter_package":
        return (CHAPTER_SYNOPSIS_REVIEWER,)
    if kind == "draft":
        return DRAFT_REVIEWERS
    return ()


def writer_reviewer_actions(
    specs: tuple[ReviewerActionSpec, ...],
    *,
    task_id: str,
    run_id: str,
    target_id: str,
    artifact_id: str = "",
    artifact_kind: str = "",
    artifact_path: str = "",
    review_id: str = "",
    chapter_id: str = "",
    draft_id: str = "",
    source: str,
) -> list[WriterReviewAction]:
    return [
        WriterReviewAction(
            action="run_reviewer",
            label=spec.label,
            payload=_reviewer_payload(
                spec,
                task_id=task_id,
                run_id=run_id,
                target_id=target_id,
                artifact_id=artifact_id,
                artifact_kind=artifact_kind,
                artifact_path=artifact_path,
                review_id=review_id,
                chapter_id=chapter_id,
                draft_id=draft_id,
                source=source,
            ),
            description=spec.description,
        )
        for spec in specs
    ]


def artifact_reviewer_actions(
    specs: tuple[ReviewerActionSpec, ...],
    *,
    task_id: str,
    run_id: str,
    target_id: str,
    artifact_id: str,
    artifact_kind: str,
    artifact_path: str,
) -> list[ArtifactAction]:
    return [
        ArtifactAction(
            action="run_reviewer",
            label=spec.label,
            payload=_reviewer_payload(
                spec,
                task_id=task_id,
                run_id=run_id,
                target_id=target_id,
                artifact_id=artifact_id,
                artifact_kind=artifact_kind,
                artifact_path=artifact_path,
                source="artifact_toolbar",
            ),
            description=spec.description,
        )
        for spec in specs
    ]


def _reviewer_payload(
    spec: ReviewerActionSpec,
    *,
    task_id: str,
    run_id: str,
    target_id: str,
    artifact_id: str = "",
    artifact_kind: str = "",
    artifact_path: str = "",
    review_id: str = "",
    chapter_id: str = "",
    draft_id: str = "",
    source: str,
) -> dict[str, Any]:
    return {
        "task_id": task_id,
        "run_id": run_id,
        "target_id": target_id,
        "target_type": spec.target_type,
        "reviewer_id": spec.reviewer_id,
        "reviewer_ids": [spec.reviewer_id],
        "reviewer_label": spec.label,
        "artifact_id": artifact_id,
        "artifact_kind": artifact_kind,
        "artifact_path": artifact_path,
        "review_id": review_id,
        "chapter_id": chapter_id,
        "draft_id": draft_id,
        "source": source,
        "user_focus": spec.user_focus,
    }

from __future__ import annotations

from pathlib import Path

import pytest

from novel_agent.app.reviewer.registry import ReviewerRegistry
from novel_agent.app.schemas.reviewer_schema import (
    ReviewBudget,
    ReviewContextPolicy,
    ReviewReport,
    ReviewRequest,
    ReviewTarget,
    ReviewerManifest,
)


def test_review_target_supports_text_document_and_artifact_sources(tmp_path: Path) -> None:
    artifact = tmp_path / "draft.md"
    artifact.write_text("正文片段", encoding="utf-8")

    text_target = ReviewTarget(target_id="target-text", target_type="raw_text", text="需要评审的文本")
    document_target = ReviewTarget(target_id="target-doc", target_type="draft", document_ids=["1", "2"])
    artifact_target = ReviewTarget(target_id="target-artifact", target_type="draft", artifact_path=str(artifact))

    assert text_target.text == "需要评审的文本"
    assert document_target.document_ids == ["1", "2"]
    assert artifact_target.artifact_path == str(artifact)


def test_non_benchmark_context_forbids_reference_truth() -> None:
    with pytest.raises(ValueError, match="allow_reference_truth"):
        ReviewContextPolicy(purpose="writer_assist", allow_reference_truth=True)

    benchmark = ReviewContextPolicy(
        purpose="benchmark",
        allow_reference_truth=True,
        leakage_guard="benchmark_authorized_reference",
    )
    assert benchmark.allow_reference_truth is True


def test_review_request_requires_explicit_reviewer_ids() -> None:
    with pytest.raises(ValueError, match="reviewer_ids"):
        ReviewRequest(
            review_request_id="req-1",
            book_id="book-1",
            target=ReviewTarget(target_id="target-1", target_type="raw_text", text="文本"),
            reviewer_ids=[],
            context_policy=ReviewContextPolicy(purpose="user_review"),
            budget=ReviewBudget(),
            created_at="2026-05-20T10:00:00Z",
        )


def test_failed_report_cannot_carry_formal_score() -> None:
    with pytest.raises(ValueError, match="formal score"):
        ReviewReport(
            review_report_id="report-1",
            review_request_id="req-1",
            target_id="target-1",
            target_type="draft",
            reviewer_id="local_draft_continuity",
            reviewer_version="1.0.0",
            status="failed",
            score=10,
            summary_zh="模型失败，评审未完成。",
            model_id="model-x",
        )


def test_success_report_score_usage_is_reference_only() -> None:
    report = ReviewReport(
        review_report_id="report-1",
        review_request_id="req-1",
        target_id="target-1",
        target_type="draft",
        reviewer_id="local_draft_continuity",
        reviewer_version="1.0.0",
        status="success",
        score=82,
        score_usage="reference_only",
        summary_zh="整体顺畅，但局部承接需要加强。",
        model_id="model-x",
    )

    assert report.score_usage == "reference_only"

    with pytest.raises(ValueError, match="score_usage"):
        ReviewReport(
            review_report_id="report-2",
            review_request_id="req-1",
            target_id="target-1",
            target_type="draft",
            reviewer_id="local_draft_continuity",
            reviewer_version="1.0.0",
            status="success",
            score=82,
            score_usage="pass_gate",
            summary_zh="整体顺畅，但局部承接需要加强。",
            model_id="model-x",
        )


def test_fake_or_baseline_reviewer_cannot_be_formal_manifest_or_registry() -> None:
    with pytest.raises(ValueError, match="fake"):
        ReviewerManifest(
            reviewer_id="fake_local_draft_continuity",
            reviewer_version="1.0.0",
            display_name_zh="测试评审",
            supported_target_types=["draft"],
            dimensions=["连续性"],
            requires_model=True,
            allowed_tools=[],
        )

    class _NonModelReviewer:
        def manifest(self) -> ReviewerManifest:
            return ReviewerManifest(
                reviewer_id="unit_non_model_reviewer",
                reviewer_version="1.0.0",
                display_name_zh="测试评审",
                supported_target_types=["draft"],
                dimensions=["连续性"],
                requires_model=False,
                allowed_tools=[],
            )

    with pytest.raises(ValueError, match="requires_model"):
        ReviewerRegistry().register(_NonModelReviewer())  # type: ignore[arg-type]

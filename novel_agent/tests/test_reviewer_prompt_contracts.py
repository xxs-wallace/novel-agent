from __future__ import annotations

import json

import pytest

from novel_agent.app.reviewer.base import ReviewerLoopState
from novel_agent.app.reviewer.reviewers import default_reviewers
from novel_agent.app.schemas.reviewer_schema import (
    ResolvedReviewTarget,
    ReviewBudget,
    ReviewContextPolicy,
    ReviewReport,
    ReviewRequest,
    ReviewTarget,
)


DISALLOWED_QUALITY_WORDS = ("approved", "rejected", "pass", "fail")


@pytest.mark.parametrize("reviewer", default_reviewers())
def test_reviewer_prompts_require_reference_report_contract(reviewer) -> None:
    request = _request(reviewer.manifest().reviewer_id, next(iter(reviewer.manifest().supported_target_types)))
    resolved = _resolved(request.target.target_type)
    state = ReviewerLoopState(
        request=request,
        resolved_target=resolved,
        reviewer_id=reviewer.manifest().reviewer_id,
        reviewer_version=reviewer.manifest().reviewer_version,
        plan={
            "schema_version": "1.0",
            "reviewer_id": reviewer.manifest().reviewer_id,
            "target_id": "target-1",
            "dimensions": reviewer.manifest().dimensions,
            "tool_requests": [],
        },
        tool_results=[],
    )
    report = _report(reviewer.manifest().reviewer_id, reviewer.manifest().reviewer_version, request.target.target_type)

    prompts = [
        reviewer.build_planning_prompt(request, resolved),
        reviewer.build_judging_prompt(state),
        reviewer.build_self_check_prompt(report, state),
    ]

    for prompt in prompts:
        text = f"{prompt.system_prompt}\n{prompt.user_prompt}"
        assert "中文参考意见" in text
        assert "0-100" in text
        assert "score_usage" in text
        assert "reference_only" in text
        assert "findings" in text
        assert "evidence_refs" in text
        assert "critical、major、minor、note" in text
        assert "不得输出 info" in text or "严禁使用 info" in text
        assert "自检" in text
        assert "Writer" in text
        assert "benchmark" in text
        assert "质量裁决" in text
        assert not any(word in text.lower() for word in DISALLOWED_QUALITY_WORDS)


def test_memory_and_kb_reviewer_tool_boundaries_are_explicit() -> None:
    manifests = {reviewer.manifest().reviewer_id: reviewer.manifest() for reviewer in default_reviewers()}

    assert manifests["chapter_synopsis_plot_character"].allowed_tools == ["memory_query"]
    assert manifests["memory_draft_consistency"].allowed_tools == ["memory_query"]
    assert manifests["kb_draft_style_atmosphere"].allowed_tools == ["kb_retrieval"]
    assert "kb_retrieval" not in manifests["memory_draft_consistency"].allowed_tools
    assert "memory_query" not in manifests["kb_draft_style_atmosphere"].allowed_tools


@pytest.mark.parametrize("reviewer", default_reviewers())
def test_planning_prompt_serializes_contract_payload_without_semantic_rules(reviewer) -> None:
    target_type = next(iter(reviewer.manifest().supported_target_types))
    request = _request(reviewer.manifest().reviewer_id, target_type)
    prompt = reviewer.build_planning_prompt(request, _resolved(target_type))

    assert reviewer.manifest().reviewer_id in prompt.user_prompt
    assert "不得使用本地规则、关键词覆盖、固定角色表或小说专名映射" in prompt.system_prompt
    assert "allowed_tools" in prompt.user_prompt
    assert json.loads(json.dumps(request.to_dict(), ensure_ascii=False))["target"]["target_type"] == target_type


def _request(reviewer_id: str, target_type: str) -> ReviewRequest:
    return ReviewRequest(
        review_request_id=f"req-{reviewer_id}",
        book_id="book-1",
        target=ReviewTarget(target_id="target-1", target_type=target_type, text="需要模型评审的文本。"),
        reviewer_ids=[reviewer_id],
        context_policy=ReviewContextPolicy(purpose="writer_assist"),
        budget=ReviewBudget(),
        created_at="2026-05-20T10:00:00Z",
    )


def _resolved(target_type: str) -> ResolvedReviewTarget:
    return ResolvedReviewTarget(
        target_id="target-1",
        target_type=target_type,
        resolved_text="需要模型评审的文本。",
        source_refs=[{"source_type": "user_input", "source_id": "target-1", "label": "测试输入"}],
    )


def _report(reviewer_id: str, reviewer_version: str, target_type: str) -> ReviewReport:
    return ReviewReport(
        review_report_id=f"report-{reviewer_id}",
        review_request_id=f"req-{reviewer_id}",
        target_id="target-1",
        target_type=target_type,
        reviewer_id=reviewer_id,
        reviewer_version=reviewer_version,
        status="success",
        score=80,
        score_usage="reference_only",
        summary_zh="这是中文参考意见。",
        model_id="unit-model",
        findings=[],
        evidence_refs=[],
        confidence=0.7,
    )

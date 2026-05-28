from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from novel_agent.app.reviewer import ReviewerRegistry, ReviewerRuntime
from novel_agent.app.reviewer.reviewers import (
    ChapterSynopsisPlotCharacterReviewer,
    KBDraftStyleAtmosphereReviewer,
    LocalDraftContinuityReviewer,
    MemoryDraftConsistencyReviewer,
    OutlinePlotDevelopmentReviewer,
    SourceChapterLiteraryDiagnosticReviewer,
    default_reviewers,
)
from novel_agent.app.schemas.reviewer_schema import ReviewBudget, ReviewContextPolicy, ReviewRequest, ReviewTarget


EXPECTED_REVIEWERS = {
    "outline_plot_development": {
        "target_types": {"outline"},
        "allowed_tools": ["artifact_read", "memory_query"],
        "dimensions": {"剧情承接", "阶段推进", "因果链", "长期结构", "主支线落点"},
    },
    "chapter_synopsis_plot_character": {
        "target_types": {"chapter_brief", "synopsis"},
        "allowed_tools": ["memory_query"],
        "dimensions": {"剧情目标", "事件推进", "人物动机", "关系状态", "正文指导性"},
    },
    "local_draft_continuity": {
        "target_types": {"draft"},
        "allowed_tools": ["artifact_read"],
        "dimensions": {"局部承接", "剧情动作连续性", "场景衔接", "叙事视角", "文风过渡"},
    },
    "memory_draft_consistency": {
        "target_types": {"draft"},
        "allowed_tools": ["memory_query"],
        "dimensions": {"历史事件一致性", "人物状态", "关系状态", "设定约束", "时间线"},
    },
    "kb_draft_style_atmosphere": {
        "target_types": {"draft", "raw_text"},
        "allowed_tools": ["kb_retrieval"],
        "dimensions": {"文笔细节", "氛围", "节奏", "叙述视角", "风格一致性"},
    },
    "source_chapter_literary_diagnostic": {
        "target_types": {"source_chapter"},
        "allowed_tools": ["memory_query"],
        "dimensions": {"文学执行", "人物契合", "人物特点体现", "连续性与因果", "证据置信度"},
    },
}


class _ScriptedModelClient:
    def __init__(self, responses: list[str]) -> None:
        self.responses = list(responses)
        self.settings = SimpleNamespace(model_name="unit-review-model")
        self.calls: list[dict[str, str]] = []

    def generate_text(self, *, system_prompt: str, user_prompt: str) -> str:
        self.calls.append({"system_prompt": system_prompt, "user_prompt": user_prompt})
        if not self.responses:
            raise RuntimeError("no scripted response")
        return self.responses.pop(0)


def test_default_model_only_reviewer_manifests_register() -> None:
    reviewers = default_reviewers()
    registry = ReviewerRegistry(reviewers)

    manifests = {manifest.reviewer_id: manifest for manifest in registry.manifests()}

    assert set(manifests) == set(EXPECTED_REVIEWERS)
    for reviewer_id, expected in EXPECTED_REVIEWERS.items():
        manifest = manifests[reviewer_id]
        assert manifest.requires_model is True
        assert set(manifest.supported_target_types) == expected["target_types"]
        assert manifest.allowed_tools == expected["allowed_tools"]
        assert set(manifest.dimensions) == expected["dimensions"]
        assert manifest.default_budget["max_model_calls"] >= 5
        assert manifest.default_budget["json_repair_attempts"] == 1

    assert registry.get("outline_plot_development", target_type="outline").manifest().reviewer_id == "outline_plot_development"
    with pytest.raises(ValueError, match="does not support"):
        registry.get("outline_plot_development", target_type="draft")


@pytest.mark.parametrize(
    ("reviewer", "target_type"),
    [
        (OutlinePlotDevelopmentReviewer(), "outline"),
        (ChapterSynopsisPlotCharacterReviewer(), "synopsis"),
        (ChapterSynopsisPlotCharacterReviewer(), "chapter_brief"),
        (LocalDraftContinuityReviewer(), "draft"),
        (MemoryDraftConsistencyReviewer(), "draft"),
        (KBDraftStyleAtmosphereReviewer(), "draft"),
        (KBDraftStyleAtmosphereReviewer(), "raw_text"),
        (SourceChapterLiteraryDiagnosticReviewer(), "source_chapter"),
    ],
)
def test_model_only_reviewers_run_with_scripted_model_responses(tmp_path: Path, reviewer, target_type: str) -> None:
    request = _request(reviewer.manifest().reviewer_id, target_type)
    model = _ScriptedModelClient(_scripted_success_responses(reviewer.manifest().reviewer_id, target_type))
    runtime = ReviewerRuntime(model_client=model, artifact_root=tmp_path / "reviewer-runs")

    report = runtime.run(request, reviewer=reviewer)

    assert report.status == "success"
    assert report.score == 84
    assert report.score_usage == "reference_only"
    assert report.reviewer_id == reviewer.manifest().reviewer_id
    assert report.model_id == "unit-review-model"
    assert report.self_check["status"] == "ok"
    assert len(model.calls) == 3


def test_reviewer_prompts_are_json_model_prompts() -> None:
    request = _request("local_draft_continuity", "draft")
    reviewer = LocalDraftContinuityReviewer()
    resolved = SimpleNamespace(
        to_dict=lambda: {
            "schema_version": "1.0",
            "target_id": "target-1",
            "target_type": "draft",
            "resolved_text": "上一段和最新草稿。",
            "source_refs": [],
            "artifact_refs": [],
            "document_refs": [],
            "truncation": {"truncated": False, "strategy": "", "original_chars": 9, "resolved_chars": 9},
        },
        target_id="target-1",
        target_type="draft",
    )

    prompt = reviewer.build_planning_prompt(request, resolved)  # type: ignore[arg-type]

    assert prompt.response_format == "json"
    assert "local_draft_continuity" in prompt.system_prompt
    assert "ReviewPlan" in prompt.user_prompt
    assert "reference_only" in prompt.user_prompt


def _request(reviewer_id: str, target_type: str) -> ReviewRequest:
    return ReviewRequest(
        review_request_id=f"req-{reviewer_id}-{target_type}",
        book_id="book-1",
        target=ReviewTarget(
            target_id="target-1",
            target_type=target_type,
            text="最近上下文：人物正在对话。最新文本：这一段需要模型做参考评审。",
        ),
        reviewer_ids=[reviewer_id],
        context_policy=ReviewContextPolicy(
            purpose="writer_assist",
            allow_memory=True,
            allow_kb=True,
            allow_writer_artifacts=True,
        ),
        budget=ReviewBudget(max_model_calls=6, max_tool_calls=0, json_repair_attempts=1),
        created_at="2026-05-20T10:00:00Z",
    )


def _scripted_success_responses(reviewer_id: str, target_type: str) -> list[str]:
    return [
        json.dumps(
            {
                "schema_version": "1.0",
                "reviewer_id": reviewer_id,
                "target_id": "target-1",
                "dimensions": ["综合评审"],
                "initial_risks": ["需要模型综合判断。"],
                "tool_requests": [],
                "can_judge_without_context": True,
                "notes_zh": "测试中不请求外部证据。",
            },
            ensure_ascii=False,
        ),
        json.dumps(
            {
                "schema_version": "1.0",
                "target_type": target_type,
                "reviewer_id": reviewer_id,
                "status": "success",
                "score": 84,
                "score_usage": "reference_only",
                "summary_zh": "文本整体可读，但仍需注意局部证据和修订重点。",
                "dimension_scores": {"综合评审": 84},
                "findings": [
                    {
                        "finding_id": "finding-001",
                        "severity": "minor",
                        "category": "综合评审",
                        "message_zh": "测试模型指出一个需要继续核对的局部问题。",
                        "evidence_refs": ["ev-target-001"],
                        "suggestion_zh": "建议在修订时补足上下文承接。",
                        "confidence": 0.7,
                    }
                ],
                "evidence_refs": [
                    {
                        "evidence_id": "ev-target-001",
                        "source_type": "target_text",
                        "source_id": "target-1",
                        "quote": "这一段需要模型做参考评审。",
                        "summary_zh": "目标文本证据。",
                    }
                ],
                "confidence": 0.75,
            },
            ensure_ascii=False,
        ),
        json.dumps(
            {
                "status": "ok",
                "schema_ok": True,
                "score_usage_is_reference_only": True,
                "chinese_reference_opinion": True,
                "findings_have_evidence_refs": True,
                "authorized_context_only": True,
                "no_quality_gate_decision": True,
                "notes_zh": "自检通过。",
                "issues_zh": [],
            },
            ensure_ascii=False,
        ),
    ]

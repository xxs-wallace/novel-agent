from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

from novel_agent.app.reviewer.base import ModelPrompt, ReviewerLoopState
from novel_agent.app.reviewer.runtime import ReviewerRuntime
from novel_agent.app.schemas.reviewer_schema import (
    ResolvedReviewTarget,
    ReviewBudget,
    ReviewContextPolicy,
    ReviewReport,
    ReviewRequest,
    ReviewTarget,
    ReviewerManifest,
)


class _ScriptedModelClient:
    def __init__(self, responses: list[str]) -> None:
        self.responses = list(responses)
        self.settings = SimpleNamespace(model_name="unit-model")
        self.calls: list[dict[str, str]] = []

    def generate_text(self, *, system_prompt: str, user_prompt: str) -> str:
        self.calls.append({"system_prompt": system_prompt, "user_prompt": user_prompt})
        if not self.responses:
            raise RuntimeError("no scripted model response")
        return self.responses.pop(0)


class _UnitReviewer:
    reviewer_id = "unit_runtime_reviewer"
    reviewer_version = "1.0.0"
    supported_target_types = {"draft", "raw_text"}
    dimensions = ["连续性"]

    def manifest(self) -> ReviewerManifest:
        return ReviewerManifest(
            reviewer_id=self.reviewer_id,
            reviewer_version=self.reviewer_version,
            display_name_zh="单元评审",
            supported_target_types=sorted(self.supported_target_types),
            dimensions=list(self.dimensions),
            requires_model=True,
            allowed_tools=[],
        )

    def build_planning_prompt(self, request: ReviewRequest, resolved_target: ResolvedReviewTarget) -> ModelPrompt:
        return ModelPrompt(system_prompt="plan", user_prompt=resolved_target.resolved_text)

    def build_judging_prompt(self, state: ReviewerLoopState) -> ModelPrompt:
        return ModelPrompt(system_prompt="judge", user_prompt=json.dumps(state.plan, ensure_ascii=False))

    def build_self_check_prompt(self, report: ReviewReport, state: ReviewerLoopState) -> ModelPrompt:
        return ModelPrompt(system_prompt="self-check", user_prompt=json.dumps(report.to_dict(), ensure_ascii=False))


def _request(*, budget: ReviewBudget | None = None) -> ReviewRequest:
    return ReviewRequest(
        review_request_id="req-1",
        book_id="book-1",
        target=ReviewTarget(target_id="target-1", target_type="draft", text="这一段需要模型评审。"),
        reviewer_ids=["unit_runtime_reviewer"],
        context_policy=ReviewContextPolicy(purpose="writer_assist", allow_memory=False, allow_kb=False),
        budget=budget or ReviewBudget(max_model_calls=6, json_repair_attempts=1),
        created_at="2026-05-20T10:00:00Z",
    )


def test_reviewer_runtime_runs_planning_judging_and_self_check(tmp_path: Path) -> None:
    model = _ScriptedModelClient(
        [
            json.dumps(
                {
                    "reviewer_id": "unit_runtime_reviewer",
                    "target_id": "target-1",
                    "dimensions": ["连续性"],
                    "tool_requests": [],
                    "can_judge_without_context": True,
                    "notes_zh": "无需额外上下文。",
                },
                ensure_ascii=False,
            ),
            json.dumps(
                {
                    "status": "success",
                    "score": 81,
                    "summary_zh": "文本基本连贯，但转折铺垫略薄。",
                    "dimension_scores": {"连续性": 81},
                    "findings": [],
                    "evidence_refs": [],
                    "confidence": 0.8,
                },
                ensure_ascii=False,
            ),
            json.dumps({"status": "passed", "notes_zh": "报告符合 contract。"}, ensure_ascii=False),
        ]
    )
    runtime = ReviewerRuntime(model_client=model, artifact_root=tmp_path / "reviewer-runs")

    report = runtime.run(_request(), reviewer=_UnitReviewer())

    assert report.status == "success"
    assert report.score == 81
    assert report.score_usage == "reference_only"
    assert report.model_id == "unit-model"
    assert report.self_check["status"] == "passed"
    assert len(model.calls) == 3
    assert (tmp_path / "reviewer-runs" / "req-1" / "unit_runtime_reviewer" / "reviewer_report.json").exists()
    loop_trace = json.loads(
        (tmp_path / "reviewer-runs" / "req-1" / "unit_runtime_reviewer" / "loop_trace.json").read_text(encoding="utf-8")
    )
    assert any(item["status"] == "completed" for item in loop_trace)


def test_reviewer_runtime_repairs_schema_invalid_judging_report_with_model(tmp_path: Path) -> None:
    model = _ScriptedModelClient(
        [
            json.dumps(
                {
                    "reviewer_id": "unit_runtime_reviewer",
                    "target_id": "target-1",
                    "dimensions": ["连续性"],
                    "tool_requests": [],
                    "can_judge_without_context": True,
                    "notes_zh": "无需额外上下文。",
                },
                ensure_ascii=False,
            ),
            json.dumps(
                {
                    "status": "success",
                    "score": 75,
                    "summary_zh": "文本有一处证据引用类型需要修正。",
                    "findings": [],
                    "evidence_refs": [
                        {
                            "evidence_id": "ev-tool",
                            "source_type": "tool_result",
                            "source_id": "tool-call-001",
                            "summary_zh": "工具失败记录。",
                        }
                    ],
                    "confidence": 0.7,
                },
                ensure_ascii=False,
            ),
            json.dumps(
                {
                    "status": "success",
                    "score": 75,
                    "summary_zh": "文本有一处证据引用类型已按 contract 修正。",
                    "findings": [],
                    "evidence_refs": [
                        {
                            "evidence_id": "ev-target",
                            "source_type": "target_text",
                            "source_id": "target-1",
                            "summary_zh": "目标文本证据。",
                        }
                    ],
                    "confidence": 0.7,
                },
                ensure_ascii=False,
            ),
            json.dumps({"status": "passed", "notes_zh": "报告符合 contract。"}, ensure_ascii=False),
        ]
    )
    runtime = ReviewerRuntime(model_client=model, artifact_root=tmp_path / "reviewer-runs")

    report = runtime.run(_request(), reviewer=_UnitReviewer())

    assert report.status == "success"
    assert report.score == 75
    assert report.evidence_refs[0].source_type == "target_text"
    assert len(model.calls) == 4
    assert "未通过 ReviewReport contract 校验" in model.calls[2]["user_prompt"]
    assert "tool_result" in model.calls[2]["user_prompt"]


def test_reviewer_runtime_returns_needs_model_without_model_client(tmp_path: Path) -> None:
    runtime = ReviewerRuntime(model_client=None, artifact_root=tmp_path / "reviewer-runs")

    report = runtime.run(_request(), reviewer=_UnitReviewer())

    assert report.status == "needs_model"
    assert report.score is None
    assert report.summary_zh == "模型不可用，评审未完成。"


def test_reviewer_runtime_fails_after_json_repair_attempts_are_exhausted(tmp_path: Path) -> None:
    model = _ScriptedModelClient(["not-json", "still not json"])
    runtime = ReviewerRuntime(
        model_client=model,
        artifact_root=tmp_path / "reviewer-runs",
    )

    report = runtime.run(
        _request(budget=ReviewBudget(max_model_calls=3, json_repair_attempts=1)),
        reviewer=_UnitReviewer(),
    )

    assert report.status == "failed"
    assert report.score is None
    assert "JSON parsing failed" in report.summary_zh
    assert len(model.calls) == 2


def test_reviewer_runtime_rejects_unauthorized_reference_truth_in_report(tmp_path: Path) -> None:
    model = _ScriptedModelClient(
        [
            json.dumps(
                {
                    "reviewer_id": "unit_runtime_reviewer",
                    "target_id": "target-1",
                    "dimensions": ["连续性"],
                    "tool_requests": [],
                    "can_judge_without_context": True,
                },
                ensure_ascii=False,
            ),
            json.dumps(
                {
                    "status": "success",
                    "score": 70,
                    "summary_zh": "引用了未授权参考真值。",
                    "findings": [],
                    "evidence_refs": [
                        {
                            "evidence_id": "ev-reference",
                            "source_type": "reference_truth",
                            "source_id": "held-out",
                            "summary_zh": "未授权参考答案。",
                        }
                    ],
                },
                ensure_ascii=False,
            ),
        ]
    )
    runtime = ReviewerRuntime(model_client=model, artifact_root=tmp_path / "reviewer-runs")

    report = runtime.run(_request(), reviewer=_UnitReviewer())

    assert report.status == "failed"
    assert report.score is None
    assert "reference_truth" in report.summary_zh

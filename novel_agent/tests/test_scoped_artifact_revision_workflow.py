from __future__ import annotations

import json
from copy import deepcopy
from pathlib import Path
from typing import Any

import pytest

from novel_agent.app.orchestrators import ScopedArtifactRevisionLLMInput
from novel_agent.app.run_interactive import build_writer_workflow
from novel_agent.tests.test_writer_execution_workflow import _prepare_freeze_c_chain


class FakeScopedRevisionAdapter:
    def __init__(self, *, invalid: bool = False) -> None:
        self.invalid = invalid
        self.inputs: list[ScopedArtifactRevisionLLMInput] = []

    def generate_candidate(self, llm_input: ScopedArtifactRevisionLLMInput) -> dict[str, Any]:
        self.inputs.append(llm_input)
        artifact = deepcopy(llm_input.target_artifact)
        artifact_type = str(llm_input.request["target_artifact_type"])
        if self.invalid:
            self._make_invalid(artifact, artifact_type)
        else:
            self._make_valid_revision(artifact, artifact_type)
        return {
            "revision_id": f"rev-{llm_input.request['request_id']}",
            "request_id": llm_input.request["request_id"],
            "status": "candidate",
            "target_artifact_type": artifact_type,
            "target_artifact_path": llm_input.request["target_artifact_path"],
            "change_summary": f"{artifact_type} candidate revised from user feedback.",
            "validation": {"adapter": "fake"},
            "created_at": "2026-05-10T00:00:00+00:00",
            "revised_artifact": artifact,
        }

    def _make_valid_revision(self, artifact: dict[str, Any], artifact_type: str) -> None:
        if artifact_type == "BatchPlan":
            artifact["batch_goal"] = f"{artifact.get('batch_goal', '')} 补强中段压力。".strip()
            return
        if artifact_type == "ChapterPackage":
            notes = list(artifact.get("review_notes") or [])
            notes.append("按反馈提前反派压力。")
            artifact["review_notes"] = notes
            return
        if artifact_type == "ChapterLengthPlan":
            notes = list(artifact.get("review_notes") or [])
            notes.append("按反馈增加重点章节篇幅。")
            artifact["review_notes"] = notes
            return
        if artifact_type == "ChapterExecutionInput":
            rules = list(artifact.get("writer_rules") or [])
            rules.append("按反馈强化本章收束前的危险感。")
            artifact["writer_rules"] = rules

    def _make_invalid(self, artifact: dict[str, Any], artifact_type: str) -> None:
        if artifact_type == "BatchPlan":
            artifact["book_id"] = "other-book"
            return
        if artifact_type == "ChapterPackage":
            artifact["batch_id"] = "other-batch"
            return
        if artifact_type == "ChapterLengthPlan":
            budgets = list(artifact.get("budgets") or [])
            budgets.append({"chapter_id": "outside-chapter", "target_chars": 2000})
            artifact["budgets"] = budgets
            return
        if artifact_type == "ChapterExecutionInput":
            budget = dict(artifact.get("length_budget") or {})
            budget["chapter_id"] = "outside-chapter"
            artifact["length_budget"] = budget


def _load_data(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))["data"]


def _write_pending_review(workflow: Any, *, stage: str, artifact_path: Path, current_chapter_id: str = "") -> None:
    state = workflow.load_workflow_state(run_id="run-1") or workflow.initialize_workflow(
        run_id="run-1",
        book_id="book-1",
        product_mode="assist",
    )
    checkpoint = {
        "checkpoint_id": f"{stage}-test",
        "stage": stage,
        "status": "pending",
        "artifact_path": str(artifact_path),
        "source": "test",
        "confirmed_at": "",
    }
    state["pending_checkpoint"] = checkpoint
    state["current_stage"] = stage
    state["current_chapter_id"] = current_chapter_id
    workflow.run_writer.write_json("run-1", "workflow_state.json", state)
    workflow.run_writer.write_json("run-1", "workflow_checkpoints.json", {"checkpoints": [checkpoint]})


def _build_workflow_for_stage(tmp_path: Path, stage: str, adapter: FakeScopedRevisionAdapter) -> tuple[Any, Path]:
    db, planner_orchestrator = _prepare_freeze_c_chain(tmp_path)
    _, workflow = build_writer_workflow(
        repo_root=planner_orchestrator.repo_root,
        db_path=db.db_path,
        runs_dir=planner_orchestrator.run_writer.layout.base_dir,
        dry_run=True,
        revision_adapter=adapter,
    )
    workflow.initialize_workflow(run_id="run-1", book_id="book-1", product_mode="assist")
    run_dir = workflow.run_writer.layout.run_dir("run-1")
    if stage == "batch_review":
        _write_pending_review(workflow, stage=stage, artifact_path=run_dir / "batch_plan.json")
        return workflow, run_dir / "batch_plan.json"
    if stage == "chapter_review":
        _write_pending_review(workflow, stage=stage, artifact_path=run_dir / "chapter_package.json")
        return workflow, run_dir / "chapter_package.json"
    planner_orchestrator.confirm_chapter_package(run_id="run-1")
    if stage == "wait_length_review":
        workflow.prepare_chapter_length_plan(run_id="run-1", product_mode="assist")
        return workflow, run_dir / "chapter_length_plan.json"
    workflow.prepare_chapter_length_plan(run_id="run-1", product_mode="assist")
    workflow.continue_after_length_review(run_id="run-1")
    length_plan = _load_data(run_dir / "chapter_length_plan.json")
    chapter_id = str(length_plan["budgets"][0]["chapter_id"])
    with db.connect() as conn:
        db.init_schema(conn)
        workflow.prepare_execution(
            conn,
            run_id="run-1",
            book_id="book-1",
            chapter_id=chapter_id,
            product_mode="assist",
        )
    return workflow, run_dir / "chapter_execution_input.json"


@pytest.mark.parametrize("stage", ["batch_review", "chapter_review", "wait_length_review", "freeze_d_review"])
def test_scoped_artifact_revision_request_and_apply_happy_path(tmp_path: Path, stage: str) -> None:
    adapter = FakeScopedRevisionAdapter()
    workflow, artifact_path = _build_workflow_for_stage(tmp_path, stage, adapter)
    before = _load_data(artifact_path)

    candidate = workflow.request_scoped_artifact_revision(
        run_id="run-1",
        user_feedback="请只修改当前审阅产物，不要碰 Memory 或其他章节。",
        request_id=f"req-{stage}",
    )
    after_request = _load_data(artifact_path)
    applied = workflow.apply_scoped_artifact_revision(run_id="run-1", request_id=f"req-{stage}")
    after_apply = _load_data(artifact_path)
    state = workflow.load_workflow_state(run_id="run-1")

    assert candidate["status"] == "candidate"
    assert "diff" in candidate and candidate["diff"]
    assert after_request == before
    assert after_apply != before
    assert applied["status"] == "applied"
    assert applied["rollback"]["trigger"] == "scoped_artifact_revision"
    assert state is not None
    assert state["current_stage"] == stage
    assert state["pending_checkpoint"]["stage"] == stage
    assert "prompt" not in adapter.inputs[0].to_dict()
    context_text = json.dumps(adapter.inputs[0].allowed_context, ensure_ascii=False).lower()
    assert "memory_writeback" not in context_text
    assert "creative_kb" not in context_text


@pytest.mark.parametrize("stage", ["batch_review", "chapter_review", "wait_length_review", "freeze_d_review"])
def test_scoped_artifact_revision_validation_failure_does_not_write_artifact(tmp_path: Path, stage: str) -> None:
    adapter = FakeScopedRevisionAdapter(invalid=True)
    workflow, artifact_path = _build_workflow_for_stage(tmp_path, stage, adapter)
    before = _load_data(artifact_path)

    candidate = workflow.request_scoped_artifact_revision(
        run_id="run-1",
        user_feedback="越权修改上游约束。",
        request_id=f"req-invalid-{stage}",
    )
    after_request = _load_data(artifact_path)

    assert candidate["status"] == "validation_failed"
    assert candidate["validation"]["ok"] is False
    assert after_request == before
    with pytest.raises(Exception, match="only validated candidate revisions can be applied"):
        workflow.apply_scoped_artifact_revision(run_id="run-1", request_id=f"req-invalid-{stage}")

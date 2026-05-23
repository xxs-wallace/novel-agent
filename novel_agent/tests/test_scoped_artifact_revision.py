from __future__ import annotations

import json
from pathlib import Path

import pytest

from novel_agent.app.orchestrators import (
    RevisionResultError,
    ScopeGuardError,
    ScopedArtifactReviewContext,
    ScopedArtifactRevisionRequest,
    ScopedArtifactRevisionResult,
    ScopedArtifactRevisionStore,
    get_revision_stage_policy,
    validate_scoped_revision_request,
    validate_scoped_revision_result,
)
from novel_agent.runs.layout import RunLayout
from novel_agent.runs.writer import RunWriter


def _context(run_dir: Path, artifact_path: Path) -> ScopedArtifactReviewContext:
    return ScopedArtifactReviewContext(
        run_id="run-1",
        current_stage="batch_review",
        current_artifact_type="BatchPlan",
        current_artifact_path=str(artifact_path),
        run_dir=str(run_dir),
        current_batch_id="batch-1",
    )


def _request(artifact_path: Path) -> ScopedArtifactRevisionRequest:
    return ScopedArtifactRevisionRequest(
        request_id="req-1",
        run_id="run-1",
        target_stage="batch_review",
        target_artifact_type="BatchPlan",
        target_artifact_path=str(artifact_path),
        user_feedback="把反派登场提前，但不要改本批范围。",
        scope={
            "current_artifact_path": str(artifact_path),
            "target_artifact_path": str(artifact_path),
            "current_batch_id": "batch-1",
            "target_batch_id": "batch-1",
        },
        created_at="2026-05-10T00:00:00+00:00",
    )


def _valid_batch_plan() -> dict[str, object]:
    return {
        "batch_id": "batch-1",
        "book_id": "book-1",
        "chapters": ["chapter-1", "chapter-2", "chapter-3"],
        "batch_goal": "提前反派登场并维持主线。",
        "emotional_arc": "紧张度上升",
        "conflict_arc": "暗线转明",
        "must_resolve": [],
        "must_not_consume": ["终局真相"],
        "planned_character_beats": ["反派在第二章露面"],
        "exit_hook": "第三章留下悬疑钩子",
        "evidence": [],
        "sources": [],
    }


def test_scoped_revision_request_result_and_persistence_for_legal_stage(tmp_path: Path) -> None:
    base_dir = tmp_path / "runs"
    run_dir = base_dir / "run-1"
    run_dir.mkdir(parents=True)
    artifact_path = run_dir / "batch_plan.json"
    artifact_path.write_text(json.dumps({"batch_id": "batch-1"}), encoding="utf-8")

    context = _context(run_dir, artifact_path)
    request = _request(artifact_path)
    result = ScopedArtifactRevisionResult(
        revision_id="rev-1",
        request_id=request.request_id,
        status="candidate",
        target_artifact_type=request.target_artifact_type,
        target_artifact_path=request.target_artifact_path,
        change_summary="提前反派登场并保留当前批次范围。",
        revised_artifact=_valid_batch_plan(),
        validation={"schema_valid": True, "scope_valid": True},
        created_at="2026-05-10T00:01:00+00:00",
    )

    policy = validate_scoped_revision_request(request, context)
    validate_scoped_revision_result(request, result, context)
    assert policy.review_stage == "batch_review"
    assert policy.allowed_fields_for("BatchPlan")

    store = ScopedArtifactRevisionStore(RunWriter(RunLayout(base_dir)))
    request_path = store.write_request(request)
    result_path = store.write_result(result, request=request)
    index_path = run_dir / "scoped_artifact_revisions" / "index.json"

    request_payload = json.loads(request_path.read_text(encoding="utf-8"))["data"]
    result_payload = json.loads(result_path.read_text(encoding="utf-8"))["data"]
    index_payload = json.loads(index_path.read_text(encoding="utf-8"))["data"]
    assert request_payload["target_artifact_path"] == str(artifact_path)
    assert request_payload["user_feedback"] == "把反派登场提前，但不要改本批范围。"
    assert result_payload["request_id"] == "req-1"
    assert index_payload["revisions"][0]["target_artifact_path"] == str(artifact_path)
    assert index_payload["revisions"][0]["user_feedback"] == "把反派登场提前，但不要改本批范围。"
    assert index_payload["revisions"][0]["result_path"] == str(result_path)


def test_scoped_revision_rejects_illegal_stage(tmp_path: Path) -> None:
    run_dir = tmp_path / "runs" / "run-1"
    artifact_path = run_dir / "draft.md"
    context = ScopedArtifactReviewContext(
        run_id="run-1",
        current_stage="wait_chapter_acceptance",
        current_artifact_type="Draft",
        current_artifact_path=str(artifact_path),
        run_dir=str(run_dir),
    )
    request = ScopedArtifactRevisionRequest(
        request_id="req-2",
        run_id="run-1",
        target_stage="wait_chapter_acceptance",
        target_artifact_type="Draft",
        target_artifact_path=str(artifact_path),
        user_feedback="直接润色正文。",
        scope={"current_artifact_path": str(artifact_path)},
        created_at="2026-05-10T00:00:00+00:00",
    )

    with pytest.raises(ScopeGuardError, match="not allowed"):
        validate_scoped_revision_request(request, context)
    with pytest.raises(ScopeGuardError, match="not allowed"):
        get_revision_stage_policy("memory_review")


def test_scoped_revision_rejects_non_current_artifact(tmp_path: Path) -> None:
    run_dir = tmp_path / "runs" / "run-1"
    run_dir.mkdir(parents=True)
    current_artifact = run_dir / "batch_plan.json"
    other_artifact = run_dir / "chapter_package.json"
    context = _context(run_dir, current_artifact)
    request = _request(other_artifact)

    with pytest.raises(ScopeGuardError, match="current review artifact"):
        validate_scoped_revision_request(request, context)


def test_scoped_revision_rejects_privileged_or_forbidden_target(tmp_path: Path) -> None:
    run_dir = tmp_path / "runs" / "run-1"
    run_dir.mkdir(parents=True)
    artifact_path = run_dir / "batch_plan.json"
    context = _context(run_dir, artifact_path)
    request = ScopedArtifactRevisionRequest(
        request_id="req-3",
        run_id="run-1",
        target_stage="batch_review",
        target_artifact_type="Memory",
        target_artifact_path=str(artifact_path),
        user_feedback="把这条写入记忆库。",
        scope={"current_artifact_path": str(artifact_path)},
        created_at="2026-05-10T00:00:00+00:00",
    )

    with pytest.raises(ScopeGuardError, match="not an allowed artifact type"):
        validate_scoped_revision_request(request, context)

    workflow_state = run_dir / "workflow_state.json"
    forbidden_context = ScopedArtifactReviewContext(
        run_id="run-1",
        current_stage="batch_review",
        current_artifact_type="BatchPlan",
        current_artifact_path=str(workflow_state),
        run_dir=str(run_dir),
    )
    forbidden_request = ScopedArtifactRevisionRequest(
        request_id="req-3b",
        run_id="run-1",
        target_stage="batch_review",
        target_artifact_type="BatchPlan",
        target_artifact_path=str(workflow_state),
        user_feedback="把工作流状态改成已确认。",
        scope={"current_artifact_path": str(workflow_state)},
        created_at="2026-05-10T00:00:00+00:00",
    )

    with pytest.raises(ScopeGuardError, match="forbidden"):
        validate_scoped_revision_request(forbidden_request, forbidden_context)


def test_scoped_revision_requires_user_feedback(tmp_path: Path) -> None:
    artifact_path = tmp_path / "runs" / "run-1" / "batch_plan.json"

    with pytest.raises(ScopeGuardError, match="user_feedback"):
        ScopedArtifactRevisionRequest(
            request_id="req-4",
            run_id="run-1",
            target_stage="batch_review",
            target_artifact_type="BatchPlan",
            target_artifact_path=str(artifact_path),
            user_feedback=" ",
            scope={"current_artifact_path": str(artifact_path)},
            created_at="2026-05-10T00:00:00+00:00",
        )


def test_scoped_revision_result_requires_schema_fields(tmp_path: Path) -> None:
    run_dir = tmp_path / "runs" / "run-1"
    run_dir.mkdir(parents=True)
    artifact_path = run_dir / "batch_plan.json"
    context = _context(run_dir, artifact_path)
    request = _request(artifact_path)
    result = ScopedArtifactRevisionResult(
        revision_id="rev-2",
        request_id=request.request_id,
        status="candidate",
        target_artifact_type=request.target_artifact_type,
        target_artifact_path=request.target_artifact_path,
        change_summary="候选结果缺少 batch_goal。",
        revised_artifact={
            "batch_id": "batch-1",
            "book_id": "book-1",
            "chapters": ["chapter-1", "chapter-2", "chapter-3"],
        },
        validation={"schema_valid": False},
        created_at="2026-05-10T00:01:00+00:00",
    )

    with pytest.raises(RevisionResultError, match="missing required fields"):
        validate_scoped_revision_result(request, result, context)

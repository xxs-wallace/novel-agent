from __future__ import annotations

import json
import sqlite3
import uuid
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Mapping

from ...runs.writer import RunWriter
from ..schemas.orchestration_schema import FreezeRecord
from .scoped_artifact_revision import (
    ModelScopedArtifactRevisionAdapter,
    RevisionResultError,
    ScopedArtifactReviewContext,
    ScopedArtifactRevisionAdapter,
    ScopedArtifactRevisionLLMInput,
    ScopedArtifactRevisionRequest,
    ScopedArtifactRevisionResult,
    ScopedArtifactRevisionStore,
    ScopeGuardError,
    build_readable_artifact_diff,
    get_revision_stage_policy,
    validate_scoped_revision_references,
    validate_scoped_revision_request,
    validate_scoped_revision_result,
    validate_upstream_freeze_constraints,
)
from .writer_execution import RestrictedWriterExecutor, WriterRollbackManager
from .writer_layered_generation import WriterLayeredGenerationOrchestrator


ASSIST_MODE = "assist"
BATCH_MODE = "batch"
AUTO_NOVEL_MODE = "auto_novel"
PRODUCT_MODES = {ASSIST_MODE, BATCH_MODE, AUTO_NOVEL_MODE}
MODE_CONFIRMATION_POINTS = {
    ASSIST_MODE: ["freeze_a_review", "batch_review", "chapter_review", "freeze_d_review", "writeback_review"],
    BATCH_MODE: ["batch_review", "chapter_review"],
    AUTO_NOVEL_MODE: [],
}
RESUMABLE_WORKFLOW_STAGES = {
    "freeze_a_review",
    "batch_review",
    "chapter_review",
    "freeze_d_review",
    "wait_chapter_acceptance",
    "wait_length_review",
    "wait_chapter_review",
    "writeback_review",
}


def _utc_now() -> str:
    from datetime import datetime, timezone

    return datetime.now(timezone.utc).isoformat()


@dataclass(slots=True)
class WorkflowCheckpoint:
    checkpoint_id: str
    stage: str
    status: str
    artifact_path: str
    source: str
    confirmed_at: str = ""

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


class WriterInteractiveWorkflow:
    def __init__(
        self,
        *,
        planner: WriterLayeredGenerationOrchestrator,
        executor: RestrictedWriterExecutor,
        rollback_manager: WriterRollbackManager,
        run_writer: RunWriter,
        revision_adapter: ScopedArtifactRevisionAdapter | None = None,
    ) -> None:
        self.planner = planner
        self.executor = executor
        self.rollback_manager = rollback_manager
        self.run_writer = run_writer
        self.revision_adapter = revision_adapter or ModelScopedArtifactRevisionAdapter(model_client=planner.model_client)
        self.revision_store = ScopedArtifactRevisionStore(run_writer=run_writer)

    def initialize_workflow(
        self,
        *,
        run_id: str,
        book_id: str,
        product_mode: str,
    ) -> dict[str, Any]:
        mode = self._normalize_mode(product_mode)
        state = self._base_state(run_id=run_id, book_id=book_id, product_mode=mode)
        self._save_workflow_state(run_id, state)
        return state

    def prepare_planning(
        self,
        conn: sqlite3.Connection,
        *,
        run_id: str,
        book_id: str,
        product_mode: str,
        intent_payload: Mapping[str, Any],
        user_world_notes: str = "",
        character_seed_payloads: list[Mapping[str, Any]] | None = None,
        roster_hint_payloads: list[Mapping[str, Any]] | None = None,
    ) -> dict[str, Any]:
        mode = self._normalize_mode(product_mode)
        result = self.planner.prepare_freeze_a(
            conn,
            run_id=run_id,
            book_id=book_id,
            intent_payload=intent_payload,
            user_world_notes=user_world_notes,
            character_seed_payloads=character_seed_payloads,
            roster_hint_payloads=roster_hint_payloads,
            auto_confirm=mode != ASSIST_MODE,
        )
        state = self.load_workflow_state(run_id=run_id) or self._base_state(run_id=run_id, book_id=book_id, product_mode=mode)
        if mode == ASSIST_MODE:
            checkpoint = self._write_checkpoint(
                run_id=run_id,
                stage="freeze_a_review",
                artifact_path=str(self.run_writer.layout.run_dir(run_id)),
                source="prepare_planning",
            )
            state["pending_checkpoint"] = checkpoint
            state["current_stage"] = "freeze_a_review"
        else:
            state["current_stage"] = "freeze_a"
            state["pending_checkpoint"] = None
        self._save_workflow_state(run_id, state)
        return result

    def continue_after_planning_review(self, *, run_id: str) -> dict[str, str]:
        paths = self.planner.confirm_freeze_a(run_id=run_id)
        self._confirm_checkpoint(run_id=run_id, stage="freeze_a_review", source="continue_after_planning_review")
        return paths

    def prepare_batch_plan(
        self,
        conn: sqlite3.Connection,
        *,
        run_id: str,
        book_id: str,
        product_mode: str,
        target_chapter_count: int = 3,
    ) -> dict[str, Any]:
        mode = self._normalize_mode(product_mode)
        result = self.planner.prepare_batch_plan(
            conn,
            run_id=run_id,
            book_id=book_id,
            target_chapter_count=target_chapter_count,
            auto_confirm=mode == AUTO_NOVEL_MODE,
        )
        state = self.load_workflow_state(run_id=run_id) or self._base_state(run_id=run_id, book_id=book_id, product_mode=mode)
        if mode in {ASSIST_MODE, BATCH_MODE}:
            checkpoint = self._write_checkpoint(
                run_id=run_id,
                stage="batch_review",
                artifact_path=str(self.run_writer.layout.run_dir(run_id) / "batch_plan.json"),
                source="prepare_batch_plan",
            )
            state["pending_checkpoint"] = checkpoint
            state["current_stage"] = "batch_review"
        else:
            state["pending_checkpoint"] = None
            state["current_stage"] = "freeze_b"
        self._save_workflow_state(run_id, state)
        return result

    def continue_after_batch_review(self, *, run_id: str, artifact_path: str | None = None) -> dict[str, str]:
        paths = self.planner.confirm_batch_plan(run_id=run_id, artifact_path=artifact_path)
        self._confirm_checkpoint(run_id=run_id, stage="batch_review", source="continue_after_batch_review")
        state = self.load_workflow_state(run_id=run_id) or {}
        state["current_stage"] = "freeze_b"
        state["pending_checkpoint"] = None
        state["terminal_stage"] = None
        self._save_workflow_state(run_id, state)
        return paths

    def prepare_chapter_package(
        self,
        *,
        run_id: str,
        book_id: str,
        product_mode: str,
        chapter_count: int = 3,
    ) -> dict[str, Any]:
        mode = self._normalize_mode(product_mode)
        result = self.planner.prepare_chapter_package(
            run_id=run_id,
            book_id=book_id,
            chapter_count=chapter_count,
            auto_confirm=mode == AUTO_NOVEL_MODE,
        )
        state = self.load_workflow_state(run_id=run_id) or self._base_state(run_id=run_id, book_id=book_id, product_mode=mode)
        if mode in {ASSIST_MODE, BATCH_MODE}:
            checkpoint = self._write_checkpoint(
                run_id=run_id,
                stage="chapter_review",
                artifact_path=str(self.run_writer.layout.run_dir(run_id) / "chapter_package.json"),
                source="prepare_chapter_package",
            )
            state["pending_checkpoint"] = checkpoint
            state["current_stage"] = "chapter_review"
        else:
            state["pending_checkpoint"] = None
            state["current_stage"] = "freeze_c"
            result["chapter_length_plan"] = self.planner.prepare_chapter_length_plan(
                run_id=run_id,
                auto_confirm=True,
            )
            state["current_stage"] = "length_confirmed"
        self._save_workflow_state(run_id, state)
        return result

    def continue_after_chapter_review(self, *, run_id: str, artifact_path: str | None = None) -> dict[str, Any]:
        paths = self.planner.confirm_chapter_package(run_id=run_id, artifact_path=artifact_path)
        state = self.load_workflow_state(run_id=run_id) or {}
        pending_stage = str((state.get("pending_checkpoint") or {}).get("stage") or "")
        checkpoint_stage = "wait_chapter_review" if pending_stage == "wait_chapter_review" else "chapter_review"
        self._confirm_checkpoint(run_id=run_id, stage=checkpoint_stage, source="continue_after_chapter_review")
        state = self.load_workflow_state(run_id=run_id) or state
        mode = self._normalize_mode(str(state.get("product_mode") or BATCH_MODE))
        length_result = self.prepare_chapter_length_plan(
            run_id=run_id,
            product_mode=mode,
        )
        return {**paths, "chapter_length_plan": length_result}

    def prepare_chapter_length_plan(
        self,
        *,
        run_id: str,
        product_mode: str,
    ) -> dict[str, Any]:
        mode = self._normalize_mode(product_mode)
        result = self.planner.prepare_chapter_length_plan(
            run_id=run_id,
            auto_confirm=mode == AUTO_NOVEL_MODE,
        )
        state = self.load_workflow_state(run_id=run_id) or {}
        if mode in {ASSIST_MODE, BATCH_MODE}:
            checkpoint = self._write_checkpoint(
                run_id=run_id,
                stage="wait_length_review",
                artifact_path=str(self.run_writer.layout.run_dir(run_id) / "chapter_length_plan.json"),
                source="prepare_chapter_length_plan",
            )
            state["pending_checkpoint"] = checkpoint
            state["current_stage"] = "wait_length_review"
        else:
            state["pending_checkpoint"] = None
            state["current_stage"] = "length_confirmed"
        self._save_workflow_state(run_id, state)
        return result

    def continue_after_length_review(
        self,
        *,
        run_id: str,
        artifact_path: str | None = None,
        default_target_chars: int | None = None,
        chapter_overrides: Mapping[str, Mapping[str, Any]] | None = None,
    ) -> dict[str, str]:
        if default_target_chars is not None or chapter_overrides:
            self._apply_interactive_length_overrides(
                run_id=run_id,
                default_target_chars=default_target_chars,
                chapter_overrides=chapter_overrides or {},
            )
            artifact_path = None
        paths = self.planner.confirm_chapter_length_plan(run_id=run_id, artifact_path=artifact_path)
        self._confirm_checkpoint(run_id=run_id, stage="wait_length_review", source="continue_after_length_review")
        state = self.load_workflow_state(run_id=run_id) or {}
        state["current_stage"] = "length_confirmed"
        self._save_workflow_state(run_id, state)
        return paths

    def prepare_execution(
        self,
        conn: sqlite3.Connection,
        *,
        run_id: str,
        book_id: str,
        chapter_id: str,
        product_mode: str,
    ) -> dict[str, Any]:
        mode = self._normalize_mode(product_mode)
        result = self.executor.prepare_execution_input(
            conn,
            run_id=run_id,
            book_id=book_id,
            chapter_id=chapter_id,
            auto_confirm=mode == AUTO_NOVEL_MODE,
        )
        state = self.load_workflow_state(run_id=run_id) or self._base_state(run_id=run_id, book_id=book_id, product_mode=mode)
        state["current_chapter_id"] = chapter_id
        if mode == ASSIST_MODE:
            checkpoint = self._write_checkpoint(
                run_id=run_id,
                stage="freeze_d_review",
                artifact_path=str(self.run_writer.layout.run_dir(run_id) / "chapter_execution_input.json"),
                source="prepare_execution",
            )
            state["pending_checkpoint"] = checkpoint
            state["current_stage"] = "freeze_d_review"
        else:
            state["pending_checkpoint"] = None
            state["current_stage"] = "freeze_d"
        self._save_workflow_state(run_id, state)
        return result

    def continue_after_execution_review(self, *, run_id: str) -> dict[str, str]:
        paths = self.executor.confirm_freeze_d(run_id=run_id)
        self._confirm_checkpoint(run_id=run_id, stage="freeze_d_review", source="continue_after_execution_review")
        return paths

    def register_wait_chapter_acceptance(
        self,
        *,
        run_id: str,
        artifact_path: str | None = None,
        source: str = "register_wait_chapter_acceptance",
    ) -> dict[str, Any]:
        return self._set_pending_stage(
            run_id=run_id,
            stage="wait_chapter_acceptance",
            artifact_path=artifact_path,
            source=source,
        )

    def register_wait_length_review(
        self,
        *,
        run_id: str,
        artifact_path: str | None = None,
        source: str = "register_wait_length_review",
    ) -> dict[str, Any]:
        return self._set_pending_stage(
            run_id=run_id,
            stage="wait_length_review",
            artifact_path=artifact_path,
            source=source,
        )

    def register_wait_chapter_review(
        self,
        *,
        run_id: str,
        artifact_path: str | None = None,
        source: str = "register_wait_chapter_review",
    ) -> dict[str, Any]:
        return self._set_pending_stage(
            run_id=run_id,
            stage="wait_chapter_review",
            artifact_path=artifact_path,
            source=source,
        )

    def register_halted(
        self,
        *,
        run_id: str,
        artifact_path: str | None = None,
        source: str = "register_halted",
    ) -> dict[str, Any]:
        return self._set_terminal_stage(
            run_id=run_id,
            stage="halted",
            artifact_path=artifact_path,
            source=source,
        )

    def execute_current_chapter(
        self,
        conn: sqlite3.Connection,
        *,
        run_id: str,
        book_id: str,
        product_mode: str,
    ) -> dict[str, Any]:
        mode = self._normalize_mode(product_mode)
        commit_writeback = mode in {BATCH_MODE, AUTO_NOVEL_MODE}
        result = self.executor.execute_frozen_chapter(
            conn,
            run_id=run_id,
            book_id=book_id,
            commit_writeback=commit_writeback,
            auto_freeze_e=True,
        )
        state = self.load_workflow_state(run_id=run_id) or self._base_state(run_id=run_id, book_id=book_id, product_mode=mode)
        if result["canon_ready"]:
            state["failure_count"] = 0
            if bool(result.get("writeback_committed")):
                self._ensure_memory_writeback_artifact(
                    run_id=run_id,
                    payload=result.get("memory_writeback"),
                )
            self._route_chapter_acceptance_decision(
                run_id=run_id,
                state=state,
                mode=mode,
                source="execute_current_chapter",
            )
            self._sync_current_draft_retention_record(
                run_id=run_id,
                state=state,
                include_memory_writeback=bool(result.get("writeback_committed")),
            )
        else:
            failure_count = int(state.get("failure_count") or 0) + 1
            state["failure_count"] = failure_count
            rollback_event = self.rollback_manager.rollback_after_failure(
                run_id=run_id,
                failure_count=failure_count,
                reason="正文执行未通过 continuity 校验。",
            )
            state["last_rollback"] = rollback_event.to_dict()
            state["current_stage"] = rollback_event.target_freeze_stage
        self._save_workflow_state(run_id, state)
        return result

    def continue_after_chapter_acceptance(self, *, run_id: str) -> dict[str, Any]:
        state = self.load_workflow_state(run_id=run_id)
        if state is None:
            raise FileNotFoundError(f"workflow state not found for run_id={run_id}")
        review_payload = self._normalize_generation_review_decision_artifact(
            run_id=run_id,
            state=state,
        )
        if review_payload is not None:
            self._save_workflow_state(run_id, state)
        review_status = self._extract_generation_review_status(review_payload)
        pending_checkpoint = dict(state.get("pending_checkpoint") or {})
        if not review_status:
            if pending_checkpoint.get("stage") == "wait_chapter_acceptance":
                return pending_checkpoint
            outcome = self._route_chapter_acceptance_decision(
                run_id=run_id,
                state=state,
                mode=self._normalize_mode(str(state.get("product_mode") or "")),
                source="continue_after_chapter_acceptance",
                review_status="",
            )
            self._save_workflow_state(run_id, state)
            return outcome
        if pending_checkpoint.get("stage") == "wait_chapter_acceptance":
            self._confirm_checkpoint(
                run_id=run_id,
                stage="wait_chapter_acceptance",
                source="continue_after_chapter_acceptance",
            )
            state = self.load_workflow_state(run_id=run_id) or state
        mode = self._normalize_mode(str(state.get("product_mode") or ""))
        outcome = self._route_chapter_acceptance_decision(
            run_id=run_id,
            state=state,
            mode=mode,
            source="continue_after_chapter_acceptance",
            review_status=review_status,
        )
        self._save_workflow_state(run_id, state)
        return outcome

    def approve_writeback(self, conn: sqlite3.Connection, *, run_id: str, book_id: str) -> dict[str, Any]:
        execution_input = self._load_run_data(run_id, "chapter_execution_input.json")
        continuity_report = self._load_run_data(run_id, "continuity_report.json")
        draft_text = (self.run_writer.layout.run_dir(run_id) / "draft.md").read_text(encoding="utf-8")
        report = (
            self.executor._check_continuity_extended(  # noqa: SLF001
                conn,
                book_id=book_id,
                execution_input=execution_input,
                draft_md=draft_text,
            )
            if not continuity_report.get("canon_ready")
            else self._coerce_continuity_report(continuity_report)
        )
        gated_report = self.executor.refresh_writeback_gate(
            run_id=run_id,
            chapter_id=str(execution_input.get("chapter_id") or ""),
            continuity_report=report,
        )
        if not gated_report.accepted_for_writeback:
            raise ValueError(
                "writeback approval requires generation_review_decision.status=accepted"
            )
        state = self.load_workflow_state(run_id=run_id) or {}
        review_payload = self._normalize_generation_review_decision_artifact(
            run_id=run_id,
            state=state,
        )
        if review_payload is not None:
            self._save_workflow_state(run_id, state)
        result = self.executor.apply_memory_writeback(
            conn,
            run_id=run_id,
            book_id=book_id,
            execution_input=execution_input,
            draft_md=draft_text,
            continuity_report=gated_report,
        )
        result_payload = result.to_dict()
        self._ensure_memory_writeback_artifact(
            run_id=run_id,
            payload=result_payload,
        )
        state = self.load_workflow_state(run_id=run_id) or state
        self._sync_current_draft_retention_record(
            run_id=run_id,
            state=state,
            include_memory_writeback=True,
        )
        self._confirm_checkpoint(run_id=run_id, stage="writeback_review", source="approve_writeback")
        freeze_e_paths = self._write_freeze_e_after_writeback(
            run_id=run_id,
            execution_input=execution_input,
            continuity_report=gated_report.to_dict(),
            state_delta=gated_report.state_delta,
            memory_writeback=result_payload,
        )
        self._set_terminal_stage(
            run_id=run_id,
            stage="completed",
            artifact_path=freeze_e_paths.get("freeze.json") or str(self.run_writer.layout.run_dir(run_id)),
            source="approve_writeback",
        )
        accepted_chapters_path = self.run_writer.rebuild_accepted_chapters_markdown(run_id)
        result_payload["accepted_chapters_path"] = str(accepted_chapters_path)
        return result_payload

    def resume_from_latest_checkpoint(self, *, run_id: str) -> dict[str, Any] | None:
        state = self.load_workflow_state(run_id=run_id)
        if not state:
            return None
        pending_checkpoint = dict(state.get("pending_checkpoint") or {})
        if not pending_checkpoint:
            return None
        if not self._is_resumable_stage(str(pending_checkpoint.get("stage") or "")):
            return None
        return pending_checkpoint

    def register_character_cast_change(self, *, run_id: str, reason: str) -> dict[str, Any]:
        event = self.rollback_manager.cascade_for_character_cast_change(run_id=run_id, reason=reason)
        state = self.load_workflow_state(run_id=run_id) or {}
        state["last_rollback"] = event.to_dict()
        state["current_stage"] = "freeze_a"
        state["pending_checkpoint"] = None
        self._save_workflow_state(run_id, state)
        return event.to_dict()

    def request_scoped_artifact_revision(
        self,
        *,
        run_id: str,
        user_feedback: str,
        request_id: str | None = None,
        target_stage: str | None = None,
        target_artifact_type: str | None = None,
        target_artifact_path: str | None = None,
    ) -> dict[str, Any]:
        state = self.load_workflow_state(run_id=run_id)
        if state is None:
            raise FileNotFoundError(f"workflow state not found for run_id={run_id}")
        request, context, current_artifact, allowed_context = self._build_scoped_revision_request(
            run_id=run_id,
            state=state,
            user_feedback=user_feedback,
            request_id=request_id,
            target_stage=target_stage,
            target_artifact_type=target_artifact_type,
            target_artifact_path=target_artifact_path,
        )
        policy = validate_scoped_revision_request(request, context)
        self.revision_store.write_request(request)
        llm_input = ScopedArtifactRevisionLLMInput(
            request=request.to_dict(),
            policy={
                "review_stage": policy.review_stage,
                "target_artifact_type": request.target_artifact_type,
                "allowed_fields": list(policy.allowed_fields_for(request.target_artifact_type)),
                "required_fields": list(policy.required_fields_for(request.target_artifact_type)),
                "forbidden_targets": list(policy.forbidden_targets),
            },
            target_artifact=current_artifact,
            allowed_context=allowed_context,
            user_feedback=request.user_feedback,
        )
        try:
            raw_candidate = self.revision_adapter.generate_candidate(llm_input)
            candidate = (
                raw_candidate
                if isinstance(raw_candidate, ScopedArtifactRevisionResult)
                else ScopedArtifactRevisionResult.from_dict(raw_candidate)
            )
        except (RevisionResultError, ScopeGuardError, TypeError, ValueError, json.JSONDecodeError) as exc:
            result = self._persist_scoped_revision_result(
                request=request,
                current_artifact=current_artifact,
                candidate=self._failed_scoped_revision_candidate(
                    request=request,
                    current_artifact=current_artifact,
                    error=exc,
                ),
                status="validation_failed",
                validation={"ok": False, "errors": [str(exc)]},
            )
            self._remember_pending_scoped_revision(state=state, result=result)
            self._save_workflow_state(run_id, state)
            return {
                **result.to_dict(),
                "diff": self._read_diff_text(result.diff_path),
                "recovery_suggestions": self._scoped_revision_recovery_suggestions(),
            }
        try:
            self._validate_scoped_revision_candidate(
                request=request,
                result=candidate,
                context=context,
                allowed_context=allowed_context,
            )
        except (RevisionResultError, ScopeGuardError) as exc:
            result = self._persist_scoped_revision_result(
                request=request,
                current_artifact=current_artifact,
                candidate=candidate,
                status="validation_failed",
                validation={"ok": False, "errors": [str(exc)]},
            )
            self._remember_pending_scoped_revision(state=state, result=result)
            self._save_workflow_state(run_id, state)
            return {
                **result.to_dict(),
                "diff": self._read_diff_text(result.diff_path),
                "recovery_suggestions": self._scoped_revision_recovery_suggestions(),
            }
        result = self._persist_scoped_revision_result(
            request=request,
            current_artifact=current_artifact,
            candidate=candidate,
            status="candidate",
            validation={
                "ok": True,
                "checks": ["schema", "scope", "references", "upstream_freeze_constraints"],
            },
        )
        self._remember_pending_scoped_revision(state=state, result=result)
        self._save_workflow_state(run_id, state)
        return {**result.to_dict(), "diff": self._read_diff_text(result.diff_path)}

    def apply_scoped_artifact_revision(self, *, run_id: str, request_id: str) -> dict[str, Any]:
        state = self.load_workflow_state(run_id=run_id)
        if state is None:
            raise FileNotFoundError(f"workflow state not found for run_id={run_id}")
        request = self.revision_store.read_request(run_id, request_id)
        result = self.revision_store.read_result(run_id, request_id)
        if result.status != "candidate":
            raise RevisionResultError("only validated candidate revisions can be applied")
        if result.revised_artifact is None:
            raise RevisionResultError("applying JSON Patch candidates is not supported in this workflow phase")
        current_artifact = self._load_artifact_payload(Path(request.target_artifact_path))
        context = self._build_scoped_review_context(
            run_id=run_id,
            state=state,
            target_stage=request.target_stage,
            target_artifact_type=request.target_artifact_type,
            target_artifact_path=request.target_artifact_path,
            target_artifact=current_artifact,
        )
        allowed_context = self._build_scoped_revision_allowed_context(
            run_id=run_id,
            target_stage=request.target_stage,
            target_artifact_type=request.target_artifact_type,
            target_artifact=current_artifact,
        )
        self._validate_scoped_revision_candidate(
            request=request,
            result=result,
            context=context,
            allowed_context=allowed_context,
        )
        artifact_path = self._write_current_target_artifact(
            run_id=run_id,
            target_artifact_path=request.target_artifact_path,
            payload=result.revised_artifact,
        )
        rollback_event = self._propagate_revision_rollback(run_id=run_id, stage=request.target_stage)
        applied = self._persist_scoped_revision_result(
            request=request,
            current_artifact=current_artifact,
            candidate=result,
            status="applied",
            validation={**result.validation, "ok": True, "applied": True},
        )
        state["current_stage"] = request.target_stage
        pending_checkpoint = dict(state.get("pending_checkpoint") or {})
        if pending_checkpoint:
            pending_checkpoint["stage"] = request.target_stage
            pending_checkpoint["artifact_path"] = str(artifact_path)
            state["pending_checkpoint"] = pending_checkpoint
        state["pending_scoped_revision"] = None
        state["last_scoped_revision"] = {
            "request_id": request.request_id,
            "revision_id": applied.revision_id,
            "status": "applied",
            "target_stage": request.target_stage,
            "target_artifact_path": str(artifact_path),
            "rollback": rollback_event.to_dict(),
        }
        self._save_workflow_state(run_id, state)
        return {
            **applied.to_dict(),
            "artifact_path": str(artifact_path),
            "rollback": rollback_event.to_dict(),
            "workflow_state": self.load_workflow_state(run_id=run_id) or {},
            "diff": self._read_diff_text(applied.diff_path),
        }

    def load_workflow_state(self, *, run_id: str) -> dict[str, Any] | None:
        path = self.run_writer.layout.run_dir(run_id) / "workflow_state.json"
        if not path.exists():
            return None
        raw = json.loads(path.read_text(encoding="utf-8"))
        payload = raw.get("data") if isinstance(raw, dict) else raw
        return dict(payload) if isinstance(payload, dict) else None

    def _base_state(self, *, run_id: str, book_id: str, product_mode: str) -> dict[str, Any]:
        return {
            "run_id": run_id,
            "book_id": book_id,
            "product_mode": product_mode,
            "confirmation_points": MODE_CONFIRMATION_POINTS[product_mode],
            "current_stage": "initialized",
            "current_chapter_id": "",
            "current_draft_id": "",
            "current_decision_id": "",
            "draft_sequence": 0,
            "pending_checkpoint": None,
            "terminal_stage": None,
            "failure_count": 0,
            "last_rollback": None,
            "updated_at": _utc_now(),
        }

    def _save_workflow_state(self, run_id: str, state: Mapping[str, Any]) -> None:
        payload = dict(state)
        payload["updated_at"] = _utc_now()
        self.run_writer.write_json(run_id, "workflow_state.json", payload)

    def _build_scoped_revision_request(
        self,
        *,
        run_id: str,
        state: Mapping[str, Any],
        user_feedback: str,
        request_id: str | None,
        target_stage: str | None,
        target_artifact_type: str | None,
        target_artifact_path: str | None,
    ) -> tuple[ScopedArtifactRevisionRequest, ScopedArtifactReviewContext, dict[str, Any], dict[str, Any]]:
        checkpoint = dict(state.get("pending_checkpoint") or {})
        stage = str(target_stage or checkpoint.get("stage") or state.get("current_stage") or "").strip()
        artifact_path = str(target_artifact_path or checkpoint.get("artifact_path") or "").strip()
        if not artifact_path:
            raise ScopeGuardError("current review artifact path is required for scoped revision")
        artifact_type = str(target_artifact_type or self._infer_revision_artifact_type(stage, artifact_path)).strip()
        current_artifact = self._load_artifact_payload(Path(artifact_path))
        context = self._build_scoped_review_context(
            run_id=run_id,
            state=state,
            target_stage=stage,
            target_artifact_type=artifact_type,
            target_artifact_path=artifact_path,
            target_artifact=current_artifact,
        )
        allowed_context = self._build_scoped_revision_allowed_context(
            run_id=run_id,
            target_stage=stage,
            target_artifact_type=artifact_type,
            target_artifact=current_artifact,
        )
        scope = {
            "target_artifact_path": artifact_path,
            "target_artifact_type": artifact_type,
            "current_stage": stage,
            "current_batch_id": context.current_batch_id,
            "current_chapter_id": context.current_chapter_id,
            "allowed_chapter_ids": list(context.allowed_chapter_ids),
        }
        request = ScopedArtifactRevisionRequest(
            request_id=request_id or f"sar-{uuid.uuid4().hex[:12]}",
            run_id=run_id,
            target_stage=stage,
            target_artifact_type=artifact_type,
            target_artifact_path=artifact_path,
            user_feedback=user_feedback,
            scope=scope,
            created_at=_utc_now(),
        )
        return request, context, current_artifact, allowed_context

    def _build_scoped_review_context(
        self,
        *,
        run_id: str,
        state: Mapping[str, Any],
        target_stage: str,
        target_artifact_type: str,
        target_artifact_path: str,
        target_artifact: Mapping[str, Any],
    ) -> ScopedArtifactReviewContext:
        chapter_ids = self._artifact_chapter_ids(target_artifact)
        current_chapter_id = str(state.get("current_chapter_id") or target_artifact.get("chapter_id") or "").strip()
        if not current_chapter_id and len(chapter_ids) == 1:
            current_chapter_id = chapter_ids[0]
        return ScopedArtifactReviewContext(
            run_id=run_id,
            current_stage=target_stage,
            current_artifact_type=target_artifact_type,
            current_artifact_path=target_artifact_path,
            run_dir=str(self.run_writer.layout.run_dir(run_id)),
            current_batch_id=str(target_artifact.get("batch_id") or "").strip(),
            current_chapter_id=current_chapter_id,
            allowed_chapter_ids=tuple(chapter_ids),
        )

    def _build_scoped_revision_allowed_context(
        self,
        *,
        run_id: str,
        target_stage: str,
        target_artifact_type: str,
        target_artifact: Mapping[str, Any],
    ) -> dict[str, Any]:
        run_dir = self.run_writer.layout.run_dir(run_id)
        context: dict[str, Any] = {
            "stage": target_stage,
            "target_artifact_type": target_artifact_type,
            "source_paths": [
                str(run_dir / self._artifact_filename_for_type(target_artifact_type)),
                self._artifact_filename_for_type(target_artifact_type),
                *self._artifact_source_paths(target_artifact),
            ],
            "upstream_freezes": {},
        }
        if target_stage == "batch_review":
            context["current_batch"] = {
                "batch_id": target_artifact.get("batch_id", ""),
                "scope_start": target_artifact.get("scope_start", ""),
                "scope_end": target_artifact.get("scope_end", ""),
            }
            context["upstream_freezes"]["freeze_a"] = self._summarize_frozen_artifact(
                run_id,
                "freeze_a",
                "book_continuation_plan.json",
                fields=("book_id", "continuation_goal", "ending_direction", "stage_highlights"),
            )
        elif target_stage in {"chapter_review", "wait_chapter_review"}:
            context["current_chapter_ids"] = self._artifact_chapter_ids(target_artifact)
            context["upstream_freezes"]["freeze_b"] = self._summarize_frozen_artifact(
                run_id,
                "freeze_b",
                "batch_plan.json",
                fields=("batch_id", "book_id", "scope_start", "scope_end", "batch_goal", "planned_character_beats"),
            )
            context["allowed_character_summary"] = self._summarize_frozen_artifact(
                run_id,
                "freeze_a",
                "character_cast_plan.json",
                fields=("planned_characters", "must_not_consume"),
                optional=True,
            )
        elif target_stage == "wait_length_review":
            context["upstream_freezes"]["freeze_c"] = self._summarize_frozen_artifact(
                run_id,
                "freeze_c",
                "chapter_package.json",
                fields=("package_id", "batch_id", "chapters"),
            )
            context["length_strategy"] = {
                "default_target_chars": target_artifact.get("default_target_chars", ""),
                "default_min_chars": target_artifact.get("default_min_chars", ""),
                "default_max_chars": target_artifact.get("default_max_chars", ""),
            }
        elif target_stage == "freeze_d_review":
            context["upstream_freezes"]["freeze_c"] = self._summarize_frozen_artifact(
                run_id,
                "freeze_c",
                "chapter_package.json",
                fields=("package_id", "batch_id", "chapters"),
            )
            context["frozen_brief_and_budget"] = {
                "chapter_id": target_artifact.get("chapter_id", ""),
                "chapter_brief": target_artifact.get("chapter_brief", {}),
                "length_budget": target_artifact.get("length_budget", {}),
            }
            context["writer_input_summary"] = {
                "fact_input_keys": sorted((target_artifact.get("fact_inputs") or {}).keys())
                if isinstance(target_artifact.get("fact_inputs"), Mapping)
                else [],
                "style_reference_count": len((target_artifact.get("style_reference_bundle") or {}).get("references") or [])
                if isinstance(target_artifact.get("style_reference_bundle"), Mapping)
                else 0,
            }
        return context

    def _validate_scoped_revision_candidate(
        self,
        *,
        request: ScopedArtifactRevisionRequest,
        result: ScopedArtifactRevisionResult,
        context: ScopedArtifactReviewContext,
        allowed_context: Mapping[str, Any],
    ) -> None:
        validate_scoped_revision_result(request, result, context)
        if result.revised_artifact is None:
            raise RevisionResultError("revision candidates must include a complete revised_artifact")
        validate_scoped_revision_references(
            revised_artifact=result.revised_artifact,
            allowed_context=allowed_context,
        )
        validate_upstream_freeze_constraints(
            request=request,
            revised_artifact=result.revised_artifact,
            allowed_context=allowed_context,
        )

    def _persist_scoped_revision_result(
        self,
        *,
        request: ScopedArtifactRevisionRequest,
        current_artifact: Mapping[str, Any],
        candidate: ScopedArtifactRevisionResult,
        status: str,
        validation: Mapping[str, Any],
    ) -> ScopedArtifactRevisionResult:
        diff_path = ""
        diff_text = ""
        if candidate.revised_artifact is not None:
            diff_text = build_readable_artifact_diff(
                original_artifact=current_artifact,
                revised_artifact=candidate.revised_artifact,
                from_label="current artifact",
                to_label=f"candidate {candidate.revision_id}",
            )
            diff_path = str(self.revision_store.write_diff(request, diff_text))
        result = ScopedArtifactRevisionResult(
            revision_id=candidate.revision_id,
            request_id=request.request_id,
            status=status,
            target_artifact_type=request.target_artifact_type,
            target_artifact_path=request.target_artifact_path,
            change_summary=candidate.change_summary or self._summarize_diff_text(diff_text),
            validation=dict(validation),
            created_at=candidate.created_at or _utc_now(),
            revised_artifact=candidate.revised_artifact,
            patch=candidate.patch,
            diff_path=diff_path,
        )
        self.revision_store.write_result(result, request=request)
        return result

    def _failed_scoped_revision_candidate(
        self,
        *,
        request: ScopedArtifactRevisionRequest,
        current_artifact: Mapping[str, Any],
        error: Exception,
    ) -> ScopedArtifactRevisionResult:
        return ScopedArtifactRevisionResult(
            revision_id=f"rev-failed-{request.request_id}",
            request_id=request.request_id,
            status="validation_failed",
            target_artifact_type=request.target_artifact_type,
            target_artifact_path=request.target_artifact_path,
            change_summary=f"候选修订未通过结构化校验：{error}",
            validation={"ok": False, "errors": [str(error)]},
            created_at=_utc_now(),
            revised_artifact=dict(current_artifact),
        )

    def _scoped_revision_recovery_suggestions(self) -> list[str]:
        return [
            "修改反馈后重试，且只描述当前审阅产物需要怎样调整。",
            "如果需要精确改 JSON 字段，可选择手动编辑当前产物。",
            "不要要求修改 Memory、KB、系统 prompt、workflow state、其他批次或其他章节。",
        ]

    def _remember_pending_scoped_revision(
        self,
        *,
        state: dict[str, Any],
        result: ScopedArtifactRevisionResult,
    ) -> None:
        state["current_stage"] = result.validation.get("target_stage") or state.get("current_stage")
        state["pending_scoped_revision"] = {
            "request_id": result.request_id,
            "revision_id": result.revision_id,
            "status": result.status,
            "target_artifact_type": result.target_artifact_type,
            "target_artifact_path": result.target_artifact_path,
            "change_summary": result.change_summary,
            "diff_path": result.diff_path,
        }

    def _infer_revision_artifact_type(self, stage: str, artifact_path: str) -> str:
        path_name = Path(artifact_path).name
        policy = get_revision_stage_policy(stage)
        for artifact_type in policy.artifact_types:
            if path_name in policy.allowed_filenames_for(artifact_type):
                if artifact_type == "ChapterBrief" and path_name == "chapter_package.json":
                    continue
                return artifact_type
        if len(policy.artifact_types) == 1:
            return policy.artifact_types[0]
        raise ScopeGuardError(f"cannot infer scoped revision artifact type for {stage}: {artifact_path}")

    def _artifact_filename_for_type(self, artifact_type: str) -> str:
        filenames = {
            "BatchPlan": "batch_plan.json",
            "ChapterPackage": "chapter_package.json",
            "ChapterBrief": "chapter_brief.json",
            "ChapterLengthPlan": "chapter_length_plan.json",
            "ChapterExecutionInput": "chapter_execution_input.json",
        }
        return filenames.get(artifact_type, "")

    def _load_artifact_payload(self, path: Path) -> dict[str, Any]:
        raw = json.loads(path.read_text(encoding="utf-8"))
        payload = raw.get("data") if isinstance(raw, Mapping) else raw
        if not isinstance(payload, Mapping):
            raise ScopeGuardError(f"target artifact is not a JSON object: {path}")
        return dict(payload)

    def _summarize_frozen_artifact(
        self,
        run_id: str,
        freeze_stage: str,
        artifact_name: str,
        *,
        fields: tuple[str, ...],
        optional: bool = False,
    ) -> dict[str, Any]:
        record = self.run_writer.get_freeze_record(run_id, freeze_stage)
        if record is None:
            if optional:
                return {}
            raise RevisionResultError(f"required upstream freeze is missing: {freeze_stage}")
        for artifact in record.artifacts:
            if artifact.name == artifact_name:
                payload = self._load_artifact_payload(Path(artifact.path))
                summary = {field: payload.get(field) for field in fields if field in payload}
                summary["path"] = f"{freeze_stage}/{artifact_name}"
                summary["source_path"] = f"freezes/{freeze_stage}/{artifact_name}"
                return summary
        if optional:
            return {}
        raise RevisionResultError(f"required upstream artifact is missing: {freeze_stage}/{artifact_name}")

    def _artifact_chapter_ids(self, artifact: Mapping[str, Any]) -> list[str]:
        ids: list[str] = []

        def visit(value: Any) -> None:
            if isinstance(value, Mapping):
                chapter_id = str(value.get("chapter_id") or "").strip()
                if chapter_id and chapter_id not in ids:
                    ids.append(chapter_id)
                for child in value.values():
                    visit(child)
            elif isinstance(value, list):
                for child in value:
                    visit(child)

        visit(artifact)
        return ids

    def _artifact_source_paths(self, artifact: Mapping[str, Any]) -> list[str]:
        paths: list[str] = []

        def visit(value: Any) -> None:
            if isinstance(value, Mapping):
                for key, child in value.items():
                    if str(key) in {"path", "source_path", "artifact_path"}:
                        text = str(child or "").strip()
                        if text and text not in paths:
                            paths.append(text)
                    visit(child)
            elif isinstance(value, list):
                for child in value:
                    visit(child)

        visit(artifact)
        return paths

    def _write_current_target_artifact(
        self,
        *,
        run_id: str,
        target_artifact_path: str,
        payload: Mapping[str, Any],
    ) -> Path:
        run_dir = self.run_writer.layout.run_dir(run_id).resolve(strict=False)
        target_path = Path(target_artifact_path).expanduser().resolve(strict=False)
        relative = target_path.relative_to(run_dir)
        return self.run_writer.write_json(run_id, relative.as_posix(), dict(payload))

    def _propagate_revision_rollback(self, *, run_id: str, stage: str):
        rollback_targets = {
            "freeze_a_review": "freeze_a",
            "batch_review": "freeze_b",
            "chapter_review": "freeze_c",
            "wait_chapter_review": "freeze_c",
            "wait_length_review": "freeze_c",
            "freeze_d_review": "freeze_d",
        }
        target_freeze = rollback_targets.get(stage)
        if target_freeze is None:
            raise ScopeGuardError(f"unsupported scoped revision rollback stage: {stage}")
        event = self.rollback_manager.rollback_to_stage(
            run_id=run_id,
            target_freeze_stage=target_freeze,
            reason=f"Scoped Artifact Revision applied at {stage}.",
            trigger="scoped_artifact_revision",
        )
        if stage in {"chapter_review", "wait_chapter_review", "wait_length_review", "freeze_d_review"}:
            self.run_writer.mark_active_drafts_invalidated(
                run_id,
                reason=f"Scoped Artifact Revision applied at {stage}.",
            )
        return event

    def _summarize_diff_text(self, diff_text: str) -> str:
        changed = [line for line in diff_text.splitlines() if line.startswith(("+", "-")) and not line.startswith(("+++", "---"))]
        return f"候选修订包含 {len(changed)} 行结构化变更。"

    def _read_diff_text(self, diff_path: str) -> str:
        if not diff_path:
            return ""
        path = Path(diff_path)
        return path.read_text(encoding="utf-8") if path.exists() else ""

    def _normalize_mode(self, product_mode: str) -> str:
        normalized = str(product_mode or "").strip().lower()
        if normalized not in PRODUCT_MODES:
            raise ValueError(f"unsupported product mode: {product_mode}")
        return normalized

    def _is_resumable_stage(self, stage: str) -> bool:
        return stage in RESUMABLE_WORKFLOW_STAGES

    def _set_pending_stage(
        self,
        *,
        run_id: str,
        stage: str,
        artifact_path: str | None,
        source: str,
    ) -> dict[str, Any]:
        state = self.load_workflow_state(run_id=run_id)
        if state is None:
            raise FileNotFoundError(f"workflow state not found for run_id={run_id}")
        checkpoint = self._write_checkpoint(
            run_id=run_id,
            stage=stage,
            artifact_path=artifact_path or str(self.run_writer.layout.run_dir(run_id)),
            source=source,
        )
        state["pending_checkpoint"] = checkpoint
        state["terminal_stage"] = None
        state["current_stage"] = stage
        self._save_workflow_state(run_id, state)
        return checkpoint

    def _set_terminal_stage(
        self,
        *,
        run_id: str,
        stage: str,
        artifact_path: str | None,
        source: str,
    ) -> dict[str, Any]:
        state = self.load_workflow_state(run_id=run_id)
        if state is None:
            raise FileNotFoundError(f"workflow state not found for run_id={run_id}")
        terminal_stage = {
            "stage": stage,
            "artifact_path": artifact_path or str(self.run_writer.layout.run_dir(run_id)),
            "source": source,
        }
        state["pending_checkpoint"] = None
        state["terminal_stage"] = terminal_stage
        state["current_stage"] = stage
        self._save_workflow_state(run_id, state)
        return terminal_stage

    def _route_chapter_acceptance_decision(
        self,
        *,
        run_id: str,
        state: dict[str, Any],
        mode: str,
        source: str,
        review_status: str | None = None,
    ) -> dict[str, Any]:
        status = (review_status or self._load_generation_review_status(run_id)).strip().lower()
        run_dir = self.run_writer.layout.run_dir(run_id)
        continuity_report_path = str(run_dir / "continuity_report.json")
        decision_path = str(run_dir / "generation_review_decision.json")
        if not status:
            decision_payload = self._provision_generation_review_decision_artifact(
                run_id=run_id,
                state=state,
            )
            state["current_chapter_id"] = str(decision_payload.get("chapter_id") or state.get("current_chapter_id") or "")
            state["current_draft_id"] = str(decision_payload.get("draft_id") or "")
            state["current_decision_id"] = str(decision_payload.get("decision_id") or "")
            checkpoint = self._write_checkpoint(
                run_id=run_id,
                stage="wait_chapter_acceptance",
                artifact_path=decision_path,
                source=source,
            )
            state["pending_checkpoint"] = checkpoint
            state["terminal_stage"] = None
            state["current_stage"] = "wait_chapter_acceptance"
            return checkpoint
        if status == "accepted":
            state["pending_checkpoint"] = None
            state["terminal_stage"] = None
            state["current_stage"] = "freeze_e"
            if mode == ASSIST_MODE:
                checkpoint = self._write_checkpoint(
                    run_id=run_id,
                    stage="writeback_review",
                    artifact_path=continuity_report_path,
                    source=source,
                )
                state["pending_checkpoint"] = checkpoint
                state["terminal_stage"] = None
                state["current_stage"] = "writeback_review"
                return checkpoint
            return {"stage": "freeze_e", "artifact_path": continuity_report_path, "source": source}
        if status == "revise_length":
            self._apply_length_plan_update(run_id=run_id)
            checkpoint = self._write_checkpoint(
                run_id=run_id,
                stage="wait_length_review",
                artifact_path=str(run_dir / "chapter_length_plan.json"),
                source=source,
            )
            state["pending_checkpoint"] = checkpoint
            state["terminal_stage"] = None
            state["current_stage"] = "wait_length_review"
            return checkpoint
        if status == "replan_chapter":
            checkpoint = self._write_checkpoint(
                run_id=run_id,
                stage="wait_chapter_review",
                artifact_path=str(run_dir / "chapter_package.json"),
                source=source,
            )
            state["pending_checkpoint"] = checkpoint
            state["terminal_stage"] = None
            state["current_stage"] = "wait_chapter_review"
            return checkpoint
        if status == "discarded":
            state["pending_checkpoint"] = None
            state["terminal_stage"] = {
                "stage": "halted",
                "artifact_path": decision_path,
                "source": source,
            }
            state["current_stage"] = "halted"
            return dict(state["terminal_stage"])
        raise ValueError(f"unsupported generation review status: {status}")

    def _write_checkpoint(self, *, run_id: str, stage: str, artifact_path: str, source: str) -> dict[str, Any]:
        checkpoints = self._load_checkpoints(run_id)
        checkpoint = WorkflowCheckpoint(
            checkpoint_id=f"{stage}-{len(checkpoints) + 1:02d}",
            stage=stage,
            status="pending",
            artifact_path=artifact_path,
            source=source,
        )
        checkpoints.append(checkpoint)
        self.run_writer.write_json(run_id, "workflow_checkpoints.json", {"checkpoints": [item.to_dict() for item in checkpoints]})
        return checkpoint.to_dict()

    def _confirm_checkpoint(self, *, run_id: str, stage: str, source: str) -> None:
        checkpoints = self._load_checkpoints(run_id)
        updated: list[WorkflowCheckpoint] = []
        latest: dict[str, Any] | None = None
        for checkpoint in checkpoints:
            if checkpoint.stage == stage and checkpoint.status == "pending":
                checkpoint.status = "confirmed"
                checkpoint.confirmed_at = _utc_now()
                checkpoint.source = source
                latest = checkpoint.to_dict()
            updated.append(checkpoint)
        self.run_writer.write_json(run_id, "workflow_checkpoints.json", {"checkpoints": [item.to_dict() for item in updated]})
        state = self.load_workflow_state(run_id=run_id) or {}
        state["pending_checkpoint"] = None
        state["terminal_stage"] = None
        if latest is not None:
            state["last_confirmed_checkpoint"] = latest
        self._save_workflow_state(run_id, state)

    def _load_checkpoints(self, run_id: str) -> list[WorkflowCheckpoint]:
        path = self.run_writer.layout.run_dir(run_id) / "workflow_checkpoints.json"
        if not path.exists():
            return []
        raw = json.loads(path.read_text(encoding="utf-8"))
        payload = raw.get("data") if isinstance(raw, dict) else raw
        checkpoints: list[WorkflowCheckpoint] = []
        if isinstance(payload, dict):
            for item in payload.get("checkpoints") or []:
                if isinstance(item, dict):
                    checkpoints.append(
                        WorkflowCheckpoint(
                            checkpoint_id=str(item.get("checkpoint_id") or ""),
                            stage=str(item.get("stage") or ""),
                            status=str(item.get("status") or ""),
                            artifact_path=str(item.get("artifact_path") or ""),
                            source=str(item.get("source") or ""),
                            confirmed_at=str(item.get("confirmed_at") or ""),
                        )
                    )
        return checkpoints

    def _load_run_data(self, run_id: str, name: str) -> dict[str, Any]:
        path = self.run_writer.layout.run_dir(run_id) / name
        raw = json.loads(path.read_text(encoding="utf-8"))
        payload = raw.get("data") if isinstance(raw, dict) else raw
        return dict(payload) if isinstance(payload, dict) else {}

    def _load_optional_run_data(self, run_id: str, name: str) -> dict[str, Any] | None:
        path = self.run_writer.layout.run_dir(run_id) / name
        if not path.exists():
            return None
        raw = json.loads(path.read_text(encoding="utf-8"))
        payload = raw.get("data") if isinstance(raw, dict) else raw
        return dict(payload) if isinstance(payload, dict) else None

    def _load_generation_review_status(self, run_id: str) -> str:
        return self._extract_generation_review_status(
            self._load_optional_run_data(run_id, "generation_review_decision.json")
        )

    def _extract_generation_review_status(self, payload: Mapping[str, Any] | None) -> str:
        if not isinstance(payload, Mapping):
            return ""
        return str(payload.get("status") or "").strip().lower()

    def _normalize_generation_review_decision_artifact(
        self,
        *,
        run_id: str,
        state: dict[str, Any],
    ) -> dict[str, Any] | None:
        payload = self._load_optional_run_data(run_id, "generation_review_decision.json")
        if payload is None:
            return None
        chapter_id = self._resolve_review_chapter_id(run_id=run_id, state=state, payload=payload)
        draft_id = str(payload.get("draft_id") or state.get("current_draft_id") or "").strip()
        decision_id = str(payload.get("decision_id") or "").strip()
        if draft_id and not decision_id:
            decision_id = self._build_review_decision_id(chapter_id=chapter_id, draft_id=draft_id)
        defaults = {
            "schema_version": "1.0",
            "decision_id": decision_id,
            "run_id": run_id,
            "chapter_id": chapter_id,
            "draft_id": draft_id,
            "reviewer_type": "user",
        }
        normalized = self._merge_generation_review_defaults(payload=payload, defaults=defaults)
        self.run_writer.write_generation_review_decision(
            run_id,
            normalized,
            defaults=defaults,
        )
        self._sync_generation_review_rework_artifacts(run_id=run_id, decision_payload=normalized)
        self._sync_draft_retention_record(run_id=run_id, decision_payload=normalized)
        if chapter_id:
            state["current_chapter_id"] = chapter_id
        if draft_id:
            state["current_draft_id"] = draft_id
        if decision_id:
            state["current_decision_id"] = decision_id
            state["draft_sequence"] = max(int(state.get("draft_sequence") or 0), self._draft_sequence_from_id(draft_id))
        return normalized

    def _provision_generation_review_decision_artifact(
        self,
        *,
        run_id: str,
        state: dict[str, Any],
    ) -> dict[str, Any]:
        existing = self._load_optional_run_data(run_id, "generation_review_decision.json") or {}
        chapter_id = self._resolve_review_chapter_id(run_id=run_id, state=state, payload=existing)
        existing_status = self._extract_generation_review_status(existing)
        existing_draft_id = str(existing.get("draft_id") or "").strip()
        reuse_pending_draft = (
            bool(existing_draft_id)
            and not existing_status
            and str(existing.get("chapter_id") or "").strip() == chapter_id
        )
        if reuse_pending_draft:
            draft_id = existing_draft_id
        else:
            draft_id = self._next_review_draft_id(state=state)
        previous_draft_id = (
            existing_draft_id
            if existing_draft_id and existing_draft_id != draft_id and str(existing.get("chapter_id") or "").strip() == chapter_id
            else ""
        )
        decision_id = str(existing.get("decision_id") or "").strip()
        if not decision_id or not reuse_pending_draft:
            decision_id = self._build_review_decision_id(chapter_id=chapter_id, draft_id=draft_id)
        defaults = {
            "schema_version": "1.0",
            "decision_id": decision_id,
            "run_id": run_id,
            "chapter_id": chapter_id,
            "draft_id": draft_id,
            "status": "",
            "reason_code": "",
            "feedback_text": "",
            "next_action_checkpoint": "",
            "length_plan_update": None,
            "chapter_replan_request": None,
            "supersedes_draft_id": previous_draft_id,
            "reviewer_type": "user",
            "created_at": _utc_now(),
        }
        pending_payload = self._merge_generation_review_defaults(
            payload=existing if reuse_pending_draft else {},
            defaults=defaults,
        )
        self.run_writer.write_generation_review_decision(
            run_id,
            pending_payload,
            defaults=defaults,
        )
        self._sync_generation_review_rework_artifacts(run_id=run_id, decision_payload=pending_payload)
        self._sync_draft_retention_record(run_id=run_id, decision_payload=pending_payload)
        state["current_chapter_id"] = chapter_id
        state["current_draft_id"] = draft_id
        state["current_decision_id"] = decision_id
        return pending_payload

    def _resolve_review_chapter_id(
        self,
        *,
        run_id: str,
        state: Mapping[str, Any],
        payload: Mapping[str, Any] | None,
    ) -> str:
        chapter_id = str(state.get("current_chapter_id") or "").strip()
        if chapter_id:
            return chapter_id
        if isinstance(payload, Mapping):
            chapter_id = str(payload.get("chapter_id") or "").strip()
            if chapter_id:
                return chapter_id
        execution_input = self._load_optional_run_data(run_id, "chapter_execution_input.json")
        if execution_input is not None:
            chapter_id = str(execution_input.get("chapter_id") or "").strip()
            if chapter_id:
                return chapter_id
        return ""

    def _merge_generation_review_defaults(
        self,
        *,
        payload: Mapping[str, Any],
        defaults: Mapping[str, Any],
    ) -> dict[str, Any]:
        merged = dict(defaults)
        for key, value in payload.items():
            if key in merged and value in ("", None):
                continue
            merged[str(key)] = value
        return merged

    def _sync_generation_review_rework_artifacts(
        self,
        *,
        run_id: str,
        decision_payload: Mapping[str, Any],
    ) -> None:
        status = self._extract_generation_review_status(decision_payload)
        decision_id = str(decision_payload.get("decision_id") or "").strip()
        chapter_id = str(decision_payload.get("chapter_id") or "").strip()
        reason_code = str(decision_payload.get("reason_code") or "").strip()
        feedback_text = str(decision_payload.get("feedback_text") or "").strip()
        created_at = str(decision_payload.get("created_at") or "").strip()
        if status == "revise_length":
            payload = decision_payload.get("length_plan_update")
            if not isinstance(payload, Mapping):
                raise ValueError("revise_length decisions require length_plan_update")
            defaults = {
                "schema_version": "1.0",
                "update_id": f"length-update-{decision_id or chapter_id or run_id}",
                "decision_id": decision_id,
                "chapter_id": chapter_id,
                "reason_code": reason_code,
                "feedback_text": feedback_text,
                "preserve_story_direction": True,
                "created_at": created_at,
            }
            self.run_writer.write_length_plan_update(run_id, dict(payload), defaults=defaults)
            self._remove_run_artifact(run_id=run_id, name="chapter_replan_request.json")
            return
        if status == "replan_chapter":
            payload = decision_payload.get("chapter_replan_request")
            if not isinstance(payload, Mapping):
                raise ValueError("replan_chapter decisions require chapter_replan_request")
            defaults = {
                "schema_version": "1.0",
                "request_id": f"replan-{decision_id or chapter_id or run_id}",
                "decision_id": decision_id,
                "chapter_id": chapter_id,
                "reason_code": reason_code,
                "feedback_text": feedback_text,
                "replan_scope": "current_chapter",
                "must_preserve": [],
                "forbidden_carryover": [],
                "created_at": created_at,
            }
            self.run_writer.write_chapter_replan_request(run_id, dict(payload), defaults=defaults)
            self._remove_run_artifact(run_id=run_id, name="length_plan_update.json")
            return
        self._remove_run_artifact(run_id=run_id, name="length_plan_update.json")
        self._remove_run_artifact(run_id=run_id, name="chapter_replan_request.json")

    def _apply_length_plan_update(self, *, run_id: str) -> None:
        update = self._load_optional_run_data(run_id, "length_plan_update.json")
        if not isinstance(update, Mapping):
            return
        chapter_id = str(update.get("chapter_id") or "").strip()
        if not chapter_id:
            raise ValueError("length_plan_update.chapter_id is required")
        length_plan = self._load_optional_run_data(run_id, "chapter_length_plan.json")
        if not isinstance(length_plan, Mapping):
            target = int(update.get("target_chars") or 1200)
            length_plan = {
                "plan_id": f"length-plan-{run_id}",
                "batch_id": "",
                "default_target_chars": target,
                "default_min_chars": int(update.get("min_chars") or target),
                "default_max_chars": int(update.get("max_chars") or target),
                "budgets": [],
                "focus_chapter_ids": [],
                "climax_chapter_ids": [],
                "review_notes": [],
                "sources": [],
            }
        plan = dict(length_plan)
        budgets: list[dict[str, Any]] = []
        matched = False
        for item in plan.get("budgets") or []:
            if not isinstance(item, Mapping):
                continue
            budget = dict(item)
            if str(budget.get("chapter_id") or "") == chapter_id:
                budget["target_chars"] = int(update["target_chars"])
                budget["min_chars"] = int(update["min_chars"])
                budget["max_chars"] = int(update["max_chars"])
                notes = [str(note) for note in (budget.get("expansion_notes") or []) if str(note).strip()]
                feedback_text = str(update.get("feedback_text") or "").strip()
                if feedback_text and feedback_text not in notes:
                    notes.append(feedback_text)
                budget["expansion_notes"] = notes
                budget["is_focus_chapter"] = True
                budget["focus_reason"] = str(update.get("reason_code") or budget.get("focus_reason") or "revise_length")
                matched = True
            budgets.append(budget)
        if not matched:
            feedback_text = str(update.get("feedback_text") or "").strip()
            budgets.append(
                {
                    "chapter_id": chapter_id,
                    "target_chars": int(update["target_chars"]),
                    "min_chars": int(update["min_chars"]),
                    "max_chars": int(update["max_chars"]),
                    "is_focus_chapter": True,
                    "focus_reason": str(update.get("reason_code") or "revise_length"),
                    "expansion_notes": [feedback_text] if feedback_text else [],
                    "source_chapter_target_word_count": 0,
                }
            )
        plan["budgets"] = budgets
        focus_ids = [str(item) for item in (plan.get("focus_chapter_ids") or []) if str(item).strip()]
        if chapter_id not in focus_ids:
            focus_ids.append(chapter_id)
        plan["focus_chapter_ids"] = focus_ids
        review_notes = [str(item) for item in (plan.get("review_notes") or []) if str(item).strip()]
        note = f"已根据 length_plan_update.json 更新 {chapter_id}。"
        if note not in review_notes:
            review_notes.append(note)
        plan["review_notes"] = review_notes
        self.run_writer.write_json(run_id, "chapter_length_plan.json", plan)

    def _apply_interactive_length_overrides(
        self,
        *,
        run_id: str,
        default_target_chars: int | None,
        chapter_overrides: Mapping[str, Mapping[str, Any]],
    ) -> None:
        length_plan = self._load_optional_run_data(run_id, "chapter_length_plan.json")
        if not isinstance(length_plan, Mapping):
            raise FileNotFoundError("chapter_length_plan.json not found")
        plan = dict(length_plan)
        normalized_overrides = {
            str(chapter_id).strip(): dict(value)
            for chapter_id, value in chapter_overrides.items()
            if str(chapter_id).strip() and isinstance(value, Mapping)
        }
        default_bounds: tuple[int, int, int] | None = None
        if default_target_chars is not None:
            default_target = int(default_target_chars)
            default_bounds = self._normalized_length_bounds(
                target=default_target,
                min_chars=None,
                max_chars=None,
            )
            plan["default_target_chars"] = default_bounds[0]
            plan["default_min_chars"] = default_bounds[1]
            plan["default_max_chars"] = default_bounds[2]

        budgets: list[dict[str, Any]] = []
        seen_chapter_ids: set[str] = set()
        for item in plan.get("budgets") or []:
            if not isinstance(item, Mapping):
                continue
            budget = dict(item)
            chapter_id = str(budget.get("chapter_id") or "").strip()
            if not chapter_id:
                continue
            seen_chapter_ids.add(chapter_id)
            override = normalized_overrides.get(chapter_id)
            if override is not None:
                target, min_chars, max_chars = self._normalized_length_bounds(
                    target=override.get("target_chars") or override.get("target"),
                    min_chars=override.get("min_chars") or override.get("min"),
                    max_chars=override.get("max_chars") or override.get("max"),
                )
                budget["target_chars"] = target
                budget["min_chars"] = min_chars
                budget["max_chars"] = max_chars
                budget["is_focus_chapter"] = True
                budget["focus_reason"] = str(override.get("reason") or budget.get("focus_reason") or "interactive_override")
                notes = [str(note) for note in (budget.get("expansion_notes") or []) if str(note).strip()]
                note = str(override.get("note") or "用户在 wait_length_review 直接调整本章长度。")
                if note and note not in notes:
                    notes.append(note)
                budget["expansion_notes"] = notes
            elif default_bounds is not None:
                budget["target_chars"], budget["min_chars"], budget["max_chars"] = default_bounds
            budgets.append(budget)

        for chapter_id, override in normalized_overrides.items():
            if chapter_id in seen_chapter_ids:
                continue
            target, min_chars, max_chars = self._normalized_length_bounds(
                target=override.get("target_chars") or override.get("target"),
                min_chars=override.get("min_chars") or override.get("min"),
                max_chars=override.get("max_chars") or override.get("max"),
            )
            budgets.append(
                {
                    "chapter_id": chapter_id,
                    "target_chars": target,
                    "min_chars": min_chars,
                    "max_chars": max_chars,
                    "is_focus_chapter": True,
                    "focus_reason": str(override.get("reason") or "interactive_override"),
                    "expansion_notes": [str(override.get("note") or "用户在 wait_length_review 直接新增本章长度 override。")],
                    "source_chapter_target_word_count": 0,
                }
            )

        plan["budgets"] = budgets
        review_notes = [str(item) for item in (plan.get("review_notes") or []) if str(item).strip()]
        note = "已在 wait_length_review 通过交互输入更新章节长度计划。"
        if note not in review_notes:
            review_notes.append(note)
        plan["review_notes"] = review_notes
        focus_ids = [str(item) for item in (plan.get("focus_chapter_ids") or []) if str(item).strip()]
        for chapter_id in normalized_overrides:
            if chapter_id not in focus_ids:
                focus_ids.append(chapter_id)
        plan["focus_chapter_ids"] = focus_ids
        self.run_writer.write_json(run_id, "chapter_length_plan.json", plan)

    def _normalized_length_bounds(
        self,
        *,
        target: object,
        min_chars: object | None,
        max_chars: object | None,
    ) -> tuple[int, int, int]:
        target_chars = int(target or 0)
        if target_chars <= 0:
            raise ValueError("target_chars must be a positive integer")
        normalized_min = int(min_chars or max(1, target_chars * 85 // 100))
        normalized_max = int(max_chars or max(target_chars, target_chars * 115 // 100))
        if min(normalized_min, normalized_max) <= 0:
            raise ValueError("min_chars and max_chars must be positive integers")
        if not normalized_min <= target_chars <= normalized_max:
            raise ValueError("min_chars must be <= target_chars <= max_chars")
        return target_chars, normalized_min, normalized_max

    def _sync_draft_retention_record(
        self,
        *,
        run_id: str,
        decision_payload: Mapping[str, Any],
        include_memory_writeback: bool = False,
    ) -> None:
        draft_id = str(decision_payload.get("draft_id") or "").strip()
        if not draft_id:
            return
        chapter_id = str(decision_payload.get("chapter_id") or "").strip()
        decision_id = str(decision_payload.get("decision_id") or "").strip()
        decision_status = self._extract_generation_review_status(decision_payload)
        self.run_writer.sync_draft_retention_record(
            run_id,
            draft_id=draft_id,
            chapter_id=chapter_id,
            decision_id=decision_id,
            retention_status=self._draft_retention_status_for_decision(decision_status),
            decision_status=decision_status,
            supersedes_draft_id=str(decision_payload.get("supersedes_draft_id") or "").strip(),
            reviewer_type=str(decision_payload.get("reviewer_type") or "").strip(),
            created_at=str(decision_payload.get("created_at") or "").strip(),
            include_memory_writeback=include_memory_writeback,
        )
        superseded_draft_id = str(decision_payload.get("supersedes_draft_id") or "").strip()
        if superseded_draft_id and superseded_draft_id != draft_id:
            self.run_writer.mark_draft_superseded(
                run_id,
                draft_id=superseded_draft_id,
                replacement_draft_id=draft_id,
            )

    def _sync_current_draft_retention_record(
        self,
        *,
        run_id: str,
        state: Mapping[str, Any],
        include_memory_writeback: bool = False,
    ) -> None:
        payload = self._load_optional_run_data(run_id, "generation_review_decision.json")
        if payload is None:
            return
        chapter_id = self._resolve_review_chapter_id(run_id=run_id, state=state, payload=payload)
        draft_id = str(payload.get("draft_id") or state.get("current_draft_id") or "").strip()
        decision_id = str(payload.get("decision_id") or "").strip()
        if draft_id and not decision_id:
            decision_id = self._build_review_decision_id(chapter_id=chapter_id, draft_id=draft_id)
        defaults = {
            "schema_version": "1.0",
            "decision_id": decision_id,
            "run_id": run_id,
            "chapter_id": chapter_id,
            "draft_id": draft_id,
            "reviewer_type": "user",
        }
        normalized = self._merge_generation_review_defaults(payload=payload, defaults=defaults)
        self.run_writer.write_generation_review_decision(
            run_id,
            normalized,
            defaults=defaults,
        )
        self._sync_draft_retention_record(
            run_id=run_id,
            decision_payload=normalized,
            include_memory_writeback=include_memory_writeback,
        )

    def _draft_retention_status_for_decision(self, decision_status: str) -> str:
        if decision_status == "accepted":
            return "accepted"
        if decision_status == "discarded":
            return "discarded"
        return "drafted"

    def _ensure_memory_writeback_artifact(
        self,
        *,
        run_id: str,
        payload: Mapping[str, Any] | None,
    ) -> None:
        if not isinstance(payload, Mapping) or not payload:
            return
        path = self.run_writer.layout.run_dir(run_id) / "memory_writeback.json"
        if path.exists():
            return
        self.run_writer.write_json(run_id, "memory_writeback.json", dict(payload))

    def _write_freeze_e_after_writeback(
        self,
        *,
        run_id: str,
        execution_input: Mapping[str, Any],
        continuity_report: Mapping[str, Any],
        state_delta: Mapping[str, Any],
        memory_writeback: Mapping[str, Any],
    ) -> dict[str, str]:
        artifact_payloads: dict[str, Any] = {
            "chapter_execution_input.json": dict(execution_input),
            "continuity_report.json": dict(continuity_report),
            "state_delta.json": dict(state_delta),
        }
        if memory_writeback:
            artifact_payloads["memory_writeback.json"] = dict(memory_writeback)
        return self.run_writer.write_freeze_record(
            run_id,
            FreezeRecord(
                freeze_stage="freeze_e",
                summary="正文执行、章节验收与正式回写完成。",
                depends_on=["freeze_d"],
            ),
            artifact_payloads=artifact_payloads,
        )

    def _remove_run_artifact(self, *, run_id: str, name: str) -> None:
        path = self.run_writer.layout.run_dir(run_id) / name
        if path.exists():
            path.unlink()

    def _next_review_draft_id(self, *, state: dict[str, Any]) -> str:
        next_sequence = int(state.get("draft_sequence") or 0) + 1
        state["draft_sequence"] = next_sequence
        return f"draft-{next_sequence:03d}"

    def _draft_sequence_from_id(self, draft_id: str) -> int:
        try:
            return int(str(draft_id).rsplit("-", 1)[-1])
        except (TypeError, ValueError):
            return 0

    def _build_review_decision_id(self, *, chapter_id: str, draft_id: str) -> str:
        chapter_part = chapter_id or "chapter"
        draft_part = draft_id or "draft"
        return f"review-{chapter_part}-{draft_part}"

    def _coerce_continuity_report(self, payload: Mapping[str, Any]):
        from ...schemas.continuity import ContinuityReport

        return ContinuityReport.from_dict(dict(payload))

from __future__ import annotations

import json
import sqlite3
import uuid
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Mapping

from ...runs.writer import RunWriter
from ..schemas.orchestration_schema import (
    ArtifactReviewDecision,
    FreezeRecord,
    OutlineResearchAnswerSubmission,
    OutlineResearchQuestionSet,
    OutlineResearchUserAnswer,
    WriterLoopEvent,
    WriterLoopStep,
)
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
    ASSIST_MODE: ["freeze_a_review", "batch_review", "chapter_review", "writeback_review"],
    BATCH_MODE: ["batch_review", "chapter_review"],
    AUTO_NOVEL_MODE: [],
}
AGENT_STATES = {
    "agent_running",
    "reviewing_artifact",
    "needs_user_input",
    "generating_draft",
    "reviewing_draft",
    "writeback_review",
    "completed",
    "halted",
    "error",
}
LEGACY_STAGE_TO_AGENT_STATE = {
    "initialized": "agent_running",
    "outline_research_user_input": "needs_user_input",
    "outline_research_blocked": "halted",
    "freeze_a_review": "reviewing_artifact",
    "batch_review": "reviewing_artifact",
    "chapter_review": "reviewing_artifact",
    "wait_chapter_review": "reviewing_artifact",
    "wait_length_review": "reviewing_artifact",
    "freeze_d_review": "generating_draft",
    "ready_for_freeze_d": "generating_draft",
    "length_confirmed": "agent_running",
    "freeze_a": "agent_running",
    "freeze_b": "agent_running",
    "freeze_c": "agent_running",
    "freeze_d": "generating_draft",
    "wait_chapter_acceptance": "reviewing_draft",
    "writeback_review": "writeback_review",
    "freeze_e": "completed",
    "completed": "completed",
    "halted": "halted",
    "error": "error",
}
LEGACY_STAGE_MIGRATION_TARGETS = {
    "wait_length_review": "chapter_review",
    "freeze_d_review": "freeze_d",
}
REVIEW_STAGE_ARTIFACT_KINDS = {
    "freeze_a_review": "book_continuation_plan",
    "batch_review": "batch_plan",
    "chapter_review": "chapter_package",
    "wait_chapter_review": "chapter_package",
    "writeback_review": "writeback_summary",
}
RESUMABLE_WORKFLOW_STAGES = {
    "outline_research_user_input",
    "outline_research_blocked",
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
        if result.get("stage") in {"outline_research_user_input", "outline_research_blocked"}:
            checkpoint = dict(result.get("checkpoint") or {})
            state["pending_checkpoint"] = checkpoint
            self._set_workflow_position(state, technical_stage=str(result.get("stage") or ""))
            if result.get("stage") == "outline_research_blocked":
                state["terminal_stage"] = "outline_research_blocked"
        elif mode == ASSIST_MODE:
            run_dir = self.run_writer.layout.run_dir(run_id)
            checkpoint = self._write_checkpoint(
                run_id=run_id,
                stage="freeze_a_review",
                artifact_path=str(run_dir / "book_continuation_plan.json"),
                source="prepare_planning",
            )
            state["pending_checkpoint"] = checkpoint
            self._set_workflow_position(state, technical_stage="freeze_a_review")
        else:
            self._set_workflow_position(state, technical_stage="freeze_a")
            state["pending_checkpoint"] = None
        self._save_workflow_state(run_id, state)
        return result

    def continue_after_outline_research_input(
        self,
        conn: sqlite3.Connection,
        *,
        run_id: str,
        book_id: str,
        product_mode: str,
        user_answers: Mapping[str, str] | list[Mapping[str, Any]],
        question_set_id: str = "",
        source_message_id: str = "",
        answer_text: str = "",
        user_world_notes: str = "",
        character_seed_payloads: list[Mapping[str, Any]] | None = None,
        roster_hint_payloads: list[Mapping[str, Any]] | None = None,
    ) -> dict[str, Any]:
        mode = self._normalize_mode(product_mode)
        question_set = self._load_outline_research_question_set(run_id)
        normalized_answers = self._normalize_outline_research_answers(
            question_set=question_set,
            user_answers=user_answers,
            answer_text=answer_text,
        )
        raw_answer_text = self._outline_research_raw_answer_text(answer_text=answer_text, answers=normalized_answers)
        if question_set is not None:
            if question_set_id and question_set_id != question_set.question_set_id:
                raise ValueError("提交的问题集与当前等待的问题集不一致。")
            missing_required = self._missing_required_outline_answers(
                question_set=question_set,
                answers=normalized_answers,
            )
            if missing_required:
                return self._outline_research_missing_answer_payload(
                    run_id=run_id,
                    book_id=book_id,
                    product_mode=mode,
                    question_set=question_set,
                    missing_question_ids=missing_required,
                )
        if not raw_answer_text:
            raise ValueError("请先填写回答内容。")
        submission_question_set_id = question_set.question_set_id if question_set is not None else question_set_id
        if not submission_question_set_id:
            submission_question_set_id = f"outline-research-{run_id}-manual"
        submission = OutlineResearchAnswerSubmission(
            submission_id=f"outline-answer-{run_id}-{uuid.uuid4().hex[:8]}",
            question_set_id=submission_question_set_id,
            run_id=run_id,
            source_message_id=source_message_id,
            answer_text=raw_answer_text,
            user_answers=[
                OutlineResearchUserAnswer(question_id=question_id, answer_text=answer)
                for question_id, answer in normalized_answers.items()
            ],
        )
        self.run_writer.write_outline_research_answer_submission(run_id, submission)
        result = self.planner.continue_outline_research_with_user_input(
            conn,
            run_id=run_id,
            book_id=book_id,
            user_answers=self._outline_research_answers_for_notebook(
                question_set=question_set,
                answers=normalized_answers,
                raw_answer_text=raw_answer_text,
            ),
            user_world_notes=user_world_notes,
            character_seed_payloads=character_seed_payloads,
            roster_hint_payloads=roster_hint_payloads,
            auto_confirm=mode != ASSIST_MODE,
        )
        state = self.load_workflow_state(run_id=run_id) or self._base_state(run_id=run_id, book_id=book_id, product_mode=mode)
        if result.get("stage") in {"outline_research_user_input", "outline_research_blocked"}:
            state["pending_checkpoint"] = dict(result.get("checkpoint") or {})
            self._set_workflow_position(state, technical_stage=str(result.get("stage") or ""))
            state["terminal_stage"] = "outline_research_blocked" if result.get("stage") == "outline_research_blocked" else None
        elif mode == ASSIST_MODE:
            checkpoint = self._write_checkpoint(
                run_id=run_id,
                stage="freeze_a_review",
                artifact_path=str(self.run_writer.layout.run_dir(run_id) / "book_continuation_plan.json"),
                source="continue_after_outline_research_input",
            )
            state["pending_checkpoint"] = checkpoint
            self._set_workflow_position(state, technical_stage="freeze_a_review")
            state["terminal_stage"] = None
        else:
            state["pending_checkpoint"] = None
            self._set_workflow_position(state, technical_stage="freeze_a")
            state["terminal_stage"] = None
        self._save_workflow_state(run_id, state)
        return result

    def _load_outline_research_question_set(self, run_id: str) -> OutlineResearchQuestionSet | None:
        payload = self._load_optional_run_data(run_id, "outline_research_question_set.json")
        if not payload:
            return None
        return OutlineResearchQuestionSet.from_dict(payload)

    def _normalize_outline_research_answers(
        self,
        *,
        question_set: OutlineResearchQuestionSet | None,
        user_answers: Mapping[str, str] | list[Mapping[str, Any]],
        answer_text: str,
    ) -> dict[str, str]:
        prompt_to_id: dict[str, str] = {}
        valid_ids: set[str] = set()
        if question_set is not None:
            for question in question_set.questions:
                valid_ids.add(question.question_id)
                prompt_to_id[question.prompt] = question.question_id

        normalized: dict[str, str] = {}
        if isinstance(user_answers, Mapping):
            for raw_key, raw_value in user_answers.items():
                key = str(raw_key).strip()
                value = str(raw_value).strip()
                if not key or not value:
                    continue
                question_id = key if key in valid_ids else prompt_to_id.get(key, key)
                normalized[question_id] = value
        else:
            for item in user_answers:
                if not isinstance(item, Mapping):
                    continue
                key = str(item.get("question_id") or item.get("question") or "").strip()
                value = str(item.get("answer_text") or item.get("answer") or "").strip()
                if not key or not value:
                    continue
                question_id = key if key in valid_ids else prompt_to_id.get(key, key)
                normalized[question_id] = value

        raw_answer_text = str(answer_text or "").strip()
        if not normalized and raw_answer_text:
            if question_set is not None and len(question_set.questions) == 1:
                normalized[question_set.questions[0].question_id] = raw_answer_text
            elif question_set is None:
                normalized["user_answer"] = raw_answer_text
        return normalized

    @staticmethod
    def _outline_research_raw_answer_text(*, answer_text: str, answers: Mapping[str, str]) -> str:
        raw_answer_text = str(answer_text or "").strip()
        if raw_answer_text:
            return raw_answer_text
        return "\n".join(value for value in answers.values() if str(value).strip()).strip()

    @staticmethod
    def _missing_required_outline_answers(
        *,
        question_set: OutlineResearchQuestionSet,
        answers: Mapping[str, str],
    ) -> list[str]:
        return [
            question.question_id
            for question in question_set.questions
            if question.required and not str(answers.get(question.question_id) or "").strip()
        ]

    @staticmethod
    def _outline_research_answers_for_notebook(
        *,
        question_set: OutlineResearchQuestionSet | None,
        answers: Mapping[str, str],
        raw_answer_text: str,
    ) -> dict[str, str]:
        if question_set is None:
            return dict(answers or {"用户补充": raw_answer_text})
        if not answers and raw_answer_text:
            return {"用户补充": raw_answer_text}
        prompt_by_id = {question.question_id: question.prompt for question in question_set.questions}
        return {
            prompt_by_id.get(question_id, question_id): answer
            for question_id, answer in answers.items()
            if str(answer).strip()
        }

    def _outline_research_missing_answer_payload(
        self,
        *,
        run_id: str,
        book_id: str,
        product_mode: str,
        question_set: OutlineResearchQuestionSet,
        missing_question_ids: list[str],
    ) -> dict[str, Any]:
        state = self.load_workflow_state(run_id=run_id) or self._base_state(
            run_id=run_id,
            book_id=book_id,
            product_mode=product_mode,
        )
        checkpoint = self._load_optional_run_data(run_id, "outline_research_checkpoint.json") or {}
        state["pending_checkpoint"] = checkpoint
        self._set_workflow_position(state, technical_stage="outline_research_user_input")
        state["terminal_stage"] = None
        self._save_workflow_state(run_id, state)
        return {
            "status": "needs_user_input",
            "stage": "outline_research_user_input",
            "message": "还有必答问题没有回答，请补充后再继续大纲研究。",
            "checkpoint": checkpoint,
            "question_set": question_set.to_dict(),
            "missing_required_questions": list(missing_question_ids),
        }

    def continue_after_planning_review(self, *, run_id: str) -> dict[str, str]:
        paths = self.planner.confirm_freeze_a(run_id=run_id)
        self._confirm_checkpoint(run_id=run_id, stage="freeze_a_review", source="continue_after_planning_review")
        state = self.load_workflow_state(run_id=run_id) or {}
        state["pending_checkpoint"] = None
        self._set_workflow_position(state, technical_stage="freeze_a", agent_state="agent_running")
        self._save_workflow_state(run_id, state)
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
            self._set_workflow_position(state, technical_stage="batch_review")
        else:
            state["pending_checkpoint"] = None
            self._set_workflow_position(state, technical_stage="freeze_b")
        self._save_workflow_state(run_id, state)
        return result

    def continue_after_batch_review(self, *, run_id: str, artifact_path: str | None = None) -> dict[str, str]:
        paths = self.planner.confirm_batch_plan(run_id=run_id, artifact_path=artifact_path)
        self._confirm_checkpoint(run_id=run_id, stage="batch_review", source="continue_after_batch_review")
        state = self.load_workflow_state(run_id=run_id) or {}
        self._set_workflow_position(state, technical_stage="freeze_b")
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
            self._set_workflow_position(state, technical_stage="chapter_review")
        else:
            state["pending_checkpoint"] = None
            self._set_workflow_position(state, technical_stage="freeze_c")
        self._save_workflow_state(run_id, state)
        return result

    def continue_after_chapter_review(self, *, run_id: str, artifact_path: str | None = None) -> dict[str, Any]:
        paths = self.planner.confirm_chapter_package(run_id=run_id, artifact_path=artifact_path)
        state = self.load_workflow_state(run_id=run_id) or {}
        pending_stage = str((state.get("pending_checkpoint") or {}).get("stage") or "")
        checkpoint_stage = "wait_chapter_review" if pending_stage == "wait_chapter_review" else "chapter_review"
        self._confirm_checkpoint(run_id=run_id, stage=checkpoint_stage, source="continue_after_chapter_review")
        state = self.load_workflow_state(run_id=run_id) or state
        state["pending_checkpoint"] = None
        self._set_workflow_position(state, technical_stage="freeze_c", agent_state="agent_running")
        self._save_workflow_state(run_id, state)
        return {**paths, "next_agent_state": "generating_draft"}

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
            self._set_workflow_position(state, technical_stage="wait_length_review")
        else:
            state["pending_checkpoint"] = None
            self._set_workflow_position(state, technical_stage="length_confirmed")
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
        self._set_workflow_position(state, technical_stage="length_confirmed")
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
        previous_chapter_id = str(state.get("current_chapter_id") or "").strip()
        if previous_chapter_id and previous_chapter_id != chapter_id:
            self._remove_run_artifact(run_id=run_id, name="generation_review_decision.json")
            self._remove_run_artifact(run_id=run_id, name="draft_rewrite_request.json")
            state["current_draft_id"] = ""
            state["current_decision_id"] = ""
        state["current_chapter_id"] = chapter_id
        state["pending_checkpoint"] = None
        self.executor.confirm_freeze_d(run_id=run_id)
        self._set_workflow_position(state, technical_stage="freeze_d", agent_state="generating_draft")
        self._save_workflow_state(run_id, state)
        return {**result, "freeze_d": self.run_writer.get_freeze_record(run_id, "freeze_d").to_dict() if self.run_writer.get_freeze_record(run_id, "freeze_d") else {}}

    def continue_after_execution_review(self, *, run_id: str) -> dict[str, str]:
        paths = self.executor.confirm_freeze_d(run_id=run_id)
        self._confirm_checkpoint(run_id=run_id, stage="freeze_d_review", source="continue_after_execution_review")
        state = self.load_workflow_state(run_id=run_id) or {}
        self._set_workflow_position(state, technical_stage="freeze_d", agent_state="generating_draft")
        self._save_workflow_state(run_id, state)
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
        result = self.executor.execute_frozen_chapter(
            conn,
            run_id=run_id,
            book_id=book_id,
            commit_writeback=False,
            auto_freeze_e=False,
        )
        state = self.load_workflow_state(run_id=run_id) or self._base_state(run_id=run_id, book_id=book_id, product_mode=mode)
        if result["canon_ready"]:
            state["failure_count"] = 0
            state["last_rollback"] = None
            state.pop("last_continuity_risk", None)
        else:
            state["last_rollback"] = None
            state["last_continuity_risk"] = {
                "reason": "正文连续性检查存在风险，作为用户决策参考，不会自动回滚或阻止接受。",
                "continuity_report_path": result.get("continuity_report_path", ""),
            }
        self._route_chapter_acceptance_decision(
            run_id=run_id,
            state=state,
            mode=mode,
            source="execute_current_chapter",
        )
        self._sync_current_draft_retention_record(
            run_id=run_id,
            state=state,
            include_memory_writeback=False,
        )
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

    def rewrite_current_chapter(
        self,
        conn: sqlite3.Connection,
        *,
        run_id: str,
        book_id: str,
        product_mode: str,
    ) -> dict[str, Any]:
        state = self.load_workflow_state(run_id=run_id)
        if state is None:
            raise FileNotFoundError(f"workflow state not found for run_id={run_id}")
        decision_payload = self._normalize_generation_review_decision_artifact(run_id=run_id, state=state) or {}
        if self._extract_generation_review_status(decision_payload) != "rewrite_requested":
            raise ValueError("rewrite_current_chapter requires generation_review_decision.status=rewrite_requested")
        feedback_text = str(decision_payload.get("feedback_text") or "").strip()
        if not feedback_text:
            raise ValueError("rewrite_requested requires feedback_text")
        decision_id = str(decision_payload.get("decision_id") or uuid.uuid4().hex).strip()
        self.run_writer.write_json(run_id, f"generation_review_decisions/{decision_id}.json", dict(decision_payload))
        execution_input = self._load_optional_run_data(run_id, "chapter_execution_input.json")
        if not isinstance(execution_input, Mapping):
            raise FileNotFoundError("chapter_execution_input.json not found")
        updated_input = dict(execution_input)
        rewrite_requests = [
            dict(item) for item in (updated_input.get("draft_rewrite_requests") or []) if isinstance(item, Mapping)
        ]
        rewrite_request = {
            "decision_id": decision_id,
            "draft_id": str(decision_payload.get("draft_id") or state.get("current_draft_id") or ""),
            "feedback_text": feedback_text,
            "reason_code": str(decision_payload.get("reason_code") or "other"),
            "created_at": str(decision_payload.get("created_at") or _utc_now()),
        }
        rewrite_requests.append(rewrite_request)
        updated_input["draft_feedback"] = rewrite_request
        updated_input["draft_rewrite_requests"] = rewrite_requests
        writer_rules = [str(item) for item in (updated_input.get("writer_rules") or []) if str(item).strip()]
        writer_rules.append("重写正文时必须消费 draft_feedback.feedback_text，但不得改写已通过的 ChapterBrief 或正式写回 Memory。")
        updated_input["writer_rules"] = [item for item in dict.fromkeys(writer_rules) if item]
        self.run_writer.write_json(run_id, "chapter_execution_input.json", updated_input)
        self.run_writer.write_json(run_id, "draft_rewrite_request.json", rewrite_request)
        self.run_writer.write_freeze_record(
            run_id,
            FreezeRecord(
                freeze_stage="freeze_d",
                summary="基于用户草稿反馈重写正文；上游章节梗概未改变。",
                depends_on=["freeze_c"],
            ),
            artifact_payloads={
                "chapter_brief.json": self._load_optional_run_data(run_id, "chapter_brief.json") or {},
                "chapter_length_budget.json": self._load_optional_run_data(run_id, "chapter_length_budget.json") or {},
                "style_reference_bundle.json": self._load_optional_run_data(run_id, "style_reference_bundle.json") or {},
                "chapter_execution_input.json": updated_input,
            },
        )
        self._remove_run_artifact(run_id=run_id, name="generation_review_decision.json")
        self._set_workflow_position(state, technical_stage="freeze_d", agent_state="generating_draft")
        state["pending_checkpoint"] = None
        self._save_workflow_state(run_id, state)
        return self.execute_current_chapter(
            conn,
            run_id=run_id,
            book_id=book_id,
            product_mode=product_mode,
        )

    def replan_current_chapter_from_feedback(
        self,
        *,
        run_id: str,
        source_message_id: str = "",
    ) -> dict[str, Any]:
        state = self.load_workflow_state(run_id=run_id)
        if state is None:
            raise FileNotFoundError(f"workflow state not found for run_id={run_id}")
        decision_payload = self._normalize_generation_review_decision_artifact(run_id=run_id, state=state) or {}
        if self._extract_generation_review_status(decision_payload) != "replan_requested":
            raise ValueError("replan_current_chapter_from_feedback requires generation_review_decision.status=replan_requested")
        feedback_text = str(decision_payload.get("feedback_text") or "").strip()
        if not feedback_text:
            raise ValueError("replan_requested requires feedback_text")
        run_dir = self.run_writer.layout.run_dir(run_id)
        chapter_package_path = run_dir / "chapter_package.json"
        checkpoint = self._write_checkpoint(
            run_id=run_id,
            stage="chapter_review",
            artifact_path=str(chapter_package_path),
            source="replan_current_chapter_from_feedback",
        )
        state["pending_checkpoint"] = checkpoint
        state["terminal_stage"] = None
        self._set_workflow_position(state, technical_stage="chapter_review", agent_state="reviewing_artifact")
        self._save_workflow_state(run_id, state)
        return self.review_writer_artifact(
            run_id=run_id,
            decision="revision_requested",
            artifact_kind="chapter_package",
            artifact_path=str(chapter_package_path),
            review_id=f"artifact-review-{run_id}-draft-replan-{uuid.uuid4().hex[:8]}",
            revision_feedback=feedback_text,
            source_message_id=source_message_id,
        )

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
        stage = str(pending_checkpoint.get("stage") or "")
        if not self._is_resumable_stage(stage):
            return None
        if stage == "wait_length_review":
            migrated = dict(pending_checkpoint)
            migrated["legacy_stage"] = stage
            migrated["stage"] = "chapter_review"
            chapter_package_path = self.run_writer.layout.run_dir(run_id) / "chapter_package.json"
            if chapter_package_path.exists():
                migrated["artifact_path"] = str(chapter_package_path)
            migrated["migration_note"] = "wait_length_review is legacy/migration-only; resume at chapter synopsis review."
            return migrated
        if stage == "freeze_d_review":
            migrated = dict(pending_checkpoint)
            migrated["legacy_stage"] = stage
            migrated["stage"] = "freeze_d"
            migrated["migration_note"] = "freeze_d_review is legacy/migration-only; resume at draft generation prep."
            return migrated
        return pending_checkpoint

    def register_character_cast_change(self, *, run_id: str, reason: str) -> dict[str, Any]:
        event = self.rollback_manager.cascade_for_character_cast_change(run_id=run_id, reason=reason)
        state = self.load_workflow_state(run_id=run_id) or {}
        state["last_rollback"] = event.to_dict()
        self._set_workflow_position(state, technical_stage="freeze_a", agent_state="agent_running")
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
        self._set_workflow_position(state, technical_stage=request.target_stage, agent_state="reviewing_artifact")
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

    def review_writer_artifact(
        self,
        conn: sqlite3.Connection | None = None,
        *,
        run_id: str,
        book_id: str = "",
        product_mode: str = ASSIST_MODE,
        decision: str,
        artifact_kind: str = "",
        artifact_id: str = "",
        artifact_path: str = "",
        review_id: str = "",
        supplement_text: str = "",
        revision_feedback: str = "",
        source_message_id: str = "",
        chapter_id: str = "",
    ) -> dict[str, Any]:
        state = self.load_workflow_state(run_id=run_id)
        if state is None:
            raise FileNotFoundError(f"workflow state not found for run_id={run_id}")
        checkpoint = dict(state.get("pending_checkpoint") or {})
        stage = str(checkpoint.get("stage") or state.get("technical_stage") or state.get("current_stage") or "").strip()
        resolved_path = str(artifact_path or checkpoint.get("artifact_path") or "").strip()
        resolved_kind = artifact_kind or self._artifact_kind_for_review_stage(stage, resolved_path)
        resolved_review_id = review_id or self._review_id_for_artifact(
            run_id=run_id,
            stage=stage,
            artifact_kind=resolved_kind,
        )
        next_action = {
            "approved": "continue_agent_loop",
            "revision_requested": "revise_artifact",
            "deferred": "defer_review",
        }.get(str(decision).strip().lower(), "")
        review_decision = ArtifactReviewDecision(
            review_id=resolved_review_id,
            run_id=run_id,
            artifact_kind=resolved_kind,
            artifact_id=artifact_id,
            artifact_path=resolved_path,
            artifact_version=self._artifact_version(resolved_path),
            decision=decision,  # type: ignore[arg-type]
            supplement_text=supplement_text,
            revision_feedback=revision_feedback,
            source_message_id=source_message_id,
            reviewer_type="user",
            next_action=next_action,  # type: ignore[arg-type]
            created_at=_utc_now(),
        )
        self.run_writer.write_artifact_review_decision(run_id, review_decision)
        event = self._append_loop_event(
            run_id=run_id,
            event_kind="artifact_review",
            agent_state="reviewing_artifact",
            technical_stage=stage,
            summary=f"Artifact review decision: {review_decision.decision}",
            payload=review_decision.to_dict(),
        )
        if review_decision.decision == "approved":
            prompt_input = self._build_review_prompt_input(
                run_id=run_id,
                state=state,
                stage=stage,
                decision=review_decision,
                prompt_kind="next_stage",
            )
            prompt_path = self.run_writer.write_json(
                run_id,
                f"writer_prompt_inputs/{review_decision.review_id}_next_stage_prompt.json",
                prompt_input,
            )
            if review_decision.supplement_text:
                self.run_writer.write_user_supplement(
                    run_id,
                    {
                        "review_id": review_decision.review_id,
                        "artifact_kind": review_decision.artifact_kind,
                        "artifact_id": review_decision.artifact_id,
                        "artifact_path": review_decision.artifact_path,
                        "supplement_text": review_decision.supplement_text,
                        "source_message_id": review_decision.source_message_id,
                        "prompt_input_path": str(prompt_path),
                    },
                    review_id=review_decision.review_id,
                )
            result = self._continue_after_artifact_approval(
                conn,
                run_id=run_id,
                book_id=book_id or str(state.get("book_id") or ""),
                product_mode=product_mode or str(state.get("product_mode") or ASSIST_MODE),
                stage=stage,
                artifact_path=resolved_path or None,
                chapter_id=chapter_id,
                review_decision=review_decision,
            )
            self._write_loop_step(
                run_id=run_id,
                status="completed",
                agent_state=str((self.load_workflow_state(run_id=run_id) or {}).get("agent_state") or "agent_running"),
                technical_stage=str((self.load_workflow_state(run_id=run_id) or {}).get("technical_stage") or stage),
                event_ids=[event["event_id"]],
                prompt_input_path=str(prompt_path),
                output_artifact_path=str(result.get("artifact_path") or resolved_path),
            )
            return {
                "status": "ok",
                "decision": review_decision.to_dict(),
                "prompt_input_path": str(prompt_path),
                "result": result,
                "workflow_state": self.load_workflow_state(run_id=run_id) or {},
            }
        if review_decision.decision == "revision_requested":
            prompt_input = self._build_review_prompt_input(
                run_id=run_id,
                state=state,
                stage=stage,
                decision=review_decision,
                prompt_kind="artifact_revision",
            )
            prompt_path = self.run_writer.write_json(
                run_id,
                f"writer_prompt_inputs/{review_decision.review_id}_artifact_revision_prompt.json",
                prompt_input,
            )
            revision_result = self._revise_review_artifact(
                run_id=run_id,
                state=state,
                stage=stage,
                artifact_kind=resolved_kind,
                artifact_path=resolved_path,
                revision_feedback=review_decision.revision_feedback,
                request_id=review_decision.review_id,
            )
            self._write_loop_step(
                run_id=run_id,
                status="waiting",
                agent_state="reviewing_artifact",
                technical_stage=stage,
                event_ids=[event["event_id"]],
                prompt_input_path=str(prompt_path),
                output_artifact_path=str(revision_result.get("artifact_path") or resolved_path),
            )
            return {
                "status": "revision_requested",
                "decision": review_decision.to_dict(),
                "prompt_input_path": str(prompt_path),
                "revision": revision_result,
                "workflow_state": self.load_workflow_state(run_id=run_id) or {},
            }
        state["terminal_stage"] = {
            "stage": "halted",
            "artifact_path": resolved_path,
            "source": "defer_writer_artifact_review",
        }
        self._set_workflow_position(state, technical_stage=stage, agent_state="halted")
        self._save_workflow_state(run_id, state)
        return {
            "status": "deferred",
            "decision": review_decision.to_dict(),
            "workflow_state": self.load_workflow_state(run_id=run_id) or {},
        }

    def _continue_after_artifact_approval(
        self,
        conn: sqlite3.Connection | None,
        *,
        run_id: str,
        book_id: str,
        product_mode: str,
        stage: str,
        artifact_path: str | None,
        chapter_id: str,
        review_decision: ArtifactReviewDecision,
    ) -> dict[str, Any]:
        if stage == "freeze_a_review":
            return self.continue_after_planning_review(run_id=run_id)
        if stage == "batch_review":
            return self.continue_after_batch_review(run_id=run_id, artifact_path=artifact_path)
        if stage in {"chapter_review", "wait_chapter_review"}:
            result: dict[str, Any] = {
                "freeze_c": self.continue_after_chapter_review(run_id=run_id, artifact_path=artifact_path)
            }
            if conn is None:
                return result
            selected_chapter_id = chapter_id or self._first_chapter_id_from_chapter_package(run_id)
            if not selected_chapter_id:
                raise ValueError("chapter_package.json does not contain a chapter_id")
            result["chapter_id"] = selected_chapter_id
            result["execution_input"] = self.prepare_execution(
                conn,
                run_id=run_id,
                book_id=book_id,
                chapter_id=selected_chapter_id,
                product_mode=product_mode,
            )
            self._merge_user_supplement_into_execution_input(
                run_id=run_id,
                decision=review_decision,
            )
            result["chapter_writing_guidance"] = self._write_chapter_writing_guidance(
                run_id=run_id,
                decision=review_decision,
                chapter_id=selected_chapter_id,
            )
            result["execution_result"] = self.execute_current_chapter(
                conn,
                run_id=run_id,
                book_id=book_id,
                product_mode=product_mode,
            )
            return result
        if stage == "writeback_review" and conn is not None:
            return self.approve_writeback(conn, run_id=run_id, book_id=book_id)
        return {"stage": stage, "artifact_path": artifact_path or ""}

    def _revise_review_artifact(
        self,
        *,
        run_id: str,
        state: Mapping[str, Any],
        stage: str,
        artifact_kind: str,
        artifact_path: str,
        revision_feedback: str,
        request_id: str,
    ) -> dict[str, Any]:
        if not artifact_path:
            raise ValueError("artifact_path is required for artifact revision")
        result = self.request_scoped_artifact_revision(
            run_id=run_id,
            user_feedback=revision_feedback,
            request_id=request_id,
            target_stage=stage,
            target_artifact_type=self._revision_artifact_type_for_kind(artifact_kind, artifact_path),
            target_artifact_path=artifact_path,
        )
        if result.get("status") == "candidate":
            applied = self.apply_scoped_artifact_revision(run_id=run_id, request_id=request_id)
            state_after = self.load_workflow_state(run_id=run_id) or dict(state)
            pending = dict(state_after.get("pending_checkpoint") or {})
            pending["stage"] = stage
            pending["artifact_path"] = str(applied.get("artifact_path") or artifact_path)
            state_after["pending_checkpoint"] = pending
            state_after["terminal_stage"] = None
            self._set_workflow_position(state_after, technical_stage=stage, agent_state="reviewing_artifact")
            self._save_workflow_state(run_id, state_after)
            return {**applied, "status": "revised"}
        state_after = self.load_workflow_state(run_id=run_id) or dict(state)
        self._set_workflow_position(state_after, technical_stage=stage, agent_state="reviewing_artifact")
        self._save_workflow_state(run_id, state_after)
        return result

    def _build_review_prompt_input(
        self,
        *,
        run_id: str,
        state: Mapping[str, Any],
        stage: str,
        decision: ArtifactReviewDecision,
        prompt_kind: str,
    ) -> dict[str, Any]:
        artifact_payload = self._load_artifact_payload(Path(decision.artifact_path)) if decision.artifact_path else {}
        return {
            "schema_version": "1.0",
            "prompt_kind": prompt_kind,
            "run_id": run_id,
            "agent_state": state.get("agent_state") or self._agent_state_for_stage(stage),
            "technical_stage": stage,
            "review_decision": decision.to_dict(),
            "current_artifact": self._summarize_prompt_artifact(artifact_payload),
            "upstream_constraints": self._review_upstream_constraints(run_id=run_id, stage=stage, artifact_payload=artifact_payload),
            "planning_notebook": self._load_optional_run_data(run_id, "planning_notebook.json") or {},
            "evidence": self._review_evidence_index(run_id),
            "rules": [
                "User text must be preserved verbatim and consumed only by the Writer layer.",
                "Web, CLI, and TUI callers submit decisions; they must not assemble model prompts directly.",
                "Revision prompts must output the same artifact kind and return to the same review gate.",
            ],
        }

    def _summarize_prompt_artifact(self, artifact_payload: Mapping[str, Any]) -> dict[str, Any]:
        summary: dict[str, Any] = {}
        for key in (
            "plan_id",
            "pack_id",
            "cast_plan_id",
            "batch_id",
            "package_id",
            "chapter_id",
            "title",
            "continuation_goal",
            "batch_goal",
            "package_goal",
            "goal",
            "chapters",
            "review_notes",
        ):
            if key in artifact_payload:
                summary[key] = artifact_payload[key]
        if not summary:
            summary["keys"] = sorted(str(key) for key in artifact_payload.keys())[:40]
        return summary

    def _review_upstream_constraints(
        self,
        *,
        run_id: str,
        stage: str,
        artifact_payload: Mapping[str, Any],
    ) -> dict[str, Any]:
        try:
            artifact_type = self._revision_artifact_type_for_kind(
                self._artifact_kind_for_review_stage(stage, ""),
                "",
            )
            return self._build_scoped_revision_allowed_context(
                run_id=run_id,
                target_stage=stage,
                target_artifact_type=artifact_type,
                target_artifact=artifact_payload,
            )
        except Exception:
            return {
                "stage": stage,
                "freeze_a": self._safe_summarize_frozen_artifact(run_id, "freeze_a", "book_continuation_plan.json"),
                "freeze_b": self._safe_summarize_frozen_artifact(run_id, "freeze_b", "batch_plan.json"),
                "freeze_c": self._safe_summarize_frozen_artifact(run_id, "freeze_c", "chapter_package.json"),
            }

    def _safe_summarize_frozen_artifact(self, run_id: str, freeze_stage: str, artifact_name: str) -> dict[str, Any]:
        try:
            return self._summarize_frozen_artifact(
                run_id,
                freeze_stage,
                artifact_name,
                fields=("plan_id", "book_id", "batch_id", "package_id", "continuation_goal", "batch_goal", "chapters"),
                optional=True,
            )
        except Exception:
            return {}

    def _review_evidence_index(self, run_id: str) -> dict[str, Any]:
        run_dir = self.run_writer.layout.run_dir(run_id)
        names = [
            "outline_research_trace.json",
            "memory_query_trace.json",
            "memory_query_decision_log.json",
            "sufficiency_decision.json",
            "source_arc_map.json",
            "narrative_structure_patterns.json",
            "arc_pattern_cards.json",
        ]
        return {
            name: {"path": str(run_dir / name), "exists": (run_dir / name).exists()}
            for name in names
        }

    def _merge_user_supplement_into_execution_input(
        self,
        *,
        run_id: str,
        decision: ArtifactReviewDecision,
    ) -> None:
        if not decision.supplement_text:
            return
        execution_input = self._load_optional_run_data(run_id, "chapter_execution_input.json")
        if not isinstance(execution_input, Mapping):
            return
        updated = dict(execution_input)
        user_supplements = [
            item for item in (updated.get("user_supplements") or []) if isinstance(item, Mapping)
        ]
        user_supplement = {
            "review_id": decision.review_id,
            "artifact_kind": decision.artifact_kind,
            "artifact_id": decision.artifact_id,
            "artifact_path": decision.artifact_path,
            "supplement_text": decision.supplement_text,
            "source_message_id": decision.source_message_id,
        }
        user_supplements.append(user_supplement)
        updated["user_supplement"] = user_supplement
        updated["user_supplements"] = user_supplements
        writer_rules = [
            str(item)
            for item in (updated.get("writer_rules") or [])
            if str(item).strip()
        ]
        writer_rules.append(
            "必须消费 user_supplement.supplement_text 中用户通过章节梗概时补充的字数、风格、节奏、重点段落和禁止项要求。"
        )
        updated["writer_rules"] = [item for item in dict.fromkeys(writer_rules) if item]
        self.run_writer.write_json(run_id, "chapter_execution_input.json", updated)
        freeze_d = self.run_writer.get_freeze_record(run_id, "freeze_d")
        if freeze_d is not None:
            artifact_payloads = {
                "chapter_brief.json": self._load_optional_run_data(run_id, "chapter_brief.json") or {},
                "chapter_length_budget.json": self._load_optional_run_data(run_id, "chapter_length_budget.json") or {},
                "style_reference_bundle.json": self._load_optional_run_data(run_id, "style_reference_bundle.json") or {},
                "chapter_execution_input.json": updated,
            }
            self.run_writer.write_freeze_record(
                run_id,
                FreezeRecord(
                    freeze_stage="freeze_d",
                    summary="受限执行输入已冻结，包含用户通过审阅时的补充要求。",
                    depends_on=["freeze_c"],
                ),
                artifact_payloads=artifact_payloads,
            )

    def _write_chapter_writing_guidance(
        self,
        *,
        run_id: str,
        decision: ArtifactReviewDecision,
        chapter_id: str,
    ) -> dict[str, Any]:
        execution_input = self._load_optional_run_data(run_id, "chapter_execution_input.json") or {}
        chapter_brief = dict(execution_input.get("chapter_brief") or {})
        length_budget = dict(execution_input.get("length_budget") or {})
        guidance = {
            "schema_version": "1.0",
            "run_id": run_id,
            "chapter_id": chapter_id,
            "source_review_id": decision.review_id,
            "chapter_title": execution_input.get("chapter_title") or chapter_brief.get("title") or chapter_id,
            "chapter_brief_summary": self._summarize_prompt_artifact(chapter_brief),
            "user_supplement": {
                "supplement_text": decision.supplement_text,
                "source_message_id": decision.source_message_id,
            },
            "length_budget": length_budget,
            "prompt_input_boundary": "Writer layer assembled from approved ChapterPackage/ChapterBrief, upstream constraints, evidence, and preserved user supplement.",
            "created_at": _utc_now(),
        }
        self.run_writer.write_json(run_id, "chapter_writing_guidance.json", guidance)
        return guidance

    def _artifact_kind_for_review_stage(self, stage: str, artifact_path: str) -> str:
        if stage in REVIEW_STAGE_ARTIFACT_KINDS:
            return REVIEW_STAGE_ARTIFACT_KINDS[stage]
        path_name = Path(artifact_path).name
        return {
            "book_continuation_plan.json": "book_continuation_plan",
            "batch_plan.json": "batch_plan",
            "chapter_package.json": "chapter_package",
            "chapter_brief.json": "chapter_brief",
            "memory_writeback.json": "writeback_summary",
            "continuity_report.json": "writeback_summary",
        }.get(path_name, stage or "writer_artifact")

    def _revision_artifact_type_for_kind(self, artifact_kind: str, artifact_path: str) -> str | None:
        normalized = str(artifact_kind or "").strip()
        if normalized == "book_continuation_plan":
            return "BookContinuationPlan"
        if normalized == "world_expansion_pack":
            return "WorldExpansionPack"
        if normalized == "character_cast_plan":
            return "CharacterCastPlan"
        if normalized == "batch_plan":
            return "BatchPlan"
        if normalized == "chapter_brief":
            return "ChapterBrief"
        if normalized == "chapter_package":
            return "ChapterPackage"
        if normalized == "chapter_execution_input":
            return "ChapterExecutionInput"
        if artifact_path:
            return self._infer_revision_artifact_type("", artifact_path) if False else None
        return None

    def _artifact_version(self, artifact_path: str) -> str:
        if not artifact_path:
            return ""
        path = Path(artifact_path)
        try:
            return f"mtime-{int(path.stat().st_mtime)}"
        except OSError:
            return ""

    def _review_id_for_artifact(self, *, run_id: str, stage: str, artifact_kind: str) -> str:
        safe_stage = stage or "artifact"
        safe_kind = artifact_kind or "writer_artifact"
        return f"artifact-review-{run_id}-{safe_stage}-{safe_kind}-{uuid.uuid4().hex[:8]}"

    def _first_chapter_id_from_chapter_package(self, run_id: str) -> str:
        payload = self._load_optional_run_data(run_id, "chapter_package.json")
        if not isinstance(payload, Mapping):
            payload = self._load_optional_frozen_payload(run_id, "freeze_c", "chapter_package.json")
        for item in (payload or {}).get("chapters") or []:
            if isinstance(item, Mapping) and str(item.get("chapter_id") or "").strip():
                return str(item.get("chapter_id") or "").strip()
        return ""

    def _load_optional_frozen_payload(self, run_id: str, freeze_stage: str, artifact_name: str) -> dict[str, Any]:
        record = self.run_writer.get_freeze_record(run_id, freeze_stage)
        if record is None:
            return {}
        for artifact in record.artifacts:
            if artifact.name == artifact_name:
                try:
                    return self._load_artifact_payload(Path(artifact.path))
                except Exception:
                    return {}
        return {}

    def load_workflow_state(self, *, run_id: str) -> dict[str, Any] | None:
        path = self.run_writer.layout.run_dir(run_id) / "workflow_state.json"
        if not path.exists():
            return None
        raw = json.loads(path.read_text(encoding="utf-8"))
        payload = raw.get("data") if isinstance(raw, dict) else raw
        if not isinstance(payload, dict):
            return None
        return self._migrate_loaded_state(dict(payload))

    def _base_state(self, *, run_id: str, book_id: str, product_mode: str) -> dict[str, Any]:
        return {
            "schema_version": "2.0",
            "run_id": run_id,
            "book_id": book_id,
            "product_mode": product_mode,
            "confirmation_points": MODE_CONFIRMATION_POINTS[product_mode],
            "agent_state": "agent_running",
            "current_state": "agent_running",
            "technical_stage": "initialized",
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
        payload.setdefault("schema_version", "2.0")
        self._normalize_state_fields(payload)
        payload["updated_at"] = _utc_now()
        self.run_writer.write_json(run_id, "workflow_state.json", payload)

    def _migrate_loaded_state(self, state: dict[str, Any]) -> dict[str, Any]:
        state.setdefault("schema_version", "2.0")
        self._normalize_state_fields(state)
        stage = str(state.get("technical_stage") or state.get("current_stage") or "").strip()
        if stage in LEGACY_STAGE_MIGRATION_TARGETS:
            state.setdefault("legacy_stage", stage)
            state["migration_target_stage"] = LEGACY_STAGE_MIGRATION_TARGETS[stage]
            state["migration_note"] = (
                "Legacy Writer stage is recoverable for migration only; "
                "new runs do not expose it as a main user flow state."
            )
        return state

    def _normalize_state_fields(self, state: dict[str, Any]) -> None:
        technical_stage = str(state.get("technical_stage") or state.get("current_stage") or "").strip()
        if not technical_stage and str(state.get("current_stage") or "").strip() not in AGENT_STATES:
            technical_stage = str(state.get("current_stage") or "").strip()
        if str(state.get("current_stage") or "").strip() in AGENT_STATES and not technical_stage:
            technical_stage = str(state.get("technical_stage") or "").strip()
        if not technical_stage:
            technical_stage = "initialized"
        state["technical_stage"] = technical_stage
        agent_state = str(state.get("agent_state") or state.get("current_state") or "").strip()
        if agent_state not in AGENT_STATES:
            agent_state = self._agent_state_for_stage(technical_stage)
        state["agent_state"] = agent_state
        state["current_state"] = agent_state

    def _agent_state_for_stage(self, stage: str) -> str:
        normalized = str(stage or "").strip()
        return LEGACY_STAGE_TO_AGENT_STATE.get(normalized, normalized if normalized in AGENT_STATES else "agent_running")

    def _set_workflow_position(
        self,
        state: dict[str, Any],
        *,
        technical_stage: str,
        agent_state: str | None = None,
    ) -> None:
        state["technical_stage"] = technical_stage
        state["current_stage"] = technical_stage
        resolved_agent_state = agent_state or self._agent_state_for_stage(technical_stage)
        if resolved_agent_state not in AGENT_STATES:
            resolved_agent_state = "agent_running"
        state["agent_state"] = resolved_agent_state
        state["current_state"] = resolved_agent_state

    def _append_loop_event(
        self,
        *,
        run_id: str,
        event_kind: str,
        agent_state: str,
        technical_stage: str = "",
        summary: str = "",
        payload: Mapping[str, Any] | None = None,
    ) -> dict[str, Any]:
        event = WriterLoopEvent(
            event_id=f"writer-event-{uuid.uuid4().hex[:12]}",
            run_id=run_id,
            event_kind=event_kind,  # type: ignore[arg-type]
            agent_state=agent_state,  # type: ignore[arg-type]
            technical_stage=technical_stage,
            summary=summary,
            payload=dict(payload or {}),
        )
        self.run_writer.append_writer_loop_event(run_id, event)
        return event.to_dict()

    def _write_loop_step(
        self,
        *,
        run_id: str,
        status: str,
        agent_state: str,
        technical_stage: str = "",
        event_ids: list[str] | None = None,
        prompt_input_path: str = "",
        output_artifact_path: str = "",
    ) -> dict[str, Any]:
        step = WriterLoopStep(
            step_id=f"writer-step-{uuid.uuid4().hex[:12]}",
            run_id=run_id,
            status=status,  # type: ignore[arg-type]
            agent_state=agent_state,  # type: ignore[arg-type]
            technical_stage=technical_stage,
            event_ids=list(event_ids or []),
            prompt_input_path=prompt_input_path,
            output_artifact_path=output_artifact_path,
            completed_at=_utc_now() if status == "completed" else "",
        )
        self.run_writer.write_writer_loop_step(run_id, step)
        return step.to_dict()

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
                "chapters": list(target_artifact.get("chapters") or []),
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
                fields=("batch_id", "book_id", "chapters", "batch_goal", "planned_character_beats"),
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
        self._set_workflow_position(
            state,
            technical_stage=str(result.validation.get("target_stage") or state.get("technical_stage") or state.get("current_stage") or ""),
            agent_state="reviewing_artifact",
        )
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
        self._set_workflow_position(state, technical_stage=stage)
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
        self._set_workflow_position(state, technical_stage=stage)
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
        _ = mode
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
            self._set_workflow_position(state, technical_stage="wait_chapter_acceptance", agent_state="reviewing_draft")
            return checkpoint
        if status == "accepted":
            state["pending_checkpoint"] = None
            state["terminal_stage"] = None
            checkpoint = self._write_checkpoint(
                run_id=run_id,
                stage="writeback_review",
                artifact_path=continuity_report_path,
                source=source,
            )
            state["pending_checkpoint"] = checkpoint
            state["terminal_stage"] = None
            self._set_workflow_position(state, technical_stage="writeback_review", agent_state="writeback_review")
            return checkpoint
        if status == "rewrite_requested":
            state["pending_checkpoint"] = None
            state["terminal_stage"] = None
            self._set_workflow_position(state, technical_stage="freeze_d", agent_state="generating_draft")
            return {"stage": "generating_draft", "artifact_path": decision_path, "source": source}
        if status == "replan_requested":
            checkpoint = self._write_checkpoint(
                run_id=run_id,
                stage="chapter_review",
                artifact_path=str(run_dir / "chapter_package.json"),
                source=source,
            )
            state["pending_checkpoint"] = checkpoint
            state["terminal_stage"] = None
            self._set_workflow_position(state, technical_stage="chapter_review", agent_state="reviewing_artifact")
            return checkpoint
        if status == "discarded":
            state["pending_checkpoint"] = None
            state["terminal_stage"] = {
                "stage": "halted",
                "artifact_path": decision_path,
                "source": source,
            }
            self._set_workflow_position(state, technical_stage="halted", agent_state="halted")
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
        status = str(payload.get("status") or "").strip().lower().replace("-", "_")
        return {
            "revise_length": "rewrite_requested",
            "replan_chapter": "replan_requested",
        }.get(status, status)

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
            "next_action": "",
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
        # Group L keeps legacy rework payloads embedded in generation_review_decision.json
        # for migration traceability, but standalone files are no longer active flow inputs.
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
                summary="正文执行、用户草稿决策与正式回写完成。",
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

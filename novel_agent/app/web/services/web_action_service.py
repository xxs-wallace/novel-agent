from __future__ import annotations

import asyncio
import json
import os
import sqlite3
import uuid
from pathlib import Path
from typing import Any, Mapping

from ...cli.events import RunEvent
from ...constants import DEFAULT_CLOSE_READING_STAGE
from ...cli.status import WriterStatusPresenter
from ...llm import JsonModelClient, ModelSettings
from ...repos.character_profiles_repo import CharacterProfilesRepo
from ...repos.db import NovelAgentDB
from ...reviewer.registry import ReviewerRegistry
from ...reviewer.reviewers import default_reviewers
from ...reviewer.runtime import ReviewerRuntime
from ...reviewer.suite import ReviewerSuite
from ...reviewer.target_resolver import ReviewTargetResolver
from ...reviewer.tools import ReviewerArtifactTool, ReviewerMemoryTool
from ...schemas.reviewer_schema import ReviewBudget, ReviewContextPolicy, ReviewRequest, ReviewTarget, utc_now
from ...services.character_identity_merge_service import CharacterIdentityMergeEvidence, CharacterIdentityMergeService
from ..schemas import DecisionCard, WebActionRequest, WebActionResult
from .artifact_ids import decode_artifact_id
from .artifact_view_service import ArtifactViewService
from .job_manager import JobContext, JobManager
from .web_session_service import WebSessionService


def _model_dump(model: Any) -> dict[str, Any]:
    if hasattr(model, "model_dump"):
        return model.model_dump()
    return model.dict()


def _truthy(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    return str(value or "").strip().lower() in {"1", "true", "yes", "y", "on", "是", "允许", "需要", "开"}


class WebActionService:
    """Maps browser-native actions to shared Novel Agent capabilities."""

    _JOB_ACTION_TYPES = {
        "start_read": "read",
        "start_close_read": "close_read",
        "build_creative_kb": "kb",
        "build_narrative_scene_index": "narrative_scene_index",
        "start_writer": "writer",
        "resume": "writer_resume",
        "run_reviewer": "reviewer",
    }
    _EXCLUSIVE_TASK_JOB_TYPES = {"read", "close_read", "kb", "narrative_scene_index", "writer", "writer_resume", "reviewer"}

    _WRITER_REVIEW_ACTIONS = {
        "confirm_current_step",
        "approve_writer_artifact",
        "request_writer_artifact_revision",
        "defer_writer_artifact_review",
        "request_scoped_artifact_revision",
        "apply_scoped_artifact_revision",
        "discard_scoped_artifact_revision",
        "reject_scoped_artifact_revision",
        "accept_chapter",
        "rewrite_chapter",
        "revise_chapter_length",
        "replan_chapter",
        "discard_chapter",
        "approve_writeback",
        "submit_outline_research_answers",
        "submit_draft_research_answers",
    }

    _DIRECT_WRITER_WORKFLOW_ACTIONS = {
        "approve_writer_artifact",
        "request_writer_artifact_revision",
        "defer_writer_artifact_review",
        "request_scoped_artifact_revision",
        "apply_scoped_artifact_revision",
        "discard_scoped_artifact_revision",
        "reject_scoped_artifact_revision",
        "accept_chapter",
        "rewrite_chapter",
        "revise_chapter_length",
        "replan_chapter",
        "discard_chapter",
        "approve_writeback",
        "submit_outline_research_answers",
        "submit_draft_research_answers",
    }

    _SUPPORTED_ACTIONS = {
        "select_task",
        "create_task",
        "start_read",
        "start_close_read",
        "build_creative_kb",
        "build_narrative_scene_index",
        "start_writer",
        "resume",
        "run_reviewer",
        "confirm_current_step",
        "approve_writer_artifact",
        "request_writer_artifact_revision",
        "defer_writer_artifact_review",
        "request_scoped_artifact_revision",
        "apply_scoped_artifact_revision",
        "discard_scoped_artifact_revision",
        "reject_scoped_artifact_revision",
        "accept_chapter",
        "rewrite_chapter",
        "revise_chapter_length",
        "replan_chapter",
        "discard_chapter",
        "defer_chapter_acceptance",
        "submit_outline_research_answers",
        "submit_draft_research_answers",
        "defer_outline_research_answers",
        "defer_draft_research_answers",
        "approve_writeback",
        "go_back",
        "save_artifact",
        "show_debug_details",
        "confirm_identity_merge",
        "reject_identity_merge",
        "request_identity_merge_more_evidence",
        "route_identity_merge_to_correction",
    }

    def __init__(
        self,
        *,
        session_service: WebSessionService,
        job_manager: JobManager,
        artifact_view_service: ArtifactViewService,
        status_presenter: WriterStatusPresenter | None = None,
    ) -> None:
        self.session_service = session_service
        self.job_manager = job_manager
        self.artifact_view_service = artifact_view_service
        self.status_presenter = status_presenter or WriterStatusPresenter()

    async def execute(self, *, task_id: str, request: WebActionRequest) -> WebActionResult:
        action = request.action.strip()
        payload = dict(request.payload or {})
        if action not in self._SUPPORTED_ACTIONS:
            raise ValueError(f"未知 Web action：{action}")
        if action == "select_task":
            selected = self.session_service.select_task(task_id=str(payload.get("task_id") or task_id))
            return WebActionResult(
                action=action,
                task_id=selected.task_id,
                message=f"已进入任务 {selected.task_id}。",
                payload={"task": _model_dump(selected)},
                progress=selected.progress,
            )
        if action == "create_task":
            requested_task_id = str(payload.get("task_id") or payload.get("book_id") or task_id)
            summary = self.session_service.create_task(
                task_id=requested_task_id,
                source_path=str(payload.get("source_path") or ""),
            )
            return WebActionResult(
                action=action,
                task_id=summary.task_id,
                message=f"已创建任务 {summary.task_id}。",
                payload={"task": _model_dump(summary)},
                progress=summary.progress,
            )
        if action == "resume":
            return await self._resume_writer_action(task_id=task_id, payload=payload)
        if action in self._JOB_ACTION_TYPES:
            if action == "run_reviewer":
                self._preflight_reviewer_action(task_id=task_id, payload=payload)
            return await self._start_job_action(task_id=task_id, action=action, payload=payload)
        if action == "defer_chapter_acceptance":
            return self._defer_chapter_acceptance(task_id=task_id, payload=payload)
        if action in {"defer_outline_research_answers", "defer_draft_research_answers"}:
            return self._defer_writer_question_answers(task_id=task_id, action=action, payload=payload)
        if action in self._WRITER_REVIEW_ACTIONS:
            return await self._start_writer_review_action(task_id=task_id, action=action, payload=payload)
        if action in {
            "confirm_identity_merge",
            "reject_identity_merge",
            "request_identity_merge_more_evidence",
            "route_identity_merge_to_correction",
        }:
            return self._identity_merge_review_action(task_id=task_id, action=action, payload=payload)
        if action == "go_back":
            return self._go_back(task_id=task_id, payload=payload)
        if action == "save_artifact":
            return self._save_artifact(task_id=task_id, payload=payload)
        return WebActionResult(
            action=action,
            task_id=task_id,
            message="技术详情已准备好。",
            technical_details=self.session_service.debug_details(task_id),
        )

    async def _resume_writer_action(self, *, task_id: str, payload: dict[str, Any]) -> WebActionResult:
        writer_state = self.session_service.latest_writer_state(task_id)
        run_id = str(payload.get("run_id") or writer_state.get("run_id") or "")
        if not run_id:
            message = "没有找到可恢复的 Writer 运行。请先开始续写。"
            self.session_service.append_message(task_id, role="assistant", content=message, payload={"channel": "writer_resume"})
            return WebActionResult(
                action="resume",
                task_id=task_id,
                message=message,
                progress=self.session_service.task_progress(task_id),
            )

        self.session_service.sync_writer_question_messages(task_id)
        self.session_service.sync_writer_review_messages(task_id)
        active_stage = self.session_service._active_writer_stage(writer_state)
        if self.session_service.has_writer_gate_message(task_id, run_id, active_stage=active_stage):
            message = "已恢复到上一次等待点，请在会话卡片中继续。"
            self.session_service.append_message(
                task_id,
                role="assistant",
                content=message,
                payload={"channel": "writer_resume", "run_id": run_id},
            )
            return WebActionResult(
                action="resume",
                task_id=task_id,
                message=message,
                progress=self.session_service.task_progress(task_id),
            )

        resume_workflow_action = self._workflow_action_for_resumable_stage(writer_state)
        if resume_workflow_action:
            return await self._start_job_action(
                task_id=task_id,
                action="resume",
                payload={**payload, "run_id": run_id, "workflow_action": resume_workflow_action},
            )

        recovery_message = self.session_service.append_writer_recovery_message(
            task_id,
            writer_state=writer_state,
            force=True,
        )
        return WebActionResult(
            action="resume",
            task_id=task_id,
            message=recovery_message.content,
            decision_cards=list(recovery_message.decision_cards),
            progress=self.session_service.task_progress(task_id),
            technical_details={
                "run_id": run_id,
                "current_stage": str(writer_state.get("current_stage") or ""),
            },
        )

    def _workflow_action_for_resumable_stage(self, writer_state: dict[str, Any]) -> str:
        pending = writer_state.get("pending_checkpoint") if isinstance(writer_state.get("pending_checkpoint"), dict) else {}
        if pending:
            return ""
        stage = str(writer_state.get("current_stage") or "")
        resumable_stages = {"freeze_a", "freeze_b", "freeze_c", "freeze_d"}
        if stage not in resumable_stages:
            return ""
        actions = self.status_presenter.writer_actions_for_stage(stage=stage)
        return actions[0].workflow_action if actions else ""

    async def _start_job_action(self, *, task_id: str, action: str, payload: dict[str, Any]) -> WebActionResult:
        job_type = self._JOB_ACTION_TYPES[action]
        runner = None if os.getenv("NOVEL_AGENT_WEB_JOB_MODE", "").strip().lower() == "fake" else self._run_background_action
        job = await self.job_manager.create_job(
            task_id=task_id,
            job_type=job_type,
            payload={"action": action, **payload},
            runner=runner,
            conflict_job_types=self._EXCLUSIVE_TASK_JOB_TYPES,
        )
        if job.type != job_type:
            message = "已有后台任务正在运行，已复用现有任务；请等它结束后再触发当前动作。"
        else:
            message = {
                "start_read": "已准备开始导入原文，进度会通过后台事件更新。",
                "start_close_read": "已准备开始阅读，进度会通过后台事件更新。",
                "build_creative_kb": "已准备构建 Creative KB，进度会通过后台事件更新。",
                "build_narrative_scene_index": "已准备构建叙事场景索引，进度会通过后台事件更新。",
                "start_writer": "已收到续写意图，Writer 正在生成下一条可审阅内容；需要你回答、审阅、验收或决定草稿时会继续发到会话里。",
                "resume": "已准备恢复最近一次未完成流程。",
                "run_reviewer": "已准备运行 Reviewer，报告完成后会发到会话里。",
            }[action]
        message_payload: dict[str, Any] = {"job_id": job.job_id}
        if action == "start_writer":
            message_payload["writer_request"] = dict(payload)
        self.session_service.append_message(task_id, role="assistant", content=message, payload=message_payload)
        return WebActionResult(
            action=action,
            task_id=task_id,
            message=message,
            job=job,
            decision_cards=[],
            progress=self.session_service.task_progress(task_id),
        )

    async def _run_background_action(self, context: JobContext) -> dict[str, Any]:
        if context.job_type == "read":
            return await self._run_read_pipeline(context, read_only=True)
        if context.job_type == "close_read":
            return await self._run_read_pipeline(context, read_only=False)
        if context.job_type == "kb":
            return await self._run_creative_kb(context)
        if context.job_type == "narrative_scene_index":
            return await self._run_narrative_scene_index(context)
        if context.job_type == "writer":
            return await self._run_writer(context)
        if context.job_type == "writer_resume":
            return await self._run_writer_resume(context)
        if context.job_type == "reviewer":
            return await self._run_reviewer(context)
        raise ValueError(f"不支持的后台任务类型：{context.job_type}")

    async def _run_read_pipeline(self, context: JobContext, *, read_only: bool) -> dict[str, Any]:
        snapshot = self.session_service.facade.task_snapshot(book_id=context.task_id)
        source_path = self._resolve_source_path(snapshot.source_path)
        if not source_path:
            raise ValueError("当前任务没有原文路径，请先在任务信息中配置 source_path。")
        if not source_path.exists():
            raise FileNotFoundError(f"原文文件不存在：{source_path}")
        api_key = self._require_api_key()
        db_path = snapshot.db_path or self.session_service.facade.db_path_for_book(context.task_id)
        debug_path = self._debug_path(context, "read")
        payload = context.payload

        if read_only:
            context.emit("progress", "开始完整导入原文并写入索引。")
            result = await self._call_facade_with_events(
                context,
                lambda: self.session_service.facade.start_read_pipeline(
                    book_id=context.task_id,
                    source_path=source_path,
                    db_path=db_path,
                    debug_path=debug_path,
                    api_key=api_key,
                    run_mode="resume" if db_path.exists() else "fresh",
                    max_read_kb=self._optional_int(
                        payload,
                        "max_read_kb",
                        default=self._env_optional_int("NOVEL_AGENT_WEB_MAX_READ_KB"),
                    ),
                    max_close_batches=0,
                    segment_step_kb=self._optional_int(payload, "segment_step_kb", default=32) or 32,
                    close_step_batches=1,
                    build_creative_kb=False,
                    should_stop=context.should_cancel,
                ),
            )
            context.emit("progress", "原文导入本轮已完成，任务状态会刷新。", payload=self._progress_payload(context.task_id))
            return dict(result)

        context.emit("progress", "开始运行阅读建模。")
        result = await self._call_facade_with_events(
            context,
            lambda: self.session_service.facade.start_read_pipeline(
                book_id=context.task_id,
                source_path=source_path,
                db_path=db_path,
                debug_path=debug_path,
                api_key=api_key,
                run_mode="resume",
                max_read_kb=0,
                max_close_batches=self._optional_int(
                    payload,
                    "max_close_batches",
                    default=self._env_optional_int("NOVEL_AGENT_WEB_MAX_CLOSE_BATCHES"),
                ),
                segment_step_kb=1,
                close_step_batches=self._optional_int(payload, "close_step_batches", default=1) or 1,
                build_creative_kb=False,
                close_document_chars_budget=self._optional_int(
                    payload,
                    "close_document_chars_budget",
                    default=self._env_int("NOVEL_AGENT_WEB_CLOSE_DOCUMENT_CHARS_BUDGET", 20000),
                )
                or 20000,
                should_stop=context.should_cancel,
            ),
        )
        result_payload = dict(result)
        if not _truthy(payload.get("skip_scene_index")) and hasattr(self.session_service.facade, "build_narrative_scene_index"):
            context.emit("progress", "阅读完成，开始构建叙事场景索引。")
            try:
                scene_result = await self._call_facade_with_events(
                    context,
                    lambda: self.session_service.facade.build_narrative_scene_index(
                        db_path=db_path,
                        book_id=context.task_id,
                        api_key=api_key,
                        dry_run=_truthy(payload.get("scene_index_dry_run")),
                        window_chars_budget=self._optional_int(
                            payload,
                            "scene_index_window_chars",
                            default=self._env_optional_int("NOVEL_AGENT_WEB_SCENE_INDEX_WINDOW_CHARS"),
                        ),
                        overlap_docs=self._optional_int(
                            payload,
                            "scene_index_overlap_docs",
                            default=self._env_optional_int("NOVEL_AGENT_WEB_SCENE_INDEX_OVERLAP_DOCS"),
                        ),
                    ),
                )
                result_payload["narrative_scene_index"] = dict(scene_result)
                context.emit("progress", "叙事场景索引已完成，右侧结果浏览器会刷新。", payload=self._progress_payload(context.task_id))
            except Exception as exc:
                result_payload["narrative_scene_index_error"] = str(exc)
                context.emit(
                    "log",
                    "叙事场景索引构建失败；阅读结果已保留，可稍后单独重试。",
                    payload={"error": str(exc)},
                )
        context.emit("progress", "阅读本轮已完成，右侧结果浏览器会刷新。", payload=self._progress_payload(context.task_id))
        return result_payload

    async def _run_creative_kb(self, context: JobContext) -> dict[str, Any]:
        api_key = self._require_api_key()
        snapshot = self.session_service.facade.task_snapshot(book_id=context.task_id)
        db_path = snapshot.db_path or self.session_service.facade.db_path_for_book(context.task_id)
        if not db_path.exists():
            raise FileNotFoundError("还没有任务索引，请先导入原文并完成阅读。")
        context.emit("progress", "开始构建 Creative KB。")
        result = await self._call_facade_with_events(
            context,
            lambda: self.session_service.facade.build_creative_kb(
                db_path=db_path,
                book_id=context.task_id,
                api_key=api_key,
            ),
        )
        context.emit("progress", "Creative KB 构建完成。", payload=self._progress_payload(context.task_id))
        return dict(result)

    async def _run_narrative_scene_index(self, context: JobContext) -> dict[str, Any]:
        payload = context.payload
        dry_run = _truthy(payload.get("dry_run"))
        api_key = "" if dry_run else self._require_api_key()
        snapshot = self.session_service.facade.task_snapshot(book_id=context.task_id)
        db_path = snapshot.db_path or self.session_service.facade.db_path_for_book(context.task_id)
        if not db_path.exists():
            raise FileNotFoundError("还没有任务索引，请先导入原文并完成阅读。")
        context.emit("progress", "开始构建叙事场景索引。")
        result = await self._call_facade_with_events(
            context,
            lambda: self.session_service.facade.build_narrative_scene_index(
                db_path=db_path,
                book_id=context.task_id,
                api_key=api_key,
                dry_run=dry_run,
                window_chars_budget=self._optional_int(
                    payload,
                    "window_chars",
                    default=self._env_optional_int("NOVEL_AGENT_WEB_SCENE_INDEX_WINDOW_CHARS"),
                ),
                overlap_docs=self._optional_int(
                    payload,
                    "overlap_docs",
                    default=self._env_optional_int("NOVEL_AGENT_WEB_SCENE_INDEX_OVERLAP_DOCS"),
                ),
            ),
        )
        context.emit("progress", "叙事场景索引构建完成。", payload=self._progress_payload(context.task_id))
        return dict(result)

    async def _run_writer(self, context: JobContext) -> dict[str, Any]:
        payload = context.payload
        api_key = str(payload.get("api_key") or os.getenv("DEEPSEEK_API_KEY") or "").strip() or None
        dry_run = self._writer_dry_run_requested(payload)
        intent_payload = self._writer_intent_payload(payload)
        target_chapter_count = self._optional_int(payload, "target_chapter_count", default=None)
        if target_chapter_count is None:
            target_chapter_count = self._optional_int(payload, "target_chapters", default=3) or 3
        chapter_count = self._optional_int(payload, "chapter_count", default=target_chapter_count) or target_chapter_count
        previous_result = await self._continue_previous_writer_chapter_if_requested(
            context=context,
            payload=payload,
            dry_run=dry_run,
            api_key=api_key,
        )
        if previous_result is not None:
            self._append_writer_result_messages(task_id=context.task_id, result_payload=dict(previous_result))
            return dict(previous_result)
        if self._completion_request_needs_new_direction(payload):
            result = {
                "status": "needs_user_direction",
                "message": "当前批次已经写完。请先补充下一批续写方向，再开始新一轮规划。",
                "previous_run_id": str(payload.get("previous_run_id") or ""),
            }
            self._append_writer_result_messages(task_id=context.task_id, result_payload=result)
            return result
        run_id = str(payload.get("run_id") or uuid.uuid4().hex)
        context.emit("progress", "开始 Writer 分层生成。")
        context.emit(
            "log",
            "Writer 创建请求已保存。",
            payload={"run_id": run_id, "writer_request": dict(payload), "intent_payload": dict(intent_payload)},
        )
        result = await self._call_facade_with_events(
            context,
            lambda: self.session_service.facade.start_writer(
                book_id=context.task_id,
                run_id=run_id,
                product_mode=str(payload.get("product_mode") or "assist"),
                dry_run=dry_run,
                api_key=api_key,
                intent_payload=intent_payload,
                user_world_notes=str(payload.get("user_world_notes") or payload.get("constraints") or ""),
                target_chapter_count=target_chapter_count,
                chapter_count=chapter_count,
                allow_incomplete_modeling=True,
            ),
        )
        context.emit("progress", "Writer 已到达可审阅节点。", payload={"run_id": result.get("run_id", "")})
        result_payload = dict(result)
        self._append_writer_result_messages(task_id=context.task_id, result_payload=result_payload)
        self._attach_current_writer_decision_cards(context.task_id, result_payload)
        return result_payload

    async def _continue_previous_writer_chapter_if_requested(
        self,
        *,
        context: JobContext,
        payload: Mapping[str, Any],
        dry_run: bool,
        api_key: str | None,
    ) -> dict[str, Any] | None:
        previous_run_id = str(payload.get("previous_run_id") or "").strip()
        if str(payload.get("requested_from") or "") != "writer_completion" or not previous_run_id:
            return None
        if self._completion_continue_has_new_direction(payload):
            return None
        chapter_id = self._next_chapter_id_from_run(previous_run_id)
        if not chapter_id:
            return None

        product_mode = str(payload.get("product_mode") or "assist")
        context.emit(
            "progress",
            "继续上一轮已确认规划，准备下一章草稿。",
            payload={"run_id": previous_run_id, "chapter_id": chapter_id},
        )
        execution_input = await self._call_facade_with_events(
            context,
            lambda: self.session_service.facade.writer_action(
                book_id=context.task_id,
                run_id=previous_run_id,
                action="prepare_execution",
                product_mode=product_mode,
                payload={"chapter_id": chapter_id},
                dry_run=dry_run,
                api_key=api_key,
            ),
        )
        execution_result = await self._call_facade_with_events(
            context,
            lambda: self.session_service.facade.writer_action(
                book_id=context.task_id,
                run_id=previous_run_id,
                action="execute_current_chapter",
                product_mode=product_mode,
                payload={},
                dry_run=dry_run,
                api_key=api_key,
            ),
        )
        if str(execution_result.get("status") or "") == "draft_research_not_ready":
            draft_status = str(execution_result.get("draft_research_status") or "")
            context.emit(
                "progress",
                "下一章正文研究需要补充信息。",
                payload={"run_id": previous_run_id, "chapter_id": chapter_id},
            )
            return {
                "status": "draft_research_not_ready",
                "run_id": previous_run_id,
                "chapter_id": chapter_id,
                "workflow_stage": "draft_research_user_input" if draft_status == "needs_user_input" else "",
                "execution_input": execution_input,
                "execution_result": execution_result,
            }
        context.emit(
            "progress",
            "下一章草稿已生成，等待你决定是否接受。",
            payload={"run_id": previous_run_id, "chapter_id": chapter_id},
        )
        return {
            "status": "waiting_for_draft_review",
            "run_id": previous_run_id,
            "chapter_id": chapter_id,
            "workflow_stage": "wait_chapter_acceptance",
            "execution_input": execution_input,
            "execution_result": execution_result,
        }

    @staticmethod
    def _completion_continue_has_new_direction(payload: Mapping[str, Any]) -> bool:
        for key in ("feedback_text", "user_feedback", "supplement_text", "revision_feedback", "preferred_outcome"):
            if str(payload.get(key) or "").strip():
                return True
        for key in ("desired_actions", "major_characters", "avoidances"):
            value = payload.get(key)
            if isinstance(value, list) and any(str(item).strip() for item in value):
                return True
            if isinstance(value, str) and value.strip():
                return True
        intent_payload = payload.get("intent_payload")
        if isinstance(intent_payload, Mapping):
            for key in ("desired_actions", "major_characters", "avoidances", "preferred_outcome", "notes"):
                value = intent_payload.get(key)
                if isinstance(value, list) and any(str(item).strip() for item in value):
                    return True
                if isinstance(value, str) and value.strip():
                    return True
        return False

    def _completion_request_needs_new_direction(self, payload: Mapping[str, Any]) -> bool:
        requested_from = str(payload.get("requested_from") or "")
        previous_run_id = str(payload.get("previous_run_id") or "").strip()
        if requested_from not in {"writer_completion", "writer_new_batch"} or not previous_run_id:
            return False
        if self._completion_continue_has_new_direction(payload):
            return False
        if requested_from == "writer_new_batch":
            return True
        return not bool(self._next_chapter_id_from_run(previous_run_id))

    def _next_chapter_id_from_run(self, run_id: str) -> str:
        run_dir = self.session_service.repo_root / "runs" / "writer" / run_id
        state = self._load_writer_run_json(run_dir / "workflow_state.json")
        current_chapter_id = str(state.get("current_chapter_id") or "").strip()
        if not current_chapter_id:
            review = self._load_writer_run_json(run_dir / "generation_review_decision.json")
            current_chapter_id = str(review.get("chapter_id") or "").strip()
        package = self._load_writer_run_json(run_dir / "chapter_package.json")
        if not package:
            package = self._load_writer_run_json(run_dir / "freezes" / "freeze_c" / "chapter_package.json")
        chapter_ids = [
            str(item.get("chapter_id") or "").strip()
            for item in (package.get("chapters") or [])
            if isinstance(item, Mapping) and str(item.get("chapter_id") or "").strip()
        ]
        if not chapter_ids:
            return ""
        if current_chapter_id in chapter_ids:
            current_index = chapter_ids.index(current_chapter_id)
            if current_index + 1 < len(chapter_ids):
                return chapter_ids[current_index + 1]
            return ""
        return chapter_ids[0]

    @staticmethod
    def _load_writer_run_json(path: Path) -> dict[str, Any]:
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return {}
        if isinstance(payload, Mapping) and isinstance(payload.get("data"), Mapping):
            return dict(payload["data"])
        return dict(payload) if isinstance(payload, Mapping) else {}

    async def _run_writer_resume(self, context: JobContext) -> dict[str, Any]:
        payload = context.payload
        run_id = str(payload.get("run_id") or self.session_service.latest_writer_state(context.task_id).get("run_id") or "")
        if not run_id:
            raise ValueError("没有找到可恢复的 Writer run。")
        api_key = str(payload.get("api_key") or os.getenv("DEEPSEEK_API_KEY") or "").strip() or None
        dry_run = self._writer_dry_run_requested(payload)
        workflow_action = self._resolve_writer_workflow_action(
            task_id=context.task_id,
            action=str(payload.get("action") or ""),
            payload=payload,
        )
        context.emit("progress", self._writer_workflow_progress_message(workflow_action))
        result = await self._call_facade_with_events(
            context,
            lambda: self.session_service.facade.writer_action(
                book_id=context.task_id,
                run_id=run_id,
                action=workflow_action,
                product_mode=str(payload.get("product_mode") or "assist"),
                payload={**dict(payload), "workflow_action": workflow_action},
                dry_run=dry_run,
                api_key=api_key,
            ),
        )
        result_payload = dict(result)
        if workflow_action == "accept_chapter":
            context.emit(
                "progress",
                "本章草稿已接受，正在作为一个事务提交正文和续写记忆更新。",
                payload={"run_id": run_id},
            )
            writeback_payload = await self._call_facade_with_events(
                context,
                lambda: self.session_service.facade.writer_action(
                    book_id=context.task_id,
                    run_id=run_id,
                    action="approve_writeback",
                    product_mode=str(payload.get("product_mode") or "assist"),
                    payload={**dict(payload), "workflow_action": "approve_writeback", "source_action": "accept_chapter"},
                    dry_run=dry_run,
                    api_key=api_key,
                ),
            )
            result_payload = {"acceptance_result": result_payload, "writeback_result": dict(writeback_payload)}
            next_chapter_payload = await self._continue_next_chapter_after_writeback_if_available(
                context=context,
                run_id=run_id,
                product_mode=str(payload.get("product_mode") or "assist"),
                dry_run=dry_run,
                api_key=api_key,
                writeback_result=dict(writeback_payload),
            )
            if next_chapter_payload is not None:
                result_payload = next_chapter_payload
        elif workflow_action == "approve_writeback":
            next_chapter_payload = await self._continue_next_chapter_after_writeback_if_available(
                context=context,
                run_id=run_id,
                product_mode=str(payload.get("product_mode") or "assist"),
                dry_run=dry_run,
                api_key=api_key,
                writeback_result=result_payload,
            )
            if next_chapter_payload is not None:
                result_payload = next_chapter_payload
        self._append_writer_result_messages(task_id=context.task_id, result_payload=result_payload)
        self._attach_current_writer_decision_cards(context.task_id, result_payload)
        context.emit(
            "progress",
            "Writer 状态已更新，新的审阅入口会刷新到会话区。",
            payload={"run_id": run_id, "workflow_action": workflow_action},
        )
        return result_payload

    async def _continue_next_chapter_after_writeback_if_available(
        self,
        *,
        context: JobContext,
        run_id: str,
        product_mode: str,
        dry_run: bool,
        api_key: str | None,
        writeback_result: Mapping[str, Any],
    ) -> dict[str, Any] | None:
        next_chapter_id = self._next_chapter_id_from_run(run_id)
        if not next_chapter_id:
            return None
        context.emit(
            "progress",
            "写回已完成，继续生成下一章草稿。",
            payload={"run_id": run_id, "chapter_id": next_chapter_id},
        )
        execution_input = await self._call_facade_with_events(
            context,
            lambda: self.session_service.facade.writer_action(
                book_id=context.task_id,
                run_id=run_id,
                action="prepare_execution",
                product_mode=product_mode,
                payload={"chapter_id": next_chapter_id},
                dry_run=dry_run,
                api_key=api_key,
            ),
        )
        execution_result = await self._call_facade_with_events(
            context,
            lambda: self.session_service.facade.writer_action(
                book_id=context.task_id,
                run_id=run_id,
                action="execute_current_chapter",
                product_mode=product_mode,
                payload={},
                dry_run=dry_run,
                api_key=api_key,
            ),
        )
        if str(execution_result.get("status") or "") == "draft_research_not_ready":
            draft_status = str(execution_result.get("draft_research_status") or "")
            if draft_status == "needs_user_input":
                context.emit(
                    "progress",
                    "下一章正文研究需要补充信息，已生成问题卡。",
                    payload={"run_id": run_id, "chapter_id": next_chapter_id},
                )
            return {
                "status": "draft_research_not_ready",
                "run_id": run_id,
                "chapter_id": next_chapter_id,
                "workflow_stage": "draft_research_user_input" if draft_status == "needs_user_input" else "",
                "writeback_result": dict(writeback_result),
                "execution_input": execution_input,
                "execution_result": execution_result,
            }
        return {
            "status": "waiting_for_draft_review",
            "run_id": run_id,
            "chapter_id": next_chapter_id,
            "workflow_stage": "wait_chapter_acceptance",
            "writeback_result": dict(writeback_result),
            "execution_input": execution_input,
            "execution_result": execution_result,
        }

    async def _run_reviewer(self, context: JobContext) -> dict[str, Any]:
        payload = dict(context.payload or {})
        api_key = self._require_api_key()
        registry = ReviewerRegistry(default_reviewers())
        reviewer_ids = self._reviewer_ids_from_payload(payload)
        target_type = str(payload.get("target_type") or "").strip()
        if not target_type and len(reviewer_ids) == 1:
            manifest = registry.get(reviewer_ids[0]).manifest()
            if len(manifest.supported_target_types) == 1:
                target_type = manifest.supported_target_types[0]
        if not target_type:
            raise ValueError("Reviewer action 缺少 target_type。")
        for reviewer_id in reviewer_ids:
            registry.get(reviewer_id, target_type=target_type)

        target = self._review_target_from_payload(context, payload=payload, target_type=target_type)
        budget = self._review_budget_from_payload(registry=registry, reviewer_ids=reviewer_ids, payload=payload)
        request = ReviewRequest(
            review_request_id=str(payload.get("review_request_id") or f"web-review-{context.job_id}"),
            book_id=context.task_id,
            target=target,
            reviewer_ids=reviewer_ids,
            context_policy=ReviewContextPolicy(
                purpose="user_review" if target_type == "source_chapter" else "writer_assist",
                allow_memory=True,
                allow_kb=target_type != "source_chapter",
                allow_writer_artifacts=target_type != "source_chapter",
                allow_reference_truth=False,
                allowed_artifact_kinds=[
                    "outline",
                    "synopsis",
                    "chapter_brief",
                    "draft",
                    "book_plan",
                    "batch_plan",
                    "chapter_package",
                ],
                leakage_guard="prefix_only",
                notes="Web UI Reviewer 入口只提供参考评分和修改意见，不推进 Writer 或 benchmark 决策。",
            ),
            budget=budget,
            created_at=utc_now(),
            user_focus=str(payload.get("user_focus") or ""),
            metadata={
                "source": str(payload.get("source") or "web_ui"),
                "run_id": str(payload.get("run_id") or ""),
                "review_id": str(payload.get("review_id") or ""),
                "artifact_kind": str(payload.get("artifact_kind") or ""),
                "reviewer_label": str(payload.get("reviewer_label") or ""),
            },
        )
        snapshot = self.session_service.facade.task_snapshot(book_id=context.task_id)
        db_path = Path(snapshot.db_path or self.session_service.facade.db_path_for_book(context.task_id))
        if not db_path.exists():
            raise FileNotFoundError("Reviewer 需要先完成任务索引和 Memory/KB 准备，当前没有可用数据库。")
        artifact_root = self.session_service.repo_root / "runs" / "web_reviewer" / context.task_id / context.job_id
        model_client = JsonModelClient(self._reviewer_model_settings(api_key=api_key, payload=payload))
        runtime = ReviewerRuntime(
            model_client=model_client,
            target_resolver=ReviewTargetResolver(repo_root=self.session_service.repo_root),
            memory_tool=ReviewerMemoryTool(repo_root=self.session_service.repo_root),
            artifact_tool=ReviewerArtifactTool(repo_root=self.session_service.repo_root),
            artifact_root=artifact_root,
        )
        suite = ReviewerSuite(registry=registry, runtime=runtime, artifact_root=artifact_root)
        label = str(payload.get("reviewer_label") or "Reviewer")
        context.emit("progress", f"开始运行 {label}。", payload={"reviewer_ids": reviewer_ids, "target_type": target_type})

        def call() -> dict[str, Any]:
            with sqlite3.connect(db_path) as conn:
                conn.row_factory = sqlite3.Row
                return suite.run(request, conn=conn).to_dict()

        report_payload = await asyncio.to_thread(call)
        report_path = artifact_root / request.review_request_id / "suite_report.json"
        message = self._reviewer_report_message(label=label, report=report_payload)
        self.session_service.append_message(
            context.task_id,
            role="assistant",
            content=message,
            payload={
                "channel": "reviewer_report",
                "run_id": str(payload.get("run_id") or ""),
                "review_request_id": request.review_request_id,
                "reviewer_ids": reviewer_ids,
                "target_id": target.target_id,
                "target_type": target.target_type,
                "report_path": str(report_path),
            },
        )
        context.emit(
            "progress",
            f"{label} 已完成。",
            payload={
                "review_request_id": request.review_request_id,
                "status": report_payload.get("status"),
                "overall_score": report_payload.get("overall_score"),
                "report_path": str(report_path),
            },
        )
        return {
            "review_request": request.to_dict(),
            "suite_report": report_payload,
            "report_path": str(report_path),
        }

    async def _call_facade_with_events(self, context: JobContext, call: Any) -> dict[str, Any]:
        event_stream = getattr(self.session_service.facade, "event_stream", None)
        if event_stream is not None and hasattr(event_stream, "clear"):
            event_stream.clear()
        task = asyncio.create_task(asyncio.to_thread(call))
        while not task.done():
            self._emit_facade_events(context)
            await asyncio.sleep(0.5)
        try:
            result = await task
        finally:
            self._emit_facade_events(context)
        return dict(result or {})

    def _emit_facade_events(self, context: JobContext) -> None:
        event_stream = getattr(self.session_service.facade, "event_stream", None)
        if event_stream is None or not hasattr(event_stream, "drain"):
            return
        for event in event_stream.drain():
            self._emit_facade_event(context, event)

    @staticmethod
    def _emit_facade_event(context: JobContext, event: RunEvent) -> None:
        kind = "progress" if event.kind in {"进度", "系统"} else "log"
        payload = dict(event.payload or {})
        if event.technical_details:
            payload["technical_details"] = dict(event.technical_details)
        context.emit(kind, event.message, payload=payload)

    def _progress_payload(self, task_id: str) -> dict[str, Any]:
        progress = self.session_service.task_progress(task_id)
        return _model_dump(progress)

    def _debug_path(self, context: JobContext, prefix: str) -> Path:
        path = self.session_service.repo_root / "runs" / "web_pipeline" / context.task_id / f"{prefix}_{context.job_id}.md"
        path.parent.mkdir(parents=True, exist_ok=True)
        return path

    def _resolve_source_path(self, source_path: str) -> Path | None:
        if not source_path.strip():
            return None
        path = Path(source_path).expanduser()
        if not path.is_absolute():
            path = self.session_service.repo_root / path
        return path.resolve()

    @staticmethod
    def _require_api_key() -> str:
        api_key = os.getenv("DEEPSEEK_API_KEY", "").strip()
        if not api_key:
            raise ValueError("未检测到 DEEPSEEK_API_KEY。请先 source ~/.bash_profile 后重启 Web 服务。")
        return api_key

    @classmethod
    def _reviewer_ids_from_payload(cls, payload: Mapping[str, Any]) -> list[str]:
        reviewer_ids = cls._coerce_text_list(payload.get("reviewer_ids"))
        reviewer_id = str(payload.get("reviewer_id") or "").strip()
        if reviewer_id and reviewer_id not in reviewer_ids:
            reviewer_ids.insert(0, reviewer_id)
        if not reviewer_ids:
            raise ValueError("Reviewer action 必须显式指定 reviewer_id。")
        return reviewer_ids

    def _review_target_from_payload(
        self,
        context: JobContext,
        *,
        payload: Mapping[str, Any],
        target_type: str,
    ) -> ReviewTarget:
        artifact_path = self._reviewer_artifact_path(payload)
        document_ids = self._coerce_text_list(payload.get("document_ids"))
        text = str(payload.get("text") or payload.get("target_text") or "").strip()
        target_id = str(
            payload.get("target_id")
            or payload.get("artifact_id")
            or payload.get("draft_id")
            or (Path(artifact_path).name if artifact_path else "")
            or context.job_id
        ).strip()
        if not text and not document_ids and not artifact_path:
            raise ValueError("Reviewer action 缺少可评审正文：需要 text、document_ids 或 artifact_path。")
        return ReviewTarget(
            target_id=target_id,
            target_type=target_type,
            text=text,
            document_ids=document_ids,
            artifact_id=str(payload.get("artifact_id") or ""),
            artifact_path=artifact_path,
            chapter_id=str(payload.get("chapter_id") or ""),
            range_hint={
                "document_title_index": payload.get("document_title_index"),
                "target_raw_chars": payload.get("target_raw_chars"),
            },
            source_refs=self._coerce_source_refs(payload.get("source_refs")),
            metadata={
                "run_id": str(payload.get("run_id") or ""),
                "review_id": str(payload.get("review_id") or ""),
                "draft_id": str(payload.get("draft_id") or ""),
                "artifact_kind": str(payload.get("artifact_kind") or ""),
                "chapter_title": str(payload.get("chapter_title") or ""),
            },
        )

    def _preflight_reviewer_action(self, *, task_id: str, payload: Mapping[str, Any]) -> None:
        target_type = str(payload.get("target_type") or "").strip()
        reviewer_id = str(payload.get("reviewer_id") or "").strip()
        if target_type != "source_chapter" and reviewer_id != "source_chapter_literary_diagnostic":
            return
        max_chars = 65536
        text = str(payload.get("text") or payload.get("target_text") or "")
        if text and len(text) > max_chars:
            raise ValueError("目标原文超过 64KB，请缩小章节范围后再分析。")
        raw_chars = self._optional_int(payload, "target_raw_chars", default=None)
        if raw_chars is not None and raw_chars > max_chars:
            raise ValueError("目标原文超过 64KB，请缩小章节范围后再分析。")
        document_ids = self._coerce_text_list(payload.get("document_ids"))
        if not document_ids:
            return
        db_path = Path(self.session_service.facade.db_path_for_book(task_id))
        if not db_path.exists():
            raise FileNotFoundError("分析原文需要先完成原文导入和章节入库。")
        clean_ids = [int(item) for item in document_ids if str(item).isdigit()]
        if not clean_ids:
            return
        placeholders = ",".join("?" for _ in clean_ids)
        with sqlite3.connect(db_path) as conn:
            row = conn.execute(
                f"""
                SELECT COALESCE(SUM(LENGTH(content)), 0) AS total_chars
                FROM documents
                WHERE book_id = ? AND doc_id IN ({placeholders})
                """,
                (task_id, *clean_ids),
            ).fetchone()
        total_chars = int(row[0] if row else 0)
        if total_chars > max_chars:
            raise ValueError("目标原文超过 64KB，请缩小章节范围后再分析。")

    def _reviewer_artifact_path(self, payload: Mapping[str, Any]) -> str:
        raw_path = str(payload.get("artifact_path") or payload.get("draft_path") or "").strip()
        if not raw_path:
            artifact_id = str(payload.get("artifact_id") or "").strip()
            if artifact_id:
                try:
                    descriptor = decode_artifact_id(artifact_id)
                    raw_path = str(descriptor.get("path") or "")
                except Exception:
                    raw_path = ""
        if not raw_path:
            return ""
        path = Path(raw_path).expanduser()
        if not path.is_absolute():
            path = self.session_service.repo_root / path
        return str(path.resolve())

    @staticmethod
    def _review_budget_from_payload(
        *,
        registry: ReviewerRegistry,
        reviewer_ids: list[str],
        payload: Mapping[str, Any],
    ) -> ReviewBudget:
        raw_budget = payload.get("budget")
        if isinstance(raw_budget, Mapping):
            return ReviewBudget.from_dict(dict(raw_budget))
        if len(reviewer_ids) == 1:
            manifest = registry.get(reviewer_ids[0]).manifest()
            return ReviewBudget.from_dict(manifest.default_budget)
        return ReviewBudget()

    @classmethod
    def _reviewer_model_settings(cls, *, api_key: str, payload: Mapping[str, Any]) -> ModelSettings:
        return ModelSettings(
            model_type=str(payload.get("model_type") or os.getenv("NOVEL_AGENT_WEB_REVIEWER_MODEL_TYPE") or "OpenAIModel"),
            model_name=str(payload.get("model_name") or os.getenv("NOVEL_AGENT_WEB_REVIEWER_MODEL") or "deepseek-chat"),
            provider=str(payload.get("provider") or os.getenv("NOVEL_AGENT_WEB_REVIEWER_PROVIDER") or "openai_compatible"),
            base_url=str(
                payload.get("base_url")
                or os.getenv("NOVEL_AGENT_WEB_REVIEWER_BASE_URL")
                or os.getenv("DEEPSEEK_BASE_URL")
                or "https://api.deepseek.com"
            ),
            api_key=api_key,
            api_key_env="DEEPSEEK_API_KEY",
            temperature=float(payload.get("temperature") or os.getenv("NOVEL_AGENT_WEB_REVIEWER_TEMPERATURE") or 0.2),
            max_output_tokens=int(payload.get("max_output_tokens") or os.getenv("NOVEL_AGENT_WEB_REVIEWER_MAX_OUTPUT_TOKENS") or 8192),
            timeout_seconds=int(payload.get("timeout_seconds") or os.getenv("NOVEL_AGENT_WEB_REVIEWER_TIMEOUT_SECONDS") or 180),
            request_retry_attempts=int(payload.get("request_retry_attempts") or 3),
            retry_without_thinking_on_failure=True,
            dry_run=False,
        )

    @staticmethod
    def _reviewer_report_message(*, label: str, report: Mapping[str, Any]) -> str:
        reviewer_reports = [item for item in report.get("reviewer_reports") or [] if isinstance(item, Mapping)]
        score = report.get("overall_score")
        if score is None and len(reviewer_reports) == 1:
            score = reviewer_reports[0].get("score")
        score_text = f"{score}/100" if score is not None else "未产生评分"
        summary = str(report.get("summary_zh") or "").strip()
        if not summary and reviewer_reports:
            summary = str(reviewer_reports[0].get("summary_zh") or "").strip()
        findings = [item for item in report.get("top_findings") or [] if isinstance(item, Mapping)]
        if not findings and reviewer_reports:
            findings = [item for item in reviewer_reports[0].get("findings") or [] if isinstance(item, Mapping)]
        finding_texts: list[str] = []
        for index, finding in enumerate(findings[:3], start=1):
            message = str(finding.get("message_zh") or "").strip()
            suggestion = str(finding.get("suggestion_zh") or "").strip()
            if message and suggestion:
                finding_texts.append(f"{index}. {message} 建议：{suggestion}")
            elif message:
                finding_texts.append(f"{index}. {message}")
        details = f" 主要意见：{' '.join(finding_texts)}" if finding_texts else ""
        summary_text = f" {summary}" if summary else ""
        return f"{label} 已完成。参考评分：{score_text}。{summary_text}{details}".strip()

    @staticmethod
    def _writer_dry_run_requested(payload: Mapping[str, Any]) -> bool:
        dry_run = _truthy(payload.get("dry_run"))
        if dry_run and not _truthy(os.getenv("NOVEL_AGENT_WEB_ALLOW_WRITER_DRY_RUN")):
            raise RuntimeError(
                "Web Writer 正式入口不允许 dry-run 生成续写规划；"
                "请配置 DEEPSEEK_API_KEY 后重试，或仅在开发环境设置 NOVEL_AGENT_WEB_ALLOW_WRITER_DRY_RUN=1。"
            )
        return dry_run

    @classmethod
    def _writer_intent_payload(cls, payload: Mapping[str, Any]) -> dict[str, Any]:
        raw_intent = payload.get("intent_payload")
        intent: dict[str, Any] = dict(raw_intent) if isinstance(raw_intent, Mapping) else {}

        legacy_intent = payload.get("intent")
        if isinstance(legacy_intent, Mapping):
            direction = str(legacy_intent.get("direction") or legacy_intent.get("goal") or "").strip()
            if direction:
                cls._append_unique(intent.setdefault("desired_actions", []), direction)

        continuation_goal = str(
            payload.get("continuation_goal")
            or payload.get("feedback_text")
            or payload.get("user_feedback")
            or payload.get("supplement_text")
            or ""
        ).strip()
        if continuation_goal:
            cls._append_unique(intent.setdefault("desired_actions", []), continuation_goal)
        for item in cls._coerce_text_list(payload.get("desired_actions")):
            cls._append_unique(intent.setdefault("desired_actions", []), item)
        for item in cls._coerce_text_list(payload.get("major_characters")):
            cls._append_unique(intent.setdefault("major_characters", []), item)
        for item in cls._coerce_text_list(payload.get("avoidances")):
            cls._append_unique(intent.setdefault("avoidances", []), item)

        preferred_outcome = str(payload.get("preferred_outcome") or "").strip()
        if preferred_outcome:
            intent["preferred_outcome"] = preferred_outcome
        notes = cls._join_nonempty(intent.get("notes"), payload.get("notes"), payload.get("constraints"))
        if notes:
            intent["notes"] = notes

        intent["story_scale"] = cls._writer_story_scale_payload(payload, intent.get("story_scale"))
        intent["climax_plan"] = cls._writer_climax_plan_payload(payload.get("climax_plan"), intent.get("climax_plan"))
        if "allow_character_cast" in payload:
            intent["allow_character_cast"] = bool(payload.get("allow_character_cast"))
        return intent

    @classmethod
    def _writer_story_scale_payload(cls, payload: Mapping[str, Any], existing: Any) -> dict[str, Any]:
        source = dict(existing) if isinstance(existing, Mapping) else {}
        story_scale = payload.get("story_scale")
        if isinstance(story_scale, Mapping):
            source.update(dict(story_scale))
        target_chapter_count = cls._optional_int(payload, "target_chapter_count", default=None)
        if target_chapter_count is None:
            target_chapter_count = cls._optional_int(payload, "target_chapters", default=None)
        if target_chapter_count is not None:
            source["target_chapter_count"] = target_chapter_count
        target_total_chars = cls._optional_int(payload, "target_total_chars", default=None)
        if target_total_chars is not None:
            source["target_total_chars"] = target_total_chars
        default_chars = cls._optional_int(payload, "default_chapter_target_chars", default=None)
        if default_chars is None:
            default_chars = cls._optional_int(payload, "default_chapter_chars", default=None)
        if default_chars is not None:
            source["default_chapter_target_chars"] = default_chars
        pacing = str(payload.get("pacing_profile") or payload.get("pacing_preference") or "").strip()
        if not pacing:
            pacing_spec = payload.get("pacing_spec")
            if isinstance(pacing_spec, Mapping):
                pacing = str(pacing_spec.get("preference") or "").strip()
        if pacing:
            source["pacing_profile"] = pacing
        length_notes = str(payload.get("length_distribution_notes") or "").strip()
        if length_notes:
            source["length_distribution_notes"] = length_notes
        return source

    @classmethod
    def _writer_climax_plan_payload(cls, raw_climax: Any, existing: Any) -> dict[str, Any]:
        source = dict(existing) if isinstance(existing, Mapping) else {}
        if isinstance(raw_climax, Mapping):
            source.update(dict(raw_climax))
        setup_requirements = source.pop("setup_requirements", "")
        forbidden_early_resolution = source.pop("forbidden_early_resolution", "")
        target_position = str(source.pop("target_chapter_position", "") or "").strip()
        must_foreshadow = cls._coerce_text_list(source.get("must_foreshadow"))
        must_not_resolve_before = cls._coerce_text_list(source.get("must_not_resolve_before"))
        for item in cls._coerce_text_list(setup_requirements):
            cls._append_unique(must_foreshadow, item)
        for item in cls._coerce_text_list(forbidden_early_resolution):
            cls._append_unique(must_not_resolve_before, item)
        if target_position and not source.get("target_chapter_index"):
            parsed_position = cls._first_positive_int(target_position)
            if parsed_position is not None:
                source["target_chapter_index"] = parsed_position
        source["must_foreshadow"] = must_foreshadow
        source["must_not_resolve_before"] = must_not_resolve_before
        return source

    @staticmethod
    def _coerce_text_list(value: Any) -> list[str]:
        if value is None:
            return []
        if isinstance(value, str):
            chunks = value.replace("，", ",").replace("；", ";").replace("\n", ";")
            return [item.strip() for item in chunks.replace(";", ",").split(",") if item.strip()]
        if isinstance(value, (list, tuple, set)):
            return [str(item).strip() for item in value if str(item).strip()]
        return [str(value).strip()] if str(value).strip() else []

    @staticmethod
    def _coerce_source_refs(value: Any) -> list[dict[str, Any]]:
        if not isinstance(value, list):
            return []
        return [dict(item) for item in value if isinstance(item, Mapping)]

    @staticmethod
    def _append_unique(items: Any, value: str) -> None:
        if not isinstance(items, list):
            return
        normalized = value.strip()
        if normalized and normalized not in items:
            items.append(normalized)

    @staticmethod
    def _join_nonempty(*values: Any) -> str:
        parts = [str(value).strip() for value in values if str(value or "").strip()]
        return "\n".join(parts)

    @staticmethod
    def _first_positive_int(value: str) -> int | None:
        digits = ""
        for char in value:
            if char.isdigit():
                digits += char
            elif digits:
                break
        if not digits:
            return None
        parsed = int(digits)
        return parsed if parsed > 0 else None

    @staticmethod
    def _optional_int(payload: Mapping[str, Any], key: str, *, default: int | None) -> int | None:
        value = payload.get(key)
        if value in {None, ""}:
            return default
        return int(value)

    @staticmethod
    def _env_int(name: str, default: int) -> int:
        raw = os.getenv(name, "").strip()
        if not raw:
            return default
        return int(raw)

    @staticmethod
    def _env_optional_int(name: str) -> int | None:
        raw = os.getenv(name, "").strip()
        if not raw:
            return None
        return int(raw)

    async def _start_writer_review_action(self, *, task_id: str, action: str, payload: dict[str, Any]) -> WebActionResult:
        normalized_payload = self._normalize_writer_review_payload(task_id=task_id, action=action, payload=payload)
        runner = None if os.getenv("NOVEL_AGENT_WEB_JOB_MODE", "").strip().lower() == "fake" else self._run_background_action
        job = await self.job_manager.create_job(
            task_id=task_id,
            job_type="writer_resume",
            payload=normalized_payload,
            runner=runner,
            conflict_job_types=self._EXCLUSIVE_TASK_JOB_TYPES,
        )
        if job.type != "writer_resume":
            message = "已有后台任务正在运行，已复用现有任务；请等它结束后再触发当前动作。"
        else:
            message = self._public_action_message(str(normalized_payload.get("workflow_action") or action))
        self.session_service.append_message(
            task_id,
            role="assistant",
            content=message,
            payload={"job_id": job.job_id, "action": action},
        )
        return WebActionResult(
            action=action,
            task_id=task_id,
            message=message,
            job=job,
            decision_cards=self._writer_decision_cards(task_id=task_id),
            progress=self.session_service.task_progress(task_id),
        )

    def _defer_chapter_acceptance(self, *, task_id: str, payload: dict[str, Any]) -> WebActionResult:
        message = "已保留当前章节草稿决策点，稍后可以继续处理。"
        self.session_service.append_message(task_id, role="assistant", content=message, payload={"reason": payload.get("reason", "")})
        return WebActionResult(
            action="defer_chapter_acceptance",
            task_id=task_id,
            message=message,
            progress=self.session_service.task_progress(task_id),
            decision_cards=self._writer_decision_cards(task_id=task_id),
        )

    def _defer_writer_question_answers(
        self,
        *,
        task_id: str,
        action: str,
        payload: dict[str, Any],
    ) -> WebActionResult:
        writer_state = self.session_service.latest_writer_state(task_id)
        is_draft_research = action == "defer_draft_research_answers"
        message = "已保留当前正文研究问题，稍后可以继续回答。" if is_draft_research else "已保留当前大纲研究问题，稍后可以继续回答。"
        self.session_service.append_message(
            task_id,
            role="assistant",
            content=message,
            payload={
                "channel": "writer_question_deferred",
                "run_id": str(payload.get("run_id") or writer_state.get("run_id") or ""),
                "question_set_id": str(payload.get("question_set_id") or ""),
                "note": str(payload.get("note") or ""),
            },
        )
        return WebActionResult(
            action=action,
            task_id=task_id,
            message=message,
            progress=self.session_service.task_progress(task_id),
        )

    def _go_back(self, *, task_id: str, payload: dict[str, Any]) -> WebActionResult:
        writer_state = self.session_service.latest_writer_state(task_id)
        message = "已记录返回上一层修改的意图。"
        self.session_service.append_message(task_id, role="assistant", content=message, payload={"reason": payload.get("reason", "")})
        return WebActionResult(
            action="go_back",
            task_id=task_id,
            message=message,
            progress=self.session_service.task_progress(task_id),
            technical_details={"run_id": writer_state.get("run_id", ""), "current_stage": writer_state.get("current_stage", "")},
        )

    def _save_artifact(self, *, task_id: str, payload: dict[str, Any]) -> WebActionResult:
        artifact_id = str(payload.get("artifact_id") or "")
        text = str(payload.get("text") or payload.get("content") or "")
        result = self.artifact_view_service.save_text(artifact_id, text)
        status = "ok" if result.get("saved") else "error"
        message = str(result.get("message") or result.get("validation_error") or "")
        self.session_service.append_message(task_id, role="assistant", content=message, payload={"artifact_id": artifact_id})
        return WebActionResult(
            action="save_artifact",
            task_id=task_id,
            status=status,
            message=message,
            payload=result,
        )

    def _identity_merge_review_action(self, *, task_id: str, action: str, payload: dict[str, Any]) -> WebActionResult:
        candidate_id = str(payload.get("candidate_id") or "").strip()
        if not candidate_id:
            raise ValueError("缺少 identity merge candidate_id。")
        snapshot = self.session_service.facade.task_snapshot(book_id=task_id)
        db_path = snapshot.db_path or self.session_service.facade.db_path_for_book(task_id)
        if not db_path.exists():
            raise FileNotFoundError("当前任务索引不存在。")
        db = NovelAgentDB(db_path)
        result_payload: dict[str, Any] = {}
        message = ""
        with db.connect() as conn:
            db.init_schema(conn)
            row = conn.execute(
                "SELECT * FROM character_identity_merge_candidates WHERE book_id = ? AND candidate_id = ?",
                (task_id, candidate_id),
            ).fetchone()
            if row is None:
                raise ValueError("找不到待确认的人物身份候选。")
            candidate = self.session_service._identity_candidate_from_row(row)  # noqa: SLF001
            candidate_label = self.session_service._identity_merge_candidate_label(candidate)  # noqa: SLF001
            survivor_name = str(candidate.get("survivor_canonical_name") or "").strip()
            if str(candidate.get("status") or "") not in {"pending_user_confirmation", "needs_more_evidence"}:
                message = f"人物身份候选「{candidate_label}」已经处理过。"
                return WebActionResult(
                    action=action,
                    task_id=task_id,
                    message=message,
                    payload={"candidate": candidate},
                    progress=self.session_service.task_progress(task_id),
                )
            if action == "confirm_identity_merge":
                merge_result = self._confirm_identity_merge(conn, task_id=task_id, candidate=candidate)
                self._mark_identity_candidate(conn, candidate_id=candidate_id, status="merged", extra={"merge_result": merge_result})
                self._resolve_identity_block(conn, task_id=task_id, candidate_id=candidate_id, resolution="merged")
                survivor_text = f"，保留为「{survivor_name}」" if survivor_name else ""
                message = f"已确认人物身份合并：「{candidate_label}」{survivor_text}。相关人物档案已写回，可以重新开始阅读继续处理。"
                result_payload = {"candidate_id": candidate_id, "merge_result": merge_result}
            elif action == "reject_identity_merge":
                self._mark_identity_candidate(conn, candidate_id=candidate_id, status="rejected", extra={"resolution_reason": "user rejected merge"})
                self._resolve_identity_block(conn, task_id=task_id, candidate_id=candidate_id, resolution="rejected")
                message = f"已保持「{candidate_label}」两个人物档案分离。可以重新开始阅读继续处理。"
                result_payload = {"candidate_id": candidate_id, "status": "rejected"}
            elif action == "request_identity_merge_more_evidence":
                self._mark_identity_candidate(
                    conn,
                    candidate_id=candidate_id,
                    status="needs_more_evidence",
                    gate_level="medium",
                    extra={"resolution_reason": "user requested more evidence"},
                )
                self._resolve_identity_block(conn, task_id=task_id, candidate_id=candidate_id, resolution="needs_more_evidence")
                message = f"已将「{candidate_label}」标记为需要更多证据；后续阅读遇到新的揭示证据时会重新评分。"
                result_payload = {"candidate_id": candidate_id, "status": "needs_more_evidence"}
            else:
                self._mark_identity_candidate(
                    conn,
                    candidate_id=candidate_id,
                    status="routed_to_memory_correction",
                    extra={"resolution_reason": "user routed to memory correction"},
                )
                self._resolve_identity_block(conn, task_id=task_id, candidate_id=candidate_id, resolution="routed_to_memory_correction")
                message = f"已将「{candidate_label}」转为记忆修正候选；不会执行人物档案合并。"
                result_payload = {"candidate_id": candidate_id, "status": "routed_to_memory_correction"}
            conn.commit()
        self.session_service.append_message(
            task_id,
            role="assistant",
            content=message,
            payload={"channel": "identity_merge_review_result", **result_payload},
        )
        return WebActionResult(
            action=action,
            task_id=task_id,
            message=message,
            payload=result_payload,
            progress=self.session_service.task_progress(task_id),
            decision_cards=[],
        )

    def _confirm_identity_merge(self, conn, *, task_id: str, candidate: Mapping[str, Any]) -> dict[str, Any]:
        left_id = candidate.get("left_character_id")
        right_id = candidate.get("right_character_id")
        if left_id is None or right_id is None:
            raise ValueError("候选缺少左右人物 character_id，不能执行合并。")
        survivor_name = str(candidate.get("survivor_canonical_name") or "").strip()
        left_name = str(candidate.get("left_name") or "").strip()
        right_name = str(candidate.get("right_name") or "").strip()
        survivor_id = left_id if survivor_name == left_name or survivor_name not in {left_name, right_name} else right_id
        duplicate_id = right_id if survivor_id == left_id else left_id
        evidence = CharacterIdentityMergeEvidence(
            summary=str(candidate.get("evidence_summary") or candidate.get("reason") or "").strip(),
            source_doc_ids=[int(item) for item in candidate.get("source_doc_ids") or [] if str(item).isdigit()],
            source_title_indexes=[int(item) for item in candidate.get("source_title_indexes") or [] if str(item).isdigit()],
            outline_segment_ids=[str(item) for item in candidate.get("outline_segment_ids") or [] if str(item).strip()],
            confidence=float(candidate.get("confidence") or 1.0),
            decision_source="user_confirmed",
        )
        service = CharacterIdentityMergeService(profiles_repo=CharacterProfilesRepo())
        result = service.merge_confirmed_profiles(
            conn,
            book_id=task_id,
            survivor_character_id=survivor_id,
            duplicate_character_id=duplicate_id,
            evidence=evidence,
            aliases_to_keep=[str(item) for item in candidate.get("aliases_to_keep") or [] if str(item).strip()],
        )
        if not result.merged:
            raise RuntimeError(f"人物身份合并失败：{result.reason}")
        return result.to_dict()

    @staticmethod
    def _mark_identity_candidate(
        conn,
        *,
        candidate_id: str,
        status: str,
        gate_level: str | None = None,
        extra: Mapping[str, Any] | None = None,
    ) -> None:
        row = conn.execute(
            "SELECT decision_json FROM character_identity_merge_candidates WHERE candidate_id = ?",
            (candidate_id,),
        ).fetchone()
        decision: dict[str, Any] = {}
        if row is not None:
            try:
                loaded = json.loads(row["decision_json"] or "{}")
                decision = loaded if isinstance(loaded, dict) else {}
            except json.JSONDecodeError:
                decision = {}
        decision.update(dict(extra or {}))
        if gate_level is None:
            conn.execute(
                """
                UPDATE character_identity_merge_candidates
                SET status = ?, decision_json = ?, resolved_at = ?, updated_at = ?
                WHERE candidate_id = ?
                """,
                (status, json.dumps(decision, ensure_ascii=False), utc_now(), utc_now(), candidate_id),
            )
        else:
            conn.execute(
                """
                UPDATE character_identity_merge_candidates
                SET status = ?, gate_level = ?, decision_json = ?, resolved_at = ?, updated_at = ?
                WHERE candidate_id = ?
                """,
                (status, gate_level, json.dumps(decision, ensure_ascii=False), utc_now(), utc_now(), candidate_id),
            )

    @staticmethod
    def _resolve_identity_block(conn, *, task_id: str, candidate_id: str, resolution: str) -> None:
        row = conn.execute(
            "SELECT status_json FROM reading_progress WHERE book_id = ? AND agent_stage = ?",
            (task_id, DEFAULT_CLOSE_READING_STAGE),
        ).fetchone()
        if row is None:
            return
        try:
            status_payload = json.loads(row["status_json"] or "{}")
        except json.JSONDecodeError:
            status_payload = {}
        if str(status_payload.get("state") or "") != "blocked_identity_merge_review":
            return
        candidate_ids = [str(item) for item in status_payload.get("candidate_ids") or []]
        if candidate_id not in candidate_ids:
            return
        status_payload["state"] = "identity_merge_review_resolved"
        status_payload["resolution"] = resolution
        status_payload["resolved_candidate_id"] = candidate_id
        conn.execute(
            """
            UPDATE reading_progress
            SET status_json = ?, updated_at = ?
            WHERE book_id = ? AND agent_stage = ?
            """,
            (json.dumps(status_payload, ensure_ascii=False), utc_now(), task_id, DEFAULT_CLOSE_READING_STAGE),
        )

    def _normalize_writer_review_payload(self, *, task_id: str, action: str, payload: dict[str, Any]) -> dict[str, Any]:
        writer_state, pending, stage, pending_stage = self._writer_state_parts(task_id)
        run_id = str(payload.get("run_id") or writer_state.get("run_id") or "")
        if not run_id:
            raise ValueError("没有找到可恢复的 Writer run。")
        workflow_action = self._resolve_writer_workflow_action(task_id=task_id, action=action, payload=payload)
        normalized = {**payload, "action": action, "workflow_action": workflow_action, "run_id": run_id}
        if action in {"submit_outline_research_answers", "submit_draft_research_answers"}:
            answer_text = str(payload.get("answer_text") or "").strip()
            user_answers = payload.get("user_answers")
            has_structured_answers = isinstance(user_answers, list) and any(
                isinstance(item, dict) and str(item.get("answer_text") or "").strip()
                for item in user_answers
            )
            if not answer_text and not has_structured_answers:
                raise ValueError("请先在聊天输入框中回答问题，再提交继续研究。")
            normalized["answer_text"] = answer_text
            normalized["question_set_id"] = str(payload.get("question_set_id") or "")
            normalized["source_message_id"] = str(payload.get("source_message_id") or "")
            if isinstance(user_answers, list):
                normalized["user_answers"] = [dict(item) for item in user_answers if isinstance(item, dict)]
        if action in {"approve_writer_artifact", "request_writer_artifact_revision", "defer_writer_artifact_review"}:
            normalized["review_id"] = str(payload.get("review_id") or "")
            normalized["artifact_kind"] = str(payload.get("artifact_kind") or "")
            normalized["artifact_id"] = str(payload.get("artifact_id") or "")
            normalized["artifact_path"] = str(payload.get("artifact_path") or payload.get("path") or pending.get("artifact_path") or "")
            normalized["source_message_id"] = str(payload.get("source_message_id") or "")
            if action == "approve_writer_artifact":
                normalized["supplement_text"] = str(payload.get("supplement_text") or payload.get("user_feedback") or "").strip()
            if action == "request_writer_artifact_revision":
                revision_feedback = str(
                    payload.get("revision_feedback")
                    or payload.get("feedback_text")
                    or payload.get("feedback")
                    or payload.get("user_feedback")
                    or ""
                ).strip()
                if not revision_feedback:
                    raise ValueError("请先输入你希望怎样修改当前产物。")
                normalized["revision_feedback"] = revision_feedback
        if action in {"accept_chapter", "rewrite_chapter", "replan_chapter", "discard_chapter"}:
            feedback_text = str(
                payload.get("feedback_text")
                or payload.get("feedback")
                or payload.get("user_feedback")
                or payload.get("reason")
                or ""
            ).strip()
            if action in {"rewrite_chapter", "replan_chapter"} and not feedback_text:
                    raise ValueError("请先输入你的草稿调整反馈。")
            normalized["feedback_text"] = feedback_text
            normalized["source_message_id"] = str(payload.get("source_message_id") or "")
            normalized["chapter_id"] = str(payload.get("chapter_id") or payload.get("current_chapter_id") or "")
            normalized["draft_id"] = str(payload.get("draft_id") or payload.get("current_draft_id") or "")
            normalized["reason_code"] = str(payload.get("reason_code") or "")
        feedback = str(payload.get("user_feedback") or payload.get("feedback") or "").strip()
        if feedback:
            normalized["user_feedback"] = feedback
        if workflow_action == "request_scoped_artifact_revision":
            if not feedback:
                raise ValueError("请先输入你希望怎样修改当前产物。")
            normalized.setdefault("target_stage", str(payload.get("current_review_state") or pending_stage or stage or ""))
            normalized.setdefault(
                "target_artifact_path",
                str(payload.get("artifact_path") or payload.get("path") or pending.get("artifact_path") or ""),
            )
        return normalized

    def _resolve_writer_workflow_action(self, *, task_id: str, action: str, payload: dict[str, Any]) -> str:
        explicit_action = str(payload.get("workflow_action") or payload.get("writer_action") or "").strip()
        if explicit_action:
            return explicit_action
        if action == "resume":
            return "resume"
        if action == "submit_outline_research_answers":
            return "continue_after_outline_research_input"
        if action == "submit_draft_research_answers":
            return "continue_after_draft_research_input"
        if action == "approve_writer_artifact":
            writer_state, _pending, _stage, pending_stage = self._writer_state_parts(task_id)
            active_stage = pending_stage or str(writer_state.get("current_stage") or "")
            if active_stage == "writeback_review":
                return "approve_writeback"
            return "approve_writer_artifact"
        if action == "request_writer_artifact_revision":
            return "request_writer_artifact_revision"
        if action == "defer_writer_artifact_review":
            return "defer_writer_artifact_review"
        if action == "confirm_current_step":
            writer_state, pending, stage, pending_stage = self._writer_state_parts(task_id)
            actions = self.status_presenter.writer_actions_for_stage(stage=stage, pending_stage=pending_stage)
            if not actions:
                raise ValueError("当前没有可确认的 Writer 审阅步骤。")
            return actions[0].workflow_action
        if action in self._DIRECT_WRITER_WORKFLOW_ACTIONS:
            return action
        return "resume"

    def _append_writer_result_messages(self, *, task_id: str, result_payload: dict[str, Any]) -> None:
        if str(result_payload.get("status") or "") == "needs_user_direction":
            previous_run_id = str(result_payload.get("previous_run_id") or "")
            self.session_service.append_message(
                task_id,
                role="assistant",
                content=str(result_payload.get("message") or "请先补充下一批续写方向，再开始新一轮规划。"),
                payload={"channel": "writer_new_batch_direction_required", "previous_run_id": previous_run_id},
                decision_cards=[
                    DecisionCard(
                        card_id=f"{task_id}:writer-new-batch-direction:{previous_run_id or 'latest'}",
                        title="需要新的续写方向",
                        body="在输入框写下下一批想写的剧情、节奏或重点后，再启动新一轮规划。",
                        actions=[
                            {
                                "action": "start_writer",
                                "label": "提交下一批续写规划",
                                "variant": "primary",
                                "requires_input": True,
                                "input_role": "writer_new_batch_direction",
                                "payload": {
                                    "requested_from": "writer_new_batch",
                                    "previous_run_id": previous_run_id,
                                    "target_chapter_count": 3,
                                    "chapter_count": 3,
                                },
                            }
                        ],
                    )
                ],
            )
            return
        question_set = result_payload.get("question_set")
        if isinstance(question_set, dict):
            self.session_service.append_writer_question_message(task_id, question_set)
            return
        execution_result = result_payload.get("execution_result")
        if isinstance(execution_result, dict) and str(execution_result.get("status") or "") == "draft_research_not_ready":
            self.session_service.sync_writer_question_messages(task_id)
            self.session_service.sync_writer_review_messages(task_id)
            return
        if str(result_payload.get("status") or "") == "draft_research_not_ready":
            self.session_service.sync_writer_question_messages(task_id)
            self.session_service.sync_writer_review_messages(task_id)
            return
        self.session_service.sync_writer_completion_message(task_id)
        if str(result_payload.get("stage") or "") in {"outline_research_user_input", "draft_research_user_input"}:
            self.session_service.sync_writer_question_messages(task_id)
            return
        self.session_service.sync_writer_review_messages(task_id)
        self.session_service.sync_writer_recovery_message(task_id)

    def _attach_current_writer_decision_cards(self, task_id: str, result_payload: dict[str, Any]) -> None:
        cards = self._writer_decision_cards(task_id=task_id)
        if cards:
            result_payload["decision_cards"] = self._cards_payload(cards)

    def _writer_state_parts(self, task_id: str) -> tuple[dict[str, Any], dict[str, Any], str, str]:
        writer_state = self.session_service.latest_writer_state(task_id)
        pending = writer_state.get("pending_checkpoint") if isinstance(writer_state.get("pending_checkpoint"), dict) else {}
        stage = str(writer_state.get("current_stage") or "")
        pending_stage = str((pending or {}).get("stage") or "")
        return writer_state, dict(pending or {}), stage, pending_stage

    @staticmethod
    def _cards_payload(cards: list[DecisionCard]) -> list[dict[str, Any]]:
        return [_model_dump(card) for card in cards]

    @staticmethod
    def _public_action_message(action: str) -> str:
        return {
            "confirm_current_step": "已确认当前审阅点，Writer 会继续到下一步。",
            "approve_writer_artifact": "已通过当前审阅产物，Writer 会带着你的补充继续。",
            "request_writer_artifact_revision": "已提交调整反馈，Writer 会修订当前产物并回到同一审阅点。",
            "defer_writer_artifact_review": "已保留当前审阅点，稍后可以继续处理。",
            "request_scoped_artifact_revision": "已提交修改反馈，Writer 会生成受控修订候选。",
            "apply_scoped_artifact_revision": "已准备应用候选修改。",
            "discard_scoped_artifact_revision": "已准备放弃候选修改。",
            "reject_scoped_artifact_revision": "已准备放弃候选修改。",
            "accept_chapter": "已提交本章正文，Writer 会同步更新续写记忆。",
            "rewrite_chapter": "已提交正文重写反馈，Writer 会基于当前章节梗概重写。",
            "revise_chapter_length": "已提交正文重写反馈，Writer 会基于当前章节梗概重写。",
            "replan_chapter": "已提交章节梗概调整请求，Writer 会回到梗概审阅。",
            "discard_chapter": "已准备作废本次草稿。",
            "submit_outline_research_answers": "已提交补充回答，Writer 会继续大纲研究。",
            "submit_draft_research_answers": "已提交补充回答，Writer 会继续正文研究。",
            "approve_writeback": "已提交本章正文并更新续写记忆。",
        }.get(action, "已准备继续 Writer 流程。")

    @staticmethod
    def _writer_workflow_progress_message(workflow_action: str) -> str:
        return {
            "resume": "正在恢复最近的 Writer 审阅点。",
            "approve_writer_artifact": "正在带着你的补充继续 Writer Agent Loop。",
            "request_writer_artifact_revision": "正在按你的反馈修订当前审阅产物。",
            "defer_writer_artifact_review": "正在保留当前审阅点。",
            "request_scoped_artifact_revision": "正在生成受控修订候选。",
            "apply_scoped_artifact_revision": "正在应用受控修订候选。",
            "discard_scoped_artifact_revision": "正在放弃受控修订候选。",
            "reject_scoped_artifact_revision": "正在放弃受控修订候选。",
            "accept_chapter": "正在提交本章正文并更新续写记忆。",
            "rewrite_chapter": "正在根据反馈重写当前章。",
            "revise_chapter_length": "正在根据反馈重写当前章。",
            "replan_chapter": "正在返回章节梗概调整。",
            "discard_chapter": "正在作废本次草稿。",
            "continue_after_outline_research_input": "正在提交补充回答并继续大纲研究。",
            "continue_after_draft_research_input": "正在提交补充回答并继续正文研究。",
            "approve_writeback": "正在提交本章正文并更新续写记忆。",
        }.get(workflow_action, "正在继续 Writer 流程。")

    def _writer_decision_cards(self, *, task_id: str) -> list[DecisionCard]:
        writer_state, pending, stage, pending_stage = self._writer_state_parts(task_id)
        pending_scoped_revision = writer_state.get("pending_scoped_revision")
        if isinstance(pending_scoped_revision, dict) and str(pending_scoped_revision.get("status") or "") == "candidate":
            request_id = str(pending_scoped_revision.get("request_id") or "")
            return [
                DecisionCard(
                    card_id=f"{task_id}:scoped-revision:{request_id or 'candidate'}",
                    title="候选修改已生成",
                    body="请检查右侧 Writer 产物和技术详情中的 diff，再决定是否应用。",
                    actions=[
                        {
                            "action": "apply_scoped_artifact_revision",
                            "label": "接受候选修改",
                            "variant": "primary",
                            "payload": {"request_id": request_id},
                        },
                        {
                            "action": "discard_scoped_artifact_revision",
                            "label": "拒绝候选修改",
                            "payload": {"request_id": request_id},
                        },
                    ],
                )
            ]

        active_stage = pending_stage or stage
        if active_stage in {"freeze_a", "freeze_b", "freeze_c", "freeze_d"} and not pending:
            actions = self.status_presenter.writer_actions_for_stage(stage=stage, pending_stage=pending_stage)
            if not writer_state or not actions:
                return []
            status = self.status_presenter.present(active_stage)
            return [
                DecisionCard(
                    card_id=f"{task_id}:writer-resume:{str(writer_state.get('run_id') or active_stage)}",
                    title=status.step or "继续 Writer 流程",
                    body=status.next_action or "可以继续生成下一条可审阅内容。",
                    actions=[
                        {
                            "action": "resume",
                            "label": actions[0].label,
                            "variant": "primary",
                            "payload": {"run_id": str(writer_state.get("run_id") or "")},
                        }
                    ],
                )
            ]
        if active_stage == "outline_research_user_input":
            self.session_service.sync_writer_question_messages(task_id)
            return []
        if active_stage in {
            "initialized",
            "agent_running",
            "not_initialized",
            "freeze_a_review",
            "batch_review",
            "chapter_review",
            "wait_chapter_review",
            "wait_chapter_acceptance",
        }:
            self.session_service.sync_writer_review_messages(task_id)
            return []
        actions = self.status_presenter.writer_actions_for_stage(stage=stage, pending_stage=pending_stage)
        if not writer_state or not actions:
            return []

        status = self.status_presenter.present(active_stage)
        if active_stage == "wait_chapter_acceptance":
            return [
                DecisionCard(
                    card_id=f"{task_id}:chapter-acceptance",
                    title=status.step,
                    body=status.message or "当前章节草稿已经生成，请选择处理方式。",
                    actions=[
                        {
                            "action": "rewrite_chapter" if item.workflow_action == "revise_chapter_length" else item.workflow_action,
                            "label": "基于反馈重写本章" if item.workflow_action == "revise_chapter_length" else item.label,
                            "description": item.description,
                            "variant": "primary" if item.workflow_action == "accept_chapter" else "danger" if item.workflow_action == "discard_chapter" else "secondary",
                            "requires_input": item.workflow_action in {"rewrite_chapter", "revise_chapter_length", "replan_chapter"},
                            "payload": {},
                        }
                        for item in actions
                    ]
                    + [{"action": "defer_chapter_acceptance", "label": "稍后继续", "payload": {}}],
                )
            ]

        if active_stage == "writeback_review":
            return [
                DecisionCard(
                    card_id=f"{task_id}:writeback-review",
                    title=status.step,
                    body=status.message or "本章草稿已接受，可以继续提交正文并更新续写记忆。",
                    actions=[
                        {
                            "action": "approve_writeback",
                            "label": "提交本章正文",
                            "variant": "primary",
                            "payload": {"workflow_action": "approve_writeback"},
                        },
                        {"action": "resume", "label": "稍后继续", "payload": {}},
                    ],
                )
            ]

        return [
            DecisionCard(
                card_id=f"{task_id}:writer-review:{active_stage}",
                title=status.step or "Writer 审阅",
                body=status.message or "请审阅当前产物；通过时可以补充字数、风格、节奏、重点段落或禁止项，不通过时请说明要调整哪里。",
                actions=[
                    {
                        "action": "approve_writer_artifact",
                        "label": "通过并继续",
                        "variant": "primary",
                        "requires_input": False,
                        "payload": {
                            "workflow_action": "approve_writer_artifact",
                            "artifact_path": str(pending.get("artifact_path") or ""),
                        },
                    },
                    {
                        "action": "request_writer_artifact_revision",
                        "label": "不通过并调整",
                        "requires_input": True,
                        "payload": {
                            "workflow_action": "request_writer_artifact_revision",
                            "artifact_path": str(pending.get("artifact_path") or ""),
                        },
                    },
                    {
                        "action": "defer_writer_artifact_review",
                        "label": "稍后继续",
                        "payload": {
                            "workflow_action": "defer_writer_artifact_review",
                            "artifact_path": str(pending.get("artifact_path") or ""),
                        },
                    },
                ],
            )
        ]

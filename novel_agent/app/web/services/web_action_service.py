from __future__ import annotations

import asyncio
import os
import uuid
from pathlib import Path
from typing import Any, Mapping

from ...cli.events import RunEvent
from ...cli.status import WriterStatusPresenter
from ..schemas import DecisionCard, WebActionRequest, WebActionResult
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
    }
    _EXCLUSIVE_TASK_JOB_TYPES = {"read", "close_read", "kb", "narrative_scene_index", "writer", "writer_resume"}

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
        "defer_outline_research_answers",
        "approve_writeback",
        "go_back",
        "save_artifact",
        "show_debug_details",
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
            return await self._start_job_action(task_id=task_id, action=action, payload=payload)
        if action == "defer_chapter_acceptance":
            return self._defer_chapter_acceptance(task_id=task_id, payload=payload)
        if action == "defer_outline_research_answers":
            return self._defer_outline_research_answers(task_id=task_id, payload=payload)
        if action in self._WRITER_REVIEW_ACTIONS:
            return await self._start_writer_review_action(task_id=task_id, action=action, payload=payload)
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
                "start_writer": "已收到续写意图，Writer 正在生成下一条可审阅内容；需要你回答、审阅或验收时会继续发到会话里。",
                "resume": "已准备恢复最近一次未完成流程。",
            }[action]
        self.session_service.append_message(task_id, role="assistant", content=message, payload={"job_id": job.job_id})
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
        context.emit("progress", "开始 Writer 分层生成。")
        result = await self._call_facade_with_events(
            context,
            lambda: self.session_service.facade.start_writer(
                book_id=context.task_id,
                run_id=str(payload.get("run_id") or uuid.uuid4().hex),
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
        return result_payload

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
        self._append_writer_result_messages(task_id=context.task_id, result_payload=result_payload)
        context.emit(
            "progress",
            "Writer 状态已更新，新的审阅入口会刷新到会话区。",
            payload={"run_id": run_id, "workflow_action": workflow_action},
        )
        return result_payload

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
            message = self._public_action_message(action)
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
        message = "已保留当前章节验收点，稍后可以继续处理。"
        self.session_service.append_message(task_id, role="assistant", content=message, payload={"reason": payload.get("reason", "")})
        return WebActionResult(
            action="defer_chapter_acceptance",
            task_id=task_id,
            message=message,
            progress=self.session_service.task_progress(task_id),
            decision_cards=self._writer_decision_cards(task_id=task_id),
        )

    def _defer_outline_research_answers(self, *, task_id: str, payload: dict[str, Any]) -> WebActionResult:
        writer_state = self.session_service.latest_writer_state(task_id)
        message = "已保留当前大纲研究问题，稍后可以继续回答。"
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
            action="defer_outline_research_answers",
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

    def _normalize_writer_review_payload(self, *, task_id: str, action: str, payload: dict[str, Any]) -> dict[str, Any]:
        writer_state, pending, stage, pending_stage = self._writer_state_parts(task_id)
        run_id = str(payload.get("run_id") or writer_state.get("run_id") or "")
        if not run_id:
            raise ValueError("没有找到可恢复的 Writer run。")
        workflow_action = self._resolve_writer_workflow_action(task_id=task_id, action=action, payload=payload)
        normalized = {**payload, "action": action, "workflow_action": workflow_action, "run_id": run_id}
        if action == "submit_outline_research_answers":
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
                raise ValueError("请先输入你的草稿验收反馈。")
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
        question_set = result_payload.get("question_set")
        if isinstance(question_set, dict):
            self.session_service.append_writer_question_message(task_id, question_set)
            return
        self.session_service.sync_writer_completion_message(task_id)
        if str(result_payload.get("stage") or "") == "outline_research_user_input":
            self.session_service.sync_writer_question_messages(task_id)
            return
        self.session_service.sync_writer_review_messages(task_id)

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
            "accept_chapter": "已准备接受本章并进入写回确认。",
            "rewrite_chapter": "已提交正文重写反馈，Writer 会基于当前章节梗概重写。",
            "revise_chapter_length": "已提交正文重写反馈，Writer 会基于当前章节梗概重写。",
            "replan_chapter": "已提交章节梗概调整请求，Writer 会回到章节规划。",
            "discard_chapter": "已准备作废本次草稿。",
            "submit_outline_research_answers": "已提交补充回答，Writer 会继续大纲研究。",
            "approve_writeback": "已确认写回续写记忆。",
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
            "accept_chapter": "正在处理章节验收。",
            "rewrite_chapter": "正在根据反馈重写当前章。",
            "revise_chapter_length": "正在根据反馈重写当前章。",
            "replan_chapter": "正在返回章节梗概调整。",
            "discard_chapter": "正在作废本次草稿。",
            "continue_after_outline_research_input": "正在提交补充回答并继续大纲研究。",
            "approve_writeback": "正在写回续写记忆。",
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
                    body=status.message or "当前章节草稿已经生成，请选择验收方式。",
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
                    body=status.message or "请确认是否写回续写记忆。",
                    actions=[
                        {
                            "action": "approve_writeback",
                            "label": "确认写回续写记忆",
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

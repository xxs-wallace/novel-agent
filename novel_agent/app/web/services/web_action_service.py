from __future__ import annotations

import asyncio
import os
import uuid
from pathlib import Path
from typing import Any

from ...cli.status import WriterStatusPresenter
from ...cli.events import RunEvent
from ..schemas import DecisionCard, WebActionRequest, WebActionResult
from .artifact_view_service import ArtifactViewService
from .job_manager import JobContext, JobManager
from .web_session_service import WebSessionService


def _model_dump(model: Any) -> dict[str, Any]:
    if hasattr(model, "model_dump"):
        return model.model_dump()
    return model.dict()


class WebActionService:
    """Maps browser-native actions to shared Novel Agent capabilities."""

    _JOB_ACTION_TYPES = {
        "start_read": "read",
        "start_close_read": "close_read",
        "build_creative_kb": "kb",
        "start_writer": "writer",
        "resume": "writer_resume",
    }

    _WRITER_REVIEW_ACTIONS = {
        "confirm_current_step",
        "request_scoped_artifact_revision",
        "apply_scoped_artifact_revision",
        "discard_scoped_artifact_revision",
        "reject_scoped_artifact_revision",
        "accept_chapter",
        "revise_chapter_length",
        "replan_chapter",
        "discard_chapter",
        "approve_writeback",
    }

    _DIRECT_WRITER_WORKFLOW_ACTIONS = {
        "request_scoped_artifact_revision",
        "apply_scoped_artifact_revision",
        "discard_scoped_artifact_revision",
        "reject_scoped_artifact_revision",
        "accept_chapter",
        "revise_chapter_length",
        "replan_chapter",
        "discard_chapter",
        "approve_writeback",
    }

    _SUPPORTED_ACTIONS = {
        "select_task",
        "create_task",
        "start_read",
        "start_close_read",
        "build_creative_kb",
        "start_writer",
        "resume",
        "confirm_current_step",
        "request_scoped_artifact_revision",
        "apply_scoped_artifact_revision",
        "discard_scoped_artifact_revision",
        "reject_scoped_artifact_revision",
        "accept_chapter",
        "revise_chapter_length",
        "replan_chapter",
        "discard_chapter",
        "defer_chapter_acceptance",
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
        if action in self._JOB_ACTION_TYPES:
            return await self._start_job_action(task_id=task_id, action=action, payload=payload)
        if action == "defer_chapter_acceptance":
            return self._defer_chapter_acceptance(task_id=task_id, payload=payload)
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

    async def _start_job_action(self, *, task_id: str, action: str, payload: dict[str, Any]) -> WebActionResult:
        job_type = self._JOB_ACTION_TYPES[action]
        runner = None if os.getenv("NOVEL_AGENT_WEB_JOB_MODE", "").strip().lower() == "fake" else self._run_background_action
        job = await self.job_manager.create_job(
            task_id=task_id,
            job_type=job_type,
            payload={"action": action, **payload},
            runner=runner,
        )
        message = {
            "start_read": "已准备开始粗读，进度会通过后台事件更新。",
            "start_close_read": "已准备运行精读，进度会通过后台事件更新。",
            "build_creative_kb": "已准备构建 Creative KB，进度会通过后台事件更新。",
            "start_writer": "已准备启动 Writer 分层生成，后续审阅会以决策卡呈现。",
            "resume": "已准备恢复最近一次未完成流程。",
        }[action]
        decision_cards = self._writer_decision_cards(task_id=task_id) if action in {"start_writer", "resume"} else []
        self.session_service.append_message(task_id, role="assistant", content=message, payload={"job_id": job.job_id})
        return WebActionResult(
            action=action,
            task_id=task_id,
            message=message,
            job=job,
            decision_cards=decision_cards,
            progress=self.session_service.task_progress(task_id),
        )

    async def _run_background_action(self, context: JobContext) -> dict[str, Any]:
        if context.job_type == "read":
            return await self._run_read_pipeline(context, read_only=True)
        if context.job_type == "close_read":
            return await self._run_read_pipeline(context, read_only=False)
        if context.job_type == "kb":
            return await self._run_creative_kb(context)
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
            context.emit("progress", "开始完整粗读原文并写入索引。")
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
            context.emit("progress", "粗读本轮已完成，任务状态会刷新。", payload=self._progress_payload(context.task_id))
            return dict(result)

        context.emit("progress", "开始运行精读建模。")
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
        context.emit("progress", "精读本轮已完成，右侧结果浏览器会刷新。", payload=self._progress_payload(context.task_id))
        return dict(result)

    async def _run_creative_kb(self, context: JobContext) -> dict[str, Any]:
        api_key = self._require_api_key()
        snapshot = self.session_service.facade.task_snapshot(book_id=context.task_id)
        db_path = snapshot.db_path or self.session_service.facade.db_path_for_book(context.task_id)
        if not db_path.exists():
            raise FileNotFoundError("还没有任务索引，请先运行粗读和精读。")
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

    async def _run_writer(self, context: JobContext) -> dict[str, Any]:
        payload = context.payload
        api_key = str(payload.get("api_key") or os.getenv("DEEPSEEK_API_KEY") or "").strip() or None
        intent_payload = {
            key: value
            for key, value in payload.items()
            if key not in {"action", "requested_from", "dry_run", "target_chapter_count", "chapter_count", "target_chapters"}
        }
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
                dry_run=bool(payload.get("dry_run", False)) if api_key else True,
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
        cards = self._cards_payload(self._writer_decision_cards(task_id=context.task_id))
        if cards:
            result_payload["decision_cards"] = cards
            context.emit(
                "progress",
                "Writer 审阅决策已准备好。",
                payload={"run_id": result_payload.get("run_id") or str(payload.get("run_id") or ""), "decision_cards": cards},
            )
        return result_payload

    async def _run_writer_resume(self, context: JobContext) -> dict[str, Any]:
        payload = context.payload
        run_id = str(payload.get("run_id") or self.session_service.latest_writer_state(context.task_id).get("run_id") or "")
        if not run_id:
            raise ValueError("没有找到可恢复的 Writer run。")
        api_key = str(payload.get("api_key") or os.getenv("DEEPSEEK_API_KEY") or "").strip() or None
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
                dry_run=bool(payload.get("dry_run", False)) if api_key else True,
                api_key=api_key,
            ),
        )
        result_payload = dict(result)
        cards = self._cards_payload(self._writer_decision_cards(task_id=context.task_id))
        if cards:
            result_payload["decision_cards"] = cards
        context.emit(
            "progress",
            "Writer 状态已更新，新的审阅入口会刷新到会话区。",
            payload={"run_id": run_id, "workflow_action": workflow_action, "decision_cards": cards},
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
    def _optional_int(payload: dict[str, Any], key: str, *, default: int | None) -> int | None:
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
        )
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
        if action == "confirm_current_step":
            writer_state, pending, stage, pending_stage = self._writer_state_parts(task_id)
            actions = self.status_presenter.writer_actions_for_stage(stage=stage, pending_stage=pending_stage)
            if not actions:
                raise ValueError("当前没有可确认的 Writer 审阅步骤。")
            return actions[0].workflow_action
        if action in self._DIRECT_WRITER_WORKFLOW_ACTIONS:
            return action
        return "resume"

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
            "request_scoped_artifact_revision": "已提交修改反馈，Writer 会生成受控修订候选。",
            "apply_scoped_artifact_revision": "已准备应用候选修改。",
            "discard_scoped_artifact_revision": "已准备放弃候选修改。",
            "reject_scoped_artifact_revision": "已准备放弃候选修改。",
            "accept_chapter": "已准备接受本章并进入写回确认。",
            "revise_chapter_length": "已提交字数和节奏调整请求，Writer 会回到长度计划。",
            "replan_chapter": "已提交章节梗概调整请求，Writer 会回到章节规划。",
            "discard_chapter": "已准备作废本次草稿。",
            "approve_writeback": "已确认写回续写记忆。",
        }.get(action, "已准备继续 Writer 流程。")

    @staticmethod
    def _writer_workflow_progress_message(workflow_action: str) -> str:
        return {
            "resume": "正在恢复最近的 Writer 审阅点。",
            "request_scoped_artifact_revision": "正在生成受控修订候选。",
            "apply_scoped_artifact_revision": "正在应用受控修订候选。",
            "discard_scoped_artifact_revision": "正在放弃受控修订候选。",
            "reject_scoped_artifact_revision": "正在放弃受控修订候选。",
            "accept_chapter": "正在处理章节验收。",
            "revise_chapter_length": "正在按字数和节奏要求重写。",
            "replan_chapter": "正在返回章节梗概调整。",
            "discard_chapter": "正在作废本次草稿。",
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
        actions = self.status_presenter.writer_actions_for_stage(stage=stage, pending_stage=pending_stage)
        if not writer_state or not actions:
            return [
                DecisionCard(
                    card_id=f"{task_id}:writer-starting",
                    title="Writer 已启动",
                    body="Writer 到达审阅点后，这里会显示可继续的决策按钮。",
                    actions=[{"action": "resume", "label": "刷新审阅状态", "payload": {}}],
                )
            ]

        status = self.status_presenter.present(active_stage)
        if active_stage == "wait_chapter_acceptance":
            return [
                DecisionCard(
                    card_id=f"{task_id}:chapter-acceptance",
                    title=status.step,
                    body=status.message or "当前章节草稿已经生成，请选择验收方式。",
                    actions=[
                        {
                            "action": item.workflow_action,
                            "label": item.label,
                            "description": item.description,
                            "variant": "primary" if item.workflow_action == "accept_chapter" else "danger" if item.workflow_action == "discard_chapter" else "secondary",
                            "requires_input": item.workflow_action in {"revise_chapter_length", "replan_chapter"},
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

        workflow_action = actions[0].workflow_action
        return [
            DecisionCard(
                card_id=f"{task_id}:writer-review:{active_stage}",
                title=status.step or "Writer 审阅",
                body=status.message or "请审阅右侧 Writer 产物，再选择下一步。",
                actions=[
                    {
                        "action": "confirm_current_step",
                        "label": "接受并继续",
                        "variant": "primary",
                        "payload": {"workflow_action": workflow_action},
                    },
                    {
                        "action": "request_scoped_artifact_revision",
                        "label": "按我的反馈修改",
                        "requires_input": True,
                        "payload": {
                            "target_stage": active_stage,
                            "target_artifact_path": str(pending.get("artifact_path") or ""),
                        },
                    },
                    {"action": "go_back", "label": "返回上一层", "payload": {}},
                    {"action": "resume", "label": "稍后继续", "payload": {}},
                ],
            )
        ]

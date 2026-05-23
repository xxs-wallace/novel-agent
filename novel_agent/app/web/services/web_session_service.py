from __future__ import annotations

import json
import shutil
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping

from ...cli.facade import TuiTaskSnapshot, WorkflowFacade
from ...cli.router import CommandRouter
from ...cli.status import StatusPresenter, StatusView, WriterStatusPresenter
from ..schemas import (
    ConversationMessage,
    DecisionCard,
    TaskProgress,
    TaskSummary,
    WebActionResult,
    WriterArtifactReview,
    WriterDraftReview,
    WriterQuestionSet,
    WriterReviewAction,
)
from .artifact_ids import encode_artifact_id
from .reviewer_action_specs import reviewer_specs_for_stage, writer_reviewer_actions


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _model_dump(model: Any) -> dict[str, Any]:
    if hasattr(model, "model_dump"):
        return model.model_dump()
    return model.dict()


class WebSessionService:
    """Session boundary shared by Web routes and action adapters."""

    def __init__(
        self,
        *,
        repo_root: Path,
        facade: WorkflowFacade | None = None,
        status_presenter: StatusPresenter | None = None,
        command_router: CommandRouter | None = None,
    ) -> None:
        self.repo_root = repo_root.expanduser().resolve()
        self.status_presenter = status_presenter or WriterStatusPresenter()
        self.command_router = command_router or CommandRouter()
        self.facade = facade or WorkflowFacade(repo_root=self.repo_root)
        self.selected_task_id = ""
        self._messages: dict[str, list[ConversationMessage]] = {}

    def list_tasks(self) -> list[TaskSummary]:
        return [self.task_summary(snapshot) for snapshot in self.facade.list_tasks()]

    def create_task(self, *, task_id: str, source_path: str = "") -> TaskSummary:
        snapshot = self.facade.ensure_task(book_id=task_id, source_path=source_path)
        self.selected_task_id = snapshot.book_id
        summary = self.task_summary(snapshot)
        self.append_message(
            snapshot.book_id,
            role="assistant",
            content=f"已创建并选择任务 {snapshot.book_id}。",
            payload={"source_path": snapshot.source_path},
        )
        return summary

    def select_task(self, *, task_id: str) -> TaskSummary:
        snapshot = self.facade.task_snapshot(book_id=task_id)
        self.selected_task_id = snapshot.book_id
        summary = self.task_summary(snapshot)
        self.append_message(
            snapshot.book_id,
            role="assistant",
            content=f"已进入任务 {snapshot.book_id}。",
            payload={"source_path": snapshot.source_path},
        )
        return summary

    def delete_task(self, *, task_id: str, confirm: bool = False, include_runs: bool = False) -> dict[str, Any]:
        result = dict(self.facade.delete_task(book_id=task_id, confirm=confirm, include_runs=include_runs))
        if confirm and self.selected_task_id == result.get("book_id"):
            self.selected_task_id = ""
        return result

    def delete_latest_writer_run(self, *, task_id: str, confirm: bool = False) -> dict[str, Any]:
        writer_state = self.latest_writer_state(task_id)
        run_id = str(writer_state.get("run_id") or "")
        run_dir = Path(str(writer_state.get("run_dir") or ""))
        if not run_id or not run_dir.exists():
            return {
                "task_id": task_id,
                "confirmed": confirm,
                "run_id": "",
                "candidate_paths": [],
                "deleted_paths": [],
                "errors": [],
                "message": "没有找到可删除的 Writer 运行。",
            }
        if not confirm:
            return {
                "task_id": task_id,
                "confirmed": False,
                "run_id": run_id,
                "candidate_paths": [str(run_dir)],
                "deleted_paths": [],
                "errors": [],
                "message": "将删除最近一次 Writer 运行产物，不影响阅读记忆和任务索引。",
            }

        deleted_paths: list[str] = []
        errors: list[str] = []
        try:
            shutil.rmtree(run_dir)
            deleted_paths.append(str(run_dir))
        except OSError as exc:
            errors.append(f"{run_dir}: {exc}")
        self._messages[task_id] = [
            message
            for message in self._messages.get(task_id, [])
            if self._message_run_id(message) != run_id
        ]
        message = "已删除最近一次 Writer 运行，可以重新提交续写意图。"
        self.append_message(
            task_id,
            role="assistant",
            content=message,
            payload={"channel": "writer_run_deleted", "run_id": run_id, "deleted_paths": deleted_paths, "errors": errors},
        )
        return {
            "task_id": task_id,
            "confirmed": True,
            "run_id": run_id,
            "candidate_paths": [str(run_dir)],
            "deleted_paths": deleted_paths,
            "errors": errors,
            "message": message,
        }

    def reset_close_read(self, *, task_id: str) -> WebActionResult:
        result = dict(self.facade.reset_close_read_task(book_id=task_id))
        self.append_message(task_id, role="assistant", content="已清空阅读进度，可以重新开始阅读。", payload=result)
        return WebActionResult(
            action="reset_close_read",
            task_id=task_id,
            message="已清空阅读进度，可以重新开始阅读。",
            payload={"deleted": result.get("deleted", {})},
            progress=self.task_progress(task_id),
        )

    def task_summary(self, snapshot: TuiTaskSnapshot) -> TaskSummary:
        return TaskSummary(
            task_id=snapshot.book_id,
            source_path=snapshot.source_path,
            documents_count=snapshot.documents_count,
            chapters_count=snapshot.chapters_count,
            read_completed=snapshot.segmentation_completed_doc_id,
            close_read_completed=snapshot.close_read_completed_doc_id,
            total_documents=snapshot.max_doc_id,
            close_read_done=snapshot.close_read_done,
            active=snapshot.book_id == self.selected_task_id,
            progress=self.task_progress(snapshot.book_id, snapshot=snapshot),
        )

    def task_progress(self, task_id: str, *, snapshot: TuiTaskSnapshot | None = None) -> TaskProgress:
        snapshot = snapshot or self.facade.task_snapshot(book_id=task_id)
        modeling_status = self.facade.modeling_status(book_id=snapshot.book_id, db_path=snapshot.db_path)
        writer_state = self.latest_writer_state(snapshot.book_id)
        internal_status = self._derive_public_status_source(snapshot=snapshot, writer_state=writer_state)
        status = self.status_presenter.present(internal_status)
        return TaskProgress(
            task_id=snapshot.book_id,
            flow=status.flow,
            step=status.step,
            next_action=status.next_action,
            message=status.message,
            read_progress={
                "completed": snapshot.segmentation_completed_doc_id,
                "total": snapshot.max_doc_id,
            },
            close_read_progress={
                "completed": snapshot.close_read_completed_doc_id,
                "total": snapshot.max_doc_id,
            },
            modeling_ready=modeling_status.ready_map(),
            counts=dict(modeling_status.counts),
            technical_available=bool(writer_state),
        )

    def messages(self, task_id: str) -> list[ConversationMessage]:
        self.sync_writer_question_messages(task_id)
        self.sync_writer_review_messages(task_id)
        self.sync_writer_recovery_message(task_id)
        self.sync_writer_completion_message(task_id)
        return list(self._messages.get(task_id, []))

    def append_user_message(self, task_id: str, content: str, *, payload: Mapping[str, Any] | None = None) -> ConversationMessage:
        payload = dict(payload or {})
        analyzer_question = self._outline_analyzer_question(content=content, payload=payload)
        if analyzer_question:
            message = self.append_message(task_id, role="user", content=content, payload=payload)
            try:
                result = self.facade.analyze_outline(
                    book_id=task_id,
                    question=analyzer_question,
                    conversation_history=self._conversation_history_for_analyzer(task_id),
                )
                self.append_message(
                    task_id,
                    role="assistant",
                    content=str(result.get("answer") or ""),
                    payload={
                        "channel": "outline_analyzer",
                        "status": str(result.get("status") or ""),
                        "sources": result.get("sources") or [],
                    },
                )
            except Exception as exc:
                self.append_message(
                    task_id,
                    role="error",
                    content=f"Analyzer 暂时无法完成分析：{exc}",
                    payload={"channel": "outline_analyzer", "status": "error"},
                )
            return message
        message = self.append_message(task_id, role="user", content=content, payload=payload)
        self.append_message(
            task_id,
            role="assistant",
            content="已收到你的输入。可以继续补充方向，或通过按钮启动对应流程。",
            payload={"input_message_id": message.message_id},
        )
        return message

    def _outline_analyzer_question(self, *, content: str, payload: Mapping[str, Any]) -> str:
        if str(payload.get("channel") or "") == "outline_analyzer":
            return str(payload.get("question") or content).strip()
        text = content.strip()
        for prefix in ("/analyze", "/analyzer", "/outline-analyzer"):
            if text == prefix:
                return ""
            if text.startswith(prefix + " "):
                return text[len(prefix):].strip()
        return ""

    def _conversation_history_for_analyzer(self, task_id: str) -> list[dict[str, str]]:
        history: list[dict[str, str]] = []
        for message in self._messages.get(task_id, [])[-12:]:
            if message.payload.get("channel") != "outline_analyzer":
                continue
            history.append({"role": message.role, "content": message.content})
        return history

    def append_message(
        self,
        task_id: str,
        *,
        role: str,
        content: str,
        payload: Mapping[str, Any] | None = None,
        writer_question_set: WriterQuestionSet | Mapping[str, Any] | None = None,
        writer_artifact_review: WriterArtifactReview | Mapping[str, Any] | None = None,
        writer_draft_review: WriterDraftReview | Mapping[str, Any] | None = None,
        decision_cards: list[DecisionCard | Mapping[str, Any]] | None = None,
    ) -> ConversationMessage:
        question_set_model = self._coerce_writer_question_set(writer_question_set)
        artifact_review_model = self._coerce_writer_artifact_review(writer_artifact_review)
        draft_review_model = self._coerce_writer_draft_review(writer_draft_review)
        decision_card_models = self._coerce_decision_cards(decision_cards)
        message = ConversationMessage(
            message_id=uuid.uuid4().hex,
            task_id=task_id,
            role=role,  # type: ignore[arg-type]
            content=content,
            payload=dict(payload or {}),
            writer_question_set=question_set_model,
            writer_artifact_review=artifact_review_model,
            writer_draft_review=draft_review_model,
            decision_cards=decision_card_models,
            created_at=_utc_now(),
        )
        self._messages.setdefault(task_id, []).append(message)
        return message

    def append_writer_question_message(
        self,
        task_id: str,
        question_set: WriterQuestionSet | Mapping[str, Any],
    ) -> ConversationMessage:
        question_set_model = self._coerce_writer_question_set(question_set)
        if question_set_model is None:
            raise ValueError("问题集 payload 无效。")
        for message in self._messages.get(task_id, []):
            existing = message.writer_question_set
            if existing is not None and existing.question_set_id == question_set_model.question_set_id:
                return message
        return self.append_message(
            task_id,
            role="assistant",
            content="大纲研究需要你补充几个关键问题。",
            payload={
                "channel": "writer_question_set",
                "run_id": question_set_model.run_id,
                "question_set_id": question_set_model.question_set_id,
            },
            writer_question_set=question_set_model,
        )

    def sync_writer_question_messages(self, task_id: str) -> None:
        writer_state = self.latest_writer_state(task_id)
        pending_checkpoint = (
            writer_state.get("pending_checkpoint") if isinstance(writer_state.get("pending_checkpoint"), Mapping) else {}
        )
        active_stage = str(
            (pending_checkpoint or {}).get("stage")
            or writer_state.get("current_stage")
            or ""
        )
        if active_stage != "outline_research_user_input":
            return
        run_id = str(writer_state.get("run_id") or "")
        run_dir = Path(str(writer_state.get("run_dir") or ""))
        if not run_id or not run_dir.exists():
            return
        payload = self._load_json_data(run_dir / "outline_research_question_set.json")
        if not payload:
            return
        self.append_writer_question_message(task_id, payload)

    def append_writer_artifact_review_message(
        self,
        task_id: str,
        review: WriterArtifactReview | Mapping[str, Any],
    ) -> ConversationMessage:
        review_model = self._coerce_writer_artifact_review(review)
        if review_model is None:
            raise ValueError("artifact review payload 无效。")
        for message in self._messages.get(task_id, []):
            existing = message.writer_artifact_review
            if existing is not None and existing.review_id == review_model.review_id:
                message.content = self._writer_review_message_content(review_model.title)
                message.writer_artifact_review = review_model
                return message
        return self.append_message(
            task_id,
            role="assistant",
            content=self._writer_review_message_content(review_model.title),
            payload={
                "channel": "writer_artifact_review",
                "run_id": review_model.run_id,
                "review_id": review_model.review_id,
            },
            writer_artifact_review=review_model,
        )

    def append_writer_draft_review_message(
        self,
        task_id: str,
        review: WriterDraftReview | Mapping[str, Any],
    ) -> ConversationMessage:
        review_model = self._coerce_writer_draft_review(review)
        if review_model is None:
            raise ValueError("draft review payload 无效。")
        for message in self._messages.get(task_id, []):
            existing = message.writer_draft_review
            if existing is not None and existing.review_id == review_model.review_id:
                return message
        return self.append_message(
            task_id,
            role="assistant",
            content="请决定当前章节草稿。",
            payload={
                "channel": "writer_draft_review",
                "run_id": review_model.run_id,
                "review_id": review_model.review_id,
                "chapter_id": review_model.chapter_id,
                "draft_id": review_model.draft_id,
            },
            writer_draft_review=review_model,
        )

    def sync_writer_review_messages(self, task_id: str) -> None:
        writer_state = self.latest_writer_state(task_id)
        if not writer_state:
            return
        pending_checkpoint = (
            writer_state.get("pending_checkpoint") if isinstance(writer_state.get("pending_checkpoint"), Mapping) else {}
        )
        active_stage = str((pending_checkpoint or {}).get("stage") or writer_state.get("current_stage") or "")
        if active_stage == "outline_research_user_input":
            return
        if active_stage == "writeback_review" and self._writer_state_writeback_blocked(writer_state):
            review = self._writer_draft_review_from_state(task_id=task_id, writer_state=writer_state)
            if review is not None:
                self.append_writer_draft_review_message(task_id, review)
            return
        if active_stage == "wait_chapter_acceptance" or self._writer_state_has_orphan_draft(writer_state):
            review = self._writer_draft_review_from_state(task_id=task_id, writer_state=writer_state)
            if review is not None:
                self.append_writer_draft_review_message(task_id, review)
            return
        if active_stage in {
            "freeze_a_review",
            "batch_review",
            "chapter_review",
            "wait_chapter_review",
            "writeback_review",
        }:
            review = self._writer_artifact_review_from_state(
                task_id=task_id,
                writer_state=writer_state,
                active_stage=active_stage,
            )
            if review is not None:
                self.append_writer_artifact_review_message(task_id, review)

    def sync_writer_recovery_message(self, task_id: str) -> None:
        writer_state = self.latest_writer_state(task_id)
        run_id = str(writer_state.get("run_id") or "")
        if not run_id:
            return
        active_stage = self._active_writer_stage(writer_state)
        if self._writer_state_has_orphan_draft(writer_state):
            return
        if self._has_writer_gate_message(task_id, run_id, active_stage=active_stage):
            return
        terminal_stage = str(writer_state.get("terminal_stage") or "")
        if terminal_stage or active_stage in {"completed", "writeback_committed", "halted"}:
            return
        if active_stage in {
            "outline_research_user_input",
            "freeze_a_review",
            "batch_review",
            "chapter_review",
            "wait_chapter_review",
            "wait_chapter_acceptance",
            "writeback_review",
        }:
            return
        for message in self._messages.get(task_id, []):
            if (
                message.payload.get("channel") == "writer_run_recovery"
                and message.payload.get("run_id") == run_id
                and message.payload.get("stage") == active_stage
            ):
                return
        self.append_writer_recovery_message(task_id, writer_state=writer_state)

    def sync_writer_completion_message(self, task_id: str) -> None:
        writer_state = self.latest_writer_state(task_id)
        run_id = str(writer_state.get("run_id") or "")
        if not run_id:
            return
        active_stage = self._active_writer_stage(writer_state)
        terminal_stage = str(writer_state.get("terminal_stage") or "")
        if active_stage not in {"completed", "writeback_committed"} and "completed" not in terminal_stage:
            return
        for message in self._messages.get(task_id, []):
            if (
                message.payload.get("channel") == "writer_completion_next_step"
                and message.payload.get("run_id") == run_id
            ):
                return
        card = DecisionCard(
            card_id=f"{task_id}:writer-completed:{run_id}",
            title="本章已写回",
            body=(
                "这章已经进入续写记忆，后续 Writer 会把它当作已确认上下文。"
                "可以继续发起下一轮续写；若要补充新方向，先写在输入框里再点击继续。"
            ),
            actions=[
                {
                    "action": "start_writer",
                    "label": "继续下一章",
                    "variant": "primary",
                    "payload": {
                        "requested_from": "writer_completion",
                        "previous_run_id": run_id,
                        "continuation_goal": (
                            "继续最新已写回章节之后的剧情；必须以 Writer Memory 中 "
                            "document_title_index 最大的已写回章节作为 continuation anchor，"
                            "不得重写已写回章节或回退到更早剧情。"
                        ),
                        "target_chapter_count": 1,
                        "chapter_count": 1,
                    },
                }
            ],
        )
        self.append_message(
            task_id,
            role="assistant",
            content="本章已经写回续写记忆。你可以继续下一章，或先在输入框补充新的方向。",
            payload={"channel": "writer_completion_next_step", "run_id": run_id, "stage": active_stage},
            decision_cards=[card],
        )

    def append_writer_recovery_message(
        self,
        task_id: str,
        *,
        writer_state: Mapping[str, Any] | None = None,
        force: bool = False,
    ) -> ConversationMessage:
        writer_state = dict(writer_state or self.latest_writer_state(task_id))
        run_id = str(writer_state.get("run_id") or "")
        if not run_id:
            return self.append_message(
                task_id,
                role="assistant",
                content="没有找到可恢复的 Writer 运行。请先开始续写。",
                payload={"channel": "writer_run_recovery"},
            )
        if not force:
            for message in self._messages.get(task_id, []):
                if (
                    message.payload.get("channel") == "writer_run_recovery"
                    and message.payload.get("run_id") == run_id
                    and message.payload.get("stage") == self._active_writer_stage(writer_state)
                ):
                    return message
        content, card = self._writer_recovery_card(task_id=task_id, writer_state=writer_state)
        self.append_message(
            task_id,
            role="assistant",
            content=content,
            payload={"channel": "writer_run_recovery", "run_id": run_id, "stage": self._active_writer_stage(writer_state)},
            decision_cards=[card] if card is not None else [],
        )
        return self._messages[task_id][-1]

    def run_advanced_command(self, *, task_id: str, command: str) -> WebActionResult:
        invocation = self.command_router.parse(command)
        if invocation.handler_name == "list_tasks":
            tasks = [_model_dump(summary) for summary in self.list_tasks()]
            return WebActionResult(action="commands", task_id=task_id, message="当前任务列表已刷新。", payload={"tasks": tasks})
        if invocation.handler_name == "show_status":
            return WebActionResult(action="commands", task_id=task_id, message="当前任务状态已刷新。", progress=self.task_progress(task_id))
        if invocation.handler_name == "select_task":
            if not invocation.args:
                raise ValueError("请输入 task id。")
            summary = self.select_task(task_id=invocation.args[0])
            return WebActionResult(
                action="commands",
                task_id=summary.task_id,
                message=f"已进入任务 {summary.task_id}。",
                payload={"task": _model_dump(summary)},
                progress=summary.progress,
            )
        if invocation.handler_name == "create_task":
            if not invocation.args:
                raise ValueError("请输入新 task id。")
            summary = self.create_task(task_id=invocation.args[0], source_path=" ".join(invocation.args[1:]))
            return WebActionResult(
                action="commands",
                task_id=summary.task_id,
                message=f"已创建任务 {summary.task_id}。",
                payload={"task": _model_dump(summary)},
                progress=summary.progress,
            )
        if invocation.handler_name == "reset_close_read":
            return self.reset_close_read(task_id=task_id)
        if invocation.handler_name == "show_debug_details":
            return WebActionResult(
                action="commands",
                task_id=task_id,
                message="技术详情已准备好。",
                technical_details=self.debug_details(task_id),
            )
        return WebActionResult(
            action="commands",
            task_id=task_id,
            message=f"高级命令 /{invocation.command_id} 已识别；Web 主界面请优先使用结构化 action。",
            technical_details={"handler_name": invocation.handler_name, "args": list(invocation.args)},
        )

    def debug_details(self, task_id: str) -> dict[str, Any]:
        snapshot = self.facade.task_snapshot(book_id=task_id)
        return {
            "task": {
                "task_id": snapshot.book_id,
                "db_path": str(snapshot.db_path or ""),
                "source_path": snapshot.source_path,
                "documents_count": snapshot.documents_count,
                "chapters_count": snapshot.chapters_count,
            },
            "writer_state": self.latest_writer_state(task_id),
        }

    def latest_writer_state(self, task_id: str) -> dict[str, Any]:
        states = self.writer_states(task_id)
        return states[0] if states else {}

    def writer_states(self, task_id: str) -> list[dict[str, Any]]:
        candidates: list[tuple[float, Path, dict[str, Any]]] = []
        writer_root = self.repo_root / "runs" / "writer"
        if not writer_root.exists():
            return []
        cancelled_start_runs = self._cancelled_writer_start_run_ids()
        for state_path in writer_root.glob("*/workflow_state.json"):
            payload = self._load_json_data(state_path)
            if str(payload.get("book_id") or "") != task_id:
                continue
            run_id = str(payload.get("run_id") or state_path.parent.name)
            if run_id in cancelled_start_runs and not self._writer_run_has_reviewable_artifact(state_path.parent, payload):
                continue
            if self._writer_run_looks_like_dry_run_planning(state_path.parent):
                continue
            candidates.append((state_path.stat().st_mtime, state_path.parent, payload))
        if not candidates:
            return []
        states: list[dict[str, Any]] = []
        for _, run_dir, payload in sorted(candidates, key=lambda item: item[0], reverse=True):
            state = dict(payload)
            state.setdefault("run_id", run_dir.name)
            state["run_dir"] = str(run_dir)
            states.append(state)
        return states

    def _cancelled_writer_start_run_ids(self) -> set[str]:
        cancelled: set[str] = set()
        web_jobs_root = self.repo_root / "runs" / "web_jobs"
        if not web_jobs_root.exists():
            return cancelled
        for events_path in web_jobs_root.glob("*/events.jsonl"):
            run_ids: set[str] = set()
            is_writer_start = False
            was_cancelled = False
            try:
                lines = events_path.read_text(encoding="utf-8").splitlines()
            except OSError:
                continue
            for line in lines:
                try:
                    event = json.loads(line)
                except json.JSONDecodeError:
                    continue
                payload = event.get("payload") if isinstance(event.get("payload"), Mapping) else {}
                if payload.get("type") == "writer":
                    is_writer_start = True
                run_id = str(payload.get("run_id") or "")
                if run_id:
                    run_ids.add(run_id)
                if event.get("kind") == "cancelled":
                    was_cancelled = True
            if is_writer_start and was_cancelled:
                cancelled.update(run_ids)
        return cancelled

    def _writer_run_has_reviewable_artifact(self, run_dir: Path, state: Mapping[str, Any]) -> bool:
        pending = state.get("pending_checkpoint") if isinstance(state.get("pending_checkpoint"), Mapping) else {}
        if self._artifact_path_exists(pending):
            return True
        for name in (
            "freeze_a_review_checkpoint.json",
            "batch_review_checkpoint.json",
            "chapter_review_checkpoint.json",
            "generation_review_decision.json",
        ):
            checkpoint = self._load_json_data(run_dir / name)
            if self._artifact_path_exists(checkpoint):
                return True
        return False

    def _writer_state_has_orphan_draft(self, writer_state: Mapping[str, Any]) -> bool:
        run_dir = Path(str(writer_state.get("run_dir") or ""))
        if not run_dir.exists() or not (run_dir / "draft.md").exists():
            return False
        active_stage = self._active_writer_stage(writer_state)
        if active_stage in {"writeback_review", "completed", "writeback_committed", "halted"}:
            return False
        generation_review = self._load_json_data(run_dir / "generation_review_decision.json")
        status = str(generation_review.get("status") or "").strip()
        return not status

    def _writer_state_writeback_blocked(self, writer_state: Mapping[str, Any]) -> bool:
        run_dir = Path(str(writer_state.get("run_dir") or ""))
        if not run_dir.exists():
            return False
        generation_review = self._load_json_data(run_dir / "generation_review_decision.json")
        status = str(generation_review.get("status") or "").strip().lower()
        return status != "accepted"

    @staticmethod
    def _artifact_path_exists(payload: Mapping[str, Any]) -> bool:
        artifact_path = str(payload.get("artifact_path") or "").strip()
        return bool(artifact_path and Path(artifact_path).exists())

    def _writer_run_looks_like_dry_run_planning(self, run_dir: Path) -> bool:
        debug_payloads = [
            self._load_json_data(run_dir / "model_reasoning_debug.json"),
            self._load_json_data(run_dir / "generated_outline.json"),
        ]
        if any(self._contains_raw_model_output(payload) for payload in debug_payloads):
            return False

        book_plan = self._load_json_data(run_dir / "book_continuation_plan.json")
        batch_plan = self._load_json_data(run_dir / "batch_plan.json")
        chapter_package = self._load_json_data(run_dir / "chapter_package.json")
        markers = 0

        debug_text = json.dumps(debug_payloads, ensure_ascii=False)
        if "structured_decision_trace" in debug_text and "Model provider did not return" in debug_text:
            markers += 1
        if str(book_plan.get("continuation_goal") or "") == "承接原作大纲推进后续主线。":
            markers += 1
        if str(batch_plan.get("batch_goal") or "") == "承接原作大纲推进后续主线。":
            must_resolve = batch_plan.get("must_resolve") if isinstance(batch_plan.get("must_resolve"), list) else []
            if must_resolve == ["承接现有主线并推进一个阶段冲突"]:
                markers += 1
        chapters = chapter_package.get("chapters") if isinstance(chapter_package.get("chapters"), list) else []
        if chapters and all("批次推进" in str(chapter.get("title") or "") for chapter in chapters if isinstance(chapter, Mapping)):
            markers += 1
        review_notes = chapter_package.get("review_notes") if isinstance(chapter_package.get("review_notes"), list) else []
        if any("ChapterBrief" in str(note) or "BatchPlan" in str(note) for note in review_notes):
            markers += 1
        return markers >= 2

    def _contains_raw_model_output(self, payload: Any) -> bool:
        if isinstance(payload, Mapping):
            raw = payload.get("raw_visible_output")
            if isinstance(raw, str) and raw.strip():
                return True
            return any(self._contains_raw_model_output(value) for value in payload.values())
        if isinstance(payload, list):
            return any(self._contains_raw_model_output(item) for item in payload)
        return False

    @staticmethod
    def _message_run_id(message: ConversationMessage) -> str:
        run_id = str(message.payload.get("run_id") or "")
        if run_id:
            return run_id
        if message.writer_question_set is not None:
            return message.writer_question_set.run_id
        if message.writer_artifact_review is not None:
            return message.writer_artifact_review.run_id
        if message.writer_draft_review is not None:
            return message.writer_draft_review.run_id
        for card in message.decision_cards:
            for action in card.actions:
                payload = action.get("payload") if isinstance(action, Mapping) else {}
                if isinstance(payload, Mapping) and payload.get("run_id"):
                    return str(payload.get("run_id") or "")
        return ""

    def _has_writer_gate_message(self, task_id: str, run_id: str, *, active_stage: str = "") -> bool:
        for message in self._messages.get(task_id, []):
            if self._message_run_id(message) != run_id:
                continue
            if message.writer_question_set or message.writer_artifact_review or message.writer_draft_review:
                if active_stage and self._message_gate_stage(message) != active_stage:
                    continue
                return True
        return False

    def has_writer_gate_message(self, task_id: str, run_id: str, *, active_stage: str = "") -> bool:
        return self._has_writer_gate_message(task_id, run_id, active_stage=active_stage)

    @staticmethod
    def _active_writer_stage(writer_state: Mapping[str, Any]) -> str:
        pending = writer_state.get("pending_checkpoint") if isinstance(writer_state.get("pending_checkpoint"), Mapping) else {}
        return str((pending or {}).get("stage") or writer_state.get("current_stage") or "")

    @staticmethod
    def _message_gate_stage(message: ConversationMessage) -> str:
        if message.writer_question_set is not None:
            return message.writer_question_set.stage
        if message.writer_artifact_review is not None:
            return str(message.writer_artifact_review.technical_details.get("stage") or "")
        if message.writer_draft_review is not None:
            return "wait_chapter_acceptance"
        return ""

    def _derive_public_status_source(self, *, snapshot: TuiTaskSnapshot, writer_state: Mapping[str, Any]) -> str:
        pending = writer_state.get("pending_checkpoint") if isinstance(writer_state.get("pending_checkpoint"), Mapping) else {}
        pending_stage = str((pending or {}).get("stage") or "")
        if pending_stage:
            return pending_stage
        current_stage = str(writer_state.get("current_stage") or "")
        if current_stage:
            return current_stage
        agent_state = str(writer_state.get("agent_state") or writer_state.get("current_state") or "")
        if agent_state:
            return agent_state
        if snapshot.close_read_done:
            return "memory ready"
        if snapshot.close_read_completed_doc_id:
            return "close_read paused"
        if snapshot.max_doc_id and snapshot.segmentation_completed_doc_id >= snapshot.max_doc_id:
            return "documents indexed"
        if snapshot.segmentation_completed_doc_id:
            return "segmentation paused"
        if snapshot.source_path:
            return "source selected"
        return ""

    def _writer_artifact_review_from_state(
        self,
        *,
        task_id: str,
        writer_state: Mapping[str, Any],
        active_stage: str,
    ) -> WriterArtifactReview | None:
        run_id = str(writer_state.get("run_id") or "")
        run_dir = Path(str(writer_state.get("run_dir") or ""))
        if not run_id:
            return None
        pending = writer_state.get("pending_checkpoint") if isinstance(writer_state.get("pending_checkpoint"), Mapping) else {}
        artifact_path = str((pending or {}).get("artifact_path") or self._default_writer_artifact_path(run_dir, active_stage))
        title, artifact_kind, view_kind = self._writer_artifact_review_meta(active_stage, artifact_path)
        detail_artifact_id = self._writer_artifact_id(
            task_id=task_id,
            kind=view_kind,
            path=artifact_path,
            run_id=run_id,
        )
        review_id = f"artifact-review-{run_id}-{active_stage}"
        summary = self._writer_artifact_summary(Path(artifact_path), title)
        reviewer_actions = writer_reviewer_actions(
            reviewer_specs_for_stage(active_stage),
            task_id=task_id,
            run_id=run_id,
            target_id=detail_artifact_id or f"{run_id}:{active_stage}",
            artifact_id=detail_artifact_id,
            artifact_kind=artifact_kind,
            artifact_path=artifact_path,
            review_id=review_id,
            source="writer_artifact_review_card",
        )
        return WriterArtifactReview(
            run_id=run_id,
            review_id=review_id,
            artifact_kind=artifact_kind,
            artifact_id=detail_artifact_id,
            title=title,
            summary=summary,
            next_prompt=(
                "通过时可以补充字数、风格、节奏、重点描写或禁止项；"
                "不通过时请说明要调整的标题、因果、人物动机、场景顺序、关系推进或伏笔安排。"
            ),
            detail_artifact_id=detail_artifact_id,
            actions=[
                *reviewer_actions,
                WriterReviewAction(
                    action="approve_writer_artifact",
                    label="通过并继续",
                    payload={"run_id": run_id, "review_id": review_id, "artifact_kind": artifact_kind, "artifact_id": detail_artifact_id},
                    description="保留可选补充原文，并交给 Writer 继续后续流程。",
                    variant="primary",
                    input_role="artifact_supplement",
                ),
                WriterReviewAction(
                    action="request_writer_artifact_revision",
                    label="不通过并调整",
                    payload={"run_id": run_id, "review_id": review_id, "artifact_kind": artifact_kind, "artifact_id": detail_artifact_id},
                    description="需要输入调整反馈，Writer 会修订当前产物并回到同一审阅点。",
                    requires_input=True,
                    input_role="artifact_revision_feedback",
                ),
                WriterReviewAction(
                    action="defer_writer_artifact_review",
                    label="稍后继续",
                    payload={"run_id": run_id, "review_id": review_id, "artifact_kind": artifact_kind, "artifact_id": detail_artifact_id},
                    description="保留当前审阅点，不推进流程。",
                ),
            ],
            technical_details={
                "stage": active_stage,
                "artifact_path": artifact_path,
                "run_id": run_id,
            },
        )

    def _writer_draft_review_from_state(
        self,
        *,
        task_id: str,
        writer_state: Mapping[str, Any],
    ) -> WriterDraftReview | None:
        run_id = str(writer_state.get("run_id") or "")
        run_dir = Path(str(writer_state.get("run_dir") or ""))
        if not run_id or not run_dir.exists():
            return None
        generation_review = self._load_json_data(run_dir / "generation_review_decision.json")
        chapter_id = str(generation_review.get("chapter_id") or writer_state.get("current_chapter_id") or "")
        draft_id = str(generation_review.get("draft_id") or writer_state.get("current_draft_id") or "draft-001")
        draft_path = run_dir / "draft.md"
        draft_text = self._load_text(draft_path)
        preview = draft_text[:900].strip()
        continuity = self._continuity_summary(run_dir)
        target_word_count = self._target_word_count(run_dir)
        detail_artifact_id = self._writer_artifact_id(
            task_id=task_id,
            kind="draft",
            path=str(draft_path),
            run_id=run_id,
        )
        review_id = str(generation_review.get("decision_id") or f"draft-review-{run_id}-{chapter_id or 'chapter'}-{draft_id}")
        common_payload = {"run_id": run_id, "chapter_id": chapter_id, "draft_id": draft_id, "review_id": review_id}
        reviewer_actions = writer_reviewer_actions(
            reviewer_specs_for_stage("wait_chapter_acceptance"),
            task_id=task_id,
            run_id=run_id,
            target_id=detail_artifact_id or draft_id or f"{run_id}:{chapter_id}:draft",
            artifact_id=detail_artifact_id,
            artifact_kind="draft",
            artifact_path=str(draft_path),
            review_id=review_id,
            chapter_id=chapter_id,
            draft_id=draft_id,
            source="writer_draft_review_card",
        )
        return WriterDraftReview(
            run_id=run_id,
            review_id=review_id,
            chapter_id=chapter_id,
            draft_id=draft_id,
            preview=preview,
            word_count=len(draft_text),
            target_word_count=target_word_count,
            continuity_summary=continuity,
            detail_artifact_id=detail_artifact_id,
            actions=[
                *reviewer_actions,
                WriterReviewAction(
                    action="accept_chapter",
                    label="接受本章",
                    payload=dict(common_payload),
                    description="唯一会进入写回摘要审阅或正式写回候选的草稿分支。",
                    variant="primary",
                ),
                WriterReviewAction(
                    action="rewrite_chapter",
                    label="基于反馈重写",
                    payload=dict(common_payload),
                    description="基于当前已通过的章节梗概和你的反馈重写，不写回记忆。",
                    requires_input=True,
                    input_role="draft_rewrite_feedback",
                ),
                WriterReviewAction(
                    action="replan_chapter",
                    label="修改章节梗概后重写",
                    payload=dict(common_payload),
                    description="退回章节梗概审阅点，不写回记忆。",
                    requires_input=True,
                    input_role="draft_replan_feedback",
                ),
                WriterReviewAction(
                    action="discard_chapter",
                    label="作废本次草稿",
                    payload=dict(common_payload),
                    description="只保留运行产物，不进入正式记忆。",
                    variant="danger",
                    input_role="draft_discard_reason",
                ),
                WriterReviewAction(
                    action="defer_chapter_acceptance",
                    label="稍后再决定",
                    payload=dict(common_payload),
                    description="保留当前待决策状态，不写正式 decision。",
                ),
            ],
            technical_details={
                "stage": "wait_chapter_acceptance",
                "draft_path": str(draft_path),
                "run_id": run_id,
            },
        )

    @staticmethod
    def _writer_artifact_review_meta(stage: str, artifact_path: str) -> tuple[str, str, str]:
        if stage == "freeze_a_review":
            return "全书续写规划", "book_continuation_plan", "book_plan"
        if stage == "batch_review":
            return "本批剧情大纲", "batch_plan", "batch_plan"
        if stage in {"chapter_review", "wait_chapter_review"}:
            return "章节标题与梗概", "chapter_package", "chapter_package"
        if stage == "writeback_review":
            return "写回摘要", "writeback_summary", "writeback"
        path_name = Path(artifact_path).name
        return "Writer 审阅产物", path_name.removesuffix(".json") or "writer_artifact", "writer_artifact"

    @staticmethod
    def _default_writer_artifact_path(run_dir: Path, stage: str) -> str:
        name_by_stage = {
            "freeze_a_review": "book_continuation_plan.json",
            "batch_review": "batch_plan.json",
            "chapter_review": "chapter_package.json",
            "wait_chapter_review": "chapter_package.json",
            "writeback_review": "memory_writeback.json",
        }
        name = name_by_stage.get(stage, "")
        return str(run_dir / name) if name and run_dir else ""

    @staticmethod
    def _writer_artifact_id(*, task_id: str, kind: str, path: str, run_id: str) -> str:
        return encode_artifact_id(
            {
                "task_id": task_id,
                "surface": "writer",
                "kind": kind,
                "path": path,
                "run_id": run_id,
            }
        )

    def _writer_artifact_summary(self, path: Path, fallback_title: str) -> str:
        if not path.exists():
            return f"{fallback_title}还没有可预览内容，请查看右侧 Writer 结果或稍后刷新。"
        if path.suffix.lower() != ".json":
            text = self._load_text(path)
            return text[:500].strip()
        payload = self._load_json_data(path)
        if path.name == "chapter_package.json":
            summary = self._writer_chapter_package_summary(payload)
            if summary:
                return summary
        for key in (
            "continuation_goal",
            "stage_goal",
            "goal",
            "batch_goal",
            "summary",
            "chapter_goal",
            "review_notes",
        ):
            value = payload.get(key)
            if value:
                return self._public_writer_text(self._compact_text(value))
        chapters = payload.get("chapters")
        if isinstance(chapters, list) and chapters:
            return self._public_writer_text(self._compact_text(chapters[0]))
        return f"{fallback_title}已生成，请在右侧查看详情。"

    @staticmethod
    def _writer_review_message_content(title: str) -> str:
        if title == "章节标题与梗概":
            return "我整理好了章节标题与梗概，请看下面这版是否按这个方向写。"
        if title == "本批剧情大纲":
            return "我整理好了本批剧情大纲，请看下面这版是否合适。"
        if title == "全书续写规划":
            return "我整理好了全书续写规划，请看下面这版是否符合你的续写目标。"
        return f"请审阅{title}。"

    def _writer_chapter_package_summary(self, payload: Mapping[str, Any]) -> str:
        chapters = payload.get("chapters") if isinstance(payload.get("chapters"), list) else []
        lines: list[str] = []
        for index, item in enumerate(chapters[:6], start=1):
            if not isinstance(item, Mapping):
                continue
            title = self._compact_text(item.get("title") or item.get("chapter_title") or item.get("chapter_id") or f"第 {index} 章")
            goal = self._compact_text(item.get("goal") or item.get("chapter_goal") or item.get("plot_function") or "")
            role = self._compact_text(item.get("chapter_role") or "")
            lines.append(f"{index}. {title}")
            if role:
                lines.append(f"   章节作用：{role}")
            if goal:
                lines.append(f"   章节梗概：{goal}")
            beats = self._writer_chapter_beats(item)
            if beats:
                lines.append(f"   关键节拍：{'；'.join(beats[:4])}")
            ending = self._compact_text(item.get("ending_hook") or item.get("exit_hook") or "")
            if ending:
                lines.append(f"   结尾钩子：{ending}")
        review_notes = payload.get("review_notes") if isinstance(payload.get("review_notes"), list) else []
        public_notes = [
            self._public_writer_text(self._compact_text(note))
            for note in review_notes
            if self._compact_text(note)
        ]
        if public_notes:
            lines.append("")
            lines.append("审阅重点：")
            lines.extend(f"- {note}" for note in public_notes[:5])
        return "\n".join(lines).strip()

    def _writer_chapter_beats(self, item: Mapping[str, Any]) -> list[str]:
        raw_beats = item.get("scene_beats")
        if not raw_beats and isinstance(item.get("structure_hint"), Mapping):
            raw_beats = item["structure_hint"].get("beats")
        if not isinstance(raw_beats, list):
            return []
        beats: list[str] = []
        for beat in raw_beats:
            text = self._compact_text(beat)
            if text:
                beats.append(text)
        return beats

    def _continuity_summary(self, run_dir: Path) -> str:
        payload = self._load_json_data(run_dir / "continuity_report.json")
        issues = [item for item in payload.get("issues", []) if isinstance(item, Mapping)]
        if issues:
            public_issues = [
                self._compact_text(item.get("message") or item.get("type") or "")
                for item in issues
                if self._compact_text(item.get("message") or item.get("type") or "")
            ]
            if public_issues:
                prefix = "连续性风险提示：" if payload.get("blocked") else "连续性检查提示："
                return f"{prefix}{'；'.join(public_issues[:3])}"
        for key in ("summary", "overall_summary", "status", "review_summary"):
            value = payload.get(key)
            if value:
                return self._compact_text(value)
        return "连续性检查结果可在右侧详情或技术详情中查看。"

    def _target_word_count(self, run_dir: Path) -> int | None:
        for name in ("chapter_writing_guidance.json", "chapter_execution_input.json", "chapter_length_budget.json"):
            payload = self._load_json_data(run_dir / name)
            budget = payload.get("length_budget") if isinstance(payload.get("length_budget"), Mapping) else payload
            if not isinstance(budget, Mapping):
                continue
            for key in ("target_chars", "target_word_count", "target_words", "target"):
                value = budget.get(key)
                if value in (None, ""):
                    continue
                try:
                    return int(value)
                except (TypeError, ValueError):
                    continue
        return None

    def _writer_recovery_card(
        self,
        *,
        task_id: str,
        writer_state: Mapping[str, Any],
    ) -> tuple[str, DecisionCard | None]:
        run_id = str(writer_state.get("run_id") or "")
        run_dir = Path(str(writer_state.get("run_dir") or ""))
        missing_steps = self._writer_missing_modeling_steps(task_id=task_id, run_dir=run_dir)
        if missing_steps:
            missing_text = "、".join(self._public_missing_modeling_label(step) for step in missing_steps)
            actions = self._writer_modeling_recovery_actions(missing_steps)
            card = DecisionCard(
                card_id=f"{task_id}:writer-modeling-recovery:{run_id}",
                title="续写前还需要建模",
                body=f"需要先补齐：{missing_text}。完成后请重新点击“开始续写”。",
                actions=actions,
            )
            return (
                f"上一次 Writer 运行停在建模检查：{missing_text}。先补齐这些材料后，再重新开始续写。",
                card,
            )
        resumable_action = self._resumable_writer_action(writer_state)
        if resumable_action is not None:
            status = self.status_presenter.present(str(writer_state.get("current_stage") or ""))
            card = DecisionCard(
                card_id=f"{task_id}:writer-resume:{run_id}",
                title=status.step or "继续 Writer 流程",
                body=status.next_action or "可以继续生成下一条可审阅内容。",
                actions=[
                    {
                        "action": "resume",
                        "label": resumable_action.label,
                        "variant": "primary",
                        "payload": {"run_id": run_id},
                    }
                ],
            )
            return (
                f"{status.step or '上一次 Writer 运行可以继续'}。点击“{resumable_action.label}”继续。",
                card,
            )
        return (
            "上一次 Writer 运行还没有保存到可审阅节点，当前没有可恢复的问题或审阅卡。"
            "请重新点击“开始续写”提交方向；如需清理旧 run，可从任务菜单删除最近续写。",
            DecisionCard(
                card_id=f"{task_id}:writer-empty-recovery:{run_id}",
                title="没有可恢复审阅点",
                body="当前 run 没有问题集、审阅产物或草稿决策点。请重新开始续写，或删除最近续写后重试。",
                actions=[],
            ),
        )

    def _resumable_writer_action(self, writer_state: Mapping[str, Any]) -> Any | None:
        pending = writer_state.get("pending_checkpoint") if isinstance(writer_state.get("pending_checkpoint"), Mapping) else {}
        if pending:
            return None
        stage = str(writer_state.get("current_stage") or "")
        if stage not in {"freeze_a", "freeze_b", "freeze_c", "freeze_d"}:
            return None
        actions = self.status_presenter.writer_actions_for_stage(stage=stage)
        return actions[0] if actions else None

    def _writer_missing_modeling_steps(self, *, task_id: str, run_dir: Path) -> list[str]:
        stale_steps = self._writer_missing_modeling_steps_from_run(run_dir)
        if not stale_steps:
            return []
        current_status = self._current_modeling_status(task_id)
        if current_status is None:
            return stale_steps
        return [
            step
            for step in stale_steps
            if not self._modeling_step_ready(current_status=current_status, step=step)
        ]

    def _writer_missing_modeling_steps_from_run(self, run_dir: Path) -> list[str]:
        payload = self._load_json_data(run_dir / "modeling_status.json")
        raw_steps = payload.get("missing_modeling_steps")
        if isinstance(raw_steps, list):
            steps = [str(item).strip() for item in raw_steps if str(item).strip()]
            if steps:
                return steps
        checks = payload.get("checks")
        if not isinstance(checks, list):
            return []
        mapped: list[str] = []
        for item in checks:
            if not isinstance(item, Mapping) or item.get("ready") is True:
                continue
            name = str(item.get("name") or "").strip()
            step = {
                "documents_index": "documents.not_indexed",
                "character_profiles": "memory.character_profiles",
                "story_outline": "memory.story_outline",
                "world_summary": "memory.world_summary",
                "creative_kb": "creative_kb.fragment_cards",
                "source_arc_map": "memory.source_arc_map",
            }.get(name, "")
            if step:
                mapped.append(step)
        return list(dict.fromkeys(mapped))

    def _current_modeling_status(self, task_id: str) -> Any | None:
        try:
            snapshot = self.facade.task_snapshot(book_id=task_id)
            return self.facade.modeling_status(book_id=snapshot.book_id, db_path=snapshot.db_path)
        except Exception:
            return None

    @staticmethod
    def _modeling_step_ready(*, current_status: Any, step: str) -> bool:
        ready_by_step = {
            "documents.not_indexed": bool(getattr(current_status, "documents_ready", False)),
            "memory.character_profiles": bool(getattr(current_status, "character_profiles_ready", False)),
            "memory.story_outline": bool(getattr(current_status, "story_outline_ready", False)),
            "memory.world_summary": bool(getattr(current_status, "world_summary_ready", False)),
            "memory.source_arc_map": bool(getattr(current_status, "source_arc_map_ready", False)),
            "creative_kb.fragment_cards": bool(getattr(current_status, "creative_kb_ready", False)),
        }
        return ready_by_step.get(step, False)

    @staticmethod
    def _public_missing_modeling_label(step: str) -> str:
        return {
            "documents.not_indexed": "原文导入",
            "memory.character_profiles": "人物档案",
            "memory.story_outline": "故事大纲",
            "memory.world_summary": "世界观概要",
            "memory.source_arc_map": "源作品篇章地图",
            "creative_kb.fragment_cards": "Creative KB 片段卡",
        }.get(step, step)

    @staticmethod
    def _writer_modeling_recovery_actions(missing_steps: list[str]) -> list[dict[str, Any]]:
        actions: list[dict[str, Any]] = []
        missing = set(missing_steps)
        if "documents.not_indexed" in missing:
            actions.append(
                {
                    "action": "start_read",
                    "label": "导入原文",
                    "variant": "primary",
                    "payload": {"requested_from": "writer_recovery"},
                }
            )
        if any(step.startswith("memory.") for step in missing):
            actions.append(
                {
                    "action": "start_close_read",
                    "label": "继续阅读建模",
                    "variant": "primary" if not actions else "secondary",
                    "payload": {"requested_from": "writer_recovery"},
                }
            )
        if any(step.startswith("creative_kb.") for step in missing):
            actions.append(
                {
                    "action": "build_creative_kb",
                    "label": "构建 Creative KB",
                    "variant": "primary" if not actions else "secondary",
                    "payload": {"requested_from": "writer_recovery"},
                }
            )
        return actions

    @staticmethod
    def _load_text(path: Path) -> str:
        try:
            return path.read_text(encoding="utf-8", errors="replace")
        except OSError:
            return ""

    @staticmethod
    def _compact_text(value: object) -> str:
        if isinstance(value, (dict, list)):
            if isinstance(value, list):
                return "；".join(WebSessionService._compact_text(item) for item in value if WebSessionService._compact_text(item))
            return "；".join(
                f"{key}：{WebSessionService._compact_text(item)}"
                for key, item in value.items()
                if WebSessionService._compact_text(item)
            )
        return " ".join(str(value or "").split())

    @staticmethod
    def _public_writer_text(value: str) -> str:
        replacements = {
            "ChapterBrief": "章节梗概",
            "BatchPlan": "本批剧情大纲",
            "BookContinuationPlan": "全书续写规划",
            "must_resolve": "必须推进的剧情",
            "must_not_consume": "禁止提前消耗的内容",
            "stage_goal": "阶段目标",
        }
        text = value
        for raw, public in replacements.items():
            text = text.replace(raw, public)
        return text

    @staticmethod
    def _load_json_data(path: Path) -> dict[str, Any]:
        try:
            raw = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return {}
        payload = raw.get("data") if isinstance(raw, dict) else raw
        return dict(payload) if isinstance(payload, dict) else {}

    @staticmethod
    def _coerce_writer_question_set(
        question_set: WriterQuestionSet | Mapping[str, Any] | None,
    ) -> WriterQuestionSet | None:
        if question_set is None:
            return None
        if isinstance(question_set, WriterQuestionSet):
            return question_set
        try:
            return WriterQuestionSet(**dict(question_set))
        except (TypeError, ValueError):
            return None

    @staticmethod
    def _coerce_writer_artifact_review(
        review: WriterArtifactReview | Mapping[str, Any] | None,
    ) -> WriterArtifactReview | None:
        if review is None:
            return None
        if isinstance(review, WriterArtifactReview):
            return review
        try:
            return WriterArtifactReview(**dict(review))
        except (TypeError, ValueError):
            return None

    @staticmethod
    def _coerce_writer_draft_review(
        review: WriterDraftReview | Mapping[str, Any] | None,
    ) -> WriterDraftReview | None:
        if review is None:
            return None
        if isinstance(review, WriterDraftReview):
            return review
        try:
            return WriterDraftReview(**dict(review))
        except (TypeError, ValueError):
            return None

    @staticmethod
    def _coerce_decision_cards(cards: list[DecisionCard | Mapping[str, Any]] | None) -> list[DecisionCard]:
        models: list[DecisionCard] = []
        for card in cards or []:
            if isinstance(card, DecisionCard):
                models.append(card)
                continue
            try:
                models.append(DecisionCard(**dict(card)))
            except (TypeError, ValueError):
                continue
        return models

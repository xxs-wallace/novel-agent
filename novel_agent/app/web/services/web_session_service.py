from __future__ import annotations

import json
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping

from ...cli.facade import TuiTaskSnapshot, WorkflowFacade
from ...cli.router import CommandRouter
from ...cli.status import StatusPresenter, StatusView, WriterStatusPresenter
from ..schemas import ConversationMessage, TaskProgress, TaskSummary, WebActionResult


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

    def reset_close_read(self, *, task_id: str) -> WebActionResult:
        result = dict(self.facade.reset_close_read_task(book_id=task_id))
        self.append_message(task_id, role="assistant", content="已清空精读进度，可以重新运行精读。", payload=result)
        return WebActionResult(
            action="reset_close_read",
            task_id=task_id,
            message="已清空精读进度，可以重新运行精读。",
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
        return list(self._messages.get(task_id, []))

    def append_user_message(self, task_id: str, content: str, *, payload: Mapping[str, Any] | None = None) -> ConversationMessage:
        message = self.append_message(task_id, role="user", content=content, payload=payload)
        self.append_message(
            task_id,
            role="assistant",
            content="已收到你的输入。可以继续补充方向，或通过按钮启动对应流程。",
            payload={"input_message_id": message.message_id},
        )
        return message

    def append_message(
        self,
        task_id: str,
        *,
        role: str,
        content: str,
        payload: Mapping[str, Any] | None = None,
    ) -> ConversationMessage:
        message = ConversationMessage(
            message_id=uuid.uuid4().hex,
            task_id=task_id,
            role=role,  # type: ignore[arg-type]
            content=content,
            payload=dict(payload or {}),
            created_at=_utc_now(),
        )
        self._messages.setdefault(task_id, []).append(message)
        return message

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
        candidates: list[tuple[float, Path, dict[str, Any]]] = []
        writer_root = self.repo_root / "runs" / "writer"
        if not writer_root.exists():
            return {}
        for state_path in writer_root.glob("*/workflow_state.json"):
            payload = self._load_json_data(state_path)
            if str(payload.get("book_id") or "") != task_id:
                continue
            candidates.append((state_path.stat().st_mtime, state_path.parent, payload))
        if not candidates:
            return {}
        _, run_dir, payload = sorted(candidates, key=lambda item: item[0])[-1]
        state = dict(payload)
        state.setdefault("run_id", run_dir.name)
        state["run_dir"] = str(run_dir)
        return state

    def _derive_public_status_source(self, *, snapshot: TuiTaskSnapshot, writer_state: Mapping[str, Any]) -> str:
        pending = writer_state.get("pending_checkpoint") if isinstance(writer_state.get("pending_checkpoint"), Mapping) else {}
        pending_stage = str((pending or {}).get("stage") or "")
        if pending_stage:
            return pending_stage
        current_stage = str(writer_state.get("current_stage") or "")
        if current_stage:
            return current_stage
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

    @staticmethod
    def _load_json_data(path: Path) -> dict[str, Any]:
        try:
            raw = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return {}
        payload = raw.get("data") if isinstance(raw, dict) else raw
        return dict(payload) if isinstance(payload, dict) else {}

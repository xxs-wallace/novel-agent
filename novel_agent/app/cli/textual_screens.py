from __future__ import annotations

import os
import threading
from pathlib import Path
from typing import Any

from textual.app import ComposeResult
from textual.containers import Horizontal, Vertical
from textual.screen import Screen
from textual.widgets import Footer, Header, Label, ListItem, ListView, Static

from ..constants import DEFAULT_CLOSE_READ_DOC_BUDGET
from .app import TuiApp
from .decisions import DecisionPanel
from .router import CommandContext, CommandInvocation
from .textual_widgets import (
    ArtifactEditorPane,
    ArtifactReferenceCandidate,
    ArtifactReviewPane,
    DecisionPanelWidget,
    MessageFlow,
    PromptInput,
    ScopedRevisionFeedbackWidget,
    StatusSidebar,
    ToastLayer,
)


HOME_ACTIONS: tuple[tuple[str, str, str], ...] = (
    ("1", "选择或创建任务", "/tasks"),
    ("2", "继续上次会话", "/resume"),
    ("3", "导入/粗读原文", "/read"),
    ("4", "运行精读建模", "/close-read"),
    ("5", "查看建模状态", "/status"),
    ("6", "查看精读产物", "/query-close-read summary"),
    ("7", "构建 Creative KB", "/kb"),
    ("8", "运行最小续写回归", "/benchmark"),
    ("9", "开始或恢复 Writer", "/writer"),
)


class HomeScreen(Screen[None]):
    """Prompt-first landing screen for the formal Textual CLI."""

    DEFAULT_CSS = """
    HomeScreen {
        layout: vertical;
    }

    #home-main {
        height: 1fr;
        padding: 1 2;
    }

    #home-title {
        text-style: bold;
        margin-bottom: 1;
    }

    #home-actions {
        height: auto;
        margin-top: 1;
        border-left: solid $secondary;
        padding-left: 1;
    }

    #home-actions-text {
        margin-top: 1;
    }
    """

    def compose(self) -> ComposeResult:
        yield Header(show_clock=True)
        with Vertical(id="home-main"):
            yield Static("小说续写工作台", id="home-title")
            yield PromptInput(router=self.app.command_router, context=CommandContext(), id="home-prompt")  # type: ignore[attr-defined]
            yield Static(self._actions_text(), id="home-actions-text")
            yield ListView(
                *[ListItem(Label(f"{key}  {label}")) for key, label, _command in HOME_ACTIONS],
                id="home-actions",
            )
        yield Footer()

    def on_mount(self) -> None:
        self.query_one("#home-prompt", PromptInput).focus()

    def on_key(self, event) -> None:  # type: ignore[no-untyped-def]
        if event.character:
            for key, _label, command in HOME_ACTIONS:
                if event.character == key:
                    event.stop()
                    self._run_home_command(command)
                    return

    def on_list_view_selected(self, event: ListView.Selected) -> None:
        index = event.list_view.index or 0
        if index < len(HOME_ACTIONS):
            self._run_home_command(HOME_ACTIONS[index][2])

    def on_prompt_input_submitted(self, event: PromptInput.Submitted) -> None:
        value = event.value.strip()
        if not value:
            return
        if value.startswith("/"):
            self._run_home_command(value)
            return
        self.app.open_workbench(intent_text=value, initial_status="initialized")  # type: ignore[attr-defined]

    @staticmethod
    def _actions_text() -> str:
        return "\n".join(f"{key}  {label}" for key, label, _command in HOME_ACTIONS)

    def _run_home_command(self, command: str) -> None:
        self.app.open_workbench(initial_command=command)  # type: ignore[attr-defined]


class WorkbenchScreen(Screen[None]):
    """Main Textual workbench: message flow, artifact pane, status sidebar and bottom input."""

    DEFAULT_CSS = """
    WorkbenchScreen {
        layout: vertical;
    }

    #workbench-body {
        height: 1fr;
    }

    #workbench-main {
        width: 1fr;
        height: 1fr;
    }

    #artifact-stack {
        height: 1fr;
    }

    #bottom-region {
        dock: bottom;
        height: 14;
    }

    .hidden {
        display: none;
    }
    """

    def __init__(
        self,
        *,
        session: TuiApp,
        initial_command: str = "",
        intent_text: str = "",
        initial_status: str = "",
    ) -> None:
        super().__init__()
        self.session = session
        self.initial_command = initial_command
        self.intent_text = intent_text
        self.initial_status = initial_status
        self.running_worker_name = ""
        self.running_worker = None
        self.running_stop_event: threading.Event | None = None
        self.show_logs = False
        self.scoped_revision_feedback_active = False
        self.pending_scoped_revision: dict[str, Any] | None = None

    def compose(self) -> ComposeResult:
        yield Header(show_clock=True)
        yield ToastLayer(id="toast-layer")
        with Horizontal(id="workbench-body"):
            with Vertical(id="workbench-main"):
                yield MessageFlow(id="message-flow", wrap=True, markup=True)
                with Vertical(id="artifact-stack"):
                    yield ArtifactReviewPane(presenter=self.session.artifact_presenter, id="artifact-review")
                    yield ArtifactEditorPane(presenter=self.session.artifact_presenter, id="artifact-editor")
            yield StatusSidebar(self.session.render_status_sidebar(), id="status-sidebar")
        with Vertical(id="bottom-region"):
            yield PromptInput(router=self.session.command_router, context=self._command_context(), id="workbench-prompt")
        yield Footer()

    def on_mount(self) -> None:
        self._append_message("系统", "小说续写工作台已启动。")
        self._append_message("系统", "先用 /tasks 查看任务，或 /new-task <task_id> <source_path> 创建任务。")
        self._append_message("系统", "可输入 /task <task_id>、/read、/close-read、/query、/kb、/benchmark、/writer、/resume。")
        if self.initial_status:
            self.session.set_status(self.initial_status)
        if self.intent_text:
            self._append_message("你", self.intent_text)
            self._append_message("系统", "已记录续写方向；Writer 将在正式流程中消费这段方向。")
        self.refresh_all()
        if self.initial_command:
            self._append_message("你", self.initial_command)
            self.handle_command(self.initial_command)

    def on_prompt_input_submitted(self, event: PromptInput.Submitted) -> None:
        value = event.value.strip()
        if not value:
            return
        self._append_message("你", value)
        if value.startswith("/"):
            self.handle_command(value)
            return
        self._append_message("系统", "已记录输入。可以继续输入 /writer 开始或恢复 Writer。")

    def on_decision_panel_widget_selected(self, event: DecisionPanelWidget.Selected) -> None:
        self._append_message("确认", f"{event.action.next_status} · 将调用 {event.action.workflow_action}")
        if event.action.workflow_action == "confirm_current_step":
            self.confirm_current_step(payload=event.action.payload)
            return
        if event.action.workflow_action == "request_scoped_artifact_revision":
            self.show_scoped_revision_feedback()
            return
        if event.action.workflow_action == "manual_edit":
            self.open_current_artifact()
            return
        if event.action.workflow_action == "apply_scoped_artifact_revision":
            self.apply_scoped_revision(str(event.action.payload.get("request_id") or ""))
            return
        if event.action.workflow_action == "reject_scoped_artifact_revision":
            self.reject_scoped_revision()
            return
        if event.action.workflow_action in {"defer_decision", "go_back"}:
            return
        self.confirm_current_step(action_override=event.action.workflow_action, payload=event.action.payload)

    def on_scoped_revision_feedback_widget_submitted(self, event: ScopedRevisionFeedbackWidget.Submitted) -> None:
        feedback = event.feedback.strip()
        if not feedback:
            self._append_message("错误", "请输入你希望怎样修改当前产物。")
            return
        self.request_scoped_revision(feedback)

    def on_scoped_revision_feedback_widget_cancelled(self, _event: ScopedRevisionFeedbackWidget.Cancelled) -> None:
        self.scoped_revision_feedback_active = False
        self._append_message("系统", "已返回当前审阅状态，未提交修改反馈。")
        self.refresh_all()

    def handle_invocation(self, invocation: CommandInvocation) -> None:
        if invocation.handler_name in {"show_status", "show_help", "show_command_palette", "show_debug_details"}:
            self._append_message("系统", self.session.dispatch_command(f"/{invocation.command_id}"))
            self.refresh_all()
            return
        self.handle_command(f"/{invocation.command_id} {' '.join(invocation.args)}".strip())

    def handle_command(self, raw: str) -> None:
        context = self._command_context()
        try:
            invocation = self.session.command_router.parse(raw, context)
        except ValueError as exc:
            self._append_message("错误", str(exc))
            self._append_message("建议", "输入 /help 查看当前可用命令，或按 Ctrl+P 打开命令面板。")
            return
        if invocation.handler_name in {"list_tasks", "select_task", "create_task", "reset_close_read", "query_close_read"}:
            self._append_message("系统", self.session.dispatch_command(raw))
            self.refresh_all()
            return
        if invocation.handler_name == "start_read":
            self.start_read_worker(source_path=Path(invocation.args[0]).expanduser() if invocation.args else None)
            return
        if invocation.handler_name == "start_close_read":
            options = self._parse_close_read_options(invocation.args)
            if "error" in options:
                self._append_message("错误", str(options["error"]))
                self._append_message("恢复建议", self._close_read_usage())
                return
            self.start_read_worker(
                source_path=options["source_path"],  # type: ignore[arg-type]
                close_only=True,
                max_close_batches=int(options["max_close_batches"]),
                close_step_batches=int(options["close_step_batches"]),
            )
            return
        if invocation.handler_name == "build_creative_kb":
            self.start_kb_worker()
            return
        if invocation.handler_name == "run_smoke_benchmark":
            options = self._parse_benchmark_options(invocation.args)
            if "error" in options:
                self._append_message("错误", str(options["error"]))
                self._append_message("恢复建议", self._benchmark_usage())
                return
            self.start_benchmark_worker(
                target=str(options["target"]),
                source_path=options["source_path"],  # type: ignore[arg-type]
                sample_path=options["sample_path"],  # type: ignore[arg-type]
                db_path=options["db_path"],  # type: ignore[arg-type]
                use_real_model=bool(options["use_real_model"]),
            )
            return
        if invocation.handler_name == "run_creative_kb_benchmark":
            options = self._parse_creative_kb_benchmark_options(invocation.args)
            if "error" in options:
                self._append_message("错误", str(options["error"]))
                self._append_message("恢复建议", self._creative_kb_benchmark_usage())
                return
            self.start_creative_kb_benchmark_worker(
                target=str(options["target"]),
                source_path=options["source_path"],  # type: ignore[arg-type]
                run_id=options["run_id"],  # type: ignore[arg-type]
                artifact_dir=options["artifact_dir"],  # type: ignore[arg-type]
                case_count=int(options["case_count"]),
                enable_writer_ab=bool(options["enable_writer_ab"]),
                use_real_model=bool(options["use_real_model"]),
                dry_run_model=bool(options["dry_run_model"]),
            )
            return
        if invocation.handler_name in {"start_writer", "resume"}:
            self.start_writer_worker()
            return
        if invocation.handler_name == "open_artifact":
            self.open_current_artifact()
            return
        if invocation.handler_name == "save_artifact":
            self.save_current_artifact()
            return
        if invocation.handler_name == "confirm_current_step":
            self.confirm_current_step()
            return
        self._append_message("系统", self.session.dispatch_command(raw))
        self.refresh_all()

    def start_read_worker(
        self,
        *,
        source_path: Path | None,
        close_only: bool = False,
        max_close_batches: int = 1,
        close_step_batches: int = 1,
    ) -> None:
        resolved_source_path = source_path or (
            Path(self.session.config.source_path).expanduser() if self.session.config.source_path else None
        )
        if resolved_source_path is None and not close_only:
            self._append_message("错误", "请先选择或创建任务，并提供原文路径。例如 /new-task couple ./couple.txt，或 /read ./couple.txt。")
            self._append_message("恢复建议", "输入 /tasks 查看现有任务；输入 /task <task_id> 进入任务。")
            return
        if not self.session.config.book_id:
            self._append_message("错误", "请先选择 task id。")
            if close_only:
                self._append_message(
                    "恢复建议",
                    f"用法：先 /task <task_id> 或 /new-task <task_id> <source_path>，再执行 {self._close_read_usage()}",
                )
            else:
                self._append_message("恢复建议", "输入 /tasks 查看任务，或 /new-task <task_id> <source_path> 创建任务。")
            return
        if close_only:
            self._append_message(
                "系统",
                f"本轮 /close-read 将处理最多 {max_close_batches} 个精读 batch；每个 batch 按约 {DEFAULT_CLOSE_READ_DOC_BUDGET} 字文档预算组装。",
            )
        if source_path is not None:
            self.session.config.source_path = str(source_path)
            self.session.facade.ensure_task(book_id=self.session.config.book_id, source_path=str(source_path))
        self._start_worker(
            "精读建模" if close_only else "粗读/精读",
            lambda: self.session.facade.start_read_pipeline(
                book_id=self.session.config.book_id,
                source_path=resolved_source_path or self.session.repo_root / "couple.txt",
                db_path=self.session.facade.db_path_for_book(self.session.config.book_id),
                debug_path=self.session.repo_root / "runs" / "close_read_debug.md",
                api_key=os.getenv("DEEPSEEK_API_KEY", "unused"),
                run_mode="resume" if close_only else "new",
                max_read_kb=0 if close_only else 64,
                max_close_batches=max_close_batches,
                segment_step_kb=64,
                close_step_batches=close_step_batches,
                build_creative_kb=True,
                should_stop=self._worker_stop_requested,
            ),
        )

    @staticmethod
    def _close_read_usage() -> str:
        return (
            "/close-read [source_path] [--batches N]；"
            f"默认 N=1，单 batch 约 {DEFAULT_CLOSE_READ_DOC_BUDGET} 字文档预算，从最近 checkpoint 继续。"
        )

    def _parse_close_read_options(self, args: tuple[str, ...]) -> dict[str, object]:
        options: dict[str, object] = {
            "source_path": None,
            "max_close_batches": 1,
            "close_step_batches": 1,
        }
        index = 0
        while index < len(args):
            token = args[index]
            if token in {"--batches", "--max-close-batches", "--max-chapters"}:
                value, index = self._read_int_option(args, index, token)
                if value is None:
                    return {"error": f"{token} 需要一个正整数。"}
                options["max_close_batches"] = value
                continue
            if token in {"--step", "--step-batches", "--close-step-batches"}:
                value, index = self._read_int_option(args, index, token)
                if value is None:
                    return {"error": f"{token} 需要一个正整数。"}
                options["close_step_batches"] = value
                continue
            if token.startswith("--batches="):
                value = self._parse_positive_int(token.split("=", 1)[1])
                if value is None:
                    return {"error": "--batches 需要一个正整数。"}
                options["max_close_batches"] = value
                index += 1
                continue
            if token.startswith("--"):
                return {"error": f"未知 /close-read 参数：{token}"}
            if options["source_path"] is not None:
                return {"error": "只能提供一个 source_path。"}
            options["source_path"] = Path(token).expanduser()
            index += 1
        return options

    def _parse_benchmark_options(self, args: tuple[str, ...]) -> dict[str, object]:
        options: dict[str, object] = {
            "target": "",
            "source_path": None,
            "sample_path": None,
            "db_path": None,
            "use_real_model": True,
        }
        index = 0
        while index < len(args):
            token = args[index]
            if token == "--source":
                if index + 1 >= len(args):
                    return {"error": f"{token} 需要一个文件路径。"}
                options["source_path"] = Path(args[index + 1]).expanduser()
                index += 2
                continue
            if token == "--sample":
                if index + 1 >= len(args):
                    return {"error": f"{token} 需要 sample.json 路径。"}
                options["sample_path"] = Path(args[index + 1]).expanduser()
                index += 2
                continue
            if token == "--db":
                if index + 1 >= len(args):
                    return {"error": f"{token} 需要 SQLite DB 路径。"}
                options["db_path"] = Path(args[index + 1]).expanduser()
                index += 2
                continue
            if token == "--real":
                options["use_real_model"] = True
                index += 1
                continue
            if token.startswith("--source="):
                options["source_path"] = Path(token.split("=", 1)[1]).expanduser()
                index += 1
                continue
            if token.startswith("--sample="):
                options["sample_path"] = Path(token.split("=", 1)[1]).expanduser()
                index += 1
                continue
            if token.startswith("--db="):
                options["db_path"] = Path(token.split("=", 1)[1]).expanduser()
                index += 1
                continue
            if token.startswith("--"):
                return {"error": f"未知 /benchmark 参数：{token}"}
            if options["target"]:
                return {"error": "只能提供一个 benchmark 目标。"}
            options["target"] = token.strip()
            index += 1
        if options["target"] and (options["source_path"] is not None or options["sample_path"] is not None):
            return {"error": "benchmark 目标、--source、--sample 三者只能选择一种。"}
        if options["sample_path"] is not None and options["db_path"] is None:
            return {"error": "使用 --sample 时必须同时提供 --db。"}
        if options["sample_path"] is None and options["db_path"] is not None:
            return {"error": "使用 --db 时必须同时提供 --sample。"}
        if not options["target"] and options["source_path"] is None and options["sample_path"] is None:
            options["target"] = "longzu-32kb"
        return options

    @staticmethod
    def _benchmark_usage() -> str:
        return "/benchmark longzu-32kb | /benchmark --source novel_agent/tests/longzu_32kb.txt"

    def _parse_creative_kb_benchmark_options(self, args: tuple[str, ...]) -> dict[str, object]:
        options: dict[str, object] = {
            "target": "longzu-32kb",
            "source_path": None,
            "run_id": None,
            "artifact_dir": None,
            "case_count": 3,
            "enable_writer_ab": False,
            "use_real_model": True,
            "dry_run_model": False,
        }
        index = 0
        explicit_target = False
        while index < len(args):
            token = args[index]
            if token in {"--source", "--run-id", "--artifact-dir", "--case-count"}:
                if index + 1 >= len(args):
                    return {"error": f"{token} 需要一个值。"}
                value = args[index + 1]
                if token == "--source":
                    options["source_path"] = Path(value).expanduser()
                elif token == "--run-id":
                    options["run_id"] = value
                elif token == "--artifact-dir":
                    options["artifact_dir"] = Path(value).expanduser()
                else:
                    parsed = self._parse_positive_int(value)
                    if parsed is None:
                        return {"error": "--case-count 需要一个正整数。"}
                    options["case_count"] = parsed
                index += 2
                continue
            if token in {"--writer-ab", "--enable-writer-ab"}:
                options["enable_writer_ab"] = True
                index += 1
                continue
            if token == "--dry-run-model":
                options["use_real_model"] = False
                options["dry_run_model"] = True
                index += 1
                continue
            if token.startswith("--source="):
                options["source_path"] = Path(token.split("=", 1)[1]).expanduser()
                index += 1
                continue
            if token.startswith("--run-id="):
                options["run_id"] = token.split("=", 1)[1]
                index += 1
                continue
            if token.startswith("--artifact-dir="):
                options["artifact_dir"] = Path(token.split("=", 1)[1]).expanduser()
                index += 1
                continue
            if token.startswith("--case-count="):
                parsed = self._parse_positive_int(token.split("=", 1)[1])
                if parsed is None:
                    return {"error": "--case-count 需要一个正整数。"}
                options["case_count"] = parsed
                index += 1
                continue
            if token.startswith("--"):
                return {"error": f"未知 /creative-kb-benchmark 参数：{token}"}
            if explicit_target:
                return {"error": "只能提供一个 Creative KB benchmark 目标。"}
            options["target"] = token
            explicit_target = True
            index += 1
        if explicit_target and options["source_path"] is not None:
            return {"error": "benchmark 目标与 --source 只能选择一种。"}
        return options

    @staticmethod
    def _creative_kb_benchmark_usage() -> str:
        return "/creative-kb-benchmark longzu-32kb [--writer-ab] 或 /creative-kb-benchmark --source ./novel.txt"

    def _read_int_option(self, args: tuple[str, ...], index: int, token: str) -> tuple[int | None, int]:
        if index + 1 >= len(args):
            return None, index + 1
        value = self._parse_positive_int(args[index + 1])
        return value, index + 2

    @staticmethod
    def _parse_positive_int(value: str) -> int | None:
        try:
            parsed = int(value)
        except ValueError:
            return None
        return parsed if parsed > 0 else None

    def start_kb_worker(self) -> None:
        book_id = self._require_task_id()
        if not book_id:
            return
        self._start_worker(
            "Creative KB",
            lambda: self.session.facade.build_creative_kb(
                db_path=self.session.facade.db_path_for_book(book_id),
                book_id=book_id,
                api_key=os.getenv("DEEPSEEK_API_KEY", "unused"),
            ),
        )

    def start_benchmark_worker(
        self,
        *,
        target: str,
        source_path: Path | None,
        sample_path: Path | None,
        db_path: Path | None,
        use_real_model: bool,
    ) -> None:
        self._start_worker(
            "MVP smoke benchmark",
            lambda: self.session.facade.run_smoke_benchmark(
                target=target,
                source_path=source_path,
                sample_path=sample_path,
                db_path=db_path,
                use_real_model=use_real_model,
                api_key=os.getenv("DEEPSEEK_API_KEY", "unused"),
            ),
        )

    def start_creative_kb_benchmark_worker(
        self,
        *,
        target: str,
        source_path: Path | None,
        run_id: str | None,
        artifact_dir: Path | None,
        case_count: int,
        enable_writer_ab: bool,
        use_real_model: bool,
        dry_run_model: bool,
    ) -> None:
        self._start_worker(
            "Creative KB Benchmark",
            lambda: self.session.facade.run_creative_kb_benchmark(
                target=target,
                source_path=source_path,
                run_id=run_id,
                artifact_dir=artifact_dir,
                case_count=case_count,
                enable_writer_ab=enable_writer_ab,
                use_real_model=use_real_model,
                dry_run_model=dry_run_model,
                api_key=os.getenv("DEEPSEEK_API_KEY", "unused"),
            ),
        )

    def start_writer_worker(self) -> None:
        book_id = self._require_task_id()
        if not book_id:
            return
        self._start_worker(
            "Writer",
            lambda: self.session.facade.start_writer(book_id=book_id, dry_run=True, allow_incomplete_modeling=True),
        )

    def confirm_current_step(
        self,
        *,
        action_override: str = "",
        payload: dict[str, object] | None = None,
    ) -> None:
        stage = str(self.session.current_status.technical_details.get("internal_stage") or "")
        action = action_override or next(
            (item.workflow_action for item in self.session.status_presenter.writer_actions_for_stage(stage=stage)),
            "",
        )
        if not action:
            self._append_message("确认", self.session.status_presenter.event_message("confirm_checkpoint"))
            return
        run_id = str(self.session.current_status.technical_details.get("run_id") or "")
        if not run_id:
            self._append_message("确认", f"下一步将调用 workflow action：{action}")
            return
        self._start_worker(
            "Writer 确认",
            lambda: self.session.facade.writer_action(
                book_id=self.session.config.book_id,
                run_id=run_id,
                action=action,
                payload=payload or {},
                dry_run=True,
            ),
        )

    def save_current_artifact(self) -> None:
        result = self.query_one("#artifact-editor", ArtifactEditorPane).save_current()
        if result.saved:
            self.toast(result.message)
            self._append_message("保存", self.session.status_presenter.event_message("artifact_saved"))
            self.show_artifact(result.path, stage=str(self.session.current_status.technical_details.get("internal_stage") or ""))
            return
        self._append_message("错误", result.validation_error or result.message)

    def show_scoped_revision_feedback(self) -> None:
        if not self.session.current_artifact:
            self._append_message("错误", "当前没有可按反馈修改的产物。")
            return
        if not self._current_review_stage():
            self._append_message("错误", "当前审阅状态不完整，无法发起受控修订。")
            return
        self.scoped_revision_feedback_active = True
        self.pending_scoped_revision = None
        self._ensure_scoped_revision_feedback_widget()
        self.refresh_all()

    def request_scoped_revision(self, feedback: str) -> None:
        artifact = self.session.current_artifact
        stage = self._current_review_stage()
        run_id = self._current_run_id()
        if artifact is None or not stage or not run_id:
            self._append_message("错误", "缺少 run id、审阅状态或当前产物，无法提交修改反馈。")
            self._append_message("恢复建议", "先恢复 Writer 审阅 checkpoint，再重新选择“按我的反馈修改”。")
            self.scoped_revision_feedback_active = False
            self.refresh_all()
            return
        self.scoped_revision_feedback_active = False
        self._append_message("反馈", "已提交你的修改要求，正在生成受控修订候选。")
        self._start_worker(
            "按反馈修改",
            lambda: self.session.facade.request_scoped_artifact_revision(
                book_id=self.session.config.book_id,
                run_id=run_id,
                current_review_state=stage,
                target_artifact_path=str(artifact.path),
                user_feedback=feedback,
                dry_run=True,
            ),
        )

    def apply_scoped_revision(self, request_id: str) -> None:
        run_id = self._current_run_id()
        if not request_id or not run_id:
            self._append_message("错误", "缺少候选修改 request id，无法应用。")
            self.refresh_all()
            return
        self._start_worker(
            "应用候选修改",
            lambda: self.session.facade.apply_scoped_artifact_revision(
                book_id=self.session.config.book_id,
                run_id=run_id,
                request_id=request_id,
                dry_run=True,
            ),
        )

    def reject_scoped_revision(self) -> None:
        self.pending_scoped_revision = None
        self.scoped_revision_feedback_active = False
        self._append_message("系统", "已拒绝候选修改，当前产物未写入，仍停留在当前审阅状态。")
        self.refresh_all()

    def open_current_artifact(self) -> None:
        if not self.session.current_artifact:
            self._append_message("系统", "当前没有可打开的产物。")
            return
        self.query_one("#artifact-editor", ArtifactEditorPane).load_path(self.session.current_artifact.path)
        self.toast(f"已打开编辑视图：{self.session.current_artifact.path.name}")
        self.refresh_all()

    def show_artifact(self, path: Path | str, *, stage: str = "") -> None:
        summary = self.session.show_artifact(path, stage=stage)
        self.query_one("#artifact-review", ArtifactReviewPane).show_summary(summary)
        self.query_one("#artifact-editor", ArtifactEditorPane).load_path(summary.path)
        self.refresh_all()

    def toggle_logs(self) -> None:
        self.show_logs = not self.show_logs
        self._append_message("系统", "已显示折叠日志事件。" if self.show_logs else "已收起运行日志。")

    def refresh_all(self) -> None:
        self.session.ingest_facade_events()
        self._refresh_events_from_stream()
        self.query_one("#status-sidebar", StatusSidebar).update(self.session.render_status_sidebar())
        prompt = self.query_one("#workbench-prompt", PromptInput)
        prompt.set_context(
            flow=self.session.current_status.flow,
            step=self.session.current_status.step,
            running=bool(self.running_worker_name),
        )
        prompt.set_artifact_context(
            has_artifact=self.session.current_artifact is not None,
            candidates=self._artifact_candidates(),
        )
        self._refresh_decision_panel()

    def toast(self, message: str) -> None:
        self.query_one("#toast-layer", ToastLayer).show_message(message)
        self.notify(message, timeout=2)

    def technical_details_text(self) -> str:
        details = dict(self.session.last_debug_details)
        artifact = self.session.current_artifact
        if artifact:
            details["artifact_path"] = str(artifact.path)
            details.update(artifact.technical_details)
        return "\n".join(f"{key}: {value}" for key, value in details.items())

    def _start_worker(self, name: str, fn) -> None:  # type: ignore[no-untyped-def]
        self.running_worker_name = name
        self.running_stop_event = threading.Event()
        self._append_message("进度", f"正在运行{name}…")
        self.refresh_all()

        def run() -> None:
            try:
                result = fn()
            except Exception as exc:  # noqa: BLE001 - convert worker failures to recoverable UI events.
                self.app.call_from_thread(self._finish_worker, name, None, exc)
                return
            self.app.call_from_thread(self._finish_worker, name, result, None)

        self.running_worker = self.app.run_worker(run, name=name, thread=True, exit_on_error=False)

    def _finish_worker(self, name: str, result: Any, exc: Exception | None) -> None:
        self.running_worker_name = ""
        self.running_worker = None
        self.running_stop_event = None
        if exc is not None:
            self._append_message("错误", f"{name}遇到问题：{exc}")
            self._append_message("恢复建议", "检查缺失文件、API Key 或最近 checkpoint 后，可从 /resume 或对应流程重试。")
            self.refresh_all()
            return
        self.session.ingest_facade_events()
        self._refresh_events_from_stream()
        self._append_message("系统", f"{name}本轮已完成。")
        if isinstance(result, dict):
            self._apply_workflow_result(result)
        self.refresh_all()

    def request_stop_worker(self, *, announce: bool = True) -> None:
        if not self.running_worker_name:
            return
        if self.running_stop_event is not None:
            self.running_stop_event.set()
        worker = self.running_worker
        if worker is not None and hasattr(worker, "cancel"):
            worker.cancel()
        if announce:
            self._append_message("暂停", "已请求停止后台任务；当前模型调用结束后会在 checkpoint 处停下。")
            self.refresh_all()

    def on_unmount(self) -> None:
        self.request_stop_worker(announce=False)

    def _worker_stop_requested(self) -> bool:
        return bool(self.running_stop_event and self.running_stop_event.is_set())

    def _apply_workflow_result(self, result: dict[str, Any]) -> None:
        if self._is_scoped_revision_result(result):
            self._apply_scoped_revision_result(result)
            return
        checkpoint = result.get("checkpoint")
        status = str(result.get("status") or "")
        if result.get("summary_text"):
            self._append_message("Reviewer", str(result["summary_text"]))
            return
        if "decision" in result and "score" in result:
            self._append_message(
                "Reviewer",
                (
                    f"{result.get('summary', '')}\n"
                    f"结果：{result.get('decision')}，分数：{round(float(result.get('score') or 0.0) * 100)}。\n"
                    f"产物目录：{result.get('run_dir')}"
                ).strip(),
            )
            return
        if isinstance(checkpoint, dict):
            self.session.current_status = self.session.status_presenter.present_checkpoint(checkpoint)
            artifact_path = str(checkpoint.get("artifact_path") or "")
            if artifact_path:
                self.show_artifact(artifact_path, stage=str(checkpoint.get("stage") or ""))
            return
        if status:
            self.session.set_status(status)

    @staticmethod
    def _is_scoped_revision_result(result: dict[str, Any]) -> bool:
        return any(key in result for key in ("revision_id", "request_id", "change_summary")) and "validation" in result

    def _apply_scoped_revision_result(self, result: dict[str, Any]) -> None:
        status = str(result.get("status") or "")
        self._append_message("候选修改", self._render_scoped_revision_result(result))
        if status == "candidate":
            self.pending_scoped_revision = dict(result)
            return
        if status == "applied":
            self.pending_scoped_revision = None
            self.toast(self.session.status_presenter.event_message("artifact_saved"))
            self._append_message("保存", self.session.status_presenter.event_message("artifact_saved"))
            artifact_path = str(result.get("artifact_path") or "")
            if artifact_path:
                self.show_artifact(artifact_path, stage=self._current_review_stage())
            return
        self.pending_scoped_revision = None

    @staticmethod
    def _render_scoped_revision_result(result: dict[str, Any]) -> str:
        validation = result.get("validation") if isinstance(result.get("validation"), dict) else {}
        errors = validation.get("errors") if isinstance(validation, dict) else None
        suggestions = result.get("recovery_suggestions") or result.get("recovery") or []
        if isinstance(suggestions, str):
            suggestion_lines = [suggestions]
        elif isinstance(suggestions, list):
            suggestion_lines = [str(item) for item in suggestions if str(item).strip()]
        else:
            suggestion_lines = []
        if not suggestion_lines and validation.get("ok") is False:
            suggestion_lines = ["修改反馈后重试，或选择手动编辑当前产物。"]
        if not suggestion_lines:
            suggestion_lines = ["确认无误后选择“接受候选修改”，或拒绝返回当前审阅。"]

        lines = [
            f"修改摘要：{result.get('change_summary') or '未提供摘要'}",
            "",
            "Diff：",
            str(result.get("diff") or "无 diff。"),
            "",
            "校验结果：",
            "通过" if validation.get("ok") is True else "未通过" if validation.get("ok") is False else "未提供",
        ]
        if errors:
            if not isinstance(errors, list):
                errors = [errors]
            lines.extend(str(error) for error in errors)
        lines.extend(["", "恢复建议：", *suggestion_lines])
        return "\n".join(lines)

    def _refresh_decision_panel(self) -> None:
        stage = str(self.session.current_status.technical_details.get("internal_stage") or "")
        panel = None
        self._hide_scoped_revision_feedback_widget(not self.scoped_revision_feedback_active)
        prompt = self.query_one("#workbench-prompt", PromptInput)
        if self.scoped_revision_feedback_active:
            prompt.display = False
            for widget in self.query("#decision-panel"):
                widget.display = False
            self._ensure_scoped_revision_feedback_widget()
            return
        if self.pending_scoped_revision and str(self.pending_scoped_revision.get("status") or "") == "candidate":
            panel = DecisionPanel.scoped_revision_candidate(
                request_id=str(self.pending_scoped_revision.get("request_id") or ""),
                stage_label=self.session.current_status.step,
            )
        elif stage == "wait_chapter_acceptance" and self.session.current_artifact:
            panel = DecisionPanel.chapter_acceptance(draft_path=str(self.session.current_artifact.path))
        elif self.session.current_artifact and stage in {
            "freeze_a_review",
            "batch_review",
            "chapter_review",
            "wait_length_review",
            "freeze_d_review",
            "writeback_review",
        }:
            panel = DecisionPanel.planning_review(
                artifact_path=str(self.session.current_artifact.path),
                stage_label=self.session.current_status.step,
                next_status=self.session.current_status.next_action,
            )
        existing = self.query("#decision-panel")
        if panel is None:
            for widget in existing:
                widget.display = False
            prompt.display = True
            return
        prompt.display = False
        if self.session.decision_panel is None or self.session.decision_panel.render() != panel.render():
            self.session.show_decision_panel(panel)
        else:
            self.session.decision_panel = panel
        for widget in existing:
            decision_widget = widget
            if isinstance(decision_widget, DecisionPanelWidget):
                decision_widget.set_panel(panel)
                decision_widget.display = True
                return
        self.query_one("#bottom-region", Vertical).mount(DecisionPanelWidget(panel, id="decision-panel"))

    def _ensure_scoped_revision_feedback_widget(self) -> ScopedRevisionFeedbackWidget:
        existing = self.query("#scoped-revision-feedback")
        for widget in existing:
            if isinstance(widget, ScopedRevisionFeedbackWidget):
                widget.display = True
                widget.focus()
                return widget
        widget = ScopedRevisionFeedbackWidget(id="scoped-revision-feedback")
        self.query_one("#bottom-region", Vertical).mount(widget)
        return widget

    def _hide_scoped_revision_feedback_widget(self, should_hide: bool) -> None:
        if not should_hide:
            return
        for widget in self.query("#scoped-revision-feedback"):
            widget.display = False

    def _current_review_stage(self) -> str:
        return str(self.session.current_status.technical_details.get("internal_stage") or "")

    def _current_run_id(self) -> str:
        return str(self.session.current_status.technical_details.get("run_id") or "")

    def _refresh_events_from_stream(self) -> None:
        flow = self.query_one("#message-flow", MessageFlow)
        existing = getattr(flow, "_novel_event_count", 0)
        events = self.session.messages.messages()
        for event in events[existing:]:
            flow.append_event(event)
        setattr(flow, "_novel_event_count", len(events))

    def _append_message(self, kind: str, message: str) -> None:
        event = self.session.messages.append(kind, message)
        self.query_one("#message-flow", MessageFlow).append_event(event)
        flow = self.query_one("#message-flow", MessageFlow)
        setattr(flow, "_novel_event_count", len(self.session.messages.messages()))

    def _command_context(self) -> CommandContext:
        return CommandContext(
            mode=self.session.current_status.flow,
            stage=str(self.session.current_status.technical_details.get("internal_stage") or ""),
            has_artifact=self.session.current_artifact is not None,
            running=bool(self.running_worker_name),
        )

    def _require_task_id(self) -> str:
        if self.session.config.book_id:
            return self.session.config.book_id
        self._append_message("错误", "请先选择 task id。")
        self._append_message("建议", "输入 /tasks 查看任务，或 /new-task <task_id> <source_path> 创建任务。")
        return ""

    def _artifact_candidates(self) -> list[ArtifactReferenceCandidate]:
        candidates = []
        if self.session.current_artifact:
            path = self.session.current_artifact.path
            candidates.append(ArtifactReferenceCandidate(label=path.name, path=path, token=f"[Artifact: {path.name}]"))
        runs_dir = self.session.repo_root / "runs"
        if runs_dir.exists():
            candidates.extend(
                ArtifactReferenceCandidate(label=path.name, path=path, token=f"[Artifact: {path.name}]")
                for path in sorted(runs_dir.rglob("*"))[:8]
                if path.is_file()
            )
        return candidates

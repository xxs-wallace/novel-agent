from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

from ..query_close_read import QUERY_TYPES
from .artifacts import ArtifactPresenter, ArtifactSummary
from .decisions import DecisionPanel
from .events import MessageStream, RunEventStream
from .facade import WorkflowFacade
from .input import ChineseInputBuffer
from .router import CommandContext, CommandRouter
from .status import StatusPresenter, StatusView


@dataclass(slots=True)
class TuiSessionConfig:
    project: str = ""
    book_id: str = ""
    source_path: str = ""
    width: int = 100
    narrow_width: int = 72


class TuiApp:
    """Minimal terminal workbench facade with stable output/input regions."""

    def __init__(
        self,
        *,
        repo_root: Path,
        config: TuiSessionConfig | None = None,
        facade: WorkflowFacade | None = None,
        status_presenter: StatusPresenter | None = None,
        artifact_presenter: ArtifactPresenter | None = None,
        command_router: CommandRouter | None = None,
    ) -> None:
        self.repo_root = repo_root.expanduser().resolve()
        self.config = config or TuiSessionConfig()
        self.status_presenter = status_presenter or StatusPresenter()
        self.artifact_presenter = artifact_presenter or ArtifactPresenter()
        self.event_stream = RunEventStream()
        self.facade = facade or WorkflowFacade(repo_root=self.repo_root, event_stream=self.event_stream)
        self.command_router = command_router or CommandRouter()
        self.messages = MessageStream()
        self.input_buffer = ChineseInputBuffer()
        self.current_status = self.status_presenter.present("")
        self.current_artifact: ArtifactSummary | None = None
        self.decision_panel: DecisionPanel | None = None
        self.last_debug_details: dict[str, Any] = {}

    def set_status(self, internal_status: str, *, technical_details: dict[str, Any] | None = None) -> StatusView:
        self.current_status = self.status_presenter.present(internal_status, technical_details=technical_details)
        self.last_debug_details.update(self.current_status.technical_details)
        return self.current_status

    def show_artifact(self, path: Path | str, *, stage: str = "") -> ArtifactSummary:
        self.current_artifact = self.artifact_presenter.summarize(path, stage=stage)
        self.messages.append("审阅", self.current_artifact.title, payload={"path": str(self.current_artifact.path)})
        return self.current_artifact

    def show_decision_panel(self, panel: DecisionPanel) -> None:
        self.decision_panel = panel
        self.messages.append("确认", panel.title)

    def dispatch_command(self, raw: str) -> str:
        context = CommandContext(
            mode=self.current_status.flow,
            stage=str(self.current_status.technical_details.get("internal_stage") or ""),
            has_artifact=self.current_artifact is not None,
            running=False,
        )
        invocation = self.command_router.parse(raw, context)
        if invocation.handler_name == "show_status":
            return self.render_status_sidebar()
        if invocation.handler_name == "list_tasks":
            return self.facade.render_task_list(active_book_id=self.config.book_id)
        if invocation.handler_name == "select_task":
            if not invocation.args:
                return "请输入 task id，例如 /task couple。也可以输入 /tasks 查看所有任务。"
            task = self.facade.ensure_task(book_id=invocation.args[0])
            self.config.book_id = task.book_id
            self.config.source_path = task.source_path
            return f"已进入任务 {task.book_id}。\n{task.render_status_line(active=True)}"
        if invocation.handler_name == "create_task":
            if not invocation.args:
                return "请输入新 task id，例如 /new-task couple ./couple.txt。"
            source_path = " ".join(invocation.args[1:])
            task = self.facade.ensure_task(book_id=invocation.args[0], source_path=source_path)
            self.config.book_id = task.book_id
            self.config.source_path = task.source_path
            return f"已创建并进入任务 {task.book_id}。\n{task.render_status_line(active=True)}"
        if invocation.handler_name == "reset_close_read":
            if not self.config.book_id:
                return "请先选择 task id。使用 /tasks 查看任务，或 /task <task_id> 进入任务。"
            result = self.facade.reset_close_read_task(book_id=self.config.book_id)
            deleted = result["deleted"] if isinstance(result.get("deleted"), dict) else {}
            return (
                f"已清空任务 {self.config.book_id} 的精读进度，可以重新执行 /close-read。\n"
                f"清理：chapters={deleted.get('chapters', 0)}，人物档案={deleted.get('character_profiles', 0)}，"
                f"进度={deleted.get('close_read_progress', 0)}，文件={deleted.get('files', 0)}"
            )
        if invocation.handler_name == "query_close_read":
            return self._dispatch_close_read_query(invocation.args)
        if invocation.handler_name == "run_smoke_benchmark":
            return self._dispatch_smoke_benchmark(invocation.args)
        if invocation.handler_name == "run_creative_kb_benchmark":
            return self._dispatch_creative_kb_benchmark(invocation.args)
        if invocation.handler_name == "show_command_palette":
            return self.command_router.render_panel(context)
        if invocation.handler_name == "show_help":
            return self.command_router.render_panel(context)
        if invocation.handler_name == "list_artifacts":
            if not self.current_artifact:
                return "当前没有可审阅的产物。"
            return self.current_artifact.render()
        if invocation.handler_name == "save_artifact":
            if not self.current_artifact:
                return "当前没有可保存的产物。"
            if not invocation.args:
                return "请输入要保存的文本，或进入编辑视图后按保存。"
            result = self.artifact_presenter.save_text(self.current_artifact.path, " ".join(invocation.args))
            return result.message if result.saved else result.validation_error
        if invocation.handler_name == "confirm_current_step":
            return self.status_presenter.event_message(
                "confirm_checkpoint",
                {"next_status": self.current_status.next_action},
            )
        if invocation.handler_name == "show_debug_details":
            return str(self.last_debug_details)
        return f"已收到命令：/{invocation.command_id}"

    def _dispatch_close_read_query(self, args: tuple[str, ...]) -> str:
        if not self.config.book_id:
            return "请先选择 task id。使用 /tasks 查看任务，或 /task <task_id> 进入任务。"
        if not args:
            return (
                "用法：/query <summary|character|outline|source_arc> [参数] [--json]\n"
                "例如 /query summary、/query summary 5、/query summary total、/query character 沈青。"
            )
        output_format = "json" if "--json" in args or "--format=json" in args else "markdown"
        positional = tuple(arg for arg in args if arg not in {"--json", "--format=json"})
        if not positional:
            return "请输入要查看的精读产物类型：summary、character、outline 或 source_arc。"
        query_type = positional[0]
        book_id = self.config.book_id
        if query_type not in QUERY_TYPES and len(positional) >= 2 and positional[1] in QUERY_TYPES:
            book_id = positional[0]
            query_type = positional[1]
            character_name = " ".join(positional[2:])
        else:
            character_name = " ".join(positional[1:])
        if query_type not in QUERY_TYPES:
            return "未知精读产物类型。可用类型：summary、character、outline、source_arc。"
        summary_selector = self._parse_summary_selector(positional[1:]) if query_type == "summary" else {}
        if query_type == "summary":
            character_name = ""
        try:
            return self.facade.query_close_read(
                book_id=book_id,
                query_type=query_type,
                character_name=character_name,
                **summary_selector,
                output_format=output_format,
            )
        except FileNotFoundError as exc:
            return str(exc)

    def _dispatch_smoke_benchmark(self, args: tuple[str, ...]) -> str:
        options: dict[str, object] = {
            "target": "",
            "source_path": None,
            "sample_path": None,
            "db_path": None,
        }
        index = 0
        while index < len(args):
            token = args[index]
            if token in {"--source", "--sample", "--db"}:
                if index + 1 >= len(args):
                    return f"{token} 需要一个路径。"
                key = {
                    "--source": "source_path",
                    "--sample": "sample_path",
                    "--db": "db_path",
                }[token]
                options[key] = Path(args[index + 1]).expanduser()
                index += 2
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
                return f"未知 /benchmark 参数：{token}"
            if options["target"]:
                return "只能提供一个 benchmark 目标。"
            options["target"] = token
            index += 1
        if not options["target"] and options["source_path"] is None and options["sample_path"] is None:
            options["target"] = "longzu-32kb"
        if options["sample_path"] is not None and options["db_path"] is None:
            return "使用 --sample 时必须同时提供 --db。"
        payload = self.facade.run_smoke_benchmark(
            target=str(options["target"]),
            source_path=options["source_path"],  # type: ignore[arg-type]
            sample_path=options["sample_path"],  # type: ignore[arg-type]
            db_path=options["db_path"],  # type: ignore[arg-type]
        )
        return str(payload.get("summary_text") or payload.get("reviewer_summary") or payload)

    def _dispatch_creative_kb_benchmark(self, args: tuple[str, ...]) -> str:
        options = self._parse_creative_kb_benchmark_options(args)
        error = options.get("error")
        if error:
            return str(error)
        payload = self.facade.run_creative_kb_benchmark(
            target=str(options["target"]),
            source_path=options["source_path"],  # type: ignore[arg-type]
            run_id=options["run_id"],  # type: ignore[arg-type]
            artifact_dir=options["artifact_dir"],  # type: ignore[arg-type]
            case_count=int(options["case_count"]),
            enable_writer_ab=bool(options["enable_writer_ab"]),
            use_real_model=bool(options["use_real_model"]),
            dry_run_model=bool(options["dry_run_model"]),
        )
        return str(payload.get("summary_text") or payload.get("summary") or payload)

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
    def _parse_summary_selector(args: tuple[str, ...]) -> dict[str, object]:
        if not args:
            return {}
        keyword = args[0].strip().lower()
        if keyword in {"total", "overall", "all-summary", "总览", "总共", "整体"}:
            return {"summary_scope": "total"}
        if keyword in {"all", "全部"}:
            return {"summary_scope": "all"}
        if keyword in {"doc", "doc-id", "document-id"} and len(args) >= 2:
            doc_id = TuiApp._parse_positive_int(args[1])
            return {"doc_id": doc_id, "summary_scope": "document"} if doc_id is not None else {}
        if keyword in {"document", "title", "title-index", "document-title-index"} and len(args) >= 2:
            title_index = TuiApp._parse_positive_int(args[1])
            return {"document_title_index": title_index, "summary_scope": "document"} if title_index is not None else {}
        title_index = TuiApp._parse_positive_int(args[0])
        return {"document_title_index": title_index, "summary_scope": "document"} if title_index is not None else {}

    @staticmethod
    def _parse_positive_int(value: str) -> int | None:
        try:
            parsed = int(str(value).strip())
        except ValueError:
            return None
        return parsed if parsed >= 0 else None

    def ingest_facade_events(self) -> None:
        self.messages.extend(self.event_stream.events())
        self.event_stream.clear()

    def render(self, *, width: int | None = None) -> str:
        width = width or self.config.width
        self.ingest_facade_events()
        message_panel = self.messages.render(limit=16) or "欢迎来到小说续写工作台。"
        artifact_panel = self.current_artifact.render() if self.current_artifact else "当前没有打开的产物。"
        decision_or_input = self.decision_panel.render() if self.decision_panel else self._render_input_area()
        if width < self.config.narrow_width:
            parts = [
                self._box("消息流", message_panel),
                self._box("产物", artifact_panel),
                self._box("输入区", decision_or_input),
            ]
            return "\n".join(parts)
        parts = [
            self._box("消息流", message_panel),
            self._box("产物审阅", artifact_panel),
            self._box("状态侧栏", self.render_status_sidebar()),
            self._box("输入区 / 决策面板", decision_or_input),
        ]
        return "\n".join(parts)

    def render_status_sidebar(self) -> str:
        return self.status_presenter.present_sidebar(
            project=self._project_label(),
            internal_status=str(self.current_status.technical_details.get("internal_stage") or ""),
            artifact_path=str(self.current_artifact.path) if self.current_artifact else "",
        )

    def _render_input_area(self) -> str:
        context = self.current_status.step
        return f"{self.current_status.flow} · {context}\n{self.input_buffer.text}\nEnter 确认输入 · Ctrl+S 保存 · Ctrl+P 命令面板"

    def _project_label(self) -> str:
        if self.config.book_id and self.config.project and self.config.project != self.config.book_id:
            return f"{self.config.project} / task {self.config.book_id}"
        return self.config.book_id or self.config.project

    @staticmethod
    def _box(title: str, content: str) -> str:
        return f"[{title}]\n{content}"

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from rich.align import Align
from rich.panel import Panel
from rich.text import Text
from textual import events
from textual.app import ComposeResult
from textual.containers import Container, Vertical
from textual.message import Message
from textual.screen import ModalScreen
from textual.widgets import Input, RichLog, Static, TextArea

from .artifacts import ArtifactPresenter, ArtifactSaveResult, ArtifactSummary
from .decisions import DecisionAction, DecisionPanel
from .events import RunEvent
from .router import CommandContext, CommandInvocation, CommandRouter, CommandSpec


@dataclass(frozen=True, slots=True)
class ArtifactReferenceCandidate:
    label: str
    path: Path
    token: str


class MessageFlow(RichLog):
    """Message stream widget that keeps runner output away from the editable prompt."""

    DEFAULT_CSS = """
    MessageFlow {
        height: 2fr;
        border-left: solid $primary;
        padding: 0 1;
    }
    """

    def append_event(self, event: RunEvent) -> None:
        self.write(self.render_event(event), expand=event.kind == "你")

    @staticmethod
    def render_event(event: RunEvent) -> object:
        if event.kind == "你":
            return Align.right(
                Panel.fit(
                    Text(event.message, style="bold white"),
                    title="你",
                    title_align="right",
                    border_style="cyan",
                    padding=(0, 1),
                )
            )
        return f"{event.kind} · {event.message}"


class StatusSidebar(Static):
    """User-facing project status; internal ids belong only in the technical overlay."""

    DEFAULT_CSS = """
    StatusSidebar {
        width: 42;
        border-left: solid $secondary;
        padding: 0 1;
    }
    """


class ToastLayer(Static):
    DEFAULT_CSS = """
    ToastLayer {
        dock: top;
        height: auto;
        display: none;
        padding: 0 1;
        background: $success 20%;
        color: $text;
    }
    """

    def show_message(self, message: str) -> None:
        self.update(message)
        self.display = True
        self.set_timer(2.4, self.hide)

    def hide(self) -> None:
        self.display = False


class PromptTextArea(TextArea):
    """TextArea variant where Enter submits instead of being swallowed as an edit key."""

    async def _on_key(self, event: events.Key) -> None:
        if event.key == "shift+enter":
            event.stop()
            event.prevent_default()
            self.insert("\n")
            return
        if event.key in {"enter", "ctrl+j"}:
            event.stop()
            event.prevent_default()
            prompt = self.parent
            if isinstance(prompt, PromptInput):
                prompt.submit()
            return
        await super()._on_key(event)


class PromptInput(Vertical, can_focus=True):
    """Textual prompt wrapper with metadata, history, slash and artifact suggestions."""

    DEFAULT_CSS = """
    PromptInput {
        height: 14;
        min-height: 12;
        max-height: 16;
        border-top: solid $accent;
        padding: 0 1;
        background: $surface;
    }

    PromptInput TextArea {
        height: 8;
        min-height: 6;
        max-height: 10;
        border: none;
        background: $panel;
    }

    #prompt-meta, #prompt-running {
        height: 1;
        color: $text-muted;
    }

    #slash-autocomplete, #artifact-autocomplete {
        height: auto;
        max-height: 5;
        display: none;
        color: $warning;
    }
    """

    class Submitted(Message):
        def __init__(self, value: str) -> None:
            self.value = value
            super().__init__()

    def __init__(
        self,
        *,
        router: CommandRouter,
        context: CommandContext | None = None,
        artifact_candidates: list[ArtifactReferenceCandidate] | None = None,
        id: str | None = None,
    ) -> None:
        super().__init__(id=id)
        self.router = router
        self.context = context or CommandContext()
        self.history: list[str] = []
        self.artifact_candidates = artifact_candidates or []

    def compose(self) -> ComposeResult:
        yield Static("工作台 · 等待你选择下一步    Enter 发送 · Shift+Enter 换行 · Ctrl+P 命令面板", id="prompt-meta")
        yield Static("", id="slash-autocomplete")
        yield Static("", id="artifact-autocomplete")
        yield PromptTextArea("", language="markdown", show_line_numbers=False, soft_wrap=True, id="prompt-text")
        yield Static("输出与后台日志会进入消息流，不会覆盖输入。", id="prompt-running")

    def on_mount(self) -> None:
        self.query_one("#prompt-text", TextArea).focus()
        self.refresh_suggestions()

    @property
    def value(self) -> str:
        return self.query_one("#prompt-text", TextArea).text

    @value.setter
    def value(self, text: str) -> None:
        prompt = self.query_one("#prompt-text", TextArea)
        prompt.load_text(text)
        prompt.move_cursor(prompt.document.end)
        self.refresh_suggestions()

    def set_context(self, *, flow: str, step: str, running: bool = False) -> None:
        self.context = CommandContext(mode=flow, stage=step, has_artifact=self.context.has_artifact, running=running)
        self.query_one("#prompt-meta", Static).update(
            f"{flow} · {step}    Enter 发送 · Shift+Enter 换行 · Ctrl+S 保存 · Ctrl+P 命令面板"
        )
        self.query_one("#prompt-running", Static).update(
            "后台任务运行中 · Esc 请求暂停 · 输出不会覆盖输入"
            if running
            else "输出与后台日志会进入消息流，不会覆盖输入。"
        )
        self.refresh_suggestions()

    def set_artifact_context(self, *, has_artifact: bool, candidates: list[ArtifactReferenceCandidate] | None = None) -> None:
        self.context = CommandContext(
            mode=self.context.mode,
            stage=self.context.stage,
            has_artifact=has_artifact,
            running=self.context.running,
        )
        if candidates is not None:
            self.artifact_candidates = candidates
        self.refresh_suggestions()

    def submit(self) -> None:
        value = self.value.strip()
        if value:
            self.history.append(value)
        self.value = ""
        self.post_message(self.Submitted(value))

    def on_text_area_changed(self, _event: TextArea.Changed) -> None:
        self.refresh_suggestions()

    def refresh_suggestions(self) -> None:
        text = self.value.strip()
        self._refresh_slash(text)
        self._refresh_artifacts(text)

    def _refresh_slash(self, text: str) -> None:
        widget = self.query_one("#slash-autocomplete", Static)
        if not text.startswith("/"):
            widget.display = False
            widget.update("")
            return
        query = next(iter(text[1:].split(maxsplit=1)), "").lower()
        commands = [
            command
            for command in self.router.available_commands(self.context)
            if not query or query in command.command_id or query in command.label.lower()
        ]
        widget.update("\n".join(f"/{command.command_id}  {command.label}" for command in commands[:8]))
        widget.display = bool(commands)

    def _refresh_artifacts(self, text: str) -> None:
        widget = self.query_one("#artifact-autocomplete", Static)
        if "@" not in text:
            widget.display = False
            widget.update("")
            return
        query = text.rsplit("@", 1)[-1].strip().lower()
        candidates = [
            candidate
            for candidate in self.artifact_candidates
            if not query or query in candidate.label.lower() or query in candidate.path.name.lower()
        ]
        widget.update("\n".join(f"{candidate.token}  {candidate.path.name}" for candidate in candidates[:6]))
        widget.display = bool(candidates)


class ArtifactReviewPane(Vertical):
    DEFAULT_CSS = """
    ArtifactReviewPane {
        height: 1fr;
        border-left: solid $accent;
        padding: 0 1;
    }

    #artifact-review-body {
        height: 1fr;
    }
    """

    def __init__(self, *, presenter: ArtifactPresenter, id: str | None = None) -> None:
        super().__init__(id=id)
        self.presenter = presenter
        self.summary: ArtifactSummary | None = None

    def compose(self) -> ComposeResult:
        yield Static("当前没有打开的产物。", id="artifact-review-body")

    def show_summary(self, summary: ArtifactSummary) -> None:
        self.summary = summary
        self.query_one("#artifact-review-body", Static).update(summary.render())

    def show_path(self, path: Path | str, *, stage: str = "") -> ArtifactSummary:
        summary = self.presenter.summarize(path, stage=stage)
        self.show_summary(summary)
        return summary


class ArtifactEditorPane(Vertical):
    DEFAULT_CSS = """
    ArtifactEditorPane {
        height: 1fr;
        border-left: solid $warning;
        padding: 0 1;
        display: none;
    }

    ArtifactEditorPane TextArea {
        height: 1fr;
        background: $panel;
    }

    #artifact-editor-status {
        height: auto;
        color: $warning;
    }
    """

    def __init__(self, *, presenter: ArtifactPresenter, id: str | None = None) -> None:
        super().__init__(id=id)
        self.presenter = presenter
        self.path: Path | None = None

    def compose(self) -> ComposeResult:
        yield Static("编辑视图", id="artifact-editor-title")
        yield TextArea.code_editor("", language="json", id="artifact-editor-text")
        yield Static("", id="artifact-editor-status")

    def load_path(self, path: Path | str) -> None:
        model = self.presenter.edit_model(path)
        self.path = Path(model["path"])
        self.query_one("#artifact-editor-title", Static).update(f"编辑：{self.path.name}")
        self.query_one("#artifact-editor-text", TextArea).load_text(str(model["text"]))
        self.query_one("#artifact-editor-status", Static).update(str(model["validation_error"] or ""))
        self.display = True

    def save_current(self) -> ArtifactSaveResult:
        if self.path is None:
            return ArtifactSaveResult(path=Path(""), saved=False, message="当前没有正在编辑的产物", validation_error="当前没有正在编辑的产物")
        result = self.presenter.save_text(self.path, self.query_one("#artifact-editor-text", TextArea).text)
        self.query_one("#artifact-editor-status", Static).update(result.message if result.saved else result.validation_error)
        return result


class DecisionPanelWidget(Vertical, can_focus=True):
    DEFAULT_CSS = """
    DecisionPanelWidget {
        height: auto;
        border-top: solid $warning;
        padding: 0 1;
        background: $surface;
    }
    """

    class Selected(Message):
        def __init__(self, action: DecisionAction) -> None:
            self.action = action
            super().__init__()

    def __init__(self, panel: DecisionPanel, *, id: str | None = None) -> None:
        super().__init__(id=id)
        self.panel = panel
        self.selected_index = 0

    def compose(self) -> ComposeResult:
        yield Static(self.render_panel(), id="decision-panel-body")

    def on_key(self, event: events.Key) -> None:
        if event.key in {"up", "k"}:
            event.stop()
            self.selected_index = max(0, self.selected_index - 1)
            self._refresh()
            return
        if event.key in {"down", "j"}:
            event.stop()
            self.selected_index = min(len(self.panel.options) - 1, self.selected_index + 1)
            self._refresh()
            return
        if event.key == "enter":
            event.stop()
            self.post_message(self.Selected(self.panel.choose(self.panel.options[self.selected_index].key)))
            return
        if event.character:
            for index, option in enumerate(self.panel.options):
                if event.character.lower() == option.key.lower():
                    event.stop()
                    self.selected_index = index
                    self._refresh()
                    self.post_message(self.Selected(self.panel.choose(option.key)))
                    return

    def _refresh(self) -> None:
        self.query_one("#decision-panel-body", Static).update(self.render_panel())

    def set_panel(self, panel: DecisionPanel) -> None:
        self.panel = panel
        self.selected_index = 0
        self._refresh()

    def render_panel(self) -> str:
        lines = [self.panel.title]
        if self.panel.summary:
            lines.extend(["", self.panel.summary])
        lines.append("")
        for index, option in enumerate(self.panel.options):
            prefix = ">" if index == self.selected_index else " "
            lines.append(f"{prefix} [{option.key}] {option.label} -> {option.next_status} · action={option.workflow_action}")
        return "\n".join(lines)


class CommandPalette(ModalScreen[CommandInvocation | None]):
    DEFAULT_CSS = """
    CommandPalette {
        align: center middle;
    }

    #command-palette {
        width: 76;
        max-width: 90%;
        height: auto;
        max-height: 80%;
        border: tall $accent;
        background: $surface;
        padding: 1 2;
    }

    #command-list {
        height: auto;
        max-height: 18;
        margin-top: 1;
    }

    #command-footer {
        margin-top: 1;
        color: $text-muted;
    }
    """

    KEYWORDS = {
        "zhuangtai": "status",
        "状态": "status",
        "粗读": "read",
        "精读": "close-read",
        "查询": "query-close-read",
        "精读产物": "query-close-read",
        "续写": "writer",
        "保存": "save",
        "确认": "confirm",
    }

    def __init__(self, *, router: CommandRouter, context: CommandContext) -> None:
        super().__init__()
        self.router = router
        self.context = context
        self.visible_commands: list[CommandSpec] = []

    def compose(self) -> ComposeResult:
        with Container(id="command-palette"):
            yield Static("命令面板", id="command-title")
            yield Input(placeholder="搜索命令，支持 /writer、续写、状态", id="command-search")
            yield Static("", id="command-list")
            yield Static("Enter 执行 · Esc 关闭 · Tab / Shift+Tab 切换焦点", id="command-footer")

    def on_mount(self) -> None:
        self.query_one("#command-search", Input).focus()
        self.refresh_commands("")

    def on_input_changed(self, event: Input.Changed) -> None:
        if event.input.id == "command-search":
            self.refresh_commands(event.value)

    def on_key(self, event: events.Key) -> None:
        if event.key == "escape":
            event.stop()
            self.dismiss(None)
            return
        if event.key == "enter":
            event.stop()
            if self.visible_commands:
                command = self.visible_commands[0]
                self.dismiss(CommandInvocation(command.command_id, command.handler_name))

    def refresh_commands(self, query: str) -> None:
        normalized = query.strip().lower()
        keyword = self.KEYWORDS.get(normalized, normalized)
        rows: list[str] = []
        self.visible_commands = []
        for command, available, reason in self.router.commands_with_availability(self.context):
            haystack = f"{command.command_id} {command.label} {command.group}".lower()
            if keyword and keyword not in haystack:
                continue
            marker = "" if available else "（当前不可用：{reason}）".format(reason=reason)
            rows.append(f"{command.group} · /{command.command_id}  {command.label}{marker}")
            if available:
                self.visible_commands.append(command)
        self.query_one("#command-list", Static).update("\n".join(rows) or "没有匹配命令。")


class TechnicalDetailsOverlay(ModalScreen[None]):
    DEFAULT_CSS = """
    TechnicalDetailsOverlay {
        align: center middle;
    }

    #technical-details {
        width: 82;
        max-width: 92%;
        max-height: 80%;
        border: tall $secondary;
        background: $surface;
        padding: 1 2;
    }
    """

    def __init__(self, details: str) -> None:
        super().__init__()
        self.details = details

    def compose(self) -> ComposeResult:
        with Container(id="technical-details"):
            yield Static("技术详情")
            yield Static(self.details or "暂无技术详情。")
            yield Static("Esc 关闭")

    def on_key(self, event: events.Key) -> None:
        if event.key == "escape":
            event.stop()
            self.dismiss(None)


class StatusOverlay(ModalScreen[None]):
    DEFAULT_CSS = """
    StatusOverlay {
        align: center middle;
    }

    #status-overlay {
        width: 60;
        max-width: 92%;
        border: tall $secondary;
        background: $surface;
        padding: 1 2;
    }
    """

    def __init__(self, status_text: str) -> None:
        super().__init__()
        self.status_text = status_text

    def compose(self) -> ComposeResult:
        with Container(id="status-overlay"):
            yield Static("状态侧栏")
            yield Static(self.status_text)
            yield Static("Esc 关闭")

    def on_key(self, event: events.Key) -> None:
        if event.key == "escape":
            event.stop()
            self.dismiss(None)

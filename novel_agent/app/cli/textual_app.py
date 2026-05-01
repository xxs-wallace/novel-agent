from __future__ import annotations

from pathlib import Path

from textual.app import App

from .app import TuiApp, TuiSessionConfig
from .router import CommandContext, CommandRouter
from .textual_screens import HomeScreen, WorkbenchScreen
from .textual_widgets import CommandPalette, StatusOverlay, TechnicalDetailsOverlay


class TextualNovelAgentApp(App[None]):
    """Formal full-screen Textual entry for Novel Agent."""

    TITLE = "Novel Agent"
    CSS = """
    $surface: #15181d;
    $panel: #1e232b;
    $success: #3a8f5a;
    $warning: #d7a443;
    $error: #c85c5c;

    Screen {
        background: $surface;
        color: $text;
    }

    Header {
        background: $primary 30%;
    }

    Footer {
        background: $panel;
    }

    .user-message {
        border-left: solid $accent;
    }

    .progress-message {
        border-left: solid $primary;
    }

    .tool-message {
        border-left: solid $secondary;
    }

    .artifact-message {
        border-left: solid $warning;
    }

    .error-message {
        border-left: solid $error;
    }
    """

    BINDINGS = [
        ("ctrl+p", "command_palette", "命令面板"),
        ("ctrl+s", "save_artifact", "保存"),
        ("ctrl+enter", "confirm", "确认"),
        ("ctrl+o", "open_artifact", "打开产物"),
        ("ctrl+d", "toggle_details", "技术详情"),
        ("ctrl+l", "toggle_logs", "日志"),
        ("tab", "focus_next", "切换焦点"),
        ("shift+tab", "focus_previous", "反向切换"),
        ("escape", "escape", "关闭/暂停"),
    ]

    def __init__(self, *, repo_root: Path, session: TuiApp | None = None) -> None:
        super().__init__()
        self.repo_root = repo_root.expanduser().resolve()
        self.command_router = CommandRouter()
        self.session = session or TuiApp(
            repo_root=self.repo_root,
            config=TuiSessionConfig(project=self.repo_root.name),
            command_router=self.command_router,
        )

    def on_mount(self) -> None:
        self.push_screen(HomeScreen())

    def open_workbench(
        self,
        *,
        initial_command: str = "",
        intent_text: str = "",
        initial_status: str = "",
    ) -> None:
        self.switch_screen(
            WorkbenchScreen(
                session=self.session,
                initial_command=initial_command,
                intent_text=intent_text,
                initial_status=initial_status,
            )
        )

    def action_command_palette(self) -> None:
        self.push_screen(
            CommandPalette(
                router=self.command_router,
                context=self._command_context(),
            ),
            self._handle_palette_result,
        )

    def action_save_artifact(self) -> None:
        workbench = self._workbench()
        if workbench:
            workbench.save_current_artifact()

    def action_confirm(self) -> None:
        workbench = self._workbench()
        if workbench:
            workbench.confirm_current_step()

    def action_open_artifact(self) -> None:
        workbench = self._workbench()
        if workbench:
            workbench.open_current_artifact()

    def action_toggle_details(self) -> None:
        workbench = self._workbench()
        if not workbench:
            return
        if self.size.width < 82:
            self.push_screen(StatusOverlay(self.session.render_status_sidebar()))
            return
        self.push_screen(TechnicalDetailsOverlay(workbench.technical_details_text()))

    def action_toggle_logs(self) -> None:
        workbench = self._workbench()
        if workbench:
            workbench.toggle_logs()

    def action_escape(self) -> None:
        workbench = self._workbench()
        if workbench and workbench.running_worker_name:
            workbench.request_stop_worker()

    def _handle_palette_result(self, invocation) -> None:  # type: ignore[no-untyped-def]
        if invocation is None:
            return
        workbench = self._workbench()
        if workbench:
            workbench.handle_invocation(invocation)
            return
        self.open_workbench(initial_command=f"/{invocation.command_id}")

    def _workbench(self) -> WorkbenchScreen | None:
        return self.screen if isinstance(self.screen, WorkbenchScreen) else None

    def _command_context(self) -> CommandContext:
        workbench = self._workbench()
        if workbench:
            return workbench._command_context()  # noqa: SLF001
        return CommandContext()

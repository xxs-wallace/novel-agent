from __future__ import annotations

from dataclasses import dataclass
from typing import Callable


@dataclass(frozen=True, slots=True)
class CommandContext:
    mode: str = "workbench"
    stage: str = ""
    has_artifact: bool = False
    running: bool = False


@dataclass(frozen=True, slots=True)
class CommandSpec:
    command_id: str
    label: str
    group: str
    handler_name: str
    aliases: tuple[str, ...] = ()
    predicate: Callable[[CommandContext], bool] = lambda _context: True


@dataclass(frozen=True, slots=True)
class CommandInvocation:
    command_id: str
    handler_name: str
    args: tuple[str, ...] = ()


class CommandRouter:
    """Routes slash commands and command-palette actions to facade handler names."""

    def __init__(self, commands: list[CommandSpec] | None = None) -> None:
        self._commands = commands or self._default_commands()

    def parse(self, raw: str, context: CommandContext | None = None) -> CommandInvocation:
        context = context or CommandContext()
        text = raw.strip()
        if not text:
            raise ValueError("请输入命令。")
        if text == "\x10":
            return CommandInvocation("palette", "show_command_palette")
        parts = text.split()
        command_name = parts[0][1:] if parts[0].startswith("/") else parts[0]
        command_name = command_name.strip().lower()
        for command in self.available_commands(context):
            names = {command.command_id, *command.aliases}
            if command_name in names:
                return CommandInvocation(command.command_id, command.handler_name, tuple(parts[1:]))
        raise ValueError(f"未知或当前不可用的命令：/{command_name}")

    def available_commands(self, context: CommandContext | None = None) -> list[CommandSpec]:
        context = context or CommandContext()
        return [command for command in self._commands if command.predicate(context)]

    def commands_with_availability(self, context: CommandContext | None = None) -> list[tuple[CommandSpec, bool, str]]:
        context = context or CommandContext()
        return [
            (command, command.predicate(context), self._unavailable_reason(command, context))
            for command in self._commands
        ]

    def command_panel(self, context: CommandContext | None = None) -> dict[str, list[CommandSpec]]:
        groups: dict[str, list[CommandSpec]] = {}
        for command in self.available_commands(context):
            groups.setdefault(command.group, []).append(command)
        return groups

    def render_panel(self, context: CommandContext | None = None) -> str:
        lines: list[str] = []
        for group, commands in self.command_panel(context).items():
            lines.append(group)
            lines.extend(f"  /{command.command_id}  {command.label}" for command in commands)
        return "\n".join(lines)

    @staticmethod
    def _unavailable_reason(command: CommandSpec, context: CommandContext) -> str:
        if command.command_id in {"artifacts", "open", "save"} and not context.has_artifact:
            return "当前没有打开的产物"
        if command.command_id in {"confirm", "back"} and context.running:
            return "后台任务运行中"
        if command.command_id == "confirm" and not context.stage:
            return "当前没有待确认步骤"
        if command.command_id == "back" and context.mode != "writer":
            return "仅 Writer 审阅流程可返回上一层"
        return "当前上下文不适用"

    @staticmethod
    def _default_commands() -> list[CommandSpec]:
        return [
            CommandSpec("status", "查看当前项目建模、知识库与 Writer 状态", "当前步骤推荐动作", "show_status"),
            CommandSpec("tasks", "列出所有任务及导入原文/阅读进度", "当前步骤推荐动作", "list_tasks"),
            CommandSpec("task", "进入指定 task id", "当前步骤推荐动作", "select_task", aliases=("use-task",)),
            CommandSpec("new-task", "创建新任务并记录原文路径", "当前步骤推荐动作", "create_task", aliases=("create-task",)),
            CommandSpec(
                "delete-task",
                "删除任务及本地建模产物；先预览，带 --yes 才执行",
                "当前步骤推荐动作",
                "delete_task",
                aliases=("rm-task", "remove-task"),
            ),
            CommandSpec(
                "reset-close-read",
                "清空当前任务的阅读进度并允许重做",
                "read pipeline",
                "reset_close_read",
                aliases=("clear-close-read", "reset-closeread"),
            ),
            CommandSpec("read", "导入或继续原文；/read --all 完整导入原文、阅读并更新 KB", "read pipeline", "start_read"),
            CommandSpec(
                "close-read",
                "开始阅读；用法 /close-read [source_path] [--batches N] [--document-kb KB]，默认跑完全部剩余已导入 documents",
                "read pipeline",
                "start_close_read",
                aliases=("closeread",),
            ),
            CommandSpec(
                "query-close-read",
                "查看阅读产物：summary、character、outline、source_arc",
                "read pipeline",
                "query_close_read",
                aliases=("query", "close-read-query", "inspect-close-read"),
            ),
            CommandSpec(
                "analyze",
                "和只读 Analyzer 讨论当前小说大纲与剧情合理性",
                "Analyzer",
                "analyze_outline",
                aliases=("analyzer", "outline-analyzer"),
            ),
            CommandSpec("kb", "构建或查看 Creative KB", "read pipeline", "build_creative_kb"),
            CommandSpec(
                "benchmark",
                "运行端到端 Agentic benchmark：/benchmark longzu-32kb 或 /benchmark --source novel_agent/tests/longzu_32kb.txt",
                "debug",
                "run_smoke_benchmark",
                aliases=("bench", "smoke-benchmark"),
            ),
            CommandSpec(
                "creative-kb-benchmark",
                "运行 Creative KB Benchmark：/creative-kb-benchmark longzu-32kb [--writer-ab]",
                "debug",
                "run_creative_kb_benchmark",
                aliases=("kb-benchmark", "creative-kb-bench"),
            ),
            CommandSpec("writer", "开始或恢复 Writer 分层生成", "Writer", "start_writer"),
            CommandSpec("resume", "恢复最近一次未完成流程", "Writer", "resume"),
            CommandSpec(
                "artifacts",
                "查看当前会话产物",
                "artifact",
                "list_artifacts",
                predicate=lambda context: context.has_artifact,
            ),
            CommandSpec(
                "open",
                "打开当前重点产物",
                "artifact",
                "open_artifact",
                predicate=lambda context: context.has_artifact,
            ),
            CommandSpec(
                "save",
                "保存当前 artifact 编辑内容",
                "artifact",
                "save_artifact",
                predicate=lambda context: context.has_artifact,
            ),
            CommandSpec(
                "confirm",
                "确认当前审阅步骤",
                "当前步骤推荐动作",
                "confirm_current_step",
                predicate=lambda context: bool(context.stage) and not context.running,
            ),
            CommandSpec(
                "back",
                "返回上一层可修改节点",
                "当前步骤推荐动作",
                "go_back",
                predicate=lambda context: context.mode == "writer" and not context.running,
            ),
            CommandSpec("help", "查看当前上下文可用操作", "配置", "show_help"),
            CommandSpec("palette", "打开命令面板", "配置", "show_command_palette", aliases=("ctrl+p",)),
            CommandSpec("debug", "查看技术详情", "debug", "show_debug_details"),
        ]

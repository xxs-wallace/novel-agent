from __future__ import annotations

import json
import os
import re
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol


class GuiRunCommand(Protocol):
    def command(self) -> list[str]: ...

    def environment(self) -> dict[str, str]: ...

    def stdin_payload(self) -> bytes: ...

    def validate_runtime(self) -> None: ...

    def working_directory(self) -> Path: ...


def _resolve_python(repo_root: Path, python_executable: Path | None = None) -> Path:
    if python_executable is not None:
        return python_executable.expanduser().absolute()
    venv_python = repo_root / ".venv" / "bin" / "python"
    if venv_python.exists():
        return venv_python.absolute()
    return Path(sys.executable).absolute()


def _base_environment(repo_root: Path, api_key: str = "") -> dict[str, str]:
    resolved_repo_root = repo_root.expanduser().resolve()
    python_path_parts = [str(resolved_repo_root), str(resolved_repo_root / "src")]
    existing_pythonpath = os.environ.get("PYTHONPATH", "")
    if existing_pythonpath:
        python_path_parts.append(existing_pythonpath)

    env = dict(os.environ)
    env["PYTHONPATH"] = os.pathsep.join(python_path_parts)
    env["NOVEL_AGENT_REPO_ROOT"] = str(resolved_repo_root)
    if api_key.strip():
        env["DEEPSEEK_API_KEY"] = api_key.strip()
    return env


def _validate_python_runtime(
    *,
    python_executable: Path,
    repo_root: Path,
    env: dict[str, str],
    modules: list[str],
) -> None:
    probe = "\n".join([f"import {module}" for module in modules])
    result = subprocess.run(
        [str(python_executable), "-c", probe],
        cwd=str(repo_root),
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode != 0:
        details = (result.stderr or result.stdout).strip()
        raise RuntimeError(
            "当前 Python 执行器缺少运行依赖。请先运行："
            "python -m pip install -e '.[gui]'，或确认项目 .venv 已安装必要依赖。\n\n"
            f"执行器：{python_executable}\n{details}"
        )


@dataclass(frozen=True)
class PipelineRunConfig:
    """Configuration collected by the GUI for the existing interactive pipeline."""

    repo_root: Path
    task_name: str
    source_path: Path
    run_mode: str = "fresh"
    max_read_kb: int = 50
    max_close_batches: int = 12
    segment_step_kb: int = 32
    close_step_batches: int = 1
    build_creative_kb: bool = True
    api_key: str = ""
    python_executable: Path | None = None

    def validate(self) -> None:
        if not self.task_name.strip():
            raise ValueError("任务名称不能为空。")
        if self.run_mode not in {"fresh", "resume"}:
            raise ValueError("运行模式必须是 fresh 或 resume。")
        if self.max_read_kb < 1:
            raise ValueError("导入原文 KB 必须大于 0。")
        if self.max_close_batches < 1:
            raise ValueError("阅读轮数必须大于 0。")
        if self.segment_step_kb < 1:
            raise ValueError("导入原文步长必须大于 0。")
        if self.close_step_batches < 1:
            raise ValueError("阅读步长必须大于 0。")
        if not self.source_path.expanduser().exists():
            raise ValueError(f"小说路径不存在：{self.source_path}")

    @property
    def resolved_python(self) -> Path:
        return _resolve_python(self.repo_root, self.python_executable)


class InteractivePipelineCommand:
    """Builds the subprocess invocation and stdin script for run_interactive.py."""

    def __init__(self, config: PipelineRunConfig) -> None:
        self.config = config

    def command(self) -> list[str]:
        return [str(self.config.resolved_python), "-m", "novel_agent.app.run_interactive"]

    def validate_runtime(self) -> None:
        _validate_python_runtime(
            python_executable=self.config.resolved_python,
            repo_root=self.config.repo_root,
            env=self.environment(),
            modules=["PIL.Image", "smolagents", "novel_agent.app.run_interactive"],
        )

    def environment(self) -> dict[str, str]:
        return _base_environment(self.config.repo_root, self.config.api_key)

    def working_directory(self) -> Path:
        return self.config.repo_root

    def stdin_payload(self) -> bytes:
        self.config.validate()
        answers = [
            "pipeline",
            self.config.task_name.strip(),
            str(self.config.source_path.expanduser().resolve()),
            self.config.run_mode,
            str(self.config.max_read_kb),
            str(self.config.max_close_batches),
            str(self.config.segment_step_kb),
            str(self.config.close_step_batches),
            "y" if self.config.build_creative_kb else "n",
        ]
        return ("\n".join(answers) + "\n").encode("utf-8")


@dataclass(frozen=True)
class WriterRunConfig:
    repo_root: Path
    task_name: str
    dry_run: bool = True
    api_key: str = ""
    product_mode: str = "assist"
    action: str = "guided"
    run_id: str = ""
    major_characters: str = ""
    desired_actions: str = ""
    avoidances: str = ""
    preferred_outcome: str = ""
    notes: str = ""
    user_world_notes: str = ""
    target_chapter_count: int = 3
    chapter_count: int = 3
    chapter_id: str = ""
    allow_incomplete_modeling: bool = True
    execute_chapter: bool = False
    reset_writer_memory: bool = False
    python_executable: Path | None = None

    def validate(self) -> None:
        if not self.task_name.strip():
            raise ValueError("Writer 任务名称不能为空。")
        if self.product_mode not in {"assist", "batch", "auto_novel"}:
            raise ValueError("产品模式无效。")
        if self.action not in {
            "guided",
            "initialize",
            "prepare_planning",
            "resume",
            "prepare_chapter_length_plan",
            "continue_after_length_review",
            "prepare_execution",
            "continue_after_planning_review",
            "prepare_batch_plan",
            "continue_after_batch_review",
            "prepare_chapter_package",
            "continue_after_chapter_review",
            "continue_after_execution_review",
            "execute_current_chapter",
            "accept_chapter",
            "revise_chapter_length",
            "replan_chapter",
            "discard_chapter",
            "approve_writeback",
        }:
            raise ValueError("Writer 动作无效。")
        if self.target_chapter_count < 1:
            raise ValueError("批次章节数必须大于 0。")
        if self.chapter_count < 1:
            raise ValueError("章节梗概数必须大于 0。")
        if not self.dry_run and not self.api_key.strip() and not os.getenv("DEEPSEEK_API_KEY"):
            raise ValueError("非 dry-run Writer 模式需要 DeepSeek API Key。")
        if self.action in {
            "continue_after_planning_review",
            "prepare_batch_plan",
            "continue_after_batch_review",
            "prepare_chapter_package",
            "continue_after_chapter_review",
            "continue_after_length_review",
            "continue_after_execution_review",
            "execute_current_chapter",
            "accept_chapter",
            "revise_chapter_length",
            "replan_chapter",
            "discard_chapter",
            "approve_writeback",
        } and not self.run_id.strip():
            raise ValueError("该状态机动作需要填写 run_id。")

    @property
    def resolved_python(self) -> Path:
        return _resolve_python(self.repo_root, self.python_executable)


class WriterWorkflowCommand:
    def __init__(self, config: WriterRunConfig) -> None:
        self.config = config

    def command(self) -> list[str]:
        return [str(self.config.resolved_python), "-m", "novel_agent.app.gui.writer_cli"]

    def validate_runtime(self) -> None:
        _validate_python_runtime(
            python_executable=self.config.resolved_python,
            repo_root=self.config.repo_root,
            env=self.environment(),
            modules=["PIL.Image", "smolagents", "novel_agent.app.gui.writer_cli"],
        )

    def environment(self) -> dict[str, str]:
        return _base_environment(self.config.repo_root, self.config.api_key)

    def working_directory(self) -> Path:
        return self.config.repo_root

    def stdin_payload(self) -> bytes:
        self.config.validate()
        payload = {
            "repo_root": str(self.config.repo_root.expanduser().resolve()),
            "task_name": self.config.task_name.strip(),
            "dry_run": self.config.dry_run,
            "api_key": self.config.api_key.strip(),
            "product_mode": self.config.product_mode,
            "action": self.config.action,
            "run_id": self.config.run_id.strip(),
            "intent_payload": {
                "major_characters": _split_csv(self.config.major_characters),
                "desired_actions": _split_csv(self.config.desired_actions),
                "avoidances": _split_csv(self.config.avoidances),
                "preferred_outcome": self.config.preferred_outcome.strip(),
                "notes": self.config.notes.strip(),
            },
            "user_world_notes": self.config.user_world_notes.strip(),
            "target_chapter_count": self.config.target_chapter_count,
            "chapter_count": self.config.chapter_count,
            "chapter_id": self.config.chapter_id.strip(),
            "allow_incomplete_modeling": self.config.allow_incomplete_modeling,
            "execute_chapter": self.config.execute_chapter,
            "reset_writer_memory": self.config.reset_writer_memory,
        }
        return json.dumps(payload, ensure_ascii=False).encode("utf-8")


def _split_csv(value: str) -> list[str]:
    return [item.strip() for item in re.split(r"[,，;；\n]+", value) if item.strip()]

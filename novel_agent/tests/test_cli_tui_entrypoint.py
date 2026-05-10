from __future__ import annotations

from pathlib import Path

import tomllib

from novel_agent.app import cli_tui


def test_novel_agent_project_script_points_to_textual_entrypoint() -> None:
    pyproject = tomllib.loads(Path("pyproject.toml").read_text(encoding="utf-8"))

    assert pyproject["project"]["scripts"]["novel-agent"] == "cli.novel_agent:main"
    assert "textual>=0.89.0" in pyproject["project"]["dependencies"]


def test_root_launcher_bootstraps_venv_and_starts_textual_entrypoint() -> None:
    launcher = Path("novel-agent")
    script = launcher.read_text(encoding="utf-8")

    assert launcher.exists()
    assert launcher.stat().st_mode & 0o111
    assert '-m venv "$VENV_DIR"' in script
    assert 'pip install -e "$REPO_ROOT[openai]" PyYAML' in script
    assert '-m novel_agent.app.cli_tui "$@"' in script
    assert "run_interactive" not in script


def test_cli_design_declares_textual_as_formal_tui() -> None:
    design = Path(".trae/specs/cli-interface/design.md").read_text(encoding="utf-8")

    assert "正式用户入口 SHALL 通过项目脚本启动" in design
    assert "./novel-agent" in design
    assert "自动创建或复用 `.venv`" in design
    assert "novel-agent" in design
    assert "正式 TUI 框架选型为 Textual" in design
    assert "`run_interactive.py` 中的 `_prompt_text()`" in design


def test_cli_tui_dispatches_creative_kb_benchmark_subcommand(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    captured: dict[str, object] = {}

    def _fake_main(argv):  # type: ignore[no-untyped-def]
        captured["argv"] = list(argv)
        return 0

    monkeypatch.setattr("novel_agent.app.run_creative_kb_benchmark.main", _fake_main)

    exit_code = cli_tui.main(["creative-kb-benchmark", "--dry-run-model", "--run-id", "kb-run"])

    assert exit_code == 0
    assert captured["argv"] == ["--dry-run-model", "--run-id", "kb-run"]

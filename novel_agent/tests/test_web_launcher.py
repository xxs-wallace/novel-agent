from __future__ import annotations

import sys
from pathlib import Path

from novel_agent.app.web.launcher import DependencyInspector, LauncherConfig, WebWorkbenchLauncher


def test_web_launcher_builds_backend_and_frontend_commands(tmp_path: Path) -> None:
    web_dir = tmp_path / "web"
    web_dir.mkdir()
    (web_dir / "package.json").write_text("{}", encoding="utf-8")

    config = LauncherConfig(
        repo_root=tmp_path,
        api_host="127.0.0.1",
        api_port=8100,
        web_host="0.0.0.0",
        web_port=5179,
        open_browser=False,
    )
    launcher = WebWorkbenchLauncher(config)

    assert launcher.backend_command() == [
        sys.executable,
        "-m",
        "uvicorn",
        "novel_agent.app.web.main:app",
        "--host",
        "127.0.0.1",
        "--port",
        "8100",
    ]
    assert launcher.frontend_command() == [
        "npm",
        "run",
        "dev",
        "--",
        "--host",
        "0.0.0.0",
        "--port",
        "5179",
    ]
    assert launcher.backend_environment()["NOVEL_AGENT_REPO_ROOT"] == str(tmp_path)
    assert launcher.frontend_environment()["VITE_API_PROXY_TARGET"] == "http://127.0.0.1:8100"


def test_dependency_inspector_reports_missing_node_and_npm(tmp_path: Path) -> None:
    web_dir = tmp_path / "web"
    web_dir.mkdir()
    (web_dir / "package.json").write_text("{}", encoding="utf-8")
    config = LauncherConfig(repo_root=tmp_path, open_browser=False)

    inspector = DependencyInspector(
        config,
        which=lambda _name: None,
        import_module=lambda _name: object(),
    )

    issues = inspector.inspect()

    assert any("node" in issue.message for issue in issues if issue.fatal)
    assert any("npm" in issue.message for issue in issues if issue.fatal)


def test_dependency_inspector_warns_when_deepseek_key_is_missing(tmp_path: Path, monkeypatch) -> None:  # type: ignore[no-untyped-def]
    web_dir = tmp_path / "web"
    web_dir.mkdir()
    (web_dir / "package.json").write_text("{}", encoding="utf-8")
    monkeypatch.delenv("DEEPSEEK_API_KEY", raising=False)
    config = LauncherConfig(repo_root=tmp_path, open_browser=False)

    inspector = DependencyInspector(
        config,
        which=lambda _name: "/usr/bin/tool",
        import_module=lambda _name: object(),
    )

    issues = inspector.inspect()

    assert any("DEEPSEEK_API_KEY" in issue.message and not issue.fatal for issue in issues)

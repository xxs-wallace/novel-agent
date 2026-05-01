from __future__ import annotations

import subprocess
import sys
from pathlib import Path


def test_novel_agent_importable():
    import novel_agent  # noqa: F401


def test_run_continue_scene_help():
    repo_root = Path(__file__).resolve().parents[1]
    result = subprocess.run(
        [sys.executable, "-m", "novel_agent.app.run_continue_scene", "--help"],
        cwd=repo_root,
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0
    assert "Continue a novel scene" in result.stdout


def test_run_continue_scene_dry_run_writes_config(tmp_path: Path):
    repo_root = Path(__file__).resolve().parents[1]
    runs_dir = tmp_path / "runs"
    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "novel_agent.app.run_continue_scene",
            "hello",
            "--dry-run",
            "--runs-dir",
            str(runs_dir),
        ],
        cwd=repo_root,
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0
    assert (runs_dir / "current").exists()
    run_id = (runs_dir / "current").read_text(encoding="utf-8").strip()
    assert run_id
    assert (runs_dir / run_id / "config.json").exists()

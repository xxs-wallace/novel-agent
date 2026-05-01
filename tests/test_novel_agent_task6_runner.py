from __future__ import annotations

import os
import sqlite3
import subprocess
import sys
from pathlib import Path

import pytest

from novel_agent.indexes import build_index


def _fts5_available() -> bool:
    try:
        conn = sqlite3.connect(":memory:")
        conn.execute("CREATE VIRTUAL TABLE t USING fts5(content)")
        conn.close()
        return True
    except sqlite3.OperationalError:
        return False


@pytest.mark.skipif(not _fts5_available(), reason="SQLite FTS5 unavailable in this Python build")
def test_run_mvp_dry_run_writes_scene_plan_and_continuity_report(tmp_path: Path):
    repo_root = tmp_path / "repo"
    (repo_root / "longzu_split").mkdir(parents=True, exist_ok=True)
    (repo_root / "analysis").mkdir(parents=True, exist_ok=True)

    (repo_root / "longzu_split" / "seg_001.md").write_text("# S1\n\n战争的阴影逼近。\n", encoding="utf-8")
    (repo_root / "longzu_split" / "seg_002.md").write_text("# S2\n\n张三沉默，李四握紧刀柄。\n", encoding="utf-8")
    (repo_root / "longzu_split" / "seg_003.md").write_text("# S3\n\n城门外传来号角。\n", encoding="utf-8")
    (repo_root / "analysis" / "lore.md").write_text("# 设定\n\n神器名为青铜钥。\n", encoding="utf-8")

    db_path = tmp_path / "novel.db"
    build_index(db_path=db_path, repo_root=repo_root, rebuild=True)

    runs_dir = tmp_path / "runs"
    env = os.environ.copy()
    env["NOVEL_AGENT_REPO_ROOT"] = str(repo_root)
    env["NOVEL_AGENT_INDEX_DB"] = str(db_path)

    project_root = Path(__file__).resolve().parents[1]
    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "novel_agent.app.run_mvp",
            "--anchor-path",
            "longzu_split/seg_002.md",
            "--goal",
            "战争升级，必须写到青铜钥",
            "--lore-keywords",
            "青铜钥",
            "--runs-dir",
            str(runs_dir),
            "--dry-run",
        ],
        cwd=project_root,
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr
    run_id = (runs_dir / "current").read_text(encoding="utf-8").strip()
    assert run_id
    run_dir = runs_dir / run_id
    assert (run_dir / "scene_plan.json").exists()
    assert (run_dir / "continuity_report.json").exists()

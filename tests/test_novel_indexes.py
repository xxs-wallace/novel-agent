from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest

from novel_agent.indexes import build_index, search_documents


def _fts5_available() -> bool:
    try:
        conn = sqlite3.connect(":memory:")
        conn.execute("CREATE VIRTUAL TABLE t USING fts5(content)")
        conn.close()
        return True
    except sqlite3.OperationalError:
        return False


@pytest.mark.skipif(not _fts5_available(), reason="SQLite FTS5 unavailable in this Python build")
def test_build_and_search_tmp_db(tmp_path: Path):
    repo_root = tmp_path
    (repo_root / "longzu_split").mkdir(parents=True, exist_ok=True)
    (repo_root / "analysis").mkdir(parents=True, exist_ok=True)

    (repo_root / "longzu_split" / "seg_001.md").write_text(
        "# Segment One\n\n龙族的故事开始于这里。\n", encoding="utf-8"
    )
    (repo_root / "analysis" / "note.md").write_text("# Analysis Note\n\n这里有一些分析内容。\n", encoding="utf-8")

    db_path = tmp_path / "novel.db"
    build_index(db_path=db_path, repo_root=repo_root, rebuild=True)
    hits = search_documents(db_path, "龙族", limit=5)
    assert len(hits) >= 1
    assert any("longzu_split/seg_001.md" in h.path for h in hits)

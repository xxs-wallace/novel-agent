from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest

from novel_agent.indexes import build_index
from novel_agent.tools.task4_retrieval_tools import (
    ReadAnchorContextTool,
    SearchByCharacterTool,
    SearchByTimelineTool,
    SearchLoreTool,
)


def _fts5_available() -> bool:
    try:
        conn = sqlite3.connect(":memory:")
        conn.execute("CREATE VIRTUAL TABLE t USING fts5(content)")
        conn.close()
        return True
    except sqlite3.OperationalError:
        return False


@pytest.mark.skipif(not _fts5_available(), reason="SQLite FTS5 unavailable in this Python build")
def test_read_anchor_context_success(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    repo_root = tmp_path
    (repo_root / "longzu_split").mkdir(parents=True, exist_ok=True)
    (repo_root / "analysis").mkdir(parents=True, exist_ok=True)

    (repo_root / "longzu_split" / "seg_001.md").write_text("# S1\n\n第一段。\n", encoding="utf-8")
    (repo_root / "longzu_split" / "seg_002.md").write_text("# S2\n\n第二段。\n", encoding="utf-8")
    (repo_root / "longzu_split" / "seg_003.md").write_text("# S3\n\n第三段。\n", encoding="utf-8")

    db_path = tmp_path / "novel.db"
    build_index(db_path=db_path, repo_root=repo_root, rebuild=True)

    monkeypatch.setenv("NOVEL_AGENT_REPO_ROOT", str(repo_root))
    monkeypatch.setenv("NOVEL_AGENT_INDEX_DB", str(db_path))

    tool = ReadAnchorContextTool()
    result = tool(segment_path="longzu_split/seg_002.md", window_before=1, window_after=1)
    assert result["ok"] is True
    assert "第一段" in result["output"]["content"]
    assert "第三段" in result["output"]["content"]
    assert isinstance(result["sources"], list)
    assert len(result["sources"]) == 3
    assert all("path" in s and "scope" in s and "snippet" in s for s in result["sources"])


@pytest.mark.skipif(not _fts5_available(), reason="SQLite FTS5 unavailable in this Python build")
def test_search_by_character_alias_extraction_success(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    repo_root = tmp_path
    (repo_root / "longzu_split").mkdir(parents=True, exist_ok=True)
    (repo_root / "analysis" / "人物档案").mkdir(parents=True, exist_ok=True)

    (repo_root / "analysis" / "人物档案" / "张三.md").write_text(
        "# 张三\n\n别名：阿三，三哥\n\n其他内容。\n", encoding="utf-8"
    )
    (repo_root / "longzu_split" / "seg_001.md").write_text("# S1\n\n阿三出场。\n", encoding="utf-8")

    db_path = tmp_path / "novel.db"
    build_index(db_path=db_path, repo_root=repo_root, rebuild=True)

    monkeypatch.setenv("NOVEL_AGENT_REPO_ROOT", str(repo_root))
    monkeypatch.setenv("NOVEL_AGENT_INDEX_DB", str(db_path))

    tool = SearchByCharacterTool()
    result = tool(name="张三", scope="longzu_split", limit=10)
    assert result["ok"] is True
    assert result["output"]["canonical"] == "张三"
    assert "阿三" in result["output"]["variants"]
    assert any(s["path"] == "longzu_split/seg_001.md" for s in result["sources"])
    assert all("snippet" in s for s in result["sources"])


@pytest.mark.skipif(not _fts5_available(), reason="SQLite FTS5 unavailable in this Python build")
def test_search_lore_success(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    repo_root = tmp_path
    (repo_root / "longzu_split").mkdir(parents=True, exist_ok=True)
    (repo_root / "analysis").mkdir(parents=True, exist_ok=True)

    (repo_root / "analysis" / "lore.md").write_text("# 设定\n\n神器的来历。\n", encoding="utf-8")
    (repo_root / "longzu_split" / "seg_001.md").write_text("# S1\n\n无关内容。\n", encoding="utf-8")

    db_path = tmp_path / "novel.db"
    build_index(db_path=db_path, repo_root=repo_root, rebuild=True)

    monkeypatch.setenv("NOVEL_AGENT_REPO_ROOT", str(repo_root))
    monkeypatch.setenv("NOVEL_AGENT_INDEX_DB", str(db_path))

    tool = SearchLoreTool()
    result = tool(keyword="神器", limit=10)
    assert result["ok"] is True
    assert result["output"]["scope"] == "analysis"
    assert any(s["path"] == "analysis/lore.md" for s in result["sources"])


@pytest.mark.skipif(not _fts5_available(), reason="SQLite FTS5 unavailable in this Python build")
def test_search_by_timeline_range_success(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    repo_root = tmp_path
    (repo_root / "longzu_split").mkdir(parents=True, exist_ok=True)
    (repo_root / "analysis").mkdir(parents=True, exist_ok=True)

    (repo_root / "longzu_split" / "seg_001.md").write_text("# S1\n\n战争开始。\n", encoding="utf-8")
    (repo_root / "longzu_split" / "seg_002.md").write_text("# S2\n\n战争升级。\n", encoding="utf-8")
    (repo_root / "longzu_split" / "seg_003.md").write_text("# S3\n\n战争结束。\n", encoding="utf-8")

    db_path = tmp_path / "novel.db"
    build_index(db_path=db_path, repo_root=repo_root, rebuild=True)

    monkeypatch.setenv("NOVEL_AGENT_REPO_ROOT", str(repo_root))
    monkeypatch.setenv("NOVEL_AGENT_INDEX_DB", str(db_path))

    tool = SearchByTimelineTool()
    result = tool(keyword="战争", start=2, end=3, limit=50)
    assert result["ok"] is True
    paths = [h["path"] for h in result["output"]["hits"]]
    assert paths == ["longzu_split/seg_002.md", "longzu_split/seg_003.md"]
    assert all("path" in s and "scope" in s and "snippet" in s for s in result["sources"])

from __future__ import annotations

import json
from pathlib import Path

from novel_agent.app.query_close_read import main
from novel_agent.app.repos.assets_repo import AssetsRepo
from novel_agent.app.repos.chapters_repo import ChaptersRepo
from novel_agent.app.repos.character_profiles_repo import CharacterProfilesRepo
from novel_agent.app.repos.db import NovelAgentDB


def test_query_close_read_outputs_character_profiles(tmp_path: Path, capsys) -> None:
    db_path = _seed_close_read_outputs(tmp_path, book_id="demo-task")

    assert main(["demo-task", "character", "--repo-root", str(tmp_path), "--db", str(db_path)]) == 0

    output = capsys.readouterr().out
    assert "# 人物档案：demo-task" in output
    assert "## 沈青" in output
    assert "已建档人物" in output


def test_query_close_read_outputs_summary_json_from_default_task_db(tmp_path: Path, capsys) -> None:
    _seed_close_read_outputs(tmp_path, book_id="demo-task")

    assert main(["demo-task", "summary", "--repo-root", str(tmp_path), "--format", "json"]) == 0

    payload = json.loads(capsys.readouterr().out)
    assert payload["type"] == "summary"
    assert payload["book_id"] == "demo-task"
    assert payload["chapters"][0]["chapter_title"] == "第一章 雨夜"
    assert payload["chapters"][0]["summary_short"] == "沈青在雨夜继续追查旧案。"


def test_query_close_read_outputs_single_document_summary(tmp_path: Path, capsys) -> None:
    _seed_close_read_outputs(tmp_path, book_id="demo-task")

    assert main(["demo-task", "summary", "--repo-root", str(tmp_path), "--document-title-index", "2"]) == 0

    output = capsys.readouterr().out
    assert "# 剧情概括：document 2：demo-task" in output
    assert "## [2] 第二章 旧楼" in output
    assert "林白在旧楼找到新的证词" in output
    assert "第一章 雨夜" not in output


def test_query_close_read_outputs_total_summary(tmp_path: Path, capsys) -> None:
    _seed_close_read_outputs(tmp_path, book_id="demo-task")

    assert main(["demo-task", "summary", "--repo-root", str(tmp_path), "--summary-scope", "total"]) == 0

    output = capsys.readouterr().out
    assert "# 当前精读总览：demo-task" in output
    assert "chapter_count: 2" in output
    assert "[1] 第一章 雨夜: 沈青在雨夜继续追查旧案。" in output
    assert "[2] 第二章 旧楼: 林白在旧楼找到新的证词。" in output


def test_query_close_read_outputs_outline_markdown(tmp_path: Path, capsys) -> None:
    db_path = _seed_close_read_outputs(tmp_path, book_id="demo-task")

    assert main(["demo-task", "outline", "--repo-root", str(tmp_path), "--db", str(db_path)]) == 0

    output = capsys.readouterr().out
    assert "# 故事大纲" in output
    assert "旧案调查仍未结束" in output


def test_query_close_read_outputs_source_arc_map(tmp_path: Path, capsys) -> None:
    db_path = _seed_close_read_outputs(tmp_path, book_id="demo-task")
    arcs_dir = tmp_path / ".memory" / "arcs"
    arcs_dir.mkdir(parents=True, exist_ok=True)
    (arcs_dir / "demo-task.source_arc_map.json").write_text(
        json.dumps(
            {
                "book_id": "demo-task",
                "generated_at": "now",
                "source_summary_count": 8,
                "used_compression": True,
                "plot_summary_units": [{"unit_id": "unit-001"}],
                "arcs": [
                    {
                        "source_arc_id": "source-arc-0001",
                        "source_arc_title": "日常关系单元（1-8）",
                        "start_document_title_index": 1,
                        "end_document_title_index": 8,
                        "source_arc_role": "日常关系",
                        "core_events": ["[1] 第一章：关系铺垫"],
                        "pacing_notes": "低冲突但有铺垫价值。",
                    }
                ],
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    assert main(["demo-task", "source_arc", "--repo-root", str(tmp_path), "--db", str(db_path)]) == 0

    output = capsys.readouterr().out
    assert "# Source Arc Map: demo-task" in output
    assert "source-arc-0001" in output
    assert "plot_summary_units: 1" in output


def test_query_close_read_outputs_source_arc_json(tmp_path: Path, capsys) -> None:
    db_path = _seed_close_read_outputs(tmp_path, book_id="demo-task")
    arcs_dir = tmp_path / ".memory" / "arcs"
    arcs_dir.mkdir(parents=True, exist_ok=True)
    (arcs_dir / "demo-task.source_arc_map.json").write_text(
        json.dumps({"book_id": "demo-task", "arcs": []}, ensure_ascii=False),
        encoding="utf-8",
    )

    assert main(["demo-task", "source_arc", "--repo-root", str(tmp_path), "--db", str(db_path), "--format", "json"]) == 0

    payload = json.loads(capsys.readouterr().out)
    assert payload["type"] == "source_arc"
    assert payload["exists"] is True
    assert payload["source_arc_map"]["book_id"] == "demo-task"


def test_query_close_read_returns_error_for_missing_db(tmp_path: Path, capsys) -> None:
    assert main(["missing-task", "summary", "--repo-root", str(tmp_path)]) == 1

    captured = capsys.readouterr()
    assert "close-read sqlite not found" in captured.err


def _seed_close_read_outputs(repo_root: Path, *, book_id: str) -> Path:
    db_path = repo_root / ".indexes" / f"{book_id}.db"
    db = NovelAgentDB(db_path)
    outline_path = repo_root / ".memory" / "outlines" / f"{book_id}.outline.md"
    world_summary_path = repo_root / ".memory" / "worlds" / f"{book_id}.world_summary.md"
    outline_path.parent.mkdir(parents=True, exist_ok=True)
    world_summary_path.parent.mkdir(parents=True, exist_ok=True)
    outline_path.write_text("# 故事大纲\n\n- 旧案调查仍未结束。\n", encoding="utf-8")
    world_summary_path.write_text("# 世界观概要\n", encoding="utf-8")
    with db.connect() as conn:
        db.init_schema(conn)
        AssetsRepo().upsert(
            conn,
            {
                "book_id": book_id,
                "source_root": str(repo_root),
                "world_markdown_path": "",
                "world_summary_path": str(world_summary_path),
                "outline_markdown_path": str(outline_path),
                "toc_markdown": "",
                "toc_source_path": "",
                "debug_export_path": "",
                "created_at": "now",
                "updated_at": "now",
            },
        )
        CharacterProfilesRepo().upsert(
            conn,
            {
                "book_id": book_id,
                "canonical_name": "沈青",
                "aliases": ["阿青"],
                "profile_summary_md": "# 沈青\n\n- 已建档人物。\n",
                "personality": [],
                "occupations": [],
                "age_timeline": [],
                "abilities": [],
                "recent_activity": ["雨夜追查旧案"],
                "relationships": [],
                "chapter_indexes": [1],
                "mentioned_doc_ids": [1],
                "speaking_doc_ids": [1],
                "first_seen_doc_id": 1,
                "last_seen_doc_id": 1,
                "first_seen_title_index": 1,
                "last_seen_title_index": 1,
                "importance_score": 8,
                "profile_version": 1,
                "created_at": "now",
                "updated_at": "now",
            },
        )
        ChaptersRepo().upsert(
            conn,
            {
                "book_id": book_id,
                "document_title_index": 1,
                "chapter_title": "第一章 雨夜",
                "source_doc_start_id": 1,
                "source_doc_end_id": 1,
                "source_doc_count": 1,
                "source_total_chars": 24,
                "summary_intermediate": [],
                "summary_md": "沈青在雨夜继续追查旧案，并意识到背后仍有黑手。",
                "summary_short": "沈青在雨夜继续追查旧案。",
                "importance_score": 72,
                "importance_reason": "承接主线调查。",
                "related_chapters": [],
                "mentioned_characters": ["沈青"],
                "world_update": {},
                "outline_update": {},
                "close_read_run_id": "seed",
                "created_at": "now",
                "updated_at": "now",
            },
        )
        ChaptersRepo().upsert(
            conn,
            {
                "book_id": book_id,
                "document_title_index": 2,
                "chapter_title": "第二章 旧楼",
                "source_doc_start_id": 2,
                "source_doc_end_id": 2,
                "source_doc_count": 1,
                "source_total_chars": 18,
                "summary_intermediate": [],
                "summary_md": "林白在旧楼找到新的证词，并把线索交给沈青。",
                "summary_short": "林白在旧楼找到新的证词。",
                "importance_score": 64,
                "importance_reason": "推进旧案调查。",
                "related_chapters": [],
                "mentioned_characters": ["沈青", "林白"],
                "world_update": {},
                "outline_update": {},
                "close_read_run_id": "seed",
                "created_at": "now",
                "updated_at": "now",
            },
        )
        conn.commit()
    return db_path

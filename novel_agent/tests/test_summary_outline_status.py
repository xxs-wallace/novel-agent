from __future__ import annotations

import json
import sqlite3
from pathlib import Path

from novel_agent.app.repos.assets_repo import AssetsRepo
from novel_agent.app.repos.chapters_repo import ChaptersRepo
from novel_agent.app.repos.character_profiles_repo import CharacterProfilesRepo
from novel_agent.app.repos.db import NovelAgentDB
from novel_agent.app.schemas.orchestration_schema import MemoryAssemblyBudget, MemoryAssemblyInput
from novel_agent.app.services.context_assembly_service import ContextAssemblyService
from novel_agent.app.services.outline_service import OutlineService
from novel_agent.app.services.source_arc_mapping_service import SourceArcMappingService
from novel_agent.app.services.summary_outline_commit_service import SummaryOutlineCommitService
from novel_agent.app.services.world_state_service import WorldStateService


def test_chapters_repo_status_fields_default_and_preserve_committed(tmp_path: Path) -> None:
    db = NovelAgentDB(tmp_path / "memory.db")
    repo = ChaptersRepo()
    with db.connect() as conn:
        db.init_schema(conn)
        repo.upsert(conn, _chapter_payload(book_id="book", index=1, summary="provisional summary"))
        row = repo.get(conn, book_id="book", document_title_index=1)
        assert row is not None
        assert row["summary_status"] == "provisional"
        assert row["outline_status"] == "provisional"

        repo.upsert(
            conn,
            {
                **_chapter_payload(book_id="book", index=1, summary="committed summary"),
                "summary_status": "committed",
                "summary_evidence_window": "1-3",
                "summary_target_range": "1-1",
                "outline_update": {"chapter_line": "[1] committed line", "timeline_events": []},
                "outline_status": "committed",
                "outline_evidence_window": "1-3",
                "outline_target_range": "1-1",
            },
        )
        repo.upsert(conn, _chapter_payload(book_id="book", index=1, summary="new provisional summary"))
        row = repo.get(conn, book_id="book", document_title_index=1)

    assert row is not None
    assert "committed summary" in row["summary_md"]
    assert "new provisional summary" not in row["summary_md"]
    assert row["summary_status"] == "committed"
    assert row["summary_evidence_window"] == "1-3"
    assert json.loads(row["outline_update_json"])["chapter_line"] == "[1] committed line"
    assert row["outline_status"] == "committed"


def test_old_chapter_rows_gain_provisional_status_defaults(tmp_path: Path) -> None:
    db = NovelAgentDB(tmp_path / "legacy.db")
    with sqlite3.connect(str(db.db_path)) as conn:
        conn.row_factory = sqlite3.Row
        conn.execute(
            """
            CREATE TABLE chapters (
                chapter_id INTEGER PRIMARY KEY AUTOINCREMENT,
                book_id TEXT NOT NULL,
                document_title_index INTEGER NOT NULL,
                chapter_title TEXT NOT NULL,
                source_doc_start_id INTEGER NOT NULL,
                source_doc_end_id INTEGER NOT NULL,
                source_doc_count INTEGER NOT NULL,
                source_total_chars INTEGER NOT NULL,
                summary_intermediate_json TEXT NOT NULL DEFAULT '[]',
                summary_md TEXT NOT NULL DEFAULT '',
                summary_short TEXT,
                importance_score INTEGER NOT NULL DEFAULT 0,
                importance_reason TEXT,
                related_chapters_json TEXT NOT NULL DEFAULT '[]',
                mentioned_characters_json TEXT NOT NULL DEFAULT '[]',
                world_update_json TEXT NOT NULL DEFAULT '{}',
                outline_update_json TEXT NOT NULL DEFAULT '{}',
                close_read_run_id TEXT NOT NULL DEFAULT '',
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                UNIQUE(book_id, document_title_index)
            )
            """
        )
        conn.execute(
            """
            INSERT INTO chapters(
                book_id, document_title_index, chapter_title, source_doc_start_id,
                source_doc_end_id, source_doc_count, source_total_chars,
                summary_md, summary_short, created_at, updated_at
            ) VALUES ('book', 1, '第一章', 1, 1, 1, 100, '旧摘要', '旧短摘要', 'now', 'now')
            """
        )
        db.init_schema(conn)
        row = ChaptersRepo().get(conn, book_id="book", document_title_index=1)

    assert row is not None
    assert row["summary_status"] == "provisional"
    assert row["outline_status"] == "provisional"


def test_summary_outline_commit_window_marks_target_range_committed(tmp_path: Path) -> None:
    db = NovelAgentDB(tmp_path / "commit.db")
    with db.connect() as conn:
        db.init_schema(conn)
        _seed_assets(conn, tmp_path, "book")
        for index in range(10, 21):
            summary = "日常关系铺垫。" if index < 14 else "调查线索推进并暴露新真相。"
            ChaptersRepo().upsert(conn, _chapter_payload(book_id="book", index=index, summary=summary))
        source_arc_payload = {
            "arcs": [
                {
                    "source_arc_id": "source-arc-001",
                    "start_document_title_index": 10,
                    "end_document_title_index": 20,
                    "source_arc_role": "主线推进",
                    "pacing_notes": "中速推进，后段信息密度上升。",
                    "chapter_role_map": [
                        {
                            "document_title_index": index,
                            "chapter_title": f"第{index}章",
                            "role": "设定揭示" if index in {16, 17} else "主线推进",
                            "reason": "窗口复核后确认结构功能。",
                        }
                        for index in range(10, 21)
                    ],
                }
            ]
        }

        result = SummaryOutlineCommitService(repo_root=tmp_path, now_factory=lambda: "now").commit_window(
            conn,
            book_id="book",
            evidence_window=(10, 20),
            target_range=(14, 18),
            source_arc_payload=source_arc_payload,
        )
        rows = [ChaptersRepo().get(conn, book_id="book", document_title_index=index) for index in range(14, 19)]

    assert result.success
    assert result.committed_title_indexes == [14, 15, 16, 17, 18]
    assert all(row is not None and row["summary_status"] == "committed" for row in rows)
    assert all(row is not None and row["summary_evidence_window"] == "10-20" for row in rows)
    assert all(row is not None and row["summary_target_range"] == "14-18" for row in rows)
    assert "状态：committed" in str(rows[0]["summary_md"])
    outline_update = json.loads(rows[2]["outline_update_json"])
    assert outline_update["chapter_line"] != "[16] 第16章: 调查线索推进并暴露新真相。"
    assert "篇章功能=设定揭示" in outline_update["chapter_line"]


def test_context_assembly_marks_mixed_status_and_falls_back_to_provisional(tmp_path: Path) -> None:
    db = NovelAgentDB(tmp_path / "context.db")
    repo = ChaptersRepo()
    with db.connect() as conn:
        db.init_schema(conn)
        _seed_assets(conn, tmp_path, "book")
        repo.upsert(conn, _chapter_payload(book_id="book", index=1, summary="第一章暂定摘要"))
        repo.upsert(
            conn,
            {
                **_chapter_payload(book_id="book", index=2, summary="第二章定稿摘要"),
                "summary_status": "committed",
                "summary_evidence_window": "1-3",
                "summary_target_range": "2-2",
                "outline_update": {"chapter_line": "[2] 第2章: 第二章定稿大纲", "timeline_events": []},
                "outline_status": "committed",
                "outline_evidence_window": "1-3",
                "outline_target_range": "2-2",
            },
        )

        payload = ContextAssemblyService.build_default(repo_root=tmp_path).assemble(
            conn,
            assembly_input=MemoryAssemblyInput(
                book_id="book",
                document_title_index="2",
                token_budget=MemoryAssemblyBudget(chapter_context_chars=2000, story_outline_chars=2000),
            ),
        )

    assert payload.memory_status["chapter_context"] == "mixed"
    assert payload.memory_status["story_outline"] == "mixed"
    assert {item.summary_status for item in payload.chapter_context} == {"provisional", "committed"}
    assert "status=provisional" in payload.story_outline_md
    assert "status=committed" in payload.story_outline_md


def test_source_arc_map_committed_structure_enters_context_and_can_reverse_commit(tmp_path: Path) -> None:
    db = NovelAgentDB(tmp_path / "source_arc.db")
    with db.connect() as conn:
        db.init_schema(conn)
        _seed_assets(conn, tmp_path, "book")
        for index in range(1, 5):
            summary = "世界规则与能力体系被进一步揭示。" if index >= 3 else "人物日常对话和关系铺垫。"
            ChaptersRepo().upsert(conn, _chapter_payload(book_id="book", index=index, summary=summary))
        source_arc_service = SourceArcMappingService(repo_root=tmp_path, now_factory=lambda: "now")
        source_arc_map = source_arc_service.build_from_chapters(conn, book_id="book")

        commit_result = SummaryOutlineCommitService(repo_root=tmp_path, now_factory=lambda: "now").commit_from_source_arc_map(
            conn,
            book_id="book",
            source_arc_payload=source_arc_map.to_dict(),
        )
        row = ChaptersRepo().get(conn, book_id="book", document_title_index=3)
        payload = ContextAssemblyService.build_default(repo_root=tmp_path).assemble(
            conn,
            assembly_input=MemoryAssemblyInput(
                book_id="book",
                document_title_index="3",
                token_budget=MemoryAssemblyBudget(source_arc_context_chars=2000),
            ),
        )

    assert commit_result.success
    assert row is not None
    assert row["summary_status"] == "committed"
    assert payload.source_arc_context
    assert payload.source_arc_context[0].status == "committed"
    assert payload.memory_status["source_arc_context"] == "committed"


def _seed_assets(conn, repo_root: Path, book_id: str) -> None:
    world_path, world_summary_path = WorldStateService(repo_root=repo_root).ensure_paths(book_id)
    world_summary_path.write_text("世界观概要：现代都市。", encoding="utf-8")
    outline_path = OutlineService(repo_root=repo_root).ensure_path(book_id)
    AssetsRepo().upsert(
        conn,
        {
            "book_id": book_id,
            "source_root": str(repo_root),
            "world_markdown_path": str(world_path),
            "world_summary_path": str(world_summary_path),
            "outline_markdown_path": str(outline_path),
            "created_at": "now",
            "updated_at": "now",
        },
    )


def _chapter_payload(*, book_id: str, index: int, summary: str) -> dict[str, object]:
    return {
        "book_id": book_id,
        "document_title_index": index,
        "chapter_title": f"第{index}章",
        "source_doc_start_id": index,
        "source_doc_end_id": index,
        "source_doc_count": 1,
        "source_total_chars": 100,
        "summary_intermediate": [],
        "summary_md": (
            "## 剧情事件链\n"
            f"- {summary}\n\n"
            "## 人物状态/关系变化\n"
            "- 人物关系继续推进。\n\n"
            "## 关键信息/设定\n"
            "- 关键信息继续积累。\n\n"
            "## 结构功能/节奏\n"
            "- 即时 close-read 暂定判断。\n"
        ),
        "summary_short": summary,
        "importance_score": 60,
        "importance_reason": "seed",
        "related_chapters": [],
        "mentioned_characters": ["林清"],
        "world_update": {},
        "outline_update": {"chapter_line": f"[{index}] 第{index}章: {summary}", "timeline_events": []},
        "close_read_run_id": "seed",
        "created_at": "now",
        "updated_at": "now",
    }

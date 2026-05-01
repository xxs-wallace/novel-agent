from __future__ import annotations

import sqlite3
from pathlib import Path

from novel_agent.app.repos.assets_repo import AssetsRepo
from novel_agent.app.repos.chapters_repo import ChaptersRepo
from novel_agent.app.repos.character_profiles_repo import CharacterProfilesRepo
from novel_agent.app.repos.db import NovelAgentDB
from novel_agent.app.schemas.orchestration_schema import MemoryAssemblyBudget, MemoryAssemblyInput
from novel_agent.app.services.context_assembly_service import ContextAssemblyService


def _seed_chapter(
    conn: sqlite3.Connection,
    *,
    book_id: str,
    title_index: int,
    title: str,
    summary_md: str,
    importance_score: int,
    mentioned_characters: list[str],
) -> None:
    ChaptersRepo().upsert(
        conn,
        {
            "book_id": book_id,
            "document_title_index": title_index,
            "chapter_title": title,
            "source_doc_start_id": title_index * 10,
            "source_doc_end_id": title_index * 10 + 1,
            "source_doc_count": 2,
            "source_total_chars": len(summary_md),
            "summary_intermediate": [],
            "summary_md": summary_md,
            "summary_short": summary_md[:40],
            "importance_score": importance_score,
            "importance_reason": "",
            "related_chapters": [],
            "mentioned_characters": mentioned_characters,
            "world_update": {},
            "outline_update": {},
            "close_read_run_id": "seed",
            "created_at": "now",
            "updated_at": "now",
        },
    )


def _seed_profile(
    conn: sqlite3.Connection,
    *,
    book_id: str,
    canonical_name: str,
    profile_summary_md: str,
    aliases: list[str] | None = None,
    importance_score: int = 0,
    last_seen_title_index: int = 1,
) -> None:
    CharacterProfilesRepo().upsert(
        conn,
        {
            "book_id": book_id,
            "canonical_name": canonical_name,
            "aliases": aliases or [],
            "profile_summary_md": profile_summary_md,
            "personality": [],
            "occupations": [],
            "age_timeline": [],
            "abilities": [],
            "recent_activity": [],
            "relationships": [],
            "chapter_indexes": [last_seen_title_index],
            "first_seen_doc_id": 1,
            "last_seen_doc_id": 10,
            "first_seen_title_index": 1,
            "last_seen_title_index": last_seen_title_index,
            "importance_score": importance_score,
            "profile_version": 1,
            "created_at": "now",
            "updated_at": "now",
        },
    )


def _seed_assets(
    conn: sqlite3.Connection,
    *,
    book_id: str,
    world_summary_path: Path,
    outline_path: Path,
) -> None:
    AssetsRepo().upsert(
        conn,
        {
            "book_id": book_id,
            "source_root": "",
            "world_markdown_path": "",
            "world_summary_path": world_summary_path.as_posix(),
            "outline_markdown_path": outline_path.as_posix(),
            "toc_markdown": "",
            "toc_source_path": "",
            "debug_export_path": "",
            "created_at": "now",
            "updated_at": "now",
        },
    )


def test_context_assembly_service_builds_payload_with_priority_and_budgets(tmp_path: Path) -> None:
    repo_root = tmp_path / "repo"
    repo_root.mkdir()
    world_summary_path = repo_root / "world_summary.md"
    outline_path = repo_root / "outline.md"
    world_summary_path.write_text("世界观概要" + "A" * 80, encoding="utf-8")
    outline_path.write_text("故事大纲" + "B" * 160, encoding="utf-8")

    db = NovelAgentDB(tmp_path / "context.db")
    with db.connect() as conn:
        db.init_schema(conn)
        _seed_assets(
            conn,
            book_id="book-1",
            world_summary_path=world_summary_path,
            outline_path=outline_path,
        )
        _seed_chapter(
            conn,
            book_id="book-1",
            title_index=1,
            title="第一章",
            summary_md="第一章摘要" + "甲" * 32,
            importance_score=2,
            mentioned_characters=["路明非"],
        )
        _seed_chapter(
            conn,
            book_id="book-1",
            title_index=2,
            title="第二章",
            summary_md="第二章摘要" + "乙" * 64,
            importance_score=9,
            mentioned_characters=["楚子航", "路明非"],
        )
        _seed_chapter(
            conn,
            book_id="book-1",
            title_index=3,
            title="第三章",
            summary_md="第三章摘要" + "丙" * 24,
            importance_score=6,
            mentioned_characters=["凯撒"],
        )
        _seed_profile(
            conn,
            book_id="book-1",
            canonical_name="楚子航",
            aliases=["楚师兄"],
            profile_summary_md="# 楚子航\n\n- 冷静克制。\n- 与当前冲突直接相关。\n",
            importance_score=8,
            last_seen_title_index=2,
        )
        _seed_profile(
            conn,
            book_id="book-1",
            canonical_name="路明非",
            aliases=["明非"],
            profile_summary_md="# 路明非\n\n- 处于被卷入状态。\n",
            importance_score=5,
            last_seen_title_index=2,
        )
        conn.commit()

        service = ContextAssemblyService.build_default(repo_root=repo_root)
        payload = service.assemble(
            conn,
            assembly_input=MemoryAssemblyInput(
                book_id="book-1",
                document_title_index="3",
                related_character_names=["楚子航"],
                token_budget=MemoryAssemblyBudget(
                    chapter_context_chars=110,
                    world_summary_chars=30,
                    character_profiles_chars=80,
                    story_outline_chars=40,
                ),
            ),
        )

    assert [item.document_title_index for item in payload.chapter_context[:2]] == ["3", "2"]
    assert payload.chapter_context[0].chapter_title == "第三章"
    assert payload.world_summary_md.startswith("世界观概要")
    assert len(payload.world_summary_md) <= 30
    assert payload.story_outline_md.startswith("故事大纲")
    assert len(payload.story_outline_md) <= 40
    assert [item.canonical_name for item in payload.character_profiles[:1]] == ["楚子航"]
    assert "路明非" in [item.canonical_name for item in payload.character_profiles]
    assert payload.character_profiles[0].aliases == ["楚师兄"]
    assert "world_summary_md.truncated" in payload.missing_context
    assert "story_outline_md.truncated" in payload.missing_context


def test_context_assembly_service_marks_missing_context_when_memory_is_unavailable(tmp_path: Path) -> None:
    repo_root = tmp_path / "repo"
    repo_root.mkdir()
    db = NovelAgentDB(tmp_path / "missing.db")
    with db.connect() as conn:
        db.init_schema(conn)
        service = ContextAssemblyService.build_default(repo_root=repo_root)
        payload = service.assemble(
            conn,
            assembly_input=MemoryAssemblyInput(
                book_id="missing-book",
                document_title_index="5",
                related_character_names=["不存在的人物"],
            ),
        )

    assert payload.chapter_context == []
    assert payload.character_profiles == []
    assert "chapter_context.empty" in payload.missing_context
    assert "book_assets.missing" in payload.missing_context
    assert "character_profiles.none_found" in payload.missing_context


def test_context_assembly_service_reports_missing_requested_characters(tmp_path: Path) -> None:
    repo_root = tmp_path / "repo"
    repo_root.mkdir()
    world_summary_path = repo_root / "world_summary.md"
    outline_path = repo_root / "outline.md"
    world_summary_path.write_text("世界观概要", encoding="utf-8")
    outline_path.write_text("故事大纲", encoding="utf-8")

    db = NovelAgentDB(tmp_path / "characters.db")
    with db.connect() as conn:
        db.init_schema(conn)
        _seed_assets(
            conn,
            book_id="book-2",
            world_summary_path=world_summary_path,
            outline_path=outline_path,
        )
        _seed_chapter(
            conn,
            book_id="book-2",
            title_index=7,
            title="第七章",
            summary_md="章节摘要",
            importance_score=7,
            mentioned_characters=["路明非"],
        )
        _seed_profile(
            conn,
            book_id="book-2",
            canonical_name="路明非",
            profile_summary_md="# 路明非\n\n- 在场。\n",
        )
        conn.commit()

        service = ContextAssemblyService.build_default(repo_root=repo_root)
        payload = service.assemble(
            conn,
            assembly_input=MemoryAssemblyInput(
                book_id="book-2",
                document_title_index="7",
                related_character_names=["楚子航", "路明非"],
            ),
        )

    assert [item.canonical_name for item in payload.character_profiles] == ["路明非"]
    assert "character_profiles.requested_missing:楚子航" in payload.missing_context

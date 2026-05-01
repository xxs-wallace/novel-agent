from __future__ import annotations

from pathlib import Path

from novel_agent.app.repos.assets_repo import AssetsRepo
from novel_agent.app.repos.chapters_repo import ChaptersRepo
from novel_agent.app.repos.character_profiles_repo import CharacterProfilesRepo
from novel_agent.app.repos.db import NovelAgentDB
from novel_agent.app.schemas.orchestration_schema import MemoryAssemblyBudget, MemoryAssemblyInput
from novel_agent.app.services.context_assembly_service import ContextAssemblyService


def _seed_chapter(
    conn,
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
    conn,
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
    conn,
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


def test_context_assembly_service_to_dict_matches_contract_shape(tmp_path: Path) -> None:
    repo_root = tmp_path / "repo"
    repo_root.mkdir()
    world_summary_path = repo_root / "world_summary.md"
    outline_path = repo_root / "outline.md"
    world_summary_path.write_text("现代都市奇幻世界，雨夜与高架桥反复出现。", encoding="utf-8")
    outline_path.write_text("主线围绕两人关系误解与再靠近展开。", encoding="utf-8")

    db = NovelAgentDB(tmp_path / "context_contract.db")
    with db.connect() as conn:
        db.init_schema(conn)
        _seed_assets(
            conn,
            book_id="book-contract",
            world_summary_path=world_summary_path,
            outline_path=outline_path,
        )
        _seed_chapter(
            conn,
            book_id="book-contract",
            title_index=5,
            title="第五章 雨夜",
            summary_md="第五章摘要：两人在高架桥下维持表面平静。",
            importance_score=9,
            mentioned_characters=["沈青", "周渡"],
        )
        _seed_profile(
            conn,
            book_id="book-contract",
            canonical_name="沈青",
            aliases=["小青"],
            profile_summary_md="# 沈青\n\n- 敏感克制。\n- 当前处于防御状态。\n",
            importance_score=7,
            last_seen_title_index=5,
        )
        conn.commit()

        service = ContextAssemblyService.build_default(repo_root=repo_root)
        payload_dict = service.assemble_to_dict(
            conn,
            assembly_input=MemoryAssemblyInput(
                book_id="book-contract",
                document_title_index="5",
                related_character_names=["沈青"],
                token_budget=MemoryAssemblyBudget(
                    chapter_context_chars=200,
                    world_summary_chars=64,
                    character_profiles_chars=120,
                    story_outline_chars=64,
                ),
            ),
        )

    assert set(payload_dict.keys()) == {
        "chapter_context",
        "world_summary_md",
        "character_profiles",
        "story_outline_md",
        "missing_context",
    }
    assert payload_dict["world_summary_md"].startswith("现代都市奇幻世界")
    assert payload_dict["story_outline_md"].startswith("主线围绕")
    assert isinstance(payload_dict["missing_context"], list)

    chapter_context = payload_dict["chapter_context"]
    assert isinstance(chapter_context, list)
    assert chapter_context[0]["document_title_index"] == "5"
    assert chapter_context[0]["chapter_title"] == "第五章 雨夜"
    assert "summary_md" in chapter_context[0]
    assert "importance_score" in chapter_context[0]

    character_profiles = payload_dict["character_profiles"]
    assert isinstance(character_profiles, list)
    assert character_profiles[0]["canonical_name"] == "沈青"
    assert character_profiles[0]["aliases"] == ["小青"]
    assert "profile_summary_md" in character_profiles[0]


def test_context_assembly_service_returns_missing_signals_when_budget_is_zero(tmp_path: Path) -> None:
    repo_root = tmp_path / "repo"
    repo_root.mkdir()
    world_summary_path = repo_root / "world_summary.md"
    outline_path = repo_root / "outline.md"
    world_summary_path.write_text("世界观概要", encoding="utf-8")
    outline_path.write_text("故事大纲", encoding="utf-8")

    db = NovelAgentDB(tmp_path / "context_zero_budget.db")
    with db.connect() as conn:
        db.init_schema(conn)
        _seed_assets(
            conn,
            book_id="book-zero",
            world_summary_path=world_summary_path,
            outline_path=outline_path,
        )
        _seed_chapter(
            conn,
            book_id="book-zero",
            title_index=1,
            title="第一章",
            summary_md="章节摘要",
            importance_score=1,
            mentioned_characters=["阿宁"],
        )
        _seed_profile(
            conn,
            book_id="book-zero",
            canonical_name="阿宁",
            profile_summary_md="# 阿宁\n\n- 在场。\n",
        )
        conn.commit()

        service = ContextAssemblyService.build_default(repo_root=repo_root)
        payload = service.assemble(
            conn,
            assembly_input=MemoryAssemblyInput(
                book_id="book-zero",
                document_title_index="1",
                related_character_names=["阿宁"],
                token_budget=MemoryAssemblyBudget(
                    chapter_context_chars=0,
                    world_summary_chars=0,
                    character_profiles_chars=0,
                    story_outline_chars=0,
                ),
            ),
        )

    assert payload.chapter_context == []
    assert payload.character_profiles == []
    assert payload.world_summary_md == ""
    assert payload.story_outline_md == ""
    assert "chapter_context.over_budget" in payload.missing_context
    assert "world_summary_md.empty" in payload.missing_context
    assert "story_outline_md.empty" in payload.missing_context
    assert "character_profiles.over_budget" in payload.missing_context

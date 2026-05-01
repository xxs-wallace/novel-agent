from __future__ import annotations

from pathlib import Path

from novel_agent.app.repos.assets_repo import AssetsRepo
from novel_agent.app.repos.chapters_repo import ChaptersRepo
from novel_agent.app.repos.character_profiles_repo import CharacterProfilesRepo
from novel_agent.app.repos.db import NovelAgentDB
from novel_agent.app.repos.documents_repo import DocumentsRepo
from novel_agent.app.repos.fragment_cards_repo import FragmentCardsRepo
from novel_agent.app.schemas.smoke_schema import AllowedOutlineScope, DocumentsCutoff, SmokeSampleConfig
from novel_agent.app.services.smoke_prefix_snapshot_service import SmokePrefixSnapshotService


def test_smoke_prefix_snapshot_service_builds_prefix_only_runtime(tmp_path: Path) -> None:
    db_path = tmp_path / "source.db"
    db = NovelAgentDB(db_path)
    documents_repo = DocumentsRepo()
    chapters_repo = ChaptersRepo()
    profiles_repo = CharacterProfilesRepo()
    assets_repo = AssetsRepo()

    source_root = tmp_path / "source_assets"
    source_root.mkdir(parents=True)
    world_path = source_root / "world.md"
    world_summary_path = source_root / "world_summary.md"
    outline_path = source_root / "outline.md"
    world_path.write_text("世界观正文。", encoding="utf-8")
    world_summary_path.write_text("世界观摘要。", encoding="utf-8")
    outline_path.write_text(
        "# 第3章\n当前章授权纲要。\n\n# 第4章\n未来章详细内容。\n",
        encoding="utf-8",
    )

    with db.connect() as conn:
        db.init_schema(conn)
        doc_id_1 = documents_repo.insert_document(
            conn,
            {
                "book_id": "book-1",
                "path": "/tmp/book.md",
                "scope": "chapter",
                "content": "第一章内容。",
                "source_path": "/tmp/book.md",
                "source_file_name": "book.md",
                "source_start_offset": 0,
                "source_end_offset": 6,
                "document_title": "第1章",
                "document_title_index": 1,
                "content_tags": ["雨天"],
            },
        )
        doc_id_2 = documents_repo.insert_document(
            conn,
            {
                "book_id": "book-1",
                "path": "/tmp/book.md",
                "scope": "chapter",
                "content": "第二章内容。",
                "source_path": "/tmp/book.md",
                "source_file_name": "book.md",
                "source_start_offset": 7,
                "source_end_offset": 13,
                "document_title": "第2章",
                "document_title_index": 2,
                "content_tags": ["告别"],
            },
        )
        doc_id_3 = documents_repo.insert_document(
            conn,
            {
                "book_id": "book-1",
                "path": "/tmp/book.md",
                "scope": "chapter",
                "content": "第三章内容。",
                "source_path": "/tmp/book.md",
                "source_file_name": "book.md",
                "source_start_offset": 14,
                "source_end_offset": 20,
                "document_title": "第3章",
                "document_title_index": 3,
                "content_tags": ["医院"],
            },
        )
        chapters_repo.upsert(
            conn,
            {
                "book_id": "book-1",
                "document_title_index": 1,
                "chapter_title": "第1章",
                "source_doc_start_id": doc_id_1,
                "source_doc_end_id": doc_id_1,
                "source_doc_count": 1,
                "source_total_chars": 6,
                "summary_intermediate": ["第一章摘要"],
                "summary_md": "第一章摘要",
                "summary_short": "第一章",
                "importance_score": 5,
                "importance_reason": "前情",
                "related_chapters": [{"document_title_index": 2, "score": 90, "reason": "承接"}],
                "mentioned_characters": ["林清"],
                "world_update": {},
                "outline_update": {},
                "close_read_run_id": "seed",
                "created_at": "now",
                "updated_at": "now",
            },
        )
        chapters_repo.upsert(
            conn,
            {
                "book_id": "book-1",
                "document_title_index": 2,
                "chapter_title": "第2章",
                "source_doc_start_id": doc_id_2,
                "source_doc_end_id": doc_id_2,
                "source_doc_count": 1,
                "source_total_chars": 6,
                "summary_intermediate": ["第二章摘要"],
                "summary_md": "第二章摘要",
                "summary_short": "第二章",
                "importance_score": 6,
                "importance_reason": "承接",
                "related_chapters": [{"document_title_index": 3, "score": 95, "reason": "当前目标"}],
                "mentioned_characters": ["林清"],
                "world_update": {},
                "outline_update": {},
                "close_read_run_id": "seed",
                "created_at": "now",
                "updated_at": "now",
            },
        )
        chapters_repo.upsert(
            conn,
            {
                "book_id": "book-1",
                "document_title_index": 3,
                "chapter_title": "第3章",
                "source_doc_start_id": doc_id_3,
                "source_doc_end_id": doc_id_3,
                "source_doc_count": 1,
                "source_total_chars": 6,
                "summary_intermediate": ["第三章摘要"],
                "summary_md": "第三章摘要",
                "summary_short": "第三章",
                "importance_score": 7,
                "importance_reason": "目标章",
                "related_chapters": [],
                "mentioned_characters": ["林清"],
                "world_update": {},
                "outline_update": {},
                "close_read_run_id": "seed",
                "created_at": "now",
                "updated_at": "now",
            },
        )
        profiles_repo.upsert(
            conn,
            {
                "book_id": "book-1",
                "canonical_name": "林清",
                "aliases": ["小清"],
                "profile_summary_md": "人物总结可能已包含后续章节结果。",
                "personality": ["克制"],
                "occupations": [],
                "age_timeline": [],
                "abilities": [],
                "recent_activity": [],
                "relationships": [],
                "chapter_indexes": [1, 2, 3],
                "first_seen_doc_id": doc_id_1,
                "last_seen_doc_id": doc_id_3,
                "first_seen_title_index": 1,
                "last_seen_title_index": 3,
                "importance_score": 9,
                "profile_version": 1,
                "created_at": "now",
                "updated_at": "now",
            },
        )
        assets_repo.upsert(
            conn,
            {
                "book_id": "book-1",
                "source_root": str(source_root),
                "world_markdown_path": str(world_path),
                "world_summary_path": str(world_summary_path),
                "outline_markdown_path": str(outline_path),
                "toc_markdown": "",
                "toc_source_path": "",
                "debug_export_path": "",
                "created_at": "now",
                "updated_at": "now",
            },
        )
        conn.commit()

    sample = SmokeSampleConfig(
        sample_id="sample-1",
        book_id="book-1",
        target_chapter_id="chapter-3",
        mode="chapter_authorized",
        anchor_context_path="/tmp/unused-anchor.md",
        recent_window_refs=[],
        documents_cutoff=DocumentsCutoff(max_document_title_index="2"),
        allowed_outline_scope=AllowedOutlineScope(
            chapter_range=["第3章"],
            allow_future_outline=False,
        ),
        reference_truth_path="/tmp/unused-truth.md",
    )

    snapshot = SmokePrefixSnapshotService().build(
        source_db_path=db_path,
        sample=sample,
        output_root=tmp_path / "runs",
    )

    snapshot_db = NovelAgentDB(Path(snapshot.db_path))
    with snapshot_db.connect() as conn:
        copied_indexes = documents_repo.list_title_indexes(conn, book_id="book-1")
        copied_chapters = chapters_repo.list_by_book(conn, book_id="book-1")
        copied_profiles = profiles_repo.list_by_book(conn, book_id="book-1")
        copied_cards = FragmentCardsRepo().list_all(conn)
        target_assets = assets_repo.get(conn, book_id="book-1")

    assert snapshot.copied_doc_count == 2
    assert copied_indexes == [1, 2]
    assert [int(row["document_title_index"]) for row in copied_chapters] == [1, 2]
    assert len(copied_profiles) == 1
    assert len(copied_cards) == 2
    assert target_assets is not None
    outline_text = Path(str(target_assets["outline_markdown_path"])).read_text(encoding="utf-8")
    assert "当前章授权纲要" in outline_text
    assert "未来章详细内容" not in outline_text
    chapter_indexes_json = copied_profiles[0]["chapter_indexes_json"]
    assert chapter_indexes_json == "[1, 2]"
    assert "character_profile.may_include_future_updates:林清" in snapshot.warnings

from __future__ import annotations

import sqlite3
from pathlib import Path

from novel_agent.app.runner.close_read_runner import CloseReadRunner
from novel_agent.app.runner.segmentation_runner import SegmentationRunner
from novel_agent.app.schemas.orchestration_schema import MemoryAssemblyInput
from novel_agent.app.schemas.config_schema import CloseReadAgentConfig, SegmentationAgentConfig
from novel_agent.app.services.context_assembly_service import ContextAssemblyService


def test_segmentation_and_close_read_pipeline(tmp_path: Path) -> None:
    source_root = Path(__file__).parent / "fixtures" / "novel_agent" / "longzu_5kb"
    db_path = tmp_path / "novel.db"

    seg_config = SegmentationAgentConfig.from_mapping(
        {
            "book": {"book_id": "demo_book", "source_root": str(source_root)},
            "storage": {"sqlite_path": str(db_path)},
            "read_strategy": {"max_total_chars": 5_120, "preferred_document_chars_min": 800},
            "runtime": {"dry_run": True},
        }
    )
    seg_runner = SegmentationRunner(repo_root=tmp_path, db_path=db_path, config=seg_config)
    seg_result = seg_runner.run()
    assert seg_result.inserted_documents >= 1
    with sqlite3.connect(db_path) as conn:
        raw_keywords = conn.execute(
            "SELECT character_keywords_json FROM documents WHERE book_id = 'demo_book' ORDER BY doc_id LIMIT 1"
        ).fetchone()[0]
    assert raw_keywords == "[]"

    close_config = CloseReadAgentConfig(book_id="demo_book", sqlite_path=str(db_path))
    close_config.runtime.dry_run = True
    close_config.runtime.max_chapters = 1
    close_config.runtime.debug_markdown_path = str(tmp_path / "debug.md")
    close_runner = CloseReadRunner(repo_root=tmp_path, db_path=db_path, config=close_config)
    close_result = close_runner.run()
    assert close_result.processed_batches == 1
    assert close_result.exported_markdown is not None
    assert close_result.exported_markdown.exists()
    exported_text = close_result.exported_markdown.read_text(encoding="utf-8")
    assert "康斯坦丁" in exported_text
    assert "## Chapters" in exported_text
    assert "## Raw SQLite Rows" in exported_text
    assert "content_tags_csv" in exported_text

    with sqlite3.connect(db_path) as conn:
        doc_count = conn.execute("SELECT COUNT(*) FROM documents WHERE book_id = 'demo_book'").fetchone()[0]
        chapter_count = conn.execute("SELECT COUNT(*) FROM chapters WHERE book_id = 'demo_book'").fetchone()[0]
        profile_count = conn.execute("SELECT COUNT(*) FROM character_profiles WHERE book_id = 'demo_book'").fetchone()[0]
        tags_csv = conn.execute(
            "SELECT content_tags_csv FROM documents WHERE book_id = 'demo_book' ORDER BY doc_id LIMIT 1"
        ).fetchone()[0]
        character_keywords_json = conn.execute(
            "SELECT character_keywords_json FROM documents WHERE book_id = 'demo_book' ORDER BY doc_id LIMIT 1"
        ).fetchone()[0]
    assert doc_count >= 1
    assert chapter_count >= 1
    assert profile_count >= 1
    assert tags_csv
    assert "康斯坦丁" in character_keywords_json


def test_memory_end_to_end_pipeline_to_context_assembly(tmp_path: Path) -> None:
    source_root = Path(__file__).parent / "fixtures" / "novel_agent" / "longzu_5kb"
    db_path = tmp_path / "memory_e2e.db"

    seg_config = SegmentationAgentConfig.from_mapping(
        {
            "book": {"book_id": "memory_e2e_book", "source_root": str(source_root)},
            "storage": {"sqlite_path": str(db_path)},
            "read_strategy": {"max_total_chars": 5_120, "preferred_document_chars_min": 800},
            "runtime": {"dry_run": True},
        }
    )
    SegmentationRunner(repo_root=tmp_path, db_path=db_path, config=seg_config).run()

    close_config = CloseReadAgentConfig(book_id="memory_e2e_book", sqlite_path=str(db_path))
    close_config.runtime.dry_run = True
    close_config.runtime.max_chapters = 1
    close_config.runtime.export_debug_markdown = False
    CloseReadRunner(repo_root=tmp_path, db_path=db_path, config=close_config).run()

    with sqlite3.connect(db_path) as conn:
        conn.row_factory = sqlite3.Row
        chapter_row = conn.execute(
            """
            SELECT document_title_index, chapter_title, summary_md
            FROM chapters
            WHERE book_id = 'memory_e2e_book'
            ORDER BY document_title_index
            LIMIT 1
            """
        ).fetchone()
        assert chapter_row is not None
        service = ContextAssemblyService.build_default(repo_root=tmp_path)
        payload = service.assemble(
            conn,
            assembly_input=MemoryAssemblyInput(
                book_id="memory_e2e_book",
                document_title_index=str(chapter_row["document_title_index"]),
            ),
        )

    assert "## 摘要元信息" in str(chapter_row["summary_md"])
    assert "## 剧情推进" in str(chapter_row["summary_md"])
    assert payload.chapter_context
    assert payload.chapter_context[0].document_title_index == str(chapter_row["document_title_index"])
    assert payload.chapter_context[0].summary_md
    assert payload.world_summary_md.strip()
    assert payload.story_outline_md.strip()
    assert payload.character_profiles
    assert "chapter_context.empty" not in payload.missing_context


def test_segmentation_resume_from_checkpoint_appends_new_documents(tmp_path: Path) -> None:
    source_root = Path(__file__).parent / "fixtures" / "novel_agent" / "longzu_5kb"
    db_path = tmp_path / "resume.db"
    base_mapping = {
        "book": {"book_id": "resume_book", "source_root": str(source_root)},
        "storage": {"sqlite_path": str(db_path)},
        "read_strategy": {
            "target_chunk_chars_min": 1200,
            "target_chunk_chars_max": 1800,
            "preferred_document_chars_min": 800,
        },
        "runtime": {"dry_run": True},
    }

    first_config = SegmentationAgentConfig.from_mapping(
        {
            **base_mapping,
            "read_strategy": {**base_mapping["read_strategy"], "max_total_chars": 2048},
        }
    )
    first_result = SegmentationRunner(repo_root=tmp_path, db_path=db_path, config=first_config).run()
    assert first_result.inserted_documents >= 1

    with sqlite3.connect(db_path) as conn:
        first_doc_count = conn.execute(
            "SELECT COUNT(*) FROM documents WHERE book_id = 'resume_book'"
        ).fetchone()[0]
        first_max_offset = conn.execute(
            "SELECT MAX(source_end_offset) FROM documents WHERE book_id = 'resume_book'"
        ).fetchone()[0]

    second_config = SegmentationAgentConfig.from_mapping(
        {
            **base_mapping,
            "read_strategy": {**base_mapping["read_strategy"], "max_total_chars": 2048},
            "runtime": {"dry_run": True, "resume_from_checkpoint": True},
        }
    )
    second_result = SegmentationRunner(repo_root=tmp_path, db_path=db_path, config=second_config).run()
    assert second_result.batch_count >= 1

    with sqlite3.connect(db_path) as conn:
        second_doc_count = conn.execute(
            "SELECT COUNT(*) FROM documents WHERE book_id = 'resume_book'"
        ).fetchone()[0]
        second_max_offset = conn.execute(
            "SELECT MAX(source_end_offset) FROM documents WHERE book_id = 'resume_book'"
        ).fetchone()[0]
        progress_row = conn.execute(
            "SELECT checkpoint_token FROM reading_progress WHERE book_id = 'resume_book' AND agent_stage = 'segmentation'"
        ).fetchone()

    assert second_doc_count > first_doc_count
    assert second_max_offset > first_max_offset
    assert progress_row is not None
    assert progress_row[0]


def test_segmentation_resume_is_idempotent_from_same_checkpoint(tmp_path: Path) -> None:
    source_root = Path(__file__).parent / "fixtures" / "novel_agent" / "longzu_5kb"
    db_path = tmp_path / "resume_idempotent.db"
    base_mapping = {
        "book": {"book_id": "resume_book", "source_root": str(source_root)},
        "storage": {"sqlite_path": str(db_path)},
        "read_strategy": {
            "target_chunk_chars_min": 1200,
            "target_chunk_chars_max": 1800,
            "preferred_document_chars_min": 800,
            "max_total_chars": 2048,
        },
        "runtime": {"dry_run": True},
    }

    SegmentationRunner(repo_root=tmp_path, db_path=db_path, config=SegmentationAgentConfig.from_mapping(base_mapping)).run()

    resume_mapping = {**base_mapping, "runtime": {"dry_run": True, "resume_from_checkpoint": True}}
    SegmentationRunner(repo_root=tmp_path, db_path=db_path, config=SegmentationAgentConfig.from_mapping(resume_mapping)).run()
    with sqlite3.connect(db_path) as conn:
        first_resume_count = conn.execute(
            "SELECT COUNT(*) FROM documents WHERE book_id = 'resume_book'"
        ).fetchone()[0]

    SegmentationRunner(repo_root=tmp_path, db_path=db_path, config=SegmentationAgentConfig.from_mapping(resume_mapping)).run()
    with sqlite3.connect(db_path) as conn:
        second_resume_count = conn.execute(
            "SELECT COUNT(*) FROM documents WHERE book_id = 'resume_book'"
        ).fetchone()[0]

    assert second_resume_count == first_resume_count


def test_segmentation_resume_preserves_close_read_checkpoint(tmp_path: Path) -> None:
    source_root = Path(__file__).parent / "fixtures" / "novel_agent" / "longzu_5kb"
    db_path = tmp_path / "resume_close_progress.db"

    first_config = SegmentationAgentConfig.from_mapping(
        {
            "book": {"book_id": "resume_close_book", "source_root": str(source_root)},
            "storage": {"sqlite_path": str(db_path)},
            "read_strategy": {
                "target_chunk_chars_min": 1200,
                "target_chunk_chars_max": 1800,
                "preferred_document_chars_min": 800,
                "max_total_chars": 2048,
            },
            "runtime": {"dry_run": True},
        }
    )
    SegmentationRunner(repo_root=tmp_path, db_path=db_path, config=first_config).run()

    close_config = CloseReadAgentConfig(book_id="resume_close_book", sqlite_path=str(db_path))
    close_config.runtime.dry_run = True
    close_config.runtime.max_chapters = 1
    CloseReadRunner(repo_root=tmp_path, db_path=db_path, config=close_config).run()

    with sqlite3.connect(db_path) as conn:
        progress_before = conn.execute(
            """
            SELECT last_completed_doc_id
            FROM reading_progress
            WHERE book_id = 'resume_close_book' AND agent_stage = 'close_reading'
            """
        ).fetchone()[0]

    resume_config = SegmentationAgentConfig.from_mapping(
        {
            "book": {"book_id": "resume_close_book", "source_root": str(source_root)},
            "storage": {"sqlite_path": str(db_path)},
            "read_strategy": {
                "target_chunk_chars_min": 1200,
                "target_chunk_chars_max": 1800,
                "preferred_document_chars_min": 800,
                "max_total_chars": 2048,
            },
            "runtime": {"dry_run": True, "resume_from_checkpoint": True},
        }
    )
    SegmentationRunner(repo_root=tmp_path, db_path=db_path, config=resume_config).run()

    with sqlite3.connect(db_path) as conn:
        progress_after = conn.execute(
            """
            SELECT last_completed_doc_id
            FROM reading_progress
            WHERE book_id = 'resume_close_book' AND agent_stage = 'close_reading'
            """
        ).fetchone()[0]

    assert progress_before is not None
    assert progress_after == progress_before

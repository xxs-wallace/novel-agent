from __future__ import annotations

import sqlite3
from pathlib import Path

from novel_agent.app.repos.db import NovelAgentDB
from novel_agent.app.repos.documents_repo import DocumentsRepo
from novel_agent.app.repos.reading_progress_repo import ReadingProgressRepo
from novel_agent.app.services.chapter_assembler_service import (
    SPLIT_REASON_FULL_CHAPTER,
    SPLIT_REASON_OVER_BUDGET,
    ChapterAssemblerService,
)


def _insert_document(
    conn: sqlite3.Connection,
    *,
    book_id: str,
    title_index: int,
    title: str,
    content: str,
) -> None:
    DocumentsRepo().insert_document(
        conn,
        {
            "path": f"{title_index:03d}.md",
            "scope": "novel",
            "title": title,
            "content": content,
            "mtime": 0,
            "size": len(content.encode("utf-8")),
            "content_sha256": f"sha-{title_index}-{len(content)}",
            "book_id": book_id,
            "source_path": f"{title_index:03d}.md",
            "source_file_name": f"{title_index:03d}.md",
            "source_start_offset": 0,
            "source_end_offset": len(content),
            "source_batch_no": 1,
            "document_title": title,
            "document_title_index": title_index,
            "inferred_chapter_no": title_index,
            "content_chars": len(content),
            "character_keywords": [],
            "content_tags": [],
            "segmentation_notes": "",
            "ingestion_run_id": "seed",
            "created_at": "now",
            "updated_at": "now",
        },
    )


def test_chapter_assembler_returns_whole_chapter_when_total_chars_within_budget(tmp_path: Path) -> None:
    db = NovelAgentDB(tmp_path / "assembler.db")
    with db.connect() as conn:
        db.init_schema(conn)
        _insert_document(conn, book_id="book-1", title_index=1, title="第一章", content="甲" * 120)
        _insert_document(conn, book_id="book-1", title_index=1, title="第一章", content="乙" * 100)
        conn.commit()

        service = ChapterAssemblerService(
            documents_repo=DocumentsRepo(),
            progress_repo=ReadingProgressRepo(),
            document_chars_budget=260,
            progress_stage="close_reading",
        )
        batch = service.load_next_batch(conn, book_id="book-1")

    assert batch is not None
    assert batch.is_complete_chapter is True
    assert batch.split_reason == SPLIT_REASON_FULL_CHAPTER
    assert batch.batch_doc_count == 2
    assert batch.chapter_doc_count == 2
    assert batch.chapter_total_chars == 220
    assert batch.batch_doc_start_index == 1


def test_chapter_assembler_packs_multiple_title_indexes_within_budget(tmp_path: Path) -> None:
    db = NovelAgentDB(tmp_path / "assembler_multi.db")
    with db.connect() as conn:
        db.init_schema(conn)
        _insert_document(conn, book_id="book-multi", title_index=1, title="第一章", content="甲" * 120)
        _insert_document(conn, book_id="book-multi", title_index=2, title="第二章", content="乙" * 100)
        _insert_document(conn, book_id="book-multi", title_index=3, title="第三章", content="丙" * 300)
        conn.commit()

        service = ChapterAssemblerService(
            documents_repo=DocumentsRepo(),
            progress_repo=ReadingProgressRepo(),
            document_chars_budget=260,
            progress_stage="close_reading",
        )
        batch = service.load_next_batch(conn, book_id="book-multi")

    assert batch is not None
    assert batch.title_indexes == [1, 2]
    assert batch.is_multi_chapter is True
    assert batch.batch_doc_count == 2
    assert batch.total_chars == 220
    assert batch.batch_label == "多章-1-2"


def test_chapter_assembler_resumes_from_checkpoint_token_and_splits_over_budget(tmp_path: Path) -> None:
    db = NovelAgentDB(tmp_path / "assembler_resume.db")
    with db.connect() as conn:
        db.init_schema(conn)
        _insert_document(conn, book_id="book-2", title_index=3, title="第三章", content="甲" * 150)
        _insert_document(conn, book_id="book-2", title_index=3, title="第三章", content="乙" * 140)
        _insert_document(conn, book_id="book-2", title_index=3, title="第三章", content="丙" * 130)
        ReadingProgressRepo().upsert(
            conn,
            {
                "book_id": "book-2",
                "agent_stage": "close_reading",
                "current_doc_id": None,
                "current_document_title_index": 3,
                "current_source_path": "003.md",
                "current_source_offset": 150,
                "last_completed_doc_id": None,
                "last_completed_title_index": 3,
                "last_completed_chapter_id": None,
                "status": {"state": "processed_batch"},
                "checkpoint_token": "3:1",
                "updated_at": "now",
            },
        )
        conn.commit()

        service = ChapterAssemblerService(
            documents_repo=DocumentsRepo(),
            progress_repo=ReadingProgressRepo(),
            document_chars_budget=220,
            progress_stage="close_reading",
        )
        batch = service.load_next_batch(conn, book_id="book-2")

    assert batch is not None
    assert [doc.doc_id for doc in batch.documents] == [2]
    assert batch.is_complete_chapter is False
    assert batch.split_reason == SPLIT_REASON_OVER_BUDGET
    assert batch.batch_doc_start_index == 2
    assert batch.chapter_doc_count == 3
    assert batch.chapter_total_chars == 420

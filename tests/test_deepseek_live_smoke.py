from __future__ import annotations

import os
import sqlite3
from pathlib import Path

import pytest

from novel_agent.app.repos.db import NovelAgentDB
from novel_agent.app.repos.documents_repo import DocumentsRepo
from novel_agent.app.runner.close_read_runner import CloseReadRunner
from novel_agent.app.schemas.config_schema import CloseReadAgentConfig

COUPLE_TXT_PATH = Path("./couple.txt")
DEEPSEEK_API_FILE = Path("~/deepseek.api")


def _require_live_smoke_enabled() -> None:
    if os.getenv("RUN_DEEPSEEK_LIVE_SMOKE") != "1":
        pytest.skip("Set RUN_DEEPSEEK_LIVE_SMOKE=1 to enable the DeepSeek live smoke test.")
    if not COUPLE_TXT_PATH.exists():
        pytest.skip(f"Missing smoke input file: {COUPLE_TXT_PATH}")
    if not DEEPSEEK_API_FILE.exists():
        pytest.skip(f"Missing DeepSeek API key file: {DEEPSEEK_API_FILE}")


def _seed_document_from_couple(conn: sqlite3.Connection, *, book_id: str) -> None:
    content = COUPLE_TXT_PATH.read_text(encoding="utf-8", errors="replace").strip()
    if len(content) < 500:
        pytest.skip("Smoke input text is too short to build a meaningful close-read prompt.")
    excerpt = content[:4000].strip()
    DocumentsRepo().insert_document(
        conn,
        {
            "path": COUPLE_TXT_PATH.as_posix(),
            "scope": "novel",
            "title": "couple.txt",
            "content": excerpt,
            "mtime": 0,
            "size": len(excerpt.encode("utf-8")),
            "content_sha256": "live-smoke-sha",
            "book_id": book_id,
            "source_path": COUPLE_TXT_PATH.as_posix(),
            "source_file_name": COUPLE_TXT_PATH.name,
            "source_start_offset": 0,
            "source_end_offset": len(excerpt),
            "source_batch_no": 1,
            "document_title": "第一章",
            "document_title_index": 1,
            "inferred_chapter_no": 1,
            "content_chars": len(excerpt),
            "character_keywords": [],
            "content_tags": ["关系", "日常"],
            "segmentation_notes": "live smoke seed",
            "ingestion_run_id": "live-smoke",
            "created_at": "now",
            "updated_at": "now",
        },
    )


@pytest.mark.timeout(240)
def test_deepseek_live_smoke_close_read_runner(tmp_path: Path) -> None:
    _require_live_smoke_enabled()

    repo_root = tmp_path / "repo"
    repo_root.mkdir()
    db_path = tmp_path / "live_smoke.db"
    book_id = "couple-live-smoke"

    db = NovelAgentDB(db_path)
    with db.connect() as conn:
        db.init_schema(conn)
        _seed_document_from_couple(conn, book_id=book_id)
        conn.commit()

    config = CloseReadAgentConfig(book_id=book_id, sqlite_path=str(db_path))
    config.model.model_type = "OpenAIModel"
    config.model.model_name = "deepseek-chat"
    config.model.base_url = "https://api.deepseek.com"
    config.model.api_key_file = DEEPSEEK_API_FILE.as_posix()
    config.model.api_key_env = "DEEPSEEK_API_KEY"
    config.model.timeout_seconds = 180
    config.runtime.dry_run = False
    config.runtime.max_chapters = 1
    config.runtime.document_chars_budget = 6000
    config.runtime.export_debug_markdown = False

    result = CloseReadRunner(repo_root=repo_root, db_path=db_path, config=config).run()

    assert result.processed_batches == 1

    with sqlite3.connect(db_path) as conn:
        chapter_row = conn.execute(
            """
            SELECT chapter_title, summary_md, importance_score
            FROM chapters
            WHERE book_id = ? AND document_title_index = 1
            """,
            (book_id,),
        ).fetchone()
        progress_row = conn.execute(
            """
            SELECT last_completed_doc_id, last_completed_title_index
            FROM reading_progress
            WHERE book_id = ? AND agent_stage = 'close_reading'
            """,
            (book_id,),
        ).fetchone()
        asset_row = conn.execute(
            """
            SELECT world_summary_path, outline_markdown_path
            FROM book_assets
            WHERE book_id = ?
            """,
            (book_id,),
        ).fetchone()

    assert chapter_row is not None
    assert str(chapter_row[0]).strip()
    assert len(str(chapter_row[1]).strip()) >= 80
    assert int(chapter_row[2]) >= 0

    assert progress_row is not None
    assert int(progress_row[0]) >= 1
    assert int(progress_row[1]) == 1

    assert asset_row is not None
    assert Path(str(asset_row[0])).exists()
    assert Path(str(asset_row[1])).exists()

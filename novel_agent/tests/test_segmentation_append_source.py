from pathlib import Path

import pytest

from novel_agent.app import run_interactive
from novel_agent.app.constants import DEFAULT_SEGMENTATION_STAGE
from novel_agent.app.repos.db import NovelAgentDB
from novel_agent.app.repos.reading_progress_repo import ReadingProgressRepo
from novel_agent.app.runner.segmentation_runner import SegmentationRunner
from novel_agent.app.schemas.config_schema import SegmentationAgentConfig
from novel_agent.app.services.chunk_reader_service import ChunkReaderService
from novel_agent.app.services.document_ingest_service import DocumentIngestService


def _runner(tmp_path: Path, *, source_path: Path, append_source: bool) -> SegmentationRunner:
    config = SegmentationAgentConfig.from_mapping(
        {
            "book": {"book_id": "book", "source_root": str(source_path)},
            "runtime": {"resume_from_checkpoint": True, "append_source": append_source},
        }
    )
    return SegmentationRunner(repo_root=tmp_path, db_path=tmp_path / "book.db", config=config)


def _seed_existing_source(tmp_path: Path) -> tuple[Path, Path, NovelAgentDB]:
    old_source = tmp_path / "old.txt"
    new_source = tmp_path / "new.txt"
    old_source.write_text("第一章\n旧内容。", encoding="utf-8")
    new_source.write_text("楔子\n新内容。", encoding="utf-8")
    db = NovelAgentDB(tmp_path / "book.db")
    with db.connect() as conn:
        db.init_schema(conn)
        conn.execute(
            """
            INSERT INTO documents(book_id, content, source_path, document_title_index)
            VALUES (?, ?, ?, ?)
            """,
            ("book", "旧内容。", str(old_source), 10),
        )
        ReadingProgressRepo().upsert(
            conn,
            {
                "book_id": "book",
                "agent_stage": DEFAULT_SEGMENTATION_STAGE,
                "current_source_path": str(old_source),
                "current_source_offset": len(old_source.read_text(encoding="utf-8")),
                "status": {"state": "completed_batch", "last_batch_no": 7},
                "checkpoint_token": f"{old_source}:8",
                "updated_at": "now",
            },
        )
        conn.commit()
    return old_source, new_source, db


def test_resume_rejects_a_different_source_without_explicit_append(tmp_path: Path) -> None:
    _old_source, new_source, db = _seed_existing_source(tmp_path)
    runner = _runner(tmp_path, source_path=new_source, append_source=False)

    with db.connect() as conn, pytest.raises(RuntimeError, match="Checkpoint source path is no longer available"):
        runner._load_resume_checkpoint(conn=conn, book_id="book", ordered_paths=[new_source])  # noqa: SLF001


def test_explicit_append_starts_new_source_at_zero_and_keeps_batch_sequence(tmp_path: Path) -> None:
    _old_source, new_source, db = _seed_existing_source(tmp_path)
    runner = _runner(tmp_path, source_path=new_source, append_source=True)

    with db.connect() as conn:
        checkpoint = runner._load_resume_checkpoint(  # noqa: SLF001
            conn=conn,
            book_id="book",
            ordered_paths=[new_source],
        )

    assert checkpoint.source_path is None
    assert checkpoint.source_offset == 0
    assert checkpoint.batch_no == 8
    assert checkpoint.appending_new_source is True


def test_explicit_append_refuses_to_restart_an_already_imported_source(tmp_path: Path) -> None:
    _old_source, new_source, db = _seed_existing_source(tmp_path)
    with db.connect() as conn:
        conn.execute(
            """
            INSERT INTO documents(book_id, content, source_path, document_title_index)
            VALUES (?, ?, ?, ?)
            """,
            ("book", "新内容。", new_source.name, 11),
        )
        conn.commit()
    runner = _runner(tmp_path, source_path=new_source, append_source=True)

    with db.connect() as conn, pytest.raises(RuntimeError, match="already has imported documents"):
        runner._load_resume_checkpoint(conn=conn, book_id="book", ordered_paths=[new_source])  # noqa: SLF001


def test_pipeline_config_carries_explicit_append_intent(tmp_path: Path) -> None:
    config = run_interactive._build_segmentation_config(  # noqa: SLF001
        book_id="book",
        source_path=tmp_path / "new.txt",
        db_path=tmp_path / "book.db",
        api_key="unused",
        max_total_chars=None,
        resume_from_checkpoint=True,
        append_source=True,
        request_retry_attempts=1,
    )

    assert config.runtime.resume_from_checkpoint is True
    assert config.runtime.append_source is True
    assert config.runtime.max_retries == 1


def test_bounded_reader_defers_a_subminimum_tail_to_the_next_round(tmp_path: Path) -> None:
    source = tmp_path / "source.txt"
    source.write_text(("这是一句话。\n" * 6000), encoding="utf-8")
    reader = ChunkReaderService(
        target_min_chars=20_000,
        target_max_chars=80_000,
        max_total_chars=32_768,
    )

    batches = reader.iter_batches([source])

    assert len(batches) == 1
    assert 20_000 <= batches[0].chars < 32_768


def test_only_empty_model_text_is_classified_for_batch_split_retry() -> None:
    empty_text = RuntimeError("Model returned empty text after 3 attempts for model=deepseek-v4-flash")
    invalid_key = RuntimeError("401: invalid api key")

    assert DocumentIngestService._is_retryable_empty_model_response(empty_text) is True
    assert DocumentIngestService._is_retryable_empty_model_response(invalid_key) is False


def test_transport_retry_classifier_excludes_authentication_failures() -> None:
    timeout = TimeoutError("LLM request timed out")
    authentication_error = type("AuthenticationError", (Exception,), {})("401 invalid api key")

    assert DocumentIngestService._is_retryable_model_transport_error(timeout) is True
    assert DocumentIngestService._is_retryable_model_transport_error(authentication_error) is False

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

from ..constants import DEFAULT_CLOSE_READING_STAGE, DEFAULT_SEGMENTATION_STAGE
from ..llm import JsonModelClient, ModelSettings
from ..repos.assets_repo import AssetsRepo
from ..repos.db import NovelAgentDB
from ..repos.documents_repo import DocumentsRepo
from ..repos.reading_progress_repo import ReadingProgressRepo
from ..schemas.config_schema import SegmentationAgentConfig
from ..services.book_toc_service import BookTocService
from ..services.chunk_reader_service import ChunkReaderService
from ..services.document_ingest_service import DocumentIngestService
from ..services.outline_service import OutlineService
from ..services.source_tree_service import SourceTreeService
from ..services.world_state_service import WorldStateService


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


@dataclass(slots=True)
class SegmentationRunnerResult:
    book_id: str
    db_path: Path
    inserted_documents: int
    batch_count: int


@dataclass(slots=True)
class SegmentationResumeCheckpoint:
    source_path: str | None
    source_offset: int
    batch_no: int


class SegmentationRunner:
    def __init__(
        self,
        *,
        repo_root: Path,
        db_path: Path,
        config: SegmentationAgentConfig,
        progress_callback: Callable[[dict[str, Any]], None] | None = None,
    ) -> None:
        self.repo_root = repo_root
        self.db_path = db_path
        self.config = config
        self.progress_callback = progress_callback

    def run(self) -> SegmentationRunnerResult:
        db = NovelAgentDB(self.db_path)
        model_client = JsonModelClient(
            ModelSettings(
                model_type=self.config.model.model_type,
                model_name=self.config.model.model_name,
                provider=self.config.model.provider,
                base_url=self.config.model.base_url,
                api_key=self.config.model.api_key,
                api_key_file=self.config.model.api_key_file,
                api_key_env=self.config.model.api_key_env,
                temperature=self.config.model.temperature,
                max_output_tokens=self.config.model.max_output_tokens,
                timeout_seconds=self.config.model.timeout_seconds,
                thinking=self.config.model.thinking,
                reasoning_effort=self.config.model.reasoning_effort,
                include_reasoning_content=self.config.model.include_reasoning_content,
                dry_run=self.config.runtime.dry_run,
            )
        )
        source_root = Path(self.config.book.source_root).expanduser().resolve()
        tree_service = SourceTreeService(model_client=model_client)
        analysis = tree_service.analyze(source_root, book_id=self.config.book.book_id)
        if not analysis.books:
            analysis = tree_service.heuristic_analysis(source_root, book_id=self.config.book.book_id)
        ordered_paths = self._resolve_ordered_paths(source_root=source_root, read_order=analysis.books[0].read_order)
        if not ordered_paths:
            fallback_analysis = tree_service.heuristic_analysis(source_root, book_id=self.config.book.book_id)
            ordered_paths = self._resolve_ordered_paths(source_root=source_root, read_order=fallback_analysis.books[0].read_order)
        if not ordered_paths:
            raise RuntimeError(f"No readable files resolved for {source_root}")
        toc_snapshot = BookTocService().extract_from_paths(ordered_paths)
        reader = ChunkReaderService(
            target_min_chars=self.config.read_strategy.target_chunk_chars_min,
            target_max_chars=self.config.read_strategy.target_chunk_chars_max,
            stop_at_newline_after_limit=self.config.read_strategy.stop_at_newline_after_limit,
            max_total_chars=self.config.read_strategy.max_total_chars,
        )
        documents_repo = DocumentsRepo()
        progress_repo = ReadingProgressRepo()
        ingest_service = DocumentIngestService(
            model_client=model_client,
            documents_repo=documents_repo,
            progress_repo=progress_repo,
            preferred_document_chars_min=self.config.read_strategy.preferred_document_chars_min,
            preferred_document_chars_max=self.config.read_strategy.preferred_document_chars_max,
            toc_markdown=toc_snapshot.toc_markdown if toc_snapshot else "",
            progress_callback=self.progress_callback,
        )
        world_service = WorldStateService(repo_root=self.repo_root, model_client=model_client)
        outline_service = OutlineService(repo_root=self.repo_root)
        world_path, world_summary_path = world_service.ensure_paths(self.config.book.book_id)
        outline_path = outline_service.ensure_path(self.config.book.book_id)
        run_id = uuid.uuid4().hex
        with db.connect() as conn:
            db.init_schema(conn)
            resume_checkpoint = self._load_resume_checkpoint(
                conn=conn,
                book_id=self.config.book.book_id,
                ordered_paths=ordered_paths,
            )
            if self.config.runtime.resume_from_checkpoint and resume_checkpoint.source_path:
                documents_repo.delete_from_source_offset(
                    conn,
                    book_id=self.config.book.book_id,
                    source_path=resume_checkpoint.source_path,
                    source_offset=resume_checkpoint.source_offset,
                )
            batches = reader.iter_batches_from_checkpoint(
                ordered_paths,
                resume_source_path=resume_checkpoint.source_path,
                resume_source_offset=resume_checkpoint.source_offset,
                start_batch_no=resume_checkpoint.batch_no,
            )
            last_document = documents_repo.fetch_last_document(conn, book_id=self.config.book.book_id)
            existing_title_indexes = documents_repo.list_title_indexes(conn, book_id=self.config.book.book_id)
            initial_title_index = (max(existing_title_indexes) + 1) if existing_title_indexes else 1
            result = ingest_service.ingest_batches(
                conn=conn,
                repo_root=self.repo_root,
                book_id=self.config.book.book_id,
                batches=batches,
                run_id=run_id,
                reset_book=not self.config.runtime.resume_from_checkpoint,
                initial_title_index=initial_title_index,
                continued_title=last_document.document_title if last_document else None,
                continued_title_index=last_document.document_title_index if last_document else None,
                continued_document_content=last_document.content if last_document else None,
            )
            AssetsRepo().upsert(
                conn,
                {
                    "book_id": self.config.book.book_id,
                    "source_root": source_root.as_posix(),
                    "world_markdown_path": world_path.as_posix(),
                    "world_summary_path": world_summary_path.as_posix(),
                    "outline_markdown_path": outline_path.as_posix(),
                    "toc_markdown": toc_snapshot.toc_markdown if toc_snapshot else "",
                    "toc_source_path": toc_snapshot.source_path if toc_snapshot else "",
                    "debug_export_path": str((self.repo_root / ".memory" / "debug" / f"{self.config.book.book_id}.sqlite.md").as_posix()),
                    "created_at": _utc_now(),
                    "updated_at": _utc_now(),
                },
            )
            existing_close_progress = ReadingProgressRepo().get(
                conn,
                book_id=self.config.book.book_id,
                agent_stage=DEFAULT_CLOSE_READING_STAGE,
            )
            if not self.config.runtime.resume_from_checkpoint or existing_close_progress is None:
                ReadingProgressRepo().upsert(
                    conn,
                    {
                        "book_id": self.config.book.book_id,
                        "agent_stage": DEFAULT_CLOSE_READING_STAGE,
                        "current_doc_id": None,
                        "current_document_title_index": None,
                        "current_source_path": None,
                        "current_source_offset": None,
                        "last_completed_doc_id": None,
                        "last_completed_title_index": None,
                        "last_completed_chapter_id": None,
                        "status": {"state": "idle", "last_run_id": run_id},
                        "checkpoint_token": None,
                        "updated_at": _utc_now(),
                    },
                )
            conn.commit()
        return SegmentationRunnerResult(
            book_id=result.book_id,
            db_path=self.db_path,
            inserted_documents=result.inserted_documents,
            batch_count=result.batch_count,
        )

    def _load_resume_checkpoint(self, *, conn, book_id: str, ordered_paths: list[Path]) -> SegmentationResumeCheckpoint:
        if not self.config.runtime.resume_from_checkpoint:
            return SegmentationResumeCheckpoint(source_path=None, source_offset=0, batch_no=1)
        progress = ReadingProgressRepo().get(conn, book_id=book_id, agent_stage=DEFAULT_SEGMENTATION_STAGE)
        if progress is None:
            raise RuntimeError(f"No segmentation checkpoint found for {book_id}")
        source_path = str(progress["current_source_path"] or "").strip()
        if not source_path:
            raise RuntimeError(f"Segmentation checkpoint for {book_id} has no source path")
        if source_path not in {path.as_posix() for path in ordered_paths}:
            raise RuntimeError(f"Checkpoint source path is no longer available: {source_path}")
        source_offset = int(progress["current_source_offset"] or 0)
        status = progress["status_json"]
        last_batch_no = 0
        if isinstance(status, str) and status:
            try:
                import json

                status_payload = json.loads(status)
            except ValueError:
                status_payload = {}
            if isinstance(status_payload, dict):
                last_batch_no = int(status_payload.get("last_batch_no", 0) or 0)
        return SegmentationResumeCheckpoint(
            source_path=source_path,
            source_offset=source_offset,
            batch_no=max(1, last_batch_no + 1),
        )

    def _resolve_ordered_paths(self, *, source_root: Path, read_order) -> list[Path]:
        ordered_paths: list[Path] = []
        for item in read_order:
            path = Path(item.path).expanduser()
            if not path.is_absolute():
                path = source_root / path
            resolved = path.resolve()
            if resolved.exists() and resolved.is_file():
                ordered_paths.append(resolved)
        return ordered_paths

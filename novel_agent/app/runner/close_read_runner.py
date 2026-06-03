from __future__ import annotations

import json
import re
import threading
import time
import uuid
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

from ..constants import DEFAULT_CLOSE_READING_STAGE
from ..llm import InvalidJSONResponseError, JsonModelClient, ModelSettings
from ..prompts.chapter_summary_prompt import build_chapter_summary_prompt
from ..prompts.character_evidence_coverage_prompt import build_character_evidence_coverage_prompt
from ..prompts.character_evidence_prompt import build_character_evidence_prompt
from ..prompts.character_reduce_prompt import build_character_reduce_prompt
from ..prompts.global_memory_prompt import build_global_memory_prompt
from ..prompts.world_evidence_prompt import build_world_evidence_prompt
from ..repos.assets_repo import AssetsRepo
from ..repos.chapters_repo import ChaptersRepo
from ..repos.character_evidence_log_repo import CharacterEvidenceLogRepo
from ..repos.character_profiles_repo import CharacterProfilesRepo
from ..repos.db import NovelAgentDB
from ..repos.documents_repo import DocumentsRepo
from ..repos.reading_progress_repo import ReadingProgressRepo
from ..schemas.config_schema import CloseReadAgentConfig
from ..schemas.prompt_io_schema import (
    CloseReadInputCharacterProfile,
    CloseReadInputDocument,
    CloseReadPromptInput,
    CloseReadTokenBudget,
)
from ..services.chapter_assembler_service import (
    SPLIT_REASON_OVER_BUDGET,
    ChapterAssemblerService,
    ChapterBatch,
)
from ..services.chapter_outline_segment_service import ChapterOutlineSegmentService
from ..services.character_canonical_name_service import CharacterCanonicalNameService
from ..services.character_evidence_batch_assembler_service import CharacterEvidenceBatchAssemblerService
from ..services.character_evidence_validator import CharacterEvidenceValidator
from ..services.character_identity_merge_service import CharacterIdentityMergeService
from ..services.character_identity_resolution_service import CharacterIdentityResolutionService
from ..services.character_mention_service import CharacterMentionService
from ..services.character_profile_brief_service import CharacterProfileBriefService
from ..services.character_profile_service import CharacterProfileService
from ..services.character_roster_service import CharacterRosterService
from ..services.debug_export_service import DebugExportService
from ..services.memory_candidate_service import MemoryCandidateService
from ..services.outline_segment_index_service import OutlineSegmentIndexService
from ..services.outline_service import OutlineService
from ..services.profile_update_gate_service import CharacterImportanceTracker, ProfileUpdateGateService
from ..services.world_state_service import WorldStateService
from ..utils.text_utils import clamp_text, safe_excerpt, split_sentences


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


CHAPTER_SUMMARY_SECTION_ORDER = (
    "摘要元信息",
    "剧情事件链",
    "人物状态/关系变化",
    "关键信息/设定",
    "结构功能/节奏",
)
CHAPTER_SUMMARY_MAX_CHARS = 6000
CHAPTER_SUMMARY_SECTION_ALIASES = {
    "摘要元信息": "摘要元信息",
    "批次元信息": "摘要元信息",
    "剧情事件链": "剧情事件链",
    "剧情推进": "剧情事件链",
    "剧情": "剧情事件链",
    "事件链": "剧情事件链",
    "情节链": "剧情事件链",
    "人物状态/关系变化": "人物状态/关系变化",
    "人物状态": "人物状态/关系变化",
    "人物变化": "人物状态/关系变化",
    "关系变化": "人物状态/关系变化",
    "关键信息/设定": "关键信息/设定",
    "关键信息": "关键信息/设定",
    "设定": "关键信息/设定",
    "结构功能/节奏": "结构功能/节奏",
    "结构功能": "结构功能/节奏",
    "节奏": "结构功能/节奏",
    "剧情节奏": "结构功能/节奏",
}
LOW_SIGNAL_SUMMARY_HINTS = (
    "无具体剧情",
    "无人物行动",
    "无情节推进",
    "基本没有可概括剧情",
    "目录",
    "扉页",
    "献词",
    "题记",
    "版权",
    "出版信息",
    "作者信息",
    "广告",
    "乱码",
)
WORLD_EVIDENCE_KEYWORDS = (
    "世界",
    "时代",
    "规则",
    "禁忌",
    "能力",
    "体系",
    "血统",
    "魔法",
    "学院",
    "阵营",
    "势力",
    "契约",
    "超自然",
)
CHARACTER_EVIDENCE_FAST_ROSTER_LIMIT = 32


@dataclass(slots=True)
class CloseReadRunnerResult:
    book_id: str
    processed_batches: int
    exported_markdown: Path | None
    batch_metrics: list[dict[str, Any]]


@dataclass(slots=True)
class _PreparedCloseReadExtraction:
    batch: ChapterBatch
    prompt_input: CloseReadPromptInput
    existing_character_roster: list[dict[str, Any]]
    full_existing_character_roster: list[dict[str, Any]]


@dataclass(slots=True)
class _CloseReadExtractionResult:
    batch: ChapterBatch
    prompt_input: CloseReadPromptInput
    summary_payload: dict[str, Any]
    evidence_payload: dict[str, Any]
    world_evidence_payload: dict[str, Any]


class _RetryCloseReadBatch(Exception):
    def __init__(self, batch: ChapterBatch) -> None:
        super().__init__("Retry close-read extraction with a smaller batch")
        self.batch = batch


class InvalidChapterSynopsisError(RuntimeError):
    def __init__(self, message: str, *, review_path: Path | None = None) -> None:
        self.review_path = review_path
        if review_path is not None:
            message = f"{message} Review written to: {review_path}"
        super().__init__(message)


class CloseReadIdentityMergeBlocked(RuntimeError):
    def __init__(self, candidates: list[dict[str, Any]]) -> None:
        self.candidates = candidates
        labels = ", ".join(
            f"{item.get('left_name', '')}/{item.get('right_name', '')}:{item.get('same_person_score', 0)}"
            for item in candidates[:3]
        )
        super().__init__(f"Close-read paused for character identity merge review: {labels}")


class CloseReadRunner:
    def __init__(
        self,
        *,
        repo_root: Path,
        db_path: Path,
        config: CloseReadAgentConfig,
        progress_callback: Callable[[dict[str, Any]], None] | None = None,
        should_stop: Callable[[], bool] | None = None,
    ) -> None:
        self.repo_root = repo_root
        self.db_path = db_path
        self.config = config
        self.progress_callback = progress_callback
        self.should_stop = should_stop or (lambda: False)
        self.character_mention_service = CharacterMentionService()
        self.character_evidence_validator = CharacterEvidenceValidator()
        self.memory_candidate_service = MemoryCandidateService(
            character_mention_service=self.character_mention_service,
        )
        self.profile_update_gate_service = ProfileUpdateGateService(
            tracker=CharacterImportanceTracker(
                detailed_min_doc_count=self.config.runtime.profile_update_detailed_min_doc_count,
                detailed_min_total_chars=self.config.runtime.profile_update_detailed_min_total_chars,
                name_normalizer=lambda value, character=None: self.memory_candidate_service.clean_evidence_name(
                    value,
                    character=character,
                ),
            )
        )
        self.profile_brief_service = CharacterProfileBriefService()
        self.character_evidence_log_repo = CharacterEvidenceLogRepo()
        self._summary_review_lock = threading.Lock()

    def _emit_progress(self, event: dict[str, Any]) -> None:
        if self.progress_callback is not None:
            self.progress_callback(event)

    def run(self) -> CloseReadRunnerResult:
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
                retry_without_thinking_on_failure=True,
                thinking=self.config.model.thinking,
                reasoning_effort=self.config.model.reasoning_effort,
                include_reasoning_content=self.config.model.include_reasoning_content,
                dry_run=self.config.runtime.dry_run,
            )
        )
        documents_repo = DocumentsRepo()
        progress_repo = ReadingProgressRepo()
        chapters_repo = ChaptersRepo()
        profiles_repo = CharacterProfilesRepo()
        profile_service = CharacterProfileService(profiles_repo=profiles_repo)
        identity_merge_service = CharacterIdentityMergeService(profiles_repo=profiles_repo)
        identity_resolution_service = CharacterIdentityResolutionService(profiles_repo=profiles_repo)
        canonical_name_service = CharacterCanonicalNameService(profiles_repo=profiles_repo)
        roster_service = CharacterRosterService(profiles_repo=profiles_repo)
        assembler = ChapterAssemblerService(
            documents_repo=documents_repo,
            progress_repo=progress_repo,
            document_chars_budget=self.config.runtime.document_chars_budget,
            progress_stage=DEFAULT_CLOSE_READING_STAGE,
        )
        world_service = WorldStateService(repo_root=self.repo_root, model_client=model_client)
        outline_service = OutlineService(repo_root=self.repo_root)
        outline_segment_index_service = OutlineSegmentIndexService(repo_root=self.repo_root, model_client=model_client)
        processed_batches = 0
        batch_metrics: list[dict[str, Any]] = []
        export_path: Path | None = None
        with db.connect() as conn:
            db.init_schema(conn)
            total_documents = self._count_documents(conn, book_id=self.config.book_id)
            assets = AssetsRepo().get(conn, book_id=self.config.book_id)
            world_path, world_summary_path = world_service.ensure_paths(self.config.book_id)
            outline_path = outline_service.ensure_path(self.config.book_id)
            if assets is None:
                AssetsRepo().upsert(
                    conn,
                    {
                        "book_id": self.config.book_id,
                        "source_root": "",
                        "world_markdown_path": world_path.as_posix(),
                        "world_summary_path": world_summary_path.as_posix(),
                        "outline_markdown_path": outline_path.as_posix(),
                        "debug_export_path": str((self.repo_root / ".memory" / "debug" / f"{self.config.book_id}.sqlite.md").as_posix()),
                        "created_at": _utc_now(),
                        "updated_at": _utc_now(),
                    },
                )
                assets = AssetsRepo().get(conn, book_id=self.config.book_id)
            if assets is None:
                raise RuntimeError(f"Failed to initialize book assets for {self.config.book_id}")

            run_id = uuid.uuid4().hex
            while True:
                if self.should_stop():
                    self._emit_progress(
                        {
                            "stage": DEFAULT_CLOSE_READING_STAGE,
                            "event": "cancelled",
                            "processed_batches": processed_batches,
                            "total_documents": total_documents,
                            "completed_documents": self._count_completed_documents(conn, book_id=self.config.book_id),
                        }
                    )
                    break
                if self.config.runtime.max_chapters is not None and processed_batches >= self.config.runtime.max_chapters:
                    break
                window_limit = self._extraction_window_limit(processed_batches=processed_batches)
                batches = assembler.load_next_batches(
                    conn,
                    book_id=self.config.book_id,
                    limit=window_limit,
                )
                if not batches:
                    break
                while True:
                    if self.should_stop():
                        break
                    prepared_extractions = [
                        self._prepare_extraction(
                            conn=conn,
                            batch=batch,
                            outline_path=Path(str(assets["outline_markdown_path"])),
                            world_summary_path=Path(str(assets["world_summary_path"])),
                            profile_service=profile_service,
                            roster_service=roster_service,
                        )
                        for batch in batches
                    ]
                    try:
                        extraction_results = self._run_close_read_extraction_window(
                            model_client=model_client,
                            prepared_extractions=prepared_extractions,
                        )
                        break
                    except _RetryCloseReadBatch as retry:
                        batches = [retry.batch]
                if self.should_stop():
                    continue

                for extraction in extraction_results:
                    if self.should_stop():
                        self._emit_progress(
                            {
                                "stage": DEFAULT_CLOSE_READING_STAGE,
                                "event": "cancelled",
                                "processed_batches": processed_batches,
                                "total_documents": total_documents,
                                "completed_documents": self._count_completed_documents(conn, book_id=self.config.book_id),
                            }
                        )
                        break
                    if self.config.runtime.max_chapters is not None and processed_batches >= self.config.runtime.max_chapters:
                        break
                    batch = extraction.batch
                    completed_before = self._count_completed_documents(conn, book_id=self.config.book_id)
                    self._emit_progress(
                        {
                            "stage": DEFAULT_CLOSE_READING_STAGE,
                            "event": "batch_start",
                            "batch_index": processed_batches + 1,
                            "document_title_index": batch.document_title_index,
                            "document_title_indexes": batch.title_indexes,
                            "chapter_title": batch.chapter_title,
                            "doc_count": len(batch.documents),
                            "first_doc_id": batch.documents[0].doc_id,
                            "last_doc_id": batch.documents[-1].doc_id,
                            "total_chars": batch.total_chars,
                            "total_documents": total_documents,
                            "completed_documents": completed_before,
                        }
                    )
                    prompt_input = self._prepare_extraction(
                        conn=conn,
                        batch=batch,
                        outline_path=Path(str(assets["outline_markdown_path"])),
                        world_summary_path=Path(str(assets["world_summary_path"])),
                        profile_service=profile_service,
                        roster_service=roster_service,
                    ).prompt_input
                    payload = self._run_close_read_memory_agents(
                        conn=conn,
                        model_client=model_client,
                        batch=batch,
                        prompt_input=prompt_input,
                        summary_payload=extraction.summary_payload,
                        evidence_payload=extraction.evidence_payload,
                        world_evidence_payload=extraction.world_evidence_payload,
                        profile_service=profile_service,
                    )
                    chapter_id: int | None = None
                    for persist_batch, persist_payload in self._iter_persistable_payloads(batch=batch, payload=payload):
                        chapter_id = self._persist_batch(
                            conn=conn,
                            batch=persist_batch,
                            payload=persist_payload,
                            run_id=run_id,
                            model_client=model_client,
                            documents_repo=documents_repo,
                            chapters_repo=chapters_repo,
                            progress_repo=progress_repo,
                            profile_service=profile_service,
                            identity_merge_service=identity_merge_service,
                            identity_resolution_service=identity_resolution_service,
                            canonical_name_service=canonical_name_service,
                            world_service=world_service,
                            outline_service=outline_service,
                        )
                    if chapter_id is None:
                        raise RuntimeError("Close-read batch produced no persistable chapter payloads")
                    progress_repo.upsert(
                        conn,
                        {
                            "book_id": self.config.book_id,
                            "agent_stage": DEFAULT_CLOSE_READING_STAGE,
                            "current_doc_id": None,
                            "current_document_title_index": batch.documents[-1].document_title_index,
                            "current_source_path": batch.documents[-1].source_path,
                            "current_source_offset": batch.documents[-1].source_end_offset,
                            "last_completed_doc_id": batch.documents[-1].doc_id,
                            "last_completed_title_index": batch.documents[-1].document_title_index,
                            "last_completed_chapter_id": chapter_id,
                            "status": {"state": "processed_batch", "last_run_id": run_id},
                            "checkpoint_token": f"{batch.documents[-1].document_title_index}:{batch.documents[-1].doc_id}",
                            "updated_at": _utc_now(),
                        },
                    )
                    conn.commit()
                    outline_segment_index_service.refresh(conn, book_id=self.config.book_id)
                    processed_batches += 1
                    completed_after = self._count_completed_documents(conn, book_id=self.config.book_id)
                    batch_metrics.append(
                        {
                            "batch_index": processed_batches,
                            "document_title_index": batch.document_title_index,
                            "document_title_indexes": batch.title_indexes,
                            "chapter_title": batch.chapter_title,
                            "doc_count": len(batch.documents),
                            "total_chars": batch.total_chars,
                            "total_kb": round(batch.total_chars / 1024, 2),
                            "is_complete_chapter": batch.is_complete_chapter,
                            "batch_label": batch.batch_label,
                            "split_reason": batch.split_reason,
                            "first_doc_id": batch.documents[0].doc_id,
                            "last_doc_id": batch.documents[-1].doc_id,
                        }
                    )
                    self._emit_progress(
                        {
                            "stage": DEFAULT_CLOSE_READING_STAGE,
                            "event": "batch_done",
                            "batch_index": processed_batches,
                            "document_title_index": batch.document_title_index,
                            "document_title_indexes": batch.title_indexes,
                            "chapter_title": batch.chapter_title,
                            "doc_count": len(batch.documents),
                            "first_doc_id": batch.documents[0].doc_id,
                            "last_doc_id": batch.documents[-1].doc_id,
                            "total_chars": batch.total_chars,
                            "total_documents": total_documents,
                            "completed_documents": completed_after,
                            "processed_batches": processed_batches,
                        }
                    )
            if self.config.runtime.export_debug_markdown:
                target = (
                    Path(self.config.runtime.debug_markdown_path).expanduser().resolve()
                    if self.config.runtime.debug_markdown_path
                    else Path(str(assets["debug_export_path"])).expanduser().resolve()
                )
                export_path = DebugExportService().export(conn, book_id=self.config.book_id, output_path=target)
                conn.commit()
        return CloseReadRunnerResult(
            book_id=self.config.book_id,
            processed_batches=processed_batches,
            exported_markdown=export_path,
            batch_metrics=batch_metrics,
        )

    def _extraction_window_limit(self, *, processed_batches: int) -> int:
        configured = max(1, int(self.config.runtime.close_read_extraction_window_count))
        if self.config.runtime.max_chapters is None:
            return configured
        remaining = max(0, int(self.config.runtime.max_chapters) - processed_batches)
        return max(1, min(configured, remaining))

    @staticmethod
    def _count_documents(conn, *, book_id: str) -> int:
        row = conn.execute("SELECT COUNT(*) FROM documents WHERE book_id = ?", (book_id,)).fetchone()
        return int(row[0] or 0) if row is not None else 0

    @staticmethod
    def _count_completed_documents(conn, *, book_id: str) -> int:
        progress = conn.execute(
            """
            SELECT last_completed_doc_id
            FROM reading_progress
            WHERE book_id = ? AND agent_stage = ?
            """,
            (book_id, DEFAULT_CLOSE_READING_STAGE),
        ).fetchone()
        if progress is None or progress["last_completed_doc_id"] is None:
            return 0
        row = conn.execute(
            "SELECT COUNT(*) FROM documents WHERE book_id = ? AND doc_id <= ?",
            (book_id, int(progress["last_completed_doc_id"] or 0)),
        ).fetchone()
        return int(row[0] or 0) if row is not None else 0

    @staticmethod
    def _last_completed_doc_id(conn, *, book_id: str) -> int | None:
        row = conn.execute(
            "SELECT last_completed_doc_id FROM reading_progress WHERE book_id = ? AND agent_stage = ?",
            (book_id, DEFAULT_CLOSE_READING_STAGE),
        ).fetchone()
        return int(row["last_completed_doc_id"]) if row is not None and row["last_completed_doc_id"] is not None else None

    @staticmethod
    def _last_completed_title_index(conn, *, book_id: str) -> int | None:
        row = conn.execute(
            "SELECT last_completed_title_index FROM reading_progress WHERE book_id = ? AND agent_stage = ?",
            (book_id, DEFAULT_CLOSE_READING_STAGE),
        ).fetchone()
        return int(row["last_completed_title_index"]) if row is not None and row["last_completed_title_index"] is not None else None

    @staticmethod
    def _last_completed_chapter_id(conn, *, book_id: str) -> int | None:
        row = conn.execute(
            "SELECT last_completed_chapter_id FROM reading_progress WHERE book_id = ? AND agent_stage = ?",
            (book_id, DEFAULT_CLOSE_READING_STAGE),
        ).fetchone()
        return int(row["last_completed_chapter_id"]) if row is not None and row["last_completed_chapter_id"] is not None else None

    def _prepare_extraction(
        self,
        *,
        conn,
        batch: ChapterBatch,
        outline_path: Path,
        world_summary_path: Path,
        profile_service: CharacterProfileService,
        roster_service: CharacterRosterService,
    ) -> _PreparedCloseReadExtraction:
        local_character_hints: dict[int, list[str]] = {}
        return _PreparedCloseReadExtraction(
            batch=batch,
            prompt_input=self._build_prompt_input(
                conn=conn,
                batch=batch,
                local_character_hints=local_character_hints,
                outline_path=outline_path,
                world_summary_path=world_summary_path,
                profile_service=profile_service,
            ),
            existing_character_roster=roster_service.load_recent_roster(
                conn,
                book_id=self.config.book_id,
                max_names=CHARACTER_EVIDENCE_FAST_ROSTER_LIMIT,
            ),
            full_existing_character_roster=roster_service.load_recent_roster(conn, book_id=self.config.book_id),
        )

    def _split_batch_for_retry(self, batch: ChapterBatch) -> ChapterBatch | None:
        if len(batch.documents) <= 1:
            return None
        half_chars = max(1, batch.total_chars // 2)
        selected = []
        current_chars = 0
        for doc in batch.documents:
            if selected and current_chars >= half_chars:
                break
            selected.append(doc)
            current_chars += doc.content_chars
        if not selected or len(selected) >= len(batch.documents):
            return None
        return ChapterBatch(
            document_title_index=batch.document_title_index,
            chapter_title=batch.chapter_title,
            documents=selected,
            is_complete_chapter=False,
            chapter_doc_count=batch.chapter_doc_count or len(batch.documents),
            chapter_total_chars=batch.chapter_total_chars or batch.total_chars,
            batch_doc_start_index=batch.batch_doc_start_index,
            split_reason=SPLIT_REASON_OVER_BUDGET,
        )

    def _build_prompt_input(
        self,
        *,
        conn,
        batch: ChapterBatch,
        local_character_hints: dict[int, list[str]],
        outline_path: Path,
        world_summary_path: Path,
        profile_service: CharacterProfileService,
    ) -> CloseReadPromptInput:
        _ = local_character_hints
        token_budget = CloseReadTokenBudget(document_chars_budget=self.config.runtime.document_chars_budget)
        names: list[str] = []
        character_profiles = [
            CloseReadInputCharacterProfile(**item)
            for item in self._load_character_profiles_with_budget(
                conn,
                profile_service=profile_service,
                names=names,
                chars_budget=token_budget.character_profiles_chars_budget,
            )
        ]
        summary_target_chars_min = self._compute_summary_target_chars_min(batch.total_chars)
        title_indexes = batch.title_indexes
        chapter_title = batch.chapter_title
        if len(title_indexes) > 1:
            chapter_title = f"多章批次 {title_indexes[0]}-{title_indexes[-1]}"
        return CloseReadPromptInput(
            book_id=self.config.book_id,
            current_title_index=batch.document_title_index,
            chapter_title=chapter_title,
            source_total_chars=batch.total_chars,
            summary_target_chars_min=summary_target_chars_min,
            documents=[
                CloseReadInputDocument(
                    doc_id=doc.doc_id,
                    document_title_index=doc.document_title_index,
                    content=doc.content,
                    character_keywords=[],
                    content_tags=doc.content_tags,
                )
                for doc in batch.documents
            ],
            story_outline_md=clamp_text(
                outline_path.read_text(encoding="utf-8", errors="replace"),
                token_budget.outline_chars_budget,
            ),
            world_summary_md=clamp_text(
                world_summary_path.read_text(encoding="utf-8", errors="replace"),
                token_budget.world_summary_chars_budget,
            ),
            character_profiles=character_profiles,
            token_budget=token_budget,
        )

    def _run_close_read_agents(
        self,
        *,
        model_client: JsonModelClient,
        batch: ChapterBatch,
        prompt_input: CloseReadPromptInput,
    ) -> dict[str, Any]:
        extraction = self._run_close_read_extraction_window(
            model_client=model_client,
            prepared_extractions=[
                _PreparedCloseReadExtraction(
                    batch=batch,
                    prompt_input=prompt_input,
                    existing_character_roster=[],
                    full_existing_character_roster=[],
                )
            ],
        )[0]
        return self._run_close_read_memory_agents(
            conn=None,
            model_client=model_client,
            batch=batch,
            prompt_input=prompt_input,
            summary_payload=extraction.summary_payload,
            evidence_payload=extraction.evidence_payload,
            world_evidence_payload=extraction.world_evidence_payload,
            profile_service=None,
        )

    def _run_close_read_extraction_window(
        self,
        *,
        model_client: JsonModelClient,
        prepared_extractions: list[_PreparedCloseReadExtraction],
    ) -> list[_CloseReadExtractionResult]:
        if not prepared_extractions:
            return []
        max_workers = max(1, int(self.config.runtime.close_read_extraction_max_workers))
        results_by_index: dict[int, _CloseReadExtractionResult] = {}
        with ThreadPoolExecutor(max_workers=max_workers) as executor:
            summary_futures = {}
            evidence_futures: dict[int, list[tuple[int, Any]]] = {}
            world_futures: dict[int, Any] = {}
            for index, prepared in enumerate(prepared_extractions):
                batch = prepared.batch
                prompt_dict = prepared.prompt_input.to_dict()
                prompt_dict["existing_character_roster"] = prepared.existing_character_roster
                prompt_dict["full_existing_character_roster"] = prepared.full_existing_character_roster
                summary_futures[index] = executor.submit(
                    self._generate_chapter_summary_payload,
                    model_client=model_client,
                    batch=batch,
                    prompt_input=prompt_dict,
                )
                evidence_futures[index] = []
                for doc in batch.documents:
                    doc_batch = self._as_single_document_batch(batch=batch, doc=doc)
                    evidence_futures[index].append(
                        (
                            int(doc.doc_id),
                            executor.submit(
                                self._generate_character_evidence_payload,
                                model_client=model_client,
                                batch=doc_batch,
                                prompt_input=prompt_dict,
                            ),
                        )
                    )
                if self._should_prefetch_world_evidence(batch=batch):
                    world_futures[index] = executor.submit(
                        self._generate_agent_payload,
                        model_client=model_client,
                        batch=batch,
                        prompt_input=self._build_world_evidence_input(batch=batch, prompt_input=prompt_dict),
                        agent_name="world_evidence",
                        prompt_builder=build_world_evidence_prompt,
                        fallback_factory=lambda batch=batch: self._fallback_world_evidence_output(batch),
                    )

            summary_payloads: dict[int, dict[str, Any]] = {}
            evidence_payloads: dict[int, dict[str, Any]] = {}
            for index, prepared in enumerate(prepared_extractions):
                batch = prepared.batch
                summary_payloads[index] = self._result_or_retry(summary_futures[index], batch=batch)
                evidence_payloads[index] = self._combine_character_evidence_payloads(
                    batch=batch,
                    evidence_payloads=[
                        (
                            doc_id,
                            self._result_or_retry(
                                future,
                                batch=self._as_single_document_batch(batch=batch, doc_id=doc_id),
                            ),
                        )
                        for doc_id, future in evidence_futures[index]
                    ],
                )
                prompt_dict = prepared.prompt_input.to_dict()
                prompt_dict["existing_character_roster"] = prepared.existing_character_roster
                prompt_dict["full_existing_character_roster"] = prepared.full_existing_character_roster
                evidence_payloads[index] = self._augment_character_evidence_with_coverage(
                    model_client=model_client,
                    batch=batch,
                    prompt_input=prompt_dict,
                    summary_payload=summary_payloads[index],
                    evidence_payload=evidence_payloads[index],
                )

            for index, prepared in enumerate(prepared_extractions):
                if index in world_futures:
                    continue
                batch = prepared.batch
                summary_payload = summary_payloads[index]
                if self._should_run_world_evidence(batch=batch, summary_payload=summary_payload):
                    world_futures[index] = executor.submit(
                        self._generate_agent_payload,
                        model_client=model_client,
                        batch=batch,
                        prompt_input=self._build_world_evidence_input(
                            batch=batch,
                            prompt_input=prepared.prompt_input.to_dict(),
                        ),
                        agent_name="world_evidence",
                        prompt_builder=build_world_evidence_prompt,
                        fallback_factory=lambda batch=batch: self._fallback_world_evidence_output(batch),
                    )

            for index, prepared in enumerate(prepared_extractions):
                batch = prepared.batch
                world_evidence_payload = (
                    self._result_or_retry(world_futures[index], batch=batch)
                    if index in world_futures
                    else {}
                )
                results_by_index[index] = _CloseReadExtractionResult(
                    batch=batch,
                    prompt_input=prepared.prompt_input,
                    summary_payload=summary_payloads[index],
                    evidence_payload=evidence_payloads[index],
                    world_evidence_payload=world_evidence_payload,
                )
        return [results_by_index[index] for index in range(len(prepared_extractions))]

    def _run_close_read_memory_agents(
        self,
        *,
        conn,
        model_client: JsonModelClient,
        batch: ChapterBatch,
        prompt_input: CloseReadPromptInput,
        summary_payload: dict[str, Any],
        evidence_payload: dict[str, Any],
        world_evidence_payload: dict[str, Any],
        profile_service: CharacterProfileService | None,
    ) -> dict[str, Any]:
        prompt_dict = prompt_input.to_dict()
        if conn is not None and profile_service is not None:
            prompt_dict = self._with_character_profiles_for_evidence(
                conn=conn,
                model_client=model_client,
                prompt_input=prompt_dict,
                evidence_payload=evidence_payload,
                profile_service=profile_service,
                batch=batch,
            )
        current_outline_segment: dict[str, Any] = {}
        if not batch.is_multi_chapter:
            summary_md = str(summary_payload.get("chapter_summary_md") or "").strip()
            summary_short = str(summary_payload.get("chapter_summary_short") or "").strip()
            generated_outline_update = self._generate_chapter_outline_segment(
                model_client=model_client,
                batch=batch,
                summary_md=summary_md,
                summary_short=summary_short,
                outline_update={},
            )
            current_outline_segment = self._enrich_outline_segment_update(
                batch=batch,
                outline_update=generated_outline_update,
                summary_short=summary_short,
            )
        character_reduce_payload = {"character_updates": []}
        global_memory_payload = self._generate_agent_payload(
            model_client=model_client,
            batch=batch,
            prompt_input=self._build_global_memory_input(
                prompt_input=prompt_dict,
                summary_payload=summary_payload,
                world_evidence_payload=world_evidence_payload,
            ),
            agent_name="global_memory",
            prompt_builder=build_global_memory_prompt,
            fallback_factory=lambda: self._fallback_global_memory_output(summary_payload, world_evidence_payload),
        )
        return self._compose_close_read_payload(
            batch=batch,
            summary_payload=summary_payload,
            evidence_payload=evidence_payload,
            character_reduce_payload=character_reduce_payload,
            global_memory_payload=global_memory_payload,
            current_outline_segment=current_outline_segment,
        )

    def _result_or_retry(self, future, *, batch: ChapterBatch) -> dict[str, Any]:
        try:
            return future.result()
        except InvalidJSONResponseError:
            smaller_batch = self._split_batch_for_retry(batch)
            if smaller_batch is not None:
                raise _RetryCloseReadBatch(smaller_batch) from None
            raise
        except InvalidChapterSynopsisError as exc:
            if not self._should_retry_invalid_synopsis(batch=batch, error=exc):
                raise
            smaller_batch = self._split_batch_for_retry(batch)
            if smaller_batch is not None:
                raise _RetryCloseReadBatch(smaller_batch) from None
            raise

    def _as_single_document_batch(
        self,
        *,
        batch: ChapterBatch,
        doc=None,
        doc_id: int | None = None,
    ) -> ChapterBatch:
        if doc is None:
            candidates = [item for item in batch.documents if int(item.doc_id) == int(doc_id or 0)]
            if not candidates:
                raise ValueError(f"No document {doc_id} in batch")
            doc = candidates[0]
        return ChapterBatch(
            document_title_index=int(doc.document_title_index),
            chapter_title=str(doc.document_title),
            documents=[doc],
            is_complete_chapter=batch.is_complete_chapter and len(batch.documents) == 1,
            chapter_doc_count=batch.chapter_doc_count or len(batch.documents),
            chapter_total_chars=batch.chapter_total_chars or batch.total_chars,
            batch_doc_start_index=batch.batch_doc_start_index,
            split_reason=batch.split_reason,
        )

    @staticmethod
    def _should_retry_invalid_synopsis(*, batch: ChapterBatch, error: InvalidChapterSynopsisError) -> bool:
        return batch.is_multi_chapter and "multi-chapter batch missing chapter_summaries" in str(error)

    def _combine_character_evidence_payloads(
        self,
        *,
        batch: ChapterBatch,
        evidence_payloads: list[tuple[int, dict[str, Any]]],
    ) -> dict[str, Any]:
        evidence_batches: list[dict[str, Any]] = []
        for fallback_doc_id, payload in evidence_payloads:
            nested_batches = payload.get("character_evidence_batches")
            if isinstance(nested_batches, list):
                evidence_batches.extend(item for item in nested_batches if isinstance(item, dict))
                continue
            doc_ids = payload.get("doc_ids")
            if not isinstance(doc_ids, list) or not doc_ids:
                raw_doc_id = payload.get("doc_id", fallback_doc_id)
                doc_ids = [int(raw_doc_id)] if raw_doc_id is not None else []
            title_indexes = payload.get("document_title_indexes")
            if not isinstance(title_indexes, list) or not title_indexes:
                raw_title_index = payload.get("document_title_index")
                title_indexes = [int(raw_title_index)] if raw_title_index is not None else []
            evidence_batches.append(
                {
                    "doc_ids": doc_ids,
                    "document_title_indexes": title_indexes,
                    "characters": payload.get("characters", []),
                    "identity_revelations": payload.get("identity_revelations", []),
                }
            )
        doc_ids = [int(doc.doc_id) for doc in batch.documents]
        return {
            "doc_ids": doc_ids,
            "document_title_indexes": batch.title_indexes,
            "character_evidence_batches": evidence_batches,
            "identity_revelations": self._flatten_identity_revelations({"character_evidence_batches": evidence_batches}),
        }

    def _with_character_profiles_for_evidence(
        self,
        *,
        conn,
        model_client: JsonModelClient,
        prompt_input: dict[str, Any],
        evidence_payload: dict[str, Any],
        profile_service: CharacterProfileService,
        batch: ChapterBatch | None = None,
    ) -> dict[str, Any]:
        profile_contexts = self._load_character_profile_contexts_for_evidence(
            conn=conn,
            model_client=model_client,
            evidence_payload=evidence_payload,
            profile_service=profile_service,
            current_total_chars=batch.total_chars if batch is not None else 0,
        )
        if not profile_contexts:
            return prompt_input
        merged = dict(prompt_input)
        existing_profiles = [
            item for item in prompt_input.get("character_profiles", []) if isinstance(item, dict)
        ]
        by_key: dict[str, dict[str, Any]] = {}
        for profile in [*existing_profiles, *profile_contexts]:
            key = self._profile_context_identity_key(profile)
            if not key:
                continue
            by_key[key] = profile
        merged["character_profiles"] = list(by_key.values())
        return merged

    def _load_character_profile_contexts_for_evidence(
        self,
        *,
        conn,
        model_client: JsonModelClient,
        evidence_payload: dict[str, Any],
        profile_service: CharacterProfileService,
        current_total_chars: int = 0,
    ) -> list[dict[str, Any]]:
        _ = model_client
        character_ids: list[int] = []
        names: list[str] = []
        for character in self._flatten_character_evidence_items(evidence_payload):
            if not isinstance(character, dict):
                continue
            character_id = self._safe_int(character.get("character_id"))
            if character_id is not None and character_id > 0 and character_id not in character_ids:
                character_ids.append(character_id)
            name = self.memory_candidate_service.clean_evidence_name(
                character.get("canonical_name"),
                character=character,
            )
            if name and name not in names:
                names.append(name)
            aliases = character.get("aliases", [])
            if isinstance(aliases, list):
                for alias in aliases:
                    alias_name = self.memory_candidate_service.clean_evidence_name(alias, character=character)
                    if alias_name and alias_name not in names:
                        names.append(alias_name)
        if not character_ids and not names:
            return []
        repo = profile_service.profiles_repo
        rows = [
            *repo.list_by_ids(conn, book_id=self.config.book_id, character_ids=character_ids),
            *repo.list_by_names(conn, book_id=self.config.book_id, names=names),
        ]
        profile_gates = self._profile_update_gates_for_evidence(
            evidence_payload=evidence_payload,
            current_total_chars=current_total_chars,
        )
        contexts: list[dict[str, Any]] = []
        seen_ids: set[int] = set()
        seen_names: set[str] = set()
        for row in rows:
            row_id = self._safe_int(row["character_id"])
            row_name = str(row["canonical_name"] or "").strip()
            if row_id is not None and row_id in seen_ids:
                continue
            if row_id is None and row_name in seen_names:
                continue
            if row_id is not None:
                seen_ids.add(row_id)
            seen_names.add(row_name)
            full_profile = self._profile_context_from_row(row)
            update_gate = self._profile_update_gate_for_profile(
                full_profile,
                profile_gates=profile_gates,
            )
            contexts.append(
                {
                    "character_id": full_profile["character_id"],
                    "canonical_name": full_profile["canonical_name"],
                    "aliases": full_profile["aliases"],
                    "profile_brief": full_profile.get("profile_brief") or {},
                    "profile_brief_status": full_profile.get("profile_brief_status") or "missing",
                    "character_update_gate": update_gate,
                }
            )
        return contexts

    def _profile_update_gates_for_evidence(
        self,
        *,
        evidence_payload: dict[str, Any],
        current_total_chars: int = 0,
    ) -> dict[str, dict[str, Any]]:
        return self.profile_update_gate_service.gates_for_evidence(
            evidence_payload=evidence_payload,
            current_total_chars=current_total_chars,
        )

    def _profile_update_gate_for_profile(
        self,
        profile: dict[str, Any],
        *,
        profile_gates: dict[str, dict[str, Any]],
    ) -> dict[str, Any]:
        return self.profile_update_gate_service.gate_for_profile(
            profile,
            profile_gates=profile_gates,
        )

    def _profile_context_from_row(self, row) -> dict[str, Any]:
        profile_brief = (
            self._load_json_dict(row["profile_brief_json"])
            if self._row_has_column(row, "profile_brief_json")
            else {}
        )
        return {
            "character_id": str(row["character_id"]),
            "canonical_name": str(row["canonical_name"] or "").strip(),
            "aliases": self._load_json_list(row["aliases_json"]),
            "profile_brief": profile_brief,
            "profile_brief_status": (
                str(row["profile_brief_status"] or "").strip()
                if self._row_has_column(row, "profile_brief_status")
                else ""
            ) or ("ready" if profile_brief else "missing"),
            "speaking_character_status": str(row["speaking_character_status"] or "unknown"),
            "personhood_evidence_summary": str(row["personhood_evidence_summary"] or ""),
            "evidence_level": str(row["evidence_level"] or "inferred"),
            "story_events": self._load_json_list(row["story_events_json"]),
            "mentioned_doc_ids": self._load_json_list(row["mentioned_doc_ids_json"]),
            "speaking_doc_ids": self._load_json_list(row["speaking_doc_ids_json"]),
            "last_seen_doc_id": row["last_seen_doc_id"],
            "last_seen_title_index": row["last_seen_title_index"],
            "importance_score": int(row["importance_score"] or 0),
        }

    def _profile_context_identity_key(self, profile: dict[str, Any]) -> str:
        character_id = str(profile.get("character_id") or "").strip()
        if character_id:
            return f"id:{character_id}"
        canonical_name = str(profile.get("canonical_name") or "").strip()
        return f"name:{canonical_name}" if canonical_name else ""

    def _character_evidence_identity_key(self, character: dict[str, Any]) -> str:
        character_id = str(character.get("character_id") or "").strip()
        if character_id:
            return f"id:{character_id}"
        name = self.memory_candidate_service.clean_evidence_name(
            character.get("canonical_name"),
            character=character,
        )
        return f"name:{name}" if name else ""

    def _run_character_reduce_agents(
        self,
        *,
        model_client: JsonModelClient,
        batch: ChapterBatch,
        prompt_input: dict[str, Any],
        summary_payload: dict[str, Any],
        evidence_payload: dict[str, Any],
        current_outline_segment: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        reduce_inputs = self.memory_candidate_service.build_character_reduce_inputs(
            prompt_input=prompt_input,
            summary_payload=summary_payload,
            evidence_payload=evidence_payload,
            current_outline_segment=current_outline_segment or {},
        )
        if not reduce_inputs:
            return {"character_updates": []}
        outputs: list[dict[str, Any]] = []
        index_only_inputs = [
            reduce_input
            for reduce_input in reduce_inputs
            if str((reduce_input.get("reduce_policy") or {}).get("detail_level") or "").strip() == "index_only"
            or str((reduce_input.get("profile_update_gate") or {}).get("update_policy") or "").strip()
            in {"defer_index_only", "drop_for_profile"}
        ]
        model_reduce_inputs = [reduce_input for reduce_input in reduce_inputs if reduce_input not in index_only_inputs]
        for reduce_input in index_only_inputs:
            outputs.append(
                self.memory_candidate_service.build_index_only_reduce_output(
                    reduce_input=reduce_input,
                )
            )
        if not model_reduce_inputs:
            return self.memory_candidate_service.normalize_character_reduce_outputs(outputs)
        max_workers = max(1, min(int(self.config.runtime.character_reduce_max_workers), len(model_reduce_inputs)))
        with ThreadPoolExecutor(max_workers=max_workers) as executor:
            futures = [
                executor.submit(
                    self._generate_agent_payload,
                    model_client=model_client,
                    batch=batch,
                    prompt_input=reduce_input,
                    agent_name="character_reduce",
                    prompt_builder=build_character_reduce_prompt,
                    fallback_factory=lambda reduce_input=reduce_input: (
                        self.memory_candidate_service.build_character_reduce_fallback_output(
                            reduce_input=reduce_input,
                        )
                    ),
                )
                for reduce_input in model_reduce_inputs
            ]
            for future in futures:
                outputs.append(future.result())
        return self.memory_candidate_service.normalize_character_reduce_outputs(outputs)

    def _prompt_input_metrics(self, prompt_input: dict[str, Any]) -> dict[str, int]:
        metrics: dict[str, int] = {}
        existing_profile = prompt_input.get("existing_profile")
        if isinstance(existing_profile, dict):
            profile_brief = existing_profile.get("profile_brief")
            if isinstance(profile_brief, dict):
                metrics["profile_brief_chars"] = len(
                    json.dumps(profile_brief, ensure_ascii=False, separators=(",", ":"))
                )
            metrics["existing_profile_chars"] = len(
                json.dumps(existing_profile, ensure_ascii=False, separators=(",", ":"))
            )
        chapter_context = prompt_input.get("chapter_context_text")
        if chapter_context is None and isinstance(prompt_input.get("chapter_summary"), dict):
            chapter_context = prompt_input["chapter_summary"].get("chapter_context_text")
        if chapter_context is not None:
            metrics["chapter_context_chars"] = len(str(chapter_context))
        if isinstance(prompt_input.get("current_outline_segment"), dict):
            metrics["current_outline_segment_chars"] = len(
                json.dumps(prompt_input["current_outline_segment"], ensure_ascii=False, separators=(",", ":"))
            )
        if isinstance(prompt_input.get("ordered_character_evidence"), list):
            metrics["ordered_character_evidence_chars"] = len(
                json.dumps(prompt_input["ordered_character_evidence"], ensure_ascii=False, separators=(",", ":"))
            )
        return metrics

    def _profile_brief_compacted_until(self, profile_brief: object) -> dict[str, Any]:
        if not isinstance(profile_brief, dict):
            return {"doc_id": None, "outline_segment_id": ""}
        compacted_until = profile_brief.get("compacted_until")
        compacted = dict(compacted_until) if isinstance(compacted_until, dict) else {}
        return {
            "doc_id": self._safe_int(compacted.get("doc_id")),
            "outline_segment_id": str(compacted.get("outline_segment_id") or "").strip(),
        }

    def _local_compacted_until_for_pending_group(self, group: dict[str, Any]) -> dict[str, Any]:
        best_doc = 0
        best_segment_id = ""
        evidence_items = [item for item in group.get("evidence_items", []) if isinstance(item, dict)]
        for item in evidence_items:
            source_doc_ids = self._safe_int_list(item.get("source_doc_ids"))
            if not source_doc_ids:
                source_doc_ids = self._safe_int_list(group.get("source_doc_ids"))
            latest_doc = max(source_doc_ids) if source_doc_ids else 0
            segment_id = str(item.get("outline_segment_id") or "").strip()
            if segment_id and (latest_doc > best_doc or (latest_doc == best_doc and segment_id > best_segment_id)):
                best_doc = latest_doc
                best_segment_id = segment_id
        if not best_doc:
            source_doc_ids = self._safe_int_list(group.get("source_doc_ids"))
            best_doc = max(source_doc_ids) if source_doc_ids else 0
        if not best_segment_id:
            segment_ids = [str(item).strip() for item in group.get("outline_segment_ids", []) if str(item).strip()]
            if segment_ids:
                best_segment_id = max(segment_ids, key=self._outline_segment_sort_key)
        return {"doc_id": best_doc or None, "outline_segment_id": best_segment_id}

    def _prepare_character_reduce_updates_for_merge(
        self,
        updates: list[dict[str, Any]],
        *,
        group: dict[str, Any],
        existing_profile_brief: dict[str, Any],
    ) -> list[dict[str, Any]]:
        compacted_until = self._local_compacted_until_for_pending_group(group)
        fallback_source_refs = self._source_refs_for_pending_group(group)
        prepared: list[dict[str, Any]] = []
        for update in updates:
            normalized = dict(update)
            normalized.pop("consumed_pending_experience_ids", None)
            recent_experiences = self._dict_list(normalized.get("recent_key_experiences"))
            if recent_experiences:
                key_experiences = self._dict_list(normalized.get("key_experiences"))
                normalized["key_experiences"] = self._dedupe_experience_items([*key_experiences, *recent_experiences])
                normalized["recent_key_experiences"] = []
                normalized["consumed_pending_experience_ids"] = self._experience_ids_from_items(recent_experiences)
            profile_brief = normalized.get("profile_brief")
            if isinstance(profile_brief, dict) and profile_brief:
                brief = dict(profile_brief)
                brief.pop("source_refs", None)
                source_ref_delta = self._dict_list(normalized.get("source_ref_delta"))
                if not source_ref_delta:
                    source_ref_delta = self._dict_list(brief.pop("source_ref_delta", []))
                brief["source_refs"] = self._merge_source_refs(
                    existing_profile_brief.get("source_refs"),
                    source_ref_delta,
                    fallback_source_refs,
                )
                brief["compacted_until"] = compacted_until
                normalized["profile_brief"] = brief
            prepared.append(normalized)
        return prepared

    def _source_refs_for_pending_group(self, group: dict[str, Any]) -> list[dict[str, Any]]:
        refs_by_key: dict[str, dict[str, Any]] = {}
        for item in group.get("evidence_items", []):
            if not isinstance(item, dict):
                continue
            evidence_id = str(item.get("evidence_id") or "").strip()
            segment_id = str(item.get("outline_segment_id") or "").strip()
            source_doc_ids = self._safe_int_list(item.get("source_doc_ids"))
            if not source_doc_ids:
                source_doc_ids = self._safe_int_list(group.get("source_doc_ids"))
            key = segment_id or evidence_id
            if not key:
                continue
            ref = refs_by_key.setdefault(
                key,
                {
                    "outline_segment_id": segment_id,
                    "source_doc_ids": [],
                    "source_doc_range": str(item.get("source_doc_range") or "").strip(),
                    "evidence_ids": [],
                },
            )
            ref["source_doc_ids"] = sorted({*self._safe_int_list(ref.get("source_doc_ids")), *source_doc_ids})
            if evidence_id and evidence_id not in ref["evidence_ids"]:
                ref["evidence_ids"].append(evidence_id)
            if not ref.get("source_doc_range"):
                ref["source_doc_range"] = self._doc_range_text(ref["source_doc_ids"])
        return [ref for ref in refs_by_key.values() if ref.get("outline_segment_id") or ref.get("evidence_ids")]

    def _merge_source_refs(self, *ref_groups: object) -> list[dict[str, Any]]:
        merged: list[dict[str, Any]] = []
        seen: set[str] = set()
        for group in ref_groups:
            for ref in self._dict_list(group):
                key = self._stable_json_key(ref)
                if key in seen:
                    continue
                seen.add(key)
                merged.append(ref)
        return merged

    def _dict_list(self, value: object) -> list[dict[str, Any]]:
        if not isinstance(value, list):
            return []
        return [dict(item) for item in value if isinstance(item, dict)]

    def _dedupe_experience_items(self, items: list[dict[str, Any]]) -> list[dict[str, Any]]:
        result: list[dict[str, Any]] = []
        seen: set[str] = set()
        for item in items:
            key = str(item.get("experience_id") or item.get("event_id") or item.get("id") or "").strip()
            if not key:
                key = self._stable_json_key(item)
            if key in seen:
                continue
            seen.add(key)
            result.append(item)
        return result

    def _experience_ids_from_items(self, items: list[dict[str, Any]]) -> list[str]:
        ids: list[str] = []
        seen: set[str] = set()
        for item in items:
            value = str(item.get("experience_id") or item.get("event_id") or item.get("id") or "").strip()
            if not value or value in seen:
                continue
            seen.add(value)
            ids.append(value)
        return ids

    def _outline_segment_sort_key(self, value: str) -> tuple[int, int, str]:
        numbers = [int(item) for item in re.findall(r"\d+", value)]
        latest = max(numbers) if numbers else 0
        first = numbers[0] if numbers else 0
        return latest, first, value

    def _stable_json_key(self, value: object) -> str:
        try:
            return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        except (TypeError, ValueError):
            return str(value)

    def _append_character_evidence_log(
        self,
        conn,
        *,
        evidence_payload: dict[str, Any],
        outline_update: dict[str, Any],
    ) -> int:
        grouped = self.memory_candidate_service._group_character_evidence(evidence_payload)  # noqa: SLF001
        evidence_items = [item for items in grouped.values() for item in items]
        if not evidence_items:
            return 0
        return self.character_evidence_log_repo.append_many(
            conn,
            book_id=self.config.book_id,
            evidence_items=evidence_items,
            outline_segment=outline_update,
            updated_at=_utc_now(),
        )

    def _apply_pending_character_reduces(
        self,
        *,
        conn,
        model_client: JsonModelClient,
        batch: ChapterBatch,
        profile_service: CharacterProfileService,
        evidence_payload: dict[str, Any],
        summary_payload: dict[str, Any],
        current_outline_segment: dict[str, Any],
    ) -> None:
        current_gates = self._profile_update_gates_for_evidence(
            evidence_payload=evidence_payload,
            current_total_chars=batch.total_chars,
        )
        pending_groups = self.character_evidence_log_repo.pending_groups(conn, book_id=self.config.book_id)
        for group in pending_groups:
            if not self._should_reduce_pending_character_group(group=group, current_gates=current_gates):
                continue
            row = self._profile_row_for_pending_group(
                conn,
                profile_service=profile_service,
                group=group,
            )
            if row is None:
                continue
            row = self._ensure_profile_brief_for_reduce(
                conn=conn,
                model_client=model_client,
                profile_service=profile_service,
                row=row,
            )
            profile_context = self._profile_context_from_row(row)
            profile_context["character_update_gate"] = self._pending_reduce_gate(group=group, current_gates=current_gates)
            reduce_payload = self._run_character_reduce_agents(
                model_client=model_client,
                batch=batch,
                prompt_input={
                    "book_id": self.config.book_id,
                    "character_profiles": [profile_context],
                },
                summary_payload=summary_payload,
                evidence_payload=self._pending_group_evidence_payload(group),
                current_outline_segment=self._outline_segment_for_pending_group(
                    group=group,
                    current_outline_segment=current_outline_segment,
                ),
            )
            updates = [
                item
                for item in reduce_payload.get("character_updates", [])
                if isinstance(item, dict) and isinstance(item.get("profile_brief"), dict) and item.get("profile_brief")
            ]
            if not updates:
                continue
            updates = self._prepare_character_reduce_updates_for_merge(
                updates,
                group=group,
                existing_profile_brief=profile_context.get("profile_brief", {})
                if isinstance(profile_context.get("profile_brief"), dict)
                else {},
            )
            profile_service.merge_updates(
                conn,
                book_id=self.config.book_id,
                chapter_index=batch.document_title_index,
                doc_ids=group.get("source_doc_ids") or [doc.doc_id for doc in batch.documents],
                updates=updates,
                mentioned_doc_ids_by_name={str(row["canonical_name"] or ""): group.get("source_doc_ids", [])},
                speaking_doc_ids_by_name={},
                story_events_by_name={},
            )
            self.character_evidence_log_repo.mark_compacted(
                conn,
                evidence_ids=group.get("evidence_ids", []),
                updated_at=_utc_now(),
            )

    def _should_reduce_pending_character_group(
        self,
        *,
        group: dict[str, Any],
        current_gates: dict[str, dict[str, Any]],
    ) -> bool:
        gate = self._pending_reduce_gate(group=group, current_gates=current_gates)
        if str(gate.get("update_policy") or "").strip() == "reduce_now":
            return True
        if bool(group.get("has_major_change")):
            return True
        evidence_count = len(group.get("evidence_items", []))
        evidence_chars = int(group.get("evidence_chars") or 0)
        if evidence_count >= int(self.config.runtime.character_reduce_pending_min_evidence_count):
            return True
        return evidence_chars >= int(self.config.runtime.character_reduce_pending_min_evidence_chars)

    def _pending_reduce_gate(
        self,
        *,
        group: dict[str, Any],
        current_gates: dict[str, dict[str, Any]],
    ) -> dict[str, Any]:
        keys = [
            f"id:{str(group.get('character_id') or '').strip()}",
            f"name:{str(group.get('canonical_name') or '').strip()}",
        ]
        for key in keys:
            gate = current_gates.get(key)
            if isinstance(gate, dict) and str(gate.get("detail_level") or "").strip() == "detailed":
                merged = dict(gate)
                merged["update_policy"] = "reduce_now"
                return merged
        return {
            "detail_level": "compact",
            "update_policy": "append_pending",
            "reason": "pending_evidence_threshold_or_major_change",
            "pending_evidence_count": len(group.get("evidence_items", [])),
            "pending_evidence_chars": int(group.get("evidence_chars") or 0),
            "pending_outline_segment_ids": group.get("outline_segment_ids", []),
        }

    def _profile_row_for_pending_group(
        self,
        conn,
        *,
        profile_service: CharacterProfileService,
        group: dict[str, Any],
    ):
        repo = profile_service.profiles_repo
        character_id = self._safe_int(group.get("character_id"))
        if character_id is not None and character_id > 0:
            row = repo.get_by_id(conn, book_id=self.config.book_id, character_id=character_id)
            if row is not None:
                return row
        canonical_name = str(group.get("canonical_name") or "").strip()
        if not canonical_name:
            return None
        row = repo.get(conn, book_id=self.config.book_id, canonical_name=canonical_name)
        if row is not None:
            return row
        for candidate in repo.list_by_book(conn, book_id=self.config.book_id):
            aliases = self._load_json_list(candidate["aliases_json"])
            if canonical_name in aliases:
                return candidate
        return None

    def _ensure_profile_brief_for_reduce(
        self,
        *,
        conn,
        model_client: JsonModelClient,
        profile_service: CharacterProfileService,
        row,
    ):
        current_brief = self._load_json_dict(row["profile_brief_json"]) if self._row_has_column(row, "profile_brief_json") else {}
        if current_brief:
            return row
        self._emit_progress(
            {
                "stage": DEFAULT_CLOSE_READING_STAGE,
                "agent": "profile_brief_bootstrap",
                "event": "prompt_start",
                "character_id": str(row["character_id"]),
                "canonical_name": str(row["canonical_name"] or ""),
                "reason": "missing_profile_brief_before_character_reduce",
            }
        )
        started_at = time.perf_counter()
        brief_payload = self.profile_brief_service.bootstrap_from_row(model_client=model_client, row=row)
        compacted_until = self._profile_brief_compacted_until(brief_payload.get("profile_brief"))
        profile_service.profiles_repo.update_profile_brief(
            conn,
            book_id=self.config.book_id,
            character_id=int(row["character_id"]),
            profile_brief=brief_payload["profile_brief"],
            profile_brief_status=brief_payload["profile_brief_status"],
            compacted_until_doc_id=compacted_until["doc_id"],
            compacted_until_segment_id=compacted_until["outline_segment_id"],
            updated_at=_utc_now(),
        )
        self._emit_progress(
            {
                "stage": DEFAULT_CLOSE_READING_STAGE,
                "agent": "profile_brief_bootstrap",
                "event": "prompt_end",
                "character_id": str(row["character_id"]),
                "canonical_name": str(row["canonical_name"] or ""),
                "duration_seconds": round(time.perf_counter() - started_at, 3),
                "profile_brief_status": brief_payload["profile_brief_status"],
            }
        )
        return profile_service.profiles_repo.get_by_id(
            conn,
            book_id=self.config.book_id,
            character_id=int(row["character_id"]),
        ) or row

    def _pending_group_evidence_payload(self, group: dict[str, Any]) -> dict[str, Any]:
        return {
            "character_evidence_batches": [
                {
                    "doc_ids": group.get("source_doc_ids", []),
                    "document_title_indexes": group.get("source_title_indexes", []),
                    "characters": [item for item in group.get("evidence_items", []) if isinstance(item, dict)],
                }
            ]
        }

    def _outline_segment_for_pending_group(
        self,
        *,
        group: dict[str, Any],
        current_outline_segment: dict[str, Any],
    ) -> dict[str, Any]:
        current_id = str(current_outline_segment.get("outline_segment_id") or "").strip()
        pending_ids = [str(item).strip() for item in group.get("outline_segment_ids", []) if str(item).strip()]
        if current_id and (not pending_ids or pending_ids == [current_id]):
            return current_outline_segment
        if len(pending_ids) == 1:
            return {
                "outline_segment_id": pending_ids[0],
                "source_doc_ids": group.get("source_doc_ids", []),
                "source_title_indexes": group.get("source_title_indexes", []),
                "source_doc_range": self._doc_range_text(group.get("source_doc_ids", [])),
                "status": "pending_evidence",
            }
        return {
            "outline_segment_id": ",".join(pending_ids),
            "source_doc_ids": group.get("source_doc_ids", []),
            "source_title_indexes": group.get("source_title_indexes", []),
            "source_doc_range": self._doc_range_text(group.get("source_doc_ids", [])),
            "status": "pending_evidence",
        }

    def _generate_character_evidence_payload(
        self,
        *,
        model_client: JsonModelClient,
        batch: ChapterBatch,
        prompt_input: dict[str, Any],
    ) -> dict[str, Any]:
        fast_input = dict(prompt_input)
        fast_input["existing_character_roster"] = [
            item for item in prompt_input.get("existing_character_roster", []) if isinstance(item, dict)
        ]
        fast_input["character_roster_scope"] = "recent_32"
        fast_input["can_request_full_roster"] = True
        payload = self._generate_agent_payload(
            model_client=model_client,
            batch=batch,
            prompt_input=self._build_character_evidence_input(
                batch=batch,
                prompt_input=fast_input,
            ),
            agent_name="character_evidence",
            prompt_builder=build_character_evidence_prompt,
            fallback_factory=lambda batch=batch: self._fallback_character_evidence_output(batch),
        )
        if not bool(payload.get("request_full_roster")):
            return payload
        full_roster = [
            item for item in prompt_input.get("full_existing_character_roster", []) if isinstance(item, dict)
        ]
        if len(full_roster) <= len(fast_input["existing_character_roster"]):
            return payload
        full_input = dict(prompt_input)
        full_input["existing_character_roster"] = full_roster
        full_input["character_roster_scope"] = "full"
        full_input["can_request_full_roster"] = False
        return self._generate_agent_payload(
            model_client=model_client,
            batch=batch,
            prompt_input=self._build_character_evidence_input(
                batch=batch,
                prompt_input=full_input,
            ),
            agent_name="character_evidence_full_roster",
            prompt_builder=build_character_evidence_prompt,
            fallback_factory=lambda batch=batch: self._fallback_character_evidence_output(batch),
        )

    def _augment_character_evidence_with_coverage(
        self,
        *,
        model_client: JsonModelClient,
        batch: ChapterBatch,
        prompt_input: dict[str, Any],
        summary_payload: dict[str, Any],
        evidence_payload: dict[str, Any],
    ) -> dict[str, Any]:
        if not bool(getattr(self.config.runtime, "character_evidence_coverage_audit", True)):
            return evidence_payload
        if not str(summary_payload.get("chapter_summary_md") or summary_payload.get("chapter_summary_short") or "").strip():
            return evidence_payload
        coverage_payload = self._generate_agent_payload(
            model_client=model_client,
            batch=batch,
            prompt_input=self._build_character_evidence_coverage_input(
                batch=batch,
                prompt_input=prompt_input,
                summary_payload=summary_payload,
                evidence_payload=evidence_payload,
            ),
            agent_name="character_evidence_coverage",
            prompt_builder=build_character_evidence_coverage_prompt,
            fallback_factory=lambda: {"coverage_gap_found": False, "coverage_notes": "", "characters": []},
        )
        return self._merge_character_evidence_coverage(
            evidence_payload=evidence_payload,
            coverage_payload=coverage_payload,
        )

    def _build_character_evidence_coverage_input(
        self,
        *,
        batch: ChapterBatch,
        prompt_input: dict[str, Any],
        summary_payload: dict[str, Any],
        evidence_payload: dict[str, Any],
    ) -> dict[str, Any]:
        context_parts = [
            str(prompt_input.get("world_summary_md", "")).strip(),
            str(prompt_input.get("story_outline_md", "")).strip(),
        ]
        roster = [
            item for item in prompt_input.get("full_existing_character_roster", []) if isinstance(item, dict)
        ] or [
            item for item in prompt_input.get("existing_character_roster", []) if isinstance(item, dict)
        ]
        evidence_batch = CharacterEvidenceBatchAssemblerService(
            document_chars_budget=self.config.runtime.document_chars_budget,
        ).build_batch(
            book_id=self.config.book_id,
            documents=batch.documents,
            existing_context_summary="\n\n".join(part for part in context_parts if part),
            existing_character_roster=roster,
            character_roster_scope="full" if roster else "none",
            can_request_full_roster=False,
        )
        return {
            "book_id": self.config.book_id,
            "chapter_summary": {
                "chapter_summary_md": summary_payload.get("chapter_summary_md", ""),
                "chapter_summary_short": summary_payload.get("chapter_summary_short", ""),
                "chapter_summaries": summary_payload.get("chapter_summaries", []),
            },
            "character_evidence_batch": evidence_batch.to_dict(),
            "existing_character_evidence": self._compact_character_evidence_payload(evidence_payload),
            "existing_character_roster": roster,
        }

    def _compact_character_evidence_payload(self, evidence_payload: dict[str, Any]) -> dict[str, Any]:
        return {
            "doc_ids": self._safe_int_list(evidence_payload.get("doc_ids")),
            "document_title_indexes": self._safe_int_list(evidence_payload.get("document_title_indexes")),
            "characters": [
                {
                    "character_id": str(item.get("character_id") or ""),
                    "canonical_name": item.get("canonical_name", ""),
                    "aliases": item.get("aliases", []),
                    "source_doc_ids": self._safe_int_list(item.get("source_doc_ids")),
                    "source_title_indexes": self._safe_int_list(item.get("source_title_indexes")),
                    "candidate_type": item.get("candidate_type", ""),
                    "confidence": item.get("confidence", 0),
                }
                for item in self._flatten_character_evidence_items(evidence_payload)
                if isinstance(item, dict)
            ],
        }

    def _merge_character_evidence_coverage(
        self,
        *,
        evidence_payload: dict[str, Any],
        coverage_payload: dict[str, Any],
    ) -> dict[str, Any]:
        raw_characters = coverage_payload.get("characters", [])
        if not isinstance(raw_characters, list) or not raw_characters:
            return evidence_payload
        merged = dict(evidence_payload)
        existing_keys = {
            self._character_evidence_identity_key(item)
            for item in self._flatten_character_evidence_items(merged)
            if isinstance(item, dict)
        }
        existing_keys.discard("")
        additions: list[dict[str, Any]] = []
        for raw_character in raw_characters:
            if not isinstance(raw_character, dict):
                continue
            character = dict(raw_character)
            name = self.memory_candidate_service.clean_evidence_name(character.get("canonical_name"), character=character)
            if not name:
                continue
            character["canonical_name"] = name
            identity_key = self._character_evidence_identity_key(character)
            if identity_key in existing_keys:
                continue
            character.setdefault("candidate_type", "character")
            character.setdefault("confidence", 0.75)
            character.setdefault("source_doc_ids", self._safe_int_list(merged.get("doc_ids")))
            character.setdefault("source_title_indexes", self._safe_int_list(merged.get("document_title_indexes")))
            additions.append(character)
            existing_keys.add(identity_key)
        if not additions:
            return evidence_payload

        batches = merged.get("character_evidence_batches")
        if isinstance(batches, list):
            normalized_batches = [dict(item) for item in batches if isinstance(item, dict)]
            if not normalized_batches:
                normalized_batches.append(
                    {
                        "doc_ids": self._safe_int_list(merged.get("doc_ids")),
                        "document_title_indexes": self._safe_int_list(merged.get("document_title_indexes")),
                        "characters": [],
                    }
                )
            for character in additions:
                target = self._find_evidence_batch_for_character(
                    evidence_batches=normalized_batches,
                    character=character,
                )
                target.setdefault("characters", [])
                if isinstance(target["characters"], list):
                    target["characters"].append(character)
            merged["character_evidence_batches"] = normalized_batches
            return merged

        characters = merged.get("characters")
        merged["characters"] = [*(characters if isinstance(characters, list) else []), *additions]
        return merged

    def _find_evidence_batch_for_character(
        self,
        *,
        evidence_batches: list[dict[str, Any]],
        character: dict[str, Any],
    ) -> dict[str, Any]:
        source_doc_ids = set(self._safe_int_list(character.get("source_doc_ids")))
        for evidence_batch in evidence_batches:
            batch_doc_ids = set(self._safe_int_list(evidence_batch.get("doc_ids")))
            if source_doc_ids and batch_doc_ids and source_doc_ids.intersection(batch_doc_ids):
                return evidence_batch
        return evidence_batches[0]

    def _build_character_evidence_input(
        self,
        *,
        batch: ChapterBatch,
        prompt_input: dict[str, Any],
    ) -> dict[str, Any]:
        context_parts = [
            str(prompt_input.get("world_summary_md", "")).strip(),
            str(prompt_input.get("story_outline_md", "")).strip(),
        ]
        evidence_batch = CharacterEvidenceBatchAssemblerService(
            document_chars_budget=self.config.runtime.document_chars_budget,
        ).build_batch(
            book_id=self.config.book_id,
            documents=batch.documents,
            existing_context_summary="\n\n".join(part for part in context_parts if part),
            existing_character_roster=[
                item for item in prompt_input.get("existing_character_roster", []) if isinstance(item, dict)
            ],
            character_roster_scope=str(prompt_input.get("character_roster_scope") or "recent_32"),
            can_request_full_roster=bool(prompt_input.get("can_request_full_roster")),
        )
        return {"character_evidence_batch": evidence_batch.to_dict()}

    def _build_world_evidence_input(
        self,
        *,
        batch: ChapterBatch,
        prompt_input: dict[str, Any],
    ) -> dict[str, Any]:
        return {
            "book_id": prompt_input.get("book_id"),
            "current_title_index": prompt_input.get("current_title_index"),
            "chapter_title": prompt_input.get("chapter_title"),
            "documents": [
                {
                    "doc_id": doc.doc_id,
                    "document_title_index": doc.document_title_index,
                    "document_title": doc.document_title,
                    "content": doc.content,
                }
                for doc in batch.documents
            ],
            "world_summary_md": prompt_input.get("world_summary_md", ""),
            "story_outline_md": prompt_input.get("story_outline_md", ""),
        }

    def _generate_agent_payload(
        self,
        *,
        model_client: JsonModelClient,
        batch: ChapterBatch,
        prompt_input: dict[str, Any],
        agent_name: str,
        prompt_builder,
        fallback_factory,
    ) -> dict[str, Any]:
        system_prompt, user_prompt = prompt_builder(prompt_input)
        prompt_metrics = self._prompt_input_metrics(prompt_input)
        started_at = time.perf_counter()
        self._emit_progress(
            {
                "stage": "close_reading",
                "agent": agent_name,
                "event": "prompt_start",
                "document_title_indexes": batch.title_indexes,
                "doc_count": len(batch.documents),
                "total_chars": batch.total_chars,
                "prompt_chars": len(system_prompt) + len(user_prompt),
                "system_prompt_chars": len(system_prompt),
                "user_prompt_chars": len(user_prompt),
                **prompt_metrics,
            }
        )
        payload, _ = model_client.generate_json(
            system_prompt=system_prompt,
            user_prompt=user_prompt,
            fallback_factory=fallback_factory,
            use_fallback_on_error=self.config.runtime.dry_run,
        )
        self._emit_progress(
            {
                "stage": "close_reading",
                "agent": agent_name,
                "event": "prompt_end",
                "document_title_indexes": batch.title_indexes,
                "doc_count": len(batch.documents),
                "total_chars": batch.total_chars,
                "prompt_chars": len(system_prompt) + len(user_prompt),
                "system_prompt_chars": len(system_prompt),
                "user_prompt_chars": len(user_prompt),
                **prompt_metrics,
                "duration_seconds": round(time.perf_counter() - started_at, 3),
            }
        )
        if not isinstance(payload, dict):
            if self.config.runtime.dry_run:
                fallback = fallback_factory()
                return fallback if isinstance(fallback, dict) else {}
            raise RuntimeError(f"{agent_name} returned a non-dict JSON payload")
        return payload

    def _generate_chapter_outline_segment(
        self,
        *,
        model_client: JsonModelClient,
        batch: ChapterBatch,
        summary_md: str,
        summary_short: str,
        outline_update: object,
    ) -> dict[str, Any]:
        existing_outline_update = outline_update if isinstance(outline_update, dict) else {}
        started_at = time.perf_counter()
        self._emit_progress(
            {
                "stage": DEFAULT_CLOSE_READING_STAGE,
                "agent": "chapter_outline_segment",
                "event": "prompt_start",
                "document_title_indexes": batch.title_indexes,
                "doc_count": len(batch.documents),
                "total_chars": batch.total_chars,
            }
        )
        generated = ChapterOutlineSegmentService(model_client=model_client).build_outline_update(
            book_id=self.config.book_id,
            document_title_index=batch.document_title_index,
            chapter_title=batch.chapter_title,
            summary_md=summary_md,
            chapter_summary_short=summary_short,
            source_doc_range=self._doc_range_text([doc.doc_id for doc in batch.documents]),
            existing_outline_update=existing_outline_update,
        )
        self._emit_progress(
            {
                "stage": DEFAULT_CLOSE_READING_STAGE,
                "agent": "chapter_outline_segment",
                "event": "prompt_end",
                "document_title_indexes": batch.title_indexes,
                "doc_count": len(batch.documents),
                "total_chars": batch.total_chars,
                "duration_seconds": round(time.perf_counter() - started_at, 3),
            }
        )
        merged = dict(existing_outline_update)
        merged.update({key: value for key, value in generated.items() if value not in (None, "", [], {})})
        return merged

    def _generate_chapter_summary_payload(
        self,
        *,
        model_client: JsonModelClient,
        batch: ChapterBatch,
        prompt_input: dict[str, Any],
    ) -> dict[str, Any]:
        system_prompt, user_prompt = build_chapter_summary_prompt(prompt_input)
        started_at = time.perf_counter()
        self._emit_progress(
            {
                "stage": "close_reading",
                "agent": "chapter_summary",
                "event": "prompt_start",
                "document_title_indexes": batch.title_indexes,
                "doc_count": len(batch.documents),
                "total_chars": batch.total_chars,
                "prompt_chars": len(system_prompt) + len(user_prompt),
                "system_prompt_chars": len(system_prompt),
                "user_prompt_chars": len(user_prompt),
            }
        )
        payload, _ = model_client.generate_json(
            system_prompt=system_prompt,
            user_prompt=user_prompt,
            fallback_factory=lambda: self._disallowed_summary_fallback(batch),
            use_fallback_on_error=False,
        )
        self._emit_progress(
            {
                "stage": "close_reading",
                "agent": "chapter_summary",
                "event": "prompt_end",
                "document_title_indexes": batch.title_indexes,
                "doc_count": len(batch.documents),
                "total_chars": batch.total_chars,
                "prompt_chars": len(system_prompt) + len(user_prompt),
                "system_prompt_chars": len(system_prompt),
                "user_prompt_chars": len(user_prompt),
                "duration_seconds": round(time.perf_counter() - started_at, 3),
            }
        )
        if not isinstance(payload, dict):
            review_path = self._write_summary_review_markdown(
                batch=batch,
                reason="chapter_summary returned a non-dict JSON payload",
                payload={"raw_payload_type": type(payload).__name__},
            )
            raise InvalidChapterSynopsisError("chapter_summary returned non-dict JSON", review_path=review_path)
        payload = self._normalize_chapter_summary_schema_aliases(payload)
        self._validate_summary_payload(batch=batch, payload=payload)
        return payload

    def _compose_close_read_payload(
        self,
        *,
        batch: ChapterBatch,
        summary_payload: dict[str, Any],
        evidence_payload: dict[str, Any],
        character_reduce_payload: dict[str, Any],
        global_memory_payload: dict[str, Any],
        current_outline_segment: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "chapter_summary_md": "",
            "chapter_summary_short": "",
            "importance_score": 0,
            "importance_reason": "",
            "related_chapters": [],
            "document_character_mentions": [],
            "character_updates": [],
            "world_update": {"should_update": False, "changes": []},
            "outline_update": {"chapter_line": ""},
        }
        for key in ("chapter_summary_md", "chapter_summary_short"):
            value = summary_payload.get(key)
            if value is not None and str(value).strip():
                payload[key] = str(value).strip()
        for key in ("importance_score",):
            value = summary_payload.get(key)
            if isinstance(value, int):
                payload[key] = value
        for key in ("importance_reason",):
            value = summary_payload.get(key)
            if value is not None and str(value).strip():
                payload[key] = str(value).strip()
        for key in ("related_chapters",):
            value = summary_payload.get(key)
            if isinstance(value, list):
                payload[key] = value
        if batch.is_multi_chapter and "chapter_summaries" in summary_payload:
            payload["chapter_summaries"] = self._normalize_model_chapter_summaries(
                batch=batch,
                raw_summaries=summary_payload.get("chapter_summaries"),
            )
        payload["document_character_mentions"] = self._document_mentions_from_character_evidence(
            batch=batch,
            evidence_payload=evidence_payload,
        )
        payload["character_evidence_payload"] = evidence_payload
        payload["identity_revelations"] = self._flatten_identity_revelations(evidence_payload)
        fallback_memory = self._fallback_memory_candidate_output(batch, summary_payload, evidence_payload)
        payload["character_updates"] = character_reduce_payload.get("character_updates", fallback_memory["character_updates"])
        payload["world_update"] = global_memory_payload.get("world_update", fallback_memory["world_update"])
        payload["outline_update"] = current_outline_segment or global_memory_payload.get("outline_update", fallback_memory["outline_update"])
        return payload

    def _normalize_model_chapter_summaries(
        self,
        *,
        batch: ChapterBatch,
        raw_summaries: object,
    ) -> list[dict[str, Any]]:
        summary_keys = {
            "document_title_index",
            "chapter_title",
            "summary_quality",
            "chapter_summary_md",
            "chapter_summary_short",
            "importance_score",
            "importance_reason",
            "related_chapters",
            "noise_documents",
        }
        model_by_index: dict[int, dict[str, Any]] = {}
        if isinstance(raw_summaries, list):
            for item in raw_summaries:
                if not isinstance(item, dict):
                    continue
                item = self._normalize_chapter_summary_schema_aliases(item)
                title_index = self._safe_int(item.get("document_title_index"))
                if title_index is None:
                    continue
                model_by_index[title_index] = {key: value for key, value in item.items() if key in summary_keys}

        merged: list[dict[str, Any]] = []
        for title_index in batch.title_indexes:
            if title_index not in model_by_index:
                sub_batch = batch.as_single_title_batch(title_index)
                review_path = self._write_summary_review_markdown(
                    batch=sub_batch,
                    reason=f"chapter_summaries missing document_title_index={title_index}",
                    payload={"chapter_summaries": raw_summaries},
                )
                raise InvalidChapterSynopsisError(
                    f"chapter_summary missing chapter_summaries item for title_index={title_index}",
                    review_path=review_path,
                )
            item = dict(model_by_index[title_index])
            item["document_title_index"] = title_index
            if not item.get("chapter_title"):
                item["chapter_title"] = batch.as_single_title_batch(title_index).chapter_title
            merged.append(item)
        return merged

    @staticmethod
    def _normalize_chapter_summary_schema_aliases(payload: dict[str, Any]) -> dict[str, Any]:
        normalized = dict(payload)
        if not str(normalized.get("chapter_summary_md") or "").strip():
            chapter_summary_alias = normalized.get("chapter_summary")
            if isinstance(chapter_summary_alias, str) and chapter_summary_alias.strip():
                normalized["chapter_summary_md"] = chapter_summary_alias.strip()
        raw_summaries = normalized.get("chapter_summaries")
        if isinstance(raw_summaries, list):
            normalized["chapter_summaries"] = [
                CloseReadRunner._normalize_chapter_summary_schema_aliases(item)
                if isinstance(item, dict)
                else item
                for item in raw_summaries
            ]
        return normalized

    def _build_global_memory_input(
        self,
        *,
        prompt_input: dict[str, Any],
        summary_payload: dict[str, Any],
        world_evidence_payload: dict[str, Any],
    ) -> dict[str, Any]:
        return self.memory_candidate_service.build_global_memory_input(
            prompt_input=prompt_input,
            summary_payload=summary_payload,
            world_evidence_payload=world_evidence_payload,
        )

    def _names_from_document_mentions(self, mention_items: object, *, field: str) -> list[str]:
        if not isinstance(mention_items, list):
            return []
        names: list[str] = []
        for item in mention_items:
            if not isinstance(item, dict):
                continue
            raw_names = item.get(field)
            if not isinstance(raw_names, list):
                continue
            names.extend(str(name).strip() for name in raw_names if str(name).strip())
        return sorted(set(self.character_mention_service.clean_names(names)))

    def _fallback_close_read_output(self, batch: ChapterBatch) -> dict[str, Any]:
        full_text = "\n".join(doc.content for doc in batch.documents)
        document_character_mentions = [
            {
                "doc_id": doc.doc_id,
                "character_keywords": [],
                "speaking_character_keywords": [],
                "character_evidence": {},
                "speaking_evidence": {},
            }
            for doc in batch.documents
        ]
        chapter_summary = ""
        short_summary = ""
        importance = min(100, max(20, 30 + len(batch.documents) * 8 + min(40, batch.total_chars // 1500)))
        mentioned_characters = sorted(
            {
                name
                for item in document_character_mentions
                for name in item["character_keywords"]
                if isinstance(name, str) and name.strip()
            }
        )
        world_changes = []
        for keyword in ("学院",):
            if keyword in full_text:
                world_changes.append({"section": "世界设定", "summary": f"本章涉及 {keyword} 相关设定", "evidence": keyword})
        character_updates = []
        for name in mentioned_characters[:8]:
            character_updates.append(
                {
                    "canonical_name": name,
                    "aliases": [],
                    "personality": [],
                    "occupations": [],
                    "recent_activity": short_summary,
                    "relationships": [],
                }
            )
        result = {
            "summary_quality": "fallback_excerpt_disallowed",
            "chapter_summary_md": chapter_summary,
            "chapter_summary_short": short_summary,
            "importance_score": importance,
            "importance_reason": "基于章节长度、人物密度和事件推进的启发式估计",
            "related_chapters": [],
            "world_signal_score": self._fallback_world_signal_score(full_text),
            "world_evidence_candidates": self._fallback_world_candidates(batch),
            "document_character_mentions": document_character_mentions,
            "world_update": {"should_update": bool(world_changes), "changes": world_changes},
            "character_updates": character_updates,
            "outline_update": {
                "chapter_line": f"[{batch.document_title_index}] {batch.chapter_title}: {short_summary}",
            },
        }
        if batch.is_multi_chapter:
            chapter_summaries = []
            for title_index in batch.title_indexes:
                sub_batch = batch.as_single_title_batch(title_index)
                chapter_summary = {
                    key: value
                    for key, value in self._fallback_close_read_output(sub_batch).items()
                    if key != "chapter_summaries"
                }
                chapter_summary["document_title_index"] = title_index
                chapter_summary["chapter_title"] = sub_batch.chapter_title
                chapter_summaries.append(chapter_summary)
            result["chapter_summaries"] = chapter_summaries
        return result

    def _fallback_summary_output(self, batch: ChapterBatch) -> dict[str, Any]:
        return self._disallowed_summary_fallback(batch)

    def _fallback_character_evidence_output(self, batch: ChapterBatch) -> dict[str, Any]:
        doc_ids = [doc.doc_id for doc in batch.documents]
        payload = {
            "doc_ids": doc_ids,
            "document_title_indexes": batch.title_indexes,
            "characters": [],
        }
        if len(doc_ids) == 1:
            payload["doc_id"] = doc_ids[0]
            payload["document_title_index"] = batch.title_indexes[0] if batch.title_indexes else 0
        return payload

    def _fallback_world_evidence_output(self, batch: ChapterBatch) -> dict[str, Any]:
        return {
            "world_signal_score": self._fallback_world_signal_score("\n".join(doc.content for doc in batch.documents)),
            "world_evidence_candidates": self._fallback_world_candidates(batch),
        }

    def _fallback_global_memory_output(
        self,
        summary_payload: dict[str, Any],
        world_evidence_payload: dict[str, Any],
    ) -> dict[str, Any]:
        return self.memory_candidate_service.build_global_memory_fallback_output(
            summary_payload=summary_payload,
            world_evidence_payload=world_evidence_payload,
        )

    def _should_run_world_evidence(self, *, batch: ChapterBatch, summary_payload: dict[str, Any]) -> bool:
        threshold = int(self.config.runtime.world_evidence_signal_threshold)
        if self._safe_int(summary_payload.get("world_signal_score")) is not None:
            if int(summary_payload.get("world_signal_score") or 0) >= threshold:
                return True
        candidates = summary_payload.get("world_evidence_candidates")
        if isinstance(candidates, list):
            for candidate in candidates:
                if not isinstance(candidate, dict):
                    continue
                confidence = self.memory_candidate_service._safe_float(candidate.get("confidence"), default=0.0)
                if 0 < confidence < 0.55:
                    return True
        return self._fallback_world_signal_score("\n".join(doc.content for doc in batch.documents)) >= threshold

    def _should_prefetch_world_evidence(self, *, batch: ChapterBatch) -> bool:
        threshold = int(self.config.runtime.world_evidence_signal_threshold)
        return self._fallback_world_signal_score("\n".join(doc.content for doc in batch.documents)) >= threshold

    def _fallback_world_signal_score(self, text: str) -> int:
        hit_count = sum(1 for keyword in WORLD_EVIDENCE_KEYWORDS if keyword in text)
        if hit_count <= 0:
            return 0
        return min(100, 35 + hit_count * 12)

    def _fallback_world_candidates(self, batch: ChapterBatch) -> list[dict[str, Any]]:
        full_text = "\n".join(doc.content for doc in batch.documents)
        section_by_keyword = {
            "血统": "能力体系",
            "能力": "能力体系",
            "学院": "阵营势力",
            "阵营": "阵营势力",
            "势力": "阵营势力",
            "禁忌": "核心禁忌与规则",
            "规则": "核心禁忌与规则",
            "时代": "时代背景",
            "世界": "世界类型",
        }
        candidates: list[dict[str, Any]] = []
        seen_sections: set[str] = set()
        for keyword, section in section_by_keyword.items():
            if keyword not in full_text or section in seen_sections:
                continue
            seen_sections.add(section)
            source_doc_ids = [doc.doc_id for doc in batch.documents if keyword in str(doc.content or "")]
            source_title_indexes = sorted(
                {doc.document_title_index for doc in batch.documents if keyword in str(doc.content or "")}
            )
            candidates.append(
                {
                    "section": section,
                    "summary": f"本批次涉及 {keyword} 相关稳定设定，需由 Global Memory 判断是否写入。",
                    "evidence_hint": keyword,
                    "source_doc_ids": source_doc_ids,
                    "source_title_indexes": source_title_indexes,
                    "confidence": 0.55,
                }
            )
        return candidates

    def _fallback_memory_candidate_output(
        self,
        batch: ChapterBatch,
        summary_payload: dict[str, Any],
        evidence_payload: dict[str, Any],
    ) -> dict[str, Any]:
        return self.memory_candidate_service.build_fallback_output(
            chapter_title=batch.chapter_title,
            document_title_index=batch.document_title_index,
            summary_payload=summary_payload,
            evidence_payload=evidence_payload,
        )

    def _document_mentions_from_character_evidence(
        self,
        *,
        batch: ChapterBatch,
        evidence_payload: dict[str, Any],
    ) -> list[dict[str, Any]]:
        legacy_mentions = evidence_payload.get("document_character_mentions")
        if isinstance(legacy_mentions, list):
            return legacy_mentions
        characters = self._flatten_character_evidence_items(evidence_payload)
        kept_names = {
            str(item.get("canonical_name", "")).strip()
            for item in self.memory_candidate_service.build_character_updates(
                summary_short="",
                evidence_payload=evidence_payload,
            )
        }
        names: list[str] = []
        name_aliases: dict[str, list[str]] = {}
        doc_mentions_by_id: dict[int, dict[str, Any]] = {}
        docs_by_id = {int(doc.doc_id): doc for doc in batch.documents}

        for doc_id in docs_by_id:
            doc_mentions_by_id[doc_id] = {
                "doc_id": doc_id,
                "character_keywords": [],
                "speaking_character_keywords": [],
                "character_evidence": {},
                "speaking_evidence": {},
                "character_aliases": {},
                "source_doc_verified_names": [],
                "source_doc_verified_speakers": [],
            }

        for item in characters:
            name = self.memory_candidate_service.clean_evidence_name(item.get("canonical_name"), character=item)
            if name and name in kept_names and name not in names:
                names.append(name)
            if not name or name not in kept_names:
                continue

            aliases = self._character_aliases_for_evidence(name=name, character=item)
            name_aliases[name] = aliases
            source_doc_ids = [
                doc_id
                for doc_id in self._safe_int_list(item.get("source_doc_ids"))
                if doc_id in docs_by_id
            ]
            if not source_doc_ids:
                source_doc_ids = [
                    doc_id
                    for doc_id, doc in docs_by_id.items()
                    if self._first_term_in_text(name=name, aliases=aliases, text=str(doc.content or ""))
                ]
            for doc_id in source_doc_ids:
                doc = docs_by_id[doc_id]
                doc_text = str(doc.content or "")
                mention = doc_mentions_by_id[doc_id]
                self._append_unique(mention["character_keywords"], name)
                self._append_unique(mention["source_doc_verified_names"], name)
                if aliases:
                    mention["character_aliases"][name] = aliases
                evidence_snippet = self._evidence_snippet_for_character(name=name, aliases=aliases, character=item, doc_text=doc_text)
                if evidence_snippet:
                    mention["character_evidence"].setdefault(name, [])
                    self._append_unique(mention["character_evidence"][name], evidence_snippet)
                if bool(item.get("is_speaking_character")):
                    self._append_unique(mention["speaking_character_keywords"], name)
                    self._append_unique(mention["source_doc_verified_speakers"], name)
                    speaking_snippet = self._evidence_snippet_for_character(
                        name=name,
                        aliases=aliases,
                        character=item,
                        doc_text=doc_text,
                        preferred_fields=("speaking_evidence",),
                    )
                    if speaking_snippet:
                        mention["speaking_evidence"].setdefault(name, [])
                        self._append_unique(mention["speaking_evidence"][name], speaking_snippet)

        # Preserve the old exact-text fallback for model payloads without source_doc_ids.
        for doc_id, doc in docs_by_id.items():
            doc_text = str(doc.content or "")
            mention = doc_mentions_by_id[doc_id]
            for name in names:
                aliases = name_aliases.get(name, [])
                if name not in mention["character_keywords"] and self._first_term_in_text(name=name, aliases=aliases, text=doc_text):
                    self._append_unique(mention["character_keywords"], name)
                    if aliases:
                        mention["character_aliases"][name] = aliases
                    evidence_snippet = self._evidence_snippet_for_character(name=name, aliases=aliases, character={}, doc_text=doc_text)
                    if evidence_snippet:
                        mention["character_evidence"].setdefault(name, [])
                        self._append_unique(mention["character_evidence"][name], evidence_snippet)
                if (
                    name in mention["character_keywords"]
                    and name not in mention["speaking_character_keywords"]
                    and self._name_has_speaking_cue_for_any_term(name=name, aliases=aliases, text=doc_text)
                ):
                    self._append_unique(mention["speaking_character_keywords"], name)
                    speaking_snippet = self._evidence_snippet_for_character(name=name, aliases=aliases, character={}, doc_text=doc_text)
                    if speaking_snippet:
                        mention["speaking_evidence"].setdefault(name, [])
                        self._append_unique(mention["speaking_evidence"][name], speaking_snippet)

        return [doc_mentions_by_id[int(doc.doc_id)] for doc in batch.documents]

    def _append_unique(self, values: list[Any], value: Any) -> None:
        if value not in values:
            values.append(value)

    def _character_aliases_for_evidence(self, *, name: str, character: dict[str, Any]) -> list[str]:
        raw_aliases = character.get("aliases", [])
        alias_items = raw_aliases if isinstance(raw_aliases, list) else []
        aliases: list[str] = []
        for raw_alias in alias_items:
            alias = str(raw_alias or "").strip()
            if not alias or alias == name or alias in aliases:
                continue
            if len(alias) > 12 or not re.fullmatch(r"[\u4e00-\u9fffA-Za-z·]{1,12}", alias):
                continue
            aliases.append(alias)
        return [alias for alias in aliases if alias != name]

    def _first_term_in_text(self, *, name: str, aliases: list[str], text: str) -> str:
        for term in [name, *aliases]:
            if term and term in text:
                return term
        return ""

    def _name_has_speaking_cue_for_any_term(self, *, name: str, aliases: list[str], text: str) -> bool:
        return any(self._name_has_speaking_cue(name=term, text=text) for term in [name, *aliases] if term)

    def _evidence_snippet_for_character(
        self,
        *,
        name: str,
        aliases: list[str],
        character: dict[str, Any],
        doc_text: str,
        preferred_fields: tuple[str, ...] = (
            "personhood_evidence",
            "activity_or_state_evidence",
            "speaking_evidence",
            "relationship_evidence",
        ),
    ) -> str:
        matching_term = self._first_term_in_text(name=name, aliases=aliases, text=doc_text)
        if matching_term:
            return self._excerpt_around_name(name=matching_term, text=doc_text)
        for field in preferred_fields:
            evidence = str(character.get(field, "")).strip()
            if evidence and evidence in doc_text:
                return evidence
        return ""

    def _flatten_character_evidence_items(self, evidence_payload: dict[str, Any]) -> list[dict[str, Any]]:
        characters = evidence_payload.get("characters")
        if isinstance(characters, list):
            batch_doc_ids = self._safe_int_list(evidence_payload.get("doc_ids"))
            batch_title_indexes = self._safe_int_list(evidence_payload.get("document_title_indexes"))
            flattened: list[dict[str, Any]] = []
            for item in characters:
                if not isinstance(item, dict):
                    continue
                character = dict(item)
                character.setdefault("source_doc_ids", batch_doc_ids)
                character.setdefault("source_title_indexes", batch_title_indexes)
                flattened.append(character)
            return flattened
        batches = evidence_payload.get("character_evidence_batches")
        flattened: list[dict[str, Any]] = []
        if isinstance(batches, list):
            for evidence_batch in batches:
                if not isinstance(evidence_batch, dict):
                    continue
                batch_doc_ids = self._safe_int_list(evidence_batch.get("doc_ids"))
                batch_title_indexes = self._safe_int_list(evidence_batch.get("document_title_indexes"))
                for item in evidence_batch.get("characters", []):
                    if isinstance(item, dict):
                        character = dict(item)
                        character.setdefault("source_doc_ids", batch_doc_ids)
                        character.setdefault("source_title_indexes", batch_title_indexes)
                        flattened.append(character)
        return flattened

    def _flatten_identity_revelations(self, evidence_payload: dict[str, Any]) -> list[dict[str, Any]]:
        revelations = evidence_payload.get("identity_revelations")
        if isinstance(revelations, list):
            batch_doc_ids = self._safe_int_list(evidence_payload.get("doc_ids"))
            batch_title_indexes = self._safe_int_list(evidence_payload.get("document_title_indexes"))
            flattened = []
            for item in revelations:
                if not isinstance(item, dict):
                    continue
                revelation = dict(item)
                revelation.setdefault("source_doc_ids", batch_doc_ids)
                revelation.setdefault("source_title_indexes", batch_title_indexes)
                flattened.append(revelation)
            return flattened
        batches = evidence_payload.get("character_evidence_batches")
        flattened: list[dict[str, Any]] = []
        if isinstance(batches, list):
            for evidence_batch in batches:
                if not isinstance(evidence_batch, dict):
                    continue
                batch_doc_ids = self._safe_int_list(evidence_batch.get("doc_ids"))
                batch_title_indexes = self._safe_int_list(evidence_batch.get("document_title_indexes"))
                for item in evidence_batch.get("identity_revelations", []):
                    if isinstance(item, dict):
                        revelation = dict(item)
                        revelation.setdefault("source_doc_ids", batch_doc_ids)
                        revelation.setdefault("source_title_indexes", batch_title_indexes)
                        flattened.append(revelation)
        return flattened

    def _excerpt_around_name(self, *, name: str, text: str) -> str:
        index = text.find(name)
        if index < 0:
            return ""
        return text[max(0, index - 18) : min(len(text), index + len(name) + 18)]

    def _sentence_with_name(self, *, name: str, text: str) -> str:
        for sentence in split_sentences(text):
            if name in sentence:
                return safe_excerpt(sentence, 160)
        return self._excerpt_around_name(name=name, text=text)

    def _name_has_speaking_cue(self, *, name: str, text: str) -> bool:
        escaped = re.escape(name)
        patterns = [
            rf"{escaped}.{{0,12}}(?:说|问|喊|答|道|叫|回应)",
            rf"(?:说|问|喊|答|道|叫|回应).{{0,12}}{escaped}",
        ]
        return any(re.search(pattern, text) for pattern in patterns)

    def _iter_persistable_payloads(
        self,
        *,
        batch: ChapterBatch,
        payload: dict[str, Any],
    ) -> list[tuple[ChapterBatch, dict[str, Any]]]:
        raw_chapter_summaries = payload.get("chapter_summaries")
        if not batch.is_multi_chapter:
            raw_chapter_summaries = None
        elif not isinstance(raw_chapter_summaries, list) and not self.config.runtime.dry_run:
            raise RuntimeError("Close-read model must return chapter_summaries for a multi-chapter batch")
        summaries_by_index: dict[int, dict[str, Any]] = {}
        if isinstance(raw_chapter_summaries, list):
            for item in raw_chapter_summaries:
                if not isinstance(item, dict):
                    continue
                try:
                    title_index = int(item.get("document_title_index"))
                except (TypeError, ValueError):
                    continue
                summaries_by_index[title_index] = item
        persistable: list[tuple[ChapterBatch, dict[str, Any]]] = []
        for title_index in batch.title_indexes:
            sub_batch = batch
            if batch.is_multi_chapter:
                sub_batch = batch.as_single_title_batch(title_index)
            sub_payload = self._payload_for_title_index(
                sub_batch=sub_batch,
                payload=payload,
                chapter_payload=summaries_by_index.get(title_index),
            )
            persistable.append((sub_batch, sub_payload))
        return persistable

    def _payload_for_title_index(
        self,
        *,
        sub_batch: ChapterBatch,
        payload: dict[str, Any],
        chapter_payload: dict[str, Any] | None,
    ) -> dict[str, Any]:
        if chapter_payload is None:
            if str(payload.get("chapter_summary_md") or "").strip():
                chapter_payload = {
                    key: payload.get(key)
                    for key in ("chapter_summary_md", "chapter_summary_short", "importance_score", "importance_reason", "related_chapters")
                }
            else:
                review_path = self._write_summary_review_markdown(
                    batch=sub_batch,
                    reason=f"missing chapter summary payload for document_title_index={sub_batch.document_title_index}",
                    payload=payload,
                )
                raise InvalidChapterSynopsisError(
                    f"Missing chapter summary payload for document_title_index={sub_batch.document_title_index}",
                    review_path=review_path,
                )
        sub_doc_ids = {doc.doc_id for doc in sub_batch.documents}
        base = {key: value for key, value in payload.items() if key != "chapter_summaries"}
        base.update({key: value for key, value in chapter_payload.items() if key not in {"document_title_index", "chapter_title"}})
        document_mentions = base.get("document_character_mentions")
        if isinstance(document_mentions, list):
            base["document_character_mentions"] = [
                item
                for item in document_mentions
                if isinstance(item, dict) and self._safe_int(item.get("doc_id")) in sub_doc_ids
            ]
        sub_names = set(self._names_from_document_mentions(base.get("document_character_mentions"), field="character_keywords"))
        character_updates = base.get("character_updates")
        if isinstance(character_updates, list):
            base["character_updates"] = [
                item
                for item in character_updates
                if isinstance(item, dict) and str(item.get("canonical_name", "")).strip() in sub_names
            ]
        return self._normalize_close_read_payload(
            batch=sub_batch,
            payload=base,
        )

    def _summary_payload_from_fallback(self, batch: ChapterBatch) -> dict[str, Any]:
        review_path = self._write_summary_review_markdown(
            batch=batch,
            reason="summary fallback is disabled; model must return a plot synopsis",
            payload=self._disallowed_summary_fallback(batch),
        )
        raise InvalidChapterSynopsisError("summary fallback is disabled", review_path=review_path)

    def _safe_int(self, value: object) -> int | None:
        try:
            return int(value)  # type: ignore[arg-type]
        except (TypeError, ValueError):
            return None

    def _safe_int_list(self, values: object) -> list[int]:
        if not isinstance(values, list):
            return []
        result: list[int] = []
        for value in values:
            try:
                result.append(int(value))
            except (TypeError, ValueError):
                continue
        return result

    def _disallowed_summary_fallback(self, batch: ChapterBatch) -> dict[str, Any]:
        return {
            "summary_quality": "fallback_excerpt_disallowed",
            "chapter_summary_md": "",
            "chapter_summary_short": "",
            "importance_score": 0,
            "importance_reason": "chapter_summary fallback is disabled; model must return plot synopsis",
            "related_chapters": [],
            "world_signal_score": 0,
            "world_evidence_candidates": [],
            "noise_documents": [
                {
                    "doc_id": int(doc.doc_id),
                    "document_title_index": int(doc.document_title_index),
                    "reason": "fallback disabled",
                }
                for doc in batch.documents
            ],
        }

    def _validate_summary_payload(self, *, batch: ChapterBatch, payload: dict[str, Any]) -> None:
        payload = self._normalize_chapter_summary_schema_aliases(payload)
        summary_quality = str(payload.get("summary_quality") or "").strip()
        if summary_quality in {"fallback_excerpt_disallowed", "fallback_excerpt"}:
            review_path = self._write_summary_review_markdown(
                batch=batch,
                reason=f"invalid summary_quality={summary_quality}",
                payload=payload,
            )
            raise InvalidChapterSynopsisError(f"invalid chapter summary quality: {summary_quality}", review_path=review_path)
        if batch.is_multi_chapter:
            raw_summaries = payload.get("chapter_summaries")
            if not isinstance(raw_summaries, list):
                review_path = self._write_summary_review_markdown(
                    batch=batch,
                    reason="multi-chapter batch missing chapter_summaries",
                    payload=payload,
                )
                raise InvalidChapterSynopsisError("multi-chapter batch missing chapter_summaries", review_path=review_path)
            by_index = {
                int(item.get("document_title_index")): self._normalize_chapter_summary_schema_aliases(item)
                for item in raw_summaries
                if isinstance(item, dict) and self._safe_int(item.get("document_title_index")) is not None
            }
            for title_index in batch.title_indexes:
                sub_batch = batch.as_single_title_batch(title_index)
                item = by_index.get(title_index)
                if item is None:
                    review_path = self._write_summary_review_markdown(
                        batch=sub_batch,
                        reason=f"missing plot synopsis for document_title_index={title_index}",
                        payload=payload,
                    )
                    raise InvalidChapterSynopsisError(
                        f"missing plot synopsis for document_title_index={title_index}",
                        review_path=review_path,
                    )
                self._validate_single_plot_synopsis(batch=sub_batch, payload=item)
            return
        self._validate_single_plot_synopsis(batch=batch, payload=payload)

    def _validate_single_plot_synopsis(self, *, batch: ChapterBatch, payload: dict[str, Any]) -> None:
        summary_quality = str(payload.get("summary_quality") or "").strip()
        if summary_quality == "low_signal_needs_review":
            self._validate_low_signal_summary(batch=batch, payload=payload)
            return
        if summary_quality in {"fallback_excerpt_disallowed", "fallback_excerpt"}:
            review_path = self._write_summary_review_markdown(
                batch=batch,
                reason=f"invalid summary_quality={summary_quality or '<empty>'}",
                payload=payload,
            )
            raise InvalidChapterSynopsisError(f"invalid chapter summary quality: {summary_quality}", review_path=review_path)
        summary_md = str(payload.get("chapter_summary_md") or "").strip()
        if not summary_md:
            review_path = self._write_summary_review_markdown(
                batch=batch,
                reason="missing chapter_summary_md plot synopsis",
                payload=payload,
            )
            raise InvalidChapterSynopsisError("missing chapter_summary_md plot synopsis", review_path=review_path)
        sections = self._parse_summary_sections(summary_md)
        if not sections["剧情事件链"]:
            if self._looks_like_low_signal_summary(batch=batch, summary_md=summary_md):
                return
            review_path = self._write_summary_review_markdown(
                batch=batch,
                reason="chapter_summary_md missing ## 剧情事件链 section",
                payload=payload,
            )
            raise InvalidChapterSynopsisError("chapter_summary_md missing plot event chain", review_path=review_path)
        if not sections["结构功能/节奏"]:
            if self._looks_like_low_signal_summary(batch=batch, summary_md=summary_md):
                return
            review_path = self._write_summary_review_markdown(
                batch=batch,
                reason="chapter_summary_md missing ## 结构功能/节奏 section",
                payload=payload,
            )
            raise InvalidChapterSynopsisError("chapter_summary_md missing structure/pacing section", review_path=review_path)
        min_chars = 40 if batch.total_chars < 160 else min(180, max(80, self._compute_summary_target_chars_min(batch.total_chars) // 2))
        if len(summary_md) < min_chars:
            review_path = self._write_summary_review_markdown(
                batch=batch,
                reason=f"chapter_summary_md too short for plot synopsis: {len(summary_md)} < {min_chars}",
                payload=payload,
            )
            raise InvalidChapterSynopsisError("chapter_summary_md too short for plot synopsis", review_path=review_path)
        copied = self._first_copied_source_span(batch=batch, summary_md=summary_md)
        if copied:
            review_path = self._write_summary_review_markdown(
                batch=batch,
                reason=f"chapter_summary_md appears to copy source text: {copied}",
                payload=payload,
            )
            raise InvalidChapterSynopsisError("chapter_summary_md appears to copy source text", review_path=review_path)

    def _looks_like_low_signal_summary(self, *, batch: ChapterBatch, summary_md: str) -> bool:
        text = str(summary_md or "").strip()
        if not text or batch.total_chars > 1_000:
            return False
        source_text = "\n".join(doc.content for doc in batch.documents)
        combined = f"{text}\n{batch.chapter_title}\n{source_text[:400]}"
        return any(hint in combined for hint in LOW_SIGNAL_SUMMARY_HINTS)

    def _validate_low_signal_summary(self, *, batch: ChapterBatch, payload: dict[str, Any]) -> None:
        summary_md = str(payload.get("chapter_summary_md") or "").strip()
        summary_short = str(payload.get("chapter_summary_short") or "").strip()
        noise_documents = payload.get("noise_documents")
        if not summary_md and not summary_short:
            review_path = self._write_summary_review_markdown(
                batch=batch,
                reason="low_signal_needs_review missing explanatory summary",
                payload=payload,
            )
            raise InvalidChapterSynopsisError("low_signal summary missing explanatory text", review_path=review_path)
        if not isinstance(noise_documents, list) or not noise_documents:
            review_path = self._write_summary_review_markdown(
                batch=batch,
                reason="low_signal_needs_review missing noise_documents",
                payload=payload,
            )
            raise InvalidChapterSynopsisError("low_signal summary missing noise_documents", review_path=review_path)
        copied = self._first_copied_source_span(batch=batch, summary_md=summary_md)
        if copied and not self._looks_like_low_signal_summary(batch=batch, summary_md=f"{summary_md}\n{summary_short}"):
            review_path = self._write_summary_review_markdown(
                batch=batch,
                reason=f"low_signal summary appears to copy source text: {copied}",
                payload=payload,
            )
            raise InvalidChapterSynopsisError("low_signal summary appears to copy source text", review_path=review_path)

    def _first_copied_source_span(self, *, batch: ChapterBatch, summary_md: str) -> str:
        normalized_summary = self._compact_for_overlap(summary_md)
        if not normalized_summary:
            return ""
        window = 30
        for doc in batch.documents:
            normalized_source = self._compact_for_overlap(doc.content)
            if len(normalized_source) < window:
                continue
            for start in range(0, len(normalized_source) - window + 1, 8):
                snippet = normalized_source[start : start + window]
                if snippet and snippet in normalized_summary:
                    return f"doc_id={doc.doc_id}: {safe_excerpt(snippet, 80)}"
        return ""

    def _compact_for_overlap(self, text: str) -> str:
        return re.sub(r"\s+", "", str(text))

    def _summary_review_path(self) -> Path:
        return self.repo_root / ".memory" / "review" / f"{self.config.book_id}.close_read_summary_review.md"

    def _write_summary_review_markdown(
        self,
        *,
        batch: ChapterBatch,
        reason: str,
        payload: dict[str, Any] | None = None,
    ) -> Path:
        path = self._summary_review_path()
        now = _utc_now()
        lines = [
            "",
            f"## {now} | document_title_index={batch.document_title_index} | {batch.chapter_title}",
            "",
            f"- reason: {reason}",
            f"- batch_label: {batch.batch_label}",
            f"- title_indexes: {batch.title_indexes}",
            f"- doc_ids: {[int(doc.doc_id) for doc in batch.documents]}",
            f"- total_chars: {batch.total_chars}",
            "",
            "### Documents",
        ]
        for doc in batch.documents:
            lines.extend(
                [
                    "",
                    f"#### doc_id={doc.doc_id} | title_index={doc.document_title_index} | {doc.document_title}",
                    "",
                    f"- source_path: {doc.source_path}",
                    f"- chars: {len(doc.content)}",
                    "",
                    "```text",
                    safe_excerpt(doc.content, 1200),
                    "```",
                ]
            )
        if payload is not None:
            lines.extend(
                [
                    "",
                    "### Model Payload",
                    "",
                    "```json",
                    json.dumps(payload, ensure_ascii=False, indent=2)[:6000],
                    "```",
                ]
            )
        with self._summary_review_lock:
            path.parent.mkdir(parents=True, exist_ok=True)
            if not path.exists():
                path.write_text(f"# Close Read Summary Review: {self.config.book_id}\n", encoding="utf-8")
            with path.open("a", encoding="utf-8") as file:
                file.write("\n".join(lines).rstrip() + "\n")
        return path

    def _compute_summary_target_chars_min(self, source_total_chars: int) -> int:
        if source_total_chars <= 0:
            return 180
        if source_total_chars <= 1500:
            return 160
        if source_total_chars <= 3000:
            return 220
        if source_total_chars <= 5000:
            return 320
        return 420

    def _normalize_close_read_payload(
        self,
        *,
        batch: ChapterBatch,
        payload: Any,
    ) -> dict[str, Any]:
        if not isinstance(payload, dict):
            review_path = self._write_summary_review_markdown(
                batch=batch,
                reason="close-read payload is not a JSON object",
                payload={"raw_payload_type": type(payload).__name__},
            )
            raise InvalidChapterSynopsisError("Close-read model returned a non-dict JSON payload", review_path=review_path)
        normalized = self._normalize_chapter_summary_schema_aliases(payload)
        if not str(normalized.get("chapter_summary_md", "")).strip():
            review_path = self._write_summary_review_markdown(
                batch=batch,
                reason="chapter_summary_md is missing or empty",
                payload=normalized,
            )
            raise InvalidChapterSynopsisError("chapter_summary_md is missing or empty", review_path=review_path)
        if not str(normalized.get("chapter_summary_short", "")).strip():
            normalized["chapter_summary_short"] = self._compute_short_summary(str(normalized["chapter_summary_md"]))
        if not isinstance(normalized.get("importance_score"), int):
            normalized["importance_score"] = 0
        if not str(normalized.get("importance_reason", "")).strip():
            normalized["importance_reason"] = "模型未提供重要性原因"
        if not isinstance(normalized.get("related_chapters"), list):
            normalized["related_chapters"] = []
        if not isinstance(normalized.get("document_character_mentions"), list):
            normalized["document_character_mentions"] = []
        if not isinstance(normalized.get("character_updates"), list):
            normalized["character_updates"] = []
        if not isinstance(normalized.get("world_update"), dict):
            normalized["world_update"] = {"should_update": False, "changes": []}
        if not isinstance(normalized.get("outline_update"), dict):
            normalized["outline_update"] = {"chapter_line": ""}
        self._validate_single_plot_synopsis(batch=batch, payload=normalized)
        required_text_fields = ["chapter_summary_md", "chapter_summary_short", "importance_reason"]
        for field in required_text_fields:
            if not str(normalized.get(field, "")).strip():
                raise RuntimeError(f"Close-read model returned empty required field: {field}")
        if not isinstance(normalized.get("importance_score"), int):
            raise RuntimeError("Close-read model returned invalid importance_score")
        if not isinstance(normalized.get("document_character_mentions"), list):
            raise RuntimeError("Close-read model returned invalid document_character_mentions")
        if not isinstance(normalized.get("character_updates"), list):
            raise RuntimeError("Close-read model returned invalid character_updates")
        if not isinstance(normalized.get("world_update"), dict):
            raise RuntimeError("Close-read model returned invalid world_update")
        if not isinstance(normalized.get("outline_update"), dict):
            raise RuntimeError("Close-read model returned invalid outline_update")
        return normalized

    def _persist_batch(
        self,
        *,
        conn,
        batch: ChapterBatch,
        payload: dict[str, Any],
        run_id: str,
        model_client: JsonModelClient,
        documents_repo: DocumentsRepo,
        chapters_repo: ChaptersRepo,
        progress_repo: ReadingProgressRepo,
        profile_service: CharacterProfileService,
        identity_merge_service: CharacterIdentityMergeService,
        identity_resolution_service: CharacterIdentityResolutionService,
        canonical_name_service: CharacterCanonicalNameService,
        world_service: WorldStateService,
        outline_service: OutlineService,
    ) -> int:
        existing = chapters_repo.get(
            conn,
            book_id=self.config.book_id,
            document_title_index=batch.document_title_index,
        )
        identity_candidate_results = identity_merge_service.review_revelations(
            conn,
            book_id=self.config.book_id,
            model_client=model_client,
            revelations=payload.get("identity_revelations", []),
        )
        for candidate in identity_candidate_results:
            self._emit_progress(
                {
                    "stage": DEFAULT_CLOSE_READING_STAGE,
                    "event": "identity_merge_candidate",
                    **candidate.to_dict(),
                }
            )
        blocking_identity_candidates = [candidate for candidate in identity_candidate_results if candidate.blocks_close_read]
        if blocking_identity_candidates:
            candidate_payloads = [candidate.to_dict() for candidate in blocking_identity_candidates]
            progress_repo.upsert(
                conn,
                {
                    "book_id": self.config.book_id,
                    "agent_stage": DEFAULT_CLOSE_READING_STAGE,
                    "current_doc_id": batch.documents[0].doc_id,
                    "current_document_title_index": batch.documents[0].document_title_index,
                    "current_source_path": batch.documents[0].source_path,
                    "current_source_offset": batch.documents[0].source_start_offset,
                    "last_completed_doc_id": self._last_completed_doc_id(conn, book_id=self.config.book_id),
                    "last_completed_title_index": self._last_completed_title_index(conn, book_id=self.config.book_id),
                    "last_completed_chapter_id": self._last_completed_chapter_id(conn, book_id=self.config.book_id),
                    "status": {
                        "state": "blocked_identity_merge_review",
                        "reason": "high-confidence character identity candidate requires user confirmation",
                        "candidate_ids": [item["candidate_id"] for item in candidate_payloads],
                        "candidates": candidate_payloads,
                    },
                    "checkpoint_token": f"{batch.documents[0].document_title_index}:{batch.documents[0].doc_id}:identity_merge_review",
                    "updated_at": _utc_now(),
                },
            )
            conn.commit()
            raise CloseReadIdentityMergeBlocked(candidate_payloads)
        existing_summary_md = str(existing["summary_md"] or "") if existing else ""
        summary_intermediate = self._load_json_list(existing["summary_intermediate_json"]) if existing else []
        if self._should_seed_existing_summary_intermediate(
            existing=existing,
            batch=batch,
            summary_intermediate=summary_intermediate,
        ):
            summary_intermediate.append(existing_summary_md)
        current_summary = self._normalize_chapter_summary(
            summary_md=str(payload.get("chapter_summary_md", "")).strip(),
            batch=batch,
            source_total_chars=batch.total_chars,
        )
        if current_summary:
            summary_intermediate.append(current_summary)
        (
            source_doc_start_id,
            source_doc_end_id,
            source_doc_count,
            effective_source_total_chars,
        ) = self._processed_chapter_source_stats(
            conn=conn,
            documents_repo=documents_repo,
            batch=batch,
        )
        final_summary = ""
        if batch.is_complete_chapter:
            final_summary = self._merge_intermediate_summaries(
                summaries=summary_intermediate or ([current_summary] if current_summary else []),
                batch=batch,
                source_total_chars=batch.chapter_total_chars or effective_source_total_chars,
            )
        summary_short = str(payload.get("chapter_summary_short", "")).strip()
        if batch.is_complete_chapter:
            summary_short = self._compute_short_summary(final_summary or current_summary)
        elif not summary_short:
            summary_short = self._compute_short_summary(current_summary)
        summary_for_outline = final_summary or current_summary
        if self._has_usable_outline_segment(payload.get("outline_update")):
            generated_outline_update = dict(payload.get("outline_update") or {})
        else:
            generated_outline_update = self._generate_chapter_outline_segment(
                model_client=model_client,
                batch=batch,
                summary_md=summary_for_outline,
                summary_short=summary_short,
                outline_update=payload.get("outline_update", {}),
            )
        document_mentions = self._normalize_document_character_mentions(batch=batch, payload=payload)
        speaking_mentions = self._normalize_document_speaking_mentions(batch=batch, payload=payload)
        for doc_id, names in speaking_mentions.items():
            document_mentions[doc_id] = sorted({*document_mentions.get(doc_id, []), *names})
        for doc in batch.documents:
            documents_repo.update_character_keywords(
                conn,
                doc_id=doc.doc_id,
                character_keywords=document_mentions.get(doc.doc_id, []),
                updated_at=_utc_now(),
            )
        mentioned_characters = sorted({name for keywords in document_mentions.values() for name in keywords})
        existing_mentioned_characters = self._load_json_list(existing["mentioned_characters_json"]) if existing else []
        merged_mentioned_characters = sorted({*existing_mentioned_characters, *mentioned_characters})
        existing_related = self._load_json_list(existing["related_chapters_json"]) if existing else []
        merged_related_chapters = self._merge_related_chapters(
            existing_related,
            payload.get("related_chapters", []),
        )
        existing_importance_score = int(existing["importance_score"] or 0) if existing else 0
        current_importance_score = int(payload.get("importance_score", 0) or 0)
        merged_importance_score = max(existing_importance_score, current_importance_score)
        existing_importance_reason = str(existing["importance_reason"] or "") if existing else ""
        merged_importance_reason = (
            str(payload.get("importance_reason", "")).strip()
            if current_importance_score >= existing_importance_score
            else existing_importance_reason
        )
        current_outline_update = self._enrich_outline_segment_update(
            batch=batch,
            outline_update=generated_outline_update,
            summary_short=summary_short,
        )
        outline_update = self._merge_outline_segment_updates(
            existing=self._load_json_dict(existing["outline_update_json"]) if existing else {},
            current=current_outline_update,
            prefer_current_segment=batch.is_complete_chapter,
        )
        chapter_id = chapters_repo.upsert(
            conn,
            {
                "book_id": self.config.book_id,
                "document_title_index": batch.document_title_index,
                "chapter_title": batch.chapter_title,
                "source_doc_start_id": source_doc_start_id,
                "source_doc_end_id": source_doc_end_id,
                "source_doc_count": source_doc_count,
                "source_total_chars": effective_source_total_chars,
                "summary_intermediate": summary_intermediate,
                "summary_md": final_summary if batch.is_complete_chapter else existing_summary_md,
                "summary_short": summary_short,
                "summary_status": "provisional",
                "summary_evidence_window": f"{batch.document_title_index}-{batch.document_title_index}",
                "summary_target_range": f"{batch.document_title_index}-{batch.document_title_index}",
                "importance_score": merged_importance_score,
                "importance_reason": merged_importance_reason,
                "related_chapters": merged_related_chapters,
                "mentioned_characters": merged_mentioned_characters,
                "world_update": payload.get("world_update", {}),
                "outline_update": outline_update,
                "outline_status": "provisional",
                "outline_evidence_window": f"{batch.document_title_index}-{batch.document_title_index}",
                "outline_target_range": f"{batch.document_title_index}-{batch.document_title_index}",
                "close_read_run_id": run_id,
                "created_at": str(existing["created_at"]) if existing else _utc_now(),
                "updated_at": _utc_now(),
            },
        )
        evidence_payload = payload.get("character_evidence_payload") if isinstance(payload.get("character_evidence_payload"), dict) else {}
        self._append_character_evidence_log(
            conn,
            evidence_payload=evidence_payload,
            outline_update=outline_update,
        )
        raw_character_updates = [item for item in payload.get("character_updates", []) if isinstance(item, dict)]
        source_verified_names = sorted({name for values in document_mentions.values() for name in values})
        source_verified_speakers = sorted({name for values in speaking_mentions.values() for name in values})
        if not raw_character_updates:
            raw_character_updates = self.memory_candidate_service.build_character_updates(
                summary_short=summary_short,
                evidence_payload=evidence_payload,
            )
            if not raw_character_updates:
                raw_character_updates = [
                    {
                        "canonical_name": name,
                        "aliases": [],
                        "personality": [],
                        "occupations": [],
                        "recent_activity": summary_short,
                        "relationships": [],
                    }
                    for name in mentioned_characters
                ]
        else:
            raw_character_updates = self._augment_character_updates_from_source_verified_names(
                raw_character_updates=raw_character_updates,
                source_verified_names=source_verified_names,
                summary_short=summary_short,
            )
        self._emit_progress(
            {
                "stage": "close_reading",
                "agent": "character_identity_resolution",
                "event": "service_start",
                "document_title_indexes": batch.title_indexes,
                "doc_count": len(batch.documents),
                "total_chars": batch.total_chars,
                "update_count": len(raw_character_updates),
            }
        )
        started_at = time.perf_counter()
        raw_character_updates = identity_resolution_service.resolve_updates(
            conn,
            book_id=self.config.book_id,
            model_client=model_client,
            updates=raw_character_updates,
            source_verified_names=source_verified_names,
            source_verified_speakers=source_verified_speakers,
        )
        self._emit_progress(
            {
                "stage": "close_reading",
                "agent": "character_identity_resolution",
                "event": "service_end",
                "document_title_indexes": batch.title_indexes,
                "doc_count": len(batch.documents),
                "total_chars": batch.total_chars,
                "update_count": len(raw_character_updates),
                "duration_seconds": round(time.perf_counter() - started_at, 3),
            }
        )
        self._emit_progress(
            {
                "stage": "close_reading",
                "agent": "character_canonical_name_resolution",
                "event": "service_start",
                "document_title_indexes": batch.title_indexes,
                "doc_count": len(batch.documents),
                "total_chars": batch.total_chars,
                "update_count": len(raw_character_updates),
            }
        )
        started_at = time.perf_counter()
        raw_character_updates = canonical_name_service.resolve_updates(
            conn,
            book_id=self.config.book_id,
            model_client=model_client,
            updates=raw_character_updates,
        )
        self._emit_progress(
            {
                "stage": "close_reading",
                "agent": "character_canonical_name_resolution",
                "event": "service_end",
                "document_title_indexes": batch.title_indexes,
                "doc_count": len(batch.documents),
                "total_chars": batch.total_chars,
                "update_count": len(raw_character_updates),
                "duration_seconds": round(time.perf_counter() - started_at, 3),
            }
        )
        profile_service.merge_updates(
            conn,
            book_id=self.config.book_id,
            chapter_index=batch.document_title_index,
            doc_ids=[doc.doc_id for doc in batch.documents],
            updates=raw_character_updates,
            mentioned_doc_ids_by_name=self._invert_mentions(document_mentions),
            speaking_doc_ids_by_name=self._invert_mentions(speaking_mentions),
            story_events_by_name={},
        )
        self._apply_pending_character_reduces(
            conn=conn,
            model_client=model_client,
            batch=batch,
            profile_service=profile_service,
            evidence_payload=evidence_payload,
            summary_payload={
                "chapter_summary_short": summary_short,
                "chapter_summaries": payload.get("chapter_summaries", []),
                "document_title_index": batch.document_title_index,
                "chapter_title": batch.chapter_title,
            },
            current_outline_segment=outline_update,
        )
        world_service.apply_update(book_id=self.config.book_id, world_update=payload.get("world_update", {}))
        return chapter_id

    def _augment_character_updates_from_source_verified_names(
        self,
        *,
        raw_character_updates: list[dict[str, Any]],
        source_verified_names: list[str],
        summary_short: str,
    ) -> list[dict[str, Any]]:
        update_names: set[str] = set()
        for update in raw_character_updates:
            canonical_name = str(update.get("canonical_name") or "").strip()
            if canonical_name:
                update_names.add(canonical_name)
            aliases = update.get("aliases")
            if isinstance(aliases, list):
                update_names.update(str(alias).strip() for alias in aliases if str(alias).strip())
        augmented = list(raw_character_updates)
        for name in source_verified_names:
            if name in update_names:
                continue
            update_names.add(name)
            augmented.append(
                {
                    "canonical_name": name,
                    "aliases": [],
                    "personality": [],
                    "occupations": [],
                    "recent_activity": summary_short,
                    "relationships": [],
                    "evidence_level": "inferred",
                }
            )
        return augmented

    def _enrich_outline_segment_update(
        self,
        *,
        batch: ChapterBatch,
        outline_update: object,
        summary_short: str,
    ) -> dict[str, Any]:
        raw = dict(outline_update) if isinstance(outline_update, dict) else {}
        doc_ids = [doc.doc_id for doc in batch.documents]
        doc_range = self._doc_range_text(doc_ids)
        title_indexes = sorted({doc.document_title_index for doc in batch.documents})
        outline_segment = str(raw.get("outline_segment") or "").strip() or summary_short
        chapter_line = str(raw.get("chapter_line") or "").strip()
        if not chapter_line:
            chapter_line = f"[{batch.document_title_index}] {batch.chapter_title}: {summary_short}".rstrip(": ")
        return {
            "chapter_line": chapter_line,
            "outline_segment": outline_segment,
            "outline_segment_id": str(raw.get("outline_segment_id") or "").strip()
            or self._outline_segment_id(
                document_title_index=batch.document_title_index,
                source_doc_range=doc_range,
            ),
            "compression_notes": str(raw.get("compression_notes") or "").strip(),
            "source_doc_ids": doc_ids,
            "source_doc_range": doc_range,
            "source_doc_start_id": doc_ids[0] if doc_ids else 0,
            "source_doc_end_id": doc_ids[-1] if doc_ids else 0,
            "source_title_indexes": title_indexes,
            "source_chapter_range": self._doc_range_text(title_indexes),
            "status": "provisional",
        }

    def _has_usable_outline_segment(self, outline_update: object) -> bool:
        if not isinstance(outline_update, dict):
            return False
        return bool(str(outline_update.get("outline_segment") or "").strip())

    def _story_experiences_by_character(
        self,
        outline_update: dict[str, Any],
        *,
        mentioned_characters: list[str],
    ) -> dict[str, list[dict[str, Any]]]:
        names = self.character_mention_service.clean_names(mentioned_characters)
        summary = str(outline_update.get("outline_segment") or outline_update.get("chapter_line") or "").strip()
        if not names or not summary:
            return {}
        title_indexes = self._safe_int_list(outline_update.get("source_title_indexes"))
        doc_ids = self._safe_int_list(outline_update.get("source_doc_ids"))
        experience_id = str(outline_update.get("outline_segment_id") or "").strip() or self._outline_segment_id(
            document_title_index=title_indexes[-1] if title_indexes else 0,
            source_doc_range=str(outline_update.get("source_doc_range") or ""),
        )
        item = {
            "event_id": experience_id,
            "experience_id": experience_id,
            "label": str(outline_update.get("chapter_line") or "").strip() or summary[:24],
            "summary": summary,
            "source_chapter_indexes": title_indexes,
            "source_chapter_range": str(outline_update.get("source_chapter_range") or ""),
            "source_doc_ids": doc_ids,
            "source_doc_range": str(outline_update.get("source_doc_range") or ""),
            "participants": names,
            "status": str(outline_update.get("status") or "provisional"),
        }
        return {name: [dict(item)] for name in names}

    def _merge_outline_segment_updates(
        self,
        *,
        existing: dict[str, Any],
        current: dict[str, Any],
        prefer_current_segment: bool = False,
    ) -> dict[str, Any]:
        if not existing:
            return dict(current)
        if not current:
            return dict(existing)

        merged = dict(existing)
        for key, value in current.items():
            if key in {"source_doc_ids", "source_title_indexes", "source_doc_range", "outline_segment"}:
                continue
            if value not in (None, "", [], {}):
                merged[key] = value

        source_doc_ids = sorted(
            {
                doc_id
                for source in (existing, current)
                for doc_id in self._safe_int_list(source.get("source_doc_ids"))
            }
        )
        source_title_indexes = sorted(
            {
                title_index
                for source in (existing, current)
                for title_index in self._safe_int_list(source.get("source_title_indexes"))
            }
        )
        existing_segment = str(existing.get("outline_segment") or "").strip()
        current_segment = str(current.get("outline_segment") or "").strip()
        if prefer_current_segment and current_segment:
            outline_segment = current_segment
        else:
            outline_segment = self._join_distinct_outline_segments([existing_segment, current_segment])
        merged["outline_segment"] = outline_segment
        merged["source_doc_ids"] = source_doc_ids
        merged["source_doc_range"] = self._doc_range_text(source_doc_ids)
        merged["source_doc_start_id"] = source_doc_ids[0] if source_doc_ids else 0
        merged["source_doc_end_id"] = source_doc_ids[-1] if source_doc_ids else 0
        merged["source_title_indexes"] = source_title_indexes
        merged["source_chapter_range"] = self._doc_range_text(source_title_indexes)
        merged["status"] = str(current.get("status") or existing.get("status") or "provisional")
        return merged

    def _outline_segment_id(self, *, document_title_index: int, source_doc_range: str = "") -> str:
        source_suffix = re.sub(r"[^\w\u4e00-\u9fff]+", "-", str(source_doc_range or "")).strip("-").lower()
        if source_suffix:
            return f"outline-segment:chapter-{document_title_index}:docs-{source_suffix}"
        return f"outline-segment:chapter-{document_title_index}"

    def _join_distinct_outline_segments(self, summaries: list[str]) -> str:
        parts: list[str] = []
        seen: set[str] = set()
        for summary in summaries:
            text = re.sub(r"\s+", " ", str(summary or "")).strip()
            if not text:
                continue
            normalized = re.sub(r"[^\w\u4e00-\u9fff]+", "", text).lower()
            if normalized in seen:
                continue
            seen.add(normalized)
            parts.append(text)
        return " ".join(parts)

    def _doc_range_text(self, doc_ids: list[int]) -> str:
        if not doc_ids:
            return ""
        return str(doc_ids[0]) if len(doc_ids) == 1 else f"{doc_ids[0]}-{doc_ids[-1]}"

    def _should_seed_existing_summary_intermediate(
        self,
        *,
        existing: Any,
        batch: ChapterBatch,
        summary_intermediate: list[Any],
    ) -> bool:
        if not existing or summary_intermediate:
            return False
        if not str(existing["summary_md"] or "").strip():
            return False
        if not batch.documents:
            return False
        existing_start_id = self._safe_int(existing["source_doc_start_id"]) or 0
        existing_end_id = self._safe_int(existing["source_doc_end_id"]) or 0
        first_batch_doc_id = batch.documents[0].doc_id
        last_batch_doc_id = batch.documents[-1].doc_id
        return 0 < existing_start_id < first_batch_doc_id and existing_end_id < last_batch_doc_id

    def _processed_chapter_source_stats(
        self,
        *,
        conn,
        documents_repo: DocumentsRepo,
        batch: ChapterBatch,
    ) -> tuple[int, int, int, int]:
        chapter_docs = documents_repo.fetch_by_title_index(
            conn,
            book_id=self.config.book_id,
            document_title_index=batch.document_title_index,
        )
        if not chapter_docs:
            return (
                batch.documents[0].doc_id,
                batch.documents[-1].doc_id,
                len(batch.documents),
                batch.total_chars,
            )
        source_doc_end_id = chapter_docs[-1].doc_id if batch.is_complete_chapter else batch.documents[-1].doc_id
        processed_docs = [doc for doc in chapter_docs if doc.doc_id <= source_doc_end_id]
        return (
            chapter_docs[0].doc_id,
            source_doc_end_id,
            len(processed_docs),
            sum(doc.content_chars for doc in processed_docs),
        )

    def _normalize_chapter_summary(self, *, summary_md: str, batch: ChapterBatch, source_total_chars: int) -> str:
        sections = self._parse_summary_sections(summary_md)
        if self._looks_like_low_signal_summary(batch=batch, summary_md=summary_md):
            sections = self._normalize_low_signal_summary_sections(summary_md)
        if not sections["剧情事件链"]:
            review_path = self._write_summary_review_markdown(
                batch=batch,
                reason="normalized chapter summary has no plot event chain",
                payload={"chapter_summary_md": summary_md},
            )
            raise InvalidChapterSynopsisError("normalized chapter summary has no plot event chain", review_path=review_path)
        if not sections["人物状态/关系变化"]:
            sections["人物状态/关系变化"] = ["- 见本批次剧情中的人物行动、情绪与关系变化。"]
        if not sections["关键信息/设定"]:
            sections["关键信息/设定"] = ["- 见本批次剧情中涉及的关键信息与设定。"]
        if not sections["结构功能/节奏"]:
            review_path = self._write_summary_review_markdown(
                batch=batch,
                reason="normalized chapter summary has no structure/pacing section",
                payload={"chapter_summary_md": summary_md},
            )
            raise InvalidChapterSynopsisError("normalized chapter summary has no structure/pacing section", review_path=review_path)
        sections["摘要元信息"] = self._build_summary_meta_lines(batch=batch, source_total_chars=source_total_chars)
        rendered = self._render_summary_sections(sections)
        return clamp_text(rendered, CHAPTER_SUMMARY_MAX_CHARS)

    def _normalize_low_signal_summary_sections(self, summary_md: str) -> dict[str, list[str]]:
        text = str(summary_md or "").strip() or "模型判断该批次为低信号文本，缺少可概括剧情。"
        return {
            "摘要元信息": [],
            "剧情事件链": [f"- {text}"],
            "人物状态/关系变化": ["- 该批次未形成可确认的人物行动或关系变化。"],
            "关键信息/设定": ["- 仅保留目录、题记、献词或基调信息；不写入新增剧情事实。"],
            "结构功能/节奏": ["- 低信号前置文本，主要提供书籍结构、题名、献词或基调，不承担完整剧情推进。"],
        }

    def _merge_intermediate_summaries(
        self,
        *,
        summaries: list[str],
        batch: ChapterBatch,
        source_total_chars: int,
    ) -> str:
        merged_sections = {section: [] for section in CHAPTER_SUMMARY_SECTION_ORDER}
        for summary in summaries:
            parsed_sections = self._parse_summary_sections(summary)
            for section in CHAPTER_SUMMARY_SECTION_ORDER:
                if section == "摘要元信息":
                    continue
                merged_sections[section].extend(parsed_sections[section])
        for section in ("剧情事件链", "人物状态/关系变化", "关键信息/设定", "结构功能/节奏"):
            merged_sections[section] = self._dedupe_lines(merged_sections[section])
        if not merged_sections["剧情事件链"]:
            merged_sections["剧情事件链"] = ["- 暂缺。"]
        if not merged_sections["人物状态/关系变化"]:
            merged_sections["人物状态/关系变化"] = ["- 暂缺。"]
        if not merged_sections["关键信息/设定"]:
            merged_sections["关键信息/设定"] = ["- 暂缺。"]
        if not merged_sections["结构功能/节奏"]:
            merged_sections["结构功能/节奏"] = ["- 暂缺。"]
        merged_sections["摘要元信息"] = self._build_summary_meta_lines(
            batch=batch,
            source_total_chars=source_total_chars,
            merged_batches=len(summaries),
        )
        return self._render_summary_sections(merged_sections)

    def _build_summary_meta_lines(
        self,
        *,
        batch: ChapterBatch,
        source_total_chars: int,
        merged_batches: int | None = None,
    ) -> list[str]:
        mode = "整章输入" if not batch.is_split_batch else "拆批输入"
        lines = [
            f"- 章节索引：{batch.document_title_index}",
            f"- 输入模式：{mode}",
            f"- 本次批次：{batch.batch_label}",
            f"- 本次文档数：{batch.batch_doc_count}",
            f"- 本次源文本长度：{batch.total_chars}",
            f"- 章节总文本长度：{source_total_chars}",
        ]
        if batch.chapter_doc_count:
            lines.append(f"- 章节总文档数：{batch.chapter_doc_count}")
        if merged_batches and merged_batches > 1:
            lines.append(f"- 汇总批次数：{merged_batches}")
        return lines

    def _parse_summary_sections(self, summary_md: str) -> dict[str, list[str]]:
        sections = {section: [] for section in CHAPTER_SUMMARY_SECTION_ORDER}
        current_section = "剧情事件链"
        if not summary_md.strip():
            return sections
        for raw_line in summary_md.splitlines():
            line = raw_line.rstrip()
            stripped = line.strip()
            if stripped.startswith("## "):
                candidate = stripped[3:].strip()
                current_section = CHAPTER_SUMMARY_SECTION_ALIASES.get(candidate, current_section)
                continue
            if stripped.startswith("### "):
                candidate = stripped[4:].strip()
                current_section = CHAPTER_SUMMARY_SECTION_ALIASES.get(candidate, current_section)
                continue
            if not stripped:
                continue
            if current_section not in sections:
                current_section = "剧情事件链"
            sections[current_section].append(self._normalize_summary_line(stripped))
        return sections

    def _split_summary_lines(self, summary_md: str) -> list[str]:
        paragraph_lines = []
        for raw_line in summary_md.splitlines():
            stripped = raw_line.strip()
            if not stripped or stripped.startswith("#"):
                continue
            paragraph_lines.append(self._normalize_summary_line(stripped))
        if paragraph_lines:
            return paragraph_lines
        return [self._normalize_summary_line(sentence) for sentence in split_sentences(summary_md)]

    def _normalize_summary_line(self, line: str) -> str:
        stripped = str(line).strip()
        if not stripped:
            return ""
        if stripped.startswith("- "):
            return stripped
        return f"- {stripped}"

    def _render_summary_sections(self, sections: dict[str, list[str]]) -> str:
        lines: list[str] = []
        for section in CHAPTER_SUMMARY_SECTION_ORDER:
            lines.append(f"## {section}")
            lines.extend(sections[section] or ["- 暂缺。"])
            lines.append("")
        return "\n".join(lines).strip() + "\n"

    def _dedupe_lines(self, lines: list[str]) -> list[str]:
        ordered: list[str] = []
        seen: set[str] = set()
        for line in lines:
            normalized = re.sub(r"[^\w\u4e00-\u9fff]+", "", str(line)).lower()
            if not normalized or normalized in seen:
                continue
            seen.add(normalized)
            ordered.append(line)
        return ordered

    def _compute_short_summary(self, summary_md: str) -> str:
        summary_sections = self._parse_summary_sections(summary_md)
        plot_text = " ".join(item[2:] if item.startswith("- ") else item for item in summary_sections["剧情事件链"])
        if plot_text.strip():
            return safe_excerpt(plot_text, 120)
        return safe_excerpt(summary_md, 120)

    def _flatten_summary_event_chain(self, summary_md: str) -> str:
        summary_sections = self._parse_summary_sections(summary_md)
        plot_items: list[str] = []
        for item in summary_sections["剧情事件链"]:
            text = item[2:] if item.startswith("- ") else item
            text = re.sub(r"\s+", " ", text).strip()
            if text:
                plot_items.append(text)
        return " ".join(plot_items)

    def _merge_related_chapters(self, existing: Any, current: Any) -> list[dict[str, Any]]:
        merged: dict[int, dict[str, Any]] = {}
        for item in [*(existing if isinstance(existing, list) else []), *(current if isinstance(current, list) else [])]:
            if not isinstance(item, dict):
                continue
            raw_index = item.get("document_title_index")
            if raw_index is None:
                continue
            try:
                title_index = int(str(raw_index))
            except (TypeError, ValueError):
                continue
            score = int(item.get("score", 0) or 0)
            reason = str(item.get("reason", "")).strip()
            previous = merged.get(title_index)
            if previous is None or score >= int(previous.get("score", 0)):
                merged[title_index] = {
                    "document_title_index": title_index,
                    "score": max(0, min(score, 100)),
                    "reason": reason,
                }
        return [merged[key] for key in sorted(merged)]

    def _load_json_list(self, raw_value: object) -> list[Any]:
        if not raw_value:
            return []
        try:
            value = json.loads(str(raw_value))
        except json.JSONDecodeError:
            return []
        return value if isinstance(value, list) else []

    def _load_json_dict(self, raw_value: object) -> dict[str, Any]:
        if not raw_value:
            return {}
        try:
            value = json.loads(str(raw_value))
        except json.JSONDecodeError:
            return {}
        return value if isinstance(value, dict) else {}

    @staticmethod
    def _row_has_column(row: Any, column: str) -> bool:
        try:
            return column in row.keys()
        except AttributeError:
            return False

    def _load_character_profiles_with_budget(
        self,
        conn,
        *,
        profile_service: CharacterProfileService,
        names: list[str],
        chars_budget: int,
    ) -> list[dict[str, str]]:
        rows = profile_service.load_profiles(conn, book_id=self.config.book_id, names=names)
        selected: list[dict[str, str]] = []
        used_chars = 0
        for row in rows:
            summary = str(row.get("profile_summary_md", ""))
            remaining = chars_budget - used_chars
            if remaining <= 0:
                break
            clipped_summary = clamp_text(summary, remaining)
            if not clipped_summary.strip():
                continue
            selected.append(
                {
                    "canonical_name": str(row.get("canonical_name", "")).strip(),
                    "profile_summary_md": clipped_summary,
                }
            )
            used_chars += len(clipped_summary)
        return selected

    def _normalize_document_character_mentions(self, *, batch: ChapterBatch, payload: dict[str, Any]) -> dict[int, list[str]]:
        mention_items = payload.get("document_character_mentions", [])
        if not isinstance(mention_items, list):
            mention_items = []
        # Do not trust local heuristic candidates as final output. Only accept model mentions
        # that can be verified by evidence snippets against the document text.
        mentions_by_doc_id = {doc.doc_id: [] for doc in batch.documents}
        doc_text_by_id = {doc.doc_id: str(doc.content or "") for doc in batch.documents}
        valid_doc_ids = {doc.doc_id for doc in batch.documents}
        for item in mention_items:
            if not isinstance(item, dict):
                continue
            raw_doc_id = item.get("doc_id")
            if raw_doc_id is None:
                continue
            try:
                doc_id = int(raw_doc_id)
            except (TypeError, ValueError):
                continue
            if doc_id not in valid_doc_ids:
                continue
            raw_keywords = item.get("character_keywords", [])
            keyword_items = raw_keywords if isinstance(raw_keywords, list) else []
            evidence_map = item.get("character_evidence")
            evidence_mapping = evidence_map if isinstance(evidence_map, dict) else {}
            aliases_map = item.get("character_aliases")
            aliases_mapping = aliases_map if isinstance(aliases_map, dict) else {}
            cleaned_keywords = self._clean_model_mention_names(
                keyword_items,
                evidence_mapping=evidence_mapping,
                aliases_mapping=aliases_mapping,
            )
            filtered = self.character_evidence_validator.filter_names(
                doc_text=doc_text_by_id.get(doc_id, ""),
                names=cleaned_keywords,
                evidence_map=evidence_mapping,
                aliases_by_name=aliases_mapping,
            )
            trusted = self._clean_trusted_source_names(item.get("source_doc_verified_names", []))
            mentions_by_doc_id[doc_id] = self._dedupe_preserve_order([*filtered, *trusted])
        return mentions_by_doc_id

    def _clean_model_mention_names(
        self,
        names: list[object],
        *,
        evidence_mapping: dict[str, object],
        aliases_mapping: dict[str, object] | None = None,
    ) -> list[str]:
        cleaned: list[str] = []
        for raw_name in names:
            raw_text = str(raw_name or "").strip()
            evidence = evidence_mapping.get(raw_text)
            evidence_text = " ".join(str(item) for item in evidence) if isinstance(evidence, list) else str(evidence or "")
            raw_aliases = (aliases_mapping or {}).get(raw_text, [])
            aliases = raw_aliases if isinstance(raw_aliases, list) else []
            name = self.memory_candidate_service.clean_evidence_name(
                raw_text,
                character={
                    "canonical_name": raw_text,
                    "aliases": aliases,
                    "confidence": 0.75,
                    "personhood_evidence": evidence_text or raw_text,
                    "activity_or_state_evidence": evidence_text,
                },
            )
            if name and name not in cleaned:
                cleaned.append(name)
        return cleaned

    def _clean_trusted_source_names(self, names: object) -> list[str]:
        name_items = names if isinstance(names, list) else []
        cleaned: list[str] = []
        for raw_name in name_items:
            raw_text = str(raw_name or "").strip()
            if not raw_text or len(raw_text) > 12 or not re.fullmatch(r"[\u4e00-\u9fffA-Za-z·]{1,12}", raw_text):
                continue
            name = self.memory_candidate_service.clean_evidence_name(
                raw_text,
                character={
                    "canonical_name": raw_text,
                    "confidence": 0.8,
                    "personhood_evidence": raw_text,
                    "activity_or_state_evidence": raw_text,
                },
            )
            if name and name not in cleaned:
                cleaned.append(name)
        return cleaned

    def _dedupe_preserve_order(self, values: list[str]) -> list[str]:
        deduped: list[str] = []
        for value in values:
            if value and value not in deduped:
                deduped.append(value)
        return deduped

    def _normalize_document_speaking_mentions(self, *, batch: ChapterBatch, payload: dict[str, Any]) -> dict[int, list[str]]:
        mention_items = payload.get("document_character_mentions", [])
        if not isinstance(mention_items, list):
            mention_items = []
        mentions_by_doc_id = {doc.doc_id: [] for doc in batch.documents}
        doc_text_by_id = {doc.doc_id: str(doc.content or "") for doc in batch.documents}
        valid_doc_ids = {doc.doc_id for doc in batch.documents}
        for item in mention_items:
            if not isinstance(item, dict):
                continue
            try:
                doc_id = int(item.get("doc_id"))
            except (TypeError, ValueError):
                continue
            if doc_id not in valid_doc_ids:
                continue
            raw_keywords = item.get("speaking_character_keywords", [])
            keyword_items = raw_keywords if isinstance(raw_keywords, list) else []
            evidence_map = item.get("speaking_evidence")
            evidence_mapping = evidence_map if isinstance(evidence_map, dict) else {}
            aliases_map = item.get("character_aliases")
            aliases_mapping = aliases_map if isinstance(aliases_map, dict) else {}
            cleaned_keywords = self._clean_model_mention_names(
                keyword_items,
                evidence_mapping=evidence_mapping,
                aliases_mapping=aliases_mapping,
            )
            filtered = self.character_evidence_validator.filter_names(
                doc_text=doc_text_by_id.get(doc_id, ""),
                names=cleaned_keywords,
                evidence_map=evidence_mapping,
                aliases_by_name=aliases_mapping,
            )
            trusted = self._clean_trusted_source_names(item.get("source_doc_verified_speakers", []))
            mentions_by_doc_id[doc_id] = self._dedupe_preserve_order([*filtered, *trusted])
        return mentions_by_doc_id

    def _invert_mentions(self, mentions_by_doc_id: dict[int, list[str]]) -> dict[str, list[int]]:
        inverted: dict[str, list[int]] = {}
        for doc_id, names in mentions_by_doc_id.items():
            for name in names:
                inverted.setdefault(name, []).append(doc_id)
        return {name: sorted(set(doc_ids)) for name, doc_ids in inverted.items()}

from __future__ import annotations

import json
import uuid
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable

from ..constants import DEFAULT_CLOSE_READING_STAGE
from ..llm import JsonModelClient, ModelSettings
from ..repos.assets_repo import AssetsRepo
from ..repos.chapters_repo import ChaptersRepo
from ..repos.character_profiles_repo import CharacterProfilesRepo
from ..repos.db import NovelAgentDB
from ..repos.documents_repo import DocumentRow, DocumentsRepo
from ..repos.reading_progress_repo import ReadingProgressRepo
from ..runner.close_read_runner import CloseReadRunner
from ..schemas.config_schema import CloseReadAgentConfig
from .chapter_assembler_service import SPLIT_REASON_FULL_CHAPTER, SPLIT_REASON_OVER_BUDGET, ChapterBatch
from .character_canonical_name_service import CharacterCanonicalNameService
from .character_profile_service import CharacterProfileService
from .character_roster_service import CharacterRosterService
from .outline_service import OutlineService
from .world_state_service import WorldStateService


@dataclass(slots=True)
class CharacterMemoryRepairResult:
    book_id: str
    min_title_index: int | None
    max_doc_id: int | None
    processed_batches: int = 0
    processed_documents: int = 0
    updated_documents: int = 0
    profile_count_before: int = 0
    profile_count_after: int = 0
    mentioned_characters: list[str] = field(default_factory=list)
    run_id: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "book_id": self.book_id,
            "min_title_index": self.min_title_index,
            "max_doc_id": self.max_doc_id,
            "processed_batches": self.processed_batches,
            "processed_documents": self.processed_documents,
            "updated_documents": self.updated_documents,
            "profile_count_before": self.profile_count_before,
            "profile_count_after": self.profile_count_after,
            "mentioned_characters": self.mentioned_characters,
            "run_id": self.run_id,
        }


class CharacterMemoryRepairService:
    """Backfills character mentions and profiles from existing close-read summaries.

    This service deliberately skips chapter-summary, world, and outline model calls. It
    reuses the already persisted chapter summaries as context while rerunning the
    character evidence and character reduce agents for documents that have already
    reached the close-read checkpoint.
    """

    def __init__(
        self,
        *,
        repo_root: Path,
        db_path: Path,
        config: CloseReadAgentConfig,
        progress_callback: Callable[[dict[str, Any]], None] | None = None,
    ) -> None:
        self.repo_root = repo_root
        self.db_path = db_path
        self.config = config
        self.progress_callback = progress_callback

    def run(self, *, min_title_index: int | None = None, max_doc_id: int | None = None) -> CharacterMemoryRepairResult:
        runner = CloseReadRunner(
            repo_root=self.repo_root,
            db_path=self.db_path,
            config=self.config,
            progress_callback=self.progress_callback,
        )
        model_client = self._model_client()
        documents_repo = DocumentsRepo()
        progress_repo = ReadingProgressRepo()
        chapters_repo = ChaptersRepo()
        profiles_repo = CharacterProfilesRepo()
        profile_service = CharacterProfileService(profiles_repo=profiles_repo)
        canonical_name_service = CharacterCanonicalNameService(profiles_repo=profiles_repo)
        roster_service = CharacterRosterService(profiles_repo=profiles_repo)
        db = NovelAgentDB(self.db_path)
        run_id = uuid.uuid4().hex

        with db.connect() as conn:
            db.init_schema(conn)
            effective_max_doc_id = max_doc_id or self._close_read_max_doc_id(conn, progress_repo=progress_repo)
            target_documents = self._target_documents(
                conn,
                documents_repo=documents_repo,
                min_title_index=min_title_index,
                max_doc_id=effective_max_doc_id,
            )
            result = CharacterMemoryRepairResult(
                book_id=self.config.book_id,
                min_title_index=min_title_index,
                max_doc_id=effective_max_doc_id,
                profile_count_before=self._profile_count(conn),
                run_id=run_id,
            )
            if not target_documents:
                result.profile_count_after = result.profile_count_before
                return result

            world_service = WorldStateService(repo_root=self.repo_root, model_client=model_client)
            world_path, world_summary_path = world_service.ensure_paths(self.config.book_id)
            outline_path = OutlineService(repo_root=self.repo_root).ensure_path(self.config.book_id)
            self._ensure_assets(conn, world_path=world_path, world_summary_path=world_summary_path, outline_path=outline_path)

            for batch in self._build_batches(conn, documents_repo=documents_repo, documents=target_documents):
                self._emit(
                    {
                        "stage": "character_memory_repair",
                        "event": "batch_start",
                        "document_title_index": batch.document_title_index,
                        "chapter_title": batch.chapter_title,
                        "doc_count": len(batch.documents),
                        "first_doc_id": batch.documents[0].doc_id,
                        "last_doc_id": batch.documents[-1].doc_id,
                    }
                )
                prepared = runner._prepare_extraction(  # noqa: SLF001
                    conn=conn,
                    batch=batch,
                    outline_path=outline_path,
                    world_summary_path=world_summary_path,
                    profile_service=profile_service,
                    roster_service=roster_service,
                )
                prompt_dict = prepared.prompt_input.to_dict()
                prompt_dict["existing_character_roster"] = prepared.existing_character_roster
                prompt_dict["full_existing_character_roster"] = prepared.full_existing_character_roster
                summary_payload = self._summary_payload(conn, chapters_repo=chapters_repo, batch=batch)
                evidence_payload = self._run_character_evidence(
                    runner=runner,
                    model_client=model_client,
                    batch=batch,
                    prompt_dict=prompt_dict,
                )
                evidence_payload = runner._augment_character_evidence_with_coverage(  # noqa: SLF001
                    model_client=model_client,
                    batch=batch,
                    prompt_input=prompt_dict,
                    summary_payload=summary_payload,
                    evidence_payload=evidence_payload,
                )
                character_reduce_payload = runner._run_character_reduce_agents(  # noqa: SLF001
                    model_client=model_client,
                    batch=batch,
                    prompt_input=prompt_dict,
                    summary_payload=summary_payload,
                    evidence_payload=evidence_payload,
                )
                self._persist_character_memory(
                    conn,
                    runner=runner,
                    batch=batch,
                    summary_payload=summary_payload,
                    evidence_payload=evidence_payload,
                    character_reduce_payload=character_reduce_payload,
                    documents_repo=documents_repo,
                    chapters_repo=chapters_repo,
                    profile_service=profile_service,
                    canonical_name_service=canonical_name_service,
                    model_client=model_client,
                )
                conn.commit()
                result.processed_batches += 1
                result.processed_documents += len(batch.documents)
                result.updated_documents += len(batch.documents)
                self._emit(
                    {
                        "stage": "character_memory_repair",
                        "event": "batch_done",
                        "document_title_index": batch.document_title_index,
                        "doc_count": len(batch.documents),
                        "first_doc_id": batch.documents[0].doc_id,
                        "last_doc_id": batch.documents[-1].doc_id,
                    }
                )

            result.profile_count_after = self._profile_count(conn)
            result.mentioned_characters = self._all_mentioned_characters(conn)
            return result

    def _model_client(self) -> JsonModelClient:
        return JsonModelClient(
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

    def _run_character_evidence(
        self,
        *,
        runner: CloseReadRunner,
        model_client: JsonModelClient,
        batch: ChapterBatch,
        prompt_dict: dict[str, Any],
    ) -> dict[str, Any]:
        max_workers = max(1, int(self.config.runtime.close_read_extraction_max_workers))
        evidence_payloads: list[tuple[int, dict[str, Any]]] = []
        with ThreadPoolExecutor(max_workers=max_workers) as executor:
            futures = []
            for doc in batch.documents:
                doc_batch = runner._as_single_document_batch(batch=batch, doc=doc)  # noqa: SLF001
                futures.append(
                    (
                        int(doc.doc_id),
                        doc_batch,
                        executor.submit(
                            runner._generate_character_evidence_payload,  # noqa: SLF001
                            model_client=model_client,
                            batch=doc_batch,
                            prompt_input=prompt_dict,
                        ),
                    )
                )
            for doc_id, doc_batch, future in futures:
                evidence_payloads.append(
                    (
                        doc_id,
                        runner._result_or_retry(future, batch=doc_batch),  # noqa: SLF001
                    )
                )
        return runner._combine_character_evidence_payloads(  # noqa: SLF001
            batch=batch,
            evidence_payloads=evidence_payloads,
        )

    def _persist_character_memory(
        self,
        conn,
        *,
        runner: CloseReadRunner,
        batch: ChapterBatch,
        summary_payload: dict[str, Any],
        evidence_payload: dict[str, Any],
        character_reduce_payload: dict[str, Any],
        documents_repo: DocumentsRepo,
        chapters_repo: ChaptersRepo,
        profile_service: CharacterProfileService,
        canonical_name_service: CharacterCanonicalNameService,
        model_client: JsonModelClient,
    ) -> None:
        document_mentions = runner._normalize_document_character_mentions(  # noqa: SLF001
            batch=batch,
            payload={
                "document_character_mentions": runner._document_mentions_from_character_evidence(  # noqa: SLF001
                    batch=batch,
                    evidence_payload=evidence_payload,
                )
            },
        )
        speaking_mentions = runner._normalize_document_speaking_mentions(  # noqa: SLF001
            batch=batch,
            payload={
                "document_character_mentions": runner._document_mentions_from_character_evidence(  # noqa: SLF001
                    batch=batch,
                    evidence_payload=evidence_payload,
                )
            },
        )
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
        existing = chapters_repo.get(conn, book_id=self.config.book_id, document_title_index=batch.document_title_index)
        existing_mentions = _load_json_list(existing["mentioned_characters_json"]) if existing else []
        merged_mentions = sorted({*existing_mentions, *mentioned_characters})
        conn.execute(
            """
            UPDATE chapters
            SET mentioned_characters_json = ?, updated_at = ?
            WHERE book_id = ? AND document_title_index = ?
            """,
            (
                json.dumps(merged_mentions, ensure_ascii=False),
                _utc_now(),
                self.config.book_id,
                batch.document_title_index,
            ),
        )

        raw_character_updates = [item for item in character_reduce_payload.get("character_updates", []) if isinstance(item, dict)]
        if not raw_character_updates:
            raw_character_updates = [
                {
                    "canonical_name": name,
                    "aliases": [],
                    "personality": [],
                    "occupations": [],
                    "recent_activity": summary_payload.get("chapter_summary_short", ""),
                    "relationships": [],
                }
                for name in mentioned_characters
            ]
        raw_character_updates = canonical_name_service.resolve_updates(
            conn,
            book_id=self.config.book_id,
            model_client=model_client,
            updates=raw_character_updates,
        )
        profile_service.merge_updates(
            conn,
            book_id=self.config.book_id,
            chapter_index=batch.document_title_index,
            doc_ids=[doc.doc_id for doc in batch.documents],
            updates=raw_character_updates,
            mentioned_doc_ids_by_name=runner._invert_mentions(document_mentions),  # noqa: SLF001
            speaking_doc_ids_by_name=runner._invert_mentions(speaking_mentions),  # noqa: SLF001
        )

    def _summary_payload(self, conn, *, chapters_repo: ChaptersRepo, batch: ChapterBatch) -> dict[str, Any]:
        row = chapters_repo.get(conn, book_id=self.config.book_id, document_title_index=batch.document_title_index)
        if row is None:
            return {
                "chapter_summary_md": "",
                "chapter_summary_short": "",
                "importance_score": 0,
                "importance_reason": "",
                "related_chapters": [],
            }
        intermediate = _load_json_list(row["summary_intermediate_json"])
        summary_md = str(row["summary_md"] or "").strip() or "\n\n".join(intermediate)
        return {
            "summary_quality": "existing_summary_reuse",
            "chapter_summary_md": summary_md,
            "chapter_summary_short": str(row["summary_short"] or "").strip(),
            "importance_score": int(row["importance_score"] or 0),
            "importance_reason": str(row["importance_reason"] or "").strip(),
            "related_chapters": _load_json_list(row["related_chapters_json"]),
            "world_signal_score": 0,
            "world_evidence_candidates": [],
        }

    def _build_batches(self, conn, *, documents_repo: DocumentsRepo, documents: list[DocumentRow]) -> list[ChapterBatch]:
        batches: list[ChapterBatch] = []
        by_title: dict[int, list[DocumentRow]] = {}
        for doc in documents:
            by_title.setdefault(int(doc.document_title_index), []).append(doc)
        for title_index in sorted(by_title):
            selected_docs = sorted(by_title[title_index], key=lambda doc: doc.doc_id)
            all_chapter_docs = documents_repo.fetch_by_title_index(
                conn,
                book_id=self.config.book_id,
                document_title_index=title_index,
            )
            all_doc_ids = [int(doc.doc_id) for doc in all_chapter_docs]
            chapter_total_chars = sum(doc.content_chars for doc in all_chapter_docs)
            cursor = 0
            while cursor < len(selected_docs):
                current: list[DocumentRow] = []
                current_chars = 0
                first_doc_id = int(selected_docs[cursor].doc_id)
                while cursor < len(selected_docs):
                    doc = selected_docs[cursor]
                    if current and current_chars + doc.content_chars > self.config.runtime.document_chars_budget:
                        break
                    current.append(doc)
                    current_chars += doc.content_chars
                    cursor += 1
                start_index = all_doc_ids.index(first_doc_id) + 1 if first_doc_id in all_doc_ids else 1
                selected_ids = [int(doc.doc_id) for doc in current]
                is_complete_chapter = selected_ids == all_doc_ids
                batches.append(
                    ChapterBatch(
                        document_title_index=title_index,
                        chapter_title=current[0].document_title,
                        documents=current,
                        is_complete_chapter=is_complete_chapter,
                        chapter_doc_count=len(all_chapter_docs),
                        chapter_total_chars=chapter_total_chars,
                        batch_doc_start_index=start_index,
                        split_reason=SPLIT_REASON_FULL_CHAPTER if is_complete_chapter else SPLIT_REASON_OVER_BUDGET,
                    )
                )
        return batches

    def _target_documents(
        self,
        conn,
        *,
        documents_repo: DocumentsRepo,
        min_title_index: int | None,
        max_doc_id: int | None,
    ) -> list[DocumentRow]:
        documents = documents_repo.fetch_after_doc_id(conn, book_id=self.config.book_id, doc_id=None)
        if min_title_index is not None:
            documents = [
                doc
                for doc in documents
                if int(doc.document_title_index) >= int(min_title_index)
            ]
        if max_doc_id is None:
            return documents
        return [doc for doc in documents if int(doc.doc_id) <= int(max_doc_id)]

    def _close_read_max_doc_id(self, conn, *, progress_repo: ReadingProgressRepo) -> int | None:
        progress = progress_repo.get(conn, book_id=self.config.book_id, agent_stage=DEFAULT_CLOSE_READING_STAGE)
        if progress is None:
            return None
        last_completed = progress["last_completed_doc_id"]
        return int(last_completed) if last_completed is not None else None

    def _ensure_assets(self, conn, *, world_path: Path, world_summary_path: Path, outline_path: Path) -> None:
        assets = AssetsRepo().get(conn, book_id=self.config.book_id)
        if assets is not None:
            return
        debug_path = self.repo_root / ".memory" / "debug" / f"{self.config.book_id}.sqlite.md"
        AssetsRepo().upsert(
            conn,
            {
                "book_id": self.config.book_id,
                "source_root": "",
                "world_markdown_path": world_path.as_posix(),
                "world_summary_path": world_summary_path.as_posix(),
                "outline_markdown_path": outline_path.as_posix(),
                "debug_export_path": debug_path.as_posix(),
                "created_at": _utc_now(),
                "updated_at": _utc_now(),
            },
        )

    def _profile_count(self, conn) -> int:
        row = conn.execute("SELECT COUNT(*) FROM character_profiles WHERE book_id = ?", (self.config.book_id,)).fetchone()
        return int(row[0] or 0) if row is not None else 0

    def _all_mentioned_characters(self, conn) -> list[str]:
        names: set[str] = set()
        for row in conn.execute(
            "SELECT mentioned_characters_json FROM chapters WHERE book_id = ?",
            (self.config.book_id,),
        ).fetchall():
            names.update(str(name).strip() for name in _load_json_list(row["mentioned_characters_json"]) if str(name).strip())
        return sorted(names)

    def _emit(self, event: dict[str, Any]) -> None:
        if self.progress_callback is not None:
            self.progress_callback(event)


def _load_json_list(raw: object) -> list[Any]:
    if isinstance(raw, list):
        return raw
    if raw in (None, ""):
        return []
    try:
        value = json.loads(str(raw))
    except json.JSONDecodeError:
        return []
    return value if isinstance(value, list) else []


def _utc_now() -> str:
    from datetime import datetime, timezone

    return datetime.now(timezone.utc).isoformat()

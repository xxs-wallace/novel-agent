from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace
import uuid

from ..repos.assets_repo import AssetsRepo
from ..repos.chapters_repo import ChaptersRepo
from ..repos.character_profiles_repo import CharacterProfilesRepo
from ..repos.creative_kb_storage import init_creative_kb_schema
from ..repos.db import NovelAgentDB
from ..repos.documents_repo import DocumentRow, DocumentsRepo
from ..repos.fragment_cards_repo import FragmentCardsRepo
from ..schemas.smoke_schema import PrefixRuntimeSnapshot, SmokeSampleConfig
from .creative_kb_facade import CreativeKnowledgeBaseFacade
from .fragment_card_builder_service import FragmentCardBuilderService


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


@dataclass(slots=True)
class _CopyDocumentsResult:
    documents: list[DocumentRow]
    doc_id_map: dict[int, int]


class _DeterministicFragmentCardModelClient:
    def __init__(self) -> None:
        self.settings = SimpleNamespace(dry_run=True)

    def generate_json(self, **kwargs: object) -> tuple[dict[str, object], str]:
        fallback_factory = kwargs.get("fallback_factory")
        if not callable(fallback_factory):
            raise RuntimeError("fallback_factory is required for deterministic fragment card build")
        payload = fallback_factory()
        if not isinstance(payload, dict):
            raise RuntimeError("fallback fragment card payload must be a JSON object")
        return payload, "{}"


class SmokePrefixSnapshotService:
    def __init__(
        self,
        *,
        documents_repo: DocumentsRepo | None = None,
        chapters_repo: ChaptersRepo | None = None,
        character_profiles_repo: CharacterProfilesRepo | None = None,
        assets_repo: AssetsRepo | None = None,
        creative_kb_facade: CreativeKnowledgeBaseFacade | None = None,
    ) -> None:
        self.documents_repo = documents_repo or DocumentsRepo()
        self.chapters_repo = chapters_repo or ChaptersRepo()
        self.character_profiles_repo = character_profiles_repo or CharacterProfilesRepo()
        self.assets_repo = assets_repo or AssetsRepo()
        self.creative_kb_facade = creative_kb_facade or self._build_default_creative_kb_facade()

    def build(
        self,
        *,
        source_db_path: str | Path,
        sample: SmokeSampleConfig,
        output_root: str | Path,
    ) -> PrefixRuntimeSnapshot:
        source_db = NovelAgentDB(Path(source_db_path).expanduser().resolve())
        snapshot_root = self._prepare_snapshot_root(output_root=Path(output_root), sample_id=sample.sample_id)
        assets_root = snapshot_root / "assets"
        db_path = snapshot_root / "novel.db"
        warnings: list[str] = []

        target_db = NovelAgentDB(db_path)
        with source_db.connect() as source_conn, target_db.connect() as target_conn:
            target_db.init_schema(target_conn)
            init_creative_kb_schema(target_conn)

            copied_documents = self._copy_documents(
                source_conn=source_conn,
                target_conn=target_conn,
                book_id=sample.book_id,
                max_document_title_index=sample.documents_cutoff.max_title_index_int,
            )
            copied_chapter_count, chapter_warnings = self._copy_chapters(
                source_conn=source_conn,
                target_conn=target_conn,
                book_id=sample.book_id,
                max_document_title_index=sample.documents_cutoff.max_title_index_int,
                doc_id_map=copied_documents.doc_id_map,
            )
            warnings.extend(chapter_warnings)
            copied_profile_count, profile_warnings = self._copy_character_profiles(
                source_conn=source_conn,
                target_conn=target_conn,
                book_id=sample.book_id,
                max_document_title_index=sample.documents_cutoff.max_title_index_int,
                doc_id_map=copied_documents.doc_id_map,
            )
            warnings.extend(profile_warnings)
            asset_paths, asset_warnings = self._copy_assets(
                source_conn=source_conn,
                target_conn=target_conn,
                sample=sample,
                snapshot_root=snapshot_root,
                assets_root=assets_root,
            )
            warnings.extend(asset_warnings)

            if copied_documents.documents:
                build_result = self.creative_kb_facade.build_creative_kb(
                    target_conn,
                    documents=copied_documents.documents,
                )
                warnings.extend(build_result.warnings)

            target_conn.commit()

        return PrefixRuntimeSnapshot(
            sample_id=sample.sample_id,
            snapshot_root=str(snapshot_root),
            db_path=str(db_path),
            assets_root=str(assets_root),
            max_document_title_index=sample.documents_cutoff.max_document_title_index,
            copied_doc_count=len(copied_documents.documents),
            copied_chapter_count=copied_chapter_count,
            copied_character_profile_count=copied_profile_count,
            asset_paths=asset_paths,
            warnings=warnings,
        )

    def _prepare_snapshot_root(self, *, output_root: Path, sample_id: str) -> Path:
        root = output_root.expanduser().resolve() / sample_id / f"prefix_runtime_{uuid.uuid4().hex[:8]}"
        root.mkdir(parents=True, exist_ok=False)
        return root

    def _copy_documents(
        self,
        *,
        source_conn,
        target_conn,
        book_id: str,
        max_document_title_index: int,
    ) -> _CopyDocumentsResult:
        copied_documents: list[DocumentRow] = []
        doc_id_map: dict[int, int] = {}
        for title_index in self.documents_repo.list_title_indexes(source_conn, book_id=book_id):
            if title_index > max_document_title_index:
                continue
            rows = self.documents_repo.fetch_by_title_index(
                source_conn,
                book_id=book_id,
                document_title_index=title_index,
            )
            for row in rows:
                new_doc_id = self.documents_repo.insert_document(
                    target_conn,
                    {
                        "path": row.path,
                        "scope": row.scope,
                        "title": row.title,
                        "content": row.content,
                        "book_id": row.book_id,
                        "source_path": row.source_path,
                        "source_file_name": row.source_file_name,
                        "source_start_offset": row.source_start_offset,
                        "source_end_offset": row.source_end_offset,
                        "document_title": row.document_title,
                        "document_title_index": row.document_title_index,
                        "inferred_chapter_no": row.inferred_chapter_no,
                        "content_chars": row.content_chars,
                        "character_keywords": list(row.character_keywords),
                        "content_tags": list(row.content_tags),
                        "created_at": _utc_now(),
                        "updated_at": _utc_now(),
                    },
                )
                doc_id_map[row.doc_id] = new_doc_id
                copied_documents.append(
                    DocumentRow(
                        doc_id=new_doc_id,
                        book_id=row.book_id,
                        path=row.path,
                        scope=row.scope,
                        title=row.title,
                        document_title=row.document_title,
                        document_title_index=row.document_title_index,
                        inferred_chapter_no=row.inferred_chapter_no,
                        content=row.content,
                        content_chars=row.content_chars,
                        character_keywords=list(row.character_keywords),
                        content_tags=list(row.content_tags),
                        source_path=row.source_path,
                        source_file_name=row.source_file_name,
                        source_start_offset=row.source_start_offset,
                        source_end_offset=row.source_end_offset,
                    )
                )
        return _CopyDocumentsResult(documents=copied_documents, doc_id_map=doc_id_map)

    def _copy_chapters(
        self,
        *,
        source_conn,
        target_conn,
        book_id: str,
        max_document_title_index: int,
        doc_id_map: dict[int, int],
    ) -> tuple[int, list[str]]:
        copied = 0
        warnings: list[str] = []
        for row in self.chapters_repo.list_by_book(source_conn, book_id=book_id):
            title_index = int(row["document_title_index"])
            if title_index > max_document_title_index:
                continue
            source_doc_start_id = doc_id_map.get(int(row["source_doc_start_id"]))
            source_doc_end_id = doc_id_map.get(int(row["source_doc_end_id"]))
            if source_doc_start_id is None or source_doc_end_id is None:
                warnings.append(f"chapter.missing_doc_mapping:{title_index}")
                continue
            related_chapters = [
                item
                for item in json.loads(row["related_chapters_json"] or "[]")
                if int(item.get("document_title_index") or 0) <= max_document_title_index
            ]
            self.chapters_repo.upsert(
                target_conn,
                {
                    "book_id": str(row["book_id"]),
                    "document_title_index": title_index,
                    "chapter_title": str(row["chapter_title"]),
                    "source_doc_start_id": source_doc_start_id,
                    "source_doc_end_id": source_doc_end_id,
                    "source_doc_count": int(row["source_doc_count"]),
                    "source_total_chars": int(row["source_total_chars"]),
                    "summary_intermediate": list(json.loads(row["summary_intermediate_json"] or "[]")),
                    "summary_md": str(row["summary_md"] or ""),
                    "summary_short": str(row["summary_short"] or ""),
                    "summary_status": _row_text(row, "summary_status", "provisional"),
                    "summary_evidence_window": _row_text(row, "summary_evidence_window"),
                    "summary_target_range": _row_text(row, "summary_target_range"),
                    "importance_score": int(row["importance_score"] or 0),
                    "importance_reason": row["importance_reason"],
                    "related_chapters": related_chapters,
                    "mentioned_characters": list(json.loads(row["mentioned_characters_json"] or "[]")),
                    "world_update": json.loads(row["world_update_json"] or "{}"),
                    "outline_update": json.loads(row["outline_update_json"] or "{}"),
                    "outline_status": _row_text(row, "outline_status", "provisional"),
                    "outline_evidence_window": _row_text(row, "outline_evidence_window"),
                    "outline_target_range": _row_text(row, "outline_target_range"),
                    "close_read_run_id": str(row["close_read_run_id"] or ""),
                    "created_at": str(row["created_at"] or _utc_now()),
                    "updated_at": str(row["updated_at"] or _utc_now()),
                },
            )
            copied += 1
        return copied, warnings

    def _copy_character_profiles(
        self,
        *,
        source_conn,
        target_conn,
        book_id: str,
        max_document_title_index: int,
        doc_id_map: dict[int, int],
    ) -> tuple[int, list[str]]:
        copied = 0
        warnings: list[str] = []
        for row in self.character_profiles_repo.list_by_book(source_conn, book_id=book_id):
            first_seen_title_index = row["first_seen_title_index"]
            if first_seen_title_index is not None and int(first_seen_title_index) > max_document_title_index:
                continue
            chapter_indexes = [
                int(item)
                for item in json.loads(row["chapter_indexes_json"] or "[]")
                if int(item) <= max_document_title_index
            ]
            if not chapter_indexes and first_seen_title_index is not None:
                continue
            last_seen_title_index = row["last_seen_title_index"]
            if last_seen_title_index is not None and int(last_seen_title_index) > max_document_title_index:
                warnings.append(
                    f"character_profile.may_include_future_updates:{str(row['canonical_name'])}"
                )
            first_seen_doc_id = (
                doc_id_map.get(int(row["first_seen_doc_id"]))
                if row["first_seen_doc_id"] is not None
                else None
            )
            last_seen_doc_id = (
                doc_id_map.get(int(row["last_seen_doc_id"]))
                if row["last_seen_doc_id"] is not None
                else None
            )
            effective_first_seen_title_index = (
                int(first_seen_title_index)
                if first_seen_title_index is not None
                else (min(chapter_indexes) if chapter_indexes else None)
            )
            effective_last_seen_title_index = (
                min(int(last_seen_title_index), max_document_title_index)
                if last_seen_title_index is not None
                else (max(chapter_indexes) if chapter_indexes else None)
            )
            self.character_profiles_repo.upsert(
                target_conn,
                {
                    "book_id": str(row["book_id"]),
                    "canonical_name": str(row["canonical_name"]),
                    "aliases": list(json.loads(row["aliases_json"] or "[]")),
                    "profile_summary_md": str(row["profile_summary_md"] or ""),
                    "personality": list(json.loads(row["personality_json"] or "[]")),
                    "occupations": list(json.loads(row["occupations_json"] or "[]")),
                    "age_timeline": list(json.loads(row["age_timeline_json"] or "[]")),
                    "abilities": list(json.loads(row["abilities_json"] or "[]")),
                    "recent_activity": list(json.loads(row["recent_activity_json"] or "[]")),
                    "relationships": list(json.loads(row["relationships_json"] or "[]")),
                    "chapter_indexes": chapter_indexes,
                    "first_seen_doc_id": first_seen_doc_id,
                    "last_seen_doc_id": last_seen_doc_id,
                    "first_seen_title_index": effective_first_seen_title_index,
                    "last_seen_title_index": effective_last_seen_title_index,
                    "importance_score": int(row["importance_score"] or 0),
                    "profile_version": int(row["profile_version"] or 1),
                    "created_at": str(row["created_at"] or _utc_now()),
                    "updated_at": str(row["updated_at"] or _utc_now()),
                },
            )
            copied += 1
        return copied, warnings

    def _copy_assets(
        self,
        *,
        source_conn,
        target_conn,
        sample: SmokeSampleConfig,
        snapshot_root: Path,
        assets_root: Path,
    ) -> tuple[dict[str, str], list[str]]:
        warnings: list[str] = []
        asset_paths: dict[str, str] = {}
        assets_root.mkdir(parents=True, exist_ok=True)
        asset_row = self.assets_repo.get(source_conn, book_id=sample.book_id)
        world_markdown_path = assets_root / "world.md"
        world_summary_path = assets_root / "world_summary.md"
        outline_markdown_path = assets_root / "outline.md"

        if asset_row is None:
            world_markdown_path.write_text("", encoding="utf-8")
            world_summary_path.write_text("", encoding="utf-8")
            outline_markdown_path.write_text("", encoding="utf-8")
            warnings.append("book_assets.missing")
        else:
            source_root = Path(str(asset_row["source_root"] or "")).expanduser()
            self._copy_text_asset(
                raw_path=str(asset_row["world_markdown_path"] or ""),
                default_path=world_markdown_path,
                source_root=source_root,
            )
            self._copy_text_asset(
                raw_path=str(asset_row["world_summary_path"] or ""),
                default_path=world_summary_path,
                source_root=source_root,
            )
            outline_text, outline_warnings = self._resolve_outline_text(
                raw_path=str(asset_row["outline_markdown_path"] or ""),
                source_root=source_root,
                sample=sample,
            )
            warnings.extend(outline_warnings)
            outline_markdown_path.write_text(outline_text, encoding="utf-8")

        self.assets_repo.upsert(
            target_conn,
            {
                "book_id": sample.book_id,
                "source_root": str(snapshot_root),
                "world_markdown_path": str(world_markdown_path),
                "world_summary_path": str(world_summary_path),
                "outline_markdown_path": str(outline_markdown_path),
                "toc_markdown": "",
                "toc_source_path": "",
                "debug_export_path": str(snapshot_root / "debug_export.md"),
                "created_at": _utc_now(),
                "updated_at": _utc_now(),
            },
        )
        asset_paths["world_markdown_path"] = str(world_markdown_path)
        asset_paths["world_summary_path"] = str(world_summary_path)
        asset_paths["outline_markdown_path"] = str(outline_markdown_path)
        return asset_paths, warnings

    def _copy_text_asset(
        self,
        *,
        raw_path: str,
        default_path: Path,
        source_root: Path,
    ) -> None:
        resolved_source = self._resolve_asset_path(raw_path=raw_path, source_root=source_root)
        text = resolved_source.read_text(encoding="utf-8") if resolved_source is not None else ""
        default_path.write_text(text, encoding="utf-8")

    def _resolve_outline_text(
        self,
        *,
        raw_path: str,
        source_root: Path,
        sample: SmokeSampleConfig,
    ) -> tuple[str, list[str]]:
        warnings: list[str] = []
        resolved_source = self._resolve_asset_path(raw_path=raw_path, source_root=source_root)
        if resolved_source is None:
            warnings.append("book_assets.outline_missing")
            return "", warnings
        full_text = resolved_source.read_text(encoding="utf-8")
        if sample.allowed_outline_scope.allow_future_outline:
            return full_text, warnings
        filtered_text = self._filter_outline_text(
            full_text,
            allowed_chapter_tokens=sample.allowed_outline_scope.chapter_range,
        )
        if sample.allowed_outline_scope.chapter_range and not filtered_text.strip():
            warnings.append("book_assets.outline_scope_empty_after_filter")
        if not sample.allowed_outline_scope.chapter_range:
            warnings.append("book_assets.outline_withheld_without_scope")
        return filtered_text, warnings

    def _resolve_asset_path(self, *, raw_path: str, source_root: Path) -> Path | None:
        text = str(raw_path).strip()
        if not text:
            return None
        path = Path(text).expanduser()
        if path.is_absolute():
            return path if path.exists() else None
        candidate = (source_root / path).resolve()
        return candidate if candidate.exists() else None

    def _filter_outline_text(self, text: str, *, allowed_chapter_tokens: list[str]) -> str:
        if not text.strip() or not allowed_chapter_tokens:
            return ""
        lowered_tokens = [token.lower() for token in allowed_chapter_tokens if token.strip()]
        lines = text.splitlines()
        if not lines:
            return ""

        filtered_sections: list[str] = []
        current_section: list[str] = []
        current_matches = False
        saw_heading = False

        for line in lines:
            stripped = line.strip()
            is_heading = stripped.startswith("#")
            if is_heading:
                saw_heading = True
                if current_section and current_matches:
                    filtered_sections.append("\n".join(current_section).strip())
                current_section = [line]
                current_matches = any(token in stripped.lower() for token in lowered_tokens)
                continue
            if not saw_heading:
                continue
            current_section.append(line)
            if any(token in stripped.lower() for token in lowered_tokens):
                current_matches = True

        if current_section and current_matches:
            filtered_sections.append("\n".join(current_section).strip())

        if filtered_sections:
            return "\n\n".join(section for section in filtered_sections if section).strip()

        matched_lines = [
            line
            for line in lines
            if any(token in line.strip().lower() for token in lowered_tokens)
        ]
        return "\n".join(matched_lines).strip()

    def _build_default_creative_kb_facade(self) -> CreativeKnowledgeBaseFacade:
        fragment_cards_repo = FragmentCardsRepo()
        builder = FragmentCardBuilderService(
            model_client=_DeterministicFragmentCardModelClient(),  # type: ignore[arg-type]
            fragment_cards_repo=fragment_cards_repo,
        )
        return CreativeKnowledgeBaseFacade(
            fragment_card_builder_service=builder,
            fragment_cards_repo=fragment_cards_repo,
        )


def _row_text(row, column: str, default: str = "") -> str:
    try:
        value = row[column]
    except (IndexError, KeyError):
        return default
    return str(value or default).strip()

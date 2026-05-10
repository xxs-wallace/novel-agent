from __future__ import annotations

import json
import sqlite3
from pathlib import Path

from ..repos.assets_repo import AssetsRepo
from ..repos.chapters_repo import ChaptersRepo
from ..repos.character_profiles_repo import CharacterProfilesRepo
from ..schemas.context_assembly_schema import (
    ChapterContextItem,
    CharacterProfileContextItem,
    ContextAssemblyPayload,
    SourceArcContextItem,
)
from ..schemas.orchestration_schema import MemoryAssemblyInput
from .context_budget_helper import fit_text_with_budget
from .context_selectors import (
    chapter_summary_text,
    infer_character_names,
    rank_chapter_rows,
    rank_character_rows,
)
from .memory_asset_adapter import MemoryAssetAdapter
from .outline_service import OutlineService
from .source_arc_mapping_service import SourceArcMappingService, select_source_arc_context
from .world_state_service import WorldStateService


class ContextAssemblyService:
    def __init__(
        self,
        *,
        chapters_repo: ChaptersRepo,
        character_profiles_repo: CharacterProfilesRepo,
        assets_repo: AssetsRepo,
        memory_asset_adapter: MemoryAssetAdapter,
        repo_root: Path | None = None,
    ) -> None:
        self.chapters_repo = chapters_repo
        self.character_profiles_repo = character_profiles_repo
        self.assets_repo = assets_repo
        self.memory_asset_adapter = memory_asset_adapter
        self.repo_root = repo_root

    @classmethod
    def build_default(cls, *, repo_root: Path) -> "ContextAssemblyService":
        world_state_service = WorldStateService(repo_root=repo_root)
        outline_service = OutlineService(repo_root=repo_root)
        assets_repo = AssetsRepo()
        return cls(
            chapters_repo=ChaptersRepo(),
            character_profiles_repo=CharacterProfilesRepo(),
            assets_repo=assets_repo,
            memory_asset_adapter=MemoryAssetAdapter(
                assets_repo=assets_repo,
                world_state_service=world_state_service,
                outline_service=outline_service,
            ),
            repo_root=repo_root,
        )

    def assemble(
        self,
        conn: sqlite3.Connection,
        *,
        assembly_input: MemoryAssemblyInput,
    ) -> ContextAssemblyPayload:
        missing_context: list[str] = []

        chapter_context, selected_chapter_rows, chapter_missing = self._assemble_chapter_context(
            conn,
            assembly_input=assembly_input,
        )
        missing_context.extend(chapter_missing)

        source_arc_context = self._assemble_source_arc_context(assembly_input=assembly_input)

        world_summary_md, story_outline_md, story_outline_status, asset_missing = self._assemble_book_assets(
            conn,
            assembly_input=assembly_input,
        )
        missing_context.extend(asset_missing)

        character_profiles, character_missing = self._assemble_character_profiles(
            conn,
            assembly_input=assembly_input,
            chapter_rows=selected_chapter_rows,
        )
        missing_context.extend(character_missing)

        return ContextAssemblyPayload(
            chapter_context=chapter_context,
            source_arc_context=source_arc_context,
            world_summary_md=world_summary_md,
            character_profiles=character_profiles,
            story_outline_md=story_outline_md,
            memory_status={
                "chapter_context": self._combined_status([item.summary_status for item in chapter_context]),
                "story_outline": story_outline_status,
                "source_arc_context": self._combined_status([item.status for item in source_arc_context]),
            },
            missing_context=self._dedupe(missing_context),
        )

    def assemble_to_dict(
        self,
        conn: sqlite3.Connection,
        *,
        assembly_input: MemoryAssemblyInput,
    ) -> dict[str, object]:
        return self.assemble(conn, assembly_input=assembly_input).to_dict()

    def _assemble_chapter_context(
        self,
        conn: sqlite3.Connection,
        *,
        assembly_input: MemoryAssemblyInput,
    ) -> tuple[list[ChapterContextItem], list[sqlite3.Row], list[str]]:
        rows = self.chapters_repo.list_by_book(conn, book_id=assembly_input.book_id)
        ranked_rows = rank_chapter_rows(
            rows,
            current_title_index=assembly_input.document_title_index,
        )
        missing_context: list[str] = []
        if not ranked_rows:
            missing_context.append("chapter_context.empty")
            return [], [], missing_context

        remaining_chars = assembly_input.token_budget.chapter_context_chars
        selected_items: list[ChapterContextItem] = []
        selected_rows: list[sqlite3.Row] = []
        for row in ranked_rows:
            summary_md = chapter_summary_text(row)
            summary_fit = fit_text_with_budget(text=summary_md, remaining_chars=remaining_chars)
            if summary_fit.omitted:
                break
            item = ChapterContextItem(
                document_title_index=str(row["document_title_index"]),
                chapter_title=str(row["chapter_title"]),
                summary_md=summary_fit.text,
                importance_score=int(row["importance_score"] or 0),
                summary_status=self._row_status(row, "summary_status"),
                summary_evidence_window=self._row_text(row, "summary_evidence_window"),
                summary_target_range=self._row_text(row, "summary_target_range"),
                structure_status=self._row_status(row, "summary_status"),
            )
            selected_items.append(item)
            selected_rows.append(row)
            remaining_chars -= summary_fit.used_chars
            if summary_fit.truncated:
                missing_context.append("chapter_context.truncated")
                break

        if not selected_items:
            missing_context.append("chapter_context.over_budget")

        if (
            assembly_input.document_title_index is not None
            and not any(
                str(row["document_title_index"]) == assembly_input.document_title_index
                for row in selected_rows
            )
        ):
            missing_context.append("chapter_context.current_chapter_unavailable")

        return selected_items, selected_rows, missing_context

    def _assemble_source_arc_context(
        self,
        *,
        assembly_input: MemoryAssemblyInput,
    ) -> list[SourceArcContextItem]:
        if self.repo_root is None or assembly_input.token_budget.source_arc_context_chars <= 0:
            return []
        service = SourceArcMappingService(repo_root=self.repo_root)
        payload = service.load_exported(book_id=assembly_input.book_id)
        if not payload:
            return []
        try:
            current_index = (
                int(assembly_input.document_title_index)
                if assembly_input.document_title_index is not None
                else None
            )
        except ValueError:
            current_index = None
        selected = select_source_arc_context(
            payload,
            document_title_index=current_index,
            max_chars=assembly_input.token_budget.source_arc_context_chars,
        )
        return [
            SourceArcContextItem(
                source_arc_id=str(item.get("source_arc_id") or ""),
                source_arc_title=str(item.get("source_arc_title") or ""),
                start_document_title_index=int(item.get("start_document_title_index") or 0),
                end_document_title_index=int(item.get("end_document_title_index") or 0),
                source_arc_role=str(item.get("source_arc_role") or ""),
                status=str(item.get("status") or "committed"),
                evidence_window=str(item.get("evidence_window") or ""),
                target_range=str(item.get("target_range") or ""),
                core_events=[str(event) for event in item.get("core_events", []) if str(event).strip()],
                transition_from_previous=str(item.get("transition_from_previous") or ""),
                setup_for_next=str(item.get("setup_for_next") or ""),
                pacing_notes=str(item.get("pacing_notes") or ""),
            )
            for item in selected
        ]

    def _assemble_book_assets(
        self,
        conn: sqlite3.Connection,
        *,
        assembly_input: MemoryAssemblyInput,
    ) -> tuple[str, str, str, list[str]]:
        resolved_assets = self.memory_asset_adapter.resolve(conn, book_id=assembly_input.book_id)
        missing_context = list(resolved_assets.missing_context)

        world_summary_fit = self._read_clamped_text(
            resolved_assets.world_summary_path,
            max_chars=assembly_input.token_budget.world_summary_chars,
        )
        story_outline_md, story_outline_status, story_outline_truncated = self._assemble_story_outline(
            conn,
            book_id=assembly_input.book_id,
            fallback_path=resolved_assets.story_outline_path,
            max_chars=assembly_input.token_budget.story_outline_chars,
        )
        world_summary_md = world_summary_fit.text

        if not world_summary_md.strip():
            missing_context.append("world_summary_md.empty")
        elif world_summary_fit.truncated:
            missing_context.append("world_summary_md.truncated")

        if not story_outline_md.strip():
            missing_context.append("story_outline_md.empty")
        elif story_outline_truncated:
            missing_context.append("story_outline_md.truncated")

        return world_summary_md, story_outline_md, story_outline_status, missing_context

    def _assemble_story_outline(
        self,
        conn: sqlite3.Connection,
        *,
        book_id: str,
        fallback_path: Path,
        max_chars: int,
    ) -> tuple[str, str, bool]:
        if max_chars <= 0:
            return "", "provisional", False
        rows = self.chapters_repo.list_by_book(conn, book_id=book_id)
        outline_rows: list[tuple[str, str]] = []
        for row in rows:
            outline_update = self._load_json_dict(row["outline_update_json"])
            chapter_line = str(outline_update.get("chapter_line") or "").strip()
            if not chapter_line:
                continue
            status = self._row_status(row, "outline_status")
            evidence_window = self._row_text(row, "outline_evidence_window")
            target_range = self._row_text(row, "outline_target_range")
            metadata = f"status={status}"
            if evidence_window:
                metadata += f"; evidence_window={evidence_window}"
            if target_range:
                metadata += f"; target_range={target_range}"
            outline_rows.append((f"- {chapter_line} ({metadata})", status))
        if outline_rows:
            statuses = [status for _, status in outline_rows]
            markdown = "# 故事大纲\n\n## 分章节进度\n" + "\n".join(line for line, _ in outline_rows)
            fit = fit_text_with_budget(text=markdown, remaining_chars=max_chars)
            return fit.text, self._combined_status(statuses), fit.truncated
        fit = self._read_clamped_text(fallback_path, max_chars=max_chars)
        return fit.text, "provisional" if fit.text.strip() else "provisional", fit.truncated

    def _assemble_character_profiles(
        self,
        conn: sqlite3.Connection,
        *,
        assembly_input: MemoryAssemblyInput,
        chapter_rows: list[sqlite3.Row],
    ) -> tuple[list[CharacterProfileContextItem], list[str]]:
        missing_context: list[str] = []
        candidate_names = infer_character_names(
            chapter_rows,
            prioritized_names=assembly_input.related_character_names,
        )
        if not candidate_names:
            missing_context.append("character_profiles.no_candidates")
            return [], missing_context

        all_rows = self.character_profiles_repo.list_by_book(conn, book_id=assembly_input.book_id)
        candidate_set = set(candidate_names)
        matching_rows = [
            row for row in all_rows if str(row["canonical_name"]).strip() in candidate_set
        ]
        if not matching_rows:
            missing_context.append("character_profiles.none_found")
            return [], missing_context

        ranked_rows = rank_character_rows(
            matching_rows,
            prioritized_names=assembly_input.related_character_names,
        )
        remaining_chars = assembly_input.token_budget.character_profiles_chars
        selected_items: list[CharacterProfileContextItem] = []
        found_names = {str(row["canonical_name"]).strip() for row in matching_rows}
        requested_names = {
            str(name).strip()
            for name in assembly_input.related_character_names
            if str(name).strip()
        }

        for row in ranked_rows:
            profile_summary_md = str(row["profile_summary_md"] or "").strip()
            if not profile_summary_md:
                continue
            summary_fit = fit_text_with_budget(
                text=profile_summary_md,
                remaining_chars=remaining_chars,
            )
            if summary_fit.omitted:
                break
            selected_items.append(
                CharacterProfileContextItem(
                    canonical_name=str(row["canonical_name"]),
                    profile_summary_md=summary_fit.text,
                    aliases=self._load_json_list(row["aliases_json"]),
                    importance_score=int(row["importance_score"] or 0),
                    speaking_character_status=str(row["speaking_character_status"] or "unknown"),
                    personhood_evidence_summary=str(row["personhood_evidence_summary"] or ""),
                    evidence_level=str(row["evidence_level"] or "inferred"),
                    recent_activity_summary=self._recent_activity_summary(row),
                )
            )
            remaining_chars -= summary_fit.used_chars
            if summary_fit.truncated:
                missing_context.append("character_profiles.truncated")
                break

        if not selected_items:
            missing_context.append("character_profiles.over_budget")

        missing_requested = sorted(name for name in requested_names if name not in found_names)
        if missing_requested:
            missing_context.append(
                "character_profiles.requested_missing:" + ",".join(missing_requested)
            )

        return selected_items, missing_context

    def _read_clamped_text(self, path: Path, *, max_chars: int):
        if max_chars <= 0 or not path.exists():
            return fit_text_with_budget(text="", remaining_chars=0)
        text = path.read_text(encoding="utf-8", errors="replace").strip()
        return fit_text_with_budget(text=text, remaining_chars=max_chars)

    def _load_json_list(self, raw_value: object) -> list[str]:
        if not raw_value:
            return []
        try:
            value = json.loads(str(raw_value))
        except json.JSONDecodeError:
            return []
        if not isinstance(value, list):
            return []
        return [str(item).strip() for item in value if str(item).strip()]

    def _load_json_dict(self, raw_value: object) -> dict[str, object]:
        if not raw_value:
            return {}
        try:
            value = json.loads(str(raw_value))
        except json.JSONDecodeError:
            return {}
        return dict(value) if isinstance(value, dict) else {}

    def _row_status(self, row: sqlite3.Row, column: str) -> str:
        text = self._row_text(row, column, default="provisional")
        return text if text in {"provisional", "committed"} else "provisional"

    def _row_text(self, row: sqlite3.Row, column: str, default: str = "") -> str:
        try:
            value = row[column]
        except (IndexError, KeyError):
            return default
        return str(value or default).strip()

    def _combined_status(self, statuses: list[str]) -> str:
        cleaned = [status if status in {"provisional", "committed"} else "provisional" for status in statuses]
        if not cleaned:
            return "provisional"
        unique = set(cleaned)
        if unique == {"committed"}:
            return "committed"
        if unique == {"provisional"}:
            return "provisional"
        return "mixed"

    def _recent_activity_summary(self, row: sqlite3.Row) -> str:
        try:
            value = json.loads(str(row["recent_activity_json"] or "[]"))
        except json.JSONDecodeError:
            return ""
        if not isinstance(value, list):
            return ""
        activities: list[str] = []
        for item in value[-3:]:
            if isinstance(item, dict):
                text = str(item.get("value") or "").strip()
            else:
                text = str(item).strip()
            if text:
                activities.append(text)
        return "；".join(activities)

    def _dedupe(self, values: list[str]) -> list[str]:
        ordered: list[str] = []
        seen: set[str] = set()
        for value in values:
            normalized = str(value).strip()
            if not normalized or normalized in seen:
                continue
            seen.add(normalized)
            ordered.append(normalized)
        return ordered

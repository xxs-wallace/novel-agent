from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import datetime, timezone

from ..repos.character_profiles_repo import CharacterProfilesRepo
from ..repos.documents_repo import DocumentsRepo
from ..services.character_profile_service import CharacterProfileService


def _normalize_text(value: object) -> str:
    return str(value).strip()


def _excerpt(text: str, *, limit: int = 120) -> str:
    normalized = " ".join(text.split())
    if len(normalized) <= limit:
        return normalized
    return normalized[: max(0, limit - 1)].rstrip() + "…"


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


@dataclass(slots=True)
class SmokeBackfillResult:
    generated_doc_id: int | None = None
    updated_character_names: list[str] = field(default_factory=list)
    created_profile_names: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, object]:
        return {
            "generated_doc_id": self.generated_doc_id,
            "updated_character_names": list(self.updated_character_names),
            "created_profile_names": list(self.created_profile_names),
        }


class SmokeBackfillService:
    def __init__(
        self,
        *,
        documents_repo: DocumentsRepo | None = None,
        character_profiles_repo: CharacterProfilesRepo | None = None,
        character_profile_service: CharacterProfileService | None = None,
    ) -> None:
        self.documents_repo = documents_repo or DocumentsRepo()
        self.character_profiles_repo = character_profiles_repo or CharacterProfilesRepo()
        self.character_profile_service = character_profile_service or CharacterProfileService(
            profiles_repo=self.character_profiles_repo
        )

    def apply_generated_segment(
        self,
        conn,
        *,
        book_id: str,
        chapter_index: int,
        step_id: str,
        generated_text: str,
        prioritized_character_names: list[str],
    ) -> SmokeBackfillResult:
        normalized_text = _normalize_text(generated_text)
        if not normalized_text:
            return SmokeBackfillResult()
        known_before = {
            str(row["canonical_name"]).strip()
            for row in self.character_profiles_repo.list_by_book(conn, book_id=book_id)
        }
        updated_names = self._resolve_updated_names(
            conn,
            book_id=book_id,
            generated_text=normalized_text,
            prioritized_character_names=prioritized_character_names,
        )
        if not updated_names:
            updated_names = [_normalize_text(name) for name in prioritized_character_names if _normalize_text(name)]
        if not updated_names:
            return SmokeBackfillResult()
        generated_doc_id = self.documents_repo.insert_document(
            conn,
            {
                "book_id": book_id,
                "path": f"smoke://generated/{step_id}.md",
                "scope": "smoke_generated",
                "title": step_id,
                "content": normalized_text,
                "source_path": f"smoke://generated/{step_id}.md",
                "source_file_name": f"{step_id}.md",
                "source_start_offset": 0,
                "source_end_offset": len(normalized_text),
                "document_title": step_id,
                "document_title_index": chapter_index,
                "character_keywords": list(updated_names),
                "content_tags": ["smoke_generated"],
                "created_at": _utc_now(),
                "updated_at": _utc_now(),
            },
        )
        updates = [
            {
                "canonical_name": name,
                "aliases": [],
                "personality": [],
                "occupations": [],
                "recent_activity": _excerpt(normalized_text),
                "relationships": [],
            }
            for name in updated_names
        ]
        self.character_profile_service.merge_updates(
            conn,
            book_id=book_id,
            chapter_index=chapter_index,
            doc_ids=[generated_doc_id],
            updates=updates,
        )
        known_after = {
            str(row["canonical_name"]).strip()
            for row in self.character_profiles_repo.list_by_book(conn, book_id=book_id)
        }
        created = [name for name in updated_names if name in known_after and name not in known_before]
        return SmokeBackfillResult(
            generated_doc_id=generated_doc_id,
            updated_character_names=list(updated_names),
            created_profile_names=created,
        )

    def _resolve_updated_names(
        self,
        conn,
        *,
        book_id: str,
        generated_text: str,
        prioritized_character_names: list[str],
    ) -> list[str]:
        rows = self.character_profiles_repo.list_by_book(conn, book_id=book_id)
        matched: list[str] = []
        seen: set[str] = set()
        prioritized = [_normalize_text(name) for name in prioritized_character_names if _normalize_text(name)]
        for name in prioritized:
            if name in generated_text and name not in seen:
                matched.append(name)
                seen.add(name)
        for row in rows:
            canonical_name = _normalize_text(row["canonical_name"])
            aliases = row["aliases_json"] or "[]"
            if canonical_name and canonical_name in generated_text and canonical_name not in seen:
                matched.append(canonical_name)
                seen.add(canonical_name)
                continue
            for alias in [item.strip() for item in json.loads(aliases) if str(item).strip()]:
                if alias in generated_text and canonical_name and canonical_name not in seen:
                    matched.append(canonical_name)
                    seen.add(canonical_name)
                    break
        return matched

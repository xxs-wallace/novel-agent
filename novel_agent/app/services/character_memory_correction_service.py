from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass, field
from typing import Any, Mapping

from ..llm import JsonModelClient
from ..prompts.character_memory_correction_prompt import (
    build_character_memory_correction_prompt,
    build_character_memory_correction_seed_prompt,
)
from ..repos.character_profiles_repo import CharacterProfilesRepo
from ..schemas.character_profile_schema import (
    CharacterAbilityItem,
    CharacterAgeItem,
    CharacterProfileSnapshot,
    CharacterRelationshipItem,
    CharacterStoryEventItem,
    ProfileAttributeItem,
)
from .character_profile_service import CharacterProfileService, _utc_now


@dataclass(slots=True)
class CharacterMemoryCorrectionResult:
    applied: bool
    reason: str
    operations_applied: int = 0
    touched_character_ids: list[int] = field(default_factory=list)
    touched_canonical_names: list[str] = field(default_factory=list)
    created_canonical_names: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


class CharacterMemoryCorrectionService:
    """Applies explicit, auditable corrections to polluted character memory.

    The service executes a confirmed correction plan. It does not discover semantic
    mistakes by itself; candidate discovery/review must be handled by a model loop
    or by an explicit user-confirmed repair task.
    """

    APPROVED_STATUSES = {"approved", "confirmed", "user_confirmed", "manual_repair"}
    VALID_CORRECTION_TYPES = {
        "false_attribution",
        "identity_reveal",
        "event_reinterpretation",
        "location_reveal",
        "timeline_reorder",
        "relationship_reinterpretation",
        "manual_profile_surgery",
    }
    VALID_OPS = {
        "remove_aliases",
        "move_story_events",
        "remove_story_events",
        "rewrite_relationship_target",
        "ensure_profile",
        "append_correction_event",
    }

    def __init__(self, *, profiles_repo: CharacterProfilesRepo, min_confidence: float = 0.9) -> None:
        self.profiles_repo = profiles_repo
        self.profile_service = CharacterProfileService(profiles_repo=profiles_repo)
        self.min_confidence = float(min_confidence)

    def seed_next_step(
        self,
        *,
        model_client: JsonModelClient,
        prompt_input: dict[str, Any],
    ) -> dict[str, Any]:
        system_prompt, user_prompt = build_character_memory_correction_seed_prompt(prompt_input)
        payload, _ = model_client.generate_json(
            system_prompt=system_prompt,
            user_prompt=user_prompt,
            fallback_factory=lambda: {
                "next_action": "request_more_index",
                "selected_outline_root_ids": [],
                "selected_outline_segment_ids": [],
                "selected_doc_ids": [],
                "search_focus": "fallback cannot locate correction evidence",
                "candidate_correction": {},
                "reason": "fallback cannot complete semantic evidence routing",
                "confidence": 0.0,
            },
            use_fallback_on_error=model_client.settings.dry_run,
        )
        step = dict(payload) if isinstance(payload, dict) else {}
        action = str(step.get("next_action") or "").strip()
        if action not in {
            "inspect_outline_segments",
            "inspect_documents",
            "propose_correction_plan",
            "request_more_index",
        }:
            raise RuntimeError("Character memory correction seed model returned an invalid next_action")
        step["selected_outline_root_ids"] = self._name_list(step.get("selected_outline_root_ids"))[:6]
        step["selected_outline_segment_ids"] = self._name_list(step.get("selected_outline_segment_ids"))[:6]
        step["selected_doc_ids"] = self._int_list(step.get("selected_doc_ids"))[:8]
        return step

    def review_candidate(
        self,
        *,
        model_client: JsonModelClient,
        prompt_input: dict[str, Any],
    ) -> dict[str, Any]:
        system_prompt, user_prompt = build_character_memory_correction_prompt(prompt_input)
        payload, _ = model_client.generate_json(
            system_prompt=system_prompt,
            user_prompt=user_prompt,
            fallback_factory=lambda: {
                "status": "request_more_evidence",
                "correction_type": "",
                "reason": "fallback cannot confirm memory correction",
                "confidence": 0.0,
                "source_doc_ids": [],
                "source_title_indexes": [],
                "outline_segment_ids": [],
                "operations": [],
            },
            use_fallback_on_error=model_client.settings.dry_run,
        )
        plan = dict(payload) if isinstance(payload, dict) else {}
        status = str(plan.get("status") or "").strip()
        if status not in {*self.APPROVED_STATUSES, "rejected", "request_more_evidence"}:
            raise RuntimeError("Character memory correction model returned an invalid status")
        operations = plan.get("operations")
        if status in self.APPROVED_STATUSES and not isinstance(operations, list):
            raise RuntimeError("Character memory correction model returned an approved plan without operations")
        return plan

    def apply_plan(self, conn, *, book_id: str, plan: Mapping[str, Any]) -> CharacterMemoryCorrectionResult:
        invalid_reason = self._invalid_plan_reason(plan)
        if invalid_reason:
            return CharacterMemoryCorrectionResult(applied=False, reason=invalid_reason)

        operations = [item for item in plan.get("operations", []) if isinstance(item, Mapping)]
        touched_ids: list[int] = []
        touched_names: list[str] = []
        created_names: list[str] = []
        applied = 0
        for operation in operations:
            op = str(operation.get("op") or "").strip()
            if op not in self.VALID_OPS:
                continue
            if op == "ensure_profile":
                row, created = self._ensure_profile(conn, book_id=book_id, operation=operation, plan=plan)
                if row is not None:
                    applied += 1
                    self._append_unique(touched_ids, self._row_id(row))
                    self._append_unique(touched_names, self._row_name(row))
                    if created:
                        self._append_unique(created_names, self._row_name(row))
                continue
            if op == "remove_aliases":
                applied += self._remove_aliases(conn, book_id=book_id, operation=operation, touched_ids=touched_ids, touched_names=touched_names)
                continue
            if op == "move_story_events":
                applied += self._move_story_events(conn, book_id=book_id, operation=operation, plan=plan, touched_ids=touched_ids, touched_names=touched_names, created_names=created_names)
                continue
            if op == "remove_story_events":
                applied += self._remove_story_events(conn, book_id=book_id, operation=operation, plan=plan, touched_ids=touched_ids, touched_names=touched_names)
                continue
            if op == "rewrite_relationship_target":
                applied += self._rewrite_relationship_target(conn, book_id=book_id, operation=operation, touched_ids=touched_ids, touched_names=touched_names)
                continue
            if op == "append_correction_event":
                applied += self._append_correction_event(conn, book_id=book_id, operation=operation, plan=plan, touched_ids=touched_ids, touched_names=touched_names)

        return CharacterMemoryCorrectionResult(
            applied=applied > 0,
            reason="applied confirmed correction plan" if applied else "no operations matched",
            operations_applied=applied,
            touched_character_ids=touched_ids,
            touched_canonical_names=touched_names,
            created_canonical_names=created_names,
        )

    def _remove_aliases(
        self,
        conn,
        *,
        book_id: str,
        operation: Mapping[str, Any],
        touched_ids: list[int],
        touched_names: list[str],
    ) -> int:
        row = self._resolve_profile(conn, book_id=book_id, character_id=operation.get("character_id"), canonical_name=operation.get("canonical_name"))
        if row is None:
            return 0
        aliases_to_remove = set(self._name_list(operation.get("aliases") or operation.get("aliases_to_remove")))
        if not aliases_to_remove:
            return 0
        aliases = [alias for alias in self._load_json_list(row, "aliases_json") if str(alias).strip() not in aliases_to_remove]
        self._write_profile(conn, book_id=book_id, row=row, aliases=aliases)
        self._touch(row, touched_ids=touched_ids, touched_names=touched_names)
        return 1

    def _move_story_events(
        self,
        conn,
        *,
        book_id: str,
        operation: Mapping[str, Any],
        plan: Mapping[str, Any],
        touched_ids: list[int],
        touched_names: list[str],
        created_names: list[str],
    ) -> int:
        source = self._resolve_profile(conn, book_id=book_id, character_id=operation.get("character_id"), canonical_name=operation.get("canonical_name"))
        if source is None:
            return 0
        target_name = str(operation.get("target_canonical_name") or operation.get("target_name") or "").strip()
        if not target_name:
            return 0
        target, created = self._ensure_profile(conn, book_id=book_id, operation={**dict(operation), "canonical_name": target_name}, plan=plan)
        if target is None:
            return 0
        source_events = self._load_json_list(source, "story_events_json")
        selected, remaining = self._split_events(source_events, operation)
        if not selected:
            return 0
        source_names = [self._row_name(source), *self._load_json_list(source, "aliases_json"), *self._name_list(operation.get("misattributed_names"))]
        moved_events = [
            self._rewrite_event_participants(event, old_names=source_names, new_name=target_name)
            for event in selected
            if isinstance(event, dict)
        ]
        source_doc_ids = self._doc_ids_from_events(moved_events)
        source_mentioned = self._load_json_list(source, "mentioned_doc_ids_json")
        source_speaking = self._load_json_list(source, "speaking_doc_ids_json")
        if bool(operation.get("remove_source_doc_refs", True)):
            source_mentioned = [doc_id for doc_id in source_mentioned if self.profile_service._safe_int(doc_id) not in source_doc_ids]  # noqa: SLF001
            source_speaking = [doc_id for doc_id in source_speaking if self.profile_service._safe_int(doc_id) not in source_doc_ids]  # noqa: SLF001
        self._write_profile(
            conn,
            book_id=book_id,
            row=source,
            story_events=remaining,
            mentioned_doc_ids=source_mentioned,
            speaking_doc_ids=source_speaking,
            personhood_evidence_summary=self._correction_summary(
                row=source,
                plan=plan,
                prefix=f"修正：部分经历已从{self._row_name(source)}迁移至{target_name}",
            ),
        )
        target = self._resolve_profile(conn, book_id=book_id, canonical_name=target_name)
        assert target is not None
        target_events = self.profile_service._merge_story_events(  # noqa: SLF001
            self._load_json_list(target, "story_events_json"),
            moved_events,
            chapter_index=self._latest_title_index(plan, moved_events),
            doc_ids=sorted(source_doc_ids),
        )
        target_mentioned = self.profile_service._merge_chapter_indexes(  # noqa: SLF001
            self._load_json_list(target, "mentioned_doc_ids_json"),
            sorted(source_doc_ids),
        )
        target_speaking = self._load_json_list(target, "speaking_doc_ids_json")
        if bool(operation.get("move_speaking_doc_refs", False)):
            target_speaking = self.profile_service._merge_chapter_indexes(target_speaking, sorted(source_doc_ids))  # noqa: SLF001
        self._write_profile(
            conn,
            book_id=book_id,
            row=target,
            story_events=target_events,
            mentioned_doc_ids=target_mentioned,
            speaking_doc_ids=target_speaking,
            personhood_evidence_summary=self._correction_summary(
                row=target,
                plan=plan,
                prefix=f"修正：从{self._row_name(source)}迁入误归因经历",
            ),
        )
        self._touch(source, touched_ids=touched_ids, touched_names=touched_names)
        updated_target = self._resolve_profile(conn, book_id=book_id, canonical_name=target_name) or target
        self._touch(updated_target, touched_ids=touched_ids, touched_names=touched_names)
        if created:
            self._append_unique(created_names, target_name)
        return 1

    def _remove_story_events(
        self,
        conn,
        *,
        book_id: str,
        operation: Mapping[str, Any],
        plan: Mapping[str, Any],
        touched_ids: list[int],
        touched_names: list[str],
    ) -> int:
        row = self._resolve_profile(conn, book_id=book_id, character_id=operation.get("character_id"), canonical_name=operation.get("canonical_name"))
        if row is None:
            return 0
        selected, remaining = self._split_events(self._load_json_list(row, "story_events_json"), operation)
        if not selected:
            return 0
        self._write_profile(
            conn,
            book_id=book_id,
            row=row,
            story_events=remaining,
            personhood_evidence_summary=self._correction_summary(
                row=row,
                plan=plan,
                prefix="修正：移除误归因经历",
            ),
        )
        self._touch(row, touched_ids=touched_ids, touched_names=touched_names)
        return 1

    def _rewrite_relationship_target(
        self,
        conn,
        *,
        book_id: str,
        operation: Mapping[str, Any],
        touched_ids: list[int],
        touched_names: list[str],
    ) -> int:
        old_names = set(self._name_list(operation.get("old_names")))
        new_name = str(operation.get("new_name") or operation.get("target_canonical_name") or "").strip()
        if not old_names or not new_name:
            return 0
        rows = self.profiles_repo.list_by_book(conn, book_id=book_id)
        if operation.get("character_id") or operation.get("canonical_name"):
            row = self._resolve_profile(conn, book_id=book_id, character_id=operation.get("character_id"), canonical_name=operation.get("canonical_name"))
            rows = [row] if row is not None else []
        changed = 0
        for row in rows:
            relationships = self._load_json_list(row, "relationships_json")
            did_change = False
            for relationship in relationships:
                if isinstance(relationship, dict) and str(relationship.get("target_name") or "").strip() in old_names:
                    relationship["target_name"] = new_name
                    did_change = True
            if not did_change:
                continue
            self._write_profile(conn, book_id=book_id, row=row, relationships=relationships)
            self._touch(row, touched_ids=touched_ids, touched_names=touched_names)
            changed += 1
        return changed

    def _append_correction_event(
        self,
        conn,
        *,
        book_id: str,
        operation: Mapping[str, Any],
        plan: Mapping[str, Any],
        touched_ids: list[int],
        touched_names: list[str],
    ) -> int:
        row = self._resolve_profile(conn, book_id=book_id, character_id=operation.get("character_id"), canonical_name=operation.get("canonical_name"))
        if row is None:
            return 0
        event = self._correction_event(row=row, operation=operation, plan=plan)
        story_events = self.profile_service._merge_story_events(  # noqa: SLF001
            self._load_json_list(row, "story_events_json"),
            [event],
            chapter_index=self._latest_title_index(plan, [event]),
            doc_ids=self._int_list(plan.get("source_doc_ids")),
        )
        self._write_profile(conn, book_id=book_id, row=row, story_events=story_events)
        self._touch(row, touched_ids=touched_ids, touched_names=touched_names)
        return 1

    def _ensure_profile(
        self,
        conn,
        *,
        book_id: str,
        operation: Mapping[str, Any],
        plan: Mapping[str, Any],
    ) -> tuple[Any | None, bool]:
        name = str(operation.get("target_canonical_name") or operation.get("canonical_name") or "").strip()
        if not name:
            return None, False
        existing = self.profiles_repo.get(conn, book_id=book_id, canonical_name=name)
        if existing is not None:
            return existing, False
        aliases = self._name_list(operation.get("aliases"))
        source_doc_ids = self._int_list(plan.get("source_doc_ids"))
        source_title_indexes = self._int_list(plan.get("source_title_indexes"))
        now = _utc_now()
        self.profiles_repo.upsert(
            conn,
            {
                "book_id": book_id,
                "canonical_name": name,
                "aliases": aliases,
                "profile_summary_md": f"# {name}\n\n- 修正创建：{str(plan.get('reason') or '').strip()}\n",
                "speaking_character_status": "unknown",
                "personhood_evidence_summary": str(operation.get("personhood_evidence_summary") or plan.get("reason") or ""),
                "evidence_level": "explicit" if source_doc_ids else "inferred",
                "personality": [],
                "occupations": [],
                "age_timeline": [],
                "abilities": [],
                "recent_activity": [],
                "relationships": [],
                "story_events": [],
                "chapter_indexes": source_title_indexes,
                "mentioned_doc_ids": source_doc_ids,
                "speaking_doc_ids": [],
                "first_seen_doc_id": min(source_doc_ids) if source_doc_ids else None,
                "last_seen_doc_id": max(source_doc_ids) if source_doc_ids else None,
                "first_seen_title_index": min(source_title_indexes) if source_title_indexes else None,
                "last_seen_title_index": max(source_title_indexes) if source_title_indexes else None,
                "importance_score": 0,
                "profile_version": 1,
                "created_at": now,
                "updated_at": now,
            },
        )
        return self.profiles_repo.get(conn, book_id=book_id, canonical_name=name), True

    def _write_profile(
        self,
        conn,
        *,
        book_id: str,
        row: Any,
        aliases: list[Any] | None = None,
        relationships: list[Any] | None = None,
        story_events: list[Any] | None = None,
        mentioned_doc_ids: list[Any] | None = None,
        speaking_doc_ids: list[Any] | None = None,
        personhood_evidence_summary: str | None = None,
    ) -> None:
        canonical_name = self._row_name(row)
        aliases_out = self.profile_service._merge_aliases([], aliases if aliases is not None else self._load_json_list(row, "aliases_json"), canonical_name=canonical_name)  # noqa: SLF001
        relationships_out = self.profile_service._merge_relationship_items(  # noqa: SLF001
            [],
            relationships if relationships is not None else self._load_json_list(row, "relationships_json"),
            subject_name=canonical_name,
            chapter_index=0,
            doc_ids=[],
            known_name_map={},
        )
        story_events_out = self.profile_service._merge_story_events(  # noqa: SLF001
            [],
            story_events if story_events is not None else self._load_json_list(row, "story_events_json"),
            chapter_index=0,
            doc_ids=[],
        )
        mentioned_out = self.profile_service._merge_chapter_indexes(  # noqa: SLF001
            [],
            mentioned_doc_ids if mentioned_doc_ids is not None else self._load_json_list(row, "mentioned_doc_ids_json"),
        )
        speaking_out = self.profile_service._merge_chapter_indexes(  # noqa: SLF001
            [],
            speaking_doc_ids if speaking_doc_ids is not None else self._load_json_list(row, "speaking_doc_ids_json"),
        )
        chapter_indexes = self.profile_service._merge_chapter_indexes(  # noqa: SLF001
            self._load_json_list(row, "chapter_indexes_json"),
            [idx for event in story_events_out for idx in self._as_list(event.get("source_chapter_indexes")) if isinstance(event, dict)],
        )
        snapshot = CharacterProfileSnapshot(
            canonical_name=canonical_name,
            aliases=aliases_out,
            speaking_character_status=str(row["speaking_character_status"] or "unknown"),
            personhood_evidence_summary=personhood_evidence_summary if personhood_evidence_summary is not None else str(row["personhood_evidence_summary"] or ""),
            evidence_level=str(row["evidence_level"] or "inferred"),
            personality=[ProfileAttributeItem(**item) for item in self.profile_service._merge_attribute_items([], self._load_json_list(row, "personality_json"), field_type="inference", evidence_level="inferred", chapter_index=0, doc_ids=[])],  # noqa: SLF001
            occupations=[ProfileAttributeItem(**item) for item in self.profile_service._merge_attribute_items([], self._load_json_list(row, "occupations_json"), field_type="fact", evidence_level="explicit", chapter_index=0, doc_ids=[])],  # noqa: SLF001
            age_timeline=[CharacterAgeItem(**item) for item in self.profile_service._merge_age_timeline([], self._load_json_list(row, "age_timeline_json"), chapter_index=0, doc_ids=[])],  # noqa: SLF001
            abilities=[CharacterAbilityItem(**item) for item in self.profile_service._merge_ability_items([], self._load_json_list(row, "abilities_json"), chapter_index=0, doc_ids=[])],  # noqa: SLF001
            recent_activity=[ProfileAttributeItem(**item) for item in self.profile_service._merge_attribute_items([], self._load_json_list(row, "recent_activity_json"), field_type="fact", evidence_level="explicit", chapter_index=0, doc_ids=[])],  # noqa: SLF001
            relationships=[CharacterRelationshipItem(**item) for item in relationships_out],
            story_events=[CharacterStoryEventItem(**item) for item in story_events_out],
            chapter_indexes=chapter_indexes,
        )
        profile_summary_md = self.profile_service._append_document_presence_summary(  # noqa: SLF001
            self.profile_service._build_summary(snapshot=snapshot),  # noqa: SLF001
            mentioned_doc_ids=mentioned_out,
            speaking_doc_ids=speaking_out,
        )
        self.profiles_repo.upsert(
            conn,
            {
                "book_id": book_id,
                **snapshot.to_dict(),
                "profile_summary_md": profile_summary_md,
                "story_events": story_events_out,
                "mentioned_doc_ids": mentioned_out,
                "speaking_doc_ids": speaking_out,
                "first_seen_doc_id": min(mentioned_out) if mentioned_out else row["first_seen_doc_id"],
                "last_seen_doc_id": max(mentioned_out) if mentioned_out else row["last_seen_doc_id"],
                "first_seen_title_index": min(chapter_indexes) if chapter_indexes else row["first_seen_title_index"],
                "last_seen_title_index": max(chapter_indexes) if chapter_indexes else row["last_seen_title_index"],
                "importance_score": int(row["importance_score"] or 0),
                "profile_version": int(row["profile_version"] or 1) + 1,
                "created_at": str(row["created_at"] or "") or _utc_now(),
                "updated_at": _utc_now(),
            },
        )

    def _split_events(self, events: list[Any], operation: Mapping[str, Any]) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
        if not self._has_event_selector(operation):
            return [], [event for event in events if isinstance(event, dict)]
        selected: list[dict[str, Any]] = []
        remaining: list[dict[str, Any]] = []
        for event in events:
            if not isinstance(event, dict):
                continue
            if self._event_matches(event, operation):
                selected.append(event)
            else:
                remaining.append(event)
        return selected, remaining

    def _event_matches(self, event: Mapping[str, Any], operation: Mapping[str, Any]) -> bool:
        event_ids = set(self._name_list(operation.get("event_ids")))
        if event_ids and str(event.get("event_id") or "").strip() in event_ids:
            return True
        outline_segment_ids = set(self._name_list(operation.get("outline_segment_ids") or operation.get("outline_segment_id")))
        if outline_segment_ids and str(event.get("outline_segment_id") or "").strip() in outline_segment_ids:
            return True
        source_doc_ids = set(self._int_list(operation.get("source_doc_ids")))
        if source_doc_ids and source_doc_ids.intersection(self._int_list(event.get("source_doc_ids"))):
            return True
        participant_names = set(self._name_list(operation.get("participant_names")))
        if participant_names and participant_names.intersection(self._name_list(event.get("participants"))):
            return True
        label_contains = [text for text in self._name_list(operation.get("label_contains")) if text]
        label_text = f"{event.get('label') or ''}\n{event.get('summary') or ''}"
        return bool(label_contains and any(text in label_text for text in label_contains))

    def _has_event_selector(self, operation: Mapping[str, Any]) -> bool:
        return any(
            self._name_list(operation.get(field_name))
            for field_name in (
                "event_ids",
                "outline_segment_ids",
                "outline_segment_id",
                "source_doc_ids",
                "participant_names",
                "label_contains",
            )
        )

    def _rewrite_event_participants(self, event: Mapping[str, Any], *, old_names: list[str], new_name: str) -> dict[str, Any]:
        old_name_set = set(self._name_list(old_names))
        rewritten = dict(event)
        participants = self._name_list(event.get("participants"))
        rewritten["participants"] = self.profile_service._merge_aliases(  # noqa: SLF001
            [],
            [new_name if name in old_name_set else name for name in participants] or [new_name],
            canonical_name="",
        )
        return rewritten

    def _correction_event(self, *, row: Any, operation: Mapping[str, Any], plan: Mapping[str, Any]) -> dict[str, Any]:
        summary = str(operation.get("summary") or plan.get("reason") or "").strip()
        source_doc_ids = self._int_list(operation.get("source_doc_ids") or plan.get("source_doc_ids"))
        source_title_indexes = self._int_list(operation.get("source_title_indexes") or plan.get("source_title_indexes"))
        outline_ids = self._name_list(operation.get("outline_segment_ids") or plan.get("outline_segment_ids"))
        digest = hashlib.sha1(
            f"{self._row_id(row)}:{summary}:{source_doc_ids}:{outline_ids}".encode("utf-8")
        ).hexdigest()[:10]
        return {
            "event_id": f"memory-correction:{self._row_id(row)}:{digest}",
            "label": str(operation.get("label") or "记忆修正").strip(),
            "summary": summary,
            "outline_segment_id": outline_ids[0] if outline_ids else "",
            "role_in_segment": "memory_correction",
            "compression_level": "brief",
            "source_chapter_indexes": source_title_indexes,
            "source_doc_ids": source_doc_ids,
            "source_doc_range": self.profile_service._doc_range_text(source_doc_ids),  # noqa: SLF001
            "participants": [self._row_name(row)],
        }

    def _correction_summary(self, *, row: Any, plan: Mapping[str, Any], prefix: str) -> str:
        current = str(row["personhood_evidence_summary"] or "")
        reason = str(plan.get("reason") or "").strip()
        return self.profile_service._merge_personhood_evidence_summary(current, f"{prefix}：{reason}")  # noqa: SLF001

    def _invalid_plan_reason(self, plan: Mapping[str, Any]) -> str:
        status = str(plan.get("status") or "").strip()
        if status not in self.APPROVED_STATUSES:
            return f"correction plan is not approved: {status or 'missing'}"
        correction_type = str(plan.get("correction_type") or "").strip()
        if correction_type not in self.VALID_CORRECTION_TYPES:
            return "correction type is not supported"
        try:
            confidence = float(plan.get("confidence") or 0.0)
        except (TypeError, ValueError):
            confidence = 0.0
        if confidence < self.min_confidence:
            return "correction confidence below threshold"
        if not str(plan.get("reason") or "").strip():
            return "correction reason is empty"
        if not self._int_list(plan.get("source_doc_ids")) and not self._name_list(plan.get("outline_segment_ids")):
            return "correction plan lacks source refs"
        operations = plan.get("operations")
        if not isinstance(operations, list) or not operations:
            return "correction plan has no operations"
        return ""

    def _resolve_profile(self, conn, *, book_id: str, character_id: object = None, canonical_name: object = "") -> Any | None:
        try:
            normalized_id = int(character_id or 0)
        except (TypeError, ValueError):
            normalized_id = 0
        if normalized_id > 0:
            row = self.profiles_repo.get_by_id(conn, book_id=book_id, character_id=normalized_id)
            if row is not None:
                return row
        name = str(canonical_name or "").strip()
        if not name:
            return None
        exact = self.profiles_repo.get(conn, book_id=book_id, canonical_name=name)
        if exact is not None:
            return exact
        for row in self.profiles_repo.list_by_book(conn, book_id=book_id):
            if name in {str(item).strip() for item in self._load_json_list(row, "aliases_json")}:
                return row
        return None

    def _latest_title_index(self, plan: Mapping[str, Any], events: list[Mapping[str, Any]]) -> int:
        values = self._int_list(plan.get("source_title_indexes"))
        for event in events:
            values.extend(self._int_list(event.get("source_chapter_indexes")))
        return max(values) if values else 0

    def _doc_ids_from_events(self, events: list[Mapping[str, Any]]) -> set[int]:
        doc_ids: set[int] = set()
        for event in events:
            doc_ids.update(self._int_list(event.get("source_doc_ids")))
        return doc_ids

    def _load_json_list(self, row: Any, field_name: str) -> list[Any]:
        raw = row[field_name]
        if not raw:
            return []
        try:
            loaded = json.loads(raw)
        except json.JSONDecodeError:
            return []
        return loaded if isinstance(loaded, list) else []

    def _name_list(self, values: object) -> list[str]:
        if values is None:
            return []
        if not isinstance(values, list):
            values = [values]
        result: list[str] = []
        for value in values:
            text = str(value or "").strip()
            if text and text not in result:
                result.append(text)
        return result

    def _int_list(self, values: object) -> list[int]:
        result: list[int] = []
        for value in self._name_list(values):
            try:
                item = int(value)
            except (TypeError, ValueError):
                continue
            if item not in result:
                result.append(item)
        return result

    def _as_list(self, value: object) -> list[Any]:
        if value is None:
            return []
        if isinstance(value, list):
            return value
        return [value]

    def _touch(self, row: Any, *, touched_ids: list[int], touched_names: list[str]) -> None:
        self._append_unique(touched_ids, self._row_id(row))
        self._append_unique(touched_names, self._row_name(row))

    @staticmethod
    def _append_unique(values: list[Any], value: Any) -> None:
        if value not in values:
            values.append(value)

    @staticmethod
    def _row_id(row: Any) -> int:
        try:
            return int(row["character_id"])
        except (KeyError, TypeError, ValueError):
            return 0

    @staticmethod
    def _row_name(row: Any) -> str:
        return str(row["canonical_name"] or "").strip()

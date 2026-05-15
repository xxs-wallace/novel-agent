from __future__ import annotations

import json
import re
from datetime import datetime, timezone
from typing import Any

from ..repos.character_profiles_repo import CharacterProfilesRepo
from ..schemas.character_profile_schema import (
    CharacterAbilityItem,
    CharacterAgeItem,
    CharacterProfileSnapshot,
    CharacterRelationshipItem,
    CharacterStoryEventItem,
    ProfileAttributeItem,
)


ALIAS_PREFIXES = ("小", "老", "阿")
ALIAS_SUFFIXES = (
    "哥",
    "姐",
    "叔",
    "姨",
    "伯",
    "老师",
    "教授",
    "先生",
    "小姐",
    "少爷",
    "师兄",
    "师姐",
    "师弟",
    "师妹",
    "学长",
    "学姐",
    "同学",
    "前辈",
    "老板",
    "总",
)
STYLE_META_KEYWORDS = (
    "伏笔",
    "铺垫",
    "呼应",
    "映衬",
    "反衬",
    "悬念",
    "张力",
    "节奏",
    "氛围",
    "描写",
    "写法",
    "文风",
    "叙事",
    "镜头",
    "视角",
    "隐喻",
    "象征",
    "转场",
    "感染力",
    "戏剧性",
    "宿命感",
)
STYLE_META_PATTERNS = (
    "本章",
    "这一章",
    "这段",
    "这一段",
    "作者",
    "文本",
    "叙事上",
    "写法上",
)
WHITESPACE_RE = re.compile(r"\s+")


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


class CharacterProfileService:
    def __init__(self, *, profiles_repo: CharacterProfilesRepo) -> None:
        self.profiles_repo = profiles_repo

    def load_profiles(self, conn, *, book_id: str, names: list[str]) -> list[dict[str, str]]:
        rows = self.profiles_repo.list_by_names(conn, book_id=book_id, names=names)
        return [
            {
                "canonical_name": str(row["canonical_name"]),
                "profile_summary_md": str(row["profile_summary_md"]),
            }
            for row in rows
        ]

    def merge_updates(
        self,
        conn,
        *,
        book_id: str,
        chapter_index: int,
        doc_ids: list[int],
        updates: list[dict[str, object]],
        mentioned_doc_ids_by_name: dict[str, list[int]] | None = None,
        speaking_doc_ids_by_name: dict[str, list[int]] | None = None,
        story_events_by_name: dict[str, list[dict[str, Any]]] | None = None,
    ) -> None:
        first_doc_id = min(doc_ids) if doc_ids else None
        last_doc_id = max(doc_ids) if doc_ids else None
        for update in updates:
            if not isinstance(update, dict):
                continue
            incoming_name = self._normalize_name(update.get("canonical_name"))
            if not incoming_name:
                continue
            update_aliases = self._normalize_aliases(update.get("aliases"))
            matched_rows, known_name_map = self._find_matching_rows(
                conn,
                book_id=book_id,
                names=[incoming_name, *update_aliases],
            )
            all_known_names = [incoming_name, *update_aliases]
            for row in matched_rows:
                all_known_names.append(self._normalize_name(row["canonical_name"]))
                all_known_names.extend(self._normalize_aliases(self._load_json_field(row, "aliases_json")))
            canonical_name = self._choose_canonical_name(all_known_names)
            base_profile = self._merge_existing_rows(matched_rows)
            mentioned_doc_ids_for_update = self._doc_ids_for_names(
                mentioned_doc_ids_by_name or {},
                [incoming_name, *update_aliases],
            )
            speaking_doc_ids_for_update = self._doc_ids_for_names(
                speaking_doc_ids_by_name or {},
                [incoming_name, *update_aliases],
            )
            story_events_for_update = self._events_for_names(
                story_events_by_name or {},
                [incoming_name, *update_aliases],
            )
            mentioned_doc_ids = self._merge_chapter_indexes(
                base_profile["mentioned_doc_ids"],
                mentioned_doc_ids_for_update if mentioned_doc_ids_by_name is not None else doc_ids,
            )
            speaking_doc_ids = self._merge_chapter_indexes(
                base_profile["speaking_doc_ids"],
                speaking_doc_ids_for_update,
            )
            aliases = self._merge_aliases(
                base_profile["aliases"],
                [incoming_name, *update_aliases],
                canonical_name=canonical_name,
            )
            personality = self._merge_attribute_items(
                base_profile["personality"],
                update.get("personality"),
                field_type="inference",
                evidence_level="inferred",
                chapter_index=chapter_index,
                doc_ids=doc_ids,
            )
            occupations = self._merge_attribute_items(
                base_profile["occupations"],
                update.get("occupations"),
                field_type="fact",
                evidence_level="explicit",
                chapter_index=chapter_index,
                doc_ids=doc_ids,
            )
            abilities = self._merge_ability_items(
                base_profile["abilities"],
                update.get("abilities"),
                chapter_index=chapter_index,
                doc_ids=doc_ids,
            )
            relationships = self._merge_relationship_items(
                base_profile["relationships"],
                [
                    *self._as_list(update.get("relationships")),
                    *self._relationship_items_from_lightweight_evidence(
                        subject_name=canonical_name,
                        relationship_evidence=update.get("relationship_evidence"),
                        chapter_index=chapter_index,
                    ),
                ],
                subject_name=canonical_name,
                chapter_index=chapter_index,
                doc_ids=doc_ids,
                known_name_map=known_name_map,
            )
            chapter_indexes = self._merge_chapter_indexes(
                base_profile["chapter_indexes"],
                [chapter_index],
            )
            age_timeline = self._merge_age_timeline(
                base_profile["age_timeline"],
                update.get("age_update"),
                chapter_index=chapter_index,
                doc_ids=doc_ids,
            )
            recent_activity = self._merge_attribute_items(
                base_profile["recent_activity"],
                self._lightweight_recent_activity_items(update),
                field_type="fact",
                evidence_level="explicit",
                chapter_index=chapter_index,
                doc_ids=doc_ids,
            )
            story_events = self._merge_story_events(
                base_profile["story_events"],
                story_events_for_update,
                chapter_index=chapter_index,
                doc_ids=doc_ids,
            )
            speaking_character_status = self._merge_speaking_character_status(
                base_profile["speaking_character_status"],
                update=update,
                speaking_doc_ids=speaking_doc_ids,
            )
            personhood_evidence_summary = self._merge_personhood_evidence_summary(
                base_profile["personhood_evidence_summary"],
                update.get("personhood_evidence_summary") or update.get("personhood_evidence"),
            )
            evidence_level = self._merge_profile_evidence_level(
                base_profile["evidence_level"],
                update.get("evidence_level"),
                speaking_character_status=speaking_character_status,
            )
            snapshot = CharacterProfileSnapshot(
                canonical_name=canonical_name,
                aliases=aliases,
                speaking_character_status=speaking_character_status,
                personhood_evidence_summary=personhood_evidence_summary,
                evidence_level=evidence_level,
                personality=[
                    ProfileAttributeItem(**item)
                    for item in personality
                ],
                occupations=[
                    ProfileAttributeItem(**item)
                    for item in occupations
                ],
                age_timeline=[
                    CharacterAgeItem(**item)
                    for item in age_timeline
                ],
                abilities=[
                    CharacterAbilityItem(**item)
                    for item in abilities
                ],
                recent_activity=[
                    ProfileAttributeItem(**item)
                    for item in recent_activity
                ],
                relationships=[
                    CharacterRelationshipItem(**item)
                    for item in relationships
                ],
                story_events=[
                    CharacterStoryEventItem(**item)
                    for item in story_events
                ],
                chapter_indexes=chapter_indexes,
            )
            snapshot.profile_summary_md = self._append_document_presence_summary(
                self._build_summary(snapshot=snapshot),
                mentioned_doc_ids=mentioned_doc_ids,
                speaking_doc_ids=speaking_doc_ids,
            )
            self.profiles_repo.upsert(
                conn,
                {
                    "book_id": book_id,
                    **snapshot.to_dict(),
                    "story_events": story_events,
                    "mentioned_doc_ids": mentioned_doc_ids,
                    "speaking_doc_ids": speaking_doc_ids,
                    "first_seen_doc_id": self._min_int(base_profile["first_seen_doc_id"], first_doc_id),
                    "last_seen_doc_id": self._max_int(base_profile["last_seen_doc_id"], last_doc_id),
                    "first_seen_title_index": self._min_int(
                        base_profile["first_seen_title_index"],
                        chapter_index,
                    ),
                    "last_seen_title_index": self._max_int(
                        base_profile["last_seen_title_index"],
                        chapter_index,
                    ),
                    "importance_score": int(base_profile["importance_score"]),
                    "profile_version": int(base_profile["profile_version"]) + 1,
                    "created_at": base_profile["created_at"] or _utc_now(),
                    "updated_at": _utc_now(),
                },
            )
            duplicate_names = [
                self._normalize_name(row["canonical_name"])
                for row in matched_rows
                if self._normalize_name(row["canonical_name"]) != canonical_name
            ]
            self.profiles_repo.delete_many(
                conn,
                book_id=book_id,
                canonical_names=duplicate_names,
            )

    def _find_matching_rows(
        self,
        conn,
        *,
        book_id: str,
        names: list[Any],
    ) -> tuple[list[Any], dict[str, str]]:
        normalized_names = {name for name in (self._normalize_name(item) for item in names) if name}
        rows = self.profiles_repo.list_by_book(conn, book_id=book_id)
        matched_rows = []
        known_name_map: dict[str, str] = {}
        for row in rows:
            canonical_name = self._normalize_name(row["canonical_name"])
            row_names = {canonical_name}
            row_names.update(self._normalize_aliases(self._load_json_field(row, "aliases_json")))
            if normalized_names and row_names.intersection(normalized_names):
                matched_rows.append(row)
            for item in row_names:
                known_name_map[item] = canonical_name
        return matched_rows, known_name_map

    def _doc_ids_for_names(self, mapping: dict[str, list[int]], names: list[str]) -> list[int]:
        doc_ids: list[int] = []
        for name in names:
            normalized = self._normalize_name(name)
            if not normalized:
                continue
            doc_ids.extend(mapping.get(normalized, []))
        return self._merge_chapter_indexes([], doc_ids)

    def _events_for_names(self, mapping: dict[str, list[dict[str, Any]]], names: list[str]) -> list[dict[str, Any]]:
        events: list[dict[str, Any]] = []
        for name in names:
            normalized = self._normalize_name(name)
            if not normalized:
                continue
            events.extend(item for item in mapping.get(normalized, []) if isinstance(item, dict))
        return events

    def _merge_existing_rows(self, rows: list[Any]) -> dict[str, Any]:
        merged: dict[str, Any] = {
            "aliases": [],
            "personality": [],
            "occupations": [],
            "age_timeline": [],
            "abilities": [],
            "recent_activity": [],
            "relationships": [],
            "story_events": [],
            "chapter_indexes": [],
            "mentioned_doc_ids": [],
            "speaking_doc_ids": [],
            "speaking_character_status": "unknown",
            "personhood_evidence_summary": "",
            "evidence_level": "inferred",
            "first_seen_doc_id": None,
            "last_seen_doc_id": None,
            "first_seen_title_index": None,
            "last_seen_title_index": None,
            "importance_score": 0,
            "profile_version": 0,
            "created_at": "",
        }
        for row in rows:
            merged["aliases"] = self._merge_aliases(
                merged["aliases"],
                [self._normalize_name(row["canonical_name"]), *self._load_json_field(row, "aliases_json")],
                canonical_name="",
            )
            merged["personality"] = self._merge_attribute_items(
                merged["personality"],
                self._load_json_field(row, "personality_json"),
                field_type="inference",
                evidence_level="inferred",
                chapter_index=0,
                doc_ids=[],
            )
            merged["occupations"] = self._merge_attribute_items(
                merged["occupations"],
                self._load_json_field(row, "occupations_json"),
                field_type="fact",
                evidence_level="explicit",
                chapter_index=0,
                doc_ids=[],
            )
            merged["age_timeline"] = self._merge_age_timeline(
                merged["age_timeline"],
                self._load_json_field(row, "age_timeline_json"),
                chapter_index=0,
                doc_ids=[],
            )
            merged["abilities"] = self._merge_ability_items(
                merged["abilities"],
                self._load_json_field(row, "abilities_json"),
                chapter_index=0,
                doc_ids=[],
            )
            merged["recent_activity"] = self._merge_attribute_items(
                merged["recent_activity"],
                self._load_json_field(row, "recent_activity_json"),
                field_type="fact",
                evidence_level="explicit",
                chapter_index=0,
                doc_ids=[],
            )
            merged["relationships"] = self._merge_relationship_items(
                merged["relationships"],
                self._load_json_field(row, "relationships_json"),
                subject_name="",
                chapter_index=0,
                doc_ids=[],
                known_name_map={},
            )
            merged["story_events"] = self._merge_story_events(
                merged["story_events"],
                self._load_json_field(row, "story_events_json"),
                chapter_index=0,
                doc_ids=[],
            )
            merged["chapter_indexes"] = self._merge_chapter_indexes(
                merged["chapter_indexes"],
                self._load_json_field(row, "chapter_indexes_json"),
            )
            merged["mentioned_doc_ids"] = self._merge_chapter_indexes(
                merged["mentioned_doc_ids"],
                self._load_json_field(row, "mentioned_doc_ids_json"),
            )
            merged["speaking_doc_ids"] = self._merge_chapter_indexes(
                merged["speaking_doc_ids"],
                self._load_json_field(row, "speaking_doc_ids_json"),
            )
            merged["speaking_character_status"] = self._merge_speaking_character_status(
                merged["speaking_character_status"],
                update={
                    "speaking_character_status": self._row_value(row, "speaking_character_status", "unknown"),
                },
                speaking_doc_ids=merged["speaking_doc_ids"],
            )
            merged["personhood_evidence_summary"] = self._merge_personhood_evidence_summary(
                merged["personhood_evidence_summary"],
                self._row_value(row, "personhood_evidence_summary", ""),
            )
            merged["evidence_level"] = self._merge_profile_evidence_level(
                merged["evidence_level"],
                self._row_value(row, "evidence_level", "inferred"),
                speaking_character_status=merged["speaking_character_status"],
            )
            merged["first_seen_doc_id"] = self._min_int(
                merged["first_seen_doc_id"],
                row["first_seen_doc_id"],
            )
            merged["last_seen_doc_id"] = self._max_int(
                merged["last_seen_doc_id"],
                row["last_seen_doc_id"],
            )
            merged["first_seen_title_index"] = self._min_int(
                merged["first_seen_title_index"],
                row["first_seen_title_index"],
            )
            merged["last_seen_title_index"] = self._max_int(
                merged["last_seen_title_index"],
                row["last_seen_title_index"],
            )
            merged["importance_score"] = max(
                int(merged["importance_score"]),
                int(row["importance_score"] or 0),
            )
            merged["profile_version"] = max(
                int(merged["profile_version"]),
                int(row["profile_version"] or 0),
            )
            created_at = str(row["created_at"] or "").strip()
            if created_at and (not merged["created_at"] or created_at < merged["created_at"]):
                merged["created_at"] = created_at
        return merged

    def _merge_aliases(
        self,
        base_aliases: list[str],
        names: list[Any],
        *,
        canonical_name: str,
    ) -> list[str]:
        merged: list[str] = []
        seen: set[str] = set()
        for raw_name in [*base_aliases, *names]:
            name = self._normalize_name(raw_name)
            if not name or name == canonical_name or name in seen:
                continue
            seen.add(name)
            merged.append(name)
        return merged

    def _merge_chapter_indexes(self, base_indexes: list[Any], new_indexes: list[Any]) -> list[int]:
        values = set()
        for raw_value in [*base_indexes, *new_indexes]:
            value = self._safe_int(raw_value)
            if value is None:
                continue
            values.add(value)
        return sorted(values)

    def _merge_story_events(
        self,
        base_events: list[Any],
        new_events: object,
        *,
        chapter_index: int,
        doc_ids: list[int],
    ) -> list[dict[str, Any]]:
        merged: dict[str, dict[str, Any]] = {}
        for raw_event in [*base_events, *self._as_list(new_events)]:
            if not isinstance(raw_event, dict):
                continue
            label = str(raw_event.get("label") or "").strip()
            summary = str(raw_event.get("summary") or "").strip()
            event_id = str(raw_event.get("event_id") or "").strip()
            if not event_id:
                event_id = self._story_event_id(
                    chapter_indexes=self._merge_chapter_indexes([], raw_event.get("source_chapter_indexes") or [chapter_index]),
                    label=label,
                    summary=summary,
                )
            if not (event_id and (label or summary)):
                continue
            existing = merged.get(event_id, {})
            item = {
                "event_id": event_id,
                "label": label or existing.get("label") or summary[:24],
                "summary": summary if len(summary) >= len(str(existing.get("summary") or "")) else str(existing.get("summary") or ""),
                "source_chapter_indexes": self._merge_chapter_indexes(
                    self._as_list(existing.get("source_chapter_indexes")),
                    self._as_list(raw_event.get("source_chapter_indexes") or [chapter_index]),
                ),
                "source_doc_ids": self._merge_chapter_indexes(
                    self._as_list(existing.get("source_doc_ids")),
                    self._as_list(raw_event.get("source_doc_ids") or doc_ids),
                ),
                "source_doc_range": str(raw_event.get("source_doc_range") or existing.get("source_doc_range") or ""),
                "participants": self._merge_aliases(
                    self._as_list(existing.get("participants")),
                    self._as_list(raw_event.get("participants")),
                    canonical_name="",
                ),
            }
            if not item["source_doc_range"] and item["source_doc_ids"]:
                item["source_doc_range"] = self._doc_range_text(item["source_doc_ids"])
            merged[event_id] = item
        return sorted(
            merged.values(),
            key=lambda item: (
                max(item.get("source_chapter_indexes") or [0]),
                max(item.get("source_doc_ids") or [0]),
                str(item.get("event_id") or ""),
            ),
        )[-24:]

    def _story_event_id(self, *, chapter_indexes: list[int], label: str, summary: str) -> str:
        chapter = chapter_indexes[-1] if chapter_indexes else 0
        key = re.sub(r"[^\w\u4e00-\u9fff]+", "-", f"{label or summary[:24]}").strip("-").lower()
        return f"chapter-{chapter}:event-{key[:32] or 'unknown'}"

    def _doc_range_text(self, doc_ids: list[int]) -> str:
        cleaned = self._merge_chapter_indexes([], doc_ids)
        if not cleaned:
            return ""
        if len(cleaned) == 1:
            return str(cleaned[0])
        return f"{cleaned[0]}-{cleaned[-1]}"

    def _merge_attribute_items(
        self,
        base_items: list[Any],
        new_items: object,
        *,
        field_type: str,
        evidence_level: str,
        chapter_index: int,
        doc_ids: list[int],
    ) -> list[dict[str, Any]]:
        merged: list[dict[str, Any]] = []
        by_key: dict[str, dict[str, Any]] = {}
        for raw_item in [*base_items, *self._as_list(new_items)]:
            item = self._normalize_attribute_item(
                raw_item,
                field_type=field_type,
                evidence_level=evidence_level,
                chapter_index=chapter_index,
                doc_ids=doc_ids,
            )
            if item is None:
                continue
            key = item["value"]
            existing = by_key.get(key)
            if existing is None:
                by_key[key] = item
                merged.append(item)
                continue
            self._merge_sources(existing, item)
        return merged

    def _merge_ability_items(
        self,
        base_items: list[Any],
        new_items: object,
        *,
        chapter_index: int,
        doc_ids: list[int],
    ) -> list[dict[str, Any]]:
        merged: list[dict[str, Any]] = []
        by_key: dict[str, dict[str, Any]] = {}
        for raw_item in [*base_items, *self._as_list(new_items)]:
            item = self._normalize_ability_item(
                raw_item,
                chapter_index=chapter_index,
                doc_ids=doc_ids,
            )
            if item is None:
                continue
            key = f"{item['type']}::{item['name']}"
            existing = by_key.get(key)
            if existing is None:
                by_key[key] = item
                merged.append(item)
                continue
            if len(item["summary"]) > len(existing["summary"]):
                existing["summary"] = item["summary"]
            self._merge_sources(existing, item)
        return merged

    def _merge_age_timeline(
        self,
        base_items: list[Any],
        new_items: object,
        *,
        chapter_index: int,
        doc_ids: list[int],
    ) -> list[dict[str, Any]]:
        merged: list[dict[str, Any]] = []
        by_key: dict[str, dict[str, Any]] = {}
        for raw_item in [*base_items, *self._as_list(new_items)]:
            item = self._normalize_age_item(
                raw_item,
                chapter_index=chapter_index,
                doc_ids=doc_ids,
            )
            if item is None:
                continue
            key = f"{item['label']}::{item['chapter_range']}"
            existing = by_key.get(key)
            if existing is None:
                by_key[key] = item
                merged.append(item)
                continue
            if len(item["reason"]) > len(existing["reason"]):
                existing["reason"] = item["reason"]
            self._merge_sources(existing, item)
        return merged

    def _merge_relationship_items(
        self,
        base_items: list[Any],
        new_items: object,
        *,
        subject_name: str,
        chapter_index: int,
        doc_ids: list[int],
        known_name_map: dict[str, str],
    ) -> list[dict[str, Any]]:
        merged: list[dict[str, Any]] = []
        by_key: dict[str, dict[str, Any]] = {}
        for raw_item in [*base_items, *self._as_list(new_items)]:
            item = self._normalize_relationship_item(
                raw_item,
                subject_name=subject_name,
                chapter_index=chapter_index,
                doc_ids=doc_ids,
                known_name_map=known_name_map,
            )
            if item is None:
                continue
            key = item["target_name"]
            existing = by_key.get(key)
            if existing is None:
                by_key[key] = item
                merged.append(item)
                continue
            by_key[key] = self._resolve_relationship_conflict(existing, item)
            index = merged.index(existing)
            merged[index] = by_key[key]
        return merged

    def _lightweight_recent_activity_items(self, update: dict[str, object]) -> list[object]:
        items: list[object] = []
        for field_name in ("recent_activity", "activity_or_state_evidence"):
            value = update.get(field_name)
            if isinstance(value, list):
                items.extend(value)
                continue
            if value:
                items.append(value)
        return items

    def _relationship_items_from_lightweight_evidence(
        self,
        *,
        subject_name: str,
        relationship_evidence: object,
        chapter_index: int,
    ) -> list[dict[str, Any]]:
        evidence = self._normalize_text(relationship_evidence)
        if not evidence or not self._is_fact_like_text(evidence):
            return []
        target_names = self._extract_relationship_targets(evidence=evidence, subject_name=subject_name)
        return [
            {
                "target_name": target_name,
                "relation_type": "互动",
                "sentiment_state": "",
                "status_summary": evidence,
                "field_type": "fact",
                "evidence_level": "explicit",
                "last_updated_chapter_index": chapter_index,
            }
            for target_name in target_names
        ]

    def _extract_relationship_targets(self, *, evidence: str, subject_name: str) -> list[str]:
        names: list[str] = []
        for token in re.findall(r"(?:与|和|跟|对|向)([\u4e00-\u9fffA-Za-z·]{2,12})", evidence):
            normalized = self._normalize_name(token)
            if normalized and normalized != subject_name and normalized not in names:
                names.append(normalized)
        return names[:4]

    def _merge_speaking_character_status(
        self,
        current_status: object,
        *,
        update: dict[str, object],
        speaking_doc_ids: list[int],
    ) -> str:
        current = self._normalize_speaking_character_status(current_status)
        incoming = self._normalize_speaking_character_status(update.get("speaking_character_status"))
        if bool(update.get("is_speaking_character")) or self._normalize_text(update.get("speaking_evidence")):
            incoming = "confirmed_speaking"
        elif speaking_doc_ids:
            incoming = "confirmed_speaking"
        elif self._normalize_text(update.get("personhood_evidence_summary") or update.get("personhood_evidence")):
            incoming = "personhood_supported"
        return max([current, incoming], key=self._speaking_status_rank)

    def _normalize_speaking_character_status(self, status: object) -> str:
        normalized = self._normalize_text(status).lower()
        aliases = {
            "speaking": "confirmed_speaking",
            "is_speaking": "confirmed_speaking",
            "true": "confirmed_speaking",
            "personhood": "personhood_supported",
            "supported": "personhood_supported",
            "mentioned": "mentioned_only",
            "": "unknown",
        }
        normalized = aliases.get(normalized, normalized)
        if normalized not in {"unknown", "mentioned_only", "personhood_supported", "confirmed_speaking"}:
            return "unknown"
        return normalized

    def _speaking_status_rank(self, status: str) -> int:
        return {
            "unknown": 0,
            "mentioned_only": 1,
            "personhood_supported": 2,
            "confirmed_speaking": 3,
        }.get(status, 0)

    def _merge_personhood_evidence_summary(self, current_summary: object, candidate_summary: object) -> str:
        current = self._normalize_text(current_summary)
        candidate = self._normalize_text(candidate_summary)
        if not self._is_fact_like_text(candidate):
            candidate = ""
        if not current:
            return candidate
        if not candidate or candidate in current:
            return current
        if current in candidate:
            return candidate
        return f"{current}；{candidate}"[:500]

    def _merge_profile_evidence_level(
        self,
        current_level: object,
        candidate_level: object,
        *,
        speaking_character_status: str,
    ) -> str:
        levels = [self._normalize_profile_evidence_level(current_level), self._normalize_profile_evidence_level(candidate_level)]
        if speaking_character_status == "confirmed_speaking":
            levels.append("explicit")
        return max(levels, key=self._evidence_rank)

    def _normalize_profile_evidence_level(self, value: object) -> str:
        normalized = self._normalize_text(value).lower()
        if normalized in {"explicit", "confirmed", "high", "strong", "原文明确"}:
            return "explicit"
        return "inferred"

    def _normalize_attribute_item(
        self,
        raw_item: object,
        *,
        field_type: str,
        evidence_level: str,
        chapter_index: int,
        doc_ids: list[int],
    ) -> dict[str, Any] | None:
        if isinstance(raw_item, dict):
            raw_value = raw_item.get("value")
            field_type = str(raw_item.get("field_type", field_type) or field_type)
            evidence_level = str(raw_item.get("evidence_level", evidence_level) or evidence_level)
            source_chapters = self._merge_chapter_indexes(
                self._as_list(raw_item.get("source_chapter_indexes")),
                [chapter_index] if chapter_index > 0 else [],
            )
            source_doc_ids = self._merge_chapter_indexes(
                self._as_list(raw_item.get("source_doc_ids")),
                doc_ids,
            )
        else:
            raw_value = raw_item
            source_chapters = [chapter_index] if chapter_index > 0 else []
            source_doc_ids = self._merge_chapter_indexes([], doc_ids)
        value = self._normalize_text(raw_value)
        if not value or not self._is_fact_like_text(value):
            return None
        return ProfileAttributeItem(
            value=value,
            field_type="fact" if field_type == "fact" else "inference",
            evidence_level="explicit" if evidence_level == "explicit" else "inferred",
            source_chapter_indexes=source_chapters,
            source_doc_ids=source_doc_ids,
        ).to_dict()

    def _normalize_ability_item(
        self,
        raw_item: object,
        *,
        chapter_index: int,
        doc_ids: list[int],
    ) -> dict[str, Any] | None:
        if not isinstance(raw_item, dict):
            return None
        ability_type = self._normalize_text(raw_item.get("type"))
        ability_name = self._normalize_text(raw_item.get("name"))
        summary = self._normalize_text(raw_item.get("summary"))
        if not ability_name or not summary or not self._is_fact_like_text(summary):
            return None
        source_chapters = self._merge_chapter_indexes(
            self._as_list(raw_item.get("source_chapter_indexes")),
            [chapter_index] if chapter_index > 0 else [],
        )
        source_doc_ids = self._merge_chapter_indexes(
            self._as_list(raw_item.get("source_doc_ids")),
            doc_ids,
        )
        return CharacterAbilityItem(
            type=ability_type,
            name=ability_name,
            summary=summary,
            field_type="fact",
            evidence_level="explicit",
            source_chapter_indexes=source_chapters,
            source_doc_ids=source_doc_ids,
        ).to_dict()

    def _normalize_age_item(
        self,
        raw_item: object,
        *,
        chapter_index: int,
        doc_ids: list[int],
    ) -> dict[str, Any] | None:
        if isinstance(raw_item, list):
            return None
        payload = raw_item if isinstance(raw_item, dict) else {"label": raw_item}
        label = self._normalize_text(payload.get("label"))
        chapter_range = self._normalize_text(payload.get("chapter_range"))
        reason = self._normalize_text(payload.get("reason"))
        if not label:
            return None
        if reason and not self._is_fact_like_text(reason):
            return None
        source_chapters = self._merge_chapter_indexes(
            self._as_list(payload.get("source_chapter_indexes")),
            [chapter_index] if chapter_index > 0 else [],
        )
        source_doc_ids = self._merge_chapter_indexes(
            self._as_list(payload.get("source_doc_ids")),
            doc_ids,
        )
        field_type = str(payload.get("field_type", "inference") or "inference")
        evidence_level = str(payload.get("evidence_level", "inferred") or "inferred")
        return CharacterAgeItem(
            label=label,
            chapter_range=chapter_range,
            reason=reason,
            field_type="fact" if field_type == "fact" else "inference",
            evidence_level="explicit" if evidence_level == "explicit" else "inferred",
            source_chapter_indexes=source_chapters,
            source_doc_ids=source_doc_ids,
        ).to_dict()

    def _normalize_relationship_item(
        self,
        raw_item: object,
        *,
        subject_name: str,
        chapter_index: int,
        doc_ids: list[int],
        known_name_map: dict[str, str],
    ) -> dict[str, Any] | None:
        if not isinstance(raw_item, dict):
            return None
        target_name = self._normalize_name(raw_item.get("target_name"))
        target_name = known_name_map.get(target_name, target_name)
        relation_type = self._normalize_text(raw_item.get("relation_type"))
        sentiment_state = self._normalize_text(raw_item.get("sentiment_state"))
        status_summary = self._normalize_text(raw_item.get("status_summary"))
        if not target_name or (subject_name and target_name == subject_name):
            return None
        if not relation_type and not sentiment_state and not status_summary:
            return None
        if status_summary and not self._is_fact_like_text(status_summary):
            return None
        source_chapters = self._merge_chapter_indexes(
            self._as_list(raw_item.get("source_chapter_indexes")),
            [chapter_index] if chapter_index > 0 else [],
        )
        source_doc_ids = self._merge_chapter_indexes(
            self._as_list(raw_item.get("source_doc_ids")),
            doc_ids,
        )
        field_type = str(raw_item.get("field_type", "fact") or "fact")
        evidence_level = str(raw_item.get("evidence_level", "explicit") or "explicit")
        return CharacterRelationshipItem(
            target_name=target_name,
            relation_type=relation_type,
            sentiment_state=sentiment_state,
            status_summary=status_summary,
            field_type="fact" if field_type == "fact" else "inference",
            evidence_level="explicit" if evidence_level == "explicit" else "inferred",
            source_chapter_indexes=source_chapters,
            source_doc_ids=source_doc_ids,
            last_updated_chapter_index=int(raw_item.get("last_updated_chapter_index") or chapter_index or 0),
        ).to_dict()

    def _resolve_relationship_conflict(
        self,
        current: dict[str, Any],
        candidate: dict[str, Any],
    ) -> dict[str, Any]:
        candidate_rank = (
            int(candidate.get("last_updated_chapter_index") or 0),
            self._evidence_rank(candidate.get("evidence_level")),
            self._completeness_score(candidate),
        )
        current_rank = (
            int(current.get("last_updated_chapter_index") or 0),
            self._evidence_rank(current.get("evidence_level")),
            self._completeness_score(current),
        )
        preferred = candidate if candidate_rank >= current_rank else current
        fallback = current if preferred is candidate else candidate
        merged = dict(fallback)
        for field_name in (
            "relation_type",
            "sentiment_state",
            "status_summary",
            "field_type",
            "evidence_level",
            "last_updated_chapter_index",
        ):
            if preferred.get(field_name) not in ("", None, []):
                merged[field_name] = preferred.get(field_name)
        merged["target_name"] = preferred.get("target_name") or fallback.get("target_name")
        self._merge_sources(merged, preferred)
        self._merge_sources(merged, fallback)
        return merged

    def _build_summary(self, *, snapshot: CharacterProfileSnapshot) -> str:
        parts = [f"# {snapshot.canonical_name}", ""]
        chapter_indexes = ", ".join(str(item) for item in snapshot.chapter_indexes)
        parts.append(f"- 相关章节：{chapter_indexes or '暂无'}")
        if snapshot.aliases:
            parts.append(f"- 别名：{', '.join(snapshot.aliases)}")
        parts.append(f"- 证据级别：{snapshot.evidence_level}")
        parts.append(f"- 发言状态：{snapshot.speaking_character_status}")
        if snapshot.personhood_evidence_summary:
            parts.append(f"- 人物性证据：{snapshot.personhood_evidence_summary}")
        parts.extend(["", "## 基本属性/关系/能力"])
        fact_lines: list[str] = []
        fact_lines.extend(self._format_attribute_lines("职业", snapshot.occupations, limit=3))
        fact_lines.extend(self._format_ability_lines(snapshot.abilities, limit=3))
        fact_lines.extend(self._format_relationship_lines(snapshot.relationships, limit=4))
        fact_lines.extend(self._format_attribute_lines("性格", snapshot.personality, limit=4))
        fact_lines.extend(self._format_age_lines(snapshot.age_timeline, limit=3))
        if fact_lines:
            parts.extend(fact_lines)
        else:
            parts.append("- 暂无稳定基础属性。")
        parts.extend(["", "## 剧情时间线"])
        event_lines = self._format_story_event_lines(snapshot.story_events, limit=8)
        if event_lines:
            parts.extend(event_lines)
        elif snapshot.recent_activity:
            parts.extend(self._format_attribute_lines("近期活动", snapshot.recent_activity, limit=4))
        else:
            parts.append("- 暂无可索引剧情事件。")
        return "\n".join(parts).strip() + "\n"

    def _append_document_presence_summary(
        self,
        summary_md: str,
        *,
        mentioned_doc_ids: list[int],
        speaking_doc_ids: list[int],
    ) -> str:
        mentioned = ", ".join(str(item) for item in mentioned_doc_ids[-12:])
        speaking = ", ".join(str(item) for item in speaking_doc_ids[-12:])
        lines = [
            summary_md.rstrip(),
            "",
            "## 出场/发言证据",
            f"- 出现 documents：{mentioned or '暂无'}",
            f"- 发言 documents：{speaking or '暂无'}",
        ]
        if mentioned_doc_ids and not speaking_doc_ids and len(mentioned_doc_ids) <= 2:
            lines.append("- 置信提示：低频且无发言记录，后续应复核是否为误识别人名。")
        return "\n".join(lines).strip() + "\n"

    def _format_attribute_lines(
        self,
        label: str,
        items: list[ProfileAttributeItem],
        *,
        limit: int,
    ) -> list[str]:
        lines = []
        for item in self._sort_items_by_recency(items)[:limit]:
            lines.append(
                f"- {label} [{item.evidence_level}]：{item.value}{self._format_source_suffix(item.source_chapter_indexes)}"
            )
        return lines

    def _format_ability_lines(
        self,
        items: list[CharacterAbilityItem],
        *,
        limit: int,
    ) -> list[str]:
        lines = []
        for item in self._sort_items_by_recency(items)[:limit]:
            ability_name = f"{item.type}/{item.name}" if item.type else item.name
            lines.append(
                f"- 能力 [{item.evidence_level}]：{ability_name} - {item.summary}"
                f"{self._format_source_suffix(item.source_chapter_indexes)}"
            )
        return lines

    def _format_age_lines(
        self,
        items: list[CharacterAgeItem],
        *,
        limit: int,
    ) -> list[str]:
        lines = []
        for item in self._sort_items_by_recency(items)[:limit]:
            detail = item.label
            if item.chapter_range:
                detail = f"{detail}（{item.chapter_range}）"
            if item.reason:
                detail = f"{detail} - {item.reason}"
            lines.append(
                f"- 年龄/阶段 [{item.evidence_level}]：{detail}"
                f"{self._format_source_suffix(item.source_chapter_indexes)}"
            )
        return lines

    def _format_relationship_lines(
        self,
        items: list[CharacterRelationshipItem],
        *,
        limit: int,
    ) -> list[str]:
        lines = []
        ordered = sorted(
            items,
            key=lambda item: (
                item.last_updated_chapter_index,
                max(item.source_chapter_indexes or [0]),
                item.target_name,
            ),
            reverse=True,
        )
        for item in ordered[:limit]:
            fragments = [item.target_name]
            if item.relation_type:
                fragments.append(item.relation_type)
            if item.sentiment_state:
                fragments.append(item.sentiment_state)
            detail = " | ".join(fragments)
            if item.status_summary:
                detail = f"{detail} - {item.status_summary}"
            lines.append(
                f"- 关系 [{item.evidence_level}]：{detail}"
                f"{self._format_source_suffix(item.source_chapter_indexes)}"
            )
        return lines

    def _sort_items_by_recency(self, items: list[Any]) -> list[Any]:
        return sorted(
            items,
            key=lambda item: (
                max(getattr(item, "source_chapter_indexes", []) or [0]),
                getattr(item, "value", getattr(item, "name", "")),
            ),
            reverse=True,
        )

    def _format_source_suffix(self, chapter_indexes: list[int]) -> str:
        if not chapter_indexes:
            return ""
        recent = ", ".join(str(item) for item in chapter_indexes[-3:])
        return f"（章节：{recent}）"

    def _format_story_event_lines(self, events: list[CharacterStoryEventItem], *, limit: int) -> list[str]:
        lines: list[str] = []
        for item in sorted(
            events,
            key=lambda event: (
                max(event.source_chapter_indexes or [0]),
                max(event.source_doc_ids or [0]),
                event.event_id,
            ),
        )[-limit:]:
            chapters = ",".join(str(value) for value in item.source_chapter_indexes) or "?"
            docs = item.source_doc_range or self._doc_range_text(item.source_doc_ids) or "?"
            label = item.label or item.event_id
            summary = item.summary or label
            lines.append(f"- [{item.event_id}] {label}：{summary}（章节：{chapters}；documents：{docs}）")
        return lines

    def _merge_sources(self, target: dict[str, Any], source: dict[str, Any]) -> None:
        target["source_chapter_indexes"] = self._merge_chapter_indexes(
            self._as_list(target.get("source_chapter_indexes")),
            self._as_list(source.get("source_chapter_indexes")),
        )
        target["source_doc_ids"] = self._merge_chapter_indexes(
            self._as_list(target.get("source_doc_ids")),
            self._as_list(source.get("source_doc_ids")),
        )

    def _choose_canonical_name(self, names: list[Any]) -> str:
        normalized = [name for name in (self._normalize_name(item) for item in names) if name]
        if not normalized:
            return ""
        return min(normalized, key=self._canonical_name_sort_key)

    def _canonical_name_sort_key(self, name: str) -> tuple[int, int, str]:
        alias_penalty = 1 if self._looks_like_alias(name) else 0
        return (alias_penalty, -len(name), name)

    def _looks_like_alias(self, name: str) -> bool:
        return name.startswith(ALIAS_PREFIXES) or name.endswith(ALIAS_SUFFIXES)

    def _normalize_name(self, raw_value: object) -> str:
        text = self._normalize_text(raw_value)
        return text

    def _normalize_aliases(self, raw_aliases: object) -> list[str]:
        aliases: list[str] = []
        seen: set[str] = set()
        for raw_value in self._as_list(raw_aliases):
            alias = self._normalize_name(raw_value)
            if not alias or alias in seen:
                continue
            seen.add(alias)
            aliases.append(alias)
        return aliases

    def _normalize_text(self, raw_value: object) -> str:
        if raw_value is None:
            return ""
        text = WHITESPACE_RE.sub(" ", str(raw_value)).strip()
        return text

    def _is_fact_like_text(self, text: str) -> bool:
        if not text:
            return False
        if any(keyword in text for keyword in STYLE_META_KEYWORDS):
            return False
        if any(pattern in text for pattern in STYLE_META_PATTERNS) and any(
            keyword in text for keyword in ("表现", "刻画", "渲染", "制造", "强化", "暗示", "突出")
        ):
            return False
        return True

    def _evidence_rank(self, evidence_level: object) -> int:
        return 1 if str(evidence_level) == "explicit" else 0

    def _completeness_score(self, item: dict[str, Any]) -> int:
        return sum(
            1
            for field_name in ("relation_type", "sentiment_state", "status_summary")
            if str(item.get(field_name, "")).strip()
        )

    def _load_json_field(self, row: Any, field_name: str) -> list[Any]:
        if hasattr(row, "keys") and field_name not in row.keys():
            return []
        raw_value = row[field_name]
        if not raw_value:
            return []
        return list(json.loads(raw_value))

    def _row_value(self, row: Any, field_name: str, default: object = "") -> object:
        if hasattr(row, "keys") and field_name not in row.keys():
            return default
        value = row[field_name]
        return default if value is None else value

    def _as_list(self, value: object) -> list[Any]:
        if value is None:
            return []
        if isinstance(value, list):
            return value
        return [value]

    def _min_int(self, current: object, candidate: object) -> int | None:
        current_value = self._safe_int(current)
        candidate_value = self._safe_int(candidate)
        if current_value is None:
            return candidate_value
        if candidate_value is None:
            return current_value
        return min(current_value, candidate_value)

    def _max_int(self, current: object, candidate: object) -> int | None:
        current_value = self._safe_int(current)
        candidate_value = self._safe_int(candidate)
        if current_value is None:
            return candidate_value
        if candidate_value is None:
            return current_value
        return max(current_value, candidate_value)

    def _safe_int(self, value: object) -> int | None:
        try:
            if value is None or value == "":
                return None
            return int(str(value).strip())
        except (TypeError, ValueError):
            return None

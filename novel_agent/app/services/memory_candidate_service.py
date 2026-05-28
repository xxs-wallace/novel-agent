from __future__ import annotations

import re
from typing import Any

from .character_mention_service import CHARACTER_NAME_STOPWORDS, CharacterMentionService


LOW_CONFIDENCE_THRESHOLD = 0.45
LOW_VALUE_CANDIDATE_TYPES = {
    "abstract",
    "concept",
    "low_confidence",
    "non_person",
    "object",
    "place",
    "scene",
    "setting",
    "weak_cooccurrence",
}
MODEL_NAME_STOPWORDS = {
    *CHARACTER_NAME_STOPWORDS,
    "身体",
    "房门",
    "邮件",
    "照片",
    "电脑",
    "手机",
    "本章",
    "章节",
    "剧情",
    "现实",
    "幻想",
}
ROLE_CHARACTER_NAMES = {
    "主角",
    "男主",
    "女主",
    "丈夫",
    "妻子",
    "未婚妻",
    "表弟",
    "表姐",
    "哥哥",
    "姐姐",
    "弟弟",
    "妹妹",
    "父亲",
    "母亲",
}
NICKNAME_PREFIXES = ("小", "老", "阿")


class MemoryCandidateService:
    def __init__(self, *, character_mention_service: CharacterMentionService | None = None) -> None:
        self.character_mention_service = character_mention_service or CharacterMentionService()

    def build_prompt_input(
        self,
        *,
        prompt_input: dict[str, Any],
        summary_payload: dict[str, Any],
        evidence_payload: dict[str, Any],
    ) -> dict[str, Any]:
        return {
            "book_id": prompt_input.get("book_id"),
            "current_title_index": prompt_input.get("current_title_index"),
            "chapter_title": prompt_input.get("chapter_title"),
            "chapter_summary": {
                "chapter_summary_md": summary_payload.get("chapter_summary_md", ""),
                "chapter_summary_short": summary_payload.get("chapter_summary_short", ""),
                "importance_score": summary_payload.get("importance_score", 0),
                "importance_reason": summary_payload.get("importance_reason", ""),
                "related_chapters": summary_payload.get("related_chapters", []),
                "chapter_summaries": summary_payload.get("chapter_summaries", []),
            },
            "character_evidence_batches": self._normalize_evidence_batches(evidence_payload),
            "story_outline_md": prompt_input.get("story_outline_md", ""),
            "world_summary_md": prompt_input.get("world_summary_md", ""),
            "character_profiles": prompt_input.get("character_profiles", []),
            "candidate_policy": {
                "low_confidence_threshold": LOW_CONFIDENCE_THRESHOLD,
                "drop_low_value_candidate_types": sorted(LOW_VALUE_CANDIDATE_TYPES),
                "memory_update_agent_contract": "只消费候选事实，不依赖 Character Evidence prompt 或原文 offset 细节。",
            },
        }

    def build_character_reduce_inputs(
        self,
        *,
        prompt_input: dict[str, Any],
        summary_payload: dict[str, Any],
        evidence_payload: dict[str, Any],
        current_outline_segment: dict[str, Any] | None = None,
    ) -> list[dict[str, Any]]:
        grouped = self._group_character_evidence(evidence_payload)
        if not grouped:
            return []
        outline_segment = dict(current_outline_segment or {})
        reduce_outline_segment = self._character_reduce_outline_segment(outline_segment)
        chapter_summary = self._character_reduce_summary(
            summary_payload,
            current_outline_segment=reduce_outline_segment,
        )
        result: list[dict[str, Any]] = []
        for identity_key in sorted(grouped):
            evidence_items = sorted(grouped[identity_key], key=self._evidence_sort_key)
            canonical_name = str(evidence_items[0].get("canonical_name", "")).strip()
            character_id = str(evidence_items[0].get("character_id", "") or "").strip()
            existing_profile = self._character_reduce_existing_profile(
                prompt_input.get("character_profiles", []),
                canonical_name=canonical_name,
                character_id=character_id,
            )
            detail_policy = self._character_reduce_detail_policy(
                evidence_items=evidence_items,
                existing_profile=existing_profile,
            )
            result.append(
                {
                    "book_id": prompt_input.get("book_id"),
                    "character_id": character_id,
                    "canonical_name": canonical_name,
                    "existing_profile": existing_profile,
                    "ordered_character_evidence": evidence_items,
                    "chapter_summary": chapter_summary,
                    "chapter_context_text": chapter_summary["chapter_context_text"],
                    "current_outline_segment": reduce_outline_segment,
                    "reduce_policy": {
                        "same_character_must_be_reduced_serially": True,
                        "relationships_are_merged_inside_character_reduce": True,
                        "character_id_is_primary_identity_when_present": True,
                        "personhood_and_relationships_must_be_deduplicated": True,
                        "key_experiences_must_be_target_character_scoped": True,
                        "preserve_outline_segment_id": True,
                        "background_roles_should_be_brief_or_index_only": True,
                        "detail_level": detail_policy["detail_level"],
                        "detail_reason": detail_policy["reason"],
                        "non_core_characters_get_index_only_experience": True,
                        "relationships_for_non_core_characters_must_be_short": True,
                        "drop_low_value_candidate_types": sorted(LOW_VALUE_CANDIDATE_TYPES),
                        "low_confidence_threshold": LOW_CONFIDENCE_THRESHOLD,
                    },
                    "profile_update_gate": detail_policy,
                }
            )
        return result

    def build_character_reduce_fallback_output(
        self,
        *,
        reduce_input: dict[str, Any],
    ) -> dict[str, Any]:
        canonical_name = str(reduce_input.get("canonical_name", "")).strip()
        evidence_items = [item for item in reduce_input.get("ordered_character_evidence", []) if isinstance(item, dict)]
        if not canonical_name or not evidence_items:
            return {"should_update": False, "canonical_name": canonical_name, "character_update": None}
        evidence_payload = {"characters": evidence_items}
        chapter_summary = reduce_input.get("chapter_summary", {})
        summary_short = (
            str(chapter_summary.get("chapter_summary_short", "")).strip()
            if isinstance(chapter_summary, dict)
            else ""
        )
        updates = self.build_character_updates(
            summary_short=summary_short,
            evidence_payload=evidence_payload,
        )
        update = next((item for item in updates if item.get("canonical_name") == canonical_name), None)
        if update is not None and reduce_input.get("character_id"):
            update = dict(update)
            update["character_id"] = str(reduce_input.get("character_id") or "").strip()
        if update is not None:
            key_experiences = self._fallback_key_experiences_for_character(
                canonical_name=canonical_name,
                character_id=str(reduce_input.get("character_id") or "").strip(),
                reduce_input=reduce_input,
            )
            if key_experiences:
                update = dict(update)
                update["key_experiences"] = key_experiences
        return {
            "should_update": update is not None,
            "canonical_name": canonical_name,
            "character_id": str(reduce_input.get("character_id") or "").strip(),
            "character_update": update,
        }

    def build_index_only_reduce_output(
        self,
        *,
        reduce_input: dict[str, Any],
    ) -> dict[str, Any]:
        canonical_name = str(reduce_input.get("canonical_name", "")).strip()
        evidence_items = [item for item in reduce_input.get("ordered_character_evidence", []) if isinstance(item, dict)]
        if not canonical_name or not evidence_items:
            return {"should_update": False, "canonical_name": canonical_name, "character_update": None}
        character_id = str(reduce_input.get("character_id") or "").strip()
        aliases: list[str] = []
        for item in evidence_items:
            for alias in item.get("aliases", []) if isinstance(item.get("aliases"), list) else []:
                cleaned = self.clean_evidence_name(alias, character=item)
                if cleaned and cleaned not in aliases:
                    aliases.append(cleaned)
        key_experiences = self._index_only_key_experiences_for_character(
            canonical_name=canonical_name,
            character_id=character_id,
            reduce_input=reduce_input,
        )
        update: dict[str, Any] = {
            "canonical_name": canonical_name,
            "character_id": character_id,
            "aliases": aliases,
            "personality": [],
            "occupations": [],
            "abilities": [],
            "relationships": [],
            "recent_activity": [],
            "key_experiences": key_experiences,
            "recent_key_experiences": key_experiences,
            "profile_update_policy": "defer_index_only",
            "profile_update_gate": reduce_input.get("profile_update_gate") or {},
            "evidence_level": "explicit" if any(item.get("confidence", 0) for item in evidence_items) else "inferred",
        }
        if any(bool(item.get("is_speaking_character")) for item in evidence_items):
            update["speaking_character_status"] = "confirmed_speaking"
        return {
            "should_update": True,
            "canonical_name": canonical_name,
            "character_id": character_id,
            "character_update": update,
            "key_experiences": key_experiences,
            "profile_update_gate": reduce_input.get("profile_update_gate") or {},
            "skipped_model_reduce": True,
        }

    def normalize_character_reduce_outputs(self, outputs: list[dict[str, Any]]) -> dict[str, Any]:
        updates: list[dict[str, Any]] = []
        seen: set[str] = set()
        for output in outputs:
            if not isinstance(output, dict) or output.get("should_update") is False:
                continue
            update = output.get("character_update")
            if not isinstance(update, dict):
                continue
            canonical_name = self.clean_evidence_name(
                update.get("canonical_name") or output.get("canonical_name"),
                character=update,
            )
            if not canonical_name:
                continue
            if canonical_name in seen:
                continue
            seen.add(canonical_name)
            normalized = dict(update)
            normalized["canonical_name"] = canonical_name
            if output.get("character_id") and not normalized.get("character_id"):
                normalized["character_id"] = str(output.get("character_id") or "").strip()
            if isinstance(output.get("key_experiences"), list) and not isinstance(normalized.get("key_experiences"), list):
                normalized["key_experiences"] = output["key_experiences"]
            updates.append(normalized)
        return {"character_updates": updates}

    def _fallback_key_experiences_for_character(
        self,
        *,
        canonical_name: str,
        character_id: str,
        reduce_input: dict[str, Any],
    ) -> list[dict[str, Any]]:
        outline_segment = reduce_input.get("current_outline_segment")
        if not isinstance(outline_segment, dict):
            return []
        outline_segment_id = str(outline_segment.get("outline_segment_id") or "").strip()
        summary = str(outline_segment.get("outline_segment") or "").strip()
        if not outline_segment_id or not summary:
            return []
        evidence_items = [item for item in reduce_input.get("ordered_character_evidence", []) if isinstance(item, dict)]
        has_speaking = any(bool(item.get("is_speaking_character")) for item in evidence_items)
        has_action = any(str(item.get("activity_or_state_evidence") or "").strip() for item in evidence_items)
        role = "speaker_source" if has_speaking else "supporting" if has_action else "background"
        compression_level = "medium" if role in {"speaker_source", "supporting"} else "brief"
        character_suffix = character_id or re.sub(r"[^\w\u4e00-\u9fff]+", "-", canonical_name).strip("-").lower()
        return [
            {
                "experience_id": f"char-exp:{character_suffix}:{outline_segment_id}",
                "outline_segment_id": outline_segment_id,
                "role_in_segment": role,
                "compression_level": compression_level,
                "label": str(outline_segment.get("chapter_line") or "").strip() or summary[:24],
                "summary": summary if role != "background" else f"{canonical_name}在该剧情段中作为背景或弱相关人物出现。",
                "source_chapter_indexes": self._safe_int_list(outline_segment.get("source_title_indexes")),
                "source_doc_ids": self._safe_int_list(outline_segment.get("source_doc_ids")),
                "source_doc_range": str(outline_segment.get("source_doc_range") or "").strip(),
                "participants": [canonical_name],
                "status": str(outline_segment.get("status") or "provisional"),
                "generation_note": "dry_run_fallback",
            }
        ]

    def _index_only_key_experiences_for_character(
        self,
        *,
        canonical_name: str,
        character_id: str,
        reduce_input: dict[str, Any],
    ) -> list[dict[str, Any]]:
        outline_segment = reduce_input.get("current_outline_segment")
        if not isinstance(outline_segment, dict):
            return []
        outline_segment_id = str(outline_segment.get("outline_segment_id") or "").strip()
        if not outline_segment_id:
            return []
        evidence_items = [item for item in reduce_input.get("ordered_character_evidence", []) if isinstance(item, dict)]
        source_doc_ids = sorted(
            {
                doc_id
                for item in evidence_items
                for doc_id in self._safe_int_list(item.get("source_doc_ids"))
            }
        )
        source_title_indexes = sorted(
            {
                title_index
                for item in evidence_items
                for title_index in self._safe_int_list(item.get("source_title_indexes"))
            }
        )
        has_speaking = any(bool(item.get("is_speaking_character")) for item in evidence_items)
        has_action = any(str(item.get("activity_or_state_evidence") or "").strip() for item in evidence_items)
        has_relationship = any(str(item.get("relationship_evidence") or "").strip() for item in evidence_items)
        role = "speaker_source" if has_speaking else "supporting" if has_action or has_relationship else "background"
        evidence_summary = self._first_evidence_summary(evidence_items)
        if not evidence_summary:
            evidence_summary = f"{canonical_name}在该剧情段中作为背景或弱相关人物出现。"
        character_suffix = character_id or re.sub(r"[^\w\u4e00-\u9fff]+", "-", canonical_name).strip("-").lower()
        return [
            {
                "experience_id": f"char-exp:{character_suffix}:{outline_segment_id}",
                "outline_segment_id": outline_segment_id,
                "role_in_segment": role,
                "compression_level": "index_only",
                "label": str(outline_segment.get("chapter_line") or "").strip() or canonical_name,
                "summary": evidence_summary,
                "source_chapter_indexes": source_title_indexes or self._safe_int_list(outline_segment.get("source_title_indexes")),
                "source_doc_ids": source_doc_ids or self._safe_int_list(outline_segment.get("source_doc_ids")),
                "source_doc_range": str(outline_segment.get("source_doc_range") or "").strip(),
                "participants": [canonical_name],
                "status": str(outline_segment.get("status") or "provisional"),
                "generation_note": "index_only_deferred_from_character_evidence",
            }
        ]

    @staticmethod
    def _first_evidence_summary(evidence_items: list[dict[str, Any]]) -> str:
        for field_name in ("activity_or_state_evidence", "relationship_evidence", "personhood_evidence", "speaking_evidence"):
            for item in evidence_items:
                text = str(item.get(field_name) or "").strip()
                if text:
                    return text
        return ""

    def build_global_memory_input(
        self,
        *,
        prompt_input: dict[str, Any],
        summary_payload: dict[str, Any],
        world_evidence_payload: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        return {
            "book_id": prompt_input.get("book_id"),
            "current_title_index": prompt_input.get("current_title_index"),
            "chapter_title": prompt_input.get("chapter_title"),
            "chapter_summary": self._global_summary_payload(summary_payload),
            "world_evidence": self._normalize_world_evidence_payload(world_evidence_payload or {}),
            "story_outline_md": prompt_input.get("story_outline_md", ""),
            "world_summary_md": prompt_input.get("world_summary_md", ""),
            "global_memory_policy": {
                "do_not_read_full_documents": True,
                "do_not_emit_character_updates": True,
                "allowed_world_sections": [
                    "世界类型",
                    "时代背景",
                    "能力体系",
                    "超自然要素",
                    "阵营势力",
                    "核心禁忌与规则",
                ],
            },
        }

    def build_global_memory_fallback_output(
        self,
        *,
        summary_payload: dict[str, Any],
        world_evidence_payload: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        candidates = [
            *self._normalize_world_candidates(summary_payload.get("world_evidence_candidates", [])),
            *self._normalize_world_candidates((world_evidence_payload or {}).get("world_evidence_candidates", [])),
        ]
        changes = []
        seen: set[tuple[str, str]] = set()
        for candidate in candidates:
            confidence = self._safe_float(candidate.get("confidence"), default=0.0)
            section = str(candidate.get("section", "")).strip()
            summary = str(candidate.get("summary", "")).strip()
            if confidence < 0.5 or not section or not summary:
                continue
            key = (section, summary)
            if key in seen:
                continue
            seen.add(key)
            changes.append(
                {
                    "section": section,
                    "summary": summary,
                    "evidence": str(candidate.get("evidence_hint", "")).strip() or summary,
                }
            )
        return {"world_update": {"should_update": bool(changes), "changes": changes}}

    def build_fallback_output(
        self,
        *,
        chapter_title: str,
        document_title_index: int,
        summary_payload: dict[str, Any],
        evidence_payload: dict[str, Any],
    ) -> dict[str, Any]:
        summary_short = str(summary_payload.get("chapter_summary_short", "")).strip()
        return {
            "character_updates": self.build_character_updates(
                summary_short=summary_short,
                evidence_payload=evidence_payload,
            ),
            "world_update": {"should_update": False, "changes": []},
            "outline_update": {
                "chapter_line": f"[{document_title_index}] {chapter_title}: {summary_short}",
            },
        }

    def build_character_updates(
        self,
        *,
        summary_short: str,
        evidence_payload: dict[str, Any],
    ) -> list[dict[str, Any]]:
        updates: list[dict[str, Any]] = []
        seen: set[str] = set()
        for character in self._iter_character_evidence(evidence_payload):
            canonical_name = self.clean_evidence_name(character.get("canonical_name"), character=character)
            if not canonical_name:
                continue
            if canonical_name in seen or not self._should_keep_character(character):
                continue
            seen.add(canonical_name)
            activity_evidence = str(character.get("activity_or_state_evidence", "")).strip()
            relationship_evidence = str(character.get("relationship_evidence", "")).strip()
            recent_activity = activity_evidence or relationship_evidence or summary_short
            updates.append(
                {
                    "character_id": str(character.get("character_id") or "").strip(),
                    "canonical_name": canonical_name,
                    "aliases": self._clean_aliases(character.get("aliases", [])),
                    "personality": [],
                    "occupations": [],
                    "recent_activity": recent_activity,
                    "relationships": self._relationship_updates_from_evidence(
                        canonical_name=canonical_name,
                        relationship_evidence=relationship_evidence,
                    ),
                    "evidence_level": self._evidence_level(character),
                    "is_speaking_character": bool(character.get("is_speaking_character")),
                    "speaking_character_status": (
                        "confirmed_speaking" if bool(character.get("is_speaking_character")) else "personhood_supported"
                    ),
                    "speaking_evidence": str(character.get("speaking_evidence", "")).strip(),
                    "personhood_evidence_summary": str(character.get("personhood_evidence", "")).strip(),
                    "activity_or_state_evidence": activity_evidence,
                    "relationship_evidence": relationship_evidence,
                }
            )
        return updates

    def _normalize_evidence_batches(self, evidence_payload: dict[str, Any]) -> list[dict[str, Any]]:
        if isinstance(evidence_payload.get("characters"), list):
            return [
                {
                    "character_evidence_batch_id": evidence_payload.get("character_evidence_batch_id", ""),
                    "doc_ids": evidence_payload.get("doc_ids", []),
                    "document_title_indexes": evidence_payload.get("document_title_indexes", []),
                    "characters": evidence_payload.get("characters", []),
                }
            ]
        if isinstance(evidence_payload.get("character_evidence_batches"), list):
            return [item for item in evidence_payload["character_evidence_batches"] if isinstance(item, dict)]
        return [
            {
                "character_evidence_batch_id": evidence_payload.get("character_evidence_batch_id", ""),
                "characters": [],
                "legacy_document_character_mentions": evidence_payload.get("document_character_mentions", []),
            }
        ]

    def _iter_character_evidence(self, evidence_payload: dict[str, Any]):
        characters = evidence_payload.get("characters")
        if isinstance(characters, list):
            batch_doc_ids = self._safe_int_list(evidence_payload.get("doc_ids"))
            batch_title_indexes = self._safe_int_list(evidence_payload.get("document_title_indexes"))
            for item in characters:
                if isinstance(item, dict):
                    character = dict(item)
                    character.setdefault("source_doc_ids", batch_doc_ids)
                    character.setdefault("source_title_indexes", batch_title_indexes)
                    yield character
            return
        batches = evidence_payload.get("character_evidence_batches")
        if isinstance(batches, list):
            for batch in batches:
                if not isinstance(batch, dict):
                    continue
                batch_doc_ids = self._safe_int_list(batch.get("doc_ids"))
                batch_title_indexes = self._safe_int_list(batch.get("document_title_indexes"))
                for character in batch.get("characters", []):
                    if not isinstance(character, dict):
                        continue
                    item = dict(character)
                    item.setdefault("source_doc_ids", batch_doc_ids)
                    item.setdefault("source_title_indexes", batch_title_indexes)
                    yield item
            return
        for item in evidence_payload.get("document_character_mentions", []):
            if not isinstance(item, dict):
                continue
            for name in item.get("character_keywords", []):
                yield {
                    "canonical_name": name,
                    "aliases": [],
                    "is_speaking_character": name in item.get("speaking_character_keywords", []),
                    "personhood_evidence": "旧 document 级人物命中",
                    "activity_or_state_evidence": "",
                    "relationship_evidence": "",
                    "source_doc_ids": [item.get("doc_id")] if item.get("doc_id") is not None else [],
                    "source_title_indexes": [],
                    "candidate_type": "character",
                    "confidence": 0.65,
                    "uncertainty_reason": "",
                }

    def _should_keep_character(self, character: dict[str, Any]) -> bool:
        candidate_type = str(character.get("candidate_type", "")).strip().lower()
        if candidate_type in LOW_VALUE_CANDIDATE_TYPES:
            return False
        confidence = self._safe_float(character.get("confidence"), default=0.0)
        has_personhood = bool(str(character.get("personhood_evidence", "")).strip())
        has_action = bool(str(character.get("activity_or_state_evidence", "")).strip())
        has_relationship = bool(str(character.get("relationship_evidence", "")).strip())
        is_speaking = bool(character.get("is_speaking_character"))
        if confidence < LOW_CONFIDENCE_THRESHOLD and not (is_speaking and has_personhood):
            return False
        return is_speaking or has_personhood or has_action or has_relationship

    def _evidence_level(self, character: dict[str, Any]) -> str:
        confidence = self._safe_float(character.get("confidence"), default=0.0)
        if bool(character.get("is_speaking_character")) and confidence >= 0.6:
            return "explicit"
        if confidence >= 0.75:
            return "explicit"
        if confidence >= LOW_CONFIDENCE_THRESHOLD:
            return "inferred"
        return "weak"

    def _safe_float(self, value: object, *, default: float) -> float:
        try:
            return float(value)  # type: ignore[arg-type]
        except (TypeError, ValueError):
            return default

    def _clean_aliases(self, aliases: object) -> list[str]:
        if not isinstance(aliases, list):
            return []
        return self.character_mention_service.clean_names(aliases)

    def _relationship_updates_from_evidence(
        self,
        *,
        canonical_name: str,
        relationship_evidence: str,
    ) -> list[dict[str, str]]:
        _ = canonical_name, relationship_evidence
        return []

    def _group_character_evidence(self, evidence_payload: dict[str, Any]) -> dict[str, list[dict[str, Any]]]:
        grouped: dict[str, list[dict[str, Any]]] = {}
        for character in self._iter_character_evidence(evidence_payload):
            canonical_name = self.clean_evidence_name(character.get("canonical_name"), character=character)
            if not canonical_name or not self._should_keep_character(character):
                continue
            item = dict(character)
            item["canonical_name"] = canonical_name
            item["character_id"] = str(item.get("character_id") or "").strip()
            item["source_doc_ids"] = self._safe_int_list(item.get("source_doc_ids"))
            item["source_title_indexes"] = self._safe_int_list(item.get("source_title_indexes"))
            grouped.setdefault(self._character_identity_key(item), []).append(item)
        return grouped

    def _character_identity_key(self, character: dict[str, Any]) -> str:
        character_id = str(character.get("character_id") or "").strip()
        if character_id:
            return f"id:{character_id}"
        return f"name:{str(character.get('canonical_name', '')).strip()}"

    def clean_evidence_name(self, raw_name: object, *, character: dict[str, Any] | None = None) -> str:
        name = str(raw_name or "").strip()
        cleaned = self.character_mention_service.clean_names([name])
        if cleaned:
            return cleaned[0]
        if self._is_supported_model_character_name(name=name, character=character or {}):
            return name
        return ""

    def _is_supported_model_character_name(self, *, name: str, character: dict[str, Any]) -> bool:
        if not name or name in MODEL_NAME_STOPWORDS:
            return False
        if len(name) > 12:
            return False
        if not re.fullmatch(r"[\u4e00-\u9fffA-Za-z·]{1,12}", name):
            return False
        if name in ROLE_CHARACTER_NAMES:
            return True
        if len(name) <= 4 and name.startswith(NICKNAME_PREFIXES):
            return True
        if len(name) == 1 and re.fullmatch(r"[\u4e00-\u9fff]", name):
            return self._safe_float(character.get("confidence"), default=0.0) >= 0.6 and self._model_evidence_mentions_name(
                name=name,
                character=character,
            )
        if 2 <= len(name) <= 4 and re.fullmatch(r"[\u4e00-\u9fff]{2,4}", name):
            return self._model_evidence_mentions_name(name=name, character=character)
        return False

    @staticmethod
    def _model_evidence_mentions_name(*, name: str, character: dict[str, Any]) -> bool:
        evidence_fields = (
            "speaking_evidence",
            "personhood_evidence",
            "activity_or_state_evidence",
            "relationship_evidence",
        )
        aliases = character.get("aliases", [])
        terms = [name]
        if isinstance(aliases, list):
            terms.extend(str(alias).strip() for alias in aliases if str(alias).strip())
        return any(term in str(character.get(field) or "") for term in terms for field in evidence_fields)

    def _evidence_sort_key(self, item: dict[str, Any]) -> tuple[int, int, str]:
        doc_ids = self._safe_int_list(item.get("source_doc_ids"))
        title_indexes = self._safe_int_list(item.get("source_title_indexes"))
        return (
            min(doc_ids) if doc_ids else 10**12,
            min(title_indexes) if title_indexes else 10**12,
            str(item.get("canonical_name", "")),
        )

    def _find_existing_profile(
        self,
        profiles: object,
        *,
        canonical_name: str,
        character_id: str = "",
    ) -> dict[str, Any] | None:
        if not isinstance(profiles, list):
            return None
        for profile in profiles:
            if not isinstance(profile, dict):
                continue
            profile_id = str(profile.get("character_id") or "").strip()
            if character_id and profile_id == character_id:
                return profile
            profile_name = str(profile.get("canonical_name", "")).strip()
            aliases = profile.get("aliases", [])
            alias_values = aliases if isinstance(aliases, list) else []
            if profile_name == canonical_name or canonical_name in alias_values:
                return profile
        return None

    def _character_reduce_existing_profile(
        self,
        profiles: object,
        *,
        canonical_name: str,
        character_id: str = "",
    ) -> dict[str, Any] | None:
        profile = self._find_existing_profile(
            profiles,
            canonical_name=canonical_name,
            character_id=character_id,
        )
        if not isinstance(profile, dict):
            return None
        brief = profile.get("profile_brief")
        existing_profile = {
            "character_id": profile.get("character_id"),
            "canonical_name": profile.get("canonical_name"),
            "aliases": profile.get("aliases", []),
            "profile_brief": brief if isinstance(brief, dict) else {},
            "profile_brief_status": str(profile.get("profile_brief_status") or "").strip() or (
                "ready" if isinstance(brief, dict) and brief else "missing"
            ),
        }
        if isinstance(profile.get("character_update_gate"), dict):
            existing_profile["character_update_gate"] = profile["character_update_gate"]
        return existing_profile

    def _character_reduce_detail_policy(
        self,
        *,
        evidence_items: list[dict[str, Any]],
        existing_profile: dict[str, Any] | None,
    ) -> dict[str, Any]:
        gate = None
        if isinstance(existing_profile, dict):
            raw_gate = existing_profile.get("character_update_gate")
            if isinstance(raw_gate, dict):
                gate = raw_gate
        if isinstance(gate, dict) and str(gate.get("detail_level") or "").strip():
            return {
                "detail_level": str(gate.get("detail_level") or "compact").strip(),
                "reason": str(gate.get("reason") or "profile_update_gate").strip(),
                "current_doc_frequency": gate.get("current_doc_frequency"),
                "current_doc_count": gate.get("current_doc_count"),
                "current_total_docs": gate.get("current_total_docs"),
                "speaking_doc_count": gate.get("speaking_doc_count"),
                "action_doc_count": gate.get("action_doc_count"),
                "relationship_doc_count": gate.get("relationship_doc_count"),
            }
        doc_ids = {
            doc_id
            for item in evidence_items
            for doc_id in self._safe_int_list(item.get("source_doc_ids"))
        }
        speaking_count = sum(1 for item in evidence_items if bool(item.get("is_speaking_character")))
        action_count = sum(1 for item in evidence_items if str(item.get("activity_or_state_evidence") or "").strip())
        relationship_count = sum(1 for item in evidence_items if str(item.get("relationship_evidence") or "").strip())
        if len(doc_ids) >= 3 and (speaking_count > 0 or action_count >= 2 or relationship_count > 0):
            detail_level = "detailed"
            reason = "fallback_batch_wide_direct_signal"
        elif speaking_count > 0 or action_count > 0 or relationship_count > 0:
            detail_level = "compact"
            reason = "fallback_direct_signal"
        else:
            detail_level = "index_only"
            reason = "fallback_low_frequency_or_background_role"
        return {
            "detail_level": detail_level,
            "reason": reason,
            "current_doc_count": len(doc_ids),
            "speaking_doc_count": speaking_count,
            "action_doc_count": action_count,
            "relationship_doc_count": relationship_count,
        }

    def _character_reduce_summary(
        self,
        summary_payload: dict[str, Any],
        *,
        current_outline_segment: dict[str, Any],
    ) -> dict[str, Any]:
        chapter_summaries = self._compact_chapter_summaries(summary_payload.get("chapter_summaries", []))
        summary_short = str(summary_payload.get("chapter_summary_short") or "").strip()
        context_text = self._character_reduce_chapter_context_text(
            summary_short=summary_short,
            chapter_summaries=chapter_summaries,
            current_outline_segment=current_outline_segment,
        )
        return {
            "chapter_summary_short": summary_short,
            "chapter_context_text": context_text,
            "chapter_summaries": chapter_summaries,
            "summary_policy": "full_chapter_summary_md_omitted; use chapter_context_text/current_outline_segment",
        }

    def _character_reduce_outline_segment(self, outline_segment: dict[str, Any]) -> dict[str, Any]:
        allowed = {
            "outline_segment_id",
            "outline_segment",
            "chapter_line",
            "source_doc_ids",
            "source_doc_range",
            "source_doc_start_id",
            "source_doc_end_id",
            "source_title_indexes",
            "source_chapter_range",
            "status",
        }
        return {key: outline_segment[key] for key in allowed if key in outline_segment and outline_segment[key] not in ("", [], {})}

    def _compact_chapter_summaries(self, value: object) -> list[dict[str, Any]]:
        if not isinstance(value, list):
            return []
        result: list[dict[str, Any]] = []
        for item in value:
            if not isinstance(item, dict):
                continue
            summary_short = str(item.get("chapter_summary_short") or "").strip()
            if not summary_short:
                summary_short = str(item.get("summary_short") or "").strip()
            outline_source = item.get("current_outline_segment")
            if not isinstance(outline_source, dict):
                outline_source = item.get("outline_update")
            if not isinstance(outline_source, dict):
                outline_source = {
                    "outline_segment_id": item.get("outline_segment_id"),
                    "outline_segment": item.get("outline_segment") or item.get("summary"),
                    "source_doc_range": item.get("source_doc_range"),
                    "source_doc_ids": item.get("source_doc_ids"),
                    "source_title_indexes": item.get("source_title_indexes"),
                }
            outline_segment = self._character_reduce_outline_segment(dict(outline_source))
            if not summary_short and not outline_segment.get("outline_segment"):
                continue
            compact_item = {
                "document_title_index": item.get("document_title_index"),
                "chapter_title": str(item.get("chapter_title") or "").strip(),
                "chapter_summary_short": summary_short,
                "summary_quality": str(item.get("summary_quality") or "").strip(),
            }
            if outline_segment:
                compact_item["current_outline_segment"] = outline_segment
            result.append(compact_item)
        return result

    def _character_reduce_chapter_context_text(
        self,
        *,
        summary_short: str,
        chapter_summaries: list[dict[str, Any]],
        current_outline_segment: dict[str, Any],
    ) -> str:
        parts: list[str] = []
        outline_text = str(current_outline_segment.get("outline_segment") or "").strip()
        outline_id = str(current_outline_segment.get("outline_segment_id") or "").strip()
        doc_range = str(current_outline_segment.get("source_doc_range") or "").strip()
        if outline_text:
            label = outline_id or "current_outline_segment"
            suffix = f" docs {doc_range}" if doc_range else ""
            parts.append(f"[{label}{suffix}] {outline_text}")
        elif summary_short:
            parts.append(f"短摘要：{summary_short}")
        for item in chapter_summaries:
            title_index = item.get("document_title_index")
            title = str(item.get("chapter_title") or "").strip()
            short = str(item.get("chapter_summary_short") or "").strip()
            item_outline = item.get("current_outline_segment")
            if isinstance(item_outline, dict):
                item_outline = self._character_reduce_outline_segment(item_outline)
            else:
                item_outline = {}
            item_outline_text = str(item_outline.get("outline_segment") or "").strip()
            item_outline_id = str(item_outline.get("outline_segment_id") or "").strip()
            item_doc_range = str(item_outline.get("source_doc_range") or "").strip()
            label_bits = [str(title_index)] if title_index not in (None, "") else []
            if title:
                label_bits.append(title)
            label = item_outline_id or " ".join(label_bits) or "chapter_summary"
            if item_outline_text:
                suffix = f" docs {item_doc_range}" if item_doc_range else ""
                parts.append(f"[{label}{suffix}] {item_outline_text}")
            elif short:
                parts.append(f"[{label}] {short}")
        return "\n".join(dict.fromkeys(part for part in parts if part))

    def _global_summary_payload(self, summary_payload: dict[str, Any]) -> dict[str, Any]:
        return {
            "chapter_summary_md": summary_payload.get("chapter_summary_md", ""),
            "chapter_summary_short": summary_payload.get("chapter_summary_short", ""),
            "importance_score": summary_payload.get("importance_score", 0),
            "importance_reason": summary_payload.get("importance_reason", ""),
            "related_chapters": summary_payload.get("related_chapters", []),
            "chapter_summaries": summary_payload.get("chapter_summaries", []),
            "world_signal_score": summary_payload.get("world_signal_score", 0),
            "world_evidence_candidates": self._normalize_world_candidates(
                summary_payload.get("world_evidence_candidates", [])
            ),
        }

    def _normalize_world_evidence_payload(self, payload: dict[str, Any]) -> dict[str, Any]:
        return {
            "world_signal_score": payload.get("world_signal_score", 0),
            "world_evidence_candidates": self._normalize_world_candidates(
                payload.get("world_evidence_candidates", [])
            ),
        }

    def _normalize_world_candidates(self, candidates: object) -> list[dict[str, Any]]:
        if not isinstance(candidates, list):
            return []
        result: list[dict[str, Any]] = []
        for candidate in candidates:
            if not isinstance(candidate, dict):
                continue
            result.append(
                {
                    "section": str(candidate.get("section", "")).strip(),
                    "summary": str(candidate.get("summary", "")).strip(),
                    "evidence_hint": str(candidate.get("evidence_hint", "")).strip(),
                    "source_doc_ids": self._safe_int_list(candidate.get("source_doc_ids")),
                    "source_title_indexes": self._safe_int_list(candidate.get("source_title_indexes")),
                    "confidence": self._safe_float(candidate.get("confidence"), default=0.0),
                }
            )
        return result

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

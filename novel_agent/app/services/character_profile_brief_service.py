from __future__ import annotations

import json
import sqlite3
from typing import Any, Mapping

from ..llm import JsonModelClient
from ..prompts.profile_brief_prompt import (
    build_profile_brief_bootstrap_prompt,
    build_profile_brief_compact_prompt,
)
from ..repos.documents_repo import DocumentsRepo
from ..utils.text_utils import safe_excerpt


PROFILE_BRIEF_STATUS_READY = "ready"
PROFILE_BRIEF_STATUS_MISSING = "missing"
PROFILE_BRIEF_STATUS_NEEDS_COMPACT = "needs_compact"


class CharacterProfileBriefService:
    def __init__(self, *, max_compact_rounds: int = 2, source_doc_excerpt_chars: int = 1200) -> None:
        self.max_compact_rounds = max(1, int(max_compact_rounds))
        self.source_doc_excerpt_chars = max(200, int(source_doc_excerpt_chars))

    def bootstrap_from_row(self, *, model_client: JsonModelClient, row: sqlite3.Row) -> dict[str, Any]:
        prompt_input = {
            "mode": "bootstrap_missing_profile_brief",
            "profile": self._full_profile_from_row(row),
            "output_policy": {
                "profile_brief_is_persistent": True,
                "use_persistent_profile_brief": True,
                "preserve_source_refs": True,
            },
        }
        system_prompt, user_prompt = build_profile_brief_bootstrap_prompt(prompt_input)
        payload, _raw = model_client.generate_json(
            system_prompt=system_prompt,
            user_prompt=user_prompt,
            fallback_factory=lambda: self._dry_run_payload(row=row),
            use_fallback_on_error=False,
        )
        return self._normalize_brief_payload(payload, row=row, status=PROFILE_BRIEF_STATUS_READY)

    def compact_loop(
        self,
        *,
        conn: sqlite3.Connection,
        model_client: JsonModelClient,
        documents_repo: DocumentsRepo,
        row: sqlite3.Row,
        current_update: Mapping[str, Any],
        chapter_summary: Mapping[str, Any],
        current_outline_segment: Mapping[str, Any],
    ) -> dict[str, Any]:
        profile = self._full_profile_from_row(row)
        context_details: list[dict[str, Any]] = []
        payload: dict[str, Any] = {}
        for round_index in range(1, self.max_compact_rounds + 1):
            prompt_input = {
                "mode": "compact_profile_brief",
                "round": round_index,
                "profile_identity": profile["identity"],
                "current_profile_brief": profile["profile_brief"],
                "current_update": dict(current_update),
                "chapter_summary": dict(chapter_summary),
                "current_outline_segment": dict(current_outline_segment),
                "recent_activity_index": self._experience_index(profile["recent_activity"]),
                "story_event_index": self._experience_index(profile["story_events"]),
                "requested_context": context_details,
                "loop_policy": {
                    "request_context_when_needed": round_index < self.max_compact_rounds,
                    "finalize_on_last_round": round_index >= self.max_compact_rounds,
                    "use_persistent_profile_brief": True,
                },
            }
            system_prompt, user_prompt = build_profile_brief_compact_prompt(prompt_input)
            raw_payload, _raw = model_client.generate_json(
                system_prompt=system_prompt,
                user_prompt=user_prompt,
                fallback_factory=lambda: self._dry_run_payload(row=row),
                use_fallback_on_error=False,
            )
            payload = raw_payload if isinstance(raw_payload, dict) else {}
            action = str(payload.get("action") or "").strip()
            if action == "request_context" and round_index < self.max_compact_rounds:
                context_details.extend(
                    self._resolve_context_requests(
                        conn=conn,
                        documents_repo=documents_repo,
                        profile=profile,
                        requests=payload.get("requests"),
                    )
                )
                continue
            break
        return self._normalize_brief_payload(payload, row=row, status=PROFILE_BRIEF_STATUS_READY)

    def should_compact(
        self,
        *,
        row: sqlite3.Row,
        current_update: Mapping[str, Any],
    ) -> bool:
        brief = self._json_dict(row["profile_brief_json"]) if self._row_has_column(row, "profile_brief_json") else {}
        status = str(row["profile_brief_status"] or "").strip() if self._row_has_column(row, "profile_brief_status") else ""
        if not brief or status in {PROFILE_BRIEF_STATUS_MISSING, PROFILE_BRIEF_STATUS_NEEDS_COMPACT}:
            return True
        compact_signal = current_update.get("profile_brief_compact") or current_update.get("brief_compact")
        if isinstance(compact_signal, Mapping) and bool(compact_signal.get("needed")):
            return True
        change_types = current_update.get("profile_brief_change_types")
        if isinstance(change_types, list) and any(str(item).strip() for item in change_types):
            return True
        return False

    def _normalize_brief_payload(
        self,
        payload: object,
        *,
        row: sqlite3.Row,
        status: str,
    ) -> dict[str, Any]:
        data = dict(payload) if isinstance(payload, Mapping) else {}
        brief = data.get("profile_brief")
        if not isinstance(brief, Mapping):
            brief = data
        normalized = dict(brief) if isinstance(brief, Mapping) else {}
        identity = normalized.get("identity") if isinstance(normalized.get("identity"), Mapping) else {}
        normalized["identity"] = {
            "character_id": str(identity.get("character_id") or row["character_id"]),
            "canonical_name": str(identity.get("canonical_name") or row["canonical_name"] or "").strip(),
            "aliases": self._string_list(identity.get("aliases") or self._json_list(row["aliases_json"])),
        }
        normalized["current_state"] = str(normalized.get("current_state") or "").strip()
        normalized["stable_traits"] = self._string_list(normalized.get("stable_traits"))
        normalized["abilities_or_limits"] = self._string_list(normalized.get("abilities_or_limits"))
        normalized["relationship_digest"] = self._dict_list(normalized.get("relationship_digest"))
        normalized["open_questions"] = self._string_list(normalized.get("open_questions"))
        latest_major_change = normalized.get("latest_major_change")
        normalized["latest_major_change"] = dict(latest_major_change) if isinstance(latest_major_change, Mapping) else {}
        normalized["source_refs"] = self._dict_list(normalized.get("source_refs"))
        compacted_until = normalized.get("compacted_until")
        normalized["compacted_until"] = dict(compacted_until) if isinstance(compacted_until, Mapping) else {
            "doc_id": row["last_seen_doc_id"],
            "outline_segment_id": "",
        }
        return {
            "profile_brief": normalized,
            "profile_brief_status": status,
            "compact_notes": str(data.get("compact_notes") or "").strip(),
            "consumed_recent_activity_refs": self._string_list(data.get("consumed_recent_activity_refs")),
        }

    def _resolve_context_requests(
        self,
        *,
        conn: sqlite3.Connection,
        documents_repo: DocumentsRepo,
        profile: Mapping[str, Any],
        requests: object,
    ) -> list[dict[str, Any]]:
        if not isinstance(requests, list):
            return []
        resolved: list[dict[str, Any]] = []
        for request in requests[:6]:
            if not isinstance(request, Mapping):
                continue
            kind = str(request.get("kind") or "").strip()
            selector = dict(request.get("selector") or {}) if isinstance(request.get("selector"), Mapping) else {}
            if kind in {"recent_activity", "story_event"}:
                source_items = profile["recent_activity"] if kind == "recent_activity" else profile["story_events"]
                matches = self._select_experience_items(source_items, selector=selector)
                resolved.append(
                    {
                        "kind": kind,
                        "selector": selector,
                        "reason": str(request.get("reason") or "").strip(),
                        "items": matches,
                    }
                )
            elif kind in {"source_doc", "document"}:
                doc_ids = self._int_list(selector.get("doc_ids") or selector.get("source_doc_ids"))
                docs = []
                for doc_id in doc_ids[:4]:
                    row = conn.execute(
                        "SELECT * FROM documents WHERE doc_id = ?",
                        (doc_id,),
                    ).fetchone()
                    if row is None:
                        continue
                    doc = documents_repo._row_to_document(row)  # noqa: SLF001
                    docs.append(
                        {
                            "doc_id": doc.doc_id,
                            "document_title_index": doc.document_title_index,
                            "document_title": doc.document_title,
                            "excerpt": safe_excerpt(doc.content, self.source_doc_excerpt_chars),
                        }
                    )
                resolved.append({"kind": "source_doc", "selector": selector, "items": docs})
        return resolved

    def _select_experience_items(self, items: object, *, selector: Mapping[str, Any]) -> list[dict[str, Any]]:
        source_items = [dict(item) for item in items if isinstance(item, Mapping)] if isinstance(items, list) else []
        if not selector:
            return source_items[:6]
        event_id = str(selector.get("event_id") or selector.get("experience_id") or "").strip()
        outline_segment_id = str(selector.get("outline_segment_id") or "").strip()
        doc_ids = set(self._int_list(selector.get("doc_ids") or selector.get("source_doc_ids")))
        label_contains = str(selector.get("label_contains") or "").strip()
        matches = []
        for item in source_items:
            item_doc_ids = set(self._int_list(item.get("source_doc_ids")))
            if event_id and event_id not in {str(item.get("event_id") or ""), str(item.get("experience_id") or "")}:
                continue
            if outline_segment_id and outline_segment_id != str(item.get("outline_segment_id") or ""):
                continue
            if doc_ids and not doc_ids.intersection(item_doc_ids):
                continue
            if label_contains and label_contains not in json.dumps(item, ensure_ascii=False):
                continue
            matches.append(item)
        return matches[:8]

    def _experience_index(self, items: object) -> list[dict[str, Any]]:
        result = []
        for item in (items if isinstance(items, list) else []):
            if not isinstance(item, Mapping):
                continue
            result.append(
                {
                    "event_id": item.get("event_id") or item.get("experience_id") or "",
                    "label": item.get("label") or item.get("value") or "",
                    "summary": safe_excerpt(item.get("summary") or item.get("value") or "", 240),
                    "outline_segment_id": item.get("outline_segment_id") or "",
                    "source_doc_ids": self._int_list(item.get("source_doc_ids")),
                    "source_doc_range": item.get("source_doc_range") or "",
                }
            )
        return result

    def _full_profile_from_row(self, row: sqlite3.Row) -> dict[str, Any]:
        return {
            "identity": {
                "character_id": str(row["character_id"]),
                "canonical_name": str(row["canonical_name"] or "").strip(),
                "aliases": self._json_list(row["aliases_json"]),
            },
            "profile_summary_md": str(row["profile_summary_md"] or ""),
            "speaking_character_status": str(row["speaking_character_status"] or "unknown"),
            "personhood_evidence_summary": str(row["personhood_evidence_summary"] or ""),
            "evidence_level": str(row["evidence_level"] or "inferred"),
            "personality": self._json_list(row["personality_json"]),
            "occupations": self._json_list(row["occupations_json"]),
            "age_timeline": self._json_list(row["age_timeline_json"]),
            "abilities": self._json_list(row["abilities_json"]),
            "recent_activity": self._json_list(row["recent_activity_json"]),
            "relationships": self._json_list(row["relationships_json"]),
            "story_events": self._json_list(row["story_events_json"]),
            "chapter_indexes": self._json_list(row["chapter_indexes_json"]),
            "mentioned_doc_ids": self._json_list(row["mentioned_doc_ids_json"]),
            "speaking_doc_ids": self._json_list(row["speaking_doc_ids_json"]),
            "profile_brief": self._json_dict(row["profile_brief_json"]) if self._row_has_column(row, "profile_brief_json") else {},
            "last_seen_doc_id": row["last_seen_doc_id"],
            "last_seen_title_index": row["last_seen_title_index"],
            "importance_score": int(row["importance_score"] or 0),
        }

    def _dry_run_payload(self, *, row: sqlite3.Row) -> dict[str, Any]:
        return {
            "profile_brief": {
                "identity": {
                    "character_id": str(row["character_id"]),
                    "canonical_name": str(row["canonical_name"] or ""),
                    "aliases": self._json_list(row["aliases_json"]),
                },
                "current_state": "dry_run_profile_brief",
                "stable_traits": [],
                "abilities_or_limits": [],
                "relationship_digest": [],
                "open_questions": [],
                "latest_major_change": {},
                "source_refs": [],
                "compacted_until": {"doc_id": row["last_seen_doc_id"], "outline_segment_id": ""},
            },
            "compact_notes": "dry_run",
        }

    @staticmethod
    def _row_has_column(row: sqlite3.Row, column: str) -> bool:
        return column in row.keys()

    @staticmethod
    def _json_list(raw_value: object) -> list[Any]:
        if not raw_value:
            return []
        try:
            value = json.loads(str(raw_value))
        except json.JSONDecodeError:
            return []
        return value if isinstance(value, list) else []

    @staticmethod
    def _json_dict(raw_value: object) -> dict[str, Any]:
        if not raw_value:
            return {}
        try:
            value = json.loads(str(raw_value))
        except json.JSONDecodeError:
            return {}
        return value if isinstance(value, dict) else {}

    @staticmethod
    def _string_list(value: object) -> list[str]:
        if not isinstance(value, list):
            return []
        result: list[str] = []
        for item in value:
            text = str(item or "").strip()
            if text and text not in result:
                result.append(text)
        return result

    @staticmethod
    def _dict_list(value: object) -> list[dict[str, Any]]:
        return [dict(item) for item in value if isinstance(item, Mapping)] if isinstance(value, list) else []

    @staticmethod
    def _int_list(value: object) -> list[int]:
        if not isinstance(value, list):
            return []
        result: list[int] = []
        for item in value:
            try:
                number = int(item)
            except (TypeError, ValueError):
                continue
            if number not in result:
                result.append(number)
        return result

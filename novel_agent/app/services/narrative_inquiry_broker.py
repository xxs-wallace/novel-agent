from __future__ import annotations

import json
import re
import sqlite3
from pathlib import Path
from typing import Any, Mapping, Sequence

from ..repos.assets_repo import AssetsRepo
from ..repos.chapters_repo import ChaptersRepo
from ..repos.character_profiles_repo import CharacterProfilesRepo
from ..repos.documents_repo import DocumentsRepo
from ..repos.fragment_cards_repo import FragmentCardsRepo
from ..schemas.narrative_index_schema import IndexQueryBudget, IndexQueryIntent
from ..schemas.narrative_inquiry_schema import (
    AnalyzerBudget,
    EvidenceBundle,
    NarrativeInquiryRequest,
)
from ..schemas.narrative_memory_schema import (
    MemoryCandidateSelection,
    MemoryEvidenceBundle,
    MemoryQueryBudget,
    MemoryQueryState,
)
from .narrative_index_facade import NarrativeIndexFacade
from .narrative_memory_query_service import NarrativeMemoryQueryService


def _text(value: object) -> str:
    return str(value or "").strip()


def _safe_excerpt(text: str, *, limit: int) -> str:
    normalized = re.sub(r"\s+", " ", _text(text))
    if len(normalized) <= limit:
        return normalized
    return normalized[:limit].rstrip() + "..."


def _json_list(value: object) -> list[Any]:
    if isinstance(value, list):
        return value
    try:
        parsed = json.loads(str(value or "[]"))
    except json.JSONDecodeError:
        return []
    return parsed if isinstance(parsed, list) else []


def _json_dict(value: object) -> dict[str, Any]:
    if isinstance(value, Mapping):
        return dict(value)
    try:
        parsed = json.loads(str(value or "{}"))
    except json.JSONDecodeError:
        return {}
    return dict(parsed) if isinstance(parsed, Mapping) else {}


def _string_list(value: object) -> list[str]:
    if not isinstance(value, Sequence) or isinstance(value, (str, bytes)):
        return []
    result: list[str] = []
    seen: set[str] = set()
    for item in value:
        text = _text(item)
        if text and text not in seen:
            seen.add(text)
            result.append(text)
    return result


def _tokens(text: str) -> list[str]:
    return [token for token in re.findall(r"[\u4e00-\u9fff]{2,}|[A-Za-z0-9_]{2,}", _text(text)) if token]


def _expanded_query_tokens(text: str) -> list[str]:
    tokens = _tokens(text)
    seen = set(tokens)
    expanded = list(tokens)
    for token in tokens:
        if not re.fullmatch(r"[\u4e00-\u9fff]{4,}", token):
            continue
        for size in range(2, min(6, len(token)) + 1):
            for index in range(0, len(token) - size + 1):
                fragment = token[index : index + size]
                if fragment not in seen:
                    seen.add(fragment)
                    expanded.append(fragment)
    return expanded


def _json_text(value: object) -> str:
    if isinstance(value, Mapping):
        return json.dumps(value, ensure_ascii=False, sort_keys=True)
    return str(value or "")


def _profile_item_text(value: object) -> str:
    if not isinstance(value, Mapping):
        return str(value or "")
    priority_keys = (
        "value",
        "summary",
        "label",
        "status_summary",
        "relationship_summary",
        "target_name",
    )
    parts = [_text(value.get(key)) for key in priority_keys if _text(value.get(key))]
    metadata = json.dumps(value, ensure_ascii=False, sort_keys=True)
    if metadata:
        parts.append(metadata)
    return " | ".join(parts)


def _profile_story_event_text(value: object) -> str:
    if not isinstance(value, Mapping):
        return str(value or "")
    parts = [_text(value.get(key)) for key in ("label", "summary", "value") if _text(value.get(key))]
    participants = value.get("participants")
    if isinstance(participants, Sequence) and not isinstance(participants, (str, bytes)):
        participant_text = "、".join(_text(item) for item in participants if _text(item))
        if participant_text:
            parts.append(f"participants: {participant_text}")
    source_range = _text(value.get("source_doc_range"))
    if source_range:
        parts.append(f"source_doc_range: {source_range}")
    chapter_indexes = value.get("source_chapter_indexes")
    if isinstance(chapter_indexes, Sequence) and not isinstance(chapter_indexes, (str, bytes)):
        chapter_text = ", ".join(str(item) for item in chapter_indexes if str(item))
        if chapter_text:
            parts.append(f"source_chapter_indexes: {chapter_text}")
    return " | ".join(part for part in parts if part)


def _metadata_int(metadata: Mapping[str, Any], *keys: str, default: int = 0) -> int:
    for key in keys:
        if key not in metadata:
            continue
        try:
            return int(metadata[key])
        except (TypeError, ValueError):
            return default
    return default


class NarrativeInquiryBroker:
    """Shared semantic evidence broker for Analyzer, Writer Research, and future Reviewer.

    The broker routes semantic requests to factual Memory Query or module-specific
    structured resolvers. It does not generate story advice, write Memory, or
    create Writer artifacts.
    """

    FACTUAL_MEMORY_TYPES = {"story_detail", "fact_check", "related_documents", "chapter_summary", "raw_excerpt"}
    INDEX_CARD_TYPES = {
        "index_card_search",
        "factual_event_card_search",
        "narrative_scene_card_search",
        "character_state_card_search",
        "mystery_card_search",
        "theme_signal_card_search",
        "world_concept_card_search",
        "creative_reference_card_search",
    }

    def __init__(
        self,
        *,
        repo_root: Path,
        memory_query_service: NarrativeMemoryQueryService | None = None,
        assets_repo: AssetsRepo | None = None,
        chapters_repo: ChaptersRepo | None = None,
        character_profiles_repo: CharacterProfilesRepo | None = None,
        documents_repo: DocumentsRepo | None = None,
        fragment_cards_repo: FragmentCardsRepo | None = None,
        narrative_index_facade: NarrativeIndexFacade | None = None,
    ) -> None:
        self.repo_root = repo_root.expanduser().resolve()
        self.memory_query_service = memory_query_service or NarrativeMemoryQueryService(repo_root=self.repo_root)
        self.assets_repo = assets_repo or AssetsRepo()
        self.chapters_repo = chapters_repo or ChaptersRepo()
        self.character_profiles_repo = character_profiles_repo or CharacterProfilesRepo()
        self.documents_repo = documents_repo or DocumentsRepo()
        self.fragment_cards_repo = fragment_cards_repo or FragmentCardsRepo()
        self.narrative_index_facade = narrative_index_facade or NarrativeIndexFacade(
            repo_root=self.repo_root,
            assets_repo=self.assets_repo,
            fragment_cards_repo=self.fragment_cards_repo,
        )

    def resolve_requests(
        self,
        conn: sqlite3.Connection,
        *,
        book_id: str,
        requests: Sequence[NarrativeInquiryRequest],
        budget: AnalyzerBudget,
        total_requests_used: int = 0,
        raw_requests_used: int = 0,
        selection_adapter: object | None = None,
    ) -> tuple[list[EvidenceBundle], dict[str, int]]:
        remaining = max(0, budget.max_total_requests - total_requests_used)
        priority_rank = {"high": 0, "medium": 1, "low": 2}
        deduped: list[NarrativeInquiryRequest] = []
        seen: set[str] = set()
        for request in sorted(requests, key=lambda item: priority_rank[item.priority]):
            if request.dedupe_key in seen:
                continue
            seen.add(request.dedupe_key)
            deduped.append(request)

        bundles: list[EvidenceBundle] = []
        raw_used = raw_requests_used
        for request in deduped[:remaining]:
            if request.request_type == "raw_excerpt":
                if raw_used >= budget.max_raw_excerpt_requests:
                    bundles.append(
                        EvidenceBundle(
                            request_id=request.request_id,
                            request_type=request.request_type,
                            query=request.query,
                            status="budget_limited",
                            fact_status="insufficient_context",
                            missing_facets=["raw_excerpt_budget"],
                            trace=[{"operation": "budget_reject", "reason": "max_raw_excerpt_requests"}],
                        )
                    )
                    continue
                raw_used += 1
            bundles.append(
                self.resolve_one(
                    conn,
                    book_id=book_id,
                    request=request,
                    budget=budget,
                    selection_adapter=selection_adapter,
                )
            )
        return bundles, {"total_requests_used": min(budget.max_total_requests, total_requests_used + len(deduped[:remaining])), "raw_requests_used": raw_used}

    def resolve_one(
        self,
        conn: sqlite3.Connection,
        *,
        book_id: str,
        request: NarrativeInquiryRequest,
        budget: AnalyzerBudget,
        selection_adapter: object | None = None,
    ) -> EvidenceBundle:
        if request.request_type in self.INDEX_CARD_TYPES:
            return self._resolve_index_cards(conn, book_id=book_id, request=request, budget=budget)
        if request.request_type == "text_search":
            return self._resolve_text_search(conn, book_id=book_id, request=request, budget=budget)
        if request.request_type in {"story_detail", "fact_check", "related_documents"}:
            return self._resolve_story_memory(
                conn,
                book_id=book_id,
                request=request,
                budget=budget,
                selection_adapter=selection_adapter,
            )
        if request.request_type == "chapter_summary":
            return self._resolve_chapter_summary(conn, book_id=book_id, request=request, budget=budget)
        if request.request_type == "raw_excerpt":
            return self._resolve_raw_excerpt(conn, book_id=book_id, request=request, budget=budget)
        if request.request_type == "character_profile":
            return self._resolve_character_profile(conn, book_id=book_id, request=request, budget=budget)
        if request.request_type == "world_concept":
            return self._resolve_world_concept(conn, book_id=book_id, request=request, budget=budget)
        if request.request_type == "source_arc":
            return self._resolve_source_arc(book_id=book_id, request=request, budget=budget)
        if request.request_type == "open_threads":
            return self._resolve_open_threads(conn, book_id=book_id, request=request, budget=budget)
        return self._resolve_structure_pattern(conn, request=request, budget=budget)

    def _resolve_text_search(
        self,
        conn: sqlite3.Connection,
        *,
        book_id: str,
        request: NarrativeInquiryRequest,
        budget: AnalyzerBudget,
    ) -> EvidenceBundle:
        metadata = request.metadata if isinstance(request.metadata, Mapping) else {}
        terms = self._text_search_terms(request)
        if not terms:
            return EvidenceBundle.missing(request, "search_terms")
        match_mode = _text(metadata.get("match_mode") or "all").lower()
        if match_mode not in {"all", "any"}:
            match_mode = "all"
        scopes = _string_list(metadata.get("scopes")) or [
            "memory_roots",
            "outline_segments",
            "chapter_summaries",
            "character_profiles",
            "index_cards",
        ]
        max_matches = max(1, min(24, _metadata_int(metadata, "max_matches", default=12) or 12))
        default_per_scope_limit = 10 if any(scope in {"document", "documents", "raw_documents"} for scope in scopes) else 4
        per_scope_limit = max(
            1,
            min(10, _metadata_int(metadata, "max_matches_per_scope", default=default_per_scope_limit) or default_per_scope_limit),
        )
        document_match_offset = max(0, _metadata_int(metadata, "match_offset", "document_match_offset", default=0))
        doc_ids = list(request.document_ids or request.source_doc_ids)
        if not doc_ids and request.chapter_refs:
            refs = [ref for ref in (self._normalize_chapter_ref(item) for item in request.chapter_refs) if ref]
            memory_bundle = self.memory_query_service.resolve_chapter_refs(conn, book_id=book_id, chapter_refs=refs)
            doc_ids = list(memory_bundle.source_doc_ids)
        if not doc_ids:
            doc_ids, too_broad = self._doc_ids_from_text(
                " ".join([request.query, request.purpose, request.expected_depth]),
                limit=12,
            )
            if too_broad:
                doc_ids = []

        matches: list[dict[str, Any]] = []
        trace: list[dict[str, Any]] = [
            {
                "operation": "text_search_start",
                "terms": list(terms),
                "match_mode": match_mode,
                "scopes": list(scopes),
                "bounded_document_ids": list(doc_ids),
            }
        ]
        scope_counts: dict[str, int] = {}
        for scope in scopes:
            before = len(matches)
            if scope in {"memory_root", "memory_roots", "root_summary", "story_overview"}:
                matches.extend(
                    self._text_search_memory_roots(
                        conn,
                        book_id=book_id,
                        terms=terms,
                        match_mode=match_mode,
                        budget=budget,
                        limit=per_scope_limit,
                    )
                )
            elif scope in {"outline_segment", "outline_segments"}:
                matches.extend(
                    self._text_search_outline_segments(
                        book_id=book_id,
                        terms=terms,
                        match_mode=match_mode,
                        budget=budget,
                        limit=per_scope_limit,
                    )
                )
            elif scope in {"chapter_summary", "chapter_summaries", "chapters"}:
                matches.extend(
                    self._text_search_chapter_summaries(
                        conn,
                        book_id=book_id,
                        terms=terms,
                        match_mode=match_mode,
                        budget=budget,
                        limit=per_scope_limit,
                    )
                )
            elif scope in {"character_profile", "character_profiles", "profiles"}:
                matches.extend(
                    self._text_search_character_profiles(
                        conn,
                        book_id=book_id,
                        terms=terms,
                        match_mode=match_mode,
                        budget=budget,
                        limit=per_scope_limit,
                    )
                )
            elif scope in {"index_card", "index_cards", "cards", "scene_cards"}:
                matches.extend(
                    self._text_search_index_cards(
                        book_id=book_id,
                        terms=terms,
                        match_mode=match_mode,
                        budget=budget,
                        limit=per_scope_limit,
                    )
                )
            elif scope in {"document", "documents", "raw_documents"}:
                if doc_ids or bool(metadata.get("allow_document_scan")):
                    matches.extend(
                        self._text_search_documents(
                            conn,
                            book_id=book_id,
                            terms=terms,
                            match_mode=match_mode,
                            budget=budget,
                            limit=per_scope_limit,
                            doc_ids=doc_ids[:12],
                            match_offset=document_match_offset,
                        )
                    )
                else:
                    trace.append(
                        {
                            "operation": "text_search_scope_skipped",
                            "scope": scope,
                            "reason": "documents_require_source_doc_ids_or_allow_document_scan",
                        }
                    )
            scope_counts[scope] = len(matches) - before
            if len(matches) >= max_matches:
                break

        deduped = self._dedupe_text_search_matches(matches)[:max_matches]
        source_doc_ids: list[int] = []
        seen_doc_ids: set[int] = set()
        for item in deduped:
            for doc_id in item.get("source_doc_ids") or []:
                if not str(doc_id).isdigit():
                    continue
                normalized_doc_id = int(doc_id)
                if normalized_doc_id in seen_doc_ids:
                    continue
                seen_doc_ids.add(normalized_doc_id)
                source_doc_ids.append(normalized_doc_id)
        chapter_refs = self._merge_chapter_refs(
            [
                str(ref)
                for item in deduped
                for ref in (item.get("chapter_refs") or [])
                if str(ref)
            ],
            [],
        )
        trace.append(
            {
                "operation": "text_search_complete",
                "scope_counts": scope_counts,
                "match_count": len(deduped),
                "document_match_offset": document_match_offset,
            }
        )
        if not deduped:
            return EvidenceBundle(
                request_id=request.request_id,
                request_type=request.request_type,
                query=request.query,
                status="missing",
                fact_status="missing",
                missing_facets=["text_matches"],
                trace=trace,
            )
        return EvidenceBundle(
            request_id=request.request_id,
            request_type=request.request_type,
            query=request.query,
            status="found",
            fact_status="candidate",
            evidence_items=deduped,
            chapter_refs=chapter_refs,
            source_doc_ids=source_doc_ids,
            sources=[
                {
                    "type": "text_search",
                    "path": f"{item.get('scope')}:{item.get('id')}",
                    "status": item.get("status") or "candidate",
                }
                for item in deduped
            ],
            trace=trace,
        )

    def _resolve_index_cards(
        self,
        conn: sqlite3.Connection,
        *,
        book_id: str,
        request: NarrativeInquiryRequest,
        budget: AnalyzerBudget,
    ) -> EvidenceBundle:
        target_card_types = self._target_card_types_for_request(request.request_type)
        intent = IndexQueryIntent(
            original_query=request.query or request.name or request.concept,
            consumer=str(request.metadata.get("consumer") or "analyzer"),
            target_card_types=target_card_types,
            query_facets=[
                request.purpose,
                request.expected_depth,
                *_string_list(request.metadata.get("query_facets") or request.metadata.get("facets")),
            ],
            must_include_characters=[request.name] if request.name else [],
            raw_read_policy="avoid_unless_needed",
        )
        result = self.narrative_index_facade.search_cards(
            conn,
            book_id=book_id,
            intent=intent,
            budget=IndexQueryBudget(
                max_candidate_cards=max(1, budget.max_requests_per_round * 4),
                max_card_summary_chars=budget.max_evidence_chars_per_request,
            ),
        )
        if not result.candidate_cards:
            return EvidenceBundle.missing(request, "index_cards")
        cards = [hit.card for hit in result.candidate_cards]
        source_bundle = self.narrative_index_facade.resolve_card_sources(conn, book_id=book_id, cards=cards)
        evidence_items = [
            {
                "evidence_type": "index_card",
                "score": hit.score,
                "matched_by": list(hit.matched_by),
                "evidence_derivation": "summary_derived_index_card",
                "canonical_fact_status": "candidate_requires_direct_confirmation_for_conflicts",
                "evidence_warning": (
                    "Index card summaries and importance facets are retrieval cues, not canonical facts. "
                    "When they conflict on participants, counts, costs, causality, timeline, or scene presence, "
                    "confirm with chapter summary or raw excerpt."
                ),
                **hit.card.to_dict(),
            }
            for hit in result.candidate_cards
        ]
        return EvidenceBundle(
            request_id=request.request_id,
            request_type=request.request_type,
            query=intent.original_query,
            status="found",
            fact_status="candidate",
            evidence_items=evidence_items,
            chapter_refs=list(source_bundle.chapter_refs),
            source_doc_ids=list(source_bundle.source_doc_ids),
            sources=list(source_bundle.sources),
            trace=[
                *result.trace,
                *source_bundle.trace,
                {
                    "operation": "narrative_index_resolve",
                    "request_type": request.request_type,
                    "raw_read_recommendations": list(result.raw_read_recommendations),
                },
            ],
        )

    def _target_card_types_for_request(self, request_type: str) -> list[str]:
        mapping = {
            "factual_event_card_search": ["factual_event"],
            "narrative_scene_card_search": ["narrative_scene"],
            "character_state_card_search": ["character_state"],
            "mystery_card_search": ["mystery_foreshadow"],
            "theme_signal_card_search": ["theme_signal"],
            "world_concept_card_search": ["world_concept"],
            "creative_reference_card_search": ["creative_reference"],
        }
        return mapping.get(request_type, [])

    def _text_search_terms(self, request: NarrativeInquiryRequest) -> list[str]:
        metadata = request.metadata if isinstance(request.metadata, Mapping) else {}
        terms = _string_list(metadata.get("terms") or metadata.get("keywords"))
        if not terms:
            terms = [item for item in re.findall(r'"([^"]+)"|“([^”]+)”|\'([^\']+)\'', request.query) for item in item if item]
        if not terms:
            terms = _tokens(" ".join([request.query, request.name, request.concept]))
        if not terms and request.query:
            terms = [request.query]
        deduped: list[str] = []
        seen: set[str] = set()
        for term in terms:
            text = _text(term)
            if not text or text in seen:
                continue
            seen.add(text)
            deduped.append(text)
        return deduped[:8]

    def _text_matches(self, text: str, terms: Sequence[str], *, match_mode: str) -> tuple[bool, list[str]]:
        haystack = text.casefold()
        matched: list[str] = []
        for term in terms:
            needle = term.casefold()
            if needle and needle in haystack:
                matched.append(term)
        if match_mode == "any":
            return bool(matched), matched
        return len(matched) == len(terms), matched

    def _text_search_item(
        self,
        *,
        scope: str,
        item_id: str,
        label: str,
        text: str,
        terms: Sequence[str],
        match_mode: str,
        budget: AnalyzerBudget,
        chapter_refs: Sequence[str] = (),
        source_doc_ids: Sequence[object] = (),
        status: str = "",
        extra: Mapping[str, Any] | None = None,
    ) -> dict[str, Any] | None:
        ok, matched_terms = self._text_matches(text, terms, match_mode=match_mode)
        if not ok:
            return None
        normalized_doc_ids: list[int] = []
        seen_doc_ids: set[int] = set()
        for item in source_doc_ids:
            if not str(item).isdigit():
                continue
            doc_id = int(item)
            if doc_id in seen_doc_ids:
                continue
            seen_doc_ids.add(doc_id)
            normalized_doc_ids.append(doc_id)
        payload = {
            "evidence_type": "text_search_match",
            "scope": scope,
            "id": item_id,
            "label": label,
            "matched_terms": list(matched_terms),
            "matched_term_count": len(matched_terms),
            "match_mode": match_mode,
            "snippet": self._text_search_snippet(text, terms, limit=min(520, budget.max_evidence_chars_per_request)),
            "chapter_refs": [ref for ref in (self._normalize_chapter_ref(item) for item in chapter_refs) if ref],
            "source_doc_ids": normalized_doc_ids,
            "status": status or "candidate",
            "evidence_derivation": "lexical_text_search_locator",
            "canonical_fact_status": "locator_only_requires_followup_for_semantic_or_verbatim_answers",
        }
        if extra:
            payload.update(dict(extra))
        return payload

    def _text_search_snippet(self, text: str, terms: Sequence[str], *, limit: int) -> str:
        normalized = re.sub(r"\s+", " ", _text(text))
        if len(normalized) <= limit:
            return normalized
        positions = [normalized.casefold().find(term.casefold()) for term in terms if term and term.casefold() in normalized.casefold()]
        start = min((pos for pos in positions if pos >= 0), default=0)
        start = max(0, start - max(20, limit // 5))
        snippet = normalized[start : start + limit].strip()
        prefix = "..." if start > 0 else ""
        suffix = "..." if start + limit < len(normalized) else ""
        return f"{prefix}{snippet}{suffix}"

    def _dedupe_text_search_matches(self, matches: Sequence[Mapping[str, Any]]) -> list[dict[str, Any]]:
        deduped: list[dict[str, Any]] = []
        seen: set[tuple[str, str]] = set()
        for item in matches:
            key = (str(item.get("scope") or ""), str(item.get("id") or ""))
            if key in seen:
                continue
            seen.add(key)
            deduped.append(dict(item))
        return deduped

    def _text_search_memory_roots(
        self,
        conn: sqlite3.Connection,
        *,
        book_id: str,
        terms: Sequence[str],
        match_mode: str,
        budget: AnalyzerBudget,
        limit: int,
    ) -> list[dict[str, Any]]:
        matches: list[dict[str, Any]] = []
        try:
            state = self.memory_query_service.root_map(
                conn,
                book_id=book_id,
                budget=MemoryQueryBudget(max_root_candidates=24, max_candidate_chars=budget.max_evidence_chars_per_request),
            )
        except Exception:
            return []
        for item in state.current_candidates:
            text = " ".join(
                _text(item.get(key))
                for key in ("summary", "title", "page_id", "id", "source_doc_range")
                if _text(item.get(key))
            )
            match = self._text_search_item(
                scope="memory_root",
                item_id=str(item.get("page_id") or item.get("id") or ""),
                label=str(item.get("title") or item.get("page_id") or item.get("id") or "memory_root"),
                text=text,
                terms=terms,
                match_mode=match_mode,
                budget=budget,
                chapter_refs=[str(value) for value in (item.get("source_title_indexes") or [])],
                source_doc_ids=item.get("source_doc_ids") or [],
                status=str(item.get("status") or ""),
            )
            if match:
                matches.append(match)
            if len(matches) >= limit:
                break
        return matches

    def _text_search_outline_segments(
        self,
        *,
        book_id: str,
        terms: Sequence[str],
        match_mode: str,
        budget: AnalyzerBudget,
        limit: int,
    ) -> list[dict[str, Any]]:
        data = self._load_book_json(self.repo_root / ".memory" / "outlines" / f"{book_id}.outline_segments.json")
        segments = _json_list(data.get("segments")) if data else []
        matches: list[dict[str, Any]] = []
        for item in segments:
            if not isinstance(item, Mapping):
                continue
            text = " ".join(
                [
                    _text(item.get("summary")),
                    _text(item.get("chapter_line")),
                    _json_text(item.get("metadata")),
                ]
            )
            match = self._text_search_item(
                scope="outline_segment",
                item_id=str(item.get("outline_segment_id") or item.get("id") or ""),
                label=str(item.get("chapter_line") or item.get("outline_segment_id") or "outline_segment"),
                text=text,
                terms=terms,
                match_mode=match_mode,
                budget=budget,
                chapter_refs=[str(value) for value in (item.get("source_title_indexes") or [])],
                source_doc_ids=item.get("source_doc_ids") or [],
                status=str(item.get("status") or ""),
                extra={
                    "outline_segment_id": item.get("outline_segment_id") or "",
                    "source_doc_range": item.get("source_doc_range") or "",
                },
            )
            if match:
                matches.append(match)
            if len(matches) >= limit:
                break
        return matches

    def _text_search_chapter_summaries(
        self,
        conn: sqlite3.Connection,
        *,
        book_id: str,
        terms: Sequence[str],
        match_mode: str,
        budget: AnalyzerBudget,
        limit: int,
    ) -> list[dict[str, Any]]:
        try:
            rows = self.chapters_repo.list_by_book(conn, book_id=book_id)
        except sqlite3.OperationalError:
            rows = []
        matches: list[dict[str, Any]] = []
        for row in rows:
            chapter_index = int(row["document_title_index"] or 0)
            text = " ".join(
                [
                    str(row["chapter_title"] or ""),
                    str(row["summary_short"] or ""),
                    str(row["summary_md"] or ""),
                    str(row["importance_reason"] or ""),
                    str(row["outline_update_json"] or ""),
                    str(row["mentioned_characters_json"] or ""),
                ]
            )
            match = self._text_search_item(
                scope="chapter_summary",
                item_id=f"chapter-{chapter_index}",
                label=f"chapter-{chapter_index} {row['chapter_title'] or ''}",
                text=text,
                terms=terms,
                match_mode=match_mode,
                budget=budget,
                chapter_refs=[str(chapter_index)],
                source_doc_ids=range(int(row["source_doc_start_id"] or 0), int(row["source_doc_end_id"] or 0) + 1),
                status=str(row["summary_status"] or ""),
                extra={
                    "chapter_title": str(row["chapter_title"] or ""),
                    "source_doc_range": f"{int(row['source_doc_start_id'] or 0)}-{int(row['source_doc_end_id'] or 0)}",
                },
            )
            if match:
                matches.append(match)
            if len(matches) >= limit:
                break
        return matches

    def _text_search_character_profiles(
        self,
        conn: sqlite3.Connection,
        *,
        book_id: str,
        terms: Sequence[str],
        match_mode: str,
        budget: AnalyzerBudget,
        limit: int,
    ) -> list[dict[str, Any]]:
        try:
            rows = self.character_profiles_repo.list_by_book(conn, book_id=book_id)
        except sqlite3.OperationalError:
            rows = []
        matches: list[dict[str, Any]] = []
        for row in rows:
            text = " ".join(
                [
                    str(row["canonical_name"] or ""),
                    str(row["aliases_json"] or ""),
                    str(row["profile_summary_md"] or ""),
                    str(row["recent_activity_json"] or ""),
                    str(row["relationships_json"] or ""),
                    str(row["story_events_json"] or ""),
                    str(row["profile_brief_json"] or ""),
                ]
            )
            match = self._text_search_item(
                scope="character_profile",
                item_id=str(row["character_id"] or row["canonical_name"] or ""),
                label=str(row["canonical_name"] or "character_profile"),
                text=text,
                terms=terms,
                match_mode=match_mode,
                budget=budget,
                chapter_refs=[str(value) for value in _json_list(row["chapter_indexes_json"])],
                source_doc_ids=_json_list(row["mentioned_doc_ids_json"]),
                status=str(row["evidence_level"] or ""),
                extra={"canonical_name": str(row["canonical_name"] or "")},
            )
            if match:
                matches.append(match)
            if len(matches) >= limit:
                break
        return matches

    def _text_search_index_cards(
        self,
        *,
        book_id: str,
        terms: Sequence[str],
        match_mode: str,
        budget: AnalyzerBudget,
        limit: int,
    ) -> list[dict[str, Any]]:
        data = self._load_book_json(self.repo_root / ".memory" / "index_cards" / f"{book_id}.scene_cards.json")
        cards = _json_list(data.get("scene_cards")) if data else []
        matches: list[dict[str, Any]] = []
        for item in cards:
            if not isinstance(item, Mapping):
                continue
            text = " ".join(
                [
                    _text(item.get("summary")),
                    _json_text(item.get("query_facets")),
                    _json_text(item.get("importance_facets")),
                    _json_text(item.get("payload")),
                ]
            )
            match = self._text_search_item(
                scope="index_card",
                item_id=str(item.get("card_id") or ""),
                label=str(item.get("summary") or item.get("card_id") or "index_card"),
                text=text,
                terms=terms,
                match_mode=match_mode,
                budget=budget,
                chapter_refs=[str(value) for value in (item.get("source_title_indexes") or [])],
                source_doc_ids=item.get("source_doc_ids") or [],
                status=str(item.get("status") or ""),
                extra={
                    "card_type": item.get("card_type") or "",
                    "source_doc_range": item.get("source_doc_range") or "",
                    "summary_sufficiency": item.get("summary_sufficiency") or "",
                },
            )
            if match:
                matches.append(match)
            if len(matches) >= limit:
                break
        return matches

    def _text_search_documents(
        self,
        conn: sqlite3.Connection,
        *,
        book_id: str,
        terms: Sequence[str],
        match_mode: str,
        budget: AnalyzerBudget,
        limit: int,
        doc_ids: Sequence[int],
        match_offset: int = 0,
    ) -> list[dict[str, Any]]:
        if doc_ids:
            placeholders = ",".join("?" for _ in doc_ids)
            rows = conn.execute(
                f"SELECT * FROM documents WHERE book_id = ? AND doc_id IN ({placeholders}) ORDER BY doc_id",
                [book_id, *doc_ids],
            ).fetchall()
        else:
            rows = conn.execute("SELECT * FROM documents WHERE book_id = ? ORDER BY doc_id", (book_id,)).fetchall()
        matches: list[dict[str, Any]] = []
        matched_count = 0
        for row in rows:
            match = self._text_search_item(
                scope="document",
                item_id=f"doc-{int(row['doc_id'])}",
                label=f"doc-{int(row['doc_id'])} {row['document_title'] or ''}",
                text=str(row["content"] or ""),
                terms=terms,
                match_mode=match_mode,
                budget=budget,
                chapter_refs=[str(row["document_title_index"] or "")],
                source_doc_ids=[int(row["doc_id"])],
                status="raw_locator",
                extra={
                    "document_title": str(row["document_title"] or ""),
                    "document_title_index": int(row["document_title_index"] or 0),
                    "document_match_index": matched_count,
                    "next_match_offset_hint": matched_count + 1,
                },
            )
            if match and matched_count >= match_offset:
                matches.append(match)
            if match:
                matched_count += 1
            if len(matches) >= limit:
                break
        return matches

    def _load_book_json(self, path: Path) -> dict[str, Any]:
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return {}
        return dict(data) if isinstance(data, Mapping) else {}

    def _resolve_story_memory(
        self,
        conn: sqlite3.Connection,
        *,
        book_id: str,
        request: NarrativeInquiryRequest,
        budget: AnalyzerBudget,
        selection_adapter: object | None = None,
    ) -> EvidenceBundle:
        state = self.memory_query_service.root_scan(
            conn,
            book_id=book_id,
            query=request.query,
            budget=MemoryQueryBudget(
                max_root_candidates=6,
                max_child_candidates=8,
                max_candidate_chars=budget.max_evidence_chars_per_request,
                excerpt_budget=budget.max_evidence_chars_per_request,
            ),
        )
        if not state.current_candidates:
            return EvidenceBundle.missing(request, "memory_root_candidates")
        selection = self._select_memory_candidates(state=state, request=request, selection_adapter=selection_adapter)
        if selection is None:
            outline_bundle = self._resolve_outline_level_without_selector(
                conn,
                book_id=book_id,
                request=request,
                state=state,
                budget=budget,
            )
            if outline_bundle is not None:
                return outline_bundle
            return self._bundle_from_memory_candidates(request, state, resolver="NarrativeMemoryQueryService.root_scan")
        return self._resolve_story_memory_btree(
            conn,
            book_id=book_id,
            request=request,
            budget=budget,
            initial_state=state,
            initial_selection=selection,
            selection_adapter=selection_adapter,
        )

    def _resolve_story_memory_btree(
        self,
        conn: sqlite3.Connection,
        *,
        book_id: str,
        request: NarrativeInquiryRequest,
        budget: AnalyzerBudget,
        initial_state: MemoryQueryState,
        initial_selection: MemoryCandidateSelection,
        selection_adapter: object | None,
    ) -> EvidenceBundle:
        final_state = initial_state
        evidence_bundle: MemoryEvidenceBundle | None = None
        decision_log: list[dict[str, Any]] = []
        model_reasoning_debug: list[dict[str, Any]] = []
        selection: MemoryCandidateSelection | None = initial_selection
        levels_to_visit = {"outline_root", "outline_segment", "event_summary", "event", "chapter"}

        while final_state.current_level in levels_to_visit and final_state.current_candidates and selection is not None:
            self._append_selection_trace(
                request=request,
                state=final_state,
                selection=selection,
                decision_log=decision_log,
                model_reasoning_debug=model_reasoning_debug,
            )
            if not selection.selected_ids:
                break
            if final_state.current_level == "outline_root" and not selection.need_drill_down:
                evidence_bundle = self._memory_bundle_from_selected_candidates(final_state, selection.selected_ids)
                break
            if final_state.current_level == "outline_segment" and not selection.need_drill_down:
                evidence_bundle = self.memory_query_service.resolve_outline_segment_refs(
                    conn,
                    book_id=book_id,
                    segment_ids=selection.selected_ids,
                )
                break
            if final_state.current_level == "event_summary" and not selection.need_drill_down:
                evidence_bundle = self._memory_bundle_from_selected_candidates(final_state, selection.selected_ids)
                break
            if final_state.current_level == "event" and not selection.need_drill_down:
                evidence_bundle = self.memory_query_service.resolve_event_ids(
                    conn,
                    book_id=book_id,
                    event_ids=selection.selected_ids,
                )
                break
            if final_state.current_level == "chapter" and not selection.need_drill_down:
                evidence_bundle = self.memory_query_service.resolve_chapter_refs(
                    conn,
                    book_id=book_id,
                    chapter_refs=selection.selected_ids,
                )
                break
            final_state = self.memory_query_service.drill_down(
                conn,
                book_id=book_id,
                state=final_state,
                selected_ids=selection.selected_ids,
                query_suffix=selection.query_suffix,
                selection_reason=selection.reason,
                confidence=selection.confidence,
                need_sibling_scan=selection.need_sibling_scan,
            )
            if final_state.current_level == "document":
                doc_ids = self._doc_ids_from_candidates(final_state.current_candidates)
                evidence_bundle = self.memory_query_service.resolve_document_refs(
                    conn,
                    book_id=book_id,
                    doc_ids=doc_ids,
                    excerpt_budget=budget.max_evidence_chars_per_request,
                )
                break
            selection = self._select_memory_candidates(
                state=final_state,
                request=request,
                selection_adapter=selection_adapter,
            )

        if evidence_bundle is None:
            evidence_bundle = self._resolve_current_memory_state(conn, book_id=book_id, state=final_state, budget=budget)
        if evidence_bundle is None:
            return self._bundle_from_memory_candidates(
                request,
                final_state,
                resolver="NarrativeMemoryQueryService.btree_descent",
                decision_log=decision_log,
                model_reasoning_debug=model_reasoning_debug,
            )
        bundle = self._bundle_from_memory(request, evidence_bundle, status_if_empty="missing")
        bundle.trace.extend(
            [
                {
                    "operation": "narrative_inquiry_btree",
                    "resolver": "NarrativeMemoryQueryService.btree_descent",
                    "request_type": request.request_type,
                    "final_level": final_state.current_level,
                    "decision_log": decision_log,
                    "model_reasoning_debug": model_reasoning_debug,
                    "final_evidence_ids": {
                        "event_ids": list(evidence_bundle.event_ids),
                        "chapter_refs": list(evidence_bundle.chapter_refs),
                        "source_doc_ids": list(evidence_bundle.source_doc_ids),
                    },
                }
            ]
        )
        for item in bundle.evidence_items:
            item.setdefault("memory_query_protocol", "btree")
            item.setdefault("memory_query_trace", [*initial_state.trace, *final_state.trace, *evidence_bundle.trace])
            item.setdefault("memory_query_decision_log", decision_log)
            item.setdefault("model_reasoning_debug", model_reasoning_debug)
            item.setdefault(
                "final_evidence_ids",
                {
                    "event_ids": list(evidence_bundle.event_ids),
                    "chapter_refs": list(evidence_bundle.chapter_refs),
                    "source_doc_ids": list(evidence_bundle.source_doc_ids),
                },
            )
        return bundle

    def _resolve_outline_level_without_selector(
        self,
        conn: sqlite3.Connection,
        *,
        book_id: str,
        request: NarrativeInquiryRequest,
        state: MemoryQueryState,
        budget: AnalyzerBudget,
    ) -> EvidenceBundle | None:
        expected_depth = _text(request.expected_depth).lower()
        if state.current_level != "outline_root":
            return None
        if expected_depth not in {"outline_segment", "outline", "story_outline", "segment"}:
            return None
        selected_root_ids = [
            str(item.get("id") or item.get("page_id") or "")
            for item in state.current_candidates[:2]
            if str(item.get("id") or item.get("page_id") or "")
        ]
        if not selected_root_ids:
            return None
        next_state = self.memory_query_service.drill_down(
            conn,
            book_id=book_id,
            state=state,
            selected_ids=selected_root_ids,
            query_suffix="定位和评审问题相关的 outline segment",
            selection_reason="selector unavailable; ranked outline root expansion",
            confidence=0.5,
        )
        segment_ids = [
            str(item.get("outline_segment_id") or item.get("id") or item.get("page_id") or "")
            for item in next_state.current_candidates[:4]
            if str(item.get("outline_segment_id") or item.get("id") or item.get("page_id") or "")
        ]
        if not segment_ids:
            return self._bundle_from_memory_candidates(
                request,
                next_state,
                resolver="NarrativeMemoryQueryService.outline_segment_scan",
            )
        memory_bundle = self.memory_query_service.resolve_outline_segment_refs(
            conn,
            book_id=book_id,
            segment_ids=segment_ids,
        )
        bundle = self._bundle_from_memory(request, memory_bundle, status_if_empty="missing")
        bundle.trace.extend(
            [
                *state.trace,
                *next_state.trace,
                {
                    "operation": "narrative_inquiry_outline_segment_scan",
                    "resolver": "NarrativeMemoryQueryService.resolve_outline_segment_refs",
                    "request_type": request.request_type,
                    "selected_outline_root_ids": selected_root_ids,
                    "selected_outline_segment_ids": segment_ids,
                    "expected_depth": expected_depth,
                },
            ]
        )
        for item in bundle.evidence_items:
            item.setdefault("memory_query_protocol", "outline_segment_scan")
            item.setdefault("final_evidence_ids", {"outline_segment_ids": segment_ids})
        return bundle

    def _select_memory_candidates(
        self,
        *,
        state: MemoryQueryState,
        request: NarrativeInquiryRequest,
        selection_adapter: object | None,
    ) -> MemoryCandidateSelection | None:
        selector = getattr(selection_adapter, "select_memory_candidates", None)
        if not callable(selector):
            return None
        raw = selector(state=state, request=request)
        if isinstance(raw, MemoryCandidateSelection):
            return raw
        if isinstance(raw, Mapping):
            return MemoryCandidateSelection.from_mapping(raw)
        raise TypeError("memory candidate selector must return MemoryCandidateSelection or mapping")

    def _append_selection_trace(
        self,
        *,
        request: NarrativeInquiryRequest,
        state: MemoryQueryState,
        selection: MemoryCandidateSelection,
        decision_log: list[dict[str, Any]],
        model_reasoning_debug: list[dict[str, Any]],
    ) -> None:
        decision_log.append(
            {
                "request_id": request.request_id,
                "current_level": state.current_level,
                "candidate_ids": [str(item.get("id") or item.get("page_id")) for item in state.current_candidates],
                **selection.to_dict(),
                "budget_state": dict(state.budget_used),
            }
        )
        if selection.model_reasoning_debug:
            model_reasoning_debug.append(
                {
                    "request_id": request.request_id,
                    "current_level": state.current_level,
                    **selection.model_reasoning_debug,
                }
            )

    def _resolve_current_memory_state(
        self,
        conn: sqlite3.Connection,
        *,
        book_id: str,
        state: MemoryQueryState,
        budget: AnalyzerBudget,
    ) -> MemoryEvidenceBundle | None:
        if state.current_level == "outline_segment":
            ids = [
                str(item.get("outline_segment_id") or item.get("id") or item.get("page_id"))
                for item in state.current_candidates[:3]
            ]
            return self.memory_query_service.resolve_outline_segment_refs(conn, book_id=book_id, segment_ids=ids)
        if state.current_level == "event":
            ids = [str(item.get("event_id") or item.get("id")) for item in state.current_candidates[:3]]
            return self.memory_query_service.resolve_event_ids(conn, book_id=book_id, event_ids=ids)
        if state.current_level == "chapter":
            ids = [str(item.get("chapter_ref") or item.get("id")) for item in state.current_candidates[:3]]
            return self.memory_query_service.resolve_chapter_refs(conn, book_id=book_id, chapter_refs=ids)
        if state.current_level == "document":
            return self.memory_query_service.resolve_document_refs(
                conn,
                book_id=book_id,
                doc_ids=self._doc_ids_from_candidates(state.current_candidates[:3]),
                excerpt_budget=budget.max_evidence_chars_per_request,
            )
        return None

    def _memory_bundle_from_selected_candidates(
        self,
        state: MemoryQueryState,
        selected_ids: Sequence[str],
    ) -> MemoryEvidenceBundle:
        selected = {str(item) for item in selected_ids}
        candidates = [
            item
            for item in state.current_candidates
            if str(item.get("id") or item.get("page_id") or "") in selected
        ] or list(state.current_candidates[:3])
        source_doc_ids = sorted({
            int(doc_id)
            for item in candidates
            for doc_id in (item.get("source_doc_ids") or [])
            if str(doc_id).isdigit()
        })
        statuses = {str(item.get("status") or "provisional") for item in candidates}
        status = "committed" if statuses == {"committed"} else ("mixed" if "committed" in statuses else "provisional")
        return MemoryEvidenceBundle(
            evidence_items=[
                {
                    "page_id": str(item.get("page_id") or item.get("id") or ""),
                    "page_type": str(item.get("page_type") or state.current_level),
                    "summary": str(item.get("summary") or ""),
                    "source_doc_ids": item.get("source_doc_ids") or [],
                    "source_doc_range": str(item.get("source_doc_range") or ""),
                    "status": str(item.get("status") or "provisional"),
                }
                for item in candidates
            ],
            sources=[
                {
                    "type": "memory_query",
                    "path": f"memory:{item.get('page_type') or state.current_level}:{item.get('page_id') or item.get('id')}",
                    "status": str(item.get("status") or "provisional"),
                }
                for item in candidates
            ],
            status=status,
            source_doc_ids=source_doc_ids,
            trace=[
                {
                    "operation": "resolve_selected_memory_candidates",
                    "level": state.current_level,
                    "selected_ids": list(selected_ids),
                    "resolved_ids": [str(item.get("id") or item.get("page_id") or "") for item in candidates],
                }
            ],
        )

    def _doc_ids_from_candidates(self, candidates: Sequence[Mapping[str, Any]]) -> list[int]:
        doc_ids: list[int] = []
        for item in candidates:
            raw = item.get("doc_id") or item.get("id") or item.get("page_id")
            text = str(raw or "")
            match = re.search(r"\d+", text)
            if match:
                doc_ids.append(int(match.group(0)))
        return sorted(set(doc_ids))

    def _bundle_from_memory_candidates(
        self,
        request: NarrativeInquiryRequest,
        state: MemoryQueryState,
        *,
        resolver: str,
        decision_log: Sequence[Mapping[str, Any]] | None = None,
        model_reasoning_debug: Sequence[Mapping[str, Any]] | None = None,
    ) -> EvidenceBundle:
        items = [
            {
                "summary": _safe_excerpt(str(item.get("summary") or ""), limit=state.budget.max_candidate_chars),
                "page_id": str(item.get("page_id") or item.get("id") or ""),
                "page_type": str(item.get("page_type") or state.current_level),
                "source_doc_ids": item.get("source_doc_ids") or [],
                "source_doc_range": item.get("source_doc_range") or "",
                "status": str(item.get("status") or "provisional"),
            }
            for item in state.current_candidates[:4]
        ]
        doc_ids = sorted({int(doc_id) for item in items for doc_id in (item.get("source_doc_ids") or []) if str(doc_id).isdigit()})
        fact_status = "confirmed" if any(item.get("status") == "committed" for item in items) else "candidate"
        return EvidenceBundle(
            request_id=request.request_id,
            request_type=request.request_type,
            query=request.query,
            status="found" if items else "missing",
            fact_status=fact_status if items else "missing",  # type: ignore[arg-type]
            evidence_items=items,
            source_doc_ids=doc_ids,
            sources=[
                {
                    "type": "memory_query",
                    "path": f"memory:{item['page_type']}:{item['page_id']}",
                    "status": item.get("status", "provisional"),
                }
                for item in items
            ],
            missing_facets=[] if items else ["memory_candidates"],
            trace=[
                *state.trace,
                {
                    "operation": "narrative_inquiry_route",
                    "resolver": resolver,
                    "request_type": request.request_type,
                    "final_level": state.current_level,
                    "decision_log": [dict(item) for item in (decision_log or [])],
                    "model_reasoning_debug": [dict(item) for item in (model_reasoning_debug or [])],
                },
            ],
        )

    def _resolve_chapter_summary(
        self,
        conn: sqlite3.Connection,
        *,
        book_id: str,
        request: NarrativeInquiryRequest,
        budget: AnalyzerBudget,
    ) -> EvidenceBundle:
        query = self._expanded_query_for_detail_lookup(request.query)
        refs = [ref for ref in (self._normalize_chapter_ref(item) for item in request.chapter_refs) if ref]
        if not refs:
            refs = self._chapter_refs_from_query(query)
        if not refs:
            state = self.memory_query_service.root_scan(
                conn,
                book_id=book_id,
                query=query,
                budget=MemoryQueryBudget(max_root_candidates=6, max_child_candidates=12),
            )
            if state.current_candidates:
                refs = self._chapter_refs_from_memory_candidates(state.current_candidates)
                if not refs and state.current_level in {"outline_root", "outline_segment"}:
                    selected_ids = [
                        str(item.get("id") or item.get("page_id") or "")
                        for item in state.current_candidates[:4]
                        if str(item.get("id") or item.get("page_id") or "")
                    ]
                    next_state = self.memory_query_service.drill_down(
                        conn,
                        book_id=book_id,
                        state=state,
                        selected_ids=selected_ids,
                        query_suffix=f"定位相关章节摘要：{query}",
                        selection_reason="broker summary-level expansion",
                        confidence=0.5,
                    )
                    refs = self._chapter_refs_from_memory_candidates(next_state.current_candidates)
        if not refs:
            chapter_state = self.memory_query_service.chapter_scan(
                conn,
                book_id=book_id,
                query=query,
                budget=MemoryQueryBudget(max_root_candidates=4, max_candidate_chars=budget.max_evidence_chars_per_request),
            )
            refs = self._chapter_refs_from_memory_candidates(chapter_state.current_candidates)
        elif query:
            chapter_state = self.memory_query_service.chapter_scan(
                conn,
                book_id=book_id,
                query=query,
                budget=MemoryQueryBudget(max_root_candidates=4, max_candidate_chars=budget.max_evidence_chars_per_request),
            )
            direct_refs = self._chapter_refs_from_memory_candidates(chapter_state.current_candidates)
            refs = self._merge_chapter_refs(direct_refs, refs)
        if not refs:
            return EvidenceBundle.missing(request, "chapter_refs")
        memory_bundle = self.memory_query_service.resolve_chapter_refs(conn, book_id=book_id, chapter_refs=refs)
        return self._bundle_from_memory(request, memory_bundle, status_if_empty="missing")

    def _expanded_query_for_detail_lookup(self, query: str) -> str:
        text = _text(query)
        additions: list[str] = []
        if re.search(r"歌词|唱.*什么|唱歌|歌(曲|词)?|生日快乐", text):
            additions.extend(["生日祝福", "祝福短信", "彩信", "语音", "录音", "草稿箱"])
        if re.search(r"短信|彩信|信件|邮件|留言|原句|原文|具体措辞|写了什么|说了什么", text):
            additions.extend(["原文", "措辞", "内容", "发送", "收到", "发现"])
        unique = [item for item in additions if item and item not in text]
        return f"{text} {' '.join(unique)}" if unique else text

    def _merge_chapter_refs(self, preferred_refs: Sequence[str], fallback_refs: Sequence[str]) -> list[str]:
        merged: list[str] = []
        seen: set[str] = set()
        for ref in [*preferred_refs, *fallback_refs]:
            text = self._normalize_chapter_ref(ref)
            if text and text not in seen:
                seen.add(text)
                merged.append(text)
        return merged[:4]

    def _normalize_chapter_ref(self, value: object) -> str:
        text = _text(value)
        if not text:
            return ""
        if text.isdigit():
            return f"chapter-{text}"
        match = re.fullmatch(r"(?:chapter|章节|第)?[-\s_]*(\d+)(?:章|幕)?", text, flags=re.IGNORECASE)
        if match:
            return f"chapter-{match.group(1)}"
        match = re.search(r"chapter-(\d+)", text, flags=re.IGNORECASE)
        if match:
            return f"chapter-{match.group(1)}"
        return text if text.startswith("chapter-") else ""

    def _chapter_refs_from_query(self, query: str, *, limit: int = 4) -> list[str]:
        refs: list[str] = []
        seen: set[str] = set()

        def add(number: str) -> None:
            ref = self._normalize_chapter_ref(number)
            if ref and ref not in seen:
                seen.add(ref)
                refs.append(ref)

        for start, end in re.findall(r"第?\s*(\d+)\s*[-~—–至到]\s*第?\s*(\d+)\s*[章节幕]?", query):
            try:
                start_i = int(start)
                end_i = int(end)
            except ValueError:
                continue
            if start_i <= 0 or end_i <= 0 or abs(end_i - start_i) > limit - 1:
                continue
            for number in range(min(start_i, end_i), max(start_i, end_i) + 1):
                add(str(number))
                if len(refs) >= limit:
                    return refs
        for match in re.findall(r"(?:chapter|章节|第)\s*[-_ ]?(\d+)\s*[章节幕]?", query, flags=re.IGNORECASE):
            add(match)
            if len(refs) >= limit:
                break
        return refs

    def _doc_ids_from_text(self, text: str, *, limit: int = 6) -> tuple[list[int], bool]:
        ids: list[int] = []
        seen: set[int] = set()
        too_broad = False

        def add(number: int) -> None:
            if number > 0 and number not in seen:
                seen.add(number)
                ids.append(number)

        for start, end in re.findall(
            r"(?:source[_ ]?doc(?:ument)?s?|docs?|documents?|文档)\s*[:：]?\s*(\d+)\s*[-~—–至到]\s*(\d+)",
            text,
            flags=re.IGNORECASE,
        ):
            try:
                start_i = int(start)
                end_i = int(end)
            except ValueError:
                continue
            span = abs(end_i - start_i) + 1
            if span > limit:
                too_broad = True
                continue
            for number in range(min(start_i, end_i), max(start_i, end_i) + 1):
                add(number)
        if too_broad:
            return [], True
        for match in re.findall(
            r"(?:source[_ ]?doc(?:ument)?s?|docs?|documents?|文档)\s*[:：]?\s*(\d+)",
            text,
            flags=re.IGNORECASE,
        ):
            add(int(match))
            if len(ids) >= limit:
                break
        return ids[:limit], too_broad

    def _chapter_refs_from_memory_candidates(self, candidates: Sequence[Mapping[str, Any]]) -> list[str]:
        refs: list[str] = []
        seen: set[str] = set()

        def add_ref(value: object) -> None:
            text = self._normalize_chapter_ref(value)
            if not text:
                return
            if not text.startswith("chapter-"):
                return
            if text not in seen:
                seen.add(text)
                refs.append(text)

        for item in candidates:
            add_ref(item.get("chapter_ref"))
            for child_ref in item.get("child_refs") or []:
                add_ref(child_ref)
            for title_index in item.get("source_title_indexes") or []:
                add_ref(title_index)
            add_ref(item.get("document_title_index"))
            for field_name in ("id", "page_id", "outline_segment_id"):
                match = re.search(r"chapter-(\d+)", str(item.get(field_name) or ""))
                if match:
                    add_ref(match.group(1))
        return refs[:4]

    def _resolve_raw_excerpt(
        self,
        conn: sqlite3.Connection,
        *,
        book_id: str,
        request: NarrativeInquiryRequest,
        budget: AnalyzerBudget,
    ) -> EvidenceBundle:
        lower_query = request.query.lower()
        if re.search(r"整本|全部原文|所有原文|全文|all documents|entire book", lower_query):
            return EvidenceBundle(
                request_id=request.request_id,
                request_type=request.request_type,
                query=request.query,
                status="blocked",
                fact_status="insufficient_context",
                missing_facets=["bounded_raw_excerpt_target"],
                trace=[{"operation": "raw_excerpt_blocked", "reason": "whole_book_request"}],
            )
        if not (request.read_reason and request.expected_confirmation and request.affects_analysis):
            return EvidenceBundle(
                request_id=request.request_id,
                request_type=request.request_type,
                query=request.query,
                status="blocked",
                fact_status="insufficient_context",
                missing_facets=["read_reason", "expected_confirmation", "affects_analysis"],
                trace=[{"operation": "raw_excerpt_blocked", "reason": "missing_read_plan_fields"}],
            )
        doc_ids = list(request.document_ids or request.source_doc_ids)
        if not doc_ids and request.chapter_refs:
            refs = [ref for ref in (self._normalize_chapter_ref(item) for item in request.chapter_refs) if ref]
            chapter_bundle = self.memory_query_service.resolve_chapter_refs(conn, book_id=book_id, chapter_refs=refs)
            doc_ids = list(chapter_bundle.source_doc_ids)
        if not doc_ids and request.chapter_read_plan:
            refs = [f"chapter-{item.document_title_index}" for item in request.chapter_read_plan if item.document_title_index > 0]
            chapter_bundle = self.memory_query_service.resolve_chapter_refs(conn, book_id=book_id, chapter_refs=refs)
            doc_ids = list(chapter_bundle.source_doc_ids)
        if not doc_ids:
            refs = self._chapter_refs_from_query(request.query)
            if refs:
                chapter_bundle = self.memory_query_service.resolve_chapter_refs(conn, book_id=book_id, chapter_refs=refs)
                doc_ids = list(chapter_bundle.source_doc_ids)
        if not doc_ids:
            doc_ids, too_broad = self._doc_ids_from_text(
                " ".join(
                    [
                        request.query,
                        request.purpose,
                        request.read_reason,
                        request.expected_confirmation,
                        request.affects_analysis,
                    ]
                ),
                limit=6,
            )
            if too_broad and not doc_ids:
                return EvidenceBundle(
                    request_id=request.request_id,
                    request_type=request.request_type,
                    query=request.query,
                    status="blocked",
                    fact_status="insufficient_context",
                    missing_facets=["bounded_raw_excerpt_target"],
                    trace=[{"operation": "raw_excerpt_blocked", "reason": "document_range_too_broad"}],
                )
        if not doc_ids:
            return EvidenceBundle.missing(request, "document_ids_or_chapter_refs")
        selected_doc_ids, selection_trace = self._select_raw_excerpt_doc_ids(
            conn,
            book_id=book_id,
            doc_ids=doc_ids,
            request=request,
            limit=6,
        )
        memory_bundle = self.memory_query_service.resolve_document_refs(
            conn,
            book_id=book_id,
            doc_ids=selected_doc_ids,
            excerpt_budget=budget.max_raw_excerpt_chars_per_request,
        )
        bundle = self._bundle_from_memory(request, memory_bundle, status_if_empty="missing")
        snippet_by_doc_id = self._raw_excerpt_snippets_by_doc_id(
            conn,
            book_id=book_id,
            doc_ids=selected_doc_ids,
            request=request,
            limit=budget.max_raw_excerpt_chars_per_request,
        )
        if snippet_by_doc_id:
            for item in bundle.evidence_items:
                doc_id = item.get("doc_id")
                if isinstance(doc_id, int) and doc_id in snippet_by_doc_id:
                    item["summary"] = snippet_by_doc_id[doc_id]
            for excerpt in bundle.excerpts:
                doc_id = excerpt.get("doc_id")
                if isinstance(doc_id, int) and doc_id in snippet_by_doc_id:
                    excerpt["text"] = snippet_by_doc_id[doc_id]
        for excerpt in bundle.excerpts:
            excerpt["text"] = _safe_excerpt(str(excerpt.get("text") or ""), limit=budget.max_raw_excerpt_chars_per_request)
            excerpt["truncated"] = True
        bundle.trace.append(
            {
                "operation": "raw_excerpt_budget",
                "excerpt_budget": budget.max_raw_excerpt_chars_per_request,
                "read_reason": request.read_reason,
                "expected_confirmation": request.expected_confirmation,
                "affects_analysis": request.affects_analysis,
            }
        )
        if selection_trace:
            bundle.trace.append(selection_trace)
        if snippet_by_doc_id:
            bundle.trace.append(
                {
                    "operation": "raw_excerpt_query_snippets",
                    "doc_ids": sorted(snippet_by_doc_id),
                }
            )
        return bundle

    def _raw_excerpt_snippets_by_doc_id(
        self,
        conn: sqlite3.Connection,
        *,
        book_id: str,
        doc_ids: Sequence[int],
        request: NarrativeInquiryRequest,
        limit: int,
    ) -> dict[int, str]:
        priority_terms, context_terms = self._raw_excerpt_filter_terms(request)
        terms = [*priority_terms, *context_terms]
        clean_ids = [int(item) for item in doc_ids if int(item) > 0]
        if not clean_ids or not terms:
            return {}
        placeholders = ",".join("?" for _ in clean_ids)
        rows = conn.execute(
            f"""
            SELECT doc_id, content
            FROM documents
            WHERE book_id = ? AND doc_id IN ({placeholders})
            ORDER BY doc_id
            """,
            (book_id, *clean_ids),
        ).fetchall()
        snippets: dict[int, str] = {}
        for row in rows:
            text = str(row["content"] or "")
            if not text:
                continue
            snippets[int(row["doc_id"])] = self._text_search_snippet(
                text,
                priority_terms or terms,
                limit=max(80, int(limit or 80)),
            )
        return snippets

    def _select_raw_excerpt_doc_ids(
        self,
        conn: sqlite3.Connection,
        *,
        book_id: str,
        doc_ids: Sequence[int],
        request: NarrativeInquiryRequest,
        limit: int,
    ) -> tuple[list[int], dict[str, Any]]:
        clean_ids: list[int] = []
        seen: set[int] = set()
        for item in doc_ids:
            try:
                doc_id = int(item)
            except (TypeError, ValueError):
                continue
            if doc_id <= 0 or doc_id in seen:
                continue
            seen.add(doc_id)
            clean_ids.append(doc_id)
        if len(clean_ids) <= limit:
            return clean_ids[:limit], {
                "operation": "raw_excerpt_doc_selection",
                "strategy": "bounded_order",
                "input_doc_count": len(clean_ids),
                "selected_doc_ids": clean_ids[:limit],
            }

        priority_terms, _context_terms = self._raw_excerpt_filter_terms(request)
        if not priority_terms:
            return clean_ids[:limit], {
                "operation": "raw_excerpt_doc_selection",
                "strategy": "bounded_page_no_filter_terms",
                "input_doc_count": len(clean_ids),
                "selected_doc_ids": clean_ids[:limit],
                "next_doc_offset": limit if len(clean_ids) > limit else None,
            }

        placeholders = ",".join("?" for _ in clean_ids)
        rows = conn.execute(
            f"""
            SELECT doc_id, content, document_title
            FROM documents
            WHERE book_id = ? AND doc_id IN ({placeholders})
            ORDER BY doc_id
            """,
            (book_id, *clean_ids),
        ).fetchall()
        row_by_id = {int(row["doc_id"]): row for row in rows}
        matched_doc_ids: list[int] = []
        matched_terms_by_doc_id: dict[int, list[str]] = {}
        for doc_id in clean_ids:
            row = row_by_id.get(doc_id)
            text = " ".join([str(row["document_title"] or ""), str(row["content"] or "")]) if row is not None else ""
            matched = self._matched_raw_excerpt_terms(text, priority_terms)
            if matched:
                matched_doc_ids.append(doc_id)
                matched_terms_by_doc_id[doc_id] = matched

        if not matched_doc_ids:
            return clean_ids[:limit], {
                "operation": "raw_excerpt_doc_selection",
                "strategy": "bounded_page_no_filter_hits",
                "input_doc_count": len(clean_ids),
                "selected_doc_ids": clean_ids[:limit],
                "filter_terms": priority_terms[:12],
                "next_doc_offset": limit if len(clean_ids) > limit else None,
            }

        selected = matched_doc_ids[:limit]
        return selected[:limit], {
            "operation": "raw_excerpt_doc_selection",
            "strategy": "bounded_keyword_filter_preserve_order",
            "input_doc_count": len(clean_ids),
            "matched_doc_count": len(matched_doc_ids),
            "selected_doc_ids": selected[:limit],
            "filter_terms": priority_terms[:12],
            "matched_terms_by_doc_id": {str(doc_id): matched_terms_by_doc_id[doc_id][:8] for doc_id in selected[:limit]},
            "next_match_offset": limit if len(matched_doc_ids) > limit else None,
        }

    def _raw_excerpt_filter_terms(self, request: NarrativeInquiryRequest) -> tuple[list[str], list[str]]:
        metadata = request.metadata if isinstance(request.metadata, Mapping) else {}
        filter_terms = [
            *_string_list(metadata.get("terms") or metadata.get("keywords")),
            *_string_list(request.excerpt_focus),
            *self._text_search_terms(request),
        ]
        context_text = " ".join(
            item
            for item in [
                request.purpose,
                request.read_reason,
                request.expected_confirmation,
                request.affects_analysis,
                request.expected_depth,
            ]
            if item
        )
        return self._dedupe_limited_terms(filter_terms, limit=24), self._dedupe_limited_terms(_tokens(context_text), limit=24)

    def _dedupe_limited_terms(self, terms: Sequence[str], *, limit: int) -> list[str]:
        deduped: list[str] = []
        seen: set[str] = set()
        for term in terms:
            text = _text(term)
            if not text or text in seen:
                continue
            seen.add(text)
            deduped.append(text)
        return deduped[:limit]

    def _matched_raw_excerpt_terms(self, text: str, terms: Sequence[str]) -> list[str]:
        haystack = text.casefold()
        matched: list[str] = []
        for term in terms:
            needle = term.casefold()
            if not needle or needle not in haystack:
                continue
            matched.append(term)
        return matched

    def _bundle_from_memory(
        self,
        request: NarrativeInquiryRequest,
        memory_bundle: MemoryEvidenceBundle,
        *,
        status_if_empty: str,
    ) -> EvidenceBundle:
        has_evidence = bool(memory_bundle.evidence_items or memory_bundle.excerpts)
        fact_status = "confirmed" if memory_bundle.status == "committed" else "candidate"
        if not has_evidence:
            fact_status = "missing"
        evidence_items = [dict(item) for item in memory_bundle.evidence_items]
        if request.request_type == "chapter_summary":
            for item in evidence_items:
                item.setdefault("evidence_derivation", "summary_derived_chapter_summary")
                item.setdefault("canonical_fact_status", "candidate_requires_raw_excerpt_for_conflicts")
                item.setdefault(
                    "evidence_warning",
                    "Chapter summaries are compact narrative memory. If they conflict with other evidence on "
                    "participants, counts, costs, causality, timeline, or scene presence, confirm with raw excerpt.",
                )
        return EvidenceBundle(
            request_id=request.request_id,
            request_type=request.request_type,
            query=request.query or request.name or request.concept,
            status="found" if has_evidence else status_if_empty,  # type: ignore[arg-type]
            fact_status=fact_status,  # type: ignore[arg-type]
            evidence_items=evidence_items,
            chapter_refs=memory_bundle.chapter_refs,
            source_doc_ids=memory_bundle.source_doc_ids,
            excerpts=[
                {
                    **item,
                    "excerpt_type": "selected_raw_excerpt",
                    "truncated": True,
                }
                for item in memory_bundle.excerpts
            ],
            sources=memory_bundle.sources,
            missing_facets=[] if has_evidence else ["memory_evidence"],
            trace=[
                *memory_bundle.trace,
                {
                    "operation": "narrative_inquiry_route",
                    "resolver": "NarrativeMemoryQueryService",
                    "request_type": request.request_type,
                },
            ],
        )

    def _resolve_character_profile(
        self,
        conn: sqlite3.Connection,
        *,
        book_id: str,
        request: NarrativeInquiryRequest,
        budget: AnalyzerBudget,
    ) -> EvidenceBundle:
        target = request.name or request.query
        target_text = _text(target)
        target_tokens = _tokens(target_text)
        query_text = " ".join(
            item
            for item in [
                target_text,
                request.query,
                request.purpose,
                request.expected_depth,
            ]
            if item
        )
        query_tokens = _expanded_query_tokens(query_text)
        metadata = request.metadata if isinstance(request.metadata, Mapping) else {}
        story_events_offset_raw = _metadata_int(metadata, "story_events_offset", "experience_offset", default=-1)
        story_events_offset = max(0, story_events_offset_raw)
        story_events_char_budget = max(
            160,
            min(4096, _metadata_int(metadata, "story_events_char_budget", "experience_char_budget", default=4096)),
        )
        page_story_events = story_events_offset_raw >= 0
        try:
            rows = self.character_profiles_repo.list_by_book(conn, book_id=book_id)
        except sqlite3.OperationalError:
            rows = []
        scored_matches: list[tuple[int, int, dict[str, Any]]] = []
        for row in rows:
            aliases = [str(item) for item in _json_list(row["aliases_json"])]
            canonical = str(row["canonical_name"] or "")
            names = [canonical, *aliases]
            name_score = 0
            if target_text:
                if target_text == canonical:
                    name_score += 100
                if len(aliases) <= 16 and target_text in aliases:
                    name_score += 90
                if any(target_text and target_text in name for name in names):
                    name_score += 45
            name_haystack = " ".join(names)
            profile_haystack = " ".join(
                [
                    str(row["profile_summary_md"] or ""),
                    str(row["recent_activity_json"] or ""),
                    str(row["relationships_json"] or ""),
                ]
            )
            token_name_score = 8 * sum(1 for token in target_tokens if token in name_haystack)
            token_profile_score = sum(1 for token in target_tokens if token in profile_haystack)
            score = name_score + token_name_score + token_profile_score
            if target_text and score <= 0:
                continue
            relationships = self._select_relevant_profile_items(
                _json_list(row["relationships_json"]),
                query_text=query_text,
                query_tokens=query_tokens,
                target_names=[target_text, canonical, *aliases],
                limit=3,
                item_char_limit=220,
            )
            recent_activity = self._select_relevant_profile_items(
                _json_list(row["recent_activity_json"]),
                query_text=query_text,
                query_tokens=query_tokens,
                target_names=[target_text, canonical, *aliases],
                limit=3,
                item_char_limit=220,
            )
            all_story_events = _json_list(row["story_events_json"])
            story_events_page = {}
            if page_story_events:
                story_events, story_events_page = self._select_profile_story_events_page(
                    all_story_events,
                    offset=story_events_offset,
                    char_budget=story_events_char_budget,
                )
            else:
                story_events = self._select_relevant_profile_items(
                    all_story_events,
                    query_text=query_text,
                    query_tokens=query_tokens,
                    target_names=[target_text, canonical, *aliases],
                    limit=4,
                    item_char_limit=260,
                )
                story_events_page = {
                    "mode": "query_relevant",
                    "total": len(all_story_events),
                    "offset": 0,
                    "next_offset": None,
                    "has_more": False,
                    "char_budget": 0,
                }
            scored_matches.append(
                (
                    score,
                    int(row["importance_score"] or 0),
                    {
                        "character_id": str(row["character_id"]),
                        "canonical_name": canonical,
                        "aliases": aliases[:8],
                        "summary": _safe_excerpt(
                            str(row["profile_summary_md"] or ""),
                            limit=min(480, budget.max_evidence_chars_per_request // 2),
                        ),
                        "relationships": relationships,
                        "recent_activity": recent_activity,
                        "story_events": story_events,
                        "story_events_page": story_events_page,
                        "evidence_level": str(row["evidence_level"] or "inferred"),
                        "match_score": score,
                    },
                )
            )
        exact_matches = [item for item in scored_matches if item[0] >= 90]
        if exact_matches:
            scored_matches = exact_matches
        matches = [
            item
            for _, _, item in sorted(
                scored_matches,
                key=lambda value: (-value[0], -value[1], str(value[2].get("canonical_name") or "")),
            )
        ][:3]
        return EvidenceBundle(
            request_id=request.request_id,
            request_type=request.request_type,
            query=request.query or target,
            status="found" if matches else "missing",
            fact_status="confirmed" if matches and all(item["evidence_level"] == "confirmed" for item in matches) else ("candidate" if matches else "missing"),
            evidence_items=matches[:4],
            sources=[
                {"type": "character_profile", "path": f"sqlite:character_profiles:{item['character_id']}", "status": item["evidence_level"]}
                for item in matches[:4]
            ],
            missing_facets=[] if matches else ["character_profile"],
            trace=[
                {
                    "operation": "character_profile_resolver",
                    "source_scope": "character_memory",
                    "story_events_mode": "offset_page" if page_story_events else "query_relevant",
                    "story_events_offset": story_events_offset if page_story_events else None,
                    "story_events_char_budget": story_events_char_budget if page_story_events else None,
                }
            ],
        )

    def _select_relevant_profile_items(
        self,
        items: Sequence[Any],
        *,
        query_text: str,
        query_tokens: Sequence[str],
        target_names: Sequence[str],
        limit: int,
        item_char_limit: int,
    ) -> list[str]:
        if not items:
            return []
        clean_targets = [name for name in (_text(item) for item in target_names) if name]
        scored: list[tuple[int, int, Any]] = []
        for index, item in enumerate(items):
            haystack = _profile_item_text(item)
            score = 0
            score += 3 * sum(1 for token in query_tokens if token and token in haystack)
            score += 2 * sum(1 for name in clean_targets if name and name in haystack)
            if isinstance(item, Mapping):
                participants = item.get("participants")
                if isinstance(participants, Sequence) and not isinstance(participants, (str, bytes)):
                    participant_text = " ".join(str(value) for value in participants)
                    score += 4 * sum(1 for name in clean_targets if name and name in participant_text)
                target_name = str(item.get("target_name") or "")
                score += 5 * sum(1 for token in query_tokens if token and token in target_name)
            if query_text and query_text in haystack:
                score += 12
            scored.append((score, index, item))
        selected = sorted(scored, key=lambda value: (-value[0], value[1]))[:limit]
        if not any(score > 0 for score, _index, _item in selected):
            selected = scored[:limit]
        return [
            _safe_excerpt(_profile_item_text(item), limit=item_char_limit)
            for _score, _index, item in selected
        ]

    def _select_profile_story_events_page(
        self,
        items: Sequence[Any],
        *,
        offset: int,
        char_budget: int,
    ) -> tuple[list[str], dict[str, Any]]:
        total = len(items)
        start = min(max(0, offset), total)
        selected: list[str] = []
        used_chars = 0
        next_offset = start
        for index in range(start, total):
            text = _profile_story_event_text(items[index])
            if not text:
                next_offset = index + 1
                continue
            if not selected and len(text) > char_budget:
                selected.append(_safe_excerpt(text, limit=char_budget))
                used_chars = len(selected[-1])
                next_offset = index + 1
                break
            if selected and used_chars + len(text) > char_budget:
                next_offset = index
                break
            selected.append(text)
            used_chars += len(text)
            next_offset = index + 1
        has_more = next_offset < total
        return selected, {
            "mode": "offset_page",
            "offset": start,
            "next_offset": next_offset if has_more else None,
            "total": total,
            "has_more": has_more,
            "char_budget": char_budget,
            "chars_returned": used_chars,
        }

    def _resolve_world_concept(
        self,
        conn: sqlite3.Connection,
        *,
        book_id: str,
        request: NarrativeInquiryRequest,
        budget: AnalyzerBudget,
    ) -> EvidenceBundle:
        paths = self._asset_paths(conn, book_id=book_id, field_names=("world_summary_path", "world_markdown_path"))
        query_tokens = _tokens(request.concept or request.query)
        items = []
        sources = []
        for path in paths:
            if not path.exists():
                continue
            text = path.read_text(encoding="utf-8", errors="replace")
            lines = [line.strip("#- ") for line in text.splitlines() if line.strip()]
            relevant = [line for line in lines if any(token in line for token in query_tokens)]
            if not relevant:
                relevant = lines[:4]
            summary = _safe_excerpt(" ".join(relevant[:6]), limit=budget.max_evidence_chars_per_request)
            if summary:
                items.append({"concept": request.concept or request.query, "summary": summary})
                sources.append({"type": "world_memory", "path": str(path), "status": "structured_state"})
        return EvidenceBundle(
            request_id=request.request_id,
            request_type=request.request_type,
            query=request.query or request.concept,
            status="found" if items else "missing",
            fact_status="confirmed" if items else "missing",
            evidence_items=items[:3],
            sources=sources[:3],
            missing_facets=[] if items else ["world_concept"],
            trace=[{"operation": "world_concept_resolver", "source_scope": "world_memory"}],
        )

    def _resolve_source_arc(self, *, book_id: str, request: NarrativeInquiryRequest, budget: AnalyzerBudget) -> EvidenceBundle:
        arc_path = self.repo_root / ".memory" / "arcs"
        items = []
        sources = []
        paths = [arc_path / f"{book_id}.source_arc_map.json"]
        if not paths[0].exists():
            paths = sorted(arc_path.glob("*.source_arc_map.json"))[:8]
        for path in paths:
            payload = self._load_json(path)
            arcs = payload.get("arcs") or payload.get("source_arcs") or []
            for arc in arcs if isinstance(arcs, list) else []:
                if not isinstance(arc, Mapping):
                    continue
                haystack = json.dumps(arc, ensure_ascii=False)
                if request.query and not any(token in haystack for token in _tokens(request.query)):
                    continue
                items.append(
                    {
                        "arc_id": str(arc.get("source_arc_id") or arc.get("id") or ""),
                        "title": str(arc.get("source_arc_title") or arc.get("title") or ""),
                        "chapter_range": f"{arc.get('start_document_title_index', '')}-{arc.get('end_document_title_index', '')}",
                        "summary": _safe_excerpt(haystack, limit=budget.max_evidence_chars_per_request),
                    }
                )
                sources.append({"type": "source_arc", "path": str(path), "status": str(arc.get("status") or "committed")})
        return EvidenceBundle(
            request_id=request.request_id,
            request_type=request.request_type,
            query=request.query,
            status="found" if items else "missing",
            fact_status="confirmed" if items else "missing",
            evidence_items=items[:4],
            sources=sources[:4],
            missing_facets=[] if items else ["source_arc"],
            trace=[{"operation": "source_arc_resolver"}],
        )

    def _resolve_open_threads(
        self,
        conn: sqlite3.Connection,
        *,
        book_id: str,
        request: NarrativeInquiryRequest,
        budget: AnalyzerBudget,
    ) -> EvidenceBundle:
        paths = self._asset_paths(conn, book_id=book_id, field_names=("outline_markdown_path",))
        items = []
        sources = []
        for path in paths:
            if not path.exists():
                continue
            text = path.read_text(encoding="utf-8", errors="replace")
            lines = [line.strip() for line in text.splitlines() if line.strip()]
            unresolved = [line.lstrip("- ").strip() for line in lines if re.search(r"未解|未决|伏笔|悬而未决|问题", line)]
            if not unresolved:
                unresolved = [line.lstrip("- ").strip() for line in lines if line.startswith("- ")][:8]
            for index, line in enumerate(unresolved[:8], start=1):
                items.append({"thread_id": f"thread-{index:02d}", "summary": _safe_excerpt(line, limit=240), "status_hint": "unresolved"})
            sources.append({"type": "story_outline", "path": str(path), "status": "structured_state"})
        return EvidenceBundle(
            request_id=request.request_id,
            request_type=request.request_type,
            query=request.query,
            status="found" if items else "missing",
            fact_status="candidate" if items else "missing",
            evidence_items=items,
            sources=sources,
            missing_facets=[] if items else ["open_threads"],
            trace=[{"operation": "open_threads_resolver"}],
        )

    def _resolve_structure_pattern(
        self,
        conn: sqlite3.Connection,
        *,
        request: NarrativeInquiryRequest,
        budget: AnalyzerBudget,
    ) -> EvidenceBundle:
        items = []
        try:
            hits = self.fragment_cards_repo.search_fts(conn, query_text=request.query, limit=5, representatives_only=True)
            cards = self.fragment_cards_repo.list_by_fragment_ids(conn, fragment_ids=[hit.fragment_id for hit in hits])
        except sqlite3.OperationalError:
            cards = []
        for card in cards:
            items.append(
                {
                    "pattern_id": card.fragment_id,
                    "summary": _safe_excerpt(card.content_summary, limit=budget.max_evidence_chars_per_request // 2),
                    "structure_function": card.narrative_function_text,
                    "source_kind": "creative_kb.fragment_card",
                }
            )
        return EvidenceBundle(
            request_id=request.request_id,
            request_type=request.request_type,
            query=request.query,
            status="found" if items else "missing",
            fact_status="candidate" if items else "missing",
            evidence_items=items[:5],
            sources=[
                {"type": "creative_kb", "path": f"sqlite:fragment_cards:{item['pattern_id']}", "status": "pattern_not_fact"}
                for item in items[:5]
            ],
            missing_facets=[] if items else ["structure_pattern"],
            trace=[{"operation": "structure_pattern_resolver", "fact_policy": "not_fact_memory"}],
        )

    def _asset_paths(self, conn: sqlite3.Connection, *, book_id: str, field_names: Sequence[str]) -> list[Path]:
        try:
            assets = self.assets_repo.get(conn, book_id=book_id)
        except sqlite3.OperationalError:
            assets = None
        paths: list[Path] = []
        if assets is None:
            return paths
        for field_name in field_names:
            value = _text(assets[field_name])
            if not value:
                continue
            path = Path(value).expanduser()
            paths.append(path if path.is_absolute() else (self.repo_root / path).resolve())
        return paths

    def _load_json(self, path: Path) -> dict[str, Any]:
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return {}
        return dict(payload) if isinstance(payload, Mapping) else {}

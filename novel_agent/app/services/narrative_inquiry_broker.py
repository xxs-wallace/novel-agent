from __future__ import annotations

import json
import re
import sqlite3
from pathlib import Path
from typing import Any, Mapping, Sequence

from ..repos.assets_repo import AssetsRepo
from ..repos.character_profiles_repo import CharacterProfilesRepo
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
        character_profiles_repo: CharacterProfilesRepo | None = None,
        fragment_cards_repo: FragmentCardsRepo | None = None,
        narrative_index_facade: NarrativeIndexFacade | None = None,
    ) -> None:
        self.repo_root = repo_root.expanduser().resolve()
        self.memory_query_service = memory_query_service or NarrativeMemoryQueryService(repo_root=self.repo_root)
        self.assets_repo = assets_repo or AssetsRepo()
        self.character_profiles_repo = character_profiles_repo or CharacterProfilesRepo()
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
        refs = list(request.chapter_refs)
        if not refs:
            refs = [f"chapter-{match}" for match in re.findall(r"\d+", request.query)[:4]]
        if not refs:
            state = self.memory_query_service.root_scan(conn, book_id=book_id, query=request.query, budget=MemoryQueryBudget(max_root_candidates=4))
            if state.current_candidates:
                next_state = self.memory_query_service.drill_down(
                    conn,
                    book_id=book_id,
                    state=state,
                    selected_ids=[str(item.get("id") or item.get("page_id")) for item in state.current_candidates[:2]],
                    query_suffix="定位相关章节摘要",
                    selection_reason="broker summary-level expansion",
                    confidence=0.5,
                )
                refs = [str(item.get("chapter_ref") or item.get("id") or "") for item in next_state.current_candidates if item.get("page_type") == "chapter"][:4]
        if not refs:
            return EvidenceBundle.missing(request, "chapter_refs")
        memory_bundle = self.memory_query_service.resolve_chapter_refs(conn, book_id=book_id, chapter_refs=refs)
        return self._bundle_from_memory(request, memory_bundle, status_if_empty="missing")

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
            chapter_bundle = self.memory_query_service.resolve_chapter_refs(conn, book_id=book_id, chapter_refs=request.chapter_refs)
            doc_ids = list(chapter_bundle.source_doc_ids)
        if not doc_ids and request.chapter_read_plan:
            refs = [f"chapter-{item.document_title_index}" for item in request.chapter_read_plan if item.document_title_index > 0]
            chapter_bundle = self.memory_query_service.resolve_chapter_refs(conn, book_id=book_id, chapter_refs=refs)
            doc_ids = list(chapter_bundle.source_doc_ids)
        if not doc_ids:
            return EvidenceBundle.missing(request, "document_ids_or_chapter_refs")
        memory_bundle = self.memory_query_service.resolve_document_refs(
            conn,
            book_id=book_id,
            doc_ids=doc_ids[:6],
            excerpt_budget=budget.max_raw_excerpt_chars_per_request,
        )
        bundle = self._bundle_from_memory(request, memory_bundle, status_if_empty="missing")
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
        return bundle

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
        return EvidenceBundle(
            request_id=request.request_id,
            request_type=request.request_type,
            query=request.query or request.name or request.concept,
            status="found" if has_evidence else status_if_empty,  # type: ignore[arg-type]
            fact_status=fact_status,  # type: ignore[arg-type]
            evidence_items=memory_bundle.evidence_items,
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
                if target_text in aliases:
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
                        "relationships": [
                            _safe_excerpt(json.dumps(item, ensure_ascii=False) if isinstance(item, Mapping) else str(item), limit=180)
                            for item in _json_list(row["relationships_json"])[:2]
                        ],
                        "recent_activity": [
                            _safe_excerpt(json.dumps(item, ensure_ascii=False) if isinstance(item, Mapping) else str(item), limit=180)
                            for item in _json_list(row["recent_activity_json"])[:2]
                        ],
                        "story_events": [
                            _safe_excerpt(json.dumps(item, ensure_ascii=False) if isinstance(item, Mapping) else str(item), limit=180)
                            for item in _json_list(row["story_events_json"])[:2]
                        ],
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
            trace=[{"operation": "character_profile_resolver", "source_scope": "character_memory"}],
        )

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

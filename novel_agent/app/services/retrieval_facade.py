from __future__ import annotations

import re
import sqlite3

from ..repos.fragment_cards_repo import FragmentCardsRepo
from ..repos.fragment_clusters_repo import FragmentClustersRepo
from ..schemas.creative_kb_schema import (
    CreativeKBRetrievalResult,
    ExpandedReferenceFragment,
    FragmentCard,
    SceneBrief,
)
from ..schemas.orchestration_schema import CreativeKBRetrievalInput, RetrievalContext
from .coarse_retrieval_service import CoarseRetrievalService
from .rerank_service import RerankService
from .scene_brief_service import SceneBriefService

TOKEN_PATTERN = re.compile(r"[\w\u4e00-\u9fff]+")


class RetrievalFacade:
    def __init__(
        self,
        *,
        scene_brief_service: SceneBriefService | None = None,
        coarse_retrieval_service: CoarseRetrievalService | None = None,
        rerank_service: RerankService | None = None,
        fragment_cards_repo: FragmentCardsRepo | None = None,
        fragment_clusters_repo: FragmentClustersRepo | None = None,
    ) -> None:
        self.scene_brief_service = scene_brief_service or SceneBriefService(model_client=None)
        self.coarse_retrieval_service = coarse_retrieval_service or CoarseRetrievalService()
        self.rerank_service = rerank_service or RerankService()
        self.fragment_cards_repo = fragment_cards_repo or FragmentCardsRepo()
        self.fragment_clusters_repo = fragment_clusters_repo or FragmentClustersRepo()

    def build_scene_brief_and_retrieve(
        self,
        conn: sqlite3.Connection,
        *,
        retrieval_input: CreativeKBRetrievalInput,
        scene_brief: SceneBrief | None = None,
        include_coarse_result: bool = False,
        expand_reference_fragments: bool = False,
    ) -> CreativeKBRetrievalResult:
        resolved_scene_brief = self.scene_brief_service.build(retrieval_input, scene_brief=scene_brief)
        return self.retrieve_reference_fragments(
            conn,
            scene_brief=resolved_scene_brief,
            retrieval_context=retrieval_input.retrieval_context,
            anchor_context=retrieval_input.anchor_context,
            recent_window_summary=retrieval_input.recent_window_summary,
            include_coarse_result=include_coarse_result,
            expand_reference_fragments=expand_reference_fragments,
        )

    def retrieve_reference_fragments(
        self,
        conn: sqlite3.Connection,
        *,
        scene_brief: SceneBrief,
        retrieval_context: RetrievalContext | None = None,
        anchor_context: str = "",
        recent_window_summary: str = "",
        include_coarse_result: bool = False,
        expand_reference_fragments: bool = False,
    ) -> CreativeKBRetrievalResult:
        _ = retrieval_context
        fragment_cards = self.fragment_cards_repo.list_all(conn)
        fragment_clusters = self.fragment_clusters_repo.list_all(conn)
        fts_fragment_ids = self._search_fts_fragment_ids(conn, scene_brief=scene_brief)
        coarse_result = self.coarse_retrieval_service.retrieve(
            scene_brief=scene_brief,
            fragment_cards=fragment_cards,
            fragment_clusters=fragment_clusters,
            fts_fragment_ids=fts_fragment_ids,
        )
        candidates = self._load_cards_in_order(conn, coarse_result.candidate_fragment_ids)
        rerank_result = self.rerank_service.rerank(
            scene_brief=scene_brief,
            candidates=candidates,
            anchor_context=anchor_context,
            recent_window_summary=recent_window_summary,
        )
        reference_fragments = (
            self._expand_reference_fragments(conn, rerank_result.selected_fragment_ids)
            if expand_reference_fragments
            else []
        )
        return CreativeKBRetrievalResult(
            scene_brief=scene_brief,
            rerank_result=rerank_result,
            coarse_result=coarse_result if include_coarse_result else None,
            reference_fragments=reference_fragments,
        )

    def _search_fts_fragment_ids(
        self,
        conn: sqlite3.Connection,
        *,
        scene_brief: SceneBrief,
    ) -> list[str]:
        query_text = self._build_fts_query(scene_brief)
        if not query_text:
            return []
        hits = self.fragment_cards_repo.search_fts(
            conn,
            query_text=query_text,
            limit=max(self.coarse_retrieval_service.candidate_limit * 2, 24),
        )
        return [hit.fragment_id for hit in hits]

    def _build_fts_query(self, scene_brief: SceneBrief) -> str:
        tokens: list[str] = []
        for part in [
            scene_brief.scene_objective,
            scene_brief.emotional_goal,
            scene_brief.conflict_goal,
            *scene_brief.narrative_function,
            *scene_brief.emotion_mode,
            *scene_brief.style_need,
            *scene_brief.preferred_tags,
        ]:
            for token in TOKEN_PATTERN.findall(part):
                normalized = token.strip().lower()
                if len(normalized) <= 1 or normalized in tokens:
                    continue
                tokens.append(normalized)
        return " ".join(tokens[:12])

    def _load_cards_in_order(
        self,
        conn: sqlite3.Connection,
        fragment_ids: list[str],
    ) -> list[FragmentCard]:
        if not fragment_ids:
            return []
        cards = self.fragment_cards_repo.list_by_fragment_ids(conn, fragment_ids=fragment_ids)
        cards_by_id = {card.fragment_id: card for card in cards}
        return [cards_by_id[fragment_id] for fragment_id in fragment_ids if fragment_id in cards_by_id]

    def _expand_reference_fragments(
        self,
        conn: sqlite3.Connection,
        fragment_ids: list[str],
    ) -> list[ExpandedReferenceFragment]:
        cards = self._load_cards_in_order(conn, fragment_ids)
        return [
            ExpandedReferenceFragment(
                fragment_id=card.fragment_id,
                doc_id=card.doc_id,
                source_path=card.source_path,
                source_excerpt=card.source_excerpt,
                content_summary=card.content_summary,
                style_profile_text=card.style_profile_text,
            )
            for card in cards
        ]

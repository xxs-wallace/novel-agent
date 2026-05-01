from __future__ import annotations

import re
from dataclasses import dataclass

from ..schemas.creative_kb_schema import CoarseRetrievalResult, FragmentCard, FragmentCluster, SceneBrief

TOKEN_PATTERN = re.compile(r"[\w\u4e00-\u9fff]+")


@dataclass(slots=True)
class _ScoredCandidate:
    card: FragmentCard
    score: float
    matched_by: list[str]


class CoarseRetrievalService:
    """Applies low-cost candidate filtering before rerank."""

    def __init__(self, *, candidate_limit: int = 24) -> None:
        self.candidate_limit = max(12, min(candidate_limit, 40))

    def retrieve(
        self,
        *,
        scene_brief: SceneBrief,
        fragment_cards: list[FragmentCard],
        fragment_clusters: list[FragmentCluster] | None = None,
        fts_fragment_ids: list[str] | None = None,
    ) -> CoarseRetrievalResult:
        self._validate_scene_brief(scene_brief)
        if not fragment_cards:
            return CoarseRetrievalResult()

        cards_by_id = {card.fragment_id: card for card in fragment_cards if card.fragment_id}
        representatives = self._build_representative_map(fragment_clusters or [])
        fts_hit_set = {fragment_id for fragment_id in (fts_fragment_ids or []) if fragment_id in cards_by_id}

        scored: list[_ScoredCandidate] = []
        for card in fragment_cards:
            candidate = self._score_card(card=card, scene_brief=scene_brief, fts_hit_set=fts_hit_set)
            if candidate is None:
                continue
            scored.append(candidate)

        if not scored:
            return CoarseRetrievalResult()

        scored.sort(
            key=lambda item: (
                item.score,
                1 if item.card.is_cluster_representative else 0,
                item.card.transferability_score,
                item.card.fragment_id,
            ),
            reverse=True,
        )

        deduped = self._dedupe_by_cluster(scored=scored, representatives=representatives, cards_by_id=cards_by_id)
        selected = deduped[: self.candidate_limit]

        return CoarseRetrievalResult(
            candidate_fragment_ids=[item.card.fragment_id for item in selected],
            matched_by={item.card.fragment_id: item.matched_by for item in selected},
            filtered_cluster_ids=[
                item.card.cluster_id
                for item in selected
                if item.card.cluster_id
            ],
            coarse_scores={item.card.fragment_id: round(item.score, 4) for item in selected},
        )

    def _score_card(
        self,
        *,
        card: FragmentCard,
        scene_brief: SceneBrief,
        fts_hit_set: set[str],
    ) -> _ScoredCandidate | None:
        matched_by: list[str] = []
        primary_matched_by: list[str] = []
        score = 0.0

        if card.fragment_id in fts_hit_set:
            matched_by.append("fts")
            primary_matched_by.append("fts")
            score += 0.35

        summary_overlap = self._token_overlap(
            self._collect_query_text(scene_brief),
            self._collect_card_text(card),
        )
        if summary_overlap > 0:
            matched_by.append("summary_match")
            primary_matched_by.append("summary_match")
            score += min(summary_overlap, 1.0) * 0.30

        narrative_overlap = self._list_overlap(scene_brief.narrative_function, card.narrative_function)
        if narrative_overlap > 0:
            matched_by.append("narrative_function")
            primary_matched_by.append("narrative_function")
            score += narrative_overlap * 0.18

        emotion_overlap = self._list_overlap(scene_brief.emotion_mode, card.emotion_tags + card.expression_mode_tags)
        if emotion_overlap > 0:
            matched_by.append("emotion_mechanism_text")
            primary_matched_by.append("emotion_mechanism_text")
            score += emotion_overlap * 0.12

        temperament_overlap = self._list_overlap(scene_brief.character_temperament, card.character_temperament)
        if temperament_overlap > 0:
            matched_by.append("character_temperament")
            primary_matched_by.append("character_temperament")
            score += temperament_overlap * 0.08

        relation_overlap = self._list_overlap(scene_brief.relationship_state, card.relationship_state)
        if relation_overlap > 0:
            matched_by.append("relationship_state")
            primary_matched_by.append("relationship_state")
            score += relation_overlap * 0.10

        style_overlap = self._token_overlap(scene_brief.style_need, [card.style_profile_text])
        if style_overlap > 0:
            matched_by.append("style_profile_text")
            primary_matched_by.append("style_profile_text")
            score += min(style_overlap, 1.0) * 0.08

        preferred_tag_overlap = self._list_overlap(scene_brief.preferred_tags, card.preferred_tags)
        if preferred_tag_overlap > 0:
            matched_by.append("preferred_tags")
            score += preferred_tag_overlap * 0.05

        if score <= 0 or not primary_matched_by:
            return None
        return _ScoredCandidate(card=card, score=min(score, 1.0), matched_by=matched_by)

    def _dedupe_by_cluster(
        self,
        *,
        scored: list[_ScoredCandidate],
        representatives: dict[str, str],
        cards_by_id: dict[str, FragmentCard],
    ) -> list[_ScoredCandidate]:
        out: list[_ScoredCandidate] = []
        seen_clusters: set[str] = set()
        seen_fragments: set[str] = set()

        for item in scored:
            fragment_id = item.card.fragment_id
            cluster_id = item.card.cluster_id
            if fragment_id in seen_fragments:
                continue

            if not cluster_id:
                out.append(item)
                seen_fragments.add(fragment_id)
                continue

            if cluster_id in seen_clusters:
                continue

            representative_id = representatives.get(cluster_id)
            if representative_id:
                representative_card = cards_by_id.get(representative_id)
                if representative_card is not None:
                    representative_candidate = next(
                        (candidate for candidate in scored if candidate.card.fragment_id == representative_id),
                        None,
                    )
                    if representative_candidate is not None:
                        out.append(representative_candidate)
                        seen_fragments.add(representative_id)
                        seen_clusters.add(cluster_id)
                        continue
            out.append(item)
            seen_fragments.add(fragment_id)
            seen_clusters.add(cluster_id)
        return out

    def _build_representative_map(self, clusters: list[FragmentCluster]) -> dict[str, str]:
        out: dict[str, str] = {}
        for cluster in clusters:
            if cluster.cluster_id and cluster.representative_fragment_id:
                out[cluster.cluster_id] = cluster.representative_fragment_id
        return out

    def _validate_scene_brief(self, scene_brief: SceneBrief) -> None:
        if not scene_brief.scene_objective.strip():
            raise ValueError("scene_brief.scene_objective is required")
        if not scene_brief.narrative_function:
            raise ValueError("scene_brief.narrative_function is required")
        if not scene_brief.emotion_mode:
            raise ValueError("scene_brief.emotion_mode is required")
        if not scene_brief.must_avoid:
            raise ValueError("scene_brief.must_avoid is required")

    def _collect_query_text(self, scene_brief: SceneBrief) -> list[str]:
        return [
            scene_brief.scene_objective,
            scene_brief.emotional_goal,
            scene_brief.conflict_goal,
            " ".join(scene_brief.narrative_function),
            " ".join(scene_brief.emotion_mode),
            " ".join(scene_brief.style_need),
        ]

    def _collect_card_text(self, card: FragmentCard) -> list[str]:
        return [
            card.content_summary,
            card.narrative_function_text,
            card.emotion_mechanism_text,
            card.character_relation_text,
            card.style_profile_text,
        ]

    def _list_overlap(self, left: list[str], right: list[str]) -> float:
        left_set = {item.strip() for item in left if item and item.strip()}
        right_set = {item.strip() for item in right if item and item.strip()}
        if not left_set or not right_set:
            return 0.0
        return len(left_set & right_set) / len(left_set)

    def _token_overlap(self, left_parts: list[str], right_parts: list[str]) -> float:
        left_tokens = self._tokenize_parts(left_parts)
        right_tokens = self._tokenize_parts(right_parts)
        if not left_tokens or not right_tokens:
            return 0.0
        return len(left_tokens & right_tokens) / len(left_tokens)

    def _tokenize_parts(self, parts: list[str]) -> set[str]:
        tokens: set[str] = set()
        for part in parts:
            for token in TOKEN_PATTERN.findall(part.lower()):
                if len(token) <= 1:
                    continue
                tokens.add(token)
        return tokens

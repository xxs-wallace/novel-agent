from __future__ import annotations

import re
from typing import Any

from ..llm import JsonModelClient
from ..prompts.rerank_prompt import build_rerank_prompt
from ..schemas.creative_kb_schema import FragmentCard, RerankResult, RerankScore, SceneBrief

TOKEN_PATTERN = re.compile(r"[\w\u4e00-\u9fff]+")
CONTEXT_DEPENDENCY_PENALTY = {
    "low": 1,
    "medium": 4,
    "high": 7,
}


class RerankService:
    """Scores a small candidate set with a stable rubric."""

    def __init__(self, *, top_n: int = 3, model_client: JsonModelClient | None = None) -> None:
        self.top_n = max(1, min(top_n, 4))
        self.model_client = model_client

    def rerank(
        self,
        *,
        scene_brief: SceneBrief,
        candidates: list[FragmentCard],
        anchor_context: str = "",
        recent_window_summary: str = "",
    ) -> RerankResult:
        self._validate_scene_brief(scene_brief)
        if not candidates:
            return RerankResult(selection_notes="no candidates available for rerank")

        if self.model_client is not None:
            scores = self._rerank_with_prompt(
                scene_brief=scene_brief,
                candidates=candidates,
                anchor_context=anchor_context,
                recent_window_summary=recent_window_summary,
            )
            selection_notes = "prompt_based_fixed_rubric"
        else:
            scores = [
                self._score_candidate(
                    scene_brief=scene_brief,
                    candidate=candidate,
                    anchor_context=anchor_context,
                    recent_window_summary=recent_window_summary,
                )
                for candidate in candidates
            ]
            selection_notes = "rule_based_placeholder_rerank"

        scores.sort(
            key=lambda item: (
                item.final_score,
                1 if self._is_representative_candidate(item, candidates) else 0,
                item.transferability,
                item.candidate_id,
            ),
            reverse=True,
        )

        selected_fragment_ids = self._select_top_fragments(scores=scores, candidates=candidates)
        if not selected_fragment_ids and candidates:
            selected_fragment_ids = [candidates[0].fragment_id]
            selection_notes = "fallback_selected_first_candidate"
        elif not selected_fragment_ids:
            selection_notes = "no candidates passed cluster selection"
        return RerankResult(
            scores=scores,
            selected_fragment_ids=selected_fragment_ids,
            selection_notes=selection_notes,
        )

    def _rerank_with_prompt(
        self,
        *,
        scene_brief: SceneBrief,
        candidates: list[FragmentCard],
        anchor_context: str,
        recent_window_summary: str,
    ) -> list[RerankScore]:
        if self.model_client is None:
            return []
        system_prompt, user_prompt = build_rerank_prompt(
            scene_brief=scene_brief,
            candidates=candidates,
            anchor_context=anchor_context,
            recent_window_summary=recent_window_summary,
            top_n=self.top_n,
        )
        fallback_scores = [
            self._score_candidate(
                scene_brief=scene_brief,
                candidate=candidate,
                anchor_context=anchor_context,
                recent_window_summary=recent_window_summary,
            ).to_dict()
            for candidate in candidates
        ]
        payload, _ = self.model_client.generate_json(
            system_prompt=system_prompt,
            user_prompt=user_prompt,
            fallback_factory=lambda: {"scores": fallback_scores},
            use_fallback_on_error=self.model_client.settings.dry_run,
        )
        parsed_scores = self._parse_rerank_payload(payload=payload, candidates=candidates)
        if parsed_scores:
            return parsed_scores
        return [
            self._score_candidate(
                scene_brief=scene_brief,
                candidate=candidate,
                anchor_context=anchor_context,
                recent_window_summary=recent_window_summary,
            )
            for candidate in candidates
        ]

    def _parse_rerank_payload(
        self,
        *,
        payload: dict[str, Any] | list[Any],
        candidates: list[FragmentCard],
    ) -> list[RerankScore]:
        if not isinstance(payload, dict):
            return []
        raw_scores = payload.get("scores")
        if not isinstance(raw_scores, list):
            return []
        candidates_by_id = {candidate.fragment_id: candidate for candidate in candidates}
        parsed_by_id: dict[str, RerankScore] = {}
        for item in raw_scores:
            if not isinstance(item, dict):
                continue
            candidate_id = str(item.get("candidate_id", "")).strip()
            candidate = candidates_by_id.get(candidate_id)
            if candidate is None:
                continue
            parsed = self._score_from_payload_item(item=item, candidate=candidate)
            parsed_by_id[candidate_id] = parsed
        for candidate in candidates:
            if candidate.fragment_id not in parsed_by_id:
                parsed_by_id[candidate.fragment_id] = RerankScore(
                    candidate_id=candidate.fragment_id,
                    cluster_id=candidate.cluster_id,
                    continuity_fit=0,
                    scene_function_fit=0,
                    character_temperament_fit=0,
                    relationship_state_fit=0,
                    emotion_expression_fit=0,
                    style_fit=0,
                    transferability=self._scale_score(candidate.transferability_score),
                    context_dependency_penalty=CONTEXT_DEPENDENCY_PENALTY.get(candidate.context_dependency_level, 4),
                    final_score=0.0,
                    reason="missing_from_prompt_response",
                )
        return list(parsed_by_id.values())

    def _score_from_payload_item(self, *, item: dict[str, Any], candidate: FragmentCard) -> RerankScore:
        continuity_fit = self._as_int_score(item.get("continuity_fit"))
        scene_function_fit = self._as_int_score(item.get("scene_function_fit"))
        character_temperament_fit = self._as_int_score(item.get("character_temperament_fit"))
        relationship_state_fit = self._as_int_score(item.get("relationship_state_fit"))
        emotion_expression_fit = self._as_int_score(item.get("emotion_expression_fit"))
        style_fit = self._as_int_score(item.get("style_fit"))
        transferability = self._as_int_score(item.get("transferability"))
        context_dependency_penalty = self._as_int_score(item.get("context_dependency_penalty"))
        final_score = round(
            continuity_fit * 0.18
            + scene_function_fit * 0.22
            + character_temperament_fit * 0.10
            + relationship_state_fit * 0.12
            + emotion_expression_fit * 0.16
            + style_fit * 0.12
            + transferability * 0.18
            - context_dependency_penalty * 0.12,
            4,
        )
        reason = str(item.get("reason", "")).strip() or "prompt_rubric_scored"
        return RerankScore(
            candidate_id=candidate.fragment_id,
            cluster_id=candidate.cluster_id,
            continuity_fit=continuity_fit,
            scene_function_fit=scene_function_fit,
            character_temperament_fit=character_temperament_fit,
            relationship_state_fit=relationship_state_fit,
            emotion_expression_fit=emotion_expression_fit,
            style_fit=style_fit,
            transferability=transferability,
            context_dependency_penalty=context_dependency_penalty,
            final_score=final_score,
            reason=reason,
        )

    def _score_candidate(
        self,
        *,
        scene_brief: SceneBrief,
        candidate: FragmentCard,
        anchor_context: str,
        recent_window_summary: str,
    ) -> RerankScore:
        continuity_fit = self._scale_score(
            self._token_overlap(
                [anchor_context, recent_window_summary, scene_brief.scene_objective],
                [candidate.content_summary, candidate.character_relation_text, candidate.source_excerpt],
            )
        )
        scene_function_fit = self._scale_score(
            self._list_overlap(scene_brief.narrative_function, candidate.narrative_function)
        )
        character_temperament_fit = self._scale_score(
            self._list_overlap(scene_brief.character_temperament, candidate.character_temperament)
        )
        relationship_state_fit = self._scale_score(
            self._list_overlap(scene_brief.relationship_state, candidate.relationship_state)
        )
        emotion_expression_fit = self._scale_score(
            max(
                self._list_overlap(scene_brief.emotion_mode, candidate.emotion_tags),
                self._token_overlap(scene_brief.emotion_mode, [candidate.emotion_mechanism_text]),
            )
        )
        style_fit = self._scale_score(
            self._token_overlap(scene_brief.style_need, [candidate.style_profile_text])
        )
        transferability = self._scale_score(candidate.transferability_score)
        context_dependency_penalty = CONTEXT_DEPENDENCY_PENALTY.get(candidate.context_dependency_level, 4)

        final_score = round(
            continuity_fit * 0.18
            + scene_function_fit * 0.22
            + character_temperament_fit * 0.10
            + relationship_state_fit * 0.12
            + emotion_expression_fit * 0.16
            + style_fit * 0.12
            + transferability * 0.18
            - context_dependency_penalty * 0.12,
            4,
        )

        reason_parts: list[str] = []
        if scene_function_fit >= 7:
            reason_parts.append("scene_function_fit_high")
        if emotion_expression_fit >= 7:
            reason_parts.append("emotion_expression_fit_high")
        if relationship_state_fit >= 7:
            reason_parts.append("relationship_state_fit_high")
        if transferability >= 7:
            reason_parts.append("transferability_high")
        if not reason_parts:
            reason_parts.append("balanced_placeholder_match")

        return RerankScore(
            candidate_id=candidate.fragment_id,
            cluster_id=candidate.cluster_id,
            continuity_fit=continuity_fit,
            scene_function_fit=scene_function_fit,
            character_temperament_fit=character_temperament_fit,
            relationship_state_fit=relationship_state_fit,
            emotion_expression_fit=emotion_expression_fit,
            style_fit=style_fit,
            transferability=transferability,
            context_dependency_penalty=context_dependency_penalty,
            final_score=final_score,
            reason=", ".join(reason_parts),
        )

    def _select_top_fragments(self, *, scores: list[RerankScore], candidates: list[FragmentCard]) -> list[str]:
        candidate_map = {candidate.fragment_id: candidate for candidate in candidates}
        per_bucket: dict[str, list[RerankScore]] = {}
        for score in scores:
            candidate = candidate_map.get(score.candidate_id)
            if candidate is None:
                continue
            bucket_key = candidate.cluster_id or candidate.fragment_id
            per_bucket.setdefault(bucket_key, []).append(score)

        selected_scores: list[RerankScore] = []
        for bucket_scores in per_bucket.values():
            bucket_scores.sort(
                key=lambda item: (
                    1 if self._is_representative_candidate(item, candidates) else 0,
                    item.final_score,
                    item.transferability,
                    item.candidate_id,
                ),
                reverse=True,
            )
            selected_scores.append(bucket_scores[0])

        selected_scores.sort(
            key=lambda item: (
                item.final_score,
                1 if self._is_representative_candidate(item, candidates) else 0,
                item.transferability,
                item.candidate_id,
            ),
            reverse=True,
        )

        return [item.candidate_id for item in selected_scores[: self.top_n]]

    def _is_representative_candidate(self, score: RerankScore, candidates: list[FragmentCard]) -> bool:
        for candidate in candidates:
            if candidate.fragment_id == score.candidate_id:
                return candidate.is_cluster_representative
        return False

    def _validate_scene_brief(self, scene_brief: SceneBrief) -> None:
        if not scene_brief.scene_objective.strip():
            raise ValueError("scene_brief.scene_objective is required")
        if not scene_brief.narrative_function:
            raise ValueError("scene_brief.narrative_function is required")
        if not scene_brief.emotion_mode:
            raise ValueError("scene_brief.emotion_mode is required")
        if not scene_brief.must_avoid:
            raise ValueError("scene_brief.must_avoid is required")

    def _scale_score(self, value: float) -> int:
        bounded = max(0.0, min(value, 1.0))
        return max(0, min(int(round(bounded * 10)), 10))

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

    def _as_int_score(self, value: Any) -> int:
        try:
            number = int(round(float(value)))
        except (TypeError, ValueError):
            return 0
        return max(0, min(number, 10))

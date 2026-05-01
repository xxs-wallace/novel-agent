from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from ..schemas.creative_kb_schema import SceneBrief
from ..schemas.orchestration_schema import (
    ScenePlanRetrievalHints,
    ScenePlanStyleReferenceQuery,
    ScenePlanSubset,
)

DEFAULT_NARRATIVE_FUNCTION = "承接推进"
DEFAULT_EMOTION_MODE = "克制表达"
DEFAULT_MUST_AVOID = "避免设定冲突"


def resolve_scene_brief(
    scene_brief: SceneBrief | None,
    scene_plan: ScenePlanSubset | Mapping[str, Any] | None = None,
) -> SceneBrief:
    """Prefer explicit SceneBrief and only adapt legacy ScenePlan when needed."""
    if scene_brief is not None:
        return normalize_scene_brief(scene_brief)
    if scene_plan is None:
        raise ValueError("scene_brief or scene_plan is required")
    return adapt_scene_plan_to_scene_brief(scene_plan)


def adapt_scene_plan_to_scene_brief(scene_plan: ScenePlanSubset | Mapping[str, Any]) -> SceneBrief:
    """Adapt the legacy ScenePlan subset into the frozen SceneBrief contract."""
    subset = coerce_scene_plan_subset(scene_plan)
    return normalize_scene_brief(
        SceneBrief(
            scene_objective=subset.goal,
            emotional_goal=subset.emotional_goal,
            conflict_goal=subset.conflict_goal,
            narrative_function=_fallback_required_list(
                subset.style_reference_query.narrative_function,
                default_item=DEFAULT_NARRATIVE_FUNCTION,
            ),
            emotion_mode=_fallback_required_list(
                subset.style_reference_query.emotion_mode,
                default_item=DEFAULT_EMOTION_MODE,
            ),
            character_temperament=subset.style_reference_query.character_temperament,
            relationship_state=subset.current_relationship_state,
            style_need=subset.style_reference_query.style_need,
            must_avoid=_fallback_required_list(
                _merge_string_lists(subset.forbidden, subset.avoidance_items),
                default_item=DEFAULT_MUST_AVOID,
            ),
            preferred_tags=subset.retrieval_hints.preferred_tags,
        )
    )


def normalize_scene_brief(scene_brief: SceneBrief) -> SceneBrief:
    normalized = SceneBrief(
        scene_objective=_normalize_text(scene_brief.scene_objective),
        emotional_goal=_normalize_text(scene_brief.emotional_goal),
        conflict_goal=_normalize_text(scene_brief.conflict_goal),
        narrative_function=_normalize_string_list(scene_brief.narrative_function),
        emotion_mode=_normalize_string_list(scene_brief.emotion_mode),
        character_temperament=_normalize_string_list(scene_brief.character_temperament),
        relationship_state=_normalize_string_list(scene_brief.relationship_state),
        style_need=_normalize_string_list(scene_brief.style_need),
        must_avoid=_normalize_string_list(scene_brief.must_avoid),
        preferred_tags=_normalize_string_list(scene_brief.preferred_tags),
    )
    if not normalized.scene_objective:
        raise ValueError("SceneBrief.scene_objective is required")
    if not normalized.narrative_function:
        raise ValueError("SceneBrief.narrative_function is required")
    if not normalized.emotion_mode:
        raise ValueError("SceneBrief.emotion_mode is required")
    if not normalized.must_avoid:
        raise ValueError("SceneBrief.must_avoid is required")
    return normalized


def coerce_scene_plan_subset(scene_plan: ScenePlanSubset | Mapping[str, Any]) -> ScenePlanSubset:
    if isinstance(scene_plan, ScenePlanSubset):
        return scene_plan

    if not isinstance(scene_plan, Mapping):
        return ScenePlanSubset()

    style_reference_query = _as_mapping(scene_plan.get("style_reference_query"))
    retrieval_hints = _as_mapping(scene_plan.get("retrieval_hints"))
    return ScenePlanSubset(
        goal=_normalize_text(scene_plan.get("goal")),
        emotional_goal=_normalize_text(scene_plan.get("emotional_goal")),
        conflict_goal=_normalize_text(scene_plan.get("conflict_goal")),
        current_relationship_state=_normalize_string_list(scene_plan.get("current_relationship_state")),
        forbidden=_normalize_string_list(scene_plan.get("forbidden")),
        avoidance_items=_normalize_string_list(scene_plan.get("avoidance_items")),
        style_reference_query=ScenePlanStyleReferenceQuery(
            narrative_function=_normalize_string_list(style_reference_query.get("narrative_function")),
            emotion_mode=_normalize_string_list(style_reference_query.get("emotion_mode")),
            character_temperament=_normalize_string_list(style_reference_query.get("character_temperament")),
            style_need=_normalize_string_list(style_reference_query.get("style_need")),
        ),
        retrieval_hints=ScenePlanRetrievalHints(
            preferred_tags=_normalize_string_list(retrieval_hints.get("preferred_tags"))
        ),
    )


def _normalize_text(value: Any) -> str:
    if value is None:
        return ""
    return str(value).strip()


def _normalize_string_list(value: Any) -> list[str]:
    if value is None:
        return []
    if isinstance(value, str):
        text = value.strip()
        return [text] if text else []
    if not isinstance(value, list):
        return []

    out: list[str] = []
    seen: set[str] = set()
    for item in value:
        text = str(item).strip()
        if not text or text in seen:
            continue
        seen.add(text)
        out.append(text)
    return out


def _merge_string_lists(left: list[str], right: list[str]) -> list[str]:
    out: list[str] = []
    seen: set[str] = set()
    for item in [*left, *right]:
        if item in seen:
            continue
        seen.add(item)
        out.append(item)
    return out


def _fallback_required_list(values: list[str], *, default_item: str) -> list[str]:
    if values:
        return values
    return [default_item]


def _as_mapping(value: Any) -> Mapping[str, Any]:
    if isinstance(value, Mapping):
        return value
    return {}

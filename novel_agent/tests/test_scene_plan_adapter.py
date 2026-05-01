from __future__ import annotations

import pytest

from novel_agent.app.schemas.creative_kb_schema import SceneBrief
from novel_agent.app.schemas.orchestration_schema import (
    ScenePlanRetrievalHints,
    ScenePlanStyleReferenceQuery,
    ScenePlanSubset,
)
from novel_agent.app.services.scene_plan_adapter import (
    adapt_scene_plan_to_scene_brief,
    resolve_scene_brief,
)


def test_adapt_scene_plan_to_scene_brief_maps_expected_fields() -> None:
    scene_plan = ScenePlanSubset(
        goal="续写雨夜停顿后的离别",
        emotional_goal="压住悲伤",
        conflict_goal="维持表面平静",
        current_relationship_state=["未和解"],
        forbidden=["突然表白"],
        avoidance_items=["设定冲突"],
        style_reference_query=ScenePlanStyleReferenceQuery(
            narrative_function=["收束"],
            emotion_mode=["克制"],
            character_temperament=["敏感"],
            style_need=["短句"],
        ),
        retrieval_hints=ScenePlanRetrievalHints(preferred_tags=["雨天", "告别"]),
    )

    scene_brief = adapt_scene_plan_to_scene_brief(scene_plan)

    assert scene_brief.scene_objective == "续写雨夜停顿后的离别"
    assert scene_brief.emotional_goal == "压住悲伤"
    assert scene_brief.conflict_goal == "维持表面平静"
    assert scene_brief.narrative_function == ["收束"]
    assert scene_brief.emotion_mode == ["克制"]
    assert scene_brief.character_temperament == ["敏感"]
    assert scene_brief.relationship_state == ["未和解"]
    assert scene_brief.style_need == ["短句"]
    assert scene_brief.must_avoid == ["突然表白", "设定冲突"]
    assert scene_brief.preferred_tags == ["雨天", "告别"]


def test_adapt_scene_plan_to_scene_brief_applies_required_fallbacks() -> None:
    scene_brief = adapt_scene_plan_to_scene_brief({"goal": "补出最小 SceneBrief"})

    assert scene_brief.scene_objective == "补出最小 SceneBrief"
    assert scene_brief.narrative_function == ["承接推进"]
    assert scene_brief.emotion_mode == ["克制表达"]
    assert scene_brief.must_avoid == ["避免设定冲突"]


def test_resolve_scene_brief_prefers_explicit_scene_brief() -> None:
    scene_brief = SceneBrief(
        scene_objective="优先使用显式 SceneBrief",
        narrative_function=["冲突升级"],
        emotion_mode=["压抑"],
        must_avoid=["设定冲突"],
    )
    scene_plan = ScenePlanSubset(goal="不应覆盖 scene_brief")

    resolved = resolve_scene_brief(scene_brief, scene_plan)

    assert resolved.scene_objective == "优先使用显式 SceneBrief"
    assert resolved.narrative_function == ["冲突升级"]


def test_resolve_scene_brief_requires_input() -> None:
    with pytest.raises(ValueError, match="scene_brief or scene_plan is required"):
        resolve_scene_brief(None, None)

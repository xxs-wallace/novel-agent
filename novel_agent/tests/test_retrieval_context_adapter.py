from __future__ import annotations

from novel_agent.app.schemas.orchestration_schema import RetrievalContext
from novel_agent.app.services.retrieval_context_adapter import (
    build_retrieval_context,
    prepare_scene_brief_input,
)


def test_build_retrieval_context_accepts_mapping_input() -> None:
    context = build_retrieval_context(
        {
            "character_hits": [" 林清 ", "林清"],
            "timeline_hits": [" 第十章 "],
            "lore_hits": ["雨夜"],
        }
    )

    assert context.character_hits == ["林清"]
    assert context.timeline_hits == ["第十章"]
    assert context.lore_hits == ["雨夜"]


def test_build_retrieval_context_accepts_explicit_sequences() -> None:
    context = build_retrieval_context(
        character_hits=["林清", "林清"],
        timeline_hits=["第十章"],
        lore_hits=["旧站台", "旧站台"],
    )

    assert context.character_hits == ["林清"]
    assert context.timeline_hits == ["第十章"]
    assert context.lore_hits == ["旧站台"]


def test_build_retrieval_context_round_trips_existing_object() -> None:
    context = build_retrieval_context(
        RetrievalContext(
            character_hits=["林清"],
            timeline_hits=["第十章"],
            lore_hits=["雨夜"],
        )
    )

    assert context.to_dict() == {
        "character_hits": ["林清"],
        "timeline_hits": ["第十章"],
        "lore_hits": ["雨夜"],
    }


def test_prepare_scene_brief_input_wraps_retrieval_context_without_extra_semantics() -> None:
    scene_brief_input = prepare_scene_brief_input(
        anchor_context=" 她没有马上离开。 ",
        recent_window_summary=" 当前需要关系收束。 ",
        goal=" 续写停顿后的对话 ",
        previous_generated_segment=" 她想说的话停在舌尖。 ",
        retrieval_context={"character_hits": ["林清"], "timeline_hits": ["第十章"], "lore_hits": ["雨夜"]},
    )

    payload = scene_brief_input.to_dict()

    assert payload["anchor_context"] == "她没有马上离开。"
    assert payload["goal"] == "续写停顿后的对话"
    assert payload["retrieval_context"] == {
        "character_hits": ["林清"],
        "timeline_hits": ["第十章"],
        "lore_hits": ["雨夜"],
    }
    assert "candidate_fragment_ids" not in payload["retrieval_context"]

from __future__ import annotations

from novel_agent.app.schemas.creative_kb_schema import (
    CoarseRetrievalResult,
    CreativeKBBuildResult,
    CreativeKBRetrievalResult,
    ExpandedReferenceFragment,
    FragmentCard,
    FragmentCardBuildResult,
    RerankResult,
    SceneBrief,
    StyleFeatures,
)
from novel_agent.app.schemas.orchestration_schema import (
    EvidenceItem,
    RetrievalContext,
    SceneBriefInput,
    ScenePlanRetrievalHints,
    ScenePlanStyleReferenceQuery,
    ScenePlanSubset,
    TraceableSource,
)


def _fragment_card() -> FragmentCard:
    return FragmentCard(
        fragment_id="frag-1",
        doc_id="doc-1",
        document_title="第十章",
        document_title_index="10",
        source_path="/tmp/source.md",
        source_offsets=(0, 64),
        source_excerpt="雨夜里她没有立刻说出告别。",
        content_summary="雨夜里的克制型告别停顿。",
        narrative_function=["收束"],
        narrative_function_text="通过停顿收束当前冲突。",
        scene_space_tags=["雨夜"],
        event_tags=["告别"],
        emotion_tags=["克制", "悲伤"],
        emotion_mechanism_text="通过沉默和动作压住悲伤。",
        expression_mode_tags=["动作描写"],
        preferred_tags=["雨天", "告别"],
        pov_mode="近距离第三人称",
        character_focus=["林清"],
        character_temperament=["克制"],
        character_relation_text="关系仍未和解。",
        relationship_state=["未和解"],
        continuity_phase="承接推进",
        style_features=StyleFeatures(
            sentence_rhythm="短句偏多",
            dialogue_density="低",
            interiority_density="高",
            imagery_density="中",
        ),
        style_profile_text="短句、低对白、高内心密度。",
        transferability_score=0.8,
        context_dependency_level="medium",
    )


def test_fragment_card_build_result_normalizes_status_and_stage() -> None:
    result = FragmentCardBuildResult(
        status=" FALLBACK_SUCCESS ",
        fragment_card=_fragment_card(),
        retry_count=2,
        used_fallback=True,
        failure_stage=" SCHEMA_VALIDATE ",
        failure_reason=" missing fields ",
        warnings=[" retry used ", "retry used", ""],
    )

    assert result.status == "fallback_success"
    assert result.failure_stage == "schema_validate"
    assert result.failure_reason == "missing fields"
    assert result.warnings == ["retry used"]
    assert result.to_dict()["fragment_card"]["fragment_id"] == "frag-1"


def test_creative_kb_build_result_normalizes_lists() -> None:
    result = CreativeKBBuildResult(
        built_fragment_count=3,
        built_cluster_count=2,
        representative_count=2,
        fragment_ids=["frag-1", "frag-1", " frag-2 "],
        cluster_ids=["cluster-a", " cluster-b "],
        failed_doc_ids=["doc-x", "doc-x"],
        skipped_doc_ids=["doc-y", ""],
        warnings=[" fallback card inserted ", "fallback card inserted"],
    )

    assert result.fragment_ids == ["frag-1", "frag-2"]
    assert result.cluster_ids == ["cluster-a", "cluster-b"]
    assert result.failed_doc_ids == ["doc-x"]
    assert result.skipped_doc_ids == ["doc-y"]
    assert result.warnings == ["fallback card inserted"]


def test_creative_kb_retrieval_result_to_dict_returns_minimal_default_shape() -> None:
    result = CreativeKBRetrievalResult(
        scene_brief=SceneBrief(
            scene_objective="寻找克制型告别参考",
            narrative_function=["收束"],
            emotion_mode=["克制"],
            must_avoid=["突然表白"],
        ),
        rerank_result=RerankResult(selected_fragment_ids=["frag-1"]),
    )

    payload = result.to_dict()

    assert sorted(payload.keys()) == ["rerank_result", "scene_brief"]
    assert payload["rerank_result"]["selected_fragment_ids"] == ["frag-1"]


def test_orchestration_evidence_level_accepts_model_aliases() -> None:
    source = TraceableSource(type="memory", path="/tmp/world.md", evidence_level="结构化状态")
    evidence = EvidenceItem(
        claim="关系变化来自已确认分析",
        evidence_level="confirmed fact",
        source_paths=["/tmp/outline.md"],
    )

    assert source.evidence_level == "structured_state"
    assert evidence.evidence_level == "confirmed_analysis"


def test_creative_kb_retrieval_result_includes_optional_debug_and_reference_fields() -> None:
    result = CreativeKBRetrievalResult(
        scene_brief=SceneBrief(
            scene_objective="寻找克制型告别参考",
            narrative_function=["收束"],
            emotion_mode=["克制"],
            must_avoid=["突然表白"],
        ),
        rerank_result=RerankResult(selected_fragment_ids=["frag-1"]),
        coarse_result=CoarseRetrievalResult(candidate_fragment_ids=["frag-1"]),
        reference_fragments=[
            ExpandedReferenceFragment(
                fragment_id="frag-1",
                doc_id="doc-1",
                source_path="/tmp/source.md",
                source_excerpt="雨夜里她没有立刻说出告别。",
                content_summary="雨夜里的克制型告别停顿。",
                style_profile_text="短句、低对白、高内心密度。",
            )
        ],
    )

    payload = result.to_dict()

    assert payload["coarse_result"]["candidate_fragment_ids"] == ["frag-1"]
    assert payload["reference_fragments"][0]["doc_id"] == "doc-1"


def test_scene_plan_subset_and_scene_brief_input_serialize_stably() -> None:
    scene_plan = ScenePlanSubset(
        goal=" 续写雨夜告别前停顿 ",
        emotional_goal=" 压住悲伤 ",
        conflict_goal=" 保持表面平静 ",
        current_relationship_state=[" 未和解 ", "未和解"],
        forbidden=[" 突然表白 "],
        avoidance_items=[" 设定冲突 "],
        style_reference_query=ScenePlanStyleReferenceQuery(
            narrative_function=[" 收束 "],
            emotion_mode=[" 克制 "],
            character_temperament=[" 敏感 "],
            style_need=[" 短句 "],
        ),
        retrieval_hints=ScenePlanRetrievalHints(preferred_tags=[" 雨天 ", "告别"]),
    )
    scene_brief_input = SceneBriefInput(
        anchor_context=" 她没有说再见。 ",
        recent_window_summary=" 当前需要关系收束。 ",
        goal=" 续写雨夜告别前停顿 ",
        previous_generated_segment=" 她想开口却停住。 ",
        retrieval_context=RetrievalContext(character_hits=["林清"], timeline_hits=["第十章"], lore_hits=["无"]),
    )

    scene_plan_payload = scene_plan.to_dict()
    input_payload = scene_brief_input.to_dict()

    assert scene_plan_payload["goal"] == "续写雨夜告别前停顿"
    assert scene_plan_payload["current_relationship_state"] == ["未和解"]
    assert scene_plan_payload["style_reference_query"]["narrative_function"] == ["收束"]
    assert input_payload["anchor_context"] == "她没有说再见。"
    assert input_payload["retrieval_context"]["character_hits"] == ["林清"]

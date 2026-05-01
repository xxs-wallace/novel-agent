from __future__ import annotations

import json
from types import SimpleNamespace

import pytest

from novel_agent.app.prompts.rerank_prompt import build_rerank_prompt
from novel_agent.app.prompts.scene_brief_prompt import build_scene_brief_prompt
from novel_agent.app.schemas.creative_kb_schema import FragmentCard, SceneBrief, StyleFeatures
from novel_agent.app.schemas.orchestration_schema import CreativeKBRetrievalInput, RetrievalContext
from novel_agent.app.services.coarse_retrieval_service import CoarseRetrievalService
from novel_agent.app.services.rerank_service import RerankService
from novel_agent.app.services.scene_brief_service import SceneBriefService


class SequenceModelClient:
    def __init__(self, payloads: list[dict[str, object]]) -> None:
        self.payloads = payloads
        self.calls = 0
        self.settings = SimpleNamespace(dry_run=False)
        self.captured_prompts: list[tuple[str, str]] = []

    def generate_json(
        self,
        *,
        system_prompt: str,
        user_prompt: str,
        fallback_factory,
        use_fallback_on_error: bool = False,
    ):
        _ = fallback_factory, use_fallback_on_error
        self.captured_prompts.append((system_prompt, user_prompt))
        payload = self.payloads[min(self.calls, len(self.payloads) - 1)]
        self.calls += 1
        return payload, json.dumps(payload, ensure_ascii=False)


def _card(
    *,
    fragment_id: str,
    cluster_id: str | None = None,
    is_rep: bool = False,
    content_summary: str,
    narrative_function: list[str],
    narrative_function_text: str,
    emotion_tags: list[str],
    emotion_mechanism_text: str,
    character_temperament: list[str],
    relationship_state: list[str],
    preferred_tags: list[str],
    style_profile_text: str,
    transferability_score: float = 0.8,
    context_dependency_level: str = "medium",
) -> FragmentCard:
    return FragmentCard(
        fragment_id=fragment_id,
        doc_id=f"doc-{fragment_id}",
        document_title="第十章 雨中对话",
        document_title_index="10",
        cluster_id=cluster_id,
        is_cluster_representative=is_rep,
        source_path="/tmp/source.md",
        source_offsets=(0, 128),
        source_excerpt="她站在雨里，没有立刻说出那句告别。",
        content_summary=content_summary,
        narrative_function=narrative_function,
        narrative_function_text=narrative_function_text,
        scene_space_tags=["雨夜", "街道"],
        event_tags=["告别"],
        emotion_tags=emotion_tags,
        emotion_mechanism_text=emotion_mechanism_text,
        expression_mode_tags=["动作描写", "心理活动"],
        preferred_tags=preferred_tags,
        pov_mode="近距离第三人称",
        character_focus=["林清"],
        character_temperament=character_temperament,
        character_relation_text="处于未和解的告别边缘。",
        relationship_state=relationship_state,
        continuity_phase="冲突后收束",
        style_features=StyleFeatures(
            sentence_rhythm="短句偏多",
            dialogue_density="低",
            interiority_density="高",
            imagery_density="中",
        ),
        style_profile_text=style_profile_text,
        transferability_score=transferability_score,
        context_dependency_level=context_dependency_level,  # type: ignore[arg-type]
    )


def _retrieval_input() -> CreativeKBRetrievalInput:
    return CreativeKBRetrievalInput(
        anchor_context="上一段写到她没有说再见，只把伞柄握得更紧。",
        recent_window_summary="当前处于误解后的短暂对峙，需要一段关系收束前的停顿。",
        goal="续写一段克制型离别前停顿",
        previous_generated_segment="她想开口，却又停住。",
        retrieval_context=RetrievalContext(character_hits=["林清"], timeline_hits=["第十章"], lore_hits=["无"]),
        scene_plan={
            "goal": "续写一段克制型离别前停顿",
            "emotional_goal": "表现压住的悲伤",
            "conflict_goal": "维持表面平静，不让矛盾被轻易化解",
            "current_relationship_state": ["未和解"],
            "forbidden": ["突然表白"],
            "avoidance_items": ["设定冲突", "突然表白"],
            "style_reference_query": {
                "narrative_function": ["收束", "情绪沉浸"],
                "emotion_mode": ["克制", "悲伤"],
                "character_temperament": ["敏感", "克制"],
                "style_need": ["短句", "低对白"],
            },
            "retrieval_hints": {"preferred_tags": ["雨天", "告别"]},
        },
    )


def test_scene_brief_prompt_contains_contract_and_auxiliary_tag_guardrail() -> None:
    retrieval_input = _retrieval_input()
    fallback_scene_brief = {
        "scene_objective": "续写一段克制型离别前停顿",
        "emotional_goal": "表现压住的悲伤",
        "conflict_goal": "维持表面平静",
        "narrative_function": ["收束"],
        "emotion_mode": ["克制"],
        "character_temperament": ["敏感"],
        "relationship_state": ["未和解"],
        "style_need": ["短句"],
        "must_avoid": ["突然表白"],
        "preferred_tags": ["雨天"],
    }

    system_prompt, user_prompt = build_scene_brief_prompt(
        retrieval_input=retrieval_input,
        fallback_scene_brief=fallback_scene_brief,
    )

    assert "只输出严格 JSON" in system_prompt
    assert "preferred_tags 仅作为辅助定位" in system_prompt
    assert "scene_objective、narrative_function、emotion_mode、must_avoid 必须非空" in system_prompt
    assert "fallback_scene_brief" in user_prompt
    assert '"scene_objective": "续写一段未和解关系中的雨夜停顿与告别前压抑"' in user_prompt


def test_scene_brief_service_retries_on_invalid_model_payload_and_validates_schema() -> None:
    model_client = SequenceModelClient(
        [
            {
                "scene_objective": "续写一段克制型离别前停顿",
                "emotional_goal": "表现压住的悲伤",
                "conflict_goal": "维持表面平静",
                "narrative_function": [],
                "emotion_mode": ["克制"],
                "character_temperament": ["敏感"],
                "relationship_state": ["未和解"],
                "style_need": ["短句"],
                "must_avoid": ["突然表白"],
                "preferred_tags": ["雨天"],
            },
            {
                "scene_objective": "续写一段克制型离别前停顿",
                "emotional_goal": "表现压住的悲伤",
                "conflict_goal": "维持表面平静",
                "narrative_function": ["收束", "情绪沉浸"],
                "emotion_mode": ["克制", "悲伤"],
                "character_temperament": ["敏感", "克制"],
                "relationship_state": ["未和解"],
                "style_need": ["短句", "低对白"],
                "must_avoid": ["突然表白", "设定冲突"],
                "preferred_tags": ["雨天", "告别"],
            },
        ]
    )
    service = SceneBriefService(model_client=model_client)  # type: ignore[arg-type]

    brief = service.build(_retrieval_input())

    assert model_client.calls == 2
    assert brief.scene_objective == "续写一段克制型离别前停顿"
    assert brief.narrative_function == ["收束", "情绪沉浸"]
    assert brief.emotion_mode == ["克制", "悲伤"]
    assert brief.must_avoid == ["突然表白", "设定冲突"]
    system_prompt, user_prompt = model_client.captured_prompts[0]
    assert "只输出严格 JSON" in system_prompt
    assert "fallback_scene_brief" in user_prompt


def test_rerank_prompt_and_service_use_prompt_rubric_with_unique_cluster_selection() -> None:
    scene_brief = SceneBrief(
        scene_objective="寻找一段克制型告别的参考桥段",
        emotional_goal="压住悲伤",
        conflict_goal="维持表面平静",
        narrative_function=["收束", "情绪沉浸"],
        emotion_mode=["克制", "悲伤"],
        character_temperament=["敏感", "克制"],
        relationship_state=["未和解"],
        style_need=["短句", "低对白", "高内心密度"],
        must_avoid=["突然表白"],
        preferred_tags=["雨天", "告别"],
    )
    rep_card = _card(
        fragment_id="frag-rep",
        cluster_id="cluster-a",
        is_rep=True,
        content_summary="敏感的人在雨夜告别前压住悲伤，不肯把话说满。",
        narrative_function=["收束", "情绪沉浸"],
        narrative_function_text="通过停顿和未尽之语收束关系冲突。",
        emotion_tags=["克制", "悲伤"],
        emotion_mechanism_text="先压住眼泪，再用动作回避告别。",
        character_temperament=["敏感", "克制"],
        relationship_state=["未和解"],
        preferred_tags=["雨天", "告别"],
        style_profile_text="短句、低对白、高内心密度。",
        transferability_score=0.9,
        context_dependency_level="low",
    )
    same_cluster_non_rep = _card(
        fragment_id="frag-nonrep",
        cluster_id="cluster-a",
        is_rep=False,
        content_summary="类似的雨夜告别桥段，但更依赖原章上下文。",
        narrative_function=["收束"],
        narrative_function_text="收束人物关系。",
        emotion_tags=["克制"],
        emotion_mechanism_text="通过省略对白表达退让。",
        character_temperament=["克制"],
        relationship_state=["未和解"],
        preferred_tags=["雨天", "告别"],
        style_profile_text="短句、较低对白。",
        transferability_score=0.5,
        context_dependency_level="high",
    )
    other_cluster = _card(
        fragment_id="frag-other",
        cluster_id="cluster-b",
        is_rep=True,
        content_summary="人物在医院走廊克制地接受失去，靠动作维持秩序。",
        narrative_function=["收束", "余波"],
        narrative_function_text="在事件余波中维持秩序感。",
        emotion_tags=["克制", "麻木"],
        emotion_mechanism_text="通过动作与沉默消化失去。",
        character_temperament=["克制"],
        relationship_state=["失去后"],
        preferred_tags=["医院", "失去"],
        style_profile_text="低对白、中内心密度。",
        transferability_score=0.85,
        context_dependency_level="medium",
    )
    system_prompt, user_prompt = build_rerank_prompt(
        scene_brief=scene_brief,
        candidates=[rep_card, same_cluster_non_rep, other_cluster],
        anchor_context="她没有立刻说出那句告别，只是站在雨里。",
        recent_window_summary="当前需要一段关系收束且避免情绪失控的参考。",
        top_n=2,
    )
    assert "固定 rubric" in system_prompt
    assert "preferred_tags 只是弱辅助信号" in system_prompt
    assert '"selected_fragment_ids": [' in user_prompt

    model_client = SequenceModelClient(
        [
            {
                "scores": [
                    {
                        "candidate_id": "frag-rep",
                        "cluster_id": "cluster-a",
                        "continuity_fit": 8,
                        "scene_function_fit": 9,
                        "character_temperament_fit": 8,
                        "relationship_state_fit": 8,
                        "emotion_expression_fit": 9,
                        "style_fit": 8,
                        "transferability": 9,
                        "context_dependency_penalty": 2,
                        "final_score": 8.5,
                        "reason": "主维度高度贴合。",
                    },
                    {
                        "candidate_id": "frag-nonrep",
                        "cluster_id": "cluster-a",
                        "continuity_fit": 7,
                        "scene_function_fit": 7,
                        "character_temperament_fit": 6,
                        "relationship_state_fit": 7,
                        "emotion_expression_fit": 6,
                        "style_fit": 5,
                        "transferability": 4,
                        "context_dependency_penalty": 7,
                        "final_score": 4.8,
                        "reason": "同簇且上下文依赖高。",
                    },
                    {
                        "candidate_id": "frag-other",
                        "cluster_id": "cluster-b",
                        "continuity_fit": 5,
                        "scene_function_fit": 7,
                        "character_temperament_fit": 6,
                        "relationship_state_fit": 3,
                        "emotion_expression_fit": 5,
                        "style_fit": 5,
                        "transferability": 8,
                        "context_dependency_penalty": 4,
                        "final_score": 5.7,
                        "reason": "部分匹配。",
                    },
                ],
                "selected_fragment_ids": ["frag-rep", "frag-other"],
                "selection_notes": "模型建议结果",
            }
        ]
    )
    rerank = RerankService(top_n=2, model_client=model_client)  # type: ignore[arg-type]

    result = rerank.rerank(
        scene_brief=scene_brief,
        candidates=[rep_card, same_cluster_non_rep, other_cluster],
        anchor_context="她没有立刻说出那句告别，只是站在雨里。",
        recent_window_summary="当前需要一段关系收束且避免情绪失控的参考。",
    )

    assert result.selection_notes == "prompt_based_fixed_rubric"
    assert result.selected_fragment_ids == ["frag-rep", "frag-other"]
    assert len(result.selected_fragment_ids) == 2
    assert "frag-nonrep" not in result.selected_fragment_ids
    scores_by_id = {item.candidate_id: item for item in result.scores}
    assert scores_by_id["frag-rep"].scene_function_fit == 9
    assert scores_by_id["frag-rep"].final_score > scores_by_id["frag-nonrep"].final_score


def test_coarse_retrieval_preferred_tags_remain_auxiliary_and_cannot_admit_tag_only_candidate() -> None:
    scene_brief = SceneBrief(
        scene_objective="寻找一段克制型告别的参考桥段",
        emotional_goal="压住悲伤",
        conflict_goal="维持表面平静",
        narrative_function=["收束", "情绪沉浸"],
        emotion_mode=["克制", "悲伤"],
        character_temperament=["敏感", "克制"],
        relationship_state=["未和解"],
        style_need=["短句", "低对白"],
        must_avoid=["突然表白"],
        preferred_tags=["雨天", "告别"],
    )
    text_match = _card(
        fragment_id="frag-text-match",
        content_summary="敏感的人在雨夜告别前压住悲伤，不肯把话说满。",
        narrative_function=["收束", "情绪沉浸"],
        narrative_function_text="通过停顿和未尽之语收束关系冲突。",
        emotion_tags=["克制", "悲伤"],
        emotion_mechanism_text="先压住眼泪，再用动作回避告别。",
        character_temperament=["敏感", "克制"],
        relationship_state=["未和解"],
        preferred_tags=["雨天", "告别"],
        style_profile_text="短句、低对白、高内心密度。",
    )
    tag_only = _card(
        fragment_id="frag-tag-only",
        content_summary="轻松校园闲聊。",
        narrative_function=["铺垫"],
        narrative_function_text="铺垫轻松氛围。",
        emotion_tags=["轻松"],
        emotion_mechanism_text="通过连续对白推进信息。",
        character_temperament=["外向"],
        relationship_state=["普通同学"],
        preferred_tags=["雨天", "告别"],
        style_profile_text="高对白、快节奏。",
    )

    coarse = CoarseRetrievalService(candidate_limit=12).retrieve(
        scene_brief=scene_brief,
        fragment_cards=[text_match, tag_only],
        fragment_clusters=[],
        fts_fragment_ids=[],
    )

    assert "frag-text-match" in coarse.candidate_fragment_ids
    assert "frag-tag-only" not in coarse.candidate_fragment_ids


def test_rerank_service_limits_top_n_to_four() -> None:
    service = RerankService(top_n=10)
    assert service.top_n == 4


def test_scene_brief_service_requires_scene_objective_when_model_returns_blank() -> None:
    model_client = SequenceModelClient(
        [
            {
                "scene_objective": "",
                "emotional_goal": "",
                "conflict_goal": "",
                "narrative_function": ["收束"],
                "emotion_mode": ["克制"],
                "character_temperament": [],
                "relationship_state": [],
                "style_need": [],
                "must_avoid": ["设定冲突"],
                "preferred_tags": [],
            }
        ]
    )
    service = SceneBriefService(model_client=model_client)  # type: ignore[arg-type]

    with pytest.raises(ValueError, match="Failed to build SceneBrief"):
        service.build(_retrieval_input())

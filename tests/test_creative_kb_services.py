from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

from novel_agent.app.prompts.fragment_card_prompt import build_fragment_card_prompt
from novel_agent.app.repos.creative_kb_storage import init_creative_kb_schema
from novel_agent.app.repos.db import NovelAgentDB
from novel_agent.app.repos.documents_repo import DocumentRow
from novel_agent.app.repos.fragment_cards_repo import FragmentCardsRepo
from novel_agent.app.repos.fragment_clusters_repo import FragmentClustersRepo
from novel_agent.app.schemas.creative_kb_schema import FragmentCard, FragmentCluster, SceneBrief, StyleFeatures
from novel_agent.app.schemas.orchestration_schema import CreativeKBRetrievalInput, RetrievalContext
from novel_agent.app.services.coarse_retrieval_service import CoarseRetrievalService
from novel_agent.app.services.fragment_card_builder_service import FragmentCardBuilderService
from novel_agent.app.services.rerank_service import RerankService
from novel_agent.app.services.scene_brief_service import SceneBriefService


def _card(
    *,
    fragment_id: str,
    doc_id: str,
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
        doc_id=doc_id,
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


def _document_row(
    *,
    doc_id: int = 11,
    content_tags: list[str] | None = None,
    content: str | None = None,
) -> DocumentRow:
    return DocumentRow(
        doc_id=doc_id,
        book_id="book-demo",
        path="docs/chapter-10.md",
        scope="docs",
        title="第十章 雨中对话",
        document_title="第十章 雨中对话",
        document_title_index=10,
        inferred_chapter_no=10,
        content=content
        or "她站在雨夜的街口，没有立刻说出告别。路灯把积水照得发亮，她只把伞柄握得更紧，"
        "像是要把已经涌到喉头的话重新压回去。",
        content_chars=72,
        character_keywords=[],
        content_tags=content_tags or ["雨天", "告别", "城市街道"],
        source_path="docs/chapter-10.md",
        source_file_name="chapter-10.md",
        source_start_offset=128,
        source_end_offset=256,
    )


class SequenceModelClient:
    def __init__(self, payloads: list[dict[str, object]]) -> None:
        self.payloads = payloads
        self.calls = 0
        self.settings = SimpleNamespace(dry_run=False)

    def generate_json(
        self,
        *,
        system_prompt: str,
        user_prompt: str,
        fallback_factory,
        use_fallback_on_error: bool = False,
    ):
        _ = system_prompt, user_prompt, fallback_factory, use_fallback_on_error
        payload = self.payloads[min(self.calls, len(self.payloads) - 1)]
        self.calls += 1
        return payload, json.dumps(payload, ensure_ascii=False)


def _fragment_card_payload(*, preferred_tags: list[str], transferability_score: float = 0.82) -> dict[str, object]:
    return {
        "content_summary": "克制型雨夜告别桥段，用停顿和动作回避承载未说出口的话。",
        "narrative_function": ["收束过渡", "告别"],
        "narrative_function_text": "在关系紧绷后用未尽之语收束情绪，为离开或转场做准备。",
        "scene_space_tags": ["城市街道", "雨天"],
        "event_tags": ["告别"],
        "emotion_tags": ["悲伤低落", "孤独感"],
        "emotion_mechanism_text": "通过沉默、避视和抓紧伞柄的细小动作表达压住的悲伤。",
        "expression_mode_tags": ["动作描写", "人物对话", "心理活动"],
        "preferred_tags": preferred_tags,
        "pov_mode": "近距离第三人称",
        "character_focus": ["她"],
        "character_temperament": ["克制", "敏感"],
        "character_relation_text": "关系停在尚未和解的告别边缘，重点是情绪僵持。",
        "relationship_state": ["未和解", "即将分离"],
        "continuity_phase": "冲突后收束",
        "style_features": {
            "sentence_rhythm": "短句偏多",
            "dialogue_density": "低",
            "interiority_density": "中高",
            "imagery_density": "中",
        },
        "style_profile_text": "短句、低对白、以动作停顿和少量心理描写承载情绪。",
        "transferability_score": transferability_score,
        "context_dependency_level": "medium",
    }


def test_fragment_card_repo_roundtrip_and_fts_search(tmp_path: Path) -> None:
    db = NovelAgentDB(tmp_path / "creative_kb.db")
    cards_repo = FragmentCardsRepo()
    clusters_repo = FragmentClustersRepo()

    with db.connect() as conn:
        db.init_schema(conn)
        init_creative_kb_schema(conn)

        card = _card(
            fragment_id="frag-1",
            doc_id="doc-1",
            cluster_id="cluster-1",
            is_rep=True,
            content_summary="restrained farewell scene: 克制的人物在雨夜告别前压住情绪。",
            narrative_function=["收束", "情绪沉浸"],
            narrative_function_text="restrained departure beat，在冲突后收束情绪并制造未言明的离开感。",
            emotion_tags=["克制", "悲伤"],
            emotion_mechanism_text="通过停顿、避视和动作延迟来表达悲伤。",
            character_temperament=["克制", "敏感"],
            relationship_state=["未和解"],
            preferred_tags=["雨天", "告别"],
            style_profile_text="restrained short sentences，低对白、高内心密度。",
        )
        cards_repo.upsert_cards(conn, [card])
        clusters_repo.upsert_clusters(
            conn,
            [
                FragmentCluster(
                    cluster_id="cluster-1",
                    cluster_theme="雨夜克制告别",
                    representative_fragment_id="frag-1",
                    member_count=1,
                    dedup_reason="same emotional beat",
                )
            ],
        )
        conn.commit()

        loaded = cards_repo.get(conn, fragment_id="frag-1")
        assert loaded is not None
        assert loaded.fragment_id == "frag-1"
        assert loaded.cluster_id == "cluster-1"
        assert loaded.is_cluster_representative is True
        assert loaded.preferred_tags == ["雨天", "告别"]
        assert loaded.style_features.interiority_density == "高"

        representatives = cards_repo.list_representatives(conn, cluster_id="cluster-1")
        assert [item.fragment_id for item in representatives] == ["frag-1"]

        cluster = clusters_repo.get(conn, cluster_id="cluster-1")
        assert cluster is not None
        assert cluster.representative_fragment_id == "frag-1"

        hits = cards_repo.search_fts(conn, query_text="restrained farewell", representatives_only=True)
        assert [hit.fragment_id for hit in hits] == ["frag-1"]
        assert hits[0].cluster_id == "cluster-1"
        assert hits[0].is_cluster_representative is True


def test_fragment_card_prompt_contains_json_only_and_score_constraints() -> None:
    system_prompt, user_prompt = build_fragment_card_prompt(_document_row())

    assert "只输出严格 JSON" in system_prompt
    assert "preferred_tags 只能从提供的标签词典中选择" in system_prompt
    assert "context_dependency_level 只能是 low、medium、high 之一" in system_prompt
    assert "0.0-0.2" in user_prompt
    assert "0.9-1.0" in user_prompt
    assert '"transferability_score": 0.82' in user_prompt
    assert '"context_dependency_level": "medium"' in user_prompt


def test_fragment_card_builder_retries_on_schema_error_and_syncs_preferred_tags(tmp_path: Path) -> None:
    db = NovelAgentDB(tmp_path / "fragment_builder.db")
    cards_repo = FragmentCardsRepo()
    document = _document_row()
    model_client = SequenceModelClient(
        [
            _fragment_card_payload(preferred_tags=["自造标签"]),
            _fragment_card_payload(preferred_tags=["校园"]),
        ]
    )
    service = FragmentCardBuilderService(
        model_client=model_client,  # type: ignore[arg-type]
        fragment_cards_repo=cards_repo,
    )

    with db.connect() as conn:
        db.init_schema(conn)
        init_creative_kb_schema(conn)
        results, stats = service.build_and_persist(conn, documents=[document])
        conn.commit()

        assert model_client.calls == 2
        assert stats.built_cards == 1
        assert stats.validation_retries == 1
        assert len(results) == 1
        result = results[0]
        assert result.status == "success"
        assert result.fragment_card is not None
        card = result.fragment_card
        assert card.doc_id == str(document.doc_id)
        assert card.preferred_tags == document.content_tags
        assert card.source_offsets == (document.source_start_offset, document.source_end_offset)
        assert card.source_excerpt == document.content[:400].strip()

        loaded = cards_repo.get(conn, fragment_id=card.fragment_id)
        assert loaded is not None
        assert loaded.doc_id == str(document.doc_id)
        assert loaded.preferred_tags == document.content_tags
        assert loaded.source_offsets == (document.source_start_offset, document.source_end_offset)
        assert loaded.source_excerpt == document.content[:400].strip()


def test_scene_brief_service_maps_legacy_scene_plan_to_contract() -> None:
    model_client = SequenceModelClient(
        [
            {
                "scene_objective": "续写这一小段离别前的停顿",
                "emotional_goal": "表现克制型悲伤",
                "conflict_goal": "让人物维持表面平静",
                "narrative_function": ["收束", "情绪沉浸"],
                "emotion_mode": ["克制"],
                "character_temperament": ["敏感", "克制"],
                "relationship_state": ["未和解"],
                "style_need": ["短句", "低对白"],
                "must_avoid": ["突然表白", "设定冲突"],
                "preferred_tags": ["雨天", "告别"],
            }
        ]
    )
    service = SceneBriefService(model_client=model_client)  # type: ignore[arg-type]
    retrieval_input = CreativeKBRetrievalInput(
        anchor_context="上一段写到她没有说再见。",
        recent_window_summary="当前处于误解后的短暂对峙。",
        goal="续写这一小段离别前的停顿",
        retrieval_context=RetrievalContext(character_hits=["林清"], timeline_hits=["第十章"], lore_hits=[]),
        scene_plan={
            "goal": "续写这一小段离别前的停顿",
            "emotional_goal": "表现克制型悲伤",
            "conflict_goal": "让人物维持表面平静",
            "current_relationship_state": ["未和解"],
            "forbidden": ["突然表白"],
            "avoidance_items": ["设定冲突", "突然表白"],
            "style_reference_query": {
                "narrative_function": ["收束", "情绪沉浸"],
                "emotion_mode": ["克制"],
                "character_temperament": ["敏感", "克制"],
                "style_need": ["短句", "低对白"],
            },
            "retrieval_hints": {
                "preferred_tags": ["雨天", "告别"],
            },
        },
    )

    brief = service.build(retrieval_input)

    assert brief.scene_objective == "续写这一小段离别前的停顿"
    assert brief.emotional_goal == "表现克制型悲伤"
    assert brief.conflict_goal == "让人物维持表面平静"
    assert brief.narrative_function == ["收束", "情绪沉浸"]
    assert brief.emotion_mode == ["克制"]
    assert brief.character_temperament == ["敏感", "克制"]
    assert brief.relationship_state == ["未和解"]
    assert brief.style_need == ["短句", "低对白"]
    assert brief.must_avoid == ["突然表白", "设定冲突"]
    assert brief.preferred_tags == ["雨天", "告别"]


def test_coarse_retrieval_and_rerank_form_unique_cluster_selection() -> None:
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
        doc_id="doc-1",
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
        doc_id="doc-2",
        cluster_id="cluster-a",
        is_rep=False,
        content_summary="类似的雨夜告别桥段，但更依赖原章上下文。",
        narrative_function=["收束"],
        narrative_function_text="收束人物关系。",
        emotion_tags=["克制"],
        emotion_mechanism_text="通过省略对白表达退让。",
        character_temperament=["克制"],
        relationship_state=["未和解"],
        preferred_tags=["雨天"],
        style_profile_text="短句、较低对白。",
        transferability_score=0.5,
        context_dependency_level="high",
    )
    other_cluster = _card(
        fragment_id="frag-other",
        doc_id="doc-3",
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
    unrelated = _card(
        fragment_id="frag-unrelated",
        doc_id="doc-4",
        content_summary="热闹校园里轻松调侃的对话场景。",
        narrative_function=["铺垫"],
        narrative_function_text="铺垫轻松氛围。",
        emotion_tags=["轻松"],
        emotion_mechanism_text="通过连续对白推进信息。",
        character_temperament=["外向"],
        relationship_state=["普通同学"],
        preferred_tags=["校园"],
        style_profile_text="高对白、快节奏。",
        transferability_score=0.6,
        context_dependency_level="low",
    )

    clusters = [
        FragmentCluster(
            cluster_id="cluster-a",
            cluster_theme="克制告别",
            representative_fragment_id="frag-rep",
            member_count=2,
            dedup_reason="same beat",
        ),
        FragmentCluster(
            cluster_id="cluster-b",
            cluster_theme="克制余波",
            representative_fragment_id="frag-other",
            member_count=1,
            dedup_reason="single",
        ),
    ]

    coarse = CoarseRetrievalService(candidate_limit=12).retrieve(
        scene_brief=scene_brief,
        fragment_cards=[rep_card, same_cluster_non_rep, other_cluster, unrelated],
        fragment_clusters=clusters,
        fts_fragment_ids=["frag-nonrep", "frag-other"],
    )

    assert "frag-rep" in coarse.candidate_fragment_ids
    assert "frag-other" in coarse.candidate_fragment_ids
    assert "frag-unrelated" not in coarse.candidate_fragment_ids
    assert "frag-nonrep" not in coarse.candidate_fragment_ids
    assert "cluster-a" in coarse.filtered_cluster_ids

    selected_candidates = [rep_card, same_cluster_non_rep, other_cluster]
    rerank_model = SequenceModelClient(
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
                        "context_dependency_penalty": 1,
                        "reason": "主维度高度贴合。",
                    },
                    {
                        "candidate_id": "frag-nonrep",
                        "cluster_id": "cluster-a",
                        "continuity_fit": 6,
                        "scene_function_fit": 6,
                        "character_temperament_fit": 6,
                        "relationship_state_fit": 6,
                        "emotion_expression_fit": 6,
                        "style_fit": 5,
                        "transferability": 4,
                        "context_dependency_penalty": 7,
                        "reason": "同簇但上下文依赖高。",
                    },
                    {
                        "candidate_id": "frag-other",
                        "cluster_id": "cluster-b",
                        "continuity_fit": 5,
                        "scene_function_fit": 7,
                        "character_temperament_fit": 6,
                        "relationship_state_fit": 4,
                        "emotion_expression_fit": 5,
                        "style_fit": 5,
                        "transferability": 8,
                        "context_dependency_penalty": 4,
                        "reason": "部分匹配。",
                    },
                ]
            }
        ]
    )
    rerank = RerankService(top_n=2, model_client=rerank_model).rerank(  # type: ignore[arg-type]
        scene_brief=scene_brief,
        candidates=selected_candidates,
        anchor_context="她没有立刻说出那句告别，只是站在雨里。",
        recent_window_summary="当前需要一段关系收束且避免情绪失控的参考。",
    )

    assert len(rerank.selected_fragment_ids) == 2
    assert "frag-rep" in rerank.selected_fragment_ids
    assert "frag-nonrep" not in rerank.selected_fragment_ids
    assert rerank.selection_notes == "prompt_based_fixed_rubric"
    scores_by_id = {item.candidate_id: item for item in rerank.scores}
    assert scores_by_id["frag-rep"].scene_function_fit >= scores_by_id["frag-unrelated"].scene_function_fit if "frag-unrelated" in scores_by_id else True

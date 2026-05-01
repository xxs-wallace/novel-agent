from __future__ import annotations

from pathlib import Path

from novel_agent.app.repos.creative_kb_storage import init_creative_kb_schema
from novel_agent.app.repos.db import NovelAgentDB
from novel_agent.app.repos.fragment_cards_repo import FragmentCardsRepo
from novel_agent.app.repos.fragment_clusters_repo import FragmentClustersRepo
from novel_agent.app.schemas.creative_kb_schema import FragmentCard, FragmentCluster, SceneBrief, StyleFeatures
from novel_agent.app.schemas.orchestration_schema import CreativeKBRetrievalInput, RetrievalContext
from novel_agent.app.services.retrieval_facade import RetrievalFacade


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


def _retrieval_input() -> CreativeKBRetrievalInput:
    return CreativeKBRetrievalInput(
        anchor_context="上一段写到她没有说再见，只把伞柄握得更紧。",
        recent_window_summary="当前处于误解后的短暂对峙，需要一段关系收束前的停顿。",
        goal="续写一段克制型离别前停顿",
        previous_generated_segment="她想开口，却又停住。",
        retrieval_context=RetrievalContext(character_hits=["林清"], timeline_hits=["第十章"], lore_hits=["雨夜"]),
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


def test_retrieval_facade_default_mainflow_returns_scene_brief_and_rerank_only(tmp_path: Path) -> None:
    db = NovelAgentDB(tmp_path / "retrieval_facade_default.db")
    cards_repo = FragmentCardsRepo()
    clusters_repo = FragmentClustersRepo()
    facade = RetrievalFacade(
        fragment_cards_repo=cards_repo,
        fragment_clusters_repo=clusters_repo,
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
    sibling_card = _card(
        fragment_id="frag-sibling",
        doc_id="doc-2",
        cluster_id="cluster-a",
        is_rep=False,
        content_summary="类似的雨夜停顿，但更依赖前情。",
        narrative_function=["收束"],
        narrative_function_text="收束当前关系。",
        emotion_tags=["克制"],
        emotion_mechanism_text="通过省略对白表达退让。",
        character_temperament=["克制"],
        relationship_state=["未和解"],
        preferred_tags=["雨天", "告别"],
        style_profile_text="短句、较低对白。",
        transferability_score=0.5,
        context_dependency_level="high",
    )
    other_card = _card(
        fragment_id="frag-other",
        doc_id="doc-3",
        cluster_id="cluster-b",
        is_rep=True,
        content_summary="医院走廊里的失去余波，靠动作维持秩序。",
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
    clusters = [
        FragmentCluster(
            cluster_id="cluster-a",
            cluster_theme="雨夜告别停顿",
            representative_fragment_id="frag-rep",
            member_count=2,
            dedup_reason="same_style_pattern_with_minor_entity_changes",
        ),
        FragmentCluster(
            cluster_id="cluster-b",
            cluster_theme="医院余波",
            representative_fragment_id="frag-other",
            member_count=1,
            dedup_reason="singleton",
        ),
    ]

    with db.connect() as conn:
        db.init_schema(conn)
        init_creative_kb_schema(conn)
        cards_repo.upsert_cards(conn, [rep_card, sibling_card, other_card])
        clusters_repo.upsert_clusters(conn, clusters)
        conn.commit()

        result = facade.build_scene_brief_and_retrieve(conn, retrieval_input=_retrieval_input())

    payload = result.to_dict()
    assert sorted(payload.keys()) == ["rerank_result", "scene_brief"]
    assert payload["scene_brief"]["scene_objective"] == "续写一段克制型离别前停顿"
    assert payload["rerank_result"]["selected_fragment_ids"]
    assert "coarse_result" not in payload
    assert "reference_fragments" not in payload


def test_retrieval_facade_can_include_debug_and_expanded_reference_fields(tmp_path: Path) -> None:
    db = NovelAgentDB(tmp_path / "retrieval_facade_expanded.db")
    cards_repo = FragmentCardsRepo()
    clusters_repo = FragmentClustersRepo()
    facade = RetrievalFacade(
        fragment_cards_repo=cards_repo,
        fragment_clusters_repo=clusters_repo,
    )
    first_card = _card(
        fragment_id="frag-a",
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
        transferability_score=0.92,
        context_dependency_level="low",
    )
    second_card = _card(
        fragment_id="frag-b",
        doc_id="doc-2",
        cluster_id="cluster-b",
        is_rep=True,
        content_summary="同样克制，但更强调告别前的迟疑与停顿。",
        narrative_function=["收束", "情绪沉浸"],
        narrative_function_text="借停顿和不说满的话维持关系张力。",
        emotion_tags=["克制", "悲伤"],
        emotion_mechanism_text="以沉默和缓慢动作承接悲伤。",
        character_temperament=["敏感", "克制"],
        relationship_state=["未和解"],
        preferred_tags=["告别", "停顿"],
        style_profile_text="短句、低对白，动作停顿明显。",
        transferability_score=0.88,
        context_dependency_level="low",
    )
    clusters = [
        FragmentCluster(
            cluster_id="cluster-a",
            cluster_theme="雨夜告别停顿 A",
            representative_fragment_id="frag-a",
            member_count=1,
            dedup_reason="singleton",
        ),
        FragmentCluster(
            cluster_id="cluster-b",
            cluster_theme="雨夜告别停顿 B",
            representative_fragment_id="frag-b",
            member_count=1,
            dedup_reason="singleton",
        ),
    ]

    with db.connect() as conn:
        db.init_schema(conn)
        init_creative_kb_schema(conn)
        cards_repo.upsert_cards(conn, [first_card, second_card])
        clusters_repo.upsert_clusters(conn, clusters)
        conn.commit()

        result = facade.retrieve_reference_fragments(
            conn,
            scene_brief=SceneBrief(
                scene_objective="寻找一段克制型离别参考",
                emotional_goal="压住悲伤",
                conflict_goal="保持表面平静",
                narrative_function=["收束", "情绪沉浸"],
                emotion_mode=["克制", "悲伤"],
                character_temperament=["敏感", "克制"],
                relationship_state=["未和解"],
                style_need=["短句", "低对白"],
                must_avoid=["突然表白"],
                preferred_tags=["雨天", "告别"],
            ),
            include_coarse_result=True,
            expand_reference_fragments=True,
        )

    payload = result.to_dict()
    assert "coarse_result" in payload
    assert "reference_fragments" in payload
    assert payload["reference_fragments"]
    selected_ids = payload["rerank_result"]["selected_fragment_ids"]
    expanded_ids = [item["fragment_id"] for item in payload["reference_fragments"]]
    assert expanded_ids == selected_ids


def test_retrieval_context_cannot_bypass_fragment_card_main_path(tmp_path: Path) -> None:
    db = NovelAgentDB(tmp_path / "retrieval_facade_context_only.db")
    facade = RetrievalFacade()

    with db.connect() as conn:
        db.init_schema(conn)
        init_creative_kb_schema(conn)
        result = facade.build_scene_brief_and_retrieve(
            conn,
            retrieval_input=_retrieval_input(),
            expand_reference_fragments=True,
        )

    payload = result.to_dict()
    assert payload["scene_brief"]["scene_objective"] == "续写一段克制型离别前停顿"
    assert payload["rerank_result"]["selected_fragment_ids"] == []
    assert result.reference_fragments == []
    assert "reference_fragments" not in payload

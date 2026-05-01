from __future__ import annotations

from pathlib import Path

from novel_agent.app.orchestrators import MainLayerOrchestrator
from novel_agent.app.repos.creative_kb_storage import init_creative_kb_schema
from novel_agent.app.repos.db import NovelAgentDB
from novel_agent.app.repos.fragment_cards_repo import FragmentCardsRepo
from novel_agent.app.repos.fragment_clusters_repo import FragmentClustersRepo
from novel_agent.app.schemas.context_assembly_schema import (
    ChapterContextItem,
    CharacterProfileContextItem,
    ContextAssemblyPayload,
)
from novel_agent.app.schemas.creative_kb_schema import FragmentCard, FragmentCluster, SceneBrief, StyleFeatures


class _FakeContextAssemblyService:
    def __init__(self, payload: ContextAssemblyPayload) -> None:
        self.payload = payload
        self.last_input = None

    def assemble(self, conn, *, assembly_input):  # type: ignore[no-untyped-def]
        self.last_input = assembly_input
        return self.payload


def _card(
    *,
    fragment_id: str,
    doc_id: str,
    cluster_id: str | None = None,
    is_rep: bool = False,
    content_summary: str,
    narrative_function_text: str,
    emotion_mechanism_text: str,
    style_profile_text: str,
    preferred_tags: list[str],
    relationship_state: list[str],
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
        narrative_function=["收束", "情绪沉浸"],
        narrative_function_text=narrative_function_text,
        scene_space_tags=["雨夜", "街道"],
        event_tags=["告别"],
        emotion_tags=["克制", "悲伤"],
        emotion_mechanism_text=emotion_mechanism_text,
        expression_mode_tags=["动作描写", "心理活动"],
        preferred_tags=preferred_tags,
        pov_mode="近距离第三人称",
        character_focus=["林清"],
        character_temperament=["敏感", "克制"],
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
        transferability_score=0.9,
        context_dependency_level="low",
    )


def test_main_layer_orchestrator_prepares_creative_kb_input() -> None:
    orchestrator = MainLayerOrchestrator()

    retrieval_input = orchestrator.prepare_creative_kb_input(
        anchor_context="  锚点上下文  ",
        recent_window_summary="  最近窗口  ",
        goal="  当前目标  ",
        previous_generated_segment="  上一段  ",
        retrieval_context={
            "character_hits": ["林清", "林清", ""],
            "timeline_hits": ["第十章"],
            "lore_hits": ["雨夜"],
        },
        scene_plan={"goal": "旧计划"},
        documents=[{"doc_id": "1"}],
    )

    assert retrieval_input.anchor_context == "锚点上下文"
    assert retrieval_input.recent_window_summary == "最近窗口"
    assert retrieval_input.goal == "当前目标"
    assert retrieval_input.previous_generated_segment == "上一段"
    assert retrieval_input.retrieval_context.character_hits == ["林清"]
    assert retrieval_input.retrieval_context.timeline_hits == ["第十章"]
    assert retrieval_input.retrieval_context.lore_hits == ["雨夜"]
    assert retrieval_input.scene_plan == {"goal": "旧计划"}
    assert retrieval_input.documents == [{"doc_id": "1"}]


def test_main_layer_orchestrator_routes_online_retrieval_through_creative_kb(tmp_path: Path) -> None:
    db = NovelAgentDB(tmp_path / "main_layer_orchestrator.db")
    cards_repo = FragmentCardsRepo()
    clusters_repo = FragmentClustersRepo()
    orchestrator = MainLayerOrchestrator()
    explicit_scene_brief = SceneBrief(
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
    )

    with db.connect() as conn:
        db.init_schema(conn)
        init_creative_kb_schema(conn)
        cards_repo.upsert_cards(
            conn,
            [
                _card(
                    fragment_id="frag-rep",
                    doc_id="doc-1",
                    cluster_id="cluster-a",
                    is_rep=True,
                    content_summary="敏感的人在雨夜告别前压住悲伤，不肯把话说满。",
                    narrative_function_text="通过停顿和未尽之语收束关系冲突。",
                    emotion_mechanism_text="先压住眼泪，再用动作回避告别。",
                    style_profile_text="短句、低对白、高内心密度。",
                    preferred_tags=["雨天", "告别"],
                    relationship_state=["未和解"],
                ),
                _card(
                    fragment_id="frag-other",
                    doc_id="doc-2",
                    cluster_id="cluster-b",
                    is_rep=True,
                    content_summary="医院走廊里的失去余波，靠动作维持秩序。",
                    narrative_function_text="在事件余波中维持秩序感。",
                    emotion_mechanism_text="通过动作与沉默消化失去。",
                    style_profile_text="低对白、中内心密度。",
                    preferred_tags=["医院", "失去"],
                    relationship_state=["失去后"],
                ),
            ],
        )
        clusters_repo.upsert_clusters(
            conn,
            [
                FragmentCluster(
                    cluster_id="cluster-a",
                    cluster_theme="雨夜告别停顿",
                    representative_fragment_id="frag-rep",
                    member_count=1,
                    dedup_reason="singleton",
                ),
                FragmentCluster(
                    cluster_id="cluster-b",
                    cluster_theme="医院余波",
                    representative_fragment_id="frag-other",
                    member_count=1,
                    dedup_reason="singleton",
                ),
            ],
        )
        conn.commit()

        result = orchestrator.run_online_creative_kb_path(
            conn,
            anchor_context="上一段写到她没有说再见，只把伞柄握得更紧。",
            recent_window_summary="当前处于误解后的短暂对峙，需要一段关系收束前的停顿。",
            goal="续写一段克制型离别前停顿",
            previous_generated_segment="她想开口，却又停住。",
            retrieval_context={
                "character_hits": ["林清"],
                "timeline_hits": ["第十章"],
                "lore_hits": ["雨夜"],
            },
            scene_plan={"goal": "旧 ScenePlan 不应覆盖显式 SceneBrief"},
            scene_brief=explicit_scene_brief,
            expand_reference_fragments=True,
        )

    assert result.scene_brief.to_dict() == explicit_scene_brief.to_dict()
    assert result.rerank_result.selected_fragment_ids
    assert result.rerank_result.selected_fragment_ids[0] == "frag-rep"
    assert result.reference_fragments
    assert result.reference_fragments[0].fragment_id == "frag-rep"


def test_main_layer_orchestrator_builds_writer_input_bundle_from_retrieval_result(tmp_path: Path) -> None:
    db = NovelAgentDB(tmp_path / "main_layer_writer_bundle.db")
    cards_repo = FragmentCardsRepo()
    clusters_repo = FragmentClustersRepo()
    orchestrator = MainLayerOrchestrator()
    explicit_scene_brief = SceneBrief(
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
    )

    with db.connect() as conn:
        db.init_schema(conn)
        init_creative_kb_schema(conn)
        cards_repo.upsert_cards(
            conn,
            [
                _card(
                    fragment_id="frag-rep",
                    doc_id="doc-1",
                    cluster_id="cluster-a",
                    is_rep=True,
                    content_summary="敏感的人在雨夜告别前压住悲伤，不肯把话说满。",
                    narrative_function_text="通过停顿和未尽之语收束关系冲突。",
                    emotion_mechanism_text="先压住眼泪，再用动作回避告别。",
                    style_profile_text="短句、低对白、高内心密度。",
                    preferred_tags=["雨天", "告别"],
                    relationship_state=["未和解"],
                )
            ],
        )
        clusters_repo.upsert_clusters(
            conn,
            [
                FragmentCluster(
                    cluster_id="cluster-a",
                    cluster_theme="雨夜告别停顿",
                    representative_fragment_id="frag-rep",
                    member_count=1,
                    dedup_reason="singleton",
                )
            ],
        )
        conn.commit()

        retrieval_result = orchestrator.run_online_creative_kb_path(
            conn,
            anchor_context="上一段写到她没有说再见，只把伞柄握得更紧。",
            recent_window_summary="当前处于误解后的短暂对峙，需要一段关系收束前的停顿。",
            goal="续写一段克制型离别前停顿",
            previous_generated_segment="她想开口，却又停住。",
            retrieval_context={
                "character_hits": ["林清"],
                "timeline_hits": ["第十章"],
                "lore_hits": ["雨夜"],
            },
            scene_plan={"goal": "旧 ScenePlan 不应覆盖显式 SceneBrief"},
            scene_brief=explicit_scene_brief,
            expand_reference_fragments=True,
        )

    bundle = orchestrator.build_writer_input_bundle(
        anchor_context="上一段写到她没有说再见，只把伞柄握得更紧。",
        recent_window_summary="当前处于误解后的短暂对峙，需要一段关系收束前的停顿。",
        retrieval_result=retrieval_result,
    )

    assert bundle.scene_brief.to_dict() == explicit_scene_brief.to_dict()
    assert [item.fragment_id for item in bundle.reference_fragments] == ["frag-rep"]
    assert bundle.reference_fragments[0].source_excerpt == "她站在雨里，没有立刻说出那句告别。"
    assert bundle.sources[0].path == "/tmp/source.md"


def test_main_layer_orchestrator_assembles_memory_context_into_writer_input_bundle(tmp_path: Path) -> None:
    db = NovelAgentDB(tmp_path / "main_layer_memory_bundle.db")
    cards_repo = FragmentCardsRepo()
    clusters_repo = FragmentClustersRepo()
    fake_context_service = _FakeContextAssemblyService(
        ContextAssemblyPayload(
            chapter_context=[
                ChapterContextItem(
                    document_title_index="10",
                    chapter_title="第十章 雨中对话",
                    summary_md="两人停在雨里，关系进入收束前的短暂停顿。",
                    importance_score=8,
                )
            ],
            world_summary_md="故事发生在现代都市，没有超自然设定。",
            character_profiles=[
                CharacterProfileContextItem(
                    canonical_name="林清",
                    profile_summary_md="情绪克制，遇到重大情感冲突时会先压住表达。",
                    aliases=["小清"],
                    importance_score=9,
                )
            ],
            story_outline_md="主线推进到误解后的对峙与关系收束阶段。",
            missing_context=[],
        )
    )
    orchestrator = MainLayerOrchestrator(context_assembly_service=fake_context_service)
    explicit_scene_brief = SceneBrief(
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
    )

    with db.connect() as conn:
        db.init_schema(conn)
        init_creative_kb_schema(conn)
        cards_repo.upsert_cards(
            conn,
            [
                _card(
                    fragment_id="frag-rep",
                    doc_id="doc-1",
                    cluster_id="cluster-a",
                    is_rep=True,
                    content_summary="敏感的人在雨夜告别前压住悲伤，不肯把话说满。",
                    narrative_function_text="通过停顿和未尽之语收束关系冲突。",
                    emotion_mechanism_text="先压住眼泪，再用动作回避告别。",
                    style_profile_text="短句、低对白、高内心密度。",
                    preferred_tags=["雨天", "告别"],
                    relationship_state=["未和解"],
                )
            ],
        )
        clusters_repo.upsert_clusters(
            conn,
            [
                FragmentCluster(
                    cluster_id="cluster-a",
                    cluster_theme="雨夜告别停顿",
                    representative_fragment_id="frag-rep",
                    member_count=1,
                    dedup_reason="singleton",
                )
            ],
        )
        conn.commit()

        retrieval_result = orchestrator.run_online_creative_kb_path(
            conn,
            anchor_context="上一段写到她没有说再见，只把伞柄握得更紧。",
            recent_window_summary="当前处于误解后的短暂对峙，需要一段关系收束前的停顿。",
            goal="续写一段克制型离别前停顿",
            previous_generated_segment="她想开口，却又停住。",
            retrieval_context={
                "character_hits": ["林清"],
                "timeline_hits": ["第十章"],
                "lore_hits": ["雨夜"],
            },
            scene_plan={"goal": "旧 ScenePlan 不应覆盖显式 SceneBrief"},
            scene_brief=explicit_scene_brief,
            expand_reference_fragments=True,
        )
        context_payload = orchestrator.assemble_context_payload(
            conn,
            book_id="book-1",
            document_title_index="10",
            related_character_names=["林清"],
        )

    bundle = orchestrator.build_writer_input_bundle(
        anchor_context="上一段写到她没有说再见，只把伞柄握得更紧。",
        recent_window_summary="当前处于误解后的短暂对峙，需要一段关系收束前的停顿。",
        retrieval_result=retrieval_result,
        context_payload=context_payload,
    )

    assert fake_context_service.last_input is not None
    assert fake_context_service.last_input.book_id == "book-1"
    assert fake_context_service.last_input.document_title_index == "10"
    assert fake_context_service.last_input.related_character_names == ["林清"]
    assert bundle.context_payload.world_summary_md == "故事发生在现代都市，没有超自然设定。"
    assert bundle.context_payload.chapter_context[0].chapter_title == "第十章 雨中对话"
    assert bundle.context_payload.character_profiles[0].canonical_name == "林清"

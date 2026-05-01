from __future__ import annotations

from pathlib import Path

from novel_agent.app.repos.creative_kb_storage import init_creative_kb_schema
from novel_agent.app.repos.db import NovelAgentDB
from novel_agent.app.repos.fragment_cards_repo import FragmentCardsRepo
from novel_agent.app.repos.fragment_clusters_repo import FragmentClustersRepo
from novel_agent.app.schemas.creative_kb_schema import FragmentCard, FragmentCluster, StyleFeatures
from novel_agent.app.services.fragment_cluster_service import FragmentClusterService


def _card(
    *,
    fragment_id: str,
    doc_id: str,
    cluster_id: str | None = None,
    is_rep: bool = False,
    content_summary: str,
    narrative_function: list[str],
    narrative_function_text: str,
    event_tags: list[str],
    emotion_tags: list[str],
    emotion_mechanism_text: str,
    relationship_state: list[str],
    preferred_tags: list[str],
    style_profile_text: str,
    transferability_score: float = 0.80,
    context_dependency_level: str = "medium",
    continuity_phase: str = "冲突后收束",
    imagery_density: str = "中",
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
        source_excerpt=(
            "她站在雨里，话只说到一半，伞沿落下的水线把停顿切得更长，"
            "也把那些没说出口的情绪压回了喉咙。"
        ),
        content_summary=content_summary,
        narrative_function=narrative_function,
        narrative_function_text=narrative_function_text,
        scene_space_tags=["雨夜", "街道"],
        event_tags=event_tags,
        emotion_tags=emotion_tags,
        emotion_mechanism_text=emotion_mechanism_text,
        expression_mode_tags=["动作描写", "心理活动"],
        preferred_tags=preferred_tags,
        pov_mode="近距离第三人称",
        character_focus=["林清"],
        character_temperament=["克制", "敏感"],
        character_relation_text="关系停在未和解的告别边缘。",
        relationship_state=relationship_state,
        continuity_phase=continuity_phase,
        style_features=StyleFeatures(
            sentence_rhythm="短句偏多",
            dialogue_density="低",
            interiority_density="高",
            imagery_density=imagery_density,
        ),
        style_profile_text=style_profile_text,
        transferability_score=transferability_score,
        context_dependency_level=context_dependency_level,  # type: ignore[arg-type]
    )


def test_fragment_cluster_service_merges_near_duplicates_and_backfills_clusters(tmp_path: Path) -> None:
    db = NovelAgentDB(tmp_path / "fragment_cluster.db")
    cards_repo = FragmentCardsRepo()
    clusters_repo = FragmentClustersRepo()
    service = FragmentClusterService(
        fragment_cards_repo=cards_repo,
        fragment_clusters_repo=clusters_repo,
    )

    merged_left = _card(
        fragment_id="frag-merge-a",
        doc_id="doc-1",
        cluster_id="legacy-a",
        content_summary="雨夜里的人把告别压进停顿里，用沉默收束尚未和解的关系。",
        narrative_function=["收束", "情绪沉浸"],
        narrative_function_text="在关系紧绷后用未尽之语收束场面，让离开感慢慢沉下去。",
        event_tags=["告别"],
        emotion_tags=["克制", "悲伤"],
        emotion_mechanism_text="通过停顿、避视和抓紧伞柄的动作压住悲伤。",
        relationship_state=["未和解"],
        preferred_tags=["雨天", "告别"],
        style_profile_text="短句、低对白、高内心密度，用动作停顿承载情绪。",
        transferability_score=0.88,
        context_dependency_level="low",
    )
    merged_right = _card(
        fragment_id="frag-merge-b",
        doc_id="doc-2",
        cluster_id="legacy-a",
        content_summary="人物在雨夜告别前反复停顿，不肯把最后一句话说满，以沉默收束关系。",
        narrative_function=["收束", "情绪沉浸"],
        narrative_function_text="通过不说破的告别收束关系冲突，让情绪停留在未尽状态。",
        event_tags=["告别"],
        emotion_tags=["克制", "悲伤"],
        emotion_mechanism_text="用沉默、缓慢动作和避开目光的方式压住悲伤。",
        relationship_state=["未和解"],
        preferred_tags=["雨天", "告别"],
        style_profile_text="短句、低对白，以动作和少量心理描写承接悲伤。",
        transferability_score=0.76,
        context_dependency_level="medium",
    )
    singleton = _card(
        fragment_id="frag-singleton",
        doc_id="doc-3",
        cluster_id="legacy-b",
        content_summary="医院走廊里的人靠整理病历维持秩序，勉强处理失去后的空白。",
        narrative_function=["余波", "收束"],
        narrative_function_text="在事件余波里维持秩序感，不直接处理关系告别。",
        event_tags=["失去"],
        emotion_tags=["麻木"],
        emotion_mechanism_text="通过机械动作和沉默消化失去。",
        relationship_state=["失去后"],
        preferred_tags=["医院", "失去"],
        style_profile_text="低对白、中内心密度，以环境和动作维持冷感。",
        transferability_score=0.72,
        context_dependency_level="medium",
        continuity_phase="事件余波",
    )

    legacy_clusters = [
        FragmentCluster(
            cluster_id="legacy-a",
            cluster_theme="旧聚类 A",
            representative_fragment_id="frag-merge-a",
            member_count=2,
            dedup_reason="legacy",
        ),
        FragmentCluster(
            cluster_id="legacy-b",
            cluster_theme="旧聚类 B",
            representative_fragment_id="frag-singleton",
            member_count=1,
            dedup_reason="legacy",
        ),
    ]

    with db.connect() as conn:
        db.init_schema(conn)
        init_creative_kb_schema(conn)
        cards_repo.upsert_cards(conn, [merged_left, merged_right, singleton])
        clusters_repo.upsert_clusters(conn, legacy_clusters)

        result = service.cluster_and_persist(
            conn,
            fragment_cards=[merged_left, merged_right, singleton],
        )
        conn.commit()

        assert len(result.fragment_clusters) == 2
        cards_by_id = {card.fragment_id: card for card in result.fragment_cards}
        assert cards_by_id["frag-merge-a"].cluster_id == cards_by_id["frag-merge-b"].cluster_id
        assert cards_by_id["frag-merge-a"].cluster_id != cards_by_id["frag-singleton"].cluster_id
        assert cards_by_id["frag-merge-a"].is_cluster_representative is True
        assert cards_by_id["frag-merge-b"].is_cluster_representative is False
        assert cards_by_id["frag-singleton"].is_cluster_representative is True

        stored_left = cards_repo.get(conn, fragment_id="frag-merge-a")
        stored_right = cards_repo.get(conn, fragment_id="frag-merge-b")
        stored_singleton = cards_repo.get(conn, fragment_id="frag-singleton")
        assert stored_left is not None
        assert stored_right is not None
        assert stored_singleton is not None
        assert stored_left.cluster_id == stored_right.cluster_id
        assert stored_left.is_cluster_representative is True
        assert stored_right.is_cluster_representative is False
        assert stored_singleton.is_cluster_representative is True

        merged_cluster = clusters_repo.get(conn, cluster_id=stored_left.cluster_id or "")
        singleton_cluster = clusters_repo.get(conn, cluster_id=stored_singleton.cluster_id or "")
        assert merged_cluster is not None
        assert singleton_cluster is not None
        assert merged_cluster.member_count == 2
        assert merged_cluster.representative_fragment_id == "frag-merge-a"
        assert merged_cluster.dedup_reason.startswith("near_duplicate_cluster:")
        assert singleton_cluster.member_count == 1
        assert singleton_cluster.representative_fragment_id == "frag-singleton"

        assert clusters_repo.get(conn, cluster_id="legacy-a") is None
        assert clusters_repo.get(conn, cluster_id="legacy-b") is None


def test_fragment_cluster_service_blocks_same_event_with_different_narrative_use() -> None:
    service = FragmentClusterService()
    left = _card(
        fragment_id="frag-left",
        doc_id="doc-1",
        content_summary="雨夜告别前的沉默停顿，用来收束未和解关系。",
        narrative_function=["收束"],
        narrative_function_text="在离开前收束关系张力。",
        event_tags=["告别"],
        emotion_tags=["克制", "悲伤"],
        emotion_mechanism_text="通过停顿和避视压住悲伤。",
        relationship_state=["未和解"],
        preferred_tags=["雨天", "告别"],
        style_profile_text="短句、低对白、动作停顿明显。",
        context_dependency_level="low",
    )
    right = _card(
        fragment_id="frag-right",
        doc_id="doc-2",
        content_summary="同样发生在雨夜告别，但核心是借争执升级推动下一场冲突。",
        narrative_function=["冲突升级"],
        narrative_function_text="把告别场景改写成下一轮争执的起爆点。",
        event_tags=["告别"],
        emotion_tags=["愤怒"],
        emotion_mechanism_text="靠连续对白和指责推高对抗。",
        relationship_state=["对立升级"],
        preferred_tags=["雨天", "告别"],
        style_profile_text="高对白、快节奏、直接冲突，不强调留白。",
        context_dependency_level="low",
        continuity_phase="冲突升级",
    )

    decision = service.evaluate_pair(left, right)

    assert decision.merge is False
    assert decision.boundary_reason == "same_event_but_different_narrative_function"
    assert decision.event_overlap >= 1.0


def test_fragment_cluster_service_downweights_high_dependency_literary_member_for_representative() -> None:
    service = FragmentClusterService()
    grounded = _card(
        fragment_id="frag-grounded",
        doc_id="doc-1",
        content_summary="两人在雨夜停顿着告别，以沉默和动作收束关系。",
        narrative_function=["收束", "情绪沉浸"],
        narrative_function_text="在关系未和解时用停顿与不说破完成收束。",
        event_tags=["告别"],
        emotion_tags=["克制", "悲伤"],
        emotion_mechanism_text="通过沉默、停顿和抓紧伞柄压住情绪。",
        relationship_state=["未和解"],
        preferred_tags=["雨天", "告别"],
        style_profile_text="短句、低对白、高内心密度，信息完整且可迁移。",
        transferability_score=0.86,
        context_dependency_level="low",
        imagery_density="中",
    )
    literary = _card(
        fragment_id="frag-literary",
        doc_id="doc-2",
        content_summary="雨幕像未合上的页角，人物在停顿中让告别缓慢下沉。",
        narrative_function=["收束", "情绪沉浸"],
        narrative_function_text="借未尽之语与留白完成关系收束。",
        event_tags=["告别"],
        emotion_tags=["克制", "悲伤"],
        emotion_mechanism_text="通过留白、意象和极少对白压住悲伤。",
        relationship_state=["未和解"],
        preferred_tags=["雨天", "告别"],
        style_profile_text="意象密集、留白明显、抒情偏强，诗性表达依赖上下文回声。",
        transferability_score=0.92,
        context_dependency_level="high",
        imagery_density="高",
    )

    result = service.cluster_cards([grounded, literary])

    cards_by_id = {card.fragment_id: card for card in result.fragment_cards}
    assert cards_by_id["frag-grounded"].cluster_id == cards_by_id["frag-literary"].cluster_id
    assert cards_by_id["frag-grounded"].is_cluster_representative is True
    assert cards_by_id["frag-literary"].is_cluster_representative is False

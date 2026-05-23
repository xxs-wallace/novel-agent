from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
from typing import Any

from novel_agent.app.repos.assets_repo import AssetsRepo
from novel_agent.app.repos.chapters_repo import ChaptersRepo
from novel_agent.app.repos.creative_kb_storage import init_creative_kb_schema
from novel_agent.app.repos.db import NovelAgentDB
from novel_agent.app.repos.fragment_cards_repo import FragmentCardsRepo
from novel_agent.app.schemas.creative_kb_schema import FragmentCard, StyleFeatures
from novel_agent.app.schemas.narrative_index_schema import (
    IndexCard,
    IndexQueryBudget,
    IndexQueryIntent,
    NarrativeSceneCard,
)
from novel_agent.app.schemas.narrative_inquiry_schema import AnalyzerBudget, NarrativeInquiryRequest
from novel_agent.app.services.narrative_index_facade import NarrativeIndexFacade
from novel_agent.app.services.narrative_inquiry_broker import NarrativeInquiryBroker
from novel_agent.app.services.narrative_scene_indexer_service import NarrativeSceneIndexerService


class FakeSceneModelClient:
    def __init__(self) -> None:
        self.settings = SimpleNamespace(dry_run=False)
        self.calls: list[dict[str, str]] = []

    def generate_json(
        self,
        *,
        system_prompt: str,
        user_prompt: str,
        fallback_factory: Any,
        use_fallback_on_error: bool = False,
    ) -> tuple[dict[str, Any], str]:
        _ = fallback_factory, use_fallback_on_error
        self.calls.append({"system_prompt": system_prompt, "user_prompt": user_prompt})
        return (
            {
                "scene_cards": [
                    {
                        "label": "卡塞尔邀请与世界入口",
                        "summary": "路明非收到卡塞尔学院邀请，个人低谷与龙族世界入口在同一场景中发生转折。",
                        "scene_type": "plot_turning_point",
                        "participants": ["路明非"],
                        "source_doc_ids": [1, 2],
                        "source_title_indexes": [1],
                        "scene_boundary": {
                            "start_doc_id": "1",
                            "end_doc_id": "2",
                            "boundary_confidence": 0.88,
                            "overlap_window_id": "scene-window-0001",
                        },
                        "trigger": "学院邀请抵达。",
                        "turning_point": "平凡生活被龙族世界召唤打断。",
                        "outcome": "主线从个人失意转向未知世界。",
                        "character_pressure": ["自我低谷", "被选择的不确定感"],
                        "relationship_movements": [],
                        "world_or_mystery_signals": ["龙族血统", "卡塞尔学院"],
                        "future_consequence": "后续会围绕学院与血统规则展开。",
                        "query_facets": ["主线入口", "龙族血统"],
                        "importance_facets": ["plot_turning_point"],
                        "summary_sufficiency": "needs_raw_for_emotional_texture",
                        "raw_read_reason": "需要原文确认路明非低谷情绪的表达质感。",
                        "status": "committed",
                        "confidence": 0.88,
                    }
                ]
            },
            "{}",
        )


def _insert_documents(conn, *, book_id: str = "book-1") -> None:
    conn.execute(
        """
        INSERT INTO documents(doc_id, book_id, path, scope, content, document_title, document_title_index, content_chars)
        VALUES
            (1, ?, '/tmp/source.txt', 'chapter', '路明非收到学院邀请。', '第一章', 1, 10),
            (2, ?, '/tmp/source.txt', 'chapter', '卡塞尔学院展示龙族规则。', '第一章', 1, 12)
        """,
        (book_id, book_id),
    )


def _upsert_chapter(conn, *, book_id: str = "book-1") -> None:
    ChaptersRepo().upsert(
        conn,
        {
            "book_id": book_id,
            "document_title_index": 1,
            "chapter_title": "第一章",
            "source_doc_start_id": 1,
            "source_doc_end_id": 2,
            "source_doc_count": 2,
            "source_total_chars": 22,
            "summary_intermediate": [],
            "summary_md": "路明非在低谷中收到卡塞尔学院邀请，并接触到龙族血统与学院规则。",
            "summary_short": "路明非收到卡塞尔邀请，龙族世界规则首次浮现。",
            "summary_status": "committed",
            "summary_evidence_window": "",
            "summary_target_range": "",
            "importance_score": 90,
            "importance_reason": "主线入口",
            "related_chapters": [],
            "mentioned_characters": ["路明非"],
            "world_update": {
                "should_update": True,
                "changes": [
                    {
                        "section": "血统规则",
                        "summary": "龙族血统影响学生身份与学院筛选。",
                        "evidence": "卡塞尔学院邀请与血统测试相关。",
                    }
                ],
            },
            "outline_update": {
                "chapter_line": "[1] 第一章: 路明非收到卡塞尔邀请，龙族世界入口打开。",
                "outline_segment_id": "outline-segment:chapter-1:docs-1-2",
                "outline_segment": "路明非在自我低谷中收到卡塞尔学院邀请，原本平凡的生活被龙族血统与学院筛选机制撬开，主线从个人失意转向未知世界的召唤。",
                "source_doc_ids": [1, 2],
                "source_doc_range": "1-2",
                "source_title_indexes": [1],
            },
            "outline_status": "committed",
            "outline_evidence_window": "",
            "outline_target_range": "",
            "close_read_run_id": "run-1",
            "created_at": "2026-01-01T00:00:00Z",
            "updated_at": "2026-01-01T00:00:00Z",
        },
    )


def _fragment_card() -> FragmentCard:
    return FragmentCard(
        fragment_id="fragment-1",
        doc_id="1",
        document_title="第一章",
        document_title_index="1",
        source_path="/tmp/source.txt",
        source_offsets=(0, 10),
        source_excerpt="路明非沉默着接受邀请。",
        content_summary="失意少年收到命运邀请的桥段。",
        narrative_function=["命运召唤"],
        narrative_function_text="用外部邀请打开主线。",
        scene_space_tags=["校园"],
        event_tags=["邀请"],
        emotion_tags=["失落", "转机"],
        emotion_mechanism_text="先压低自我评价，再引入转机。",
        expression_mode_tags=["心理描写"],
        preferred_tags=["失意少年", "命运邀请"],
        pov_mode="第三人称",
        character_focus=["路明非"],
        character_temperament=["自嘲"],
        character_relation_text="人物处于被选择的位置。",
        relationship_state=["初识"],
        continuity_phase="开端",
        style_features=StyleFeatures(
            sentence_rhythm="中",
            dialogue_density="低",
            interiority_density="高",
            imagery_density="低",
        ),
        style_profile_text="自嘲心理和命运转机并置。",
        transferability_score=0.8,
        context_dependency_level="low",
    )


def test_index_card_schema_uses_world_concept_not_world_rule() -> None:
    card = IndexCard(
        card_id="world-concept:book-1:1",
        card_type="world_concept",
        book_id="book-1",
        summary="龙族血统影响学院筛选。",
        query_facets=["血统规则"],
        payload={"kind": "rule"},
    )

    assert card.card_type == "world_concept"
    assert card.payload["kind"] == "rule"


def test_narrative_scene_card_schema_accepts_scene_payload() -> None:
    card = IndexCard(
        card_id="scene-card-1",
        card_type="narrative_scene",
        book_id="book-1",
        summary="路明非收到学院邀请，主线入口打开。",
        source_doc_ids=["1", "2"],
        source_title_indexes=[1],
        summary_sufficiency="needs_raw_for_emotional_texture",
        payload={
            "scene_type": "plot_turning_point",
            "label": "卡塞尔邀请",
            "participants": ["路明非"],
            "scene_boundary": {
                "start_doc_id": "1",
                "end_doc_id": "2",
                "boundary_confidence": 0.9,
                "overlap_window_id": "scene-window-0001",
            },
        },
    )

    scene = NarrativeSceneCard.from_mapping(card.to_dict())

    assert scene.card.card_type == "narrative_scene"
    assert scene.scene.scene_type == "plot_turning_point"
    assert scene.scene.scene_boundary.start_doc_id == "1"
    assert scene.to_index_card().summary_sufficiency == "needs_raw_for_emotional_texture"


def test_narrative_scene_indexer_builds_persists_and_facade_searches_scene_cards(tmp_path: Path) -> None:
    db = NovelAgentDB(tmp_path / "scene-index.db")
    with db.connect() as conn:
        db.init_schema(conn)
        init_creative_kb_schema(conn)
        _insert_documents(conn)
        _upsert_chapter(conn)
        conn.commit()

        model_client = FakeSceneModelClient()
        scene_indexer = NarrativeSceneIndexerService(repo_root=tmp_path, window_chars_budget=1000)
        cards = scene_indexer.build_scene_cards(
            conn,
            book_id="book-1",
            model_client=model_client,
            persist=True,
        )

        facade = NarrativeIndexFacade(repo_root=tmp_path)
        result = facade.search_cards(
            conn,
            book_id="book-1",
            intent=IndexQueryIntent(
                original_query="路明非收到卡塞尔邀请后剧情如何转折？",
                consumer="analyzer",
                target_card_types=["narrative_scene"],
                query_facets=["主线入口", "龙族血统"],
                must_include_characters=["路明非"],
            ),
            budget=IndexQueryBudget(max_candidate_cards=4),
        )

    assert model_client.calls
    assert len(cards) == 1
    assert cards[0].card_type == "narrative_scene"
    assert cards[0].payload["scene_type"] == "plot_turning_point"
    assert cards[0].source_doc_ids == ["1", "2"]
    assert scene_indexer.artifact_path("book-1").exists()
    assert result.candidate_cards
    assert result.candidate_cards[0].card.card_type == "narrative_scene"
    assert result.raw_read_recommendations[0]["card_type"] == "narrative_scene"


def test_narrative_index_facade_searches_memory_world_and_creative_cards(tmp_path: Path) -> None:
    db = NovelAgentDB(tmp_path / "index.db")
    with db.connect() as conn:
        db.init_schema(conn)
        init_creative_kb_schema(conn)
        _insert_documents(conn)
        _upsert_chapter(conn)
        FragmentCardsRepo().upsert_cards(conn, [_fragment_card()])
        world_summary_path = tmp_path / "world_summary.md"
        world_summary_path.write_text("世界存在龙族血统与学院筛选机制。", encoding="utf-8")
        AssetsRepo().upsert(
            conn,
            {
                "book_id": "book-1",
                "source_root": str(tmp_path),
                "world_markdown_path": str(tmp_path / "world.md"),
                "world_summary_path": str(world_summary_path),
                "outline_markdown_path": str(tmp_path / "outline.md"),
                "created_at": "2026-01-01T00:00:00Z",
                "updated_at": "2026-01-01T00:00:00Z",
            },
        )
        conn.commit()

        facade = NarrativeIndexFacade(repo_root=tmp_path)
        result = facade.search_cards(
            conn,
            book_id="book-1",
            intent=IndexQueryIntent(
                original_query="路明非为什么被卡塞尔学院邀请，龙族血统规则是什么？",
                consumer="analyzer",
                target_card_types=["factual_event", "world_concept"],
                query_facets=["血统规则", "学院"],
                must_include_characters=["路明非"],
            ),
            budget=IndexQueryBudget(max_candidate_cards=8),
        )

    card_types = {hit.card.card_type for hit in result.candidate_cards}
    assert "factual_event" in card_types
    assert "world_concept" in card_types
    assert any(hit.card.card_id.startswith("chapter-summary:") for hit in result.candidate_cards)
    factual_hits = [hit.card for hit in result.candidate_cards if hit.card.card_type == "factual_event"]
    assert factual_hits[0].outline_segment_ids == ["outline-segment:chapter-1:docs-1-2"]
    assert factual_hits[0].payload["summary_source"] == "outline_segment"
    assert any(hit.card.payload.get("kind") == "rule" for hit in result.candidate_cards)


def test_narrative_inquiry_broker_resolves_index_card_search(tmp_path: Path) -> None:
    db = NovelAgentDB(tmp_path / "broker-index.db")
    with db.connect() as conn:
        db.init_schema(conn)
        init_creative_kb_schema(conn)
        _insert_documents(conn)
        _upsert_chapter(conn)
        conn.commit()

        broker = NarrativeInquiryBroker(repo_root=tmp_path)
        request = NarrativeInquiryRequest(
            request_id="req-index",
            request_type="factual_event_card_search",
            query="路明非收到学院邀请",
            purpose="定位主线入口",
            priority="high",
        )
        bundle = broker.resolve_one(
            conn,
            book_id="book-1",
            request=request,
            budget=AnalyzerBudget(max_evidence_chars_per_request=500),
        )

    assert bundle.status == "found"
    assert bundle.evidence_items
    assert bundle.evidence_items[0]["card_type"] == "factual_event"
    assert bundle.source_doc_ids == [1, 2]


def test_narrative_inquiry_broker_resolves_narrative_scene_card_search(tmp_path: Path) -> None:
    db = NovelAgentDB(tmp_path / "broker-scene-index.db")
    with db.connect() as conn:
        db.init_schema(conn)
        init_creative_kb_schema(conn)
        _insert_documents(conn)
        _upsert_chapter(conn)
        NarrativeSceneIndexerService(repo_root=tmp_path, window_chars_budget=1000).build_scene_cards(
            conn,
            book_id="book-1",
            model_client=FakeSceneModelClient(),
            persist=True,
        )
        conn.commit()

        broker = NarrativeInquiryBroker(repo_root=tmp_path)
        request = NarrativeInquiryRequest(
            request_id="req-scene-index",
            request_type="narrative_scene_card_search",
            query="路明非收到卡塞尔邀请后的主线转折",
            purpose="定位关键场景",
            priority="high",
        )
        bundle = broker.resolve_one(
            conn,
            book_id="book-1",
            request=request,
            budget=AnalyzerBudget(max_evidence_chars_per_request=500),
        )

    assert bundle.status == "found"
    assert bundle.evidence_items
    assert bundle.evidence_items[0]["card_type"] == "narrative_scene"
    assert bundle.source_doc_ids == [1, 2]

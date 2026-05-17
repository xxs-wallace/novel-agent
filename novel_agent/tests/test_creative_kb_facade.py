from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

from novel_agent.app.repos.creative_kb_storage import init_creative_kb_schema
from novel_agent.app.repos.db import NovelAgentDB
from novel_agent.app.repos.documents_repo import DocumentRow, DocumentsRepo
from novel_agent.app.repos.fragment_cards_repo import FragmentCardsRepo
from novel_agent.app.repos.semantic_aliases_repo import SemanticAliasesRepo
from novel_agent.app.schemas.creative_kb_schema import FragmentCard, StyleFeatures
from novel_agent.app.services.creative_kb_facade import CreativeKnowledgeBaseFacade
from novel_agent.app.services.fragment_card_builder_service import FragmentCardBuilderService
from novel_agent.app.services.semantic_alias_extractor_service import SemanticAliasExtractorService


class _FakeModelClient:
    def __init__(self, responses: list[tuple[dict[str, object] | list[object], str] | Exception]) -> None:
        self._responses = list(responses)
        self.settings = SimpleNamespace(dry_run=False)

    def generate_json(self, **_: object) -> tuple[dict[str, object] | list[object], str]:
        if not self._responses:
            raise RuntimeError("No fake response configured")
        response = self._responses.pop(0)
        if isinstance(response, Exception):
            raise response
        return response


def _document(
    *,
    doc_id: int,
    content: str,
    content_tags: list[str],
    document_title: str = "第十章",
) -> DocumentRow:
    return DocumentRow(
        doc_id=doc_id,
        book_id="book-1",
        path="/tmp/source.md",
        scope="chapter",
        title=None,
        document_title=document_title,
        document_title_index=10,
        inferred_chapter_no=10,
        content=content,
        content_chars=len(content),
        character_keywords=[],
        content_tags=content_tags,
        source_path="/tmp/source.md",
        source_file_name="source.md",
        source_start_offset=0,
        source_end_offset=len(content),
    )


def _valid_payload() -> dict[str, object]:
    return {
        "content_summary": "雨夜里的克制型告别停顿。",
        "narrative_function": ["收束"],
        "narrative_function_text": "通过停顿收束当前冲突。",
        "scene_space_tags": ["雨夜"],
        "event_tags": ["告别"],
        "emotion_tags": ["克制", "悲伤"],
        "emotion_mechanism_text": "通过沉默和动作压住悲伤。",
        "expression_mode_tags": ["动作描写"],
        "preferred_tags": ["雨天", "告别"],
        "pov_mode": "近距离第三人称",
        "character_focus": ["林清"],
        "character_temperament": ["克制"],
        "character_relation_text": "关系仍未和解。",
        "relationship_state": ["未和解"],
        "continuity_phase": "承接推进",
        "style_features": {
            "sentence_rhythm": "短句偏多",
            "dialogue_density": "低",
            "interiority_density": "高",
            "imagery_density": "中",
        },
        "style_profile_text": "短句、低对白、高内心密度。",
        "transferability_score": 0.8,
        "context_dependency_level": "medium",
    }


def _existing_card(doc_id: str) -> FragmentCard:
    return FragmentCard(
        fragment_id=f"fragment-{doc_id}-existing",
        doc_id=doc_id,
        document_title="第十章",
        document_title_index="10",
        source_path="/tmp/source.md",
        source_offsets=(0, 32),
        source_excerpt="已存在的卡片节选。",
        content_summary="已存在的知识库卡片。",
        narrative_function=["信息揭示"],
        narrative_function_text="已有卡片用于跳过重复建卡。",
        scene_space_tags=["城市街道"],
        event_tags=["调查"],
        emotion_tags=["紧张压迫"],
        emotion_mechanism_text="通过动作和环境维持压迫感。",
        expression_mode_tags=["动作描写"],
        preferred_tags=["城市街道", "调查"],
        pov_mode="近距离第三人称",
        character_focus=["旁白"],
        character_temperament=["谨慎"],
        character_relation_text="关系无关。",
        relationship_state=[],
        continuity_phase="承接推进",
        style_features=StyleFeatures(
            sentence_rhythm="中",
            dialogue_density="低",
            interiority_density="中",
            imagery_density="低",
        ),
        style_profile_text="现有卡片。",
        transferability_score=0.6,
        context_dependency_level="low",
    )


def test_creative_kb_facade_builds_clusters_and_reports_failed_and_skipped_docs(tmp_path: Path) -> None:
    db = NovelAgentDB(tmp_path / "creative_kb_facade.db")
    cards_repo = FragmentCardsRepo()
    model_client = _FakeModelClient(
        [
            (_valid_payload(), "{}"),
            (dict(_valid_payload(), content_summary=None), "{}"),
            (dict(_valid_payload(), content_summary=None), "{}"),
            (dict(_valid_payload(), content_summary=None), "{}"),
            (_valid_payload(), "{}"),
            (_valid_payload(), "{}"),
            (_valid_payload(), "{}"),
        ]
    )
    builder = FragmentCardBuilderService(
        model_client=model_client,  # type: ignore[arg-type]
        fragment_cards_repo=cards_repo,
    )
    facade = CreativeKnowledgeBaseFacade(
        fragment_card_builder_service=builder,
        fragment_cards_repo=cards_repo,
    )
    documents = [
        _document(doc_id=1, content="雨夜里她没有立刻说出告别。", content_tags=["雨天", "告别"]),
        _document(doc_id=2, content="医院走廊里她只是把病历重新整理了一遍。", content_tags=["医院", "悲伤低落"]),
        _document(doc_id=3, content="这段内容会因为非法标签而失败。", content_tags=["不在词典里的标签"]),
        _document(doc_id=4, content="这个 document 已经有现成卡片。", content_tags=["城市街道", "调查"]),
        _document(doc_id=5, content="   ", content_tags=["雨天"]),
    ]

    with db.connect() as conn:
        db.init_schema(conn)
        init_creative_kb_schema(conn)
        cards_repo.upsert_cards(conn, [_existing_card("4")])
        conn.commit()

        result = facade.build_creative_kb(conn, documents=documents)
        conn.commit()

        doc1_cards = cards_repo.list_by_doc_id(conn, doc_id="1")
        doc2_cards = cards_repo.list_by_doc_id(conn, doc_id="2")
        doc3_cards = cards_repo.list_by_doc_id(conn, doc_id="3")
        doc4_cards = cards_repo.list_by_doc_id(conn, doc_id="4")

    assert result.built_fragment_count == 1
    assert result.built_cluster_count == 2
    assert result.representative_count == 2
    assert result.failed_doc_ids == ["2", "3"]
    assert result.skipped_doc_ids == ["4", "5"]
    assert len(result.fragment_ids) == 1
    assert len(result.cluster_ids) == 2
    assert any("fragment_card build failed for doc_id=2" == warning for warning in result.warnings)
    assert any("fragment_card build failed for doc_id=3" == warning for warning in result.warnings)
    assert any("skipped existing or empty documents: 4, 5" == warning for warning in result.warnings)
    assert len(doc1_cards) == 1
    assert doc2_cards == []
    assert doc3_cards == []
    assert len(doc4_cards) == 1
    assert doc1_cards[0].is_cluster_representative is True
    assert doc4_cards[0].cluster_id
    assert doc4_cards[0].is_cluster_representative is True


def test_creative_kb_facade_returns_warning_when_no_documents_are_buildable(tmp_path: Path) -> None:
    db = NovelAgentDB(tmp_path / "creative_kb_facade_noop.db")
    cards_repo = FragmentCardsRepo()
    builder = FragmentCardBuilderService(
        model_client=_FakeModelClient([(_valid_payload(), "{}")]),  # type: ignore[arg-type]
        fragment_cards_repo=cards_repo,
    )
    facade = CreativeKnowledgeBaseFacade(
        fragment_card_builder_service=builder,
        fragment_cards_repo=cards_repo,
    )

    with db.connect() as conn:
        db.init_schema(conn)
        init_creative_kb_schema(conn)
        result = facade.build_creative_kb(
            conn,
            documents=[_document(doc_id=9, content="   ", content_tags=["雨天"])],
        )

    assert result.built_fragment_count == 0
    assert result.failed_doc_ids == []
    assert result.skipped_doc_ids == ["9"]
    assert result.warnings == ["no buildable documents for creative kb"]


def test_creative_kb_facade_commits_and_reports_progress_by_document_batches(tmp_path: Path) -> None:
    db = NovelAgentDB(tmp_path / "creative_kb_facade_progress.db")
    cards_repo = FragmentCardsRepo()
    builder = FragmentCardBuilderService(
        model_client=_FakeModelClient(
            [
                (_valid_payload(), "{}"),
                (_valid_payload(), "{}"),
                (_valid_payload(), "{}"),
            ]
        ),  # type: ignore[arg-type]
        fragment_cards_repo=cards_repo,
    )
    facade = CreativeKnowledgeBaseFacade(
        fragment_card_builder_service=builder,
        fragment_cards_repo=cards_repo,
    )
    progress_events: list[dict[str, object]] = []

    with db.connect() as conn:
        db.init_schema(conn)
        init_creative_kb_schema(conn)
        result = facade.build_creative_kb(
            conn,
            documents=[
                _document(doc_id=1, content="雨声压低了两人的对白。", content_tags=["雨天", "人物对话"]),
                _document(doc_id=2, content="街口的灯光让告别显得更迟。", content_tags=["城市街道", "告别"]),
                _document(doc_id=3, content="她把线索重新整理成一页纸。", content_tags=["调查"]),
            ],
            commit_batch_size=2,
            progress_callback=progress_events.append,
        )
        stored_cards = cards_repo.list_by_doc_ids(conn, doc_ids=["1", "2", "3"])

    assert result.built_fragment_count == 3
    assert len(stored_cards) == 3
    assert [event["phase"] for event in progress_events] == [
        "fragment_cards_batch_start",
        "fragment_card_document_start",
        "fragment_card_document_done",
        "fragment_card_document_start",
        "fragment_card_document_done",
        "fragment_cards",
        "fragment_cards_batch_start",
        "fragment_card_document_start",
        "fragment_card_document_done",
        "fragment_cards",
        "creative_kb_complete",
    ]
    assert progress_events[0]["batch_document_count"] == 2
    assert progress_events[5]["attempted_docs"] == 2
    assert progress_events[5]["remaining_docs"] == 1
    assert progress_events[9]["attempted_docs"] == 3
    assert progress_events[-1]["cluster_count"] == result.built_cluster_count


def test_creative_kb_dedup_does_not_modify_shared_documents_baseline(tmp_path: Path) -> None:
    db = NovelAgentDB(tmp_path / "creative_kb_documents_baseline.db")
    documents_repo = DocumentsRepo()
    cards_repo = FragmentCardsRepo()
    builder = FragmentCardBuilderService(
        model_client=_FakeModelClient(
            [
                (_valid_payload(), "{}"),
                (_valid_payload(), "{}"),
            ]
        ),  # type: ignore[arg-type]
        fragment_cards_repo=cards_repo,
    )
    facade = CreativeKnowledgeBaseFacade(
        fragment_card_builder_service=builder,
        fragment_cards_repo=cards_repo,
    )

    with db.connect() as conn:
        db.init_schema(conn)
        init_creative_kb_schema(conn)
        doc_id_1 = documents_repo.insert_document(
            conn,
            {
                "book_id": "book-1",
                "path": "/tmp/source.md",
                "scope": "chapter",
                "content": "雨夜里她把想说的话压回喉咙，只剩沉默。",
                "source_path": "/tmp/source.md",
                "source_file_name": "source.md",
                "source_start_offset": 0,
                "source_end_offset": 24,
                "document_title": "第十章",
                "document_title_index": 10,
                "content_tags": ["雨天", "告别"],
            },
        )
        doc_id_2 = documents_repo.insert_document(
            conn,
            {
                "book_id": "book-1",
                "path": "/tmp/source.md",
                "scope": "chapter",
                "content": "同样的雨夜停顿再次出现，她还是没有把告别说满。",
                "source_path": "/tmp/source.md",
                "source_file_name": "source.md",
                "source_start_offset": 25,
                "source_end_offset": 50,
                "document_title": "第十章",
                "document_title_index": 10,
                "content_tags": ["雨天", "告别"],
            },
        )
        conn.commit()

        before_documents = documents_repo.fetch_after_doc_id(conn, book_id="book-1")
        before_count = documents_repo.count_by_book(conn, book_id="book-1")

        result = facade.build_creative_kb(conn, documents=before_documents)
        conn.commit()

        after_documents = documents_repo.fetch_after_doc_id(conn, book_id="book-1")
        after_count = documents_repo.count_by_book(conn, book_id="book-1")

    assert result.built_fragment_count == 2
    assert result.built_cluster_count == 1
    assert before_count == 2
    assert after_count == 2
    assert [document.doc_id for document in before_documents] == [doc_id_1, doc_id_2]
    assert [document.doc_id for document in after_documents] == [doc_id_1, doc_id_2]
    assert [document.content for document in after_documents] == [document.content for document in before_documents]


def test_semantic_alias_extractor_samples_edges_and_middle_and_persists(tmp_path: Path) -> None:
    db = NovelAgentDB(tmp_path / "semantic_aliases.db")
    documents = [
        _document(doc_id=doc_id, content=f"第 {doc_id} 段里，两名角色通过暗号推进任务。", content_tags=["人物对话"])
        for doc_id in range(1, 21)
    ]
    model_client = _FakeModelClient(
        [
            (
                {
                    "aliases": [
                        {
                            "canonical_key": "密令",
                            "aliases": ["暗号", "口令"],
                            "category": "requirement_coverage",
                            "confidence": 0.9,
                            "evidence_doc_ids": ["1", "20"],
                        }
                    ]
                },
                "{}",
            )
        ]
    )
    extractor = SemanticAliasExtractorService(
        model_client=model_client,  # type: ignore[arg-type]
        edge_document_count=2,
        middle_sample_ratio=0.05,
    )
    repo = SemanticAliasesRepo()

    with db.connect() as conn:
        db.init_schema(conn)
        init_creative_kb_schema(conn)
        result = extractor.extract_aliases(book_id="book-1", documents=documents)
        changed = repo.upsert_aliases(conn, result.aliases)
        stored_aliases = repo.list_by_book(conn, book_id="book-1")

    assert result.sampled_doc_ids[:2] == ["1", "2"]
    assert result.sampled_doc_ids[-2:] == ["19", "20"]
    assert len(result.sampled_doc_ids) == 5
    assert changed == 1
    assert stored_aliases[0].canonical_key == "密令"
    assert stored_aliases[0].aliases == ["暗号", "口令"]

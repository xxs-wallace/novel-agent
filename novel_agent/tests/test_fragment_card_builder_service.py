from __future__ import annotations

import sqlite3
from pathlib import Path
from types import SimpleNamespace

import pytest

from novel_agent.app.repos.creative_kb_storage import init_creative_kb_schema
from novel_agent.app.repos.db import NovelAgentDB
from novel_agent.app.repos.documents_repo import DocumentRow
from novel_agent.app.repos.fragment_cards_repo import FragmentCardsRepo
from novel_agent.app.services.fragment_card_builder_service import (
    FragmentCardBuildError,
    FragmentCardBuilderService,
)


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


def _document(*, doc_id: int = 1, content_tags: list[str] | None = None) -> DocumentRow:
    return DocumentRow(
        doc_id=doc_id,
        book_id="book-1",
        path="/tmp/source.md",
        scope="chapter",
        title=None,
        document_title="第十章",
        document_title_index=10,
        inferred_chapter_no=10,
        content="雨夜里她没有立刻说出告别。",
        content_chars=14,
        character_keywords=[],
        content_tags=content_tags or ["雨天", "告别"],
        source_path="/tmp/source.md",
        source_file_name="source.md",
        source_start_offset=0,
        source_end_offset=14,
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


def _service_with_responses(
    responses: list[tuple[dict[str, object] | list[object], str] | Exception],
) -> FragmentCardBuilderService:
    return FragmentCardBuilderService(
        model_client=_FakeModelClient(responses),  # type: ignore[arg-type]
        fragment_cards_repo=FragmentCardsRepo(),
    )


def test_build_card_result_success() -> None:
    service = _service_with_responses([(_valid_payload(), "{}")])

    result = service.build_card_result(_document())

    assert result.status == "success"
    assert result.fragment_card is not None
    assert result.retry_count == 0
    assert result.used_fallback is False
    assert result.fragment_card.preferred_tags == ["雨天", "告别"]


def test_build_card_result_marks_failed_after_schema_retries() -> None:
    invalid_payload = _valid_payload()
    invalid_payload.pop("content_summary")
    service = _service_with_responses([(invalid_payload, "{}"), (invalid_payload, "{}"), (invalid_payload, "{}")])

    result = service.build_card_result(_document())

    assert result.status == "failed"
    assert result.fragment_card is None
    assert result.used_fallback is False
    assert result.retry_count == 2
    assert result.failure_stage == "schema_validate"
    assert "content_summary" in result.failure_reason
    assert result.warnings == ["fragment_card build failed for doc_id=1"]


def test_build_card_result_marks_failed_when_validation_never_succeeds() -> None:
    service = _service_with_responses([(_valid_payload(), "{}")] * 3)
    document = _document(content_tags=["不在词典里的标签"])

    result = service.build_card_result(document)

    assert result.status == "failed"
    assert result.fragment_card is None
    assert "不在词典里的标签" in result.failure_reason
    assert result.warnings == ["fragment_card build failed for doc_id=1"]


def test_build_cards_keeps_legacy_raise_behavior_for_failed_results() -> None:
    service = _service_with_responses([ValueError("json parse failed")] * 3)

    with pytest.raises(FragmentCardBuildError, match="Failed to build fragment cards for doc_ids: 1"):
        service.build_cards([_document(content_tags=["不在词典里的标签"])])


def test_build_and_persist_only_upserts_successful_cards(tmp_path: Path) -> None:
    db = NovelAgentDB(tmp_path / "fragment_cards.db")
    service = _service_with_responses(
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
    documents = [
        _document(doc_id=1),
        _document(doc_id=2),
        _document(doc_id=3, content_tags=["不在词典里的标签"]),
    ]

    with db.connect() as conn:
        db.init_schema(conn)
        init_creative_kb_schema(conn)

        results, stats = service.build_and_persist(conn, documents=documents)
        conn.commit()

        stored_cards = FragmentCardsRepo().list_by_doc_id(conn, doc_id="1") + FragmentCardsRepo().list_by_doc_id(
            conn, doc_id="2"
        )
        failed_cards = FragmentCardsRepo().list_by_doc_id(conn, doc_id="3")

    assert len(results) == 3
    assert [result.status for result in results] == ["success", "failed", "failed"]
    assert stats.attempted_documents == 3
    assert stats.built_cards == 1
    assert len(stored_cards) == 1
    assert failed_cards == []

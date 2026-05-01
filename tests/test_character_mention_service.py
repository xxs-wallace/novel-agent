from __future__ import annotations

from dataclasses import dataclass

from novel_agent.app.services.character_mention_service import CharacterMentionService


@dataclass
class DummyDocument:
    doc_id: int
    content: str


def test_extract_document_mentions_prefers_real_character_names() -> None:
    service = CharacterMentionService()

    mentions = service.extract_document_mentions(
        [
            DummyDocument(
                doc_id=1,
                content="路明非站在雨里。楚子航看了他一眼，路明非没有说话。",
            ),
            DummyDocument(
                doc_id=2,
                content="这段只有场景描写，没有明确人物，只剩下雨声和空房间。",
            ),
        ]
    )

    assert mentions[1] == ["路明非", "楚子航"]
    assert mentions[2] == []


def test_clean_names_filters_non_character_noise() -> None:
    service = CharacterMentionService()

    cleaned = service.clean_names(["时候", "路明非", "白帝城", "楚子航", "通知"])

    assert cleaned == ["路明非", "楚子航"]

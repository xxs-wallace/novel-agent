from __future__ import annotations

from novel_agent.app.services.character_mention_service import CharacterMentionService


def test_clean_names_only_normalizes_explicit_structured_names() -> None:
    service = CharacterMentionService()

    cleaned = service.clean_names(["时候", "路明非", " ", "路明非", "通知"])

    assert cleaned == ["时候", "路明非", "通知"]

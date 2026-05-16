from __future__ import annotations

from collections.abc import Sequence


CHARACTER_NAME_STOPWORDS: set[str] = set()


class CharacterMentionService:
    def __init__(self) -> None:
        pass

    def clean_names(self, items: Sequence[object]) -> list[str]:
        cleaned: list[str] = []
        seen: set[str] = set()
        for item in items:
            keyword = str(item).strip()
            if not keyword:
                continue
            if keyword in seen:
                continue
            seen.add(keyword)
            cleaned.append(keyword)
        return cleaned

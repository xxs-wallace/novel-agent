from __future__ import annotations

import json
import sqlite3
from typing import Any

from ..repos.character_profiles_repo import CharacterProfilesRepo


DEFAULT_CHARACTER_ROSTER_LIMIT = 10_000


class CharacterRosterService:
    def __init__(self, *, profiles_repo: CharacterProfilesRepo, max_names: int = DEFAULT_CHARACTER_ROSTER_LIMIT) -> None:
        self.profiles_repo = profiles_repo
        self.max_names = max(1, int(max_names))

    def load_recent_roster(
        self,
        conn: sqlite3.Connection,
        *,
        book_id: str,
        max_names: int | None = None,
    ) -> list[dict[str, Any]]:
        limit = self.max_names if max_names is None else max(1, int(max_names))
        rows = self.profiles_repo.list_by_book(conn, book_id=book_id)
        sorted_rows = sorted(rows, key=self._recency_sort_key)
        return [self._compact_profile(row) for row in sorted_rows[:limit]]

    def _compact_profile(self, row: sqlite3.Row) -> dict[str, Any]:
        return {
            "character_id": str(row["character_id"]),
            "canonical_name": str(row["canonical_name"] or "").strip(),
            "aliases": self._load_json_list(row, "aliases_json")[:8],
            "age_labels": self._age_labels(row)[:3],
            "gender": "",
            "occupations": self._attribute_values(row, "occupations_json")[:3],
            "speaking_character_status": str(row["speaking_character_status"] or "unknown"),
            "last_seen_doc_id": row["last_seen_doc_id"],
            "last_seen_title_index": row["last_seen_title_index"],
        }

    def _age_labels(self, row: sqlite3.Row) -> list[str]:
        labels: list[str] = []
        for item in self._load_json_list(row, "age_timeline_json"):
            if not isinstance(item, dict):
                continue
            label = str(item.get("label") or "").strip()
            if label and label not in labels:
                labels.append(label)
        return labels

    def _attribute_values(self, row: sqlite3.Row, field_name: str) -> list[str]:
        values: list[str] = []
        for item in self._load_json_list(row, field_name):
            if isinstance(item, dict):
                value = str(item.get("value") or "").strip()
            else:
                value = str(item or "").strip()
            if value and value not in values:
                values.append(value)
        return values

    def _load_json_list(self, row: sqlite3.Row, field_name: str) -> list[Any]:
        raw = row[field_name]
        if not raw:
            return []
        try:
            loaded = json.loads(raw)
        except json.JSONDecodeError:
            return []
        return loaded if isinstance(loaded, list) else []

    @staticmethod
    def _recency_sort_key(row: sqlite3.Row) -> tuple[int, int, str]:
        last_seen_doc_id = row["last_seen_doc_id"]
        last_seen_title_index = row["last_seen_title_index"]
        return (
            -(int(last_seen_doc_id) if last_seen_doc_id is not None else -1),
            -(int(last_seen_title_index) if last_seen_title_index is not None else -1),
            str(row["canonical_name"] or ""),
        )

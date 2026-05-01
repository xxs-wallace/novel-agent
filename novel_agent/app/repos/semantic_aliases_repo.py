from __future__ import annotations

import hashlib
import json
import sqlite3
from datetime import datetime, timezone
from typing import Any

from ..schemas.creative_kb_schema import SemanticAlias


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


class SemanticAliasesRepo:
    def upsert_aliases(self, conn: sqlite3.Connection, aliases: list[SemanticAlias]) -> int:
        changed = 0
        now = _utc_now()
        for alias in aliases:
            alias_id = self._alias_id(alias)
            conn.execute(
                """
                INSERT INTO semantic_aliases(
                    alias_id, book_id, canonical_key, aliases_json, category, source,
                    evidence_doc_ids_json, confidence, extraction_run_id, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(book_id, canonical_key, category, source) DO UPDATE SET
                    aliases_json = excluded.aliases_json,
                    evidence_doc_ids_json = excluded.evidence_doc_ids_json,
                    confidence = excluded.confidence,
                    extraction_run_id = excluded.extraction_run_id,
                    updated_at = excluded.updated_at
                """,
                (
                    alias_id,
                    alias.book_id,
                    alias.canonical_key,
                    json.dumps(alias.aliases, ensure_ascii=False),
                    alias.category,
                    alias.source,
                    json.dumps(alias.evidence_doc_ids, ensure_ascii=False),
                    alias.confidence,
                    alias.extraction_run_id,
                    now,
                    now,
                ),
            )
            changed += 1
        return changed

    def list_by_book(
        self,
        conn: sqlite3.Connection,
        *,
        book_id: str,
        category: str = "requirement_coverage",
    ) -> list[SemanticAlias]:
        rows = conn.execute(
            """
            SELECT * FROM semantic_aliases
            WHERE book_id = ? AND category = ?
            ORDER BY canonical_key, source
            """,
            (book_id, category),
        ).fetchall()
        return [self._row_to_alias(row) for row in rows]

    def _row_to_alias(self, row: sqlite3.Row) -> SemanticAlias:
        return SemanticAlias(
            book_id=str(row["book_id"]),
            canonical_key=str(row["canonical_key"]),
            aliases=self._json_list(row["aliases_json"]),
            category=str(row["category"]),
            source=str(row["source"]),
            evidence_doc_ids=self._json_list(row["evidence_doc_ids_json"]),
            confidence=float(row["confidence"]),
            extraction_run_id=str(row["extraction_run_id"] or ""),
        )

    def _json_list(self, value: Any) -> list[str]:
        if not isinstance(value, str) or not value.strip():
            return []
        try:
            payload = json.loads(value)
        except json.JSONDecodeError:
            return []
        if not isinstance(payload, list):
            return []
        return [str(item).strip() for item in payload if str(item).strip()]

    def _alias_id(self, alias: SemanticAlias) -> str:
        digest = hashlib.sha1(
            f"{alias.book_id}:{alias.category}:{alias.source}:{alias.canonical_key}".encode("utf-8")
        ).hexdigest()[:16]
        return f"alias-{digest}"

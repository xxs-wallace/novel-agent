from __future__ import annotations

import json
import sqlite3
from typing import Any

from ..schemas.narrative_memory_schema import NarrativeMemoryPage


class NarrativeMemoryPagesRepo:
    def upsert(self, conn: sqlite3.Connection, *, book_id: str, page: NarrativeMemoryPage) -> None:
        conn.execute(
            """
            INSERT INTO narrative_memory_pages(
                page_id, book_id, page_type, summary, child_refs_json,
                source_doc_ids_json, source_doc_range, status, metadata_json, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(page_id) DO UPDATE SET
                book_id = excluded.book_id,
                page_type = excluded.page_type,
                summary = excluded.summary,
                child_refs_json = excluded.child_refs_json,
                source_doc_ids_json = excluded.source_doc_ids_json,
                source_doc_range = excluded.source_doc_range,
                status = excluded.status,
                metadata_json = excluded.metadata_json,
                updated_at = excluded.updated_at
            """,
            (
                page.page_id,
                book_id,
                page.page_type,
                page.summary,
                json.dumps(page.child_refs, ensure_ascii=False),
                json.dumps(page.source_doc_ids, ensure_ascii=False),
                page.source_doc_range,
                page.status,
                json.dumps(page.metadata, ensure_ascii=False),
                page.updated_at,
            ),
        )

    def list_by_book(
        self,
        conn: sqlite3.Connection,
        *,
        book_id: str,
        page_type: str | None = None,
    ) -> list[NarrativeMemoryPage]:
        if page_type:
            rows = conn.execute(
                """
                SELECT * FROM narrative_memory_pages
                WHERE book_id = ? AND page_type = ?
                ORDER BY page_id
                """,
                (book_id, page_type),
            ).fetchall()
        else:
            rows = conn.execute(
                """
                SELECT * FROM narrative_memory_pages
                WHERE book_id = ?
                ORDER BY page_type, page_id
                """,
                (book_id,),
            ).fetchall()
        return [self._row_to_page(row) for row in rows]

    def get(self, conn: sqlite3.Connection, *, page_id: str) -> NarrativeMemoryPage | None:
        row = conn.execute("SELECT * FROM narrative_memory_pages WHERE page_id = ?", (page_id,)).fetchone()
        return self._row_to_page(row) if row is not None else None

    def clear_book(self, conn: sqlite3.Connection, *, book_id: str) -> None:
        conn.execute("DELETE FROM narrative_memory_pages WHERE book_id = ?", (book_id,))

    def _row_to_page(self, row: sqlite3.Row) -> NarrativeMemoryPage:
        return NarrativeMemoryPage(
            page_id=str(row["page_id"]),
            page_type=str(row["page_type"]),
            summary=str(row["summary"] or ""),
            child_refs=self._json_list(row["child_refs_json"]),
            source_doc_ids=[int(item) for item in self._json_list(row["source_doc_ids_json"]) if str(item).isdigit()],
            source_doc_range=str(row["source_doc_range"] or ""),
            status=str(row["status"] or "provisional"),
            updated_at=str(row["updated_at"] or ""),
            metadata=self._json_dict(row["metadata_json"]),
        )

    def _json_list(self, raw: object) -> list[Any]:
        try:
            payload = json.loads(str(raw or "[]"))
        except json.JSONDecodeError:
            return []
        return payload if isinstance(payload, list) else []

    def _json_dict(self, raw: object) -> dict[str, Any]:
        try:
            payload = json.loads(str(raw or "{}"))
        except json.JSONDecodeError:
            return {}
        return dict(payload) if isinstance(payload, dict) else {}

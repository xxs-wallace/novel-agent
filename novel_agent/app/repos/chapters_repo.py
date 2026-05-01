from __future__ import annotations

import json
import sqlite3
from typing import Any


class ChaptersRepo:
    def get(self, conn: sqlite3.Connection, *, book_id: str, document_title_index: int) -> sqlite3.Row | None:
        return conn.execute(
            'SELECT * FROM chapters WHERE book_id = ? AND document_title_index = ?',
            (book_id, document_title_index),
        ).fetchone()

    def upsert(self, conn: sqlite3.Connection, payload: dict[str, Any]) -> int:
        normalized_summary_intermediate = self._normalize_summary_intermediate(payload.get('summary_intermediate', []))
        normalized_summary_md = str(payload.get('summary_md', '') or '').strip()
        normalized_summary_short = str(payload.get('summary_short', '') or '').strip()
        normalized_related_chapters = self._normalize_related_chapters(payload.get('related_chapters', []))
        normalized_mentioned_characters = self._normalize_string_list(payload.get('mentioned_characters', []))
        existing = self.get(conn, book_id=payload['book_id'], document_title_index=int(payload['document_title_index']))
        params = (
            payload['chapter_title'],
            int(payload['source_doc_start_id']),
            int(payload['source_doc_end_id']),
            int(payload['source_doc_count']),
            int(payload['source_total_chars']),
            json.dumps(normalized_summary_intermediate, ensure_ascii=False),
            normalized_summary_md,
            normalized_summary_short,
            int(payload.get('importance_score', 0)),
            payload.get('importance_reason'),
            json.dumps(normalized_related_chapters, ensure_ascii=False),
            json.dumps(normalized_mentioned_characters, ensure_ascii=False),
            json.dumps(payload.get('world_update', {}), ensure_ascii=False),
            json.dumps(payload.get('outline_update', {}), ensure_ascii=False),
            payload.get('close_read_run_id', ''),
            payload['updated_at'],
        )
        if existing:
            conn.execute(
                '''
                UPDATE chapters SET
                    chapter_title = ?, source_doc_start_id = ?, source_doc_end_id = ?,
                    source_doc_count = ?, source_total_chars = ?, summary_intermediate_json = ?,
                    summary_md = ?, summary_short = ?, importance_score = ?, importance_reason = ?,
                    related_chapters_json = ?, mentioned_characters_json = ?, world_update_json = ?,
                    outline_update_json = ?, close_read_run_id = ?, updated_at = ?
                WHERE book_id = ? AND document_title_index = ?
                ''',
                params + (payload['book_id'], int(payload['document_title_index'])),
            )
            row = self.get(conn, book_id=payload['book_id'], document_title_index=int(payload['document_title_index']))
            if row is None:
                raise RuntimeError('Failed to reload chapter row after update')
            return int(row['chapter_id'])
        cur = conn.execute(
            '''
            INSERT INTO chapters(
                book_id, document_title_index, chapter_title, source_doc_start_id,
                source_doc_end_id, source_doc_count, source_total_chars, summary_intermediate_json,
                summary_md, summary_short, importance_score, importance_reason,
                related_chapters_json, mentioned_characters_json, world_update_json,
                outline_update_json, close_read_run_id, created_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ''',
            (
                payload['book_id'],
                int(payload['document_title_index']),
                payload['chapter_title'],
                int(payload['source_doc_start_id']),
                int(payload['source_doc_end_id']),
                int(payload['source_doc_count']),
                int(payload['source_total_chars']),
                json.dumps(normalized_summary_intermediate, ensure_ascii=False),
                normalized_summary_md,
                normalized_summary_short,
                int(payload.get('importance_score', 0)),
                payload.get('importance_reason'),
                json.dumps(normalized_related_chapters, ensure_ascii=False),
                json.dumps(normalized_mentioned_characters, ensure_ascii=False),
                json.dumps(payload.get('world_update', {}), ensure_ascii=False),
                json.dumps(payload.get('outline_update', {}), ensure_ascii=False),
                payload.get('close_read_run_id', ''),
                payload['created_at'],
                payload['updated_at'],
            ),
        )
        if cur.lastrowid is None:
            raise RuntimeError('Failed to insert chapter row')
        return int(cur.lastrowid)

    def list_by_book(self, conn: sqlite3.Connection, *, book_id: str) -> list[sqlite3.Row]:
        return conn.execute('SELECT * FROM chapters WHERE book_id = ? ORDER BY document_title_index', (book_id,)).fetchall()

    def _normalize_summary_intermediate(self, value: object) -> list[str]:
        if not isinstance(value, list):
            return []
        cleaned: list[str] = []
        for item in value:
            text = str(item or '').strip()
            if text:
                cleaned.append(text)
        return cleaned

    def _normalize_related_chapters(self, value: object) -> list[dict[str, Any]]:
        if not isinstance(value, list):
            return []
        merged: dict[int, dict[str, Any]] = {}
        for item in value:
            if not isinstance(item, dict):
                continue
            raw_index = item.get('document_title_index')
            if raw_index is None:
                continue
            try:
                title_index = int(str(raw_index))
            except (TypeError, ValueError):
                continue
            score = max(0, min(int(item.get('score', 0) or 0), 100))
            reason = str(item.get('reason', '') or '').strip()
            previous = merged.get(title_index)
            if previous is None or score >= int(previous.get('score', 0)):
                merged[title_index] = {
                    'document_title_index': title_index,
                    'score': score,
                    'reason': reason,
                }
        return [merged[index] for index in sorted(merged)]

    def _normalize_string_list(self, value: object) -> list[str]:
        if not isinstance(value, list):
            return []
        cleaned: list[str] = []
        seen: set[str] = set()
        for item in value:
            text = str(item or '').strip()
            if not text or text in seen:
                continue
            seen.add(text)
            cleaned.append(text)
        return cleaned

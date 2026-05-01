from __future__ import annotations

import json
import sqlite3
from typing import Any


class ReadingProgressRepo:
    def get(self, conn: sqlite3.Connection, *, book_id: str, agent_stage: str) -> sqlite3.Row | None:
        return conn.execute(
            'SELECT * FROM reading_progress WHERE book_id = ? AND agent_stage = ?',
            (book_id, agent_stage),
        ).fetchone()

    def resolve_resume_doc_id(self, conn: sqlite3.Connection, *, book_id: str, agent_stage: str) -> int | None:
        progress = self.get(conn, book_id=book_id, agent_stage=agent_stage)
        if progress is None:
            return None
        last_completed = progress["last_completed_doc_id"]
        if last_completed is not None:
            return int(last_completed)
        checkpoint_token = str(progress["checkpoint_token"] or "").strip()
        if not checkpoint_token:
            return None
        parts = checkpoint_token.split(":")
        if len(parts) < 2:
            return None
        raw_doc_id = parts[-1].strip()
        if not raw_doc_id.isdigit():
            return None
        return int(raw_doc_id)

    def upsert(self, conn: sqlite3.Connection, payload: dict[str, Any]) -> int:
        existing = self.get(conn, book_id=payload['book_id'], agent_stage=payload['agent_stage'])
        if existing:
            conn.execute(
                '''
                UPDATE reading_progress SET
                    current_doc_id = ?, current_document_title_index = ?, current_source_path = ?,
                    current_source_offset = ?, last_completed_doc_id = ?, last_completed_title_index = ?,
                    last_completed_chapter_id = ?, status_json = ?, checkpoint_token = ?, updated_at = ?
                WHERE book_id = ? AND agent_stage = ?
                ''',
                (
                    payload.get('current_doc_id'),
                    payload.get('current_document_title_index'),
                    payload.get('current_source_path'),
                    payload.get('current_source_offset'),
                    payload.get('last_completed_doc_id'),
                    payload.get('last_completed_title_index'),
                    payload.get('last_completed_chapter_id'),
                    json.dumps(payload.get('status', {}), ensure_ascii=False),
                    payload.get('checkpoint_token'),
                    payload['updated_at'],
                    payload['book_id'],
                    payload['agent_stage'],
                ),
            )
            row = self.get(conn, book_id=payload['book_id'], agent_stage=payload['agent_stage'])
            if row is None:
                raise RuntimeError('Failed to reload reading progress row after update')
            return int(row['progress_id'])
        cur = conn.execute(
            '''
            INSERT INTO reading_progress(
                book_id, agent_stage, current_doc_id, current_document_title_index,
                current_source_path, current_source_offset, last_completed_doc_id,
                last_completed_title_index, last_completed_chapter_id, status_json,
                checkpoint_token, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ''',
            (
                payload['book_id'],
                payload['agent_stage'],
                payload.get('current_doc_id'),
                payload.get('current_document_title_index'),
                payload.get('current_source_path'),
                payload.get('current_source_offset'),
                payload.get('last_completed_doc_id'),
                payload.get('last_completed_title_index'),
                payload.get('last_completed_chapter_id'),
                json.dumps(payload.get('status', {}), ensure_ascii=False),
                payload.get('checkpoint_token'),
                payload['updated_at'],
            ),
        )
        if cur.lastrowid is None:
            raise RuntimeError('Failed to insert reading progress row')
        return int(cur.lastrowid)

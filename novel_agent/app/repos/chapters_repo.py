from __future__ import annotations

import json
import sqlite3
from typing import Any


MEMORY_STATUSES = {"provisional", "committed"}
DEFAULT_MEMORY_STATUS = "provisional"


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
        summary_status = self._normalize_status(payload.get('summary_status'))
        summary_evidence_window = self._normalize_range(payload.get('summary_evidence_window'))
        summary_target_range = self._normalize_range(payload.get('summary_target_range'))
        outline_status = self._normalize_status(payload.get('outline_status'))
        outline_evidence_window = self._normalize_range(payload.get('outline_evidence_window'))
        outline_target_range = self._normalize_range(payload.get('outline_target_range'))
        normalized_outline_update = payload.get('outline_update', {})
        if existing and self._is_committed(existing, "summary_status") and summary_status == DEFAULT_MEMORY_STATUS:
            normalized_summary_md = str(existing["summary_md"] or "")
            normalized_summary_short = str(existing["summary_short"] or "")
            summary_status = "committed"
            summary_evidence_window = self._row_text(existing, "summary_evidence_window")
            summary_target_range = self._row_text(existing, "summary_target_range")
        if existing and self._is_committed(existing, "outline_status") and outline_status == DEFAULT_MEMORY_STATUS:
            normalized_outline_update = self._load_json_dict(existing["outline_update_json"])
            outline_status = "committed"
            outline_evidence_window = self._row_text(existing, "outline_evidence_window")
            outline_target_range = self._row_text(existing, "outline_target_range")
        params = (
            payload['chapter_title'],
            int(payload['source_doc_start_id']),
            int(payload['source_doc_end_id']),
            int(payload['source_doc_count']),
            int(payload['source_total_chars']),
            json.dumps(normalized_summary_intermediate, ensure_ascii=False),
            normalized_summary_md,
            normalized_summary_short,
            summary_status,
            summary_evidence_window,
            summary_target_range,
            int(payload.get('importance_score', 0)),
            payload.get('importance_reason'),
            json.dumps(normalized_related_chapters, ensure_ascii=False),
            json.dumps(normalized_mentioned_characters, ensure_ascii=False),
            json.dumps(payload.get('world_update', {}), ensure_ascii=False),
            json.dumps(normalized_outline_update, ensure_ascii=False),
            outline_status,
            outline_evidence_window,
            outline_target_range,
            payload.get('close_read_run_id', ''),
            payload['updated_at'],
        )
        if existing:
            conn.execute(
                '''
                UPDATE chapters SET
                    chapter_title = ?, source_doc_start_id = ?, source_doc_end_id = ?,
                    source_doc_count = ?, source_total_chars = ?, summary_intermediate_json = ?,
                    summary_md = ?, summary_short = ?, summary_status = ?,
                    summary_evidence_window = ?, summary_target_range = ?,
                    importance_score = ?, importance_reason = ?,
                    related_chapters_json = ?, mentioned_characters_json = ?, world_update_json = ?,
                    outline_update_json = ?, outline_status = ?, outline_evidence_window = ?,
                    outline_target_range = ?, close_read_run_id = ?, updated_at = ?
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
                summary_md, summary_short, summary_status, summary_evidence_window,
                summary_target_range, importance_score, importance_reason,
                related_chapters_json, mentioned_characters_json, world_update_json,
                outline_update_json, outline_status, outline_evidence_window,
                outline_target_range, close_read_run_id, created_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
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
                summary_status,
                summary_evidence_window,
                summary_target_range,
                int(payload.get('importance_score', 0)),
                payload.get('importance_reason'),
                json.dumps(normalized_related_chapters, ensure_ascii=False),
                json.dumps(normalized_mentioned_characters, ensure_ascii=False),
                json.dumps(payload.get('world_update', {}), ensure_ascii=False),
                json.dumps(normalized_outline_update, ensure_ascii=False),
                outline_status,
                outline_evidence_window,
                outline_target_range,
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

    def mark_committed(
        self,
        conn: sqlite3.Connection,
        *,
        book_id: str,
        document_title_index: int,
        summary_md: str | None = None,
        summary_short: str | None = None,
        outline_update: dict[str, Any] | None = None,
        evidence_window: object = "",
        target_range: object = "",
        updated_at: str,
        overwrite_committed: bool = False,
    ) -> bool:
        row = self.get(conn, book_id=book_id, document_title_index=document_title_index)
        if row is None:
            return False
        if not overwrite_committed and self._is_committed(row, "summary_status") and self._is_committed(row, "outline_status"):
            return False
        payload = {
            "book_id": book_id,
            "document_title_index": document_title_index,
            "chapter_title": str(row["chapter_title"] or ""),
            "source_doc_start_id": int(row["source_doc_start_id"] or 0),
            "source_doc_end_id": int(row["source_doc_end_id"] or 0),
            "source_doc_count": int(row["source_doc_count"] or 0),
            "source_total_chars": int(row["source_total_chars"] or 0),
            "summary_intermediate": self._load_json_list(row["summary_intermediate_json"]),
            "summary_md": summary_md if summary_md is not None else str(row["summary_md"] or ""),
            "summary_short": summary_short if summary_short is not None else str(row["summary_short"] or ""),
            "summary_status": "committed",
            "summary_evidence_window": evidence_window,
            "summary_target_range": target_range,
            "importance_score": int(row["importance_score"] or 0),
            "importance_reason": row["importance_reason"],
            "related_chapters": self._load_json_list(row["related_chapters_json"]),
            "mentioned_characters": self._load_json_list(row["mentioned_characters_json"]),
            "world_update": self._load_json_dict(row["world_update_json"]),
            "outline_update": outline_update if outline_update is not None else self._load_json_dict(row["outline_update_json"]),
            "outline_status": "committed",
            "outline_evidence_window": evidence_window,
            "outline_target_range": target_range,
            "close_read_run_id": str(row["close_read_run_id"] or ""),
            "created_at": str(row["created_at"] or updated_at),
            "updated_at": updated_at,
        }
        self.upsert(conn, payload)
        return True

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

    def _normalize_status(self, value: object) -> str:
        text = str(value or DEFAULT_MEMORY_STATUS).strip().lower()
        return text if text in MEMORY_STATUSES else DEFAULT_MEMORY_STATUS

    def _normalize_range(self, value: object) -> str:
        if value is None:
            return ""
        if isinstance(value, str):
            return value.strip()
        if isinstance(value, (tuple, list)) and len(value) == 2:
            try:
                return f"{int(value[0])}-{int(value[1])}"
            except (TypeError, ValueError):
                return ""
        if isinstance(value, dict):
            start = value.get("start") or value.get("start_document_title_index")
            end = value.get("end") or value.get("end_document_title_index")
            try:
                return f"{int(start)}-{int(end)}"
            except (TypeError, ValueError):
                return ""
        return str(value).strip()

    def _is_committed(self, row: sqlite3.Row, column: str) -> bool:
        return self._row_text(row, column) == "committed"

    def _row_text(self, row: sqlite3.Row, column: str, default: str = "") -> str:
        try:
            value = row[column]
        except (IndexError, KeyError):
            return default
        return str(value or default).strip()

    def _load_json_dict(self, raw_value: object) -> dict[str, Any]:
        if not raw_value:
            return {}
        try:
            value = json.loads(str(raw_value))
        except json.JSONDecodeError:
            return {}
        return dict(value) if isinstance(value, dict) else {}

    def _load_json_list(self, raw_value: object) -> list[Any]:
        if not raw_value:
            return []
        try:
            value = json.loads(str(raw_value))
        except json.JSONDecodeError:
            return []
        return list(value) if isinstance(value, list) else []

from __future__ import annotations

import json
import sqlite3
from dataclasses import dataclass
from typing import Any


@dataclass(slots=True)
class DocumentRow:
    doc_id: int
    book_id: str
    path: str
    scope: str
    title: str | None
    document_title: str
    document_title_index: int
    inferred_chapter_no: int | None
    content: str
    content_chars: int
    character_keywords: list[str]
    content_tags: list[str]
    source_path: str
    source_file_name: str
    source_start_offset: int
    source_end_offset: int


class DocumentsRepo:
    def clear_book(self, conn: sqlite3.Connection, *, book_id: str) -> None:
        doc_ids = [int(row['doc_id']) for row in conn.execute('SELECT doc_id FROM documents WHERE book_id = ?', (book_id,)).fetchall()]
        for doc_id in doc_ids:
            conn.execute('DELETE FROM documents_fts WHERE rowid = ?', (doc_id,))
        conn.execute('DELETE FROM documents WHERE book_id = ?', (book_id,))

    def delete_from_source_offset(
        self,
        conn: sqlite3.Connection,
        *,
        book_id: str,
        source_path: str,
        source_offset: int,
    ) -> int:
        rows = conn.execute(
            """
            SELECT doc_id FROM documents
            WHERE book_id = ? AND source_path = ? AND source_start_offset >= ?
            ORDER BY doc_id
            """,
            (book_id, source_path, int(source_offset)),
        ).fetchall()
        doc_ids = [int(row["doc_id"]) for row in rows]
        for doc_id in doc_ids:
            conn.execute("DELETE FROM documents_fts WHERE rowid = ?", (doc_id,))
            conn.execute("DELETE FROM documents WHERE doc_id = ?", (doc_id,))
        return len(doc_ids)

    def insert_document(self, conn: sqlite3.Connection, payload: dict[str, Any]) -> int:
        cur = conn.execute(
            '''
            INSERT INTO documents(
                path, scope, title, content, mtime, size, content_sha256, book_id,
                source_path, source_file_name, source_start_offset, source_end_offset,
                source_batch_no, document_title, document_title_index, inferred_chapter_no,
                content_chars, character_keywords_json, content_tags_csv, segmentation_notes,
                ingestion_run_id, created_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ''',
            (
                payload.get('path', ''),
                payload.get('scope', ''),
                payload.get('title'),
                payload['content'],
                float(payload.get('mtime', 0)),
                int(payload.get('size', len(payload['content']))),
                payload.get('content_sha256', ''),
                payload['book_id'],
                payload.get('source_path', ''),
                payload.get('source_file_name', ''),
                int(payload.get('source_start_offset', 0)),
                int(payload.get('source_end_offset', 0)),
                int(payload.get('source_batch_no', 0)),
                payload.get('document_title', ''),
                int(payload.get('document_title_index', 0)),
                payload.get('inferred_chapter_no'),
                int(payload.get('content_chars', len(payload['content']))),
                json.dumps(payload.get('character_keywords', []), ensure_ascii=False),
                ",".join([str(tag).strip() for tag in payload.get('content_tags', []) if str(tag).strip()]),
                payload.get('segmentation_notes'),
                payload.get('ingestion_run_id', ''),
                payload.get('created_at', ''),
                payload.get('updated_at', ''),
            ),
        )
        if cur.lastrowid is None:
            raise RuntimeError("Failed to insert document row")
        doc_id = int(cur.lastrowid)
        keywords = ' '.join(payload.get('character_keywords', []))
        content_tags = ' '.join(payload.get('content_tags', []))
        conn.execute(
            'INSERT INTO documents_fts(rowid, content, path, scope, document_title, character_keywords, content_tags) VALUES (?, ?, ?, ?, ?, ?, ?)',
            (
                doc_id,
                payload['content'],
                payload.get('path', ''),
                payload.get('scope', ''),
                payload.get('document_title', ''),
                keywords,
                content_tags,
            ),
        )
        return doc_id

    def update_character_keywords(
        self,
        conn: sqlite3.Connection,
        *,
        doc_id: int,
        character_keywords: list[str],
        updated_at: str,
    ) -> None:
        keywords_json = json.dumps(character_keywords, ensure_ascii=False)
        keywords_text = " ".join(character_keywords)
        conn.execute(
            "UPDATE documents SET character_keywords_json = ?, updated_at = ? WHERE doc_id = ?",
            (keywords_json, updated_at, doc_id),
        )
        conn.execute(
            "UPDATE documents_fts SET character_keywords = ? WHERE rowid = ?",
            (keywords_text, doc_id),
        )

    def fetch_after_doc_id(self, conn: sqlite3.Connection, *, book_id: str, doc_id: int | None = None) -> list[DocumentRow]:
        if doc_id is None:
            rows = conn.execute('SELECT * FROM documents WHERE book_id = ? ORDER BY doc_id', (book_id,)).fetchall()
        else:
            rows = conn.execute('SELECT * FROM documents WHERE book_id = ? AND doc_id > ? ORDER BY doc_id', (book_id, doc_id)).fetchall()
        return [self._row_to_document(row) for row in rows]

    def fetch_by_title_index(self, conn: sqlite3.Connection, *, book_id: str, document_title_index: int) -> list[DocumentRow]:
        rows = conn.execute(
            'SELECT * FROM documents WHERE book_id = ? AND document_title_index = ? ORDER BY doc_id',
            (book_id, document_title_index),
        ).fetchall()
        return [self._row_to_document(row) for row in rows]

    def count_by_book(self, conn: sqlite3.Connection, *, book_id: str) -> int:
        row = conn.execute('SELECT COUNT(*) AS count FROM documents WHERE book_id = ?', (book_id,)).fetchone()
        return int(row['count']) if row else 0

    def list_title_indexes(self, conn: sqlite3.Connection, *, book_id: str) -> list[int]:
        rows = conn.execute(
            'SELECT DISTINCT document_title_index FROM documents WHERE book_id = ? ORDER BY document_title_index',
            (book_id,),
        ).fetchall()
        return [int(row['document_title_index']) for row in rows]

    def fetch_last_document(self, conn: sqlite3.Connection, *, book_id: str) -> DocumentRow | None:
        row = conn.execute(
            'SELECT * FROM documents WHERE book_id = ? ORDER BY doc_id DESC LIMIT 1',
            (book_id,),
        ).fetchone()
        if row is None:
            return None
        return self._row_to_document(row)

    def _row_to_document(self, row: sqlite3.Row) -> DocumentRow:
        return DocumentRow(
            doc_id=int(row['doc_id']),
            book_id=str(row['book_id']),
            path=str(row['path']),
            scope=str(row['scope']),
            title=str(row['title']) if row['title'] is not None else None,
            document_title=str(row['document_title']),
            document_title_index=int(row['document_title_index']),
            inferred_chapter_no=int(row['inferred_chapter_no']) if row['inferred_chapter_no'] is not None else None,
            content=str(row['content']),
            content_chars=int(row['content_chars']),
            character_keywords=list(json.loads(row['character_keywords_json'] or '[]')),
            content_tags=[item.strip() for item in str(row['content_tags_csv'] or '').split(',') if item.strip()],
            source_path=str(row['source_path']),
            source_file_name=str(row['source_file_name']),
            source_start_offset=int(row['source_start_offset']),
            source_end_offset=int(row['source_end_offset']),
        )

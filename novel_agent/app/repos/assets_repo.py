from __future__ import annotations

import sqlite3


class AssetsRepo:
    def get(self, conn: sqlite3.Connection, *, book_id: str) -> sqlite3.Row | None:
        return conn.execute('SELECT * FROM book_assets WHERE book_id = ?', (book_id,)).fetchone()

    def upsert(self, conn: sqlite3.Connection, payload: dict[str, str]) -> None:
        existing = self.get(conn, book_id=payload['book_id'])
        if existing:
            conn.execute(
                '''
                UPDATE book_assets SET
                    source_root = ?, world_markdown_path = ?, world_summary_path = ?,
                    outline_markdown_path = ?, toc_markdown = ?, toc_source_path = ?, debug_export_path = ?, updated_at = ?
                WHERE book_id = ?
                ''',
                (
                    payload['source_root'],
                    payload['world_markdown_path'],
                    payload['world_summary_path'],
                    payload['outline_markdown_path'],
                    payload.get('toc_markdown', ''),
                    payload.get('toc_source_path', ''),
                    payload.get('debug_export_path'),
                    payload['updated_at'],
                    payload['book_id'],
                ),
            )
            return
        conn.execute(
            '''
            INSERT INTO book_assets(
                book_id, source_root, world_markdown_path, world_summary_path,
                outline_markdown_path, toc_markdown, toc_source_path, debug_export_path, created_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ''',
            (
                payload['book_id'],
                payload['source_root'],
                payload['world_markdown_path'],
                payload['world_summary_path'],
                payload['outline_markdown_path'],
                payload.get('toc_markdown', ''),
                payload.get('toc_source_path', ''),
                payload.get('debug_export_path'),
                payload['created_at'],
                payload['updated_at'],
            ),
        )

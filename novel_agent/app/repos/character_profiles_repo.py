from __future__ import annotations

import json
import sqlite3
from typing import Any


class CharacterProfilesRepo:
    def get(self, conn: sqlite3.Connection, *, book_id: str, canonical_name: str) -> sqlite3.Row | None:
        return conn.execute(
            'SELECT * FROM character_profiles WHERE book_id = ? AND canonical_name = ?',
            (book_id, canonical_name),
        ).fetchone()

    def list_by_names(self, conn: sqlite3.Connection, *, book_id: str, names: list[str]) -> list[sqlite3.Row]:
        if not names:
            return []
        placeholders = ','.join('?' for _ in names)
        rows = conn.execute(
            f'SELECT * FROM character_profiles WHERE book_id = ? AND canonical_name IN ({placeholders}) ORDER BY canonical_name',
            [book_id, *names],
        ).fetchall()
        return list(rows)

    def upsert(self, conn: sqlite3.Connection, payload: dict[str, Any]) -> int:
        existing = self.get(conn, book_id=payload['book_id'], canonical_name=payload['canonical_name'])
        json_fields = {
            'aliases_json': json.dumps(payload.get('aliases', []), ensure_ascii=False),
            'personality_json': json.dumps(payload.get('personality', []), ensure_ascii=False),
            'occupations_json': json.dumps(payload.get('occupations', []), ensure_ascii=False),
            'age_timeline_json': json.dumps(payload.get('age_timeline', []), ensure_ascii=False),
            'abilities_json': json.dumps(payload.get('abilities', []), ensure_ascii=False),
            'recent_activity_json': json.dumps(payload.get('recent_activity', []), ensure_ascii=False),
            'relationships_json': json.dumps(payload.get('relationships', []), ensure_ascii=False),
            'story_events_json': json.dumps(payload.get('story_events', []), ensure_ascii=False),
            'chapter_indexes_json': json.dumps(payload.get('chapter_indexes', []), ensure_ascii=False),
            'mentioned_doc_ids_json': json.dumps(payload.get('mentioned_doc_ids', []), ensure_ascii=False),
            'speaking_doc_ids_json': json.dumps(payload.get('speaking_doc_ids', []), ensure_ascii=False),
        }
        if existing:
            conn.execute(
                '''
                UPDATE character_profiles SET
                    aliases_json = ?, profile_summary_md = ?,
                    speaking_character_status = ?, personhood_evidence_summary = ?, evidence_level = ?,
                    personality_json = ?, occupations_json = ?,
                    age_timeline_json = ?, abilities_json = ?, recent_activity_json = ?, relationships_json = ?,
                    story_events_json = ?, chapter_indexes_json = ?, mentioned_doc_ids_json = ?, speaking_doc_ids_json = ?,
                    first_seen_doc_id = ?, last_seen_doc_id = ?,
                    first_seen_title_index = ?, last_seen_title_index = ?, importance_score = ?,
                    profile_version = ?, updated_at = ?
                WHERE book_id = ? AND canonical_name = ?
                ''',
                (
                    json_fields['aliases_json'],
                    payload.get('profile_summary_md', ''),
                    payload.get('speaking_character_status', 'unknown'),
                    payload.get('personhood_evidence_summary', ''),
                    payload.get('evidence_level', 'inferred'),
                    json_fields['personality_json'],
                    json_fields['occupations_json'],
                    json_fields['age_timeline_json'],
                    json_fields['abilities_json'],
                    json_fields['recent_activity_json'],
                    json_fields['relationships_json'],
                    json_fields['story_events_json'],
                    json_fields['chapter_indexes_json'],
                    json_fields['mentioned_doc_ids_json'],
                    json_fields['speaking_doc_ids_json'],
                    payload.get('first_seen_doc_id'),
                    payload.get('last_seen_doc_id'),
                    payload.get('first_seen_title_index'),
                    payload.get('last_seen_title_index'),
                    int(payload.get('importance_score', 0)),
                    int(payload.get('profile_version', 1)),
                    payload['updated_at'],
                    payload['book_id'],
                    payload['canonical_name'],
                ),
            )
            row = self.get(conn, book_id=payload['book_id'], canonical_name=payload['canonical_name'])
            return int(row['character_id'])
        cur = conn.execute(
            '''
            INSERT INTO character_profiles(
                book_id, canonical_name, aliases_json, profile_summary_md,
                speaking_character_status, personhood_evidence_summary, evidence_level, personality_json,
                occupations_json, age_timeline_json, abilities_json, recent_activity_json,
                relationships_json, story_events_json, chapter_indexes_json, mentioned_doc_ids_json, speaking_doc_ids_json,
                first_seen_doc_id, last_seen_doc_id,
                first_seen_title_index, last_seen_title_index, importance_score, profile_version,
                created_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ''',
            (
                payload['book_id'],
                payload['canonical_name'],
                json_fields['aliases_json'],
                payload.get('profile_summary_md', ''),
                payload.get('speaking_character_status', 'unknown'),
                payload.get('personhood_evidence_summary', ''),
                payload.get('evidence_level', 'inferred'),
                json_fields['personality_json'],
                json_fields['occupations_json'],
                json_fields['age_timeline_json'],
                json_fields['abilities_json'],
                json_fields['recent_activity_json'],
                json_fields['relationships_json'],
                json_fields['story_events_json'],
                json_fields['chapter_indexes_json'],
                json_fields['mentioned_doc_ids_json'],
                json_fields['speaking_doc_ids_json'],
                payload.get('first_seen_doc_id'),
                payload.get('last_seen_doc_id'),
                payload.get('first_seen_title_index'),
                payload.get('last_seen_title_index'),
                int(payload.get('importance_score', 0)),
                int(payload.get('profile_version', 1)),
                payload['created_at'],
                payload['updated_at'],
            ),
        )
        return int(cur.lastrowid)

    def list_by_book(self, conn: sqlite3.Connection, *, book_id: str) -> list[sqlite3.Row]:
        return conn.execute('SELECT * FROM character_profiles WHERE book_id = ? ORDER BY canonical_name', (book_id,)).fetchall()

    def delete_many(
        self,
        conn: sqlite3.Connection,
        *,
        book_id: str,
        canonical_names: list[str],
    ) -> None:
        names = [str(name).strip() for name in canonical_names if str(name).strip()]
        if not names:
            return
        placeholders = ",".join("?" for _ in names)
        conn.execute(
            f"DELETE FROM character_profiles WHERE book_id = ? AND canonical_name IN ({placeholders})",
            [book_id, *names],
        )

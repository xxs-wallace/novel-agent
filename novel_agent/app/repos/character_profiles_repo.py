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

    def get_by_id(self, conn: sqlite3.Connection, *, book_id: str, character_id: int) -> sqlite3.Row | None:
        return conn.execute(
            'SELECT * FROM character_profiles WHERE book_id = ? AND character_id = ?',
            (book_id, character_id),
        ).fetchone()

    def list_by_ids(self, conn: sqlite3.Connection, *, book_id: str, character_ids: list[int]) -> list[sqlite3.Row]:
        ids = []
        for raw_id in character_ids:
            try:
                character_id = int(raw_id)
            except (TypeError, ValueError):
                continue
            if character_id > 0 and character_id not in ids:
                ids.append(character_id)
        if not ids:
            return []
        placeholders = ','.join('?' for _ in ids)
        rows = conn.execute(
            f'SELECT * FROM character_profiles WHERE book_id = ? AND character_id IN ({placeholders}) ORDER BY canonical_name',
            [book_id, *ids],
        ).fetchall()
        return list(rows)

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
        existing_brief = self._json_dict(existing["profile_brief_json"]) if existing and "profile_brief" not in payload else {}
        existing_brief_status = str(existing["profile_brief_status"] or "missing") if existing else "missing"
        existing_brief_version = int(existing["profile_brief_version"] or 0) if existing else 0
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
            'profile_brief_json': json.dumps(payload.get('profile_brief', existing_brief), ensure_ascii=False),
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
                    profile_brief_json = ?, profile_brief_status = ?, profile_brief_version = ?,
                    brief_compacted_until_doc_id = ?, brief_compacted_until_segment_id = ?, profile_brief_updated_at = ?,
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
                    json_fields['profile_brief_json'],
                    payload.get('profile_brief_status', existing_brief_status),
                    int(payload.get('profile_brief_version', existing_brief_version)),
                    payload.get('brief_compacted_until_doc_id', existing["brief_compacted_until_doc_id"]),
                    payload.get('brief_compacted_until_segment_id', existing["brief_compacted_until_segment_id"]),
                    payload.get('profile_brief_updated_at', existing["profile_brief_updated_at"]),
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
                profile_brief_json, profile_brief_status, profile_brief_version,
                brief_compacted_until_doc_id, brief_compacted_until_segment_id, profile_brief_updated_at,
                first_seen_doc_id, last_seen_doc_id,
                first_seen_title_index, last_seen_title_index, importance_score, profile_version,
                created_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
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
                    json_fields['profile_brief_json'],
                    payload.get('profile_brief_status', 'missing'),
                    int(payload.get('profile_brief_version', 0)),
                    payload.get('brief_compacted_until_doc_id'),
                    payload.get('brief_compacted_until_segment_id', ''),
                    payload.get('profile_brief_updated_at', ''),
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

    @staticmethod
    def _json_dict(raw_value: object) -> dict[str, Any]:
        if not raw_value:
            return {}
        try:
            value = json.loads(str(raw_value))
        except json.JSONDecodeError:
            return {}
        return value if isinstance(value, dict) else {}

    def list_by_book(self, conn: sqlite3.Connection, *, book_id: str) -> list[sqlite3.Row]:
        return conn.execute('SELECT * FROM character_profiles WHERE book_id = ? ORDER BY canonical_name', (book_id,)).fetchall()

    def update_profile_brief(
        self,
        conn: sqlite3.Connection,
        *,
        book_id: str,
        character_id: int | None = None,
        canonical_name: str | None = None,
        profile_brief: dict[str, Any],
        profile_brief_status: str,
        compacted_until_doc_id: int | None = None,
        compacted_until_segment_id: str = "",
        updated_at: str,
    ) -> None:
        if character_id is not None:
            row = self.get_by_id(conn, book_id=book_id, character_id=character_id)
            where_clause = "book_id = ? AND character_id = ?"
            where_args: list[Any] = [book_id, character_id]
        elif canonical_name:
            row = self.get(conn, book_id=book_id, canonical_name=canonical_name)
            where_clause = "book_id = ? AND canonical_name = ?"
            where_args = [book_id, canonical_name]
        else:
            return
        if row is None:
            return
        version = int(row["profile_brief_version"] or 0) + 1
        conn.execute(
            f"""
            UPDATE character_profiles
            SET profile_brief_json = ?,
                profile_brief_status = ?,
                profile_brief_version = ?,
                brief_compacted_until_doc_id = ?,
                brief_compacted_until_segment_id = ?,
                profile_brief_updated_at = ?,
                updated_at = ?
            WHERE {where_clause}
            """,
            [
                json.dumps(profile_brief, ensure_ascii=False),
                profile_brief_status,
                version,
                compacted_until_doc_id,
                compacted_until_segment_id,
                updated_at,
                updated_at,
                *where_args,
            ],
        )

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

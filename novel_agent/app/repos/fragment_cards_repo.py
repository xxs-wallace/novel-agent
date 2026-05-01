from __future__ import annotations

import json
import re
import sqlite3
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Literal, cast

from novel_agent.app.schemas.creative_kb_schema import FragmentCard, StyleFeatures


@dataclass(slots=True)
class FragmentCardFTSHit:
    fragment_id: str
    cluster_id: str | None
    is_cluster_representative: bool
    score: float


class FragmentCardsRepo:
    def upsert_cards(self, conn: sqlite3.Connection, cards: list[FragmentCard]) -> None:
        if not cards:
            return
        now = _utc_now()
        for card in cards:
            source_offset_start, source_offset_end = self._normalize_offsets(card.source_offsets)
            conn.execute(
                '''
                INSERT INTO fragment_cards(
                    fragment_id, doc_id, document_title, document_title_index, cluster_id,
                    is_cluster_representative, source_path, source_offset_start, source_offset_end,
                    source_excerpt, content_summary, narrative_function_json, narrative_function_text,
                    scene_space_tags_json, event_tags_json, emotion_tags_json,
                    emotion_mechanism_text, expression_mode_tags_json, preferred_tags_json,
                    pov_mode, character_focus_json, character_temperament_json,
                    character_relation_text, relationship_state_json, continuity_phase,
                    style_features_json, style_profile_text, transferability_score,
                    context_dependency_level, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(fragment_id) DO UPDATE SET
                    doc_id = excluded.doc_id,
                    document_title = excluded.document_title,
                    document_title_index = excluded.document_title_index,
                    cluster_id = excluded.cluster_id,
                    is_cluster_representative = excluded.is_cluster_representative,
                    source_path = excluded.source_path,
                    source_offset_start = excluded.source_offset_start,
                    source_offset_end = excluded.source_offset_end,
                    source_excerpt = excluded.source_excerpt,
                    content_summary = excluded.content_summary,
                    narrative_function_json = excluded.narrative_function_json,
                    narrative_function_text = excluded.narrative_function_text,
                    scene_space_tags_json = excluded.scene_space_tags_json,
                    event_tags_json = excluded.event_tags_json,
                    emotion_tags_json = excluded.emotion_tags_json,
                    emotion_mechanism_text = excluded.emotion_mechanism_text,
                    expression_mode_tags_json = excluded.expression_mode_tags_json,
                    preferred_tags_json = excluded.preferred_tags_json,
                    pov_mode = excluded.pov_mode,
                    character_focus_json = excluded.character_focus_json,
                    character_temperament_json = excluded.character_temperament_json,
                    character_relation_text = excluded.character_relation_text,
                    relationship_state_json = excluded.relationship_state_json,
                    continuity_phase = excluded.continuity_phase,
                    style_features_json = excluded.style_features_json,
                    style_profile_text = excluded.style_profile_text,
                    transferability_score = excluded.transferability_score,
                    context_dependency_level = excluded.context_dependency_level,
                    updated_at = excluded.updated_at
                ''',
                (
                    card.fragment_id,
                    str(card.doc_id),
                    card.document_title,
                    str(card.document_title_index),
                    card.cluster_id,
                    int(card.is_cluster_representative),
                    card.source_path,
                    source_offset_start,
                    source_offset_end,
                    card.source_excerpt,
                    card.content_summary,
                    _json_dumps(card.narrative_function),
                    card.narrative_function_text,
                    _json_dumps(card.scene_space_tags),
                    _json_dumps(card.event_tags),
                    _json_dumps(card.emotion_tags),
                    card.emotion_mechanism_text,
                    _json_dumps(card.expression_mode_tags),
                    _json_dumps(card.preferred_tags),
                    card.pov_mode,
                    _json_dumps(card.character_focus),
                    _json_dumps(card.character_temperament),
                    card.character_relation_text,
                    _json_dumps(card.relationship_state),
                    card.continuity_phase,
                    _style_features_json(card.style_features),
                    card.style_profile_text,
                    float(card.transferability_score),
                    card.context_dependency_level,
                    now,
                    now,
                ),
            )
            self._replace_fts_row(conn, card)

    def get(self, conn: sqlite3.Connection, *, fragment_id: str) -> FragmentCard | None:
        row = conn.execute(
            'SELECT * FROM fragment_cards WHERE fragment_id = ?',
            (fragment_id,),
        ).fetchone()
        if row is None:
            return None
        return self._row_to_card(row)

    def list_all(
        self,
        conn: sqlite3.Connection,
    ) -> list[FragmentCard]:
        rows = conn.execute(
            '''
            SELECT * FROM fragment_cards
            ORDER BY fragment_id
            '''
        ).fetchall()
        return [self._row_to_card(row) for row in rows]

    def list_by_fragment_ids(
        self,
        conn: sqlite3.Connection,
        *,
        fragment_ids: list[str],
    ) -> list[FragmentCard]:
        if not fragment_ids:
            return []
        placeholders = ','.join('?' for _ in fragment_ids)
        rows = conn.execute(
            f'''
            SELECT * FROM fragment_cards
            WHERE fragment_id IN ({placeholders})
            ORDER BY fragment_id
            ''',
            fragment_ids,
        ).fetchall()
        return [self._row_to_card(row) for row in rows]

    def list_by_cluster_id(
        self,
        conn: sqlite3.Connection,
        *,
        cluster_id: str,
    ) -> list[FragmentCard]:
        rows = conn.execute(
            '''
            SELECT * FROM fragment_cards
            WHERE cluster_id = ?
            ORDER BY is_cluster_representative DESC, fragment_id
            ''',
            (cluster_id,),
        ).fetchall()
        return [self._row_to_card(row) for row in rows]

    def list_by_doc_id(
        self,
        conn: sqlite3.Connection,
        *,
        doc_id: str,
    ) -> list[FragmentCard]:
        rows = conn.execute(
            '''
            SELECT * FROM fragment_cards
            WHERE doc_id = ?
            ORDER BY fragment_id
            ''',
            (str(doc_id),),
        ).fetchall()
        return [self._row_to_card(row) for row in rows]

    def list_by_doc_ids(
        self,
        conn: sqlite3.Connection,
        *,
        doc_ids: list[str],
    ) -> list[FragmentCard]:
        if not doc_ids:
            return []
        placeholders = ",".join("?" for _ in doc_ids)
        rows = conn.execute(
            f'''
            SELECT * FROM fragment_cards
            WHERE doc_id IN ({placeholders})
            ORDER BY CAST(doc_id AS INTEGER), fragment_id
            ''',
            [str(doc_id) for doc_id in doc_ids],
        ).fetchall()
        return [self._row_to_card(row) for row in rows]

    def list_existing_doc_ids(
        self,
        conn: sqlite3.Connection,
        *,
        doc_ids: list[str],
    ) -> set[str]:
        if not doc_ids:
            return set()
        placeholders = ",".join("?" for _ in doc_ids)
        rows = conn.execute(
            f'''
            SELECT DISTINCT doc_id FROM fragment_cards
            WHERE doc_id IN ({placeholders})
            ''',
            [str(doc_id) for doc_id in doc_ids],
        ).fetchall()
        return {str(row["doc_id"]) for row in rows}

    def list_representatives(
        self,
        conn: sqlite3.Connection,
        *,
        cluster_id: str | None = None,
    ) -> list[FragmentCard]:
        if cluster_id is None:
            rows = conn.execute(
                '''
                SELECT * FROM fragment_cards
                WHERE is_cluster_representative = 1
                ORDER BY cluster_id, fragment_id
                '''
            ).fetchall()
        else:
            rows = conn.execute(
                '''
                SELECT * FROM fragment_cards
                WHERE cluster_id = ? AND is_cluster_representative = 1
                ORDER BY fragment_id
                ''',
                (cluster_id,),
            ).fetchall()
        return [self._row_to_card(row) for row in rows]

    def get_representative_by_cluster_id(
        self,
        conn: sqlite3.Connection,
        *,
        cluster_id: str,
    ) -> FragmentCard | None:
        row = conn.execute(
            '''
            SELECT * FROM fragment_cards
            WHERE cluster_id = ? AND is_cluster_representative = 1
            ORDER BY fragment_id
            LIMIT 1
            ''',
            (cluster_id,),
        ).fetchone()
        if row is None:
            return None
        return self._row_to_card(row)

    def mark_cluster_membership(
        self,
        conn: sqlite3.Connection,
        *,
        fragment_id: str,
        cluster_id: str | None,
        is_representative: bool,
    ) -> None:
        conn.execute(
            '''
            UPDATE fragment_cards
            SET cluster_id = ?, is_cluster_representative = ?, updated_at = ?
            WHERE fragment_id = ?
            ''',
            (cluster_id, int(is_representative), _utc_now(), fragment_id),
        )

    def mark_many_cluster_memberships(
        self,
        conn: sqlite3.Connection,
        *,
        memberships: list[tuple[str, str | None, bool]],
    ) -> None:
        if not memberships:
            return
        now = _utc_now()
        conn.executemany(
            '''
            UPDATE fragment_cards
            SET cluster_id = ?, is_cluster_representative = ?, updated_at = ?
            WHERE fragment_id = ?
            ''',
            [
                (cluster_id, int(is_representative), now, fragment_id)
                for fragment_id, cluster_id, is_representative in memberships
            ],
        )

    def search_fts(
        self,
        conn: sqlite3.Connection,
        *,
        query_text: str,
        limit: int = 20,
        cluster_id: str | None = None,
        representatives_only: bool = False,
    ) -> list[FragmentCardFTSHit]:
        query_text = self._normalize_fts_query(query_text)
        if not query_text:
            return []
        predicates = ['fragment_cards_fts MATCH ?']
        params: list[object] = [query_text]
        if cluster_id is not None:
            predicates.append('fc.cluster_id = ?')
            params.append(cluster_id)
        if representatives_only:
            predicates.append('fc.is_cluster_representative = 1')
        params.append(int(limit))
        try:
            rows = conn.execute(
                f'''
                SELECT
                    fc.fragment_id,
                    fc.cluster_id,
                    fc.is_cluster_representative,
                    bm25(fragment_cards_fts) AS score
                FROM fragment_cards_fts
                INNER JOIN fragment_cards AS fc
                    ON fc.fragment_id = fragment_cards_fts.fragment_id
                WHERE {' AND '.join(predicates)}
                ORDER BY score ASC, fc.fragment_id ASC
                LIMIT ?
                ''',
                params,
            ).fetchall()
        except sqlite3.OperationalError:
            return []
        return [
            FragmentCardFTSHit(
                fragment_id=str(row['fragment_id']),
                cluster_id=str(row['cluster_id']) if row['cluster_id'] is not None else None,
                is_cluster_representative=bool(row['is_cluster_representative']),
                score=float(row['score']),
            )
            for row in rows
        ]

    def _normalize_fts_query(self, query_text: str) -> str:
        tokens = re.findall(r"[0-9A-Za-z_\u4e00-\u9fff]+", query_text.strip())
        return " OR ".join(f'"{token}"' for token in tokens[:16])

    def _replace_fts_row(self, conn: sqlite3.Connection, card: FragmentCard) -> None:
        conn.execute(
            'DELETE FROM fragment_cards_fts WHERE fragment_id = ?',
            (card.fragment_id,),
        )
        conn.execute(
            '''
            INSERT INTO fragment_cards_fts(
                fragment_id,
                content_summary,
                narrative_function_text,
                emotion_mechanism_text,
                character_relation_text,
                style_profile_text,
                preferred_tags_text
            ) VALUES (?, ?, ?, ?, ?, ?, ?)
            ''',
            (
                card.fragment_id,
                card.content_summary,
                card.narrative_function_text,
                card.emotion_mechanism_text,
                card.character_relation_text,
                card.style_profile_text,
                ' '.join(card.preferred_tags),
            ),
        )

    def _row_to_card(self, row: sqlite3.Row) -> FragmentCard:
        return FragmentCard(
            fragment_id=str(row['fragment_id']),
            doc_id=str(row['doc_id']),
            document_title=str(row['document_title']),
            document_title_index=str(row['document_title_index']),
            cluster_id=str(row['cluster_id']) if row['cluster_id'] is not None else None,
            is_cluster_representative=bool(row['is_cluster_representative']),
            source_path=str(row['source_path']),
            source_offsets=(
                int(row['source_offset_start']),
                int(row['source_offset_end']),
            ),
            source_excerpt=str(row['source_excerpt']),
            content_summary=str(row['content_summary']),
            narrative_function=_json_loads(row['narrative_function_json']),
            narrative_function_text=str(row['narrative_function_text']),
            scene_space_tags=_json_loads(row['scene_space_tags_json']),
            event_tags=_json_loads(row['event_tags_json']),
            emotion_tags=_json_loads(row['emotion_tags_json']),
            emotion_mechanism_text=str(row['emotion_mechanism_text']),
            expression_mode_tags=_json_loads(row['expression_mode_tags_json']),
            preferred_tags=_json_loads(row['preferred_tags_json']),
            pov_mode=str(row['pov_mode']),
            character_focus=_json_loads(row['character_focus_json']),
            character_temperament=_json_loads(row['character_temperament_json']),
            character_relation_text=str(row['character_relation_text']),
            relationship_state=_json_loads(row['relationship_state_json']),
            continuity_phase=str(row['continuity_phase']),
            style_features=_style_features_from_json(row['style_features_json']),
            style_profile_text=str(row['style_profile_text']),
            transferability_score=float(row['transferability_score']),
            context_dependency_level=cast(
                Literal["low", "medium", "high"],
                str(row['context_dependency_level']),
            ),
        )

    def _normalize_offsets(self, source_offsets: tuple[int, int]) -> tuple[int, int]:
        if len(source_offsets) != 2:
            raise ValueError('source_offsets must contain exactly two integers')
        return int(source_offsets[0]), int(source_offsets[1])


def _json_dumps(value: list[str]) -> str:
    return json.dumps(value, ensure_ascii=False)


def _json_loads(value: str | bytes | None) -> list[str]:
    if not value:
        return []
    loaded = json.loads(value)
    if not isinstance(loaded, list):
        raise ValueError('Expected JSON array')
    return [str(item) for item in loaded]


def _style_features_json(style_features: StyleFeatures) -> str:
    return json.dumps(
        {
            'sentence_rhythm': style_features.sentence_rhythm,
            'dialogue_density': style_features.dialogue_density,
            'interiority_density': style_features.interiority_density,
            'imagery_density': style_features.imagery_density,
        },
        ensure_ascii=False,
    )


def _style_features_from_json(value: str | bytes | None) -> StyleFeatures:
    payload = json.loads(value or '{}')
    if not isinstance(payload, dict):
        raise ValueError('Expected JSON object for style_features_json')
    return StyleFeatures(
        sentence_rhythm=str(payload.get('sentence_rhythm', '')),
        dialogue_density=str(payload.get('dialogue_density', '')),
        interiority_density=str(payload.get('interiority_density', '')),
        imagery_density=str(payload.get('imagery_density', '')),
    )


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()

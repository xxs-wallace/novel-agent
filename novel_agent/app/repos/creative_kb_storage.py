from __future__ import annotations

import sqlite3


CREATE_FRAGMENT_CARDS_TABLE_SQL = '''
CREATE TABLE IF NOT EXISTS fragment_cards (
    fragment_id TEXT PRIMARY KEY,
    doc_id TEXT NOT NULL,
    document_title TEXT NOT NULL,
    document_title_index TEXT NOT NULL,
    cluster_id TEXT,
    is_cluster_representative INTEGER NOT NULL DEFAULT 0,
    source_path TEXT NOT NULL DEFAULT '',
    source_offset_start INTEGER NOT NULL DEFAULT 0,
    source_offset_end INTEGER NOT NULL DEFAULT 0,
    source_excerpt TEXT NOT NULL DEFAULT '',
    content_summary TEXT NOT NULL DEFAULT '',
    narrative_function_json TEXT NOT NULL DEFAULT '[]',
    narrative_function_text TEXT NOT NULL DEFAULT '',
    scene_space_tags_json TEXT NOT NULL DEFAULT '[]',
    event_tags_json TEXT NOT NULL DEFAULT '[]',
    emotion_tags_json TEXT NOT NULL DEFAULT '[]',
    emotion_mechanism_text TEXT NOT NULL DEFAULT '',
    expression_mode_tags_json TEXT NOT NULL DEFAULT '[]',
    preferred_tags_json TEXT NOT NULL DEFAULT '[]',
    pov_mode TEXT NOT NULL DEFAULT '',
    character_focus_json TEXT NOT NULL DEFAULT '[]',
    character_temperament_json TEXT NOT NULL DEFAULT '[]',
    character_relation_text TEXT NOT NULL DEFAULT '',
    relationship_state_json TEXT NOT NULL DEFAULT '[]',
    continuity_phase TEXT NOT NULL DEFAULT '',
    style_features_json TEXT NOT NULL DEFAULT '{}',
    style_profile_text TEXT NOT NULL DEFAULT '',
    transferability_score REAL NOT NULL DEFAULT 0.0,
    context_dependency_level TEXT NOT NULL DEFAULT 'medium',
    created_at TEXT NOT NULL DEFAULT '',
    updated_at TEXT NOT NULL DEFAULT '',
    CHECK (context_dependency_level IN ('low', 'medium', 'high'))
)
'''

CREATE_FRAGMENT_CLUSTERS_TABLE_SQL = '''
CREATE TABLE IF NOT EXISTS fragment_clusters (
    cluster_id TEXT PRIMARY KEY,
    cluster_theme TEXT NOT NULL DEFAULT '',
    representative_fragment_id TEXT NOT NULL,
    member_count INTEGER NOT NULL DEFAULT 0,
    dedup_reason TEXT NOT NULL DEFAULT '',
    created_at TEXT NOT NULL DEFAULT '',
    updated_at TEXT NOT NULL DEFAULT '',
    FOREIGN KEY(representative_fragment_id) REFERENCES fragment_cards(fragment_id)
)
'''

CREATE_FRAGMENT_CARDS_FTS_SQL = '''
CREATE VIRTUAL TABLE IF NOT EXISTS fragment_cards_fts USING fts5(
    fragment_id UNINDEXED,
    content_summary,
    narrative_function_text,
    emotion_mechanism_text,
    character_relation_text,
    style_profile_text,
    preferred_tags_text,
    tokenize='unicode61'
)
'''

CREATE_SEMANTIC_ALIASES_TABLE_SQL = '''
CREATE TABLE IF NOT EXISTS semantic_aliases (
    alias_id TEXT PRIMARY KEY,
    book_id TEXT NOT NULL,
    canonical_key TEXT NOT NULL,
    aliases_json TEXT NOT NULL DEFAULT '[]',
    category TEXT NOT NULL DEFAULT 'requirement_coverage',
    source TEXT NOT NULL DEFAULT 'model_extraction',
    evidence_doc_ids_json TEXT NOT NULL DEFAULT '[]',
    confidence REAL NOT NULL DEFAULT 0.0,
    extraction_run_id TEXT NOT NULL DEFAULT '',
    created_at TEXT NOT NULL DEFAULT '',
    updated_at TEXT NOT NULL DEFAULT '',
    UNIQUE(book_id, canonical_key, category, source)
)
'''

CREATIVE_KB_INDEX_STATEMENTS = (
    'CREATE INDEX IF NOT EXISTS idx_fragment_cards_doc_id ON fragment_cards(doc_id)',
    'CREATE INDEX IF NOT EXISTS idx_fragment_cards_cluster_id ON fragment_cards(cluster_id)',
    'CREATE INDEX IF NOT EXISTS idx_fragment_cards_title_index ON fragment_cards(document_title_index)',
    'CREATE INDEX IF NOT EXISTS idx_fragment_cards_representative ON fragment_cards(is_cluster_representative)',
    'CREATE INDEX IF NOT EXISTS idx_fragment_cards_cluster_rep ON fragment_cards(cluster_id, is_cluster_representative)',
    'CREATE INDEX IF NOT EXISTS idx_fragment_clusters_representative_fragment_id ON fragment_clusters(representative_fragment_id)',
    'CREATE INDEX IF NOT EXISTS idx_semantic_aliases_book_category ON semantic_aliases(book_id, category)',
    'CREATE INDEX IF NOT EXISTS idx_semantic_aliases_key ON semantic_aliases(canonical_key)',
)


def init_creative_kb_schema(conn: sqlite3.Connection) -> None:
    conn.execute(CREATE_FRAGMENT_CARDS_TABLE_SQL)
    conn.execute(CREATE_FRAGMENT_CLUSTERS_TABLE_SQL)
    conn.execute(CREATE_FRAGMENT_CARDS_FTS_SQL)
    conn.execute(CREATE_SEMANTIC_ALIASES_TABLE_SQL)
    for statement in CREATIVE_KB_INDEX_STATEMENTS:
        conn.execute(statement)

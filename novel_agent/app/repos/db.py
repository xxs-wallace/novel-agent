from __future__ import annotations

import json
import sqlite3
from pathlib import Path


class NovelAgentDB:
    def __init__(self, db_path: Path) -> None:
        self.db_path = db_path

    def connect(self) -> sqlite3.Connection:
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        conn = sqlite3.connect(str(self.db_path))
        conn.row_factory = sqlite3.Row
        conn.execute('PRAGMA foreign_keys=ON')
        conn.execute('PRAGMA journal_mode=WAL')
        conn.execute('PRAGMA synchronous=NORMAL')
        return conn

    def init_schema(self, conn: sqlite3.Connection) -> None:
        conn.execute(
            '''
            CREATE TABLE IF NOT EXISTS documents (
                doc_id INTEGER PRIMARY KEY AUTOINCREMENT,
                path TEXT NOT NULL DEFAULT '',
                scope TEXT NOT NULL DEFAULT '',
                title TEXT,
                content TEXT NOT NULL,
                mtime REAL NOT NULL DEFAULT 0,
                size INTEGER NOT NULL DEFAULT 0,
                content_sha256 TEXT NOT NULL DEFAULT '',
                book_id TEXT NOT NULL DEFAULT '',
                source_path TEXT NOT NULL DEFAULT '',
                source_file_name TEXT NOT NULL DEFAULT '',
                source_start_offset INTEGER NOT NULL DEFAULT 0,
                source_end_offset INTEGER NOT NULL DEFAULT 0,
                source_batch_no INTEGER NOT NULL DEFAULT 0,
                document_title TEXT NOT NULL DEFAULT '',
                document_title_index INTEGER NOT NULL DEFAULT 0,
                inferred_chapter_no INTEGER,
                content_chars INTEGER NOT NULL DEFAULT 0,
                character_keywords_json TEXT NOT NULL DEFAULT '[]',
                content_tags_csv TEXT NOT NULL DEFAULT '',
                segmentation_notes TEXT,
                boundary_candidate_id TEXT NOT NULL DEFAULT '',
                raw_heading TEXT NOT NULL DEFAULT '',
                normalized_heading TEXT NOT NULL DEFAULT '',
                boundary_confidence REAL NOT NULL DEFAULT 0,
                boundary_status TEXT NOT NULL DEFAULT 'uncertain',
                ingestion_run_id TEXT NOT NULL DEFAULT '',
                created_at TEXT NOT NULL DEFAULT '',
                updated_at TEXT NOT NULL DEFAULT ''
            )
            '''
        )
        self._ensure_documents_columns(conn)
        self._ensure_documents_fts(conn)
        conn.execute(
            '''
            CREATE TABLE IF NOT EXISTS chapters (
                chapter_id INTEGER PRIMARY KEY AUTOINCREMENT,
                book_id TEXT NOT NULL,
                document_title_index INTEGER NOT NULL,
                chapter_title TEXT NOT NULL,
                source_doc_start_id INTEGER NOT NULL,
                source_doc_end_id INTEGER NOT NULL,
                source_doc_count INTEGER NOT NULL,
                source_total_chars INTEGER NOT NULL,
                summary_intermediate_json TEXT NOT NULL DEFAULT '[]',
                summary_md TEXT NOT NULL DEFAULT '',
                summary_short TEXT,
                summary_status TEXT NOT NULL DEFAULT 'provisional',
                summary_evidence_window TEXT NOT NULL DEFAULT '',
                summary_target_range TEXT NOT NULL DEFAULT '',
                importance_score INTEGER NOT NULL DEFAULT 0,
                importance_reason TEXT,
                related_chapters_json TEXT NOT NULL DEFAULT '[]',
                mentioned_characters_json TEXT NOT NULL DEFAULT '[]',
                world_update_json TEXT NOT NULL DEFAULT '{}',
                outline_update_json TEXT NOT NULL DEFAULT '{}',
                outline_status TEXT NOT NULL DEFAULT 'provisional',
                outline_evidence_window TEXT NOT NULL DEFAULT '',
                outline_target_range TEXT NOT NULL DEFAULT '',
                close_read_run_id TEXT NOT NULL DEFAULT '',
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                UNIQUE(book_id, document_title_index)
            )
            '''
        )
        self._ensure_chapters_columns(conn)
        conn.execute(
            '''
            CREATE TABLE IF NOT EXISTS character_profiles (
                character_id INTEGER PRIMARY KEY AUTOINCREMENT,
                book_id TEXT NOT NULL,
                canonical_name TEXT NOT NULL,
                aliases_json TEXT NOT NULL DEFAULT '[]',
                profile_summary_md TEXT NOT NULL DEFAULT '',
                speaking_character_status TEXT NOT NULL DEFAULT 'unknown',
                personhood_evidence_summary TEXT NOT NULL DEFAULT '',
                evidence_level TEXT NOT NULL DEFAULT 'inferred',
                personality_json TEXT NOT NULL DEFAULT '[]',
                occupations_json TEXT NOT NULL DEFAULT '[]',
                age_timeline_json TEXT NOT NULL DEFAULT '[]',
                abilities_json TEXT NOT NULL DEFAULT '[]',
                recent_activity_json TEXT NOT NULL DEFAULT '[]',
                relationships_json TEXT NOT NULL DEFAULT '[]',
                story_events_json TEXT NOT NULL DEFAULT '[]',
                chapter_indexes_json TEXT NOT NULL DEFAULT '[]',
                first_seen_doc_id INTEGER,
                last_seen_doc_id INTEGER,
                first_seen_title_index INTEGER,
                last_seen_title_index INTEGER,
                importance_score INTEGER NOT NULL DEFAULT 0,
                profile_version INTEGER NOT NULL DEFAULT 1,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                UNIQUE(book_id, canonical_name)
            )
            '''
        )
        conn.execute(
            '''
            CREATE TABLE IF NOT EXISTS reading_progress (
                progress_id INTEGER PRIMARY KEY AUTOINCREMENT,
                book_id TEXT NOT NULL,
                agent_stage TEXT NOT NULL,
                current_doc_id INTEGER,
                current_document_title_index INTEGER,
                current_source_path TEXT,
                current_source_offset INTEGER,
                last_completed_doc_id INTEGER,
                last_completed_title_index INTEGER,
                last_completed_chapter_id INTEGER,
                status_json TEXT NOT NULL DEFAULT '{}',
                checkpoint_token TEXT,
                updated_at TEXT NOT NULL,
                UNIQUE(book_id, agent_stage)
            )
            '''
        )
        conn.execute(
            '''
            CREATE TABLE IF NOT EXISTS book_assets (
                book_id TEXT PRIMARY KEY,
                source_root TEXT NOT NULL,
                world_markdown_path TEXT NOT NULL,
                world_summary_path TEXT NOT NULL,
                outline_markdown_path TEXT NOT NULL,
                toc_markdown TEXT NOT NULL DEFAULT '',
                toc_source_path TEXT NOT NULL DEFAULT '',
                debug_export_path TEXT,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            )
            '''
        )
        conn.execute(
            '''
            CREATE TABLE IF NOT EXISTS narrative_memory_pages (
                page_id TEXT PRIMARY KEY,
                book_id TEXT NOT NULL,
                page_type TEXT NOT NULL,
                summary TEXT NOT NULL DEFAULT '',
                child_refs_json TEXT NOT NULL DEFAULT '[]',
                source_doc_ids_json TEXT NOT NULL DEFAULT '[]',
                source_doc_range TEXT NOT NULL DEFAULT '',
                status TEXT NOT NULL DEFAULT 'provisional',
                metadata_json TEXT NOT NULL DEFAULT '{}',
                updated_at TEXT NOT NULL DEFAULT ''
            )
            '''
        )
        conn.execute(
            '''
            CREATE TABLE IF NOT EXISTS character_identity_merge_candidates (
                candidate_id TEXT PRIMARY KEY,
                book_id TEXT NOT NULL,
                status TEXT NOT NULL,
                gate_level TEXT NOT NULL,
                recommended_action TEXT NOT NULL,
                same_person_score INTEGER NOT NULL DEFAULT 0,
                confidence REAL NOT NULL DEFAULT 0,
                reason TEXT NOT NULL DEFAULT '',
                evidence_summary TEXT NOT NULL DEFAULT '',
                left_character_id INTEGER,
                left_name TEXT NOT NULL DEFAULT '',
                right_character_id INTEGER,
                right_name TEXT NOT NULL DEFAULT '',
                survivor_canonical_name TEXT NOT NULL DEFAULT '',
                aliases_to_keep_json TEXT NOT NULL DEFAULT '[]',
                source_doc_ids_json TEXT NOT NULL DEFAULT '[]',
                source_title_indexes_json TEXT NOT NULL DEFAULT '[]',
                outline_segment_ids_json TEXT NOT NULL DEFAULT '[]',
                decision_json TEXT NOT NULL DEFAULT '{}',
                created_at TEXT NOT NULL DEFAULT '',
                updated_at TEXT NOT NULL DEFAULT '',
                resolved_at TEXT NOT NULL DEFAULT ''
            )
            '''
        )
        self._ensure_book_assets_columns(conn)
        self._ensure_character_profiles_columns(conn)
        conn.execute('CREATE INDEX IF NOT EXISTS idx_documents_book_title_index ON documents(book_id, document_title_index, doc_id)')
        conn.execute('CREATE INDEX IF NOT EXISTS idx_documents_path ON documents(path)')
        conn.execute('CREATE INDEX IF NOT EXISTS idx_chapters_book_title_index ON chapters(book_id, document_title_index)')
        conn.execute('CREATE INDEX IF NOT EXISTS idx_character_profiles_book_name ON character_profiles(book_id, canonical_name)')
        conn.execute('CREATE INDEX IF NOT EXISTS idx_reading_progress_stage ON reading_progress(book_id, agent_stage)')
        conn.execute('CREATE INDEX IF NOT EXISTS idx_narrative_memory_pages_book_type ON narrative_memory_pages(book_id, page_type)')
        conn.execute('CREATE INDEX IF NOT EXISTS idx_identity_merge_candidates_book_status ON character_identity_merge_candidates(book_id, status)')

    def _ensure_documents_columns(self, conn: sqlite3.Connection) -> None:
        columns = {row[1] for row in conn.execute("PRAGMA table_info(documents)").fetchall()}
        additions = {
            "content_tags_csv": "TEXT NOT NULL DEFAULT ''",
            "boundary_candidate_id": "TEXT NOT NULL DEFAULT ''",
            "raw_heading": "TEXT NOT NULL DEFAULT ''",
            "normalized_heading": "TEXT NOT NULL DEFAULT ''",
            "boundary_confidence": "REAL NOT NULL DEFAULT 0",
            "boundary_status": "TEXT NOT NULL DEFAULT 'uncertain'",
        }
        for column, ddl in additions.items():
            if column not in columns:
                conn.execute(f"ALTER TABLE documents ADD COLUMN {column} {ddl}")

    def _ensure_book_assets_columns(self, conn: sqlite3.Connection) -> None:
        columns = {row[1] for row in conn.execute("PRAGMA table_info(book_assets)").fetchall()}
        if "toc_markdown" not in columns:
            conn.execute("ALTER TABLE book_assets ADD COLUMN toc_markdown TEXT NOT NULL DEFAULT ''")
        if "toc_source_path" not in columns:
            conn.execute("ALTER TABLE book_assets ADD COLUMN toc_source_path TEXT NOT NULL DEFAULT ''")

    def _ensure_chapters_columns(self, conn: sqlite3.Connection) -> None:
        columns = {row[1] for row in conn.execute("PRAGMA table_info(chapters)").fetchall()}
        additions = {
            "summary_status": "TEXT NOT NULL DEFAULT 'provisional'",
            "summary_evidence_window": "TEXT NOT NULL DEFAULT ''",
            "summary_target_range": "TEXT NOT NULL DEFAULT ''",
            "outline_status": "TEXT NOT NULL DEFAULT 'provisional'",
            "outline_evidence_window": "TEXT NOT NULL DEFAULT ''",
            "outline_target_range": "TEXT NOT NULL DEFAULT ''",
        }
        for column, ddl in additions.items():
            if column not in columns:
                conn.execute(f"ALTER TABLE chapters ADD COLUMN {column} {ddl}")

    def _ensure_character_profiles_columns(self, conn: sqlite3.Connection) -> None:
        columns = {row[1] for row in conn.execute("PRAGMA table_info(character_profiles)").fetchall()}
        if "mentioned_doc_ids_json" not in columns:
            conn.execute("ALTER TABLE character_profiles ADD COLUMN mentioned_doc_ids_json TEXT NOT NULL DEFAULT '[]'")
        if "speaking_doc_ids_json" not in columns:
            conn.execute("ALTER TABLE character_profiles ADD COLUMN speaking_doc_ids_json TEXT NOT NULL DEFAULT '[]'")
        if "speaking_character_status" not in columns:
            conn.execute("ALTER TABLE character_profiles ADD COLUMN speaking_character_status TEXT NOT NULL DEFAULT 'unknown'")
        if "personhood_evidence_summary" not in columns:
            conn.execute("ALTER TABLE character_profiles ADD COLUMN personhood_evidence_summary TEXT NOT NULL DEFAULT ''")
        if "evidence_level" not in columns:
            conn.execute("ALTER TABLE character_profiles ADD COLUMN evidence_level TEXT NOT NULL DEFAULT 'inferred'")
        if "story_events_json" not in columns:
            conn.execute("ALTER TABLE character_profiles ADD COLUMN story_events_json TEXT NOT NULL DEFAULT '[]'")
        if "profile_brief_json" not in columns:
            conn.execute("ALTER TABLE character_profiles ADD COLUMN profile_brief_json TEXT NOT NULL DEFAULT '{}'")
        if "profile_brief_status" not in columns:
            conn.execute("ALTER TABLE character_profiles ADD COLUMN profile_brief_status TEXT NOT NULL DEFAULT 'missing'")
        if "profile_brief_version" not in columns:
            conn.execute("ALTER TABLE character_profiles ADD COLUMN profile_brief_version INTEGER NOT NULL DEFAULT 0")
        if "brief_compacted_until_doc_id" not in columns:
            conn.execute("ALTER TABLE character_profiles ADD COLUMN brief_compacted_until_doc_id INTEGER")
        if "brief_compacted_until_segment_id" not in columns:
            conn.execute("ALTER TABLE character_profiles ADD COLUMN brief_compacted_until_segment_id TEXT NOT NULL DEFAULT ''")
        if "profile_brief_updated_at" not in columns:
            conn.execute("ALTER TABLE character_profiles ADD COLUMN profile_brief_updated_at TEXT NOT NULL DEFAULT ''")

    def _ensure_documents_fts(self, conn: sqlite3.Connection) -> None:
        table_exists = conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='documents_fts'"
        ).fetchone()
        recreate = False
        if table_exists:
            fts_columns = {row[1] for row in conn.execute("PRAGMA table_info(documents_fts)").fetchall()}
            recreate = "content_tags" not in fts_columns
        if recreate:
            existing_rows = conn.execute(
                "SELECT doc_id, content, path, scope, document_title, character_keywords_json, content_tags_csv FROM documents ORDER BY doc_id"
            ).fetchall()
            conn.execute("DROP TABLE documents_fts")
            self._create_documents_fts(conn)
            for row in existing_rows:
                character_keywords = " ".join(json.loads(row["character_keywords_json"] or "[]"))
                content_tags = str(row["content_tags_csv"] or "").replace(",", " ")
                conn.execute(
                    "INSERT INTO documents_fts(rowid, content, path, scope, document_title, character_keywords, content_tags) VALUES (?, ?, ?, ?, ?, ?, ?)",
                    (
                        int(row["doc_id"]),
                        row["content"],
                        row["path"],
                        row["scope"],
                        row["document_title"],
                        character_keywords,
                        content_tags,
                    ),
                )
            return
        if not table_exists:
            self._create_documents_fts(conn)

    def _create_documents_fts(self, conn: sqlite3.Connection) -> None:
        conn.execute(
            '''
            CREATE VIRTUAL TABLE IF NOT EXISTS documents_fts USING fts5(
                content,
                path UNINDEXED,
                scope UNINDEXED,
                document_title,
                character_keywords,
                content_tags,
                tokenize='unicode61'
            )
            '''
        )

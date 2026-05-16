from __future__ import annotations

import json
from pathlib import Path

from novel_agent.app.constants import DEFAULT_CLOSE_READING_STAGE
from novel_agent.app.llm import JsonModelClient
from novel_agent.app.repos.chapters_repo import ChaptersRepo
from novel_agent.app.repos.db import NovelAgentDB
from novel_agent.app.repos.documents_repo import DocumentsRepo
from novel_agent.app.repos.reading_progress_repo import ReadingProgressRepo
from novel_agent.app.schemas.config_schema import CloseReadAgentConfig, CloseReadRuntimeConfig
from novel_agent.app.services.character_memory_repair_service import CharacterMemoryRepairService


def test_character_memory_repair_backfills_profiles_without_rewriting_summary(tmp_path: Path, monkeypatch) -> None:
    db_path = tmp_path / ".indexes" / "book.db"
    db = NovelAgentDB(db_path)
    with db.connect() as conn:
        db.init_schema(conn)
        docs = DocumentsRepo()
        doc_1 = docs.insert_document(
            conn,
            {
                "book_id": "book",
                "path": "source.txt",
                "scope": "chapter",
                "title": "第一章",
                "document_title": "第一章",
                "document_title_index": 1,
                "content": "沈青说今晚继续调查，顾迟点头回应。",
                "content_chars": len("沈青说今晚继续调查，顾迟点头回应。"),
                "source_path": "source.txt",
                "source_file_name": "source.txt",
                "source_start_offset": 0,
                "source_end_offset": 20,
                "created_at": "2026-05-15T00:00:00+00:00",
                "updated_at": "2026-05-15T00:00:00+00:00",
            },
        )
        doc_2 = docs.insert_document(
            conn,
            {
                "book_id": "book",
                "path": "source.txt",
                "scope": "chapter",
                "title": "第一章",
                "document_title": "第一章",
                "document_title_index": 1,
                "content": "林晚发现旧案线索，沈青随后赶到。",
                "content_chars": len("林晚发现旧案线索，沈青随后赶到。"),
                "source_path": "source.txt",
                "source_file_name": "source.txt",
                "source_start_offset": 20,
                "source_end_offset": 42,
                "created_at": "2026-05-15T00:00:00+00:00",
                "updated_at": "2026-05-15T00:00:00+00:00",
            },
        )
        ChaptersRepo().upsert(
            conn,
            {
                "book_id": "book",
                "document_title_index": 1,
                "chapter_title": "第一章",
                "source_doc_start_id": doc_1,
                "source_doc_end_id": doc_2,
                "source_doc_count": 2,
                "source_total_chars": 42,
                "summary_intermediate": ["## 剧情事件链\n沈青、顾迟和林晚继续调查旧案。"],
                "summary_md": "",
                "summary_short": "三人继续调查旧案。",
                "importance_score": 60,
                "importance_reason": "主线推进。",
                "mentioned_characters": [],
                "world_update": {},
                "outline_update": {},
                "created_at": "2026-05-15T00:00:00+00:00",
                "updated_at": "2026-05-15T00:00:00+00:00",
            },
        )
        ReadingProgressRepo().upsert(
            conn,
            {
                "book_id": "book",
                "agent_stage": DEFAULT_CLOSE_READING_STAGE,
                "last_completed_doc_id": doc_2,
                "last_completed_title_index": 1,
                "checkpoint_token": f"1:{doc_2}",
                "updated_at": "2026-05-15T00:00:00+00:00",
            },
        )
        conn.commit()

    def fake_generate_json(
        self,
        *,
        system_prompt: str,
        user_prompt: str,
        fallback_factory,
        use_fallback_on_error: bool = False,
    ):
        _ = self, use_fallback_on_error
        if "Character Evidence Agent" in system_prompt:
            if "沈青说今晚继续调查" in user_prompt:
                return (
                    {
                        "doc_id": doc_1,
                        "document_title_index": 1,
                        "request_full_roster": False,
                        "request_full_roster_reason": "",
                        "characters": [
                            {
                                "canonical_name": "沈青",
                                "aliases": [],
                                "is_speaking_character": True,
                                "speaking_evidence": "沈青说今晚继续调查。",
                                "personhood_evidence": "沈青发言并推进调查。",
                                "activity_or_state_evidence": "沈青继续调查旧案。",
                                "relationship_evidence": "",
                                "source_doc_ids": [doc_1],
                                "source_title_indexes": [1],
                                "candidate_type": "character",
                                "confidence": 0.9,
                                "uncertainty_reason": "",
                            }
                        ],
                    },
                    "",
                )
            return (
                {
                    "doc_id": doc_2,
                    "document_title_index": 1,
                    "request_full_roster": False,
                    "request_full_roster_reason": "",
                    "characters": [
                        {
                            "canonical_name": "沈青",
                            "aliases": [],
                            "is_speaking_character": False,
                            "speaking_evidence": "",
                            "personhood_evidence": "沈青随后赶到。",
                            "activity_or_state_evidence": "沈青赶到现场。",
                            "relationship_evidence": "",
                            "source_doc_ids": [doc_2],
                            "source_title_indexes": [1],
                            "candidate_type": "character",
                            "confidence": 0.88,
                            "uncertainty_reason": "",
                        }
                    ],
                },
                "",
            )
        if "Character Reduce Agent" in system_prompt:
            return fallback_factory(), ""
        return fallback_factory(), ""

    monkeypatch.setattr(JsonModelClient, "generate_json", fake_generate_json)

    result = CharacterMemoryRepairService(
        repo_root=tmp_path,
        db_path=db_path,
        config=CloseReadAgentConfig(
            book_id="book",
            runtime=CloseReadRuntimeConfig(dry_run=True, document_chars_budget=1_000),
        ),
    ).run()

    with db.connect() as conn:
        chapter = ChaptersRepo().get(conn, book_id="book", document_title_index=1)
        profiles = conn.execute("SELECT canonical_name FROM character_profiles WHERE book_id = ? ORDER BY canonical_name", ("book",)).fetchall()
        doc_keywords = [
            json.loads(row["character_keywords_json"])
            for row in conn.execute("SELECT character_keywords_json FROM documents ORDER BY doc_id").fetchall()
        ]

    assert result.processed_documents == 2
    assert chapter is not None
    assert json.loads(chapter["summary_intermediate_json"]) == ["## 剧情事件链\n沈青、顾迟和林晚继续调查旧案。"]
    assert str(chapter["summary_md"] or "") == ""
    assert {row["canonical_name"] for row in profiles} >= {"沈青"}
    assert any("沈青" in keywords for keywords in doc_keywords)


def test_character_memory_repair_target_documents_can_start_from_title_index(tmp_path: Path) -> None:
    db_path = tmp_path / ".indexes" / "book.db"
    db = NovelAgentDB(db_path)
    with db.connect() as conn:
        db.init_schema(conn)
        docs = DocumentsRepo()
        docs.insert_document(
            conn,
            {
                "book_id": "book",
                "path": "source.txt",
                "scope": "chapter",
                "title": "第二十七章",
                "document_title": "第二十七章",
                "document_title_index": 27,
                "content": "林初整理线索。",
                "content_chars": len("林初整理线索。"),
                "source_path": "source.txt",
                "source_file_name": "source.txt",
                "source_start_offset": 0,
                "source_end_offset": 10,
                "created_at": "2026-05-15T00:00:00+00:00",
                "updated_at": "2026-05-15T00:00:00+00:00",
            },
        )
        doc_28 = docs.insert_document(
            conn,
            {
                "book_id": "book",
                "path": "source.txt",
                "scope": "chapter",
                "title": "第二十八章",
                "document_title": "第二十八章",
                "document_title_index": 28,
                "content": "周衡重新出现。",
                "content_chars": len("周衡重新出现。"),
                "source_path": "source.txt",
                "source_file_name": "source.txt",
                "source_start_offset": 10,
                "source_end_offset": 20,
                "created_at": "2026-05-15T00:00:00+00:00",
                "updated_at": "2026-05-15T00:00:00+00:00",
            },
        )
        selected = CharacterMemoryRepairService(
            repo_root=tmp_path,
            db_path=db_path,
            config=CloseReadAgentConfig(book_id="book"),
        )._target_documents(  # noqa: SLF001
            conn,
            documents_repo=docs,
            min_title_index=28,
            max_doc_id=doc_28,
        )

    assert [doc.document_title_index for doc in selected] == [28]

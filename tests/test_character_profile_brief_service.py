from __future__ import annotations

import json
from pathlib import Path

from novel_agent.app.repos.character_profiles_repo import CharacterProfilesRepo
from novel_agent.app.repos.db import NovelAgentDB
from novel_agent.app.repos.documents_repo import DocumentsRepo
from novel_agent.app.services.character_profile_brief_service import CharacterProfileBriefService


class FakeBriefModel:
    def __init__(self, payloads: list[dict[str, object]]) -> None:
        self.payloads = list(payloads)
        self.calls: list[dict[str, str]] = []

    def generate_json(self, **kwargs: object) -> tuple[dict[str, object], str]:
        self.calls.append(
            {
                "system_prompt": str(kwargs.get("system_prompt") or ""),
                "user_prompt": str(kwargs.get("user_prompt") or ""),
            }
        )
        if not self.payloads:
            raise AssertionError("unexpected model call")
        payload = self.payloads.pop(0)
        return payload, json.dumps(payload, ensure_ascii=False)


def _open_db(tmp_path: Path):
    db = NovelAgentDB(tmp_path / "brief.db")
    conn = db.connect()
    db.init_schema(conn)
    return conn


def _insert_profile(conn, *, book_id: str = "book", name: str = "林澈") -> int:
    return CharacterProfilesRepo().upsert(
        conn,
        {
            "book_id": book_id,
            "canonical_name": name,
            "aliases": ["小林"],
            "profile_summary_md": "林澈是调查队成员，近期开始怀疑旧案真相。",
            "personality": [{"value": "谨慎", "field_type": "inference", "evidence_level": "inferred"}],
            "occupations": [],
            "age_timeline": [],
            "abilities": [],
            "recent_activity": [{"value": "发现旧案线索", "field_type": "fact", "evidence_level": "explicit", "source_chapter_indexes": [1], "source_doc_ids": [1]}],
            "relationships": [],
            "story_events": [
                {
                    "event_id": "event-1",
                    "label": "旧案线索",
                    "summary": "林澈发现旧案线索。",
                    "outline_segment_id": "outline-segment:chapter-1:docs-1",
                    "source_doc_ids": [1],
                    "source_doc_range": "1",
                    "participants": ["林澈"],
                }
            ],
            "chapter_indexes": [1],
            "mentioned_doc_ids": [1],
            "speaking_doc_ids": [],
            "first_seen_doc_id": 1,
            "last_seen_doc_id": 1,
            "first_seen_title_index": 1,
            "last_seen_title_index": 1,
            "importance_score": 1,
            "profile_version": 1,
            "created_at": "now",
            "updated_at": "now",
        },
    )


def test_profile_brief_bootstrap_creates_persistent_brief(tmp_path: Path) -> None:
    conn = _open_db(tmp_path)
    character_id = _insert_profile(conn)
    row = CharacterProfilesRepo().get_by_id(conn, book_id="book", character_id=character_id)
    model = FakeBriefModel(
        [
            {
                "profile_brief": {
                    "identity": {"character_id": str(character_id), "canonical_name": "林澈", "aliases": ["小林"]},
                    "current_state": "正在追查旧案真相。",
                    "stable_traits": ["谨慎"],
                    "abilities_or_limits": [],
                    "relationship_digest": [],
                    "open_questions": ["旧案真相"],
                    "latest_major_change": {"summary": "发现旧案线索", "source_refs": [{"type": "story_event", "id": "event-1"}]},
                    "source_refs": [{"type": "story_event", "id": "event-1"}],
                    "compacted_until": {"doc_id": 1, "outline_segment_id": "outline-segment:chapter-1:docs-1"},
                },
                "compact_notes": "bootstrap",
            }
        ]
    )

    payload = CharacterProfileBriefService().bootstrap_from_row(model_client=model, row=row)

    assert payload["profile_brief_status"] == "ready"
    assert payload["profile_brief"]["current_state"] == "正在追查旧案真相。"
    assert "Profile Brief Bootstrap" in model.calls[0]["system_prompt"]


def test_profile_brief_compact_loop_expands_requested_story_event_and_source_doc(tmp_path: Path) -> None:
    conn = _open_db(tmp_path)
    character_id = _insert_profile(conn)
    repo = CharacterProfilesRepo()
    repo.update_profile_brief(
        conn,
        book_id="book",
        character_id=character_id,
        profile_brief={
            "identity": {"character_id": str(character_id), "canonical_name": "林澈", "aliases": ["小林"]},
            "current_state": "正在追查旧案。",
            "stable_traits": ["谨慎"],
            "abilities_or_limits": [],
            "relationship_digest": [],
            "open_questions": ["旧案真相"],
            "latest_major_change": {},
            "source_refs": [],
            "compacted_until": {"doc_id": 1, "outline_segment_id": ""},
        },
        profile_brief_status="ready",
        compacted_until_doc_id=1,
        updated_at="now",
    )
    DocumentsRepo().insert_document(
        conn,
        {
            "path": "001.md",
            "scope": "novel",
            "title": "第一章",
            "content": "林澈发现旧案线索，并确认线索来自失踪者本人。",
            "mtime": 0,
            "size": 24,
            "content_sha256": "sha",
            "book_id": "book",
            "source_path": "001.md",
            "source_file_name": "001.md",
            "source_start_offset": 0,
            "source_end_offset": 24,
            "source_batch_no": 1,
            "document_title": "第一章",
            "document_title_index": 1,
            "inferred_chapter_no": 1,
            "content_chars": 24,
            "character_keywords": ["林澈"],
            "content_tags": [],
            "segmentation_notes": "",
            "ingestion_run_id": "seed",
            "created_at": "now",
            "updated_at": "now",
        },
    )
    row = repo.get_by_id(conn, book_id="book", character_id=character_id)
    model = FakeBriefModel(
        [
            {
                "action": "request_context",
                "requests": [
                    {"kind": "story_event", "selector": {"event_id": "event-1"}, "reason": "确认旧案线索"},
                    {"kind": "source_doc", "selector": {"doc_ids": [1]}, "reason": "需要原文细节"},
                ],
            },
            {
                "action": "finalize",
                "profile_brief": {
                    "identity": {"character_id": str(character_id), "canonical_name": "林澈", "aliases": ["小林"]},
                    "current_state": "确认旧案线索来自失踪者本人，追查方向发生重大变化。",
                    "stable_traits": ["谨慎"],
                    "abilities_or_limits": [],
                    "relationship_digest": [],
                    "open_questions": [],
                    "latest_major_change": {"summary": "旧案线索被确认", "source_refs": [{"type": "document", "doc_id": 1}]},
                    "source_refs": [{"type": "story_event", "id": "event-1"}, {"type": "document", "doc_id": 1}],
                    "compacted_until": {"doc_id": 1, "outline_segment_id": "outline-segment:chapter-1:docs-1"},
                },
                "consumed_recent_activity_refs": ["event-1"],
                "compact_notes": "major clue",
            },
        ]
    )

    payload = CharacterProfileBriefService(max_compact_rounds=2).compact_loop(
        conn=conn,
        model_client=model,
        documents_repo=DocumentsRepo(),
        row=row,
        current_update={"profile_brief_compact": {"needed": True, "reason": "旧案真相变化"}},
        chapter_summary={"chapter_summary_short": "林澈确认线索来源。"},
        current_outline_segment={"outline_segment_id": "outline-segment:chapter-1:docs-1"},
    )

    assert payload["profile_brief"]["current_state"].startswith("确认旧案线索")
    assert "requested_context" in model.calls[1]["user_prompt"]
    assert "失踪者本人" in model.calls[1]["user_prompt"]

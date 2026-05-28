from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

from novel_agent.app.repos.chapters_repo import ChaptersRepo
from novel_agent.app.repos.db import NovelAgentDB
from novel_agent.app.schemas.narrative_memory_schema import MemoryQueryBudget
from novel_agent.app.services.narrative_memory_query_service import NarrativeMemoryQueryService
from novel_agent.app.services.outline_segment_index_service import OutlineSegmentIndexService


class _RootSummaryModel:
    settings = SimpleNamespace(dry_run=False)

    def __init__(self) -> None:
        self.calls: list[dict[str, str]] = []

    def generate_json(self, *, system_prompt, user_prompt, fallback_factory, use_fallback_on_error=False):  # type: ignore[no-untyped-def]
        _ = fallback_factory, use_fallback_on_error
        self.calls.append({"system_prompt": system_prompt, "user_prompt": user_prompt})
        assert "Outline Root Summary Agent" in system_prompt
        assert "segments" in user_prompt
        return (
            {
                "root_summary": "调查员接到新线索并与同伴证词汇合，调查方向从前夜行动转向核心冲突。",
                "compression_notes": "保留线索、协作和方向变化。",
            },
            "",
        )


def _insert_documents(conn, *, book_id: str = "book") -> None:
    conn.execute(
        """
        INSERT INTO documents(doc_id, book_id, path, scope, content, document_title, document_title_index, content_chars)
        VALUES
            (1, ?, '/tmp/source.txt', 'chapter', '调查员接到新线索。', '第一章', 1, 10),
            (2, ?, '/tmp/source.txt', 'chapter', '同伴补充关键证词。', '第二章', 2, 10)
        """,
        (book_id, book_id),
    )


def _upsert_chapter(conn, *, book_id: str, index: int, summary: str, doc_id: int) -> None:
    ChaptersRepo().upsert(
        conn,
        {
            "book_id": book_id,
            "document_title_index": index,
            "chapter_title": f"第{index}章",
            "source_doc_start_id": doc_id,
            "source_doc_end_id": doc_id,
            "source_doc_count": 1,
            "source_total_chars": 1000,
            "summary_intermediate": [],
            "summary_md": summary,
            "summary_short": summary,
            "summary_status": "committed",
            "summary_evidence_window": f"{index}-{index}",
            "summary_target_range": f"{index}-{index}",
            "importance_score": 80,
            "importance_reason": "主线推进",
            "related_chapters": [],
            "mentioned_characters": ["调查员"],
            "world_update": {},
            "outline_update": {
                "chapter_line": f"[{index}] 第{index}章: {summary}",
                "outline_segment_id": f"outline-segment:chapter-{index}:docs-{doc_id}",
                "outline_segment": summary,
                "source_doc_ids": [doc_id],
                "source_doc_range": str(doc_id),
                "source_title_indexes": [index],
                "status": "committed",
            },
            "outline_status": "committed",
            "outline_evidence_window": f"{index}-{index}",
            "outline_target_range": f"{index}-{index}",
            "close_read_run_id": "run",
            "created_at": "2026-01-01T00:00:00Z",
            "updated_at": "2026-01-01T00:00:00Z",
        },
    )


def test_outline_segment_index_artifact_has_segments_and_roots_without_event_lists(tmp_path: Path) -> None:
    db = NovelAgentDB(tmp_path / "memory.db")
    with db.connect() as conn:
        db.init_schema(conn)
        _insert_documents(conn)
        _upsert_chapter(conn, book_id="book", index=1, summary="调查员接到新线索，重新梳理前夜行动。", doc_id=1)
        _upsert_chapter(conn, book_id="book", index=2, summary="同伴补充关键证词，调查方向转为核心冲突。", doc_id=2)
        conn.commit()

        model = _RootSummaryModel()
        path = OutlineSegmentIndexService(repo_root=tmp_path, model_client=model).refresh(conn, book_id="book")

    payload = json.loads(path.read_text(encoding="utf-8"))
    serialized = json.dumps(payload, ensure_ascii=False)
    assert len(payload["segments"]) == 2
    assert payload["roots"][0]["summary"] == "调查员接到新线索并与同伴证词汇合，调查方向从前夜行动转向核心冲突。"
    assert payload["roots"][0]["outline_segment_ids"] == [
        "outline-segment:chapter-1:docs-1",
        "outline-segment:chapter-2:docs-2",
    ]
    assert "timeline_events" not in serialized
    assert "event_ids" not in serialized


def test_memory_query_drills_from_outline_root_to_documents(tmp_path: Path) -> None:
    db = NovelAgentDB(tmp_path / "memory-query.db")
    with db.connect() as conn:
        db.init_schema(conn)
        _insert_documents(conn)
        _upsert_chapter(conn, book_id="book", index=1, summary="调查员接到新线索，重新梳理前夜行动。", doc_id=1)
        _upsert_chapter(conn, book_id="book", index=2, summary="同伴补充关键证词，调查方向转为核心冲突。", doc_id=2)
        conn.commit()
        OutlineSegmentIndexService(repo_root=tmp_path, model_client=_RootSummaryModel()).refresh(conn, book_id="book")

        service = NarrativeMemoryQueryService(repo_root=tmp_path)
        root = service.root_scan(
            conn,
            book_id="book",
            query="调查员如何确认核心冲突",
            budget=MemoryQueryBudget(max_root_candidates=4, max_child_candidates=4),
        )
        segments = service.drill_down(
            conn,
            book_id="book",
            state=root,
            selected_ids=[root.current_candidates[0]["id"]],
            query_suffix="选择相关剧情段",
            selection_reason="root covers the investigation",
            confidence=0.8,
        )
        chapters = service.drill_down(
            conn,
            book_id="book",
            state=segments,
            selected_ids=[segments.current_candidates[0]["id"]],
            query_suffix="展开章节摘要",
            selection_reason="segment mentions investigation",
            confidence=0.8,
        )
        documents = service.drill_down(
            conn,
            book_id="book",
            state=chapters,
            selected_ids=[chapters.current_candidates[0]["id"]],
            query_suffix="查看原文片段",
            selection_reason="chapter has source document",
            confidence=0.8,
        )
        bundle = service.resolve_outline_segment_refs(
            conn,
            book_id="book",
            segment_ids=[segments.current_candidates[0]["id"]],
        )

    assert root.current_level == "outline_root"
    assert root.current_candidates[0]["outline_segment_ids"]
    assert segments.current_level == "outline_segment"
    assert segments.current_candidates[0]["outline_segment_id"].startswith("outline-segment:chapter-")
    assert chapters.current_level == "chapter"
    assert documents.current_level == "document"
    assert bundle.evidence_items[0]["page_type"] == "outline_segment"
    assert bundle.source_doc_ids

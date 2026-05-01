from __future__ import annotations

from pathlib import Path

from novel_agent.app.constants import DEFAULT_CLOSE_READING_STAGE
from novel_agent.app.repos.db import NovelAgentDB
from novel_agent.app.repos.documents_repo import DocumentsRepo
from novel_agent.app.repos.reading_progress_repo import ReadingProgressRepo
from novel_agent.app.runner.close_read_runner import CloseReadRunner
from novel_agent.app.schemas.config_schema import CloseReadAgentConfig, CloseReadRuntimeConfig
from novel_agent.app.services.chapter_assembler_service import ChapterAssemblerService
from novel_agent.app.services.memory_candidate_service import MemoryCandidateService

def test_character_reduce_inputs_group_same_character_in_doc_order() -> None:
    service = MemoryCandidateService()
    reduce_inputs = service.build_character_reduce_inputs(
        prompt_input={
            "book_id": "book",
            "character_profiles": [{"canonical_name": "林澈", "aliases": ["小林"], "profile_summary_md": "旧档案"}],
        },
        summary_payload={"chapter_summary_short": "林澈连续经历两次事件。"},
        evidence_payload={
            "character_evidence_batches": [
                {
                    "character_evidence_batch_id": "book:character-evidence:2",
                    "doc_ids": [2],
                    "document_title_indexes": [1],
                    "characters": [
                        {
                            "canonical_name": "林澈",
                            "aliases": [],
                            "is_speaking_character": False,
                            "personhood_evidence": "被称呼并行动。",
                            "activity_or_state_evidence": "后续进入营地。",
                            "relationship_evidence": "",
                            "candidate_type": "character",
                            "confidence": 0.8,
                        }
                    ],
                },
                {
                    "character_evidence_batch_id": "book:character-evidence:1",
                    "doc_ids": [1],
                    "document_title_indexes": [1],
                    "characters": [
                        {
                            "canonical_name": "林澈",
                            "aliases": [],
                            "is_speaking_character": True,
                            "speaking_evidence": "有明确回应。",
                            "personhood_evidence": "发言并被称呼。",
                            "activity_or_state_evidence": "先收到邀请。",
                            "relationship_evidence": "",
                            "candidate_type": "character",
                            "confidence": 0.9,
                        },
                        {
                            "canonical_name": "广场",
                            "personhood_evidence": "",
                            "candidate_type": "scene",
                            "confidence": 0.2,
                        },
                    ],
                },
            ]
        },
    )

    assert [item["canonical_name"] for item in reduce_inputs] == ["林澈"]
    evidence = reduce_inputs[0]["ordered_character_evidence"]
    assert [item["source_doc_ids"] for item in evidence] == [[1], [2]]
    assert reduce_inputs[0]["existing_profile"]["profile_summary_md"] == "旧档案"


def test_global_memory_input_excludes_documents_and_fallback_uses_world_candidates() -> None:
    service = MemoryCandidateService()
    global_input = service.build_global_memory_input(
        prompt_input={
            "book_id": "book",
            "documents": [{"doc_id": 1, "content": "原文不应进入 global memory"}],
            "world_summary_md": "旧世界观",
        },
        summary_payload={
            "chapter_summary_short": "本章揭示契约规则。",
            "world_signal_score": 80,
            "world_evidence_candidates": [
                {
                    "section": "能力体系",
                    "summary": "法术会受到契约约束。",
                    "evidence_hint": "法术与契约同段出现。",
                    "source_doc_ids": [1],
                    "confidence": 0.8,
                }
            ],
        },
        world_evidence_payload={},
    )

    assert "documents" not in global_input
    assert global_input["global_memory_policy"]["do_not_read_full_documents"] is True
    fallback = service.build_global_memory_fallback_output(
        summary_payload=global_input["chapter_summary"],
        world_evidence_payload=global_input["world_evidence"],
    )
    assert fallback["world_update"]["should_update"] is True
    assert fallback["world_update"]["changes"][0]["section"] == "能力体系"


def test_world_evidence_trigger_uses_hybrid_threshold(tmp_path: Path) -> None:
    runner = CloseReadRunner(
        repo_root=tmp_path,
        db_path=tmp_path / "novel.db",
        config=CloseReadAgentConfig(
            book_id="book",
            runtime=CloseReadRuntimeConfig(
                dry_run=True,
                world_evidence_signal_threshold=70,
            ),
        ),
    )

    assert runner._should_run_world_evidence(  # noqa: SLF001
        batch=_FakeBatch("普通剧情推进，没有设定词。"),
        summary_payload={"world_signal_score": 20, "world_evidence_candidates": []},
    ) is False
    assert runner._should_run_world_evidence(  # noqa: SLF001
        batch=_FakeBatch("普通剧情推进。"),
        summary_payload={"world_signal_score": 75, "world_evidence_candidates": []},
    ) is True
    assert runner._should_run_world_evidence(  # noqa: SLF001
        batch=_FakeBatch("普通剧情推进。"),
        summary_payload={
            "world_signal_score": 20,
            "world_evidence_candidates": [{"section": "能力体系", "summary": "疑似规则", "confidence": 0.4}],
        },
    ) is True


def test_chapter_assembler_can_prefetch_multiple_close_read_batches(tmp_path: Path) -> None:
    db = NovelAgentDB(tmp_path / "novel.db")
    documents_repo = DocumentsRepo()
    progress_repo = ReadingProgressRepo()
    with db.connect() as conn:
        db.init_schema(conn)
        for index in range(1, 4):
            _insert_document(
                conn,
                book_id="book",
                title_index=index,
                content=f"第{index}章内容，沈青继续调查。",
                offset=index * 100,
            )
        conn.commit()

        assembler = ChapterAssemblerService(
            documents_repo=documents_repo,
            progress_repo=progress_repo,
            document_chars_budget=18,
            progress_stage=DEFAULT_CLOSE_READING_STAGE,
        )
        batches = assembler.load_next_batches(conn, book_id="book", limit=2)

    assert len(batches) == 2
    assert [batch.documents[0].document_title_index for batch in batches] == [1, 2]
    assert [batch.documents[0].doc_id for batch in batches] == [1, 2]


def test_close_read_character_evidence_runs_once_per_document_in_batch(tmp_path: Path) -> None:
    db_path = tmp_path / "novel.db"
    db = NovelAgentDB(db_path)
    with db.connect() as conn:
        db.init_schema(conn)
        for index, name in enumerate(["沈青", "顾迟", "林晚"], start=1):
            _insert_document(
                conn,
                book_id="book",
                title_index=1,
                content=f"{name}说今晚继续调查，其他人点头回应。",
                offset=index * 100,
            )
        conn.commit()

    events: list[dict[str, object]] = []
    runner = CloseReadRunner(
        repo_root=tmp_path,
        db_path=db_path,
        config=CloseReadAgentConfig(
            book_id="book",
            runtime=CloseReadRuntimeConfig(
                dry_run=True,
                export_debug_markdown=False,
                max_chapters=1,
                document_chars_budget=1_000,
                close_read_extraction_window_count=1,
                close_read_extraction_max_workers=4,
            ),
        ),
        progress_callback=events.append,
    )

    result = runner.run()

    evidence_starts = [
        event
        for event in events
        if event.get("agent") == "character_evidence" and event.get("event") == "prompt_start"
    ]
    summary_starts = [
        event
        for event in events
        if event.get("agent") == "chapter_summary" and event.get("event") == "prompt_start"
    ]
    assert result.processed_batches == 1
    assert len(summary_starts) == 1
    assert summary_starts[0]["doc_count"] == 3
    assert len(evidence_starts) == 3
    assert {event["doc_count"] for event in evidence_starts} == {1}


class _FakeDoc:
    doc_id = 1
    document_title_index = 1
    document_title = "第一章"

    def __init__(self, content: str) -> None:
        self.content = content


class _FakeBatch:
    title_indexes = [1]

    def __init__(self, content: str) -> None:
        self.documents = [_FakeDoc(content)]


def _insert_document(conn, *, book_id: str, title_index: int, content: str, offset: int) -> int:
    return DocumentsRepo().insert_document(
        conn,
        {
            "book_id": book_id,
            "path": f"docs/chapter-{title_index}.md",
            "scope": "docs",
            "title": f"第{title_index}章",
            "document_title": f"第{title_index}章",
            "document_title_index": title_index,
            "inferred_chapter_no": title_index,
            "content": content,
            "content_chars": len(content),
            "character_keywords": [],
            "content_tags": [],
            "source_path": "docs/book.md",
            "source_file_name": "book.md",
            "source_start_offset": offset,
            "source_end_offset": offset + len(content),
            "ingestion_run_id": "seed",
            "created_at": "now",
            "updated_at": "now",
        },
    )

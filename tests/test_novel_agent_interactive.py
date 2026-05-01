from __future__ import annotations

from pathlib import Path

from novel_agent.app.constants import DEFAULT_CLOSE_READING_STAGE, DEFAULT_SEGMENTATION_STAGE
from novel_agent.app.repos.db import NovelAgentDB
from novel_agent.app.repos.documents_repo import DocumentsRepo
from novel_agent.app.repos.reading_progress_repo import ReadingProgressRepo
from novel_agent.app.schemas.context_assembly_schema import (
    ChapterContextItem,
    CharacterProfileContextItem,
    ContextAssemblyPayload,
)
from novel_agent.app.schemas.creative_kb_schema import SceneBrief
from novel_agent.app.schemas.orchestration_schema import (
    CreativeKBRetrievalInput,
    ReferenceFragment,
    RetrievalContext,
    WriterInputBundle,
    WriterSource,
)
from novel_agent.app.run_interactive import (
    DEFAULT_PIPELINE_CLOSE_STEP_BATCHES,
    DEFAULT_PIPELINE_SEGMENT_STEP_KB,
    _load_progress_snapshot,
    _kb_to_chars,
    _min_positive,
    _slugify_task_name,
)


def test_slugify_task_name_keeps_meaningful_text() -> None:
    assert _slugify_task_name("龙族 任务-01") == "龙族-任务-01"
    assert _slugify_task_name("  ") == "novel-task"


def test_kb_to_chars_converts_optional_limit() -> None:
    assert _kb_to_chars(50) == 50 * 1024
    assert _kb_to_chars(None) is None


def test_min_positive_handles_optional_values() -> None:
    assert _min_positive(8, 16) == 8
    assert _min_positive(None, 16) == 16
    assert _min_positive(8, None) == 8


def test_pipeline_step_defaults() -> None:
    assert DEFAULT_PIPELINE_SEGMENT_STEP_KB == 32
    assert DEFAULT_PIPELINE_CLOSE_STEP_BATCHES == 1


def test_load_progress_snapshot_returns_zero_for_missing_db(tmp_path: Path) -> None:
    snapshot = _load_progress_snapshot(db_path=tmp_path / "missing.db", book_id="demo")

    assert snapshot["segmentation_chars"] == 0
    assert snapshot["close_read_chars"] == 0
    assert snapshot["segmentation_kb"] == 0.0
    assert snapshot["close_read_kb"] == 0.0


def test_load_progress_snapshot_reads_segmentation_and_close_read_chars(tmp_path: Path) -> None:
    db_path = tmp_path / "interactive_progress.db"
    db = NovelAgentDB(db_path)
    documents_repo = DocumentsRepo()
    progress_repo = ReadingProgressRepo()
    with db.connect() as conn:
        db.init_schema(conn)
        documents_repo.insert_document(
            conn,
            {
                "path": "001.md",
                "scope": "novel",
                "title": "第一章",
                "content": "路明非看着雨幕。",
                "mtime": 0,
                "size": 0,
                "content_sha256": "sha-1",
                "book_id": "demo",
                "source_path": "001.md",
                "source_file_name": "001.md",
                "source_start_offset": 0,
                "source_end_offset": 10,
                "source_batch_no": 1,
                "document_title": "第一章",
                "document_title_index": 1,
                "inferred_chapter_no": 1,
                "content_chars": 8,
                "character_keywords": [],
                "content_tags": [],
                "segmentation_notes": "",
                "ingestion_run_id": "run-1",
                "created_at": "now",
                "updated_at": "now",
            },
        )
        documents_repo.insert_document(
            conn,
            {
                "path": "001.md",
                "scope": "novel",
                "title": "第一章",
                "content": "楚子航仍然沉默。",
                "mtime": 0,
                "size": 0,
                "content_sha256": "sha-2",
                "book_id": "demo",
                "source_path": "001.md",
                "source_file_name": "001.md",
                "source_start_offset": 10,
                "source_end_offset": 22,
                "source_batch_no": 1,
                "document_title": "第一章",
                "document_title_index": 1,
                "inferred_chapter_no": 1,
                "content_chars": 8,
                "character_keywords": [],
                "content_tags": [],
                "segmentation_notes": "",
                "ingestion_run_id": "run-1",
                "created_at": "now",
                "updated_at": "now",
            },
        )
        progress_repo.upsert(
            conn,
            {
                "book_id": "demo",
                "agent_stage": DEFAULT_SEGMENTATION_STAGE,
                "current_doc_id": None,
                "current_document_title_index": None,
                "current_source_path": "001.md",
                "current_source_offset": 22,
                "last_completed_doc_id": None,
                "last_completed_title_index": None,
                "last_completed_chapter_id": None,
                "status": {"state": "completed_batch"},
                "checkpoint_token": "001.md:22",
                "updated_at": "now",
            },
        )
        progress_repo.upsert(
            conn,
            {
                "book_id": "demo",
                "agent_stage": DEFAULT_CLOSE_READING_STAGE,
                "current_doc_id": None,
                "current_document_title_index": 1,
                "current_source_path": "001.md",
                "current_source_offset": 10,
                "last_completed_doc_id": 1,
                "last_completed_title_index": 1,
                "last_completed_chapter_id": 1,
                "status": {"state": "processed_batch"},
                "checkpoint_token": "1:1",
                "updated_at": "now",
            },
        )
        conn.commit()

    snapshot = _load_progress_snapshot(db_path=db_path, book_id="demo")

    assert snapshot["segmentation_chars"] == 16
    assert snapshot["close_read_chars"] == 8
    assert snapshot["segmentation_source_offset"] == 22


def test_creative_kb_retrieval_input_to_dict_matches_contract_shape() -> None:
    payload = CreativeKBRetrievalInput(
        anchor_context="上一段写到她没有回头。",
        recent_window_summary="目前是短暂僵持。",
        goal="续写这段停顿",
        documents=[
            {
                "doc_id": "1",
                "document_title": "第十章",
                "content": "她站在雨里，没有说再见。",
            }
        ],
        previous_generated_segment="她的手指扣紧了伞柄。",
        retrieval_context=RetrievalContext(
            character_hits=["林清"],
            timeline_hits=["第十章"],
            lore_hits=["旧城区雨夜"],
        ),
        scene_plan={"goal": "续写这段停顿"},
    ).to_dict()

    assert set(payload.keys()) == {
        "documents",
        "anchor_context",
        "recent_window_summary",
        "goal",
        "previous_generated_segment",
        "retrieval_context",
        "scene_plan",
    }
    assert payload["documents"][0]["doc_id"] == "1"
    assert payload["retrieval_context"]["character_hits"] == ["林清"]
    assert payload["scene_plan"]["goal"] == "续写这段停顿"


def test_writer_input_bundle_to_dict_matches_contract_shape() -> None:
    bundle = WriterInputBundle(
        anchor_context="她没有回头。",
        recent_window_summary="误解仍未解开。",
        scene_brief=SceneBrief(
            scene_objective="续写雨夜停顿",
            emotional_goal="克制悲伤",
            conflict_goal="维持表面平静",
            narrative_function=["收束"],
            emotion_mode=["克制"],
            character_temperament=["敏感"],
            relationship_state=["未和解"],
            style_need=["短句"],
            must_avoid=["突然表白"],
            preferred_tags=["雨夜"],
        ),
        reference_fragments=[
            ReferenceFragment(
                fragment_id="frag-1",
                source_excerpt="她站在雨里，没有立刻说话。",
                content_summary="雨夜对峙桥段",
                style_profile_text="短句，低对白。",
            )
        ],
        context_payload=ContextAssemblyPayload(
            chapter_context=[
                ChapterContextItem(
                    document_title_index="10",
                    chapter_title="第十章 雨夜",
                    summary_md="两人在雨夜维持表面平静。",
                    importance_score=8,
                )
            ],
            world_summary_md="现代都市奇幻世界。",
            character_profiles=[
                CharacterProfileContextItem(
                    canonical_name="林清",
                    profile_summary_md="# 林清\n\n- 敏感克制。",
                    aliases=["小清"],
                    importance_score=7,
                )
            ],
            story_outline_md="主线围绕误解与再靠近展开。",
            missing_context=[],
        ),
        sources=[WriterSource(path="memory/world_summary.md", snippet="现代都市奇幻世界。")],
    ).to_dict()

    assert set(bundle.keys()) == {
        "anchor_context",
        "recent_window_summary",
        "scene_brief",
        "reference_fragments",
        "context_payload",
        "sources",
    }
    assert bundle["scene_brief"]["scene_objective"] == "续写雨夜停顿"
    assert bundle["reference_fragments"][0]["fragment_id"] == "frag-1"
    assert bundle["context_payload"]["chapter_context"][0]["document_title_index"] == "10"
    assert bundle["sources"][0]["path"] == "memory/world_summary.md"

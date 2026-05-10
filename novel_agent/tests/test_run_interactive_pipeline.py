from __future__ import annotations

import json
import sqlite3
from pathlib import Path
from types import SimpleNamespace

from novel_agent.app import run_interactive
from novel_agent.app.constants import DEFAULT_CLOSE_READING_STAGE, DEFAULT_SEGMENTATION_STAGE
from novel_agent.app.repos.chapters_repo import ChaptersRepo
from novel_agent.app.repos.creative_kb_storage import init_creative_kb_schema
from novel_agent.app.repos.db import NovelAgentDB
from novel_agent.app.repos.documents_repo import DocumentRow, DocumentsRepo
from novel_agent.app.repos.reading_progress_repo import ReadingProgressRepo
from novel_agent.app.run_interactive import (
    _build_creative_kb,
    _build_source_arc_map,
    build_writer_workflow,
    redact_writer_result_for_terminal,
    run_writer_guided_flow,
)
from novel_agent.app.schemas.creative_kb_schema import CreativeKBBuildResult
from novel_agent.tests.test_writer_layered_generation_orchestrator import (
    _seed_assets,
    _seed_document,
    _seed_fragment_card,
    _seed_knowledge_docs,
    _seed_profile,
)


class _RecordingCreativeKBFacade:
    def __init__(self) -> None:
        self.document_ids: list[int] = []
        self.schema_was_initialized = False

    def build_creative_kb(
        self,
        conn: sqlite3.Connection,
        *,
        documents: list[DocumentRow],
    ) -> CreativeKBBuildResult:
        self.document_ids = [document.doc_id for document in documents]
        conn.execute("SELECT COUNT(*) FROM fragment_cards").fetchone()
        self.schema_was_initialized = True
        return CreativeKBBuildResult(
            built_fragment_count=len(documents),
            built_cluster_count=1,
            representative_count=1,
            fragment_ids=[f"fragment-{document.doc_id}" for document in documents],
            cluster_ids=["cluster-1"],
        )


def test_creative_kb_facade_enables_thinking_fallback_for_kb_agents(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    captured_settings = []

    class FakeJsonModelClient:
        def __init__(self, settings) -> None:  # type: ignore[no-untyped-def]
            captured_settings.append(settings)

    monkeypatch.setattr(run_interactive, "JsonModelClient", FakeJsonModelClient)
    facade = run_interactive._build_creative_kb_facade(  # noqa: SLF001
        api_key="test-key",
        thinking="enabled",
        reasoning_effort="high",
        include_reasoning_content=True,
    )

    assert len(captured_settings) == 1
    settings = captured_settings[0]
    assert settings.retry_without_thinking_on_failure is True
    assert settings.thinking == "enabled"
    assert settings.reasoning_effort == "high"
    assert settings.include_reasoning_content is True
    assert facade.semantic_alias_extractor_service.model_client is facade.fragment_card_builder_service.model_client


def test_interactive_pipeline_builds_creative_kb_from_current_book_documents(tmp_path: Path) -> None:
    db_path = tmp_path / "pipeline.db"
    db = NovelAgentDB(db_path)
    documents_repo = DocumentsRepo()
    with db.connect() as conn:
        db.init_schema(conn)
        documents_repo.insert_document(
            conn,
            {
                "content": "雨夜里她停了一下，才把未说出口的话咽回去。",
                "book_id": "couple",
                "path": "/tmp/couple.txt",
                "scope": "chapter",
                "document_title": "第一章",
                "document_title_index": 1,
                "content_tags": ["雨天", "告别"],
                "source_path": "/tmp/couple.txt",
                "source_file_name": "couple.txt",
                "source_start_offset": 0,
                "source_end_offset": 24,
            },
        )
        documents_repo.insert_document(
            conn,
            {
                "content": "另一本书的片段不应进入 couple 的知识库构建。",
                "book_id": "other",
                "path": "/tmp/other.txt",
                "scope": "chapter",
                "document_title": "第一章",
                "document_title_index": 1,
                "content_tags": ["调查"],
                "source_path": "/tmp/other.txt",
                "source_file_name": "other.txt",
                "source_start_offset": 0,
                "source_end_offset": 20,
            },
        )
        conn.commit()

    facade = _RecordingCreativeKBFacade()
    result = _build_creative_kb(
        db_path=db_path,
        book_id="couple",
        api_key="unused",
        creative_kb_facade=facade,  # type: ignore[arg-type]
    )

    assert facade.schema_was_initialized is True
    assert facade.document_ids == [1]
    assert result.built_fragment_count == 1
    assert result.fragment_ids == ["fragment-1"]


def test_interactive_pipeline_can_limit_creative_kb_to_close_read_documents(tmp_path: Path) -> None:
    db_path = tmp_path / "pipeline.db"
    db = NovelAgentDB(db_path)
    documents_repo = DocumentsRepo()
    with db.connect() as conn:
        db.init_schema(conn)
        for index in range(1, 4):
            documents_repo.insert_document(
                conn,
                {
                    "content": f"第{index}段内容。",
                    "book_id": "couple",
                    "path": "/tmp/couple.txt",
                    "scope": "chapter",
                    "document_title": f"第{index}章",
                    "document_title_index": index,
                    "content_tags": [],
                    "source_path": "/tmp/couple.txt",
                    "source_file_name": "couple.txt",
                    "source_start_offset": index * 10,
                    "source_end_offset": index * 10 + 5,
                },
            )
        conn.commit()

    facade = _RecordingCreativeKBFacade()
    result = _build_creative_kb(
        db_path=db_path,
        book_id="couple",
        api_key="unused",
        creative_kb_facade=facade,  # type: ignore[arg-type]
        max_doc_id=2,
    )

    assert facade.document_ids == [1, 2]
    assert result.built_fragment_count == 2


def test_pipeline_builds_creative_kb_after_each_close_read_round(tmp_path: Path, monkeypatch) -> None:  # type: ignore[no-untyped-def]
    repo_root = tmp_path / "repo"
    repo_root.mkdir()
    db_path = tmp_path / "pipeline.db"
    source_path = tmp_path / "source.txt"
    source_path.write_text("雨夜之后，调查继续。", encoding="utf-8")
    debug_path = repo_root / ".memory" / "debug" / "couple.sqlite.md"

    db = NovelAgentDB(db_path)
    with db.connect() as conn:
        db.init_schema(conn)
        documents_repo = DocumentsRepo()
        for index in range(1, 4):
            documents_repo.insert_document(
                conn,
                {
                    "content": f"第{index}段内容。",
                    "book_id": "couple",
                    "path": source_path.as_posix(),
                    "scope": "chapter",
                    "document_title": f"第{index}章",
                    "document_title_index": index,
                    "content_tags": [],
                    "source_path": source_path.as_posix(),
                    "source_file_name": source_path.name,
                    "source_start_offset": index * 10,
                    "source_end_offset": index * 10 + 5,
                },
            )
        conn.commit()

    class FakeSegmentationRunner:
        def __init__(self, **_kwargs) -> None:  # type: ignore[no-untyped-def]
            pass

        def run(self):  # type: ignore[no-untyped-def]
            return SimpleNamespace(inserted_documents=0, batch_count=0)

    class FakeCloseReadRunner:
        calls = 0

        def __init__(self, *, db_path: Path, **_kwargs) -> None:  # type: ignore[no-untyped-def]
            self.db_path = db_path

        def run(self):  # type: ignore[no-untyped-def]
            FakeCloseReadRunner.calls += 1
            completed_doc_id = FakeCloseReadRunner.calls
            db = NovelAgentDB(self.db_path)
            with db.connect() as conn:
                db.init_schema(conn)
                ReadingProgressRepo().upsert(
                    conn,
                    {
                        "book_id": "couple",
                        "agent_stage": DEFAULT_CLOSE_READING_STAGE,
                        "last_completed_doc_id": completed_doc_id,
                        "updated_at": "now",
                    },
                )
                conn.commit()
            return SimpleNamespace(processed_batches=1, batch_metrics=[{"batch_index": completed_doc_id}])

    kb_max_doc_ids: list[int | None] = []

    def fake_build_creative_kb(**kwargs):  # type: ignore[no-untyped-def]
        kb_max_doc_ids.append(kwargs.get("max_doc_id"))
        return CreativeKBBuildResult(
            built_fragment_count=1,
            built_cluster_count=1,
            representative_count=1,
            fragment_ids=[f"fragment-{kwargs.get('max_doc_id')}"],
            cluster_ids=["cluster-1"],
        )

    monkeypatch.setattr(run_interactive, "SegmentationRunner", FakeSegmentationRunner)
    monkeypatch.setattr(run_interactive, "CloseReadRunner", FakeCloseReadRunner)
    monkeypatch.setattr(run_interactive, "_build_source_arc_map", lambda **_kwargs: {"status": "skipped"})
    monkeypatch.setattr(run_interactive, "_build_creative_kb", fake_build_creative_kb)

    result = run_interactive._run_pipeline(  # noqa: SLF001
        repo_root=repo_root,
        book_id="couple",
        source_path=source_path,
        db_path=db_path,
        debug_path=debug_path,
        api_key="unused",
        run_mode="resume",
        max_read_kb=0,
        max_close_batches=2,
        segment_step_kb=1,
        close_step_batches=1,
        build_creative_kb=True,
    )

    assert kb_max_doc_ids == [1, 2]
    assert [item["max_doc_id"] for item in result["creative_kb_runs"]] == [1, 2]  # type: ignore[index]


def test_interactive_pipeline_builds_source_arc_map_from_chapter_summaries(tmp_path: Path) -> None:
    repo_root = tmp_path / "repo"
    repo_root.mkdir()
    db_path = tmp_path / "pipeline.db"
    db = NovelAgentDB(db_path)
    with db.connect() as conn:
        db.init_schema(conn)
        chapters_repo = ChaptersRepo()
        for index, summary in [
            (1, "主角在日常生活中和朋友闲聊，关系出现细微变化。"),
            (2, "调查旧案时发现新的组织规则和能力设定。"),
        ]:
            chapters_repo.upsert(
                conn,
                {
                    "book_id": "couple",
                    "document_title_index": index,
                    "chapter_title": f"第{index}章",
                    "source_doc_start_id": index,
                    "source_doc_end_id": index,
                    "source_doc_count": 1,
                    "source_total_chars": len(summary),
                    "summary_intermediate": [],
                    "summary_md": summary,
                    "summary_short": summary,
                    "importance_score": 70,
                    "importance_reason": "测试",
                    "related_chapters": [],
                    "mentioned_characters": [],
                    "world_update": {},
                    "outline_update": {},
                    "close_read_run_id": "run-close",
                    "created_at": "now",
                    "updated_at": "now",
                },
            )
        conn.commit()

    result = _build_source_arc_map(repo_root=repo_root, db_path=db_path, book_id="couple")

    json_path = repo_root / ".memory" / "arcs" / "couple.source_arc_map.json"
    markdown_path = repo_root / ".memory" / "arcs" / "couple.source_arc_map.md"
    assert result["status"] == "built"
    assert result["source_summary_count"] == 2
    assert result["arc_count"] >= 1
    assert result["json_path"] == json_path.as_posix()
    assert result["markdown_path"] == markdown_path.as_posix()
    assert json_path.exists()
    assert markdown_path.exists()
    payload = json.loads(json_path.read_text(encoding="utf-8"))
    assert payload["book_id"] == "couple"
    assert payload["arcs"]


def test_pipeline_exports_source_arc_map_after_close_read(tmp_path: Path, monkeypatch) -> None:
    repo_root = tmp_path / "repo"
    repo_root.mkdir()
    db_path = tmp_path / "pipeline.db"
    source_path = tmp_path / "source.txt"
    source_path.write_text("雨夜之后，调查继续。", encoding="utf-8")
    debug_path = repo_root / ".memory" / "debug" / "couple.sqlite.md"

    class FakeSegmentationRunner:
        def __init__(self, **_kwargs) -> None:  # type: ignore[no-untyped-def]
            pass

        def run(self):  # type: ignore[no-untyped-def]
            return SimpleNamespace(inserted_documents=0, batch_count=0)

    class FakeCloseReadRunner:
        def __init__(self, *, db_path: Path, **_kwargs) -> None:  # type: ignore[no-untyped-def]
            self.db_path = db_path

        def run(self):  # type: ignore[no-untyped-def]
            db = NovelAgentDB(self.db_path)
            with db.connect() as conn:
                db.init_schema(conn)
                ChaptersRepo().upsert(
                    conn,
                    {
                        "book_id": "couple",
                        "document_title_index": 1,
                        "chapter_title": "第一章",
                        "source_doc_start_id": 1,
                        "source_doc_end_id": 1,
                        "source_doc_count": 1,
                        "source_total_chars": 24,
                        "summary_intermediate": [],
                        "summary_md": "日常关系暂时缓和，但旧案调查继续推进。",
                        "summary_short": "日常关系与旧案推进。",
                        "importance_score": 80,
                        "importance_reason": "测试",
                        "related_chapters": [],
                        "mentioned_characters": [],
                        "world_update": {},
                        "outline_update": {},
                        "close_read_run_id": "run-close",
                        "created_at": "now",
                        "updated_at": "now",
                    },
                )
                conn.commit()
            return SimpleNamespace(processed_batches=1, batch_metrics=[{"batch_index": 1}])

    monkeypatch.setattr(run_interactive, "SegmentationRunner", FakeSegmentationRunner)
    monkeypatch.setattr(run_interactive, "CloseReadRunner", FakeCloseReadRunner)

    result = run_interactive._run_pipeline(  # noqa: SLF001
        repo_root=repo_root,
        book_id="couple",
        source_path=source_path,
        db_path=db_path,
        debug_path=debug_path,
        api_key="unused",
        run_mode="resume",
        max_read_kb=0,
        max_close_batches=1,
        segment_step_kb=1,
        close_step_batches=1,
        build_creative_kb=False,
    )

    source_arc_path = repo_root / ".memory" / "arcs" / "couple.source_arc_map.json"
    assert result["source_arc_map"]["status"] == "built"  # type: ignore[index]
    assert source_arc_path.exists()


def test_interactive_pipeline_resume_smoke_with_couple_txt(
    tmp_path: Path,
    monkeypatch,
    capsys,
) -> None:
    repo_root = tmp_path / "repo"
    repo_root.mkdir()
    (repo_root / ".indexes").mkdir()
    source_path = Path.cwd() / "couple.txt"
    assert source_path.exists()

    book_id = "couple-txt"
    db_path = repo_root / ".indexes" / f"{book_id}.db"
    db = NovelAgentDB(db_path)
    documents_repo = DocumentsRepo()
    progress_repo = ReadingProgressRepo()
    with db.connect() as conn:
        db.init_schema(conn)
        first_doc_id = documents_repo.insert_document(
            conn,
            {
                "content": "第一段已有粗读内容。",
                "book_id": book_id,
                "path": source_path.as_posix(),
                "scope": "chapter",
                "document_title": "第一章",
                "document_title_index": 1,
                "content_tags": [],
                "source_path": source_path.as_posix(),
                "source_file_name": source_path.name,
                "source_start_offset": 0,
                "source_end_offset": 10,
            },
        )
        second_doc_id = documents_repo.insert_document(
            conn,
            {
                "content": "第二段等待精读内容。",
                "book_id": book_id,
                "path": source_path.as_posix(),
                "scope": "chapter",
                "document_title": "第二章",
                "document_title_index": 2,
                "content_tags": [],
                "source_path": source_path.as_posix(),
                "source_file_name": source_path.name,
                "source_start_offset": 10,
                "source_end_offset": 20,
            },
        )
        progress_repo.upsert(
            conn,
            {
                "book_id": book_id,
                "agent_stage": DEFAULT_SEGMENTATION_STAGE,
                "current_doc_id": None,
                "current_document_title_index": 2,
                "current_source_path": source_path.as_posix(),
                "current_source_offset": 20,
                "last_completed_doc_id": second_doc_id,
                "last_completed_title_index": 2,
                "last_completed_chapter_id": None,
                "status": {"state": "completed_batch"},
                "checkpoint_token": f"{source_path.as_posix()}:20",
                "updated_at": "now",
            },
        )
        progress_repo.upsert(
            conn,
            {
                "book_id": book_id,
                "agent_stage": DEFAULT_CLOSE_READING_STAGE,
                "current_doc_id": None,
                "current_document_title_index": 1,
                "current_source_path": source_path.as_posix(),
                "current_source_offset": 10,
                "last_completed_doc_id": first_doc_id,
                "last_completed_title_index": 1,
                "last_completed_chapter_id": 1,
                "status": {"state": "processed_batch"},
                "checkpoint_token": f"1:{first_doc_id}",
                "updated_at": "now",
            },
        )
        conn.commit()

    class FakeSegmentationRunner:
        def __init__(self, *, repo_root: Path, db_path: Path, config, progress_callback=None, **_kwargs) -> None:
            self.repo_root = repo_root
            self.db_path = db_path
            self.config = config
            self.progress_callback = progress_callback

        def run(self):
            assert self.repo_root == repo_root
            assert self.db_path == db_path
            assert self.config.book.book_id == book_id
            assert Path(self.config.book.source_root) == source_path
            assert self.config.runtime.resume_from_checkpoint is True
            assert self.config.read_strategy.max_total_chars == 1024
            assert self.progress_callback is not None
            self.progress_callback(
                {
                    "stage": "segmentation",
                    "agent": "segmentation",
                    "event": "prompt_end",
                    "duration_seconds": 0.01,
                }
            )
            return SimpleNamespace(inserted_documents=0, batch_count=0)

    class FakeCloseReadRunner:
        def __init__(self, *, repo_root: Path, db_path: Path, config, progress_callback=None, **_kwargs) -> None:
            self.repo_root = repo_root
            self.db_path = db_path
            self.config = config
            self.progress_callback = progress_callback

        def run(self):
            assert self.repo_root == repo_root
            assert self.db_path == db_path
            assert self.config.book_id == book_id
            assert self.config.runtime.max_chapters == 1
            assert self.progress_callback is not None
            self.progress_callback(
                {
                    "stage": "close_reading",
                    "agent": "chapter_summary",
                    "event": "prompt_end",
                    "duration_seconds": 0.02,
                }
            )
            with db.connect() as conn:
                db.init_schema(conn)
                progress_repo.upsert(
                    conn,
                    {
                        "book_id": book_id,
                        "agent_stage": DEFAULT_CLOSE_READING_STAGE,
                        "current_doc_id": None,
                        "current_document_title_index": 2,
                        "current_source_path": source_path.as_posix(),
                        "current_source_offset": 20,
                        "last_completed_doc_id": second_doc_id,
                        "last_completed_title_index": 2,
                        "last_completed_chapter_id": 2,
                        "status": {"state": "processed_batch"},
                        "checkpoint_token": f"2:{second_doc_id}",
                        "updated_at": "now",
                    },
                )
                conn.commit()
            return SimpleNamespace(
                processed_batches=1,
                batch_metrics=[
                    {
                        "batch_index": 1,
                        "document_title_indexes": [2],
                        "doc_count": 1,
                    }
                ],
            )

    answers = iter(
        [
            "pipeline",
            "couple.txt",
            source_path.as_posix(),
            "resume",
            "1",
            "1",
            "1",
            "1",
            "n",
        ]
    )

    def fake_input(prompt: str) -> str:
        try:
            return next(answers)
        except StopIteration as exc:
            raise AssertionError(f"run_interactive asked for unexpected extra input: {prompt}") from exc

    monkeypatch.setenv("DEEPSEEK_API_KEY", "test-key")
    monkeypatch.setattr(run_interactive, "resolve_repo_root", lambda: repo_root)
    monkeypatch.setattr(run_interactive, "SegmentationRunner", FakeSegmentationRunner)
    monkeypatch.setattr(run_interactive, "CloseReadRunner", FakeCloseReadRunner)
    monkeypatch.setattr("builtins.input", fake_input)

    assert run_interactive.main() == 0

    output = capsys.readouterr().out
    assert '"run_mode": "resume"' in output
    assert '"book_id": "couple-txt"' in output
    assert '"close_read_lag_chars": 0' in output
    assert '"close_read_batch_metrics"' in output
    assert '"prompt_timing"' in output
    assert '"agent": "chapter_summary"' in output


def test_writer_guided_flow_blocks_and_guides_when_modeling_is_missing(tmp_path: Path) -> None:
    repo_root = tmp_path / "repo"
    repo_root.mkdir()
    db, workflow = build_writer_workflow(
        repo_root=repo_root,
        db_path=tmp_path / "writer.db",
        runs_dir=tmp_path / "runs",
        dry_run=True,
    )

    with db.connect() as conn:
        db.init_schema(conn)
        result = run_writer_guided_flow(
            workflow=workflow,
            conn=conn,
            run_id="run-missing",
            book_id="couple",
            product_mode="assist",
            intent_payload={"major_characters": ["沈青"], "desired_actions": ["继续追查旧案"]},
        )

    assert result["status"] == "blocked_by_modeling"
    assert result["modeling_status"]["ready_for_continuation"] is False
    assert result["missing_guidance"]


def test_writer_artifact_review_payloads_are_terminal_safe(tmp_path: Path) -> None:
    artifact_path = tmp_path / "chapter_length_plan.json"
    artifact_path.write_text(
        json.dumps(
            {
                "run_id": "run-1",
                "data": {
                    "plan_id": "length-plan-1",
                    "batch_id": "batch-1",
                    "default_target_chars": 2400,
                    "default_min_chars": 2000,
                    "default_max_chars": 2800,
                    "budgets": [
                        {
                            "chapter_id": "chapter-001",
                            "target_chars": 2400,
                            "min_chars": 2000,
                            "max_chars": 2800,
                        }
                    ],
                    "review_notes": ["完整展示给用户审阅。"],
                },
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    length_payload = run_interactive.build_writer_artifact_review_payload("wait_length_review", str(artifact_path))

    assert length_payload["display_policy"] == "full_planning_artifact"
    assert length_payload["content"]["budgets"][0]["chapter_id"] == "chapter-001"
    assert "是否需要调整" in length_payload["prompt"]

    run_dir = tmp_path / "run-1"
    run_dir.mkdir()
    draft_text = "开头预览。" + ("后续正文。" * 200)
    (run_dir / "draft.md").write_text(draft_text, encoding="utf-8")
    decision_path = run_dir / "generation_review_decision.json"
    decision_path.write_text(
        json.dumps({"data": {"status": "accepted", "target_chars": 2400}}, ensure_ascii=False),
        encoding="utf-8",
    )

    draft_payload = run_interactive.build_writer_draft_review_payload(
        run_dir=run_dir,
        artifact_path=str(decision_path),
        preview_chars=32,
    )

    assert draft_payload["display_policy"] == "path_metadata_and_short_preview"
    assert draft_payload["draft_path"] == str(run_dir / "draft.md")
    assert draft_payload["draft_chars"] == len(draft_text)
    assert draft_payload["draft_preview"] == draft_text[:32]
    assert draft_payload["generation_review_decision"]["status"] == "accepted"


def test_optional_modeling_panels_summarize_source_arc_and_structure_patterns(tmp_path: Path) -> None:
    source_arc_path = tmp_path / ".memory" / "arcs" / "couple.source_arc_map.json"
    pattern_path = tmp_path / ".memory" / "structure_patterns" / "couple.arc_pattern_cards.json"
    source_arc_path.parent.mkdir(parents=True)
    pattern_path.parent.mkdir(parents=True)
    source_arc_path.write_text(
        json.dumps(
            {
                "source_summary_count": 12,
                "used_compression": True,
                "arcs": [
                    {
                        "source_arc_id": "source-arc-001",
                        "source_arc_title": "日常铺垫",
                        "start_document_title_index": 0,
                        "end_document_title_index": 7,
                        "source_arc_role": "setup",
                        "pacing_notes": "低冲突、关系铺垫。",
                    }
                ],
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    pattern_path.write_text(
        json.dumps({"patterns": [{"pattern_id": "arc-card-001", "dominant_function": "过渡"}]}, ensure_ascii=False),
        encoding="utf-8",
    )

    source_arc_panel = run_interactive._source_arc_panel_payload(source_arc_path)  # noqa: SLF001
    pattern_panel = run_interactive._structure_pattern_panel_payload([pattern_path])  # noqa: SLF001

    assert source_arc_panel["ready"] is True
    assert source_arc_panel["arc_count"] == 1
    assert source_arc_panel["arcs"][0]["source_arc_title"] == "日常铺垫"
    assert pattern_panel["ready"] is True
    assert pattern_panel["patterns"][0]["path"] == str(pattern_path)


def test_apply_length_plan_overrides_to_file_updates_wrapped_plan(tmp_path: Path) -> None:
    path = tmp_path / "chapter_length_plan.json"
    path.write_text(
        json.dumps(
            {
                "run_id": "run-1",
                "data": {
                    "plan_id": "length-plan-1",
                    "batch_id": "batch-1",
                    "default_target_chars": 2400,
                    "default_min_chars": 2000,
                    "default_max_chars": 2800,
                    "budgets": [
                        {
                            "chapter_id": "chapter-001",
                            "target_chars": 2400,
                            "min_chars": 2000,
                            "max_chars": 2800,
                            "is_focus_chapter": False,
                        }
                    ],
                    "focus_chapter_ids": [],
                    "review_notes": [],
                },
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    updated = run_interactive.apply_length_plan_overrides_to_file(
        path,
        default_target_chars=3000,
        chapter_overrides={
            "chapter-002": {
                "target_chars": 3600,
                "min_chars": 3200,
                "max_chars": 3900,
                "reason": "finale_buffer",
            }
        },
    )
    persisted = json.loads(path.read_text(encoding="utf-8"))["data"]

    assert updated == persisted
    assert persisted["default_target_chars"] == 3000
    assert persisted["budgets"][0]["target_chars"] == 3000
    assert persisted["budgets"][1]["chapter_id"] == "chapter-002"
    assert persisted["budgets"][1]["focus_reason"] == "finale_buffer"
    assert "已在 wait_length_review 通过交互输入更新章节长度计划。" in persisted["review_notes"]


def test_writer_guided_flow_confirms_freeze_points_to_execution_input(tmp_path: Path) -> None:
    repo_root = tmp_path / "repo"
    repo_root.mkdir()
    _seed_knowledge_docs(repo_root)
    db, workflow = build_writer_workflow(
        repo_root=repo_root,
        db_path=tmp_path / "writer.db",
        runs_dir=tmp_path / "runs",
        dry_run=True,
    )
    with db.connect() as conn:
        db.init_schema(conn)
        init_creative_kb_schema(conn)
        _seed_assets(conn, book_id="couple", repo_root=repo_root)
        _seed_document(conn, book_id="couple")
        _seed_profile(conn, book_id="couple", canonical_name="沈青")
        _seed_fragment_card(conn)
        conn.commit()

        result = run_writer_guided_flow(
            workflow=workflow,
            conn=conn,
            run_id="run-guided",
            book_id="couple",
            product_mode="assist",
            intent_payload={
                "major_characters": ["沈青", "顾迟"],
                "desired_actions": ["安排援军接应并继续追查旧案"],
                "avoidances": ["不要突然告白"],
                "preferred_outcome": "阶段性脱险但留下更深疑点",
                "notes": "需要一个新的反派压力位。",
            },
            user_world_notes="不要突破既有能力体系。",
            target_chapter_count=2,
            chapter_count=2,
            default_target_chars=1800,
            confirm_review=lambda _stage, _artifact_path: True,
        )
        conn.commit()

    run_dir = workflow.run_writer.layout.run_dir("run-guided")
    assert result["status"] == "ready_for_execution"
    assert result["modeling_status"]["ready_for_continuation"] is True
    assert result["modeling_advisories"] == [
        "memory.source_arc_map",
        "creative_kb.narrative_structure_patterns",
    ]
    assert workflow.run_writer.get_freeze_record("run-guided", "freeze_a") is not None
    assert workflow.run_writer.get_freeze_record("run-guided", "freeze_b") is not None
    assert workflow.run_writer.get_freeze_record("run-guided", "freeze_c") is not None
    assert workflow.run_writer.get_freeze_record("run-guided", "freeze_d") is not None
    assert (run_dir / "chapter_length_plan.json").exists()
    assert (run_dir / "chapter_execution_input.json").exists()
    length_budget = json.loads((run_dir / "chapter_length_budget.json").read_text(encoding="utf-8"))["data"]
    assert length_budget["target_chars"] == 1800


def test_writer_terminal_redaction_omits_large_draft_text() -> None:
    redacted = redact_writer_result_for_terminal(
        {
            "execution_result": {
                "draft_md": "正文" * 1200,
                "continuity_report": {"canon_ready": True},
            }
        }
    )

    rendered = json.dumps(redacted, ensure_ascii=False)
    assert "正文正文" not in rendered
    assert "omitted_from_terminal" in rendered
    assert "continuity_report" in rendered

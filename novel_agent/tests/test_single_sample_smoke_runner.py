from __future__ import annotations

import json
from pathlib import Path

from novel_agent.app.repos.assets_repo import AssetsRepo
from novel_agent.app.repos.chapters_repo import ChaptersRepo
from novel_agent.app.repos.character_profiles_repo import CharacterProfilesRepo
from novel_agent.app.repos.db import NovelAgentDB
from novel_agent.app.repos.documents_repo import DocumentsRepo
from novel_agent.app.runner import SingleSampleSmokeRunner
from novel_agent.app.services.continuation_generation_service import (
    ContinuationGenerationResult,
    ContinuationReasoningStep,
)
from novel_agent.app.schemas.orchestration_schema import WriterInputBundle
from novel_agent.app.schemas.smoke_schema import AuthorizedInputs, SmokeReviewerCheck, SmokeReviewerReport
from novel_agent.schemas import RunConfig


def _seed_source_db(tmp_path: Path) -> Path:
    db_path = tmp_path / "source.db"
    db = NovelAgentDB(db_path)
    documents_repo = DocumentsRepo()
    chapters_repo = ChaptersRepo()
    profiles_repo = CharacterProfilesRepo()
    assets_repo = AssetsRepo()

    source_root = tmp_path / "source_assets"
    source_root.mkdir(parents=True)
    world_summary_path = source_root / "world_summary.md"
    outline_path = source_root / "outline.md"
    world_summary_path.write_text("现代都市背景，没有超自然设定。", encoding="utf-8")
    outline_path.write_text(
        "# 第3章\n两人在雨中对峙，关系维持未和解状态。\n",
        encoding="utf-8",
    )

    with db.connect() as conn:
        db.init_schema(conn)
        doc_id_1 = documents_repo.insert_document(
            conn,
            {
                "book_id": "book-1",
                "path": "/tmp/book.md",
                "scope": "chapter",
                "content": "她在雨里停顿了一下，没有把告别说满。",
                "source_path": "/tmp/book.md",
                "source_file_name": "book.md",
                "source_start_offset": 0,
                "source_end_offset": 18,
                "document_title": "第1章",
                "document_title_index": 1,
                "content_tags": ["雨天", "告别"],
            },
        )
        doc_id_2 = documents_repo.insert_document(
            conn,
            {
                "book_id": "book-1",
                "path": "/tmp/book.md",
                "scope": "chapter",
                "content": "林清没有立刻回应，只是把伞柄握得更紧。",
                "source_path": "/tmp/book.md",
                "source_file_name": "book.md",
                "source_start_offset": 19,
                "source_end_offset": 37,
                "document_title": "第2章",
                "document_title_index": 2,
                "content_tags": ["雨天", "对峙"],
            },
        )
        chapters_repo.upsert(
            conn,
            {
                "book_id": "book-1",
                "document_title_index": 1,
                "chapter_title": "第1章 雨夜停顿",
                "source_doc_start_id": doc_id_1,
                "source_doc_end_id": doc_id_1,
                "source_doc_count": 1,
                "source_total_chars": 18,
                "summary_intermediate": ["第一章摘要"],
                "summary_md": "雨夜里的停顿和未尽之语。",
                "summary_short": "停顿",
                "importance_score": 7,
                "importance_reason": "前情",
                "related_chapters": [{"document_title_index": 2, "score": 90, "reason": "承接"}],
                "mentioned_characters": ["林清"],
                "world_update": {},
                "outline_update": {},
                "close_read_run_id": "seed",
                "created_at": "now",
                "updated_at": "now",
            },
        )
        chapters_repo.upsert(
            conn,
            {
                "book_id": "book-1",
                "document_title_index": 2,
                "chapter_title": "第2章 雨中对峙",
                "source_doc_start_id": doc_id_2,
                "source_doc_end_id": doc_id_2,
                "source_doc_count": 1,
                "source_total_chars": 18,
                "summary_intermediate": ["第二章摘要"],
                "summary_md": "林清在雨中对峙，关系仍未和解。",
                "summary_short": "对峙",
                "importance_score": 9,
                "importance_reason": "当前前缀",
                "related_chapters": [],
                "mentioned_characters": ["林清"],
                "world_update": {},
                "outline_update": {},
                "close_read_run_id": "seed",
                "created_at": "now",
                "updated_at": "now",
            },
        )
        profiles_repo.upsert(
            conn,
            {
                "book_id": "book-1",
                "canonical_name": "林清",
                "aliases": ["小清"],
                "profile_summary_md": "情绪克制，遇到冲突时先压住表达。",
                "personality": ["克制"],
                "occupations": [],
                "age_timeline": [],
                "abilities": [],
                "recent_activity": [],
                "relationships": [],
                "chapter_indexes": [1, 2],
                "first_seen_doc_id": doc_id_1,
                "last_seen_doc_id": doc_id_2,
                "first_seen_title_index": 1,
                "last_seen_title_index": 2,
                "importance_score": 9,
                "profile_version": 1,
                "created_at": "now",
                "updated_at": "now",
            },
        )
        assets_repo.upsert(
            conn,
            {
                "book_id": "book-1",
                "source_root": str(source_root),
                "world_markdown_path": "",
                "world_summary_path": str(world_summary_path),
                "outline_markdown_path": str(outline_path),
                "toc_markdown": "",
                "toc_source_path": "",
                "debug_export_path": "",
                "created_at": "now",
                "updated_at": "now",
            },
        )
        conn.commit()

    return db_path


def _build_sample_files(tmp_path: Path) -> Path:
    sample_dir = tmp_path / "sample"
    sample_dir.mkdir(parents=True)
    (sample_dir / "anchor.md").write_text(
        "上一段停在林清没有直接回应，只把伞柄握得更紧。",
        encoding="utf-8",
    )
    (sample_dir / "recent.md").write_text(
        "最近窗口里两人一直维持未和解的对峙状态。",
        encoding="utf-8",
    )
    (sample_dir / "truth.md").write_text(
        "林清在雨里沉默了几秒，开口时仍压着悲意，没有让这场对峙立刻结束。",
        encoding="utf-8",
    )
    sample_path = sample_dir / "sample.json"
    sample_path.write_text(
        json.dumps(
            {
                "sample_id": "sample-1",
                "book_id": "book-1",
                "target_chapter_id": "chapter-3",
                "mode": "chapter_authorized",
                "anchor_context_path": "anchor.md",
                "recent_window_refs": ["recent.md"],
                "documents_cutoff": {"max_document_title_index": "2"},
                "allowed_outline_scope": {
                    "chapter_range": ["第3章"],
                    "allow_future_outline": False,
                },
                "reference_truth_path": "truth.md",
                "metadata": {"target_length_chars": 1200, "window_size": 2},
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )
    return sample_path


def _build_two_step_sample_files(tmp_path: Path) -> Path:
    sample_dir = tmp_path / "sample_two_steps"
    sample_dir.mkdir(parents=True)
    (sample_dir / "anchor_1.md").write_text(
        "上一段停在林清没有直接回应，只把伞柄握得更紧。",
        encoding="utf-8",
    )
    (sample_dir / "recent_1.md").write_text(
        "最近窗口里两人一直维持未和解的对峙状态。",
        encoding="utf-8",
    )
    (sample_dir / "truth_1.md").write_text(
        "林清仍压着情绪，没有把争执真正摊开。",
        encoding="utf-8",
    )
    (sample_dir / "anchor_2.md").write_text(
        "林清没有躲开，只是把那句话吞回去，雨声压在两人之间。",
        encoding="utf-8",
    )
    (sample_dir / "recent_2.md").write_text(
        "第一段后，林清表面仍克制，但对峙已经往更深处推进。",
        encoding="utf-8",
    )
    (sample_dir / "truth_2.md").write_text(
        "林清终于抬眼，把先前压住的话一点点说了出来，对峙因此继续升级。",
        encoding="utf-8",
    )
    sample_path = sample_dir / "sample.json"
    sample_path.write_text(
        json.dumps(
            {
                "sample_id": "sample-2",
                "book_id": "book-1",
                "target_chapter_id": "chapter-3",
                "mode": "chapter_authorized",
                "anchor_context_path": "anchor_1.md",
                "recent_window_refs": ["recent_1.md"],
                "documents_cutoff": {"max_document_title_index": "2"},
                "allowed_outline_scope": {
                    "chapter_range": ["第3章"],
                    "allow_future_outline": False,
                },
                "reference_truth_path": "truth_1.md",
                "continuation_steps": [
                    {
                        "step_id": "step-1",
                        "target_segment_id": "opening",
                        "anchor_context_path": "anchor_1.md",
                        "recent_window_refs": ["recent_1.md"],
                        "reference_truth_path": "truth_1.md",
                    },
                    {
                        "step_id": "step-2",
                        "target_segment_id": "followup",
                        "anchor_context_path": "anchor_2.md",
                        "recent_window_refs": ["recent_2.md"],
                        "reference_truth_path": "truth_2.md",
                    },
                ],
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )
    return sample_path


def _fake_text_generator(prompt: str, writer_input_bundle: WriterInputBundle, authorized_inputs: AuthorizedInputs) -> str:
    assert "结构化输入" in prompt
    return (
        f"生成文本：{writer_input_bundle.scene_brief.scene_objective}"
        f" | 人物：{'、'.join(authorized_inputs.related_character_names)}"
    )


class _FakeReviewerService:
    def review(self, **kwargs):  # type: ignore[no-untyped-def]
        generated_text = str(kwargs["generated_text"])
        return SmokeReviewerReport(
            decision="pass",
            score=0.7,
            summary="mock LLM reviewer summary",
            checks={
                "non_empty_length": SmokeReviewerCheck(
                    name="non_empty_length",
                    status="pass",
                    score=1.0 if generated_text else 0.0,
                    summary="mock check",
                )
            },
            issues=[],
            generated_chars=len(generated_text),
            reference_truth_chars=len(kwargs["step"].reference_truth.text),
        )


def test_single_sample_smoke_runner_writes_run_artifacts(tmp_path: Path) -> None:
    source_db_path = _seed_source_db(tmp_path)
    sample_path = _build_sample_files(tmp_path)
    runs_dir = tmp_path / "runs"

    runner = SingleSampleSmokeRunner(
        source_db_path=source_db_path,
        runs_dir=runs_dir,
        repo_root=tmp_path,
        text_generator=_fake_text_generator,
        reviewer_service=_FakeReviewerService(),  # type: ignore[arg-type]
    )

    result = runner.run(sample_path=sample_path)

    run_dir = Path(result.run_dir)
    assert result.sample.config.sample_id == "sample-1"
    assert result.authorized_inputs.related_character_names == ["林清"]
    assert result.retrieval_result.rerank_result.selected_fragment_ids
    assert result.writer_input_bundle.reference_fragments
    assert result.generated_text.startswith("生成文本：")
    assert result.compare_report.decision in {"pass", "borderline", "fail"}
    assert result.reviewer_report is not None
    assert result.reviewer_report.decision in {"pass", "borderline", "fail"}
    assert (run_dir / "smoke_sample.json").exists()
    assert (run_dir / "prefix_runtime_snapshot.json").exists()
    assert (run_dir / "authorized_inputs.json").exists()
    assert (run_dir / "scene_brief.json").exists()
    assert (run_dir / "retrieval_bundle.json").exists()
    assert (run_dir / "writer_input_bundle.json").exists()
    assert (run_dir / "smoke_compare_report.json").exists()
    assert (run_dir / "reviewer_report.json").exists()
    assert (run_dir / "prompt.txt").exists()
    assert (run_dir / "generated.txt").exists()
    assert (run_dir / "reference_truth.txt").exists()
    summary = json.loads((run_dir / "smoke_run_summary.json").read_text(encoding="utf-8"))
    assert summary["data"]["sample_id"] == "sample-1"
    assert summary["data"]["selected_fragment_ids"]
    assert summary["data"]["decision"] in {"pass", "borderline", "fail"}
    assert summary["data"]["reviewer"]["decision"] in {"pass", "borderline", "fail"}


def test_single_sample_smoke_runner_uses_generation_service_when_configured(tmp_path: Path) -> None:
    source_db_path = _seed_source_db(tmp_path)
    sample_path = _build_sample_files(tmp_path)
    runs_dir = tmp_path / "runs"
    captured: dict[str, object] = {}

    class _FakeGenerationService:
        def generate(self, *, prompt: str, config: RunConfig) -> ContinuationGenerationResult:
            captured["prompt"] = prompt
            captured["config"] = config
            return ContinuationGenerationResult(
                generated_text="真实模型生成文本",
                reasoning_steps=[
                    ContinuationReasoningStep(
                        step_type="ModelStep",
                        reasoning_content="先承接前缀",
                        content="真实模型生成文本",
                    )
                ],
                reasoning_markdown="先承接前缀\n",
            )

    runner = SingleSampleSmokeRunner(
        source_db_path=source_db_path,
        runs_dir=runs_dir,
        repo_root=tmp_path,
        generation_service=_FakeGenerationService(),  # type: ignore[arg-type]
        generation_config=RunConfig(
            prompt=None,
            model_type="InferenceClientModel",
            model_id="test-model",
            provider=None,
            api_base=None,
            api_key=None,
            thinking=None,
            reasoning_effort=None,
            save_reasoning=True,
            action_type="code",
            tools=[],
            imports=[],
            verbosity_level=1,
            dry_run=False,
        ),
        reviewer_service=_FakeReviewerService(),  # type: ignore[arg-type]
    )

    result = runner.run(sample_path=sample_path)

    run_dir = Path(result.run_dir)
    assert result.generated_text == "真实模型生成文本"
    assert "结构化输入" in str(captured["prompt"])
    assert (run_dir / "step_1_step-1" / "reasoning.json").exists()
    assert (run_dir / "step_1_step-1" / "reasoning.md").exists()


def test_single_sample_smoke_runner_backfills_profiles_between_two_steps(tmp_path: Path) -> None:
    source_db_path = _seed_source_db(tmp_path)
    sample_path = _build_two_step_sample_files(tmp_path)
    runs_dir = tmp_path / "runs"

    def _two_step_generator(prompt: str, writer_input_bundle: WriterInputBundle, authorized_inputs: AuthorizedInputs) -> str:
        if '"step_id": "step-1"' in prompt:
            return (
                "林清仍旧没有松开伞柄，只低声说这件事不能再拖。"
                "她把那句一直压着的话收了半截。"
            )
        return (
            "林清终于抬眼，把先前压住的话继续说了下去。"
            f"人物：{'、'.join(authorized_inputs.related_character_names)}"
        )

    runner = SingleSampleSmokeRunner(
        source_db_path=source_db_path,
        runs_dir=runs_dir,
        repo_root=tmp_path,
        text_generator=_two_step_generator,
        reviewer_service=_FakeReviewerService(),  # type: ignore[arg-type]
    )

    result = runner.run(sample_path=sample_path)

    assert len(result.step_results) == 2
    first_step = result.step_results[0]
    second_step = result.step_results[1]
    assert first_step.backfill_result is not None
    assert "林清" in first_step.backfill_result.updated_character_names
    run_dir = Path(result.run_dir)
    assert (run_dir / "step_1_step-1" / "backfill_result.json").exists()
    assert (run_dir / "step_2_step-2" / "generated.txt").exists()

    snapshot_db = NovelAgentDB(result.prefix_snapshot.db_path_obj)
    with snapshot_db.connect() as conn:
        row = CharacterProfilesRepo().list_by_book(conn, book_id="book-1")[0]
    assert int(row["profile_version"]) >= 2
    assert "不能再拖" in str(row["profile_summary_md"])
    assert second_step.authorized_inputs.related_character_names == ["林清"]

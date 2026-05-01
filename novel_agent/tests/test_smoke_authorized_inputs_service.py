from __future__ import annotations

from pathlib import Path

from novel_agent.app.repos.assets_repo import AssetsRepo
from novel_agent.app.repos.chapters_repo import ChaptersRepo
from novel_agent.app.repos.character_profiles_repo import CharacterProfilesRepo
from novel_agent.app.repos.db import NovelAgentDB
from novel_agent.app.repos.documents_repo import DocumentsRepo
from novel_agent.app.schemas.smoke_schema import (
    AllowedOutlineScope,
    DocumentsCutoff,
    ForwardGuidance,
    LoadedSmokeSample,
    LoadedSmokeStep,
    PrefixRuntimeSnapshot,
    SmokeSampleConfig,
    SmokeTextArtifact,
)
from novel_agent.app.services.smoke_authorized_inputs_service import SmokeAuthorizedInputsService
from novel_agent.app.services.smoke_prefix_snapshot_service import SmokePrefixSnapshotService


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
        "# 第3章\n两人在雨中对峙，关系维持未和解状态。\n\n# 第4章\n未来章节不应进入当前授权输入。\n",
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
                "content": "第一章内容。",
                "source_path": "/tmp/book.md",
                "source_file_name": "book.md",
                "source_start_offset": 0,
                "source_end_offset": 6,
                "document_title": "第1章",
                "document_title_index": 1,
                "content_tags": ["雨天"],
            },
        )
        doc_id_2 = documents_repo.insert_document(
            conn,
            {
                "book_id": "book-1",
                "path": "/tmp/book.md",
                "scope": "chapter",
                "content": "第二章内容。",
                "source_path": "/tmp/book.md",
                "source_file_name": "book.md",
                "source_start_offset": 7,
                "source_end_offset": 13,
                "document_title": "第2章",
                "document_title_index": 2,
                "content_tags": ["告别"],
            },
        )
        chapters_repo.upsert(
            conn,
            {
                "book_id": "book-1",
                "document_title_index": 1,
                "chapter_title": "第1章",
                "source_doc_start_id": doc_id_1,
                "source_doc_end_id": doc_id_1,
                "source_doc_count": 1,
                "source_total_chars": 6,
                "summary_intermediate": ["第一章摘要"],
                "summary_md": "第一章摘要",
                "summary_short": "第一章",
                "importance_score": 5,
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
                "chapter_title": "第2章",
                "source_doc_start_id": doc_id_2,
                "source_doc_end_id": doc_id_2,
                "source_doc_count": 1,
                "source_total_chars": 6,
                "summary_intermediate": ["第二章摘要"],
                "summary_md": "第二章摘要，林清仍未和解。",
                "summary_short": "第二章",
                "importance_score": 8,
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
                "profile_summary_md": "情绪克制，比较敏感，面对冲突时先压住表达。",
                "personality": ["克制", "敏感"],
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


def _build_snapshot(tmp_path: Path, *, mode: str) -> PrefixRuntimeSnapshot:
    db_path = _seed_source_db(tmp_path)
    sample = SmokeSampleConfig(
        sample_id=f"sample-{mode}",
        book_id="book-1",
        target_chapter_id="chapter-3",
        mode=mode,  # type: ignore[arg-type]
        anchor_context_path="/tmp/anchor.md",
        recent_window_refs=[],
        documents_cutoff=DocumentsCutoff(max_document_title_index="2"),
        allowed_outline_scope=AllowedOutlineScope(
            chapter_range=["第3章"],
            allow_future_outline=False,
        ),
        forward_guidance=(
            ForwardGuidance(
                segment_objective="维持对峙并保留下一步压力",
                required_emotional_direction="先压住情绪再抬升张力",
                must_preserve_tension=True,
                must_not_reveal=["直接和解"],
                next_turn_hint="下一步只给出抽象施压",
                allowed_future_scope={"hint_level": "low", "max_future_segments": 1},
                continuity_watch_items=["关系不能突然缓和"],
                forbidden_shortcuts=["禁止直接表白"],
                target_length_chars=1500,
            )
            if mode == "bounded_future_hint"
            else None
        ),
        reference_truth_path="/tmp/truth.md",
        metadata={"target_length_chars": 1200, "window_size": 2},
    )
    return SmokePrefixSnapshotService().build(
        source_db_path=db_path,
        sample=sample,
        output_root=tmp_path / "runs",
    )


def _build_loaded_sample(*, mode: str) -> LoadedSmokeSample:
    sample = SmokeSampleConfig(
        sample_id=f"sample-{mode}",
        book_id="book-1",
        target_chapter_id="chapter-3",
        mode=mode,  # type: ignore[arg-type]
        anchor_context_path="/tmp/anchor.md",
        recent_window_refs=[],
        documents_cutoff=DocumentsCutoff(max_document_title_index="2"),
        allowed_outline_scope=AllowedOutlineScope(
            chapter_range=["第3章"],
            allow_future_outline=False,
        ),
        forward_guidance=(
            ForwardGuidance(
                segment_objective="维持对峙并保留下一步压力",
                required_emotional_direction="先压住情绪再抬升张力",
                must_preserve_tension=True,
                must_not_reveal=["直接和解"],
                next_turn_hint="下一步只给出抽象施压",
                allowed_future_scope={"hint_level": "low", "max_future_segments": 1},
                continuity_watch_items=["关系不能突然缓和"],
                forbidden_shortcuts=["禁止直接表白"],
                target_length_chars=1500,
            )
            if mode == "bounded_future_hint"
            else None
        ),
        reference_truth_path="/tmp/truth.md",
        metadata={"target_length_chars": 1200, "window_size": 2},
    )
    return LoadedSmokeSample(
        config=sample,
        sample_path="/tmp/sample.json",
        steps=[
            LoadedSmokeStep(
                step_id="step-1",
                target_segment_id=sample.target_segment_id,
                anchor_context=SmokeTextArtifact(
                    path="/tmp/anchor.md",
                    text="上一段停在林清握紧伞柄，没有直接回应对方。",
                ),
                recent_window=[
                    SmokeTextArtifact(path="/tmp/recent.md", text="最近窗口里两人一直维持未和解状态。")
                ],
                reference_truth=SmokeTextArtifact(
                    path="/tmp/truth.md",
                    text="林清在雨里沉默了几秒，开口时仍压着悲意，没有让这场对峙立刻结束。",
                ),
            )
        ],
    )


def test_smoke_authorized_inputs_service_derives_plan_and_scene_seeds(tmp_path: Path) -> None:
    snapshot = _build_snapshot(tmp_path, mode="chapter_authorized")
    loaded_sample = _build_loaded_sample(mode="chapter_authorized")

    result = SmokeAuthorizedInputsService().build(
        sample=loaded_sample,
        prefix_snapshot=snapshot,
    )

    assert result.related_character_names == ["林清"]
    assert result.target_length_chars == 1200
    assert result.current_unit_plan["chapter_goal"] == "两人在雨中对峙，关系维持未和解状态。"
    assert result.current_unit_plan["emotional_goal"] == "压住悲伤，保留余波"
    assert result.current_unit_plan["conflict_goal"] == "保持当前冲突，不让问题过早解决"
    assert result.scene_plan_seed["goal"] == "两人在雨中对峙，关系维持未和解状态。"
    assert result.scene_brief_seed["scene_objective"] == "两人在雨中对峙，关系维持未和解状态。"
    assert "克制表达" in result.scene_brief_seed["emotion_mode"]
    assert "承接推进" in result.scene_brief_seed["narrative_function"]
    assert result.prefix_facts["context_payload"]["story_outline_md"] == "# 第3章\n两人在雨中对峙，关系维持未和解状态。"


def test_smoke_authorized_inputs_service_blocks_plan_in_blind_prefix_mode(tmp_path: Path) -> None:
    snapshot = _build_snapshot(tmp_path, mode="blind_prefix")
    loaded_sample = _build_loaded_sample(mode="blind_prefix")

    result = SmokeAuthorizedInputsService().build(
        sample=loaded_sample,
        prefix_snapshot=snapshot,
    )

    assert result.current_unit_plan == {}
    assert result.scene_plan_seed == {}
    assert result.scene_brief_seed == {}
    assert result.bounded_future_hint is None
    assert result.prefix_facts["context_payload"]["story_outline_md"] == ""


def test_smoke_authorized_inputs_service_passes_bounded_future_hint(tmp_path: Path) -> None:
    snapshot = _build_snapshot(tmp_path, mode="bounded_future_hint")
    loaded_sample = _build_loaded_sample(mode="bounded_future_hint")

    result = SmokeAuthorizedInputsService().build(
        sample=loaded_sample,
        prefix_snapshot=snapshot,
    )

    assert result.bounded_future_hint is not None
    assert result.bounded_future_hint["segment_objective"] == "维持对峙并保留下一步压力"
    assert result.target_length_chars == 1500
    assert "直接和解" in result.scene_brief_seed["must_avoid"]

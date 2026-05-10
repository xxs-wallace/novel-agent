from __future__ import annotations

from pathlib import Path

from novel_agent.app.services.smoke_benchmark_service import (
    AgenticSmokeBenchmarkService,
    SmokeBenchmarkRunService,
    SmokeBenchmarkSampleService,
)
from novel_agent.app.services.smoke_sample_service import SmokeSampleService


LONGZU_FIXTURE = Path(__file__).with_name("longzu_32kb.txt")
LONGZU_96KB_FIXTURE = Path(__file__).with_name("longzu_96kb.txt")
LONGZU_120KB_FIXTURE = Path(__file__).with_name("longzu_120kb.txt")


def test_longzu_32kb_fixture_is_stable() -> None:
    assert LONGZU_FIXTURE.exists()
    raw = LONGZU_FIXTURE.read_bytes()
    assert len(raw) <= 32 * 1024
    assert raw.endswith((b"\n", b"\r\n"))
    text = raw.decode("utf-8")
    assert text.strip()


def test_longzu_96kb_fixture_is_stable() -> None:
    assert LONGZU_96KB_FIXTURE.exists()
    raw = LONGZU_96KB_FIXTURE.read_bytes()
    assert 90 * 1024 <= len(raw) <= 96 * 1024
    assert raw.endswith((b"\n", b"\r\n"))
    text = raw.decode("utf-8")
    assert text.strip()


def test_longzu_120kb_fixture_is_stable() -> None:
    assert LONGZU_120KB_FIXTURE.exists()
    raw = LONGZU_120KB_FIXTURE.read_bytes()
    assert 110 * 1024 <= len(raw) <= 120 * 1024
    assert raw.endswith((b"\n", b"\r\n"))
    text = raw.decode("utf-8")
    assert text.strip()


def test_longzu_sample_builder_generates_non_empty_smoke_sample(tmp_path: Path) -> None:
    result = SmokeBenchmarkSampleService(repo_root=Path.cwd()).build_longzu_32kb_sample(
        source_path=LONGZU_FIXTURE,
        output_dir=tmp_path / "longzu_32kb",
    )
    sample = SmokeSampleService(repo_root=Path.cwd()).load(result.sample_path)

    assert result.sample_path.exists()
    assert result.db_path.exists()
    assert sample.anchor_context.text
    assert sample.recent_window
    assert sample.recent_window_summary
    assert sample.reference_truth.text
    assert result.anchor_context
    assert result.recent_window
    assert result.reference_truth


def test_agentic_benchmark_windows_split_long_fixture_into_smoke_sized_prefix() -> None:
    service = AgenticSmokeBenchmarkService(repo_root=Path.cwd())
    prefix_text, recent_segments, reference_truth, prefix_chunks = service._prepare_agentic_windows(
        source_text=LONGZU_FIXTURE.read_text(encoding="utf-8"),
        minimum_prefix_chars=4_000,
        minimum_prefix_chunks=1,
        recent_window_size=3,
    )

    assert 4_000 <= len(prefix_text) <= 5_500
    assert recent_segments
    assert len(reference_truth) >= 2_500
    assert prefix_chunks
    assert reference_truth not in prefix_text


def test_agentic_benchmark_windows_can_select_longer_reference_truth() -> None:
    service = AgenticSmokeBenchmarkService(repo_root=Path.cwd())
    _prefix_text, _recent_segments, reference_truth, _prefix_chunks = service._prepare_agentic_windows(
        source_text=LONGZU_96KB_FIXTURE.read_text(encoding="utf-8"),
        minimum_prefix_chars=24_000,
        minimum_prefix_chunks=1,
        recent_window_size=3,
        reference_min_chars=8_000,
    )

    assert len(reference_truth) >= 8_000


def test_agentic_benchmark_windows_can_select_later_120kb_reference_truth() -> None:
    service = AgenticSmokeBenchmarkService(repo_root=Path.cwd())
    prefix_text, _recent_segments, reference_truth, _prefix_chunks = service._prepare_agentic_windows(
        source_text=LONGZU_120KB_FIXTURE.read_text(encoding="utf-8"),
        minimum_prefix_chars=30_000,
        minimum_prefix_chunks=1,
        recent_window_size=3,
        reference_min_chars=10_000,
    )

    assert len(prefix_text) >= 30_000
    assert len(reference_truth) >= 10_000


def test_agentic_benchmark_cache_key_tracks_source_window_and_pipeline_params() -> None:
    service = AgenticSmokeBenchmarkService(repo_root=Path.cwd())
    source_text = LONGZU_96KB_FIXTURE.read_text(encoding="utf-8")
    prefix_text, _recent_segments, reference_truth, _prefix_chunks = service._prepare_agentic_windows(
        source_text=source_text,
        minimum_prefix_chars=24_000,
        minimum_prefix_chunks=1,
        recent_window_size=3,
        reference_min_chars=8_000,
    )
    params = {
        "prefix_count": 1,
        "prefix_min_chars": 24_000,
        "recent_window_size": 3,
        "reference_min_chars": 8_000,
        "max_read_kb": 96,
        "max_close_batches": 24,
        "segment_step_kb": 32,
        "close_step_batches": 1,
    }

    first_key = service._build_modeling_cache_key(
        source_path=LONGZU_96KB_FIXTURE,
        source_text=source_text,
        prefix_text=prefix_text,
        reference_truth=reference_truth,
        params=params,
    )
    second_key = service._build_modeling_cache_key(
        source_path=LONGZU_96KB_FIXTURE,
        source_text=source_text,
        prefix_text=prefix_text,
        reference_truth=reference_truth,
        params={**params, "prefix_min_chars": 70_000},
    )

    assert first_key != second_key
    assert service._source_slug(LONGZU_96KB_FIXTURE) == "longzu-96kb"


def test_agentic_benchmark_normalizes_writer_chapter_brief_as_generated_synopsis() -> None:
    service = AgenticSmokeBenchmarkService(repo_root=Path.cwd())
    synopsis = service._build_writer_generated_synopsis(
        execution_data={
            "chapter_title": "测试章节",
            "chapter_brief": {
                "chapter_id": "chapter-1",
                "title": "备用标题",
                "goal": "主角被动收到异常邀请。",
                "emotional_goal": "保持困惑和防备。",
                "conflict_goal": "让邀请的真实性进入视野。",
                "structure_hint": {"beats": ["收到通知", "拿到设备"]},
                "must_include": ["面试通知", "手机"],
                "forbidden": ["不得提前揭示全部真相"],
                "ending_hook": "主角意识到事情可能不是玩笑。",
            },
            "length_budget": {"target_chars": 1800},
            "planned_character_constraints": [{"canonical_name": "主角"}],
        },
        writer_run_dir=Path("/tmp/writer-run"),
        fallback_target_chars=2700,
    )

    assert synopsis["source"] == "writer_chapter_brief"
    assert synopsis["target_chars"] == 1800
    assert synopsis["chapter_title"] == "测试章节"
    assert "主角被动收到异常邀请" in str(synopsis["combined_synopsis"])
    assert "收到通知" in synopsis["plot_beats"]  # type: ignore[operator]
    assert "面试通知" in synopsis["must_preserve"]  # type: ignore[operator]
    assert "手机" in synopsis["must_preserve"]  # type: ignore[operator]
    assert "主角" in synopsis["characters_used"]  # type: ignore[operator]
    assert synopsis["writer_artifacts"]  # type: ignore[index]


def test_agentic_benchmark_writer_synopsis_uses_fallback_length_when_budget_is_missing() -> None:
    service = AgenticSmokeBenchmarkService(repo_root=Path.cwd())
    synopsis = service._build_writer_generated_synopsis(
        execution_data={
            "chapter_brief": {
                "goal": "主角确认当前局面。",
                "structure_hint": {"beats": ["确认局面"]},
            },
            "length_budget": {},
        },
        writer_run_dir=Path("/tmp/writer-run"),
        fallback_target_chars=900,
    )

    assert synopsis["target_chars"] == 900
    assert synopsis["must_preserve"] == ["主角确认当前局面。", "确认局面"]


def test_agentic_benchmark_no_longer_exposes_parallel_generation_prompt_builders() -> None:
    service = AgenticSmokeBenchmarkService(repo_root=Path.cwd())

    assert not hasattr(service, "_build_outline_grounded_synopsis_prompt")
    assert not hasattr(service, "_build_expansion_prompt")


def test_agentic_benchmark_provenance_paths_are_not_generation_prompts(tmp_path: Path) -> None:
    writer_run_dir = tmp_path / "writer_run"
    writer_run_dir.mkdir()
    execution_input_path = writer_run_dir / "chapter_execution_input.json"
    story_outline_path = tmp_path / "benchmark_story_outline.json"

    synopsis_provenance = {
        "source": "writer_artifacts",
        "note": "No standalone benchmark synopsis-generation prompt was used.",
        "writer_run_dir": str(writer_run_dir),
        "writer_execution_input_path": str(execution_input_path),
        "close_read_story_outline_path": str(story_outline_path),
    }

    assert synopsis_provenance["source"] == "writer_artifacts"
    assert "system_prompt" not in synopsis_provenance
    assert "user_payload" not in synopsis_provenance


def test_reference_synopsis_and_outline_are_assembled_from_close_read_outputs() -> None:
    service = AgenticSmokeBenchmarkService(repo_root=Path.cwd())
    reference_context = {
        "story_outline_md": "# 故事大纲\n\n## 分章节进度\n- [3] 主角收到异常来信并被动签收神秘包裹。",
        "reference_chapter_summaries": [
            {
                "document_title_index": 1,
                "chapter_title": "目标一",
                "source_total_chars": 1200,
                "summary_short": "主角继续日常压力...",
                "summary_md": (
                    "## 剧情事件链\n"
                    "- 起点：主角等待美国来信。\n"
                    "- 转折/结果：主角收到异常来信，并被动签收神秘包裹。\n\n"
                    "## 结构功能/节奏\n"
                    "- 日常中插入异常接触。"
                ),
            }
        ],
        "reference_character_docs": [{"canonical_name": "主角"}, {"canonical_name": "参考新角色"}],
    }
    reference_synopsis = service._build_reference_synopsis_from_close_read(
        reference_context=reference_context,
        source_chars=2700,
    )
    story_outline = service._build_story_outline_from_close_read(
        story_context={
            "story_outline_md": "# 故事大纲\n\n## 分章节进度\n- [2] 主角出门购物并等待美国来信。",
            "recent_story_synopses": [{"summary_short": "上一段还停在日常压力里。"}],
            "character_docs": [{"canonical_name": "主角"}],
        },
        reference_context=reference_context,
        target_chars=2700,
    )

    assert reference_synopsis["source"] == "close_read_chapter_summary"
    assert reference_synopsis["source_chars"] == 2700
    assert "异常来信" in str(reference_synopsis["combined_synopsis"])
    assert reference_synopsis["document_synopses"]  # type: ignore[index]
    assert "主角等待美国来信" in str(reference_synopsis["plot_beats"])
    assert story_outline["source"] == "close_read_story_outline"
    assert story_outline["story_outline_md"]
    assert story_outline["next_outline_node"] == "主角收到异常来信并被动签收神秘包裹。"
    assert story_outline["timeline"][-1]["summary"] == "主角收到异常来信并被动签收神秘包裹。"  # type: ignore[index]
    assert story_outline["timeline"][-1]["target_chars"] == 2700  # type: ignore[index]
    assert "参考新角色" not in story_outline["usable_character_names"]  # type: ignore[operator]
    assert "boundary_rules" not in story_outline


def test_benchmark_writer_planning_input_uses_gold_upper_inputs_without_reference_synopsis() -> None:
    service = AgenticSmokeBenchmarkService(repo_root=Path.cwd())
    payload = service._build_benchmark_writer_planning_input(
        story_outline={
            "source": "close_read_story_outline",
            "next_outline_node": "主角收到异常来信并被动签收神秘包裹。",
            "usable_character_names": ["主角"],
            "timeline": [{"scope": "target", "summary": "主角收到异常来信并被动签收神秘包裹。"}],
        },
        story_context={
            "recent_story_synopses": [{"summary_short": "上一段停在日常压力里。"}],
            "character_docs": [{"canonical_name": "主角", "profile_summary_md": "长期处于自卑状态。"}],
        },
        target_chars=2700,
    )

    intent_payload = payload["intent_payload"]  # type: ignore[index]
    assert payload["source"] == "close_read_gold_upper_inputs"
    assert intent_payload["allow_character_cast"] is False  # type: ignore[index]
    assert "主角收到异常来信" in str(intent_payload["desired_actions"])  # type: ignore[index]
    assert "上一段停在日常压力里" in str(intent_payload["desired_actions"])  # type: ignore[index]
    assert intent_payload["major_characters"] == ["主角"]  # type: ignore[index]
    assert "combined_synopsis" not in str(intent_payload["notes"])  # type: ignore[index]
    assert "benchmark_story_outline.next_outline_node" in str(payload["user_world_notes"])


def test_expansion_execution_input_uses_reference_close_read_synopsis() -> None:
    service = AgenticSmokeBenchmarkService(repo_root=Path.cwd())
    execution_input = service._build_reference_synopsis_execution_input(
        base_execution_data={
            "chapter_id": "chapter-1",
            "chapter_title": "Writer 自生成章节",
            "chapter_brief": {"goal": "错误的梦境线索", "must_include": ["梦境"]},
            "fact_inputs": {"batch_plan": {"summary": "错误的 Writer 计划"}},
            "style_reference_bundle": {"references": [{"excerpt": "前缀风格片段"}]},
            "writer_rules": ["原规则"],
            "forbidden_inputs": ["原禁用项"],
        },
        reference_synopsis={
            "source": "close_read_chapter_summary",
            "source_chars": 2700,
            "combined_synopsis": "主角收到卡塞尔学院录取信，并被动签收一部 N96 手机。",
            "document_synopses": [
                {"order": 1, "summary": "主角收到卡塞尔学院录取信。"},
                {"order": 2, "summary": "主角被动签收一部 N96 手机。"},
            ],
            "plot_beats": ["收到录取信", "签收 N96 手机"],
            "must_preserve": ["收到录取信", "签收 N96 手机"],
            "must_avoid": ["不得新增梦境主线"],
        },
        story_outline={"next_outline_node": "卡塞尔学院主动联系主角。"},
        story_context={"recent_story_synopses": [{"summary_short": "前情"}], "character_docs": [{"canonical_name": "主角"}]},
        target_chars=2700,
    )

    chapter_brief = execution_input["chapter_brief"]  # type: ignore[index]
    assert chapter_brief["combined_synopsis"].startswith("主角收到卡塞尔学院录取信")  # type: ignore[index]
    assert "reference_document_synopses" in chapter_brief
    assert "签收 N96 手机" in chapter_brief["must_include"]  # type: ignore[index]
    assert "错误的梦境线索" not in str(chapter_brief)
    assert execution_input["fact_inputs"]["input_synopsis_source"] == "close_read_reference_story_synopsis"  # type: ignore[index]
    assert "错误的 Writer 计划" not in str(execution_input["fact_inputs"])
    assert execution_input["length_budget"]["target_chars"] == 2700  # type: ignore[index]
    assert "不得使用 reference_truth 原文" in str(execution_input["forbidden_inputs"])


def test_synopsis_reviewer_prompt_requires_core_beat_alignment() -> None:
    service = AgenticSmokeBenchmarkService(repo_root=Path.cwd())
    prompt = service._build_synopsis_review_prompt(
        story_outline={"next_outline_node": "主角收到异常来信。"},
        recent_story_synopses=[{"summary_short": "主角在日常压力中等待转折。"}],
        character_docs=[{"canonical_name": "主角"}],
        generated_synopsis={"combined_synopsis": "主角去旧书店收到匿名短信。", "plot_beats": ["匿名短信"]},
        reference_synopsis={"combined_synopsis": "主角收到录取邀请和手机包裹。", "plot_beats": ["录取邀请", "手机包裹"]},
    )
    payload = prompt["user_payload"]  # type: ignore[index]

    assert payload["story_outline"]  # type: ignore[index]
    assert payload["recent_story_synopses"]  # type: ignore[index]
    assert payload["character_docs"]  # type: ignore[index]
    assert "score 不得高于 0.45" in prompt["system_prompt"]  # type: ignore[operator]
    assert "核心 plot_beats" in prompt["system_prompt"]  # type: ignore[operator]


def test_smoke_benchmark_run_service_rejects_without_real_model(tmp_path: Path) -> None:
    build_result = SmokeBenchmarkSampleService(repo_root=Path.cwd()).build_longzu_32kb_sample(
        source_path=LONGZU_FIXTURE,
        output_dir=tmp_path / "longzu_32kb",
    )

    try:
        SmokeBenchmarkRunService(repo_root=Path.cwd()).run_existing_sample(
            sample_path=build_result.sample_path,
            db_path=build_result.db_path,
            runs_dir=tmp_path / "runs",
        )
    except ValueError as exc:
        assert "real LLM config" in str(exc)
    else:
        raise AssertionError("smoke benchmark should reject offline runs")

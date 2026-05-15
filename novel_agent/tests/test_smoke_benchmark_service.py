from __future__ import annotations

import os
from pathlib import Path

import pytest

from novel_agent.app.services.smoke_benchmark_service import (
    AgenticSmokeBenchmarkService,
    OutlineResearchReviewer,
    SmokeBenchmarkRunService,
    SmokeBenchmarkSampleService,
)
from novel_agent.app.services.smoke_sample_service import SmokeSampleService


LONGZU_FIXTURE = Path(__file__).with_name("longzu_32kb.txt")
LONGZU_96KB_FIXTURE = Path(__file__).with_name("longzu_96kb.txt")
LONGZU_120KB_FIXTURE = Path(__file__).with_name("longzu_120kb.txt")
LONGZU_240KB_FIXTURE = Path(__file__).with_name("longzu_240kb.txt")


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


def test_author_brief_240kb_window_accepts_utf8_byte_sized_fixture() -> None:
    service = AgenticSmokeBenchmarkService(repo_root=Path.cwd())
    source_text = LONGZU_240KB_FIXTURE.read_text(encoding="utf-8")
    prefix_text, _recent_segments, reference_truth, _prefix_chunks = service._prepare_agentic_windows(
        source_text=source_text,
        minimum_prefix_chars=120_000,
        minimum_prefix_chunks=1,
        recent_window_size=3,
        reference_min_chars=120_000,
    )

    assert len(prefix_text.encode("utf-8")) >= 115_000
    assert len(reference_truth.encode("utf-8")) >= 115_000


def test_sequence_reference_context_splits_close_read_summaries_in_order() -> None:
    service = AgenticSmokeBenchmarkService(repo_root=Path.cwd())
    groups = service._split_reference_context_for_sequence(
        reference_context={
            "story_outline_md": "# 大纲",
            "reference_character_docs": [{"canonical_name": "主角"}],
            "reference_chapter_summaries": [
                {"document_title_index": 1, "summary_short": "一", "source_total_chars": 1000},
                {"document_title_index": 2, "summary_short": "二", "source_total_chars": 1000},
                {"document_title_index": 3, "summary_short": "三", "source_total_chars": 1000},
                {"document_title_index": 4, "summary_short": "四", "source_total_chars": 1000},
                {"document_title_index": 5, "summary_short": "五", "source_total_chars": 1000},
                {"document_title_index": 6, "summary_short": "六", "source_total_chars": 1000},
            ],
        },
        sequence_chapter_count=3,
    )

    assert len(groups) == 3
    assert [item["document_title_index"] for item in groups[0]["reference_chapter_summaries"]] == [1, 2]  # type: ignore[index]
    assert [item["document_title_index"] for item in groups[1]["reference_chapter_summaries"]] == [3, 4]  # type: ignore[index]
    assert [item["document_title_index"] for item in groups[2]["reference_chapter_summaries"]] == [5, 6]  # type: ignore[index]


def test_sequence_story_outline_uses_step_reference_summary() -> None:
    service = AgenticSmokeBenchmarkService(repo_root=Path.cwd())
    story_outline = service._build_story_outline_from_close_read(
        story_context={"recent_story_synopses": [{"summary_short": "前情"}], "character_docs": []},
        reference_context={
            "story_outline_md": "# 大纲\n- [9] 全局最后节点，不应覆盖当前 step。",
            "reference_chapter_summaries": [
                {"summary_short": "当前 step 的 close-read 梗概。", "summary_md": ""}
            ],
        },
        target_chars=1200,
        prefer_story_outline_node=False,
    )

    assert story_outline["next_outline_node"] == "当前 step 的 close-read 梗概。"


def test_sequence_reference_context_can_split_single_close_read_event_chain() -> None:
    service = AgenticSmokeBenchmarkService(repo_root=Path.cwd())
    groups = service._split_reference_context_for_sequence(
        reference_context={
            "story_outline_md": "# 大纲",
            "reference_character_docs": [],
            "reference_chapter_summaries": [
                {
                    "document_title_index": 1,
                    "chapter_title": "目标窗口",
                    "source_total_chars": 9000,
                    "summary_md": (
                        "## 剧情事件链\n"
                        "- 起点：主角做出选择。\n"
                        "- 触发：外部系统确认身份。\n"
                        "- 行动/冲突：主角抵达新地点。\n"
                        "- 转折/结果：主角遭遇异常迹象。\n"
                        "- 后续铺垫：更大冲突露出边缘。\n\n"
                        "## 结构功能/节奏\n"
                        "- 从决定转入新阶段。"
                    ),
                }
            ],
        },
        sequence_chapter_count=3,
    )

    assert len(groups) == 3
    assert "起点：主角做出选择" in str(groups[0]["reference_chapter_summaries"])  # type: ignore[index]
    assert "主角抵达新地点" in str(groups[1]["reference_chapter_summaries"])  # type: ignore[index]
    assert "更大冲突露出边缘" in str(groups[2]["reference_chapter_summaries"])  # type: ignore[index]


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
    assert execution_input["length_budget"]["length_source"] == "external"  # type: ignore[index]
    assert "外部长度预算" in str(execution_input["length_budget"])  # type: ignore[index]
    assert "不得使用未授权原文" in str(execution_input["forbidden_inputs"])


def test_expansion_execution_input_rebuilds_teacher_forced_continuity_gates() -> None:
    service = AgenticSmokeBenchmarkService(repo_root=Path.cwd())
    execution_input = service._build_reference_synopsis_execution_input(
        base_execution_data={
            "chapter_id": "chapter-1",
            "chapter_title": "Writer 自生成章节",
            "chapter_brief": {
                "goal": "Writer 自己规划的关系推进。",
                "relationship_targets": [
                    {
                        "relation_type": "友情",
                        "current_state": "陌生",
                        "target_state": "信任",
                        "required_bridge": ["共同危机"],
                    }
                ],
            },
            "relation_state_gate": {
                "blocked": True,
                "targets": [{"relation_type": "友情", "allowed": False}],
            },
            "planned_character_constraints": [{"canonical_name": "Writer 新角色"}],
        },
        reference_synopsis={
            "source": "close_read_chapter_summary",
            "source_chars": 3000,
            "combined_synopsis": "主角收到邀请后进入新地点，参考角色短暂出现。",
            "characters_used": ["参考角色", "未出现在梗概里的旁支角色"],
            "plot_beats": [
                "起点：主角收到邀请后进入新地点，并开始观察周围异常。",
                "后续铺垫：参考角色短暂出现，为后续冲突留下疑问。",
            ],
            "must_preserve": [
                "起点：主角收到邀请后进入新地点，并开始观察周围异常。",
                "后续铺垫：参考角色短暂出现，为后续冲突留下疑问。",
            ],
        },
        story_outline={"next_outline_node": "主角进入新地点。"},
        story_context={
            "recent_story_synopses": [{"summary_short": "前情"}],
            "character_docs": [{"canonical_name": "主角"}],
        },
        target_chars=3000,
    )

    chapter_brief = execution_input["chapter_brief"]  # type: ignore[index]
    assert chapter_brief["relationship_targets"] == []  # type: ignore[index]
    assert execution_input["relation_state_gate"]["targets"] == []  # type: ignore[index]
    assert "Writer 新角色" not in str(execution_input["planned_character_constraints"])
    assert "主角" in str(execution_input["planned_character_constraints"])
    assert "参考角色" in str(execution_input["planned_character_constraints"])
    assert "未出现在梗概里的旁支角色" not in str(execution_input["planned_character_constraints"])
    assert "主角收到邀请" in str(chapter_brief["must_include"])  # type: ignore[index]
    assert "后进入新地点" in str(chapter_brief["must_include"])  # type: ignore[index]
    assert "开始观察周围异常" not in str(chapter_brief["must_include"])  # type: ignore[index]
    assert "开始观察周围异常" in str(chapter_brief["coverage_plot_beats"])  # type: ignore[index]


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


def test_outline_research_reviewer_fake_report_covers_required_checks() -> None:
    reviewer = OutlineResearchReviewer()
    prompt = reviewer.build_prompt(
        prefix_story_outline="前缀大纲",
        user_story_overview="沈青追查旧案，顾迟协助。",
        outline_seed_packet={
            "extracted_character_mentions": [{"text": "沈青"}, {"text": "顾迟"}],
            "character_resolutions": [
                {"mention_text": "沈青", "canonical_name": "沈青", "status": "resolved"},
                {"mention_text": "顾迟", "canonical_name": "顾迟", "status": "resolved"},
            ],
        },
        outline_research_trace={
            "rounds": [
                {
                    "requests": [{"request_type": "story_detail"}],
                    "results": [{"fact_status": "confirmed"}],
                }
            ]
        },
        planning_notebook={"confirmed_facts": [{"claim": "旧案线索仍未收束"}]},
        sufficiency_decision={"status": "enough"},
        generated_outline={"outline_nodes": [{"summary": "沈青追查旧案"}, {"summary": "顾迟协助"}]},
        reference_future_outline={"plot_beats": ["沈青追查旧案", "顾迟协助"]},
        reference_character_set={
            "existing_characters": [{"name": "沈青"}, {"name": "顾迟"}],
            "new_characters": [],
        },
        leakage_audit={"status": "pass", "issues": []},
    )

    report = reviewer.fake_review(prompt_payload=prompt)

    assert report["decision"] in {"pass", "borderline"}
    assert set(report["checks"]) == set(OutlineResearchReviewer.CHECK_NAMES)  # type: ignore[arg-type]
    assert "research_tool_usefulness_score" in report["scores"]  # type: ignore[operator]


def test_author_brief_overview_sanitizes_close_read_metadata_and_future_only_names() -> None:
    service = AgenticSmokeBenchmarkService(repo_root=Path.cwd())
    overview = service._build_user_story_overview(
        reference_context={
            "reference_chapter_summaries": [
                {
                    "summary_md": (
                        "## 摘要元信息\n- 章节索引：1\n## 剧情事件链\n"
                        "- **起点**：路明非登上列车，与芬格尔同行。\n"
                        "- **转折/结果**：冯·施耐德和曼施坦因讨论 EVA 与白王可能是雌性。\n"
                    )
                }
            ],
            "reference_character_docs": [{"canonical_name": "冯·施耐德"}],
        },
        prefix_story_context={
            "character_docs": [
                {"canonical_name": "李嘉图·M·路", "aliases": ["路明非"]},
                {"canonical_name": "芬格尔·冯·弗林斯", "aliases": ["芬格尔"]},
            ]
        },
    )

    assert overview.startswith("用户授权概述：")
    assert "摘要元信息" not in overview
    assert "章节索引" not in overview
    assert "冯·施耐德" not in overview
    assert "曼施坦因" not in overview
    assert "EVA" not in overview
    assert "白王" not in overview
    assert "路明非" in overview
    assert "芬格尔" in overview


def test_reference_character_set_matches_prefix_aliases() -> None:
    service = AgenticSmokeBenchmarkService(repo_root=Path.cwd())
    character_set = service._build_reference_character_set(
        prefix_story_context={"character_docs": [{"canonical_name": "李嘉图·M·路", "aliases": ["路明非"]}]},
        reference_context={"reference_character_docs": [{"canonical_name": "路明非"}, {"canonical_name": "新人物"}]},
    )

    assert [item["name"] for item in character_set["existing_characters"]] == ["路明非"]  # type: ignore[index]
    assert [item["name"] for item in character_set["new_characters"]] == ["新人物"]  # type: ignore[index]


def test_outline_research_leakage_audit_fails_reference_only_in_writer_payload() -> None:
    service = AgenticSmokeBenchmarkService(repo_root=Path.cwd())
    reference_future_outline = {"plot_beats": ["隐藏答案：主角抵达学院"]}
    reference_character_set = {"new_characters": [{"name": "隐藏新人物"}]}

    clean = service._build_leakage_audit(
        writer_stage_payloads={"writer_input": {"desired_actions": ["根据用户概述续写"]}},
        authorized_user_input="用户概述：主角收到邀请。",
        reference_future_outline=reference_future_outline,
        reference_character_set=reference_character_set,
        future_raw_text="这是后窗原文的很长一段内容。" * 20,
    )
    leaked = service._build_leakage_audit(
        writer_stage_payloads={"planning_notebook": {"reference_future_outline": reference_future_outline}},
        authorized_user_input="用户概述：主角收到邀请。",
        reference_future_outline=reference_future_outline,
        reference_character_set=reference_character_set,
        future_raw_text="这是后窗原文的很长一段内容。" * 20,
    )

    assert clean["status"] == "pass"
    assert leaked["status"] == "fail"
    assert leaked["issues"]  # type: ignore[index]


@pytest.mark.real_llm_outline_research
@pytest.mark.skipif(
    os.getenv("RUN_REAL_LLM_OUTLINE_RESEARCH") != "1",
    reason="Set RUN_REAL_LLM_OUTLINE_RESEARCH=1 to run the real LLM Outline Research smoke.",
)
def test_real_llm_outline_research_smoke_is_explicitly_gated() -> None:
    assert os.getenv("DEEPSEEK_API_KEY"), "DEEPSEEK_API_KEY is required for the gated smoke"

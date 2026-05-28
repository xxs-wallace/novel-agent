from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

from novel_agent.app import run_interactive
from novel_agent.app.cli import (
    ArtifactPresenter,
    ChineseInputBuffer,
    CommandContext,
    CommandRouter,
    DecisionPanel,
    StatusPresenter,
    TuiApp,
    TuiSessionConfig,
    WorkflowFacade,
    WriterStatusPresenter,
)
from novel_agent.app.cli.events import RunEventStream
from novel_agent.app.constants import DEFAULT_CLOSE_READING_STAGE, DEFAULT_SEGMENTATION_STAGE
from novel_agent.app.repos.db import NovelAgentDB


def test_status_presenter_translates_internal_writer_and_read_states() -> None:
    presenter = StatusPresenter()

    rendered = "\n".join(
        [
            presenter.present("freeze_d_review").step,
            presenter.present("wait_chapter_acceptance").step,
            presenter.present("Freeze B pending").step,
            presenter.present("artifact saved").step,
            presenter.present("segmentation running").step,
            presenter.present("memory ready").step,
        ]
    )

    assert "请确认本章写作材料" in rendered
    assert "请决定当前章节草稿" in rendered
    assert "请审阅本批剧情大纲" in rendered
    assert "已保存你的修改" in rendered
    assert "正在导入原文并切分" in rendered
    assert "阅读记忆已可用" in rendered
    for token in presenter.FORBIDDEN_PUBLIC_TOKENS:
        assert token not in rendered


def test_writer_status_presenter_covers_confirmation_points_events_and_gui_actions() -> None:
    presenter = WriterStatusPresenter()
    rendered = "\n".join(
        [
            presenter.present("artifact saved").step,
            presenter.present("batch_review").step,
            presenter.present("Freeze B pending").step,
            presenter.present("freeze_d_review").step,
            presenter.present("wait_chapter_acceptance").step,
            presenter.present("writeback_review").step,
            presenter.present("wait_chapter_review").step,
            presenter.present("checkpoint confirmed").step,
            presenter.present("pending").step,
            presenter.event_message("artifact_saved"),
            *(action.label for action in presenter.writer_actions_for_stage(stage="wait_chapter_acceptance")),
            *(action.label for action in presenter.writer_actions_for_stage(stage="wait_chapter_review")),
        ]
    )

    assert "已保存你的修改" in rendered
    assert "请审阅本批剧情大纲" in rendered
    assert "请确认本章写作材料" in rendered
    assert "请决定当前章节草稿" in rendered
    assert "提交本章正文" in rendered
    assert "请调整章节规划后重写" in rendered
    assert "已确认，继续下一步" in rendered
    assert "等待你确认" in rendered
    assert "提交本章正文" in rendered
    assert "调整字数后重写" in rendered
    assert "修改章节梗概后重写" in rendered
    assert "作废本次草稿" in rendered
    assert "确认修改后的章节梗概，并重新生成长度计划" in rendered
    assert "保存不等于确认" in rendered
    for token in presenter.FORBIDDEN_PUBLIC_TOKENS:
        assert token not in rendered
    assert "checkpoint confirmed" not in rendered


def test_chinese_input_buffer_handles_mixed_width_backspace_and_multiline_paste() -> None:
    buffer = ChineseInputBuffer()
    buffer.insert("沈青A")
    assert buffer.display_cursor_column() == 5

    removed = buffer.backspace()
    assert removed == "A"
    assert buffer.text == "沈青"
    assert buffer.display_cursor_column() == 4

    buffer.paste("继续调查\n避免OOC")
    assert buffer.text == "沈青继续调查\n避免OOC"
    buffer.cursor = len("沈青继续调查")
    buffer.handle_control_key("CTRL+A")
    buffer.handle_control_key("CTRL+K")
    assert buffer.text == "\n避免OOC"
    buffer.cursor = len(buffer.text)
    buffer.handle_control_key("CTRL+E")
    buffer.handle_control_key("CTRL+W")
    assert buffer.text == "\n"


def test_run_event_stream_summarizes_close_read_document_progress() -> None:
    stream = RunEventStream()

    stream.progress_callback(
        {
            "stage": "close_reading",
            "event": "batch_done",
            "batch_index": 2,
            "first_doc_id": 4,
            "last_doc_id": 6,
            "completed_documents": 6,
            "total_documents": 20,
        }
    )

    rendered = stream.events()[0].message
    assert "阅读 batch 2 完成" in rendered
    assert "doc 4-6" in rendered
    assert "已完成 6/20 documents" in rendered


def test_run_event_stream_shows_close_read_model_prompt_progress() -> None:
    stream = RunEventStream()

    stream.progress_callback(
        {
            "stage": "close_reading",
            "agent": "chapter_summary",
            "event": "prompt_start",
            "document_title_indexes": [1, 2],
            "doc_count": 2,
            "total_chars": 6400,
        }
    )
    stream.progress_callback(
        {
            "stage": "close_reading",
            "agent": "chapter_summary",
            "event": "prompt_end",
            "duration_seconds": 12.5,
        }
    )

    messages = [event.message for event in stream.events()]
    assert "正在调用模型：章节摘要" in messages[0]
    assert "章节 [1, 2]" in messages[0]
    assert "模型调用完成：章节摘要 · 12.5s" in messages[1]


def test_run_event_stream_shows_creative_kb_document_progress() -> None:
    stream = RunEventStream()

    stream.progress_callback(
        {
            "stage": "creative_kb",
            "phase": "fragment_card_document_done",
            "current_doc_id": "8",
            "attempted_docs": 3,
            "total_buildable_documents": 20,
            "built_cards": 3,
            "failed_docs": 0,
            "status": "success",
        }
    )

    rendered = stream.events()[0].message
    assert "片段卡完成：doc 8" in rendered
    assert "已建卡 3" in rendered
    assert "已处理 3/20" in rendered


def test_cli_analyze_routes_to_analyzer_facade_without_writer_action(tmp_path: Path) -> None:
    class FakeFacade:
        def __init__(self) -> None:
            self.analyzer_calls: list[dict[str, str]] = []
            self.writer_calls = 0

        def analyze_outline(self, **kwargs):  # type: ignore[no-untyped-def]
            self.analyzer_calls.append(kwargs)
            return {
                "status": "ok",
                "answer": "结论：先局部回收旧案线索。事实依据：【章节摘要】。风险：过早揭开幕后身份。",
                "sources": [{"label": "章节摘要"}],
            }

        def start_writer(self, **kwargs):  # type: ignore[no-untyped-def]
            self.writer_calls += 1
            raise AssertionError("Analyzer command must not start Writer")

    facade = FakeFacade()
    app = TuiApp(
        repo_root=tmp_path,
        config=TuiSessionConfig(book_id="book-one"),
        facade=facade,  # type: ignore[arg-type]
    )

    invocation = CommandRouter().parse("/analyze 当前未解之谜哪条最适合下一阶段回收？")
    output = app.dispatch_command("/analyze 当前未解之谜哪条最适合下一阶段回收？")

    assert invocation.handler_name == "analyze_outline"
    assert facade.analyzer_calls[0]["book_id"] == "book-one"
    assert "未解之谜" in facade.analyzer_calls[0]["question"]
    assert facade.writer_calls == 0
    assert "局部回收" in output
    assert "参考来源：章节摘要" in output


def test_workflow_facade_streams_creative_kb_progress_without_stdout_buffer(tmp_path: Path, monkeypatch) -> None:  # type: ignore[no-untyped-def]
    facade = WorkflowFacade(repo_root=tmp_path)

    def fake_build_creative_kb(**kwargs):  # type: ignore[no-untyped-def]
        progress_callback = kwargs.get("progress_callback")
        assert progress_callback is not None
        progress_callback(
            {
                "stage": "creative_kb",
                "phase": "fragment_card_document_done",
                "current_doc_id": "2",
                "attempted_docs": 1,
                "total_buildable_documents": 2,
                "built_cards": 1,
                "failed_docs": 0,
                "status": "success",
            }
        )
        return SimpleNamespace(to_dict=lambda: {"built_fragment_count": 1})

    monkeypatch.setattr(run_interactive, "_build_creative_kb", fake_build_creative_kb)

    result = facade.build_creative_kb(db_path=tmp_path / "book.db", book_id="book-one", api_key="unused")

    messages = [event.message for event in facade.event_stream.events()]
    assert result["built_fragment_count"] == 1
    assert "片段卡完成：doc 2，success，已建卡 1 · 已处理 1/2" in messages


def test_artifact_presenter_summarizes_batch_chapter_length_and_draft(tmp_path: Path) -> None:
    presenter = ArtifactPresenter()
    batch_path = tmp_path / "batch_plan.json"
    batch_path.write_text(
        json.dumps(
            {
                "data": {
                    "stage_goal": "把旧案线索推到新地点。",
                    "main_conflict": "主角组与反派压力位正面碰撞。",
                    "forbidden_early_consumption": ["不得提前揭晓幕后人"],
                }
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    chapter_path = tmp_path / "chapter_package.json"
    chapter_path.write_text(
        json.dumps(
            {
                "chapters": [
                    {
                        "chapter_id": "ch-1",
                        "chapter_title": "雨夜接应",
                        "chapter_goal": "救出关键证人。",
                    }
                ],
                "forbidden_items": ["不得告白"],
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    length_path = tmp_path / "chapter_length_plan.json"
    length_path.write_text(
        json.dumps(
            {
                "default_target_chars": 2400,
                "focus_chapter_ids": ["ch-1"],
                "budgets": [{"chapter_id": "ch-1", "target_chars": 2600}],
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    draft_path = tmp_path / "draft.md"
    draft_path.write_text("开头。" + "正文。" * 500, encoding="utf-8")

    assert "旧案线索" in presenter.summarize(batch_path, stage="batch_review").render()
    assert "雨夜接应" in presenter.summarize(chapter_path, stage="chapter_review").render()
    assert "2600" in presenter.summarize(length_path, stage="wait_length_review").render()
    draft_summary = presenter.summarize(draft_path, stage="wait_chapter_acceptance", target_chars=2000)
    assert draft_summary.collapsed is True
    assert "请决定当前章节草稿" in draft_summary.render()


def test_artifact_presenter_summarizes_writer_scale_climax_and_character_cast(tmp_path: Path) -> None:
    presenter = ArtifactPresenter()
    book_plan_path = tmp_path / "book_continuation_plan.json"
    book_plan_path.write_text(
        json.dumps(
            {
                "continuation_goal": "追查旧案并建立有限合作",
                "target_chapter_count": 4,
                "target_total_chars": 20000,
                "default_chapter_target_chars": 5000,
                "pacing_profile": "后段爆发",
                "climax_plan": {
                    "conflict_climax": "公开暴露新证据",
                    "emotional_climax": "沈青必须决定是否信任顾迟",
                    "target_chapter_index": 4,
                },
                "chapter_outline_slots": [
                    {"chapter_index": 1, "target_chars": 4500, "plot_function": "建立新目标"},
                    {"chapter_index": 2, "target_chars": 5000, "plot_function": "推进调查"},
                ],
                "must_preserve": ["关系慢热"],
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    requirement_path = tmp_path / "character_requirement_report.json"
    requirement_path.write_text(
        json.dumps(
            {
                "named_existing_characters": [{"name": "沈青", "resolved_to": "沈青"}],
                "named_new_characters": [{"name": "顾迟", "reason": "用户点名但未建档"}],
                "unfilled_role_slots": [{"slot_id": "ally-1", "slot_type": "行动支援者", "reason": "调查线需要支援"}],
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    seed_path = tmp_path / "character_seed_input.json"
    seed_path.write_text(
        json.dumps(
            {
                "character_seed_inputs": [
                    {
                        "seed_id": "seed-1",
                        "display_name_hint": "顾迟",
                        "faction": "友方",
                        "core_concept": "外冷内热的情报中间人",
                        "must_keep": ["克制"],
                        "must_avoid": ["提前交底"],
                        "world_constraints": ["不能越权调动官方力量"],
                    }
                ]
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    profiles_path = tmp_path / "planned_character_profiles.json"
    profiles_path.write_text(
        json.dumps(
            {
                "planned_character_profiles": [
                    {
                        "planned_character_id": "pc-1",
                        "canonical_name": "顾迟",
                        "faction": "友方",
                        "narrative_role": "行动支援",
                        "must_not_reveal_early": ["真实身份"],
                    }
                ]
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    cast_plan_path = tmp_path / "character_cast_plan.json"
    cast_plan_path.write_text(
        json.dumps(
            {
                "cast_plan_id": "cast-1",
                "planned_characters": [{"planned_character_id": "pc-1", "slot_id": "ally-1"}],
                "must_not_consume": ["真实身份"],
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    book_rendered = presenter.summarize(book_plan_path).render()
    assert "20000" in book_rendered
    assert "公开暴露新证据" in book_rendered
    assert "建立新目标" in book_rendered

    requirement_rendered = presenter.summarize(requirement_path).render()
    assert "已有人物" in requirement_rendered
    assert "顾迟: 用户点名但未建档" in requirement_rendered
    assert "行动支援者" in requirement_rendered

    seed_rendered = presenter.summarize(seed_path).render()
    assert "外冷内热的情报中间人" in seed_rendered
    assert "不能越权调动官方力量" in seed_rendered
    assert "seed-1" not in seed_rendered

    profiles_rendered = presenter.summarize(profiles_path).render()
    assert "顾迟 / 友方 / 行动支援" in profiles_rendered
    assert "真实身份" in profiles_rendered

    cast_rendered = presenter.summarize(cast_plan_path).render()
    assert "顾迟 / 行动支援" in cast_rendered
    assert "pc-1" not in cast_rendered
    assert "ally-1" not in cast_rendered


def test_artifact_presenter_field_edit_updates_writer_review_artifacts(tmp_path: Path) -> None:
    presenter = ArtifactPresenter()
    book_plan_path = tmp_path / "book_continuation_plan.json"
    book_plan_path.write_text(
        json.dumps(
            {
                "continuation_goal": "追查旧案",
                "target_chapter_count": 3,
                "target_total_chars": 12000,
                "default_chapter_target_chars": 4000,
                "climax_plan": {"must_foreshadow": []},
                "stage_highlights": [],
                "must_preserve": [],
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    model = presenter.field_edit_model(book_plan_path)
    assert model["field_edit"] is True
    assert "全书目标: 追查旧案" in model["text"]
    saved = presenter.save_field_text(
        book_plan_path,
        "\n".join(
            [
                "全书目标: 追查旧案并建立有限合作",
                "目标章节数: 4",
                "目标总字数: 20000",
                "默认单章字数: 5000",
                "冲突高潮: 公开暴露新证据",
                "情绪高潮: 沈青决定是否信任顾迟",
                "高潮章节位置: 4",
                "必须铺垫: 新证据来源",
                "不得提前解决: 反派身份",
                "回收预期: 证明旧案仍有隐情",
                "阶段高潮: 证人失踪",
                "必须保留: 关系慢热",
            ]
        ),
    )
    assert saved.saved is True
    updated = json.loads(book_plan_path.read_text(encoding="utf-8"))
    assert updated["continuation_goal"] == "追查旧案并建立有限合作"
    assert updated["target_total_chars"] == 20000
    assert updated["climax_plan"]["must_not_resolve_before"] == ["反派身份"]

    length_path = tmp_path / "chapter_length_plan.json"
    length_path.write_text(json.dumps({"budgets": []}, ensure_ascii=False), encoding="utf-8")
    saved = presenter.save_field_text(
        length_path,
        "\n".join(
            [
                "默认目标字数: 4200",
                "重点章节: ch-1",
                "高潮章节: ch-2",
                "单章预算: ch-1=4200/3600/4800; ch-2=5200/4800/5800",
            ]
        ),
    )
    assert saved.saved is True
    length_payload = json.loads(length_path.read_text(encoding="utf-8"))
    assert length_payload["default_target_chars"] == 4200
    assert length_payload["budgets"][1]["chapter_id"] == "ch-2"
    assert length_payload["budgets"][1]["max_chars"] == 5800


def test_artifact_save_validates_json_and_does_not_confirm(tmp_path: Path) -> None:
    presenter = ArtifactPresenter()
    path = tmp_path / "chapter_length_plan.json"

    failed = presenter.save_text(path, '{"budgets": {}}')
    assert failed.saved is False
    assert "budgets 必须是列表" in failed.validation_error
    assert not path.exists()

    saved = presenter.save_text(path, json.dumps({"budgets": []}, ensure_ascii=False))
    assert saved.saved is True
    assert saved.message == "已保存你的修改"
    assert json.loads(path.read_text(encoding="utf-8")) == {"budgets": []}


def test_command_router_supports_slash_commands_palette_and_context_filtering() -> None:
    router = CommandRouter()
    context = CommandContext(mode="Writer 分层生成", stage="batch_review", has_artifact=True)

    assert router.parse("/writer", context).handler_name == "start_writer"
    assert router.parse("/tasks", context).handler_name == "list_tasks"
    assert router.parse("/task couple", context).handler_name == "select_task"
    assert router.parse("/new-task couple ./couple.txt", context).handler_name == "create_task"
    assert router.parse("/delete-task couple", context).handler_name == "delete_task"
    assert router.parse("/reset-close-read", context).handler_name == "reset_close_read"
    assert router.parse("/query summary", context).handler_name == "query_close_read"
    assert router.parse("/benchmark longzu-32kb", context).handler_name == "run_smoke_benchmark"
    assert router.parse("/creative-kb-benchmark longzu-32kb", context).handler_name == "run_creative_kb_benchmark"
    assert router.parse("/kb-benchmark --writer-ab", context).handler_name == "run_creative_kb_benchmark"
    assert router.parse("/benchmark --source novel_agent/tests/longzu_32kb.txt", context).args == (
        "--source",
        "novel_agent/tests/longzu_32kb.txt",
    )
    assert router.parse("/confirm", context).handler_name == "confirm_current_step"
    assert router.parse("\x10", context).handler_name == "show_command_palette"
    assert "/read  导入或继续原文；/read --all 完整导入原文、阅读并更新 KB" in router.render_panel(context)
    assert "/delete-task  删除任务及本地建模产物" in router.render_panel(context)
    assert "/close-read  开始阅读；用法 /close-read [source_path] [--batches N]" in router.render_panel(context)
    assert "/benchmark  运行端到端 Agentic benchmark" in router.render_panel(context)
    assert "/creative-kb-benchmark  运行 Creative KB Benchmark" in router.render_panel(context)
    assert "--document-kb KB" in router.render_panel(context)
    assert "默认跑完全部剩余已导入 documents" in router.render_panel(context)
    panel = router.command_panel(context)
    assert "Writer" in panel
    assert any(command.command_id == "save" for command in panel["artifact"])

    no_artifact_panel = router.command_panel(CommandContext(has_artifact=False))
    assert all(command.command_id != "save" for commands in no_artifact_panel.values() for command in commands)


def test_workflow_facade_lists_tasks_with_close_read_completion(tmp_path: Path) -> None:
    facade = WorkflowFacade(repo_root=tmp_path)
    source_path = tmp_path / "source.txt"
    source_path.write_text("第一章\n旧案开始。", encoding="utf-8")
    facade.ensure_task(book_id="couple", source_path=str(source_path))
    db = NovelAgentDB(facade.db_path_for_book("couple"))
    with db.connect() as conn:
        db.init_schema(conn)
        conn.execute(
            """
            INSERT INTO documents(book_id, content, source_path, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?)
            """,
            ("couple", "第一章", str(source_path), "now", "now"),
        )
        conn.execute(
            """
            INSERT INTO chapters(
                book_id, document_title_index, chapter_title, source_doc_start_id, source_doc_end_id,
                source_doc_count, source_total_chars, created_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            ("couple", 1, "第一章", 1, 1, 1, 3, "now", "now"),
        )
        for stage in (DEFAULT_SEGMENTATION_STAGE, DEFAULT_CLOSE_READING_STAGE):
            conn.execute(
                """
                INSERT INTO reading_progress(book_id, agent_stage, last_completed_doc_id, updated_at)
                VALUES (?, ?, ?, ?)
                """,
                ("couple", stage, 1, "now"),
            )
        conn.commit()

    rendered = facade.render_task_list(active_book_id="couple")

    assert "* couple" in rendered


def test_workflow_facade_smoke_benchmark_output_prioritizes_reviewer_summary(
    tmp_path: Path,
    monkeypatch,  # type: ignore[no-untyped-def]
) -> None:
    class _FakeRunService:
        def __init__(self, *, repo_root: Path) -> None:
            self.repo_root = repo_root

        def run_longzu_32kb(self, **kwargs):  # type: ignore[no-untyped-def]
            return _fake_agentic_smoke_result(tmp_path)

    monkeypatch.setattr("novel_agent.app.cli.facade.AgenticSmokeBenchmarkService", _FakeRunService)

    payload = WorkflowFacade(repo_root=tmp_path).run_smoke_benchmark(target="longzu-32kb")

    assert payload["reviewer_summary"] == "中文 Reviewer 结论"
    assert "中文 Reviewer 结论" in payload["summary_text"]
    assert str(tmp_path / "runs" / "run-1") in payload["summary_text"]


def test_tui_app_benchmark_command_renders_reviewer_summary(tmp_path: Path) -> None:
    class _FacadeWithBenchmark:
        def run_smoke_benchmark(self, **kwargs):  # type: ignore[no-untyped-def]
            assert kwargs["target"] == "longzu-32kb"
            return {"summary_text": "Reviewer：中文结论\n产物目录：/tmp/run"}

    app = TuiApp(repo_root=tmp_path, facade=_FacadeWithBenchmark())  # type: ignore[arg-type]

    rendered = app.dispatch_command("/benchmark longzu-32kb")

    assert "Reviewer：中文结论" in rendered
    assert "产物目录" in rendered


def test_tui_app_benchmark_outline_research_author_brief_flags(tmp_path: Path) -> None:
    class _FacadeWithOutlineBenchmark:
        def run_smoke_benchmark(self, **kwargs):  # type: ignore[no-untyped-def]
            assert kwargs["target"] == "longzu-240kb"
            assert kwargs["enable_outline_research_loop"] is True
            assert kwargs["outline_research_author_brief"] is True
            return {
                "summary_text": (
                    "OutlineResearchReviewer：通过 (pass, 0.80)\n"
                    "artifact_dir：/tmp/outline_research_author_brief\n"
                    "leakage_audit：/tmp/leakage_audit.json"
                )
            }

    app = TuiApp(repo_root=tmp_path, facade=_FacadeWithOutlineBenchmark())  # type: ignore[arg-type]

    rendered = app.dispatch_command("/benchmark longzu-240kb --outline-research --author-brief")

    assert "OutlineResearchReviewer" in rendered
    assert "leakage_audit" in rendered


def test_tui_app_creative_kb_benchmark_command_renders_summary(tmp_path: Path) -> None:
    class _FacadeWithCreativeKBBenchmark:
        def run_creative_kb_benchmark(self, **kwargs):  # type: ignore[no-untyped-def]
            assert kwargs["target"] == "longzu-32kb"
            assert kwargs["enable_writer_ab"] is True
            assert kwargs["dry_run_model"] is True
            return {"summary_text": "Creative KB Benchmark\n建卡质量：pass / 0.72\nartifact_dir：/tmp/kb"}

    app = TuiApp(repo_root=tmp_path, facade=_FacadeWithCreativeKBBenchmark())  # type: ignore[arg-type]

    rendered = app.dispatch_command("/creative-kb-benchmark longzu-32kb --writer-ab --dry-run-model")

    assert "Creative KB Benchmark" in rendered
    assert "artifact_dir" in rendered


def test_workflow_facade_scoped_revision_boundary_payload_is_thin(tmp_path: Path) -> None:
    class _CaptureFacade(WorkflowFacade):
        def __init__(self, *, repo_root: Path) -> None:
            super().__init__(repo_root=repo_root)
            self.calls: list[dict[str, object]] = []

        def writer_action(self, **kwargs):  # type: ignore[no-untyped-def]
            self.calls.append(dict(kwargs))
            if kwargs["action"] == "request_scoped_artifact_revision":
                return {
                    "status": "candidate",
                    "request_id": "req-1",
                    "revision_id": "rev-1",
                    "change_summary": "已按反馈调整当前产物。",
                    "diff": "- old\n+ new",
                    "validation": {"ok": True},
                }
            return {
                "status": "applied",
                "request_id": kwargs["payload"]["request_id"],
                "revision_id": "rev-1",
                "change_summary": "已按反馈调整当前产物。",
                "diff": "- old\n+ new",
                "validation": {"ok": True, "applied": True},
            }

    facade = _CaptureFacade(repo_root=tmp_path)

    candidate = facade.request_scoped_artifact_revision(
        book_id="couple",
        run_id="run-1",
        current_review_state="batch_review",
        target_artifact_path="/tmp/batch_plan.json",
        user_feedback="把反派登场提前。",
    )
    applied = facade.apply_scoped_artifact_revision(book_id="couple", run_id="run-1", request_id="req-1")

    request_payload = facade.calls[0]["payload"]
    assert request_payload == {
        "user_feedback": "把反派登场提前。",
        "target_stage": "batch_review",
        "target_artifact_path": "/tmp/batch_plan.json",
    }
    assert "prompt" not in request_payload
    assert "allowed_context" not in request_payload
    assert "revised_artifact" not in request_payload
    assert facade.calls[1]["payload"] == {"request_id": "req-1"}
    assert candidate["diff"] == "- old\n+ new"
    assert applied["status"] == "applied"


def _fake_agentic_smoke_result(tmp_path: Path) -> SimpleNamespace:
    return SimpleNamespace(
        run_id="run-1",
        run_dir=str(tmp_path / "runs" / "run-1"),
        book_id="book-1",
        source_path=str(tmp_path / "source.txt"),
        prefix_source_path=str(tmp_path / "source_prefix.txt"),
        db_path=str(tmp_path / "novel.db"),
        writer_run_dir=str(tmp_path / "writer_runs" / "run-1"),
        draft_path=str(tmp_path / "writer_runs" / "run-1" / "draft.md"),
        reference_truth_path=str(tmp_path / "reference_truth.txt"),
        generated_synopsis_path=str(tmp_path / "generated_story_synopsis.json"),
        reference_synopsis_path=str(tmp_path / "reference_story_synopsis.json"),
        synopsis_reviewer_report_path=str(tmp_path / "synopsis_reviewer_report.json"),
        expansion_prompt_path=str(tmp_path / "expansion" / "prompt.json"),
        expansion_reviewer_report_path=str(tmp_path / "expansion_reviewer_report.json"),
        reviewer_report_path=str(tmp_path / "reviewer_report.json"),
        summary_path=str(tmp_path / "summary.json"),
        generated_chars=12,
        reference_truth_chars=8,
        synopsis_decision="pass",
        synopsis_score=0.7,
        synopsis_summary="梗概层中文结论",
        expansion_decision="pass",
        expansion_score=0.62,
        expansion_summary="扩写层中文结论",
        reviewer_decision="pass",
        reviewer_score=0.66,
        reviewer_summary="中文 Reviewer 结论",
        to_dict=lambda: {
            "run_id": "run-1",
            "run_dir": str(tmp_path / "runs" / "run-1"),
            "reviewer_summary": "中文 Reviewer 结论",
            "reviewer_decision": "pass",
            "reviewer_score": 0.66,
            "synopsis_summary": "梗概层中文结论",
            "synopsis_decision": "pass",
            "synopsis_score": 0.7,
            "expansion_summary": "扩写层中文结论",
            "expansion_decision": "pass",
            "expansion_score": 0.62,
            "generated_synopsis_path": str(tmp_path / "generated_story_synopsis.json"),
            "reference_synopsis_path": str(tmp_path / "reference_story_synopsis.json"),
            "draft_path": str(tmp_path / "writer_runs" / "run-1" / "draft.md"),
            "reference_truth_path": str(tmp_path / "reference_truth.txt"),
            "generated_chars": 12,
            "reference_truth_chars": 8,
        },
    )
    assert "documents=1" in rendered
    assert "chapters=1" in rendered
    assert "阅读完成" in rendered
    assert str(source_path) in rendered


def test_task_list_infers_segmentation_progress_from_source_offset(tmp_path: Path) -> None:
    facade = WorkflowFacade(repo_root=tmp_path)
    source_path = tmp_path / "source.txt"
    source_path.write_text("第一章\n旧案开始。", encoding="utf-8")
    facade.ensure_task(book_id="couple", source_path=str(source_path))
    db = NovelAgentDB(facade.db_path_for_book("couple"))
    with db.connect() as conn:
        db.init_schema(conn)
        for content in ("第一章", "第二章"):
            conn.execute(
                """
                INSERT INTO documents(book_id, content, source_path, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?)
                """,
                ("couple", content, str(source_path), "now", "now"),
            )
        conn.execute(
            """
            INSERT INTO reading_progress(
                book_id, agent_stage, current_source_path, current_source_offset, last_completed_doc_id, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?)
            """,
            ("couple", DEFAULT_SEGMENTATION_STAGE, str(source_path), 42, None, "now"),
        )
        conn.execute(
            """
            INSERT INTO reading_progress(book_id, agent_stage, last_completed_doc_id, updated_at)
            VALUES (?, ?, ?, ?)
            """,
            ("couple", DEFAULT_CLOSE_READING_STAGE, 2, "now"),
        )
        conn.commit()

    rendered = facade.render_task_list(active_book_id="couple")

    assert "导入原文至 doc 2/2" in rendered
    assert "阅读完成" in rendered


def test_workflow_facade_reset_close_read_keeps_documents_and_clears_progress(tmp_path: Path) -> None:
    facade = WorkflowFacade(repo_root=tmp_path)
    source_path = tmp_path / "source.txt"
    source_path.write_text("第一章\n旧案开始。", encoding="utf-8")
    facade.ensure_task(book_id="couple", source_path=str(source_path))
    world_path = tmp_path / ".memory" / "world" / "couple.summary.md"
    world_path.parent.mkdir(parents=True, exist_ok=True)
    world_path.write_text("旧世界观", encoding="utf-8")
    db = NovelAgentDB(facade.db_path_for_book("couple"))
    with db.connect() as conn:
        db.init_schema(conn)
        conn.execute(
            """
            INSERT INTO documents(book_id, content, source_path, character_keywords_json, content_tags_csv, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            ("couple", "第一章", str(source_path), '["沈青"]', "tag", "now", "now"),
        )
        conn.execute(
            """
            INSERT INTO chapters(
                book_id, document_title_index, chapter_title, source_doc_start_id, source_doc_end_id,
                source_doc_count, source_total_chars, created_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            ("couple", 1, "第一章", 1, 1, 1, 3, "now", "now"),
        )
        conn.execute(
            """
            INSERT INTO character_profiles(book_id, canonical_name, created_at, updated_at)
            VALUES (?, ?, ?, ?)
            """,
            ("couple", "沈青", "now", "now"),
        )
        for stage in (DEFAULT_SEGMENTATION_STAGE, DEFAULT_CLOSE_READING_STAGE):
            conn.execute(
                """
                INSERT INTO reading_progress(book_id, agent_stage, last_completed_doc_id, updated_at)
                VALUES (?, ?, ?, ?)
                """,
                ("couple", stage, 1, "now"),
            )
        conn.commit()

    result = facade.reset_close_read_task(book_id="couple")

    assert result["deleted"]["chapters"] == 1
    assert result["deleted"]["character_profiles"] == 1
    assert result["deleted"]["close_read_progress"] == 1
    assert result["deleted"]["files"] == 1
    assert not world_path.exists()
    with db.connect() as conn:
        db.init_schema(conn)
        assert conn.execute("SELECT COUNT(*) FROM documents WHERE book_id = ?", ("couple",)).fetchone()[0] == 1
        assert conn.execute("SELECT COUNT(*) FROM chapters WHERE book_id = ?", ("couple",)).fetchone()[0] == 0
        assert (
            conn.execute(
                "SELECT COUNT(*) FROM reading_progress WHERE book_id = ? AND agent_stage = ?",
                ("couple", DEFAULT_SEGMENTATION_STAGE),
            ).fetchone()[0]
            == 1
        )
        assert (
            conn.execute(
                "SELECT COUNT(*) FROM reading_progress WHERE book_id = ? AND agent_stage = ?",
                ("couple", DEFAULT_CLOSE_READING_STAGE),
            ).fetchone()[0]
            == 0
        )
        row = conn.execute("SELECT character_keywords_json, content_tags_csv FROM documents WHERE book_id = ?", ("couple",)).fetchone()
        assert row["character_keywords_json"] == "[]"
        assert row["content_tags_csv"] == ""


def test_workflow_facade_delete_task_previews_and_removes_local_artifacts(tmp_path: Path) -> None:
    facade = WorkflowFacade(repo_root=tmp_path)
    source_path = tmp_path / "source.txt"
    source_path.write_text("第一章\n旧案开始。", encoding="utf-8")
    facade.ensure_task(book_id="couple", source_path=str(source_path))
    db_path = facade.db_path_for_book("couple")
    db_path.parent.mkdir(parents=True, exist_ok=True)
    db_path.write_text("db", encoding="utf-8")
    wal_path = Path(f"{db_path}-wal")
    wal_path.write_text("wal", encoding="utf-8")
    world_path = tmp_path / ".memory" / "worlds" / "couple.world.md"
    world_path.parent.mkdir(parents=True, exist_ok=True)
    world_path.write_text("world", encoding="utf-8")
    writer_memory_dir = tmp_path / ".memory" / "writer" / "couple"
    writer_memory_dir.mkdir(parents=True)
    (writer_memory_dir / "state.json").write_text("{}", encoding="utf-8")

    preview = facade.delete_task(book_id="couple")

    assert preview["confirmed"] is False
    assert str(db_path) in preview["candidate_paths"]  # type: ignore[operator]
    assert db_path.exists()
    assert source_path.exists()

    result = facade.delete_task(book_id="couple", confirm=True)

    assert result["confirmed"] is True
    assert str(db_path) in result["deleted_paths"]  # type: ignore[operator]
    assert not db_path.exists()
    assert not wal_path.exists()
    assert not world_path.exists()
    assert not writer_memory_dir.exists()
    assert source_path.exists()
    assert "couple" not in facade.render_task_list(active_book_id="")


def test_decision_panel_maps_blocking_choices_to_user_visible_next_status() -> None:
    panel = DecisionPanel.chapter_acceptance(draft_path="/tmp/draft.md", draft_chars=4820, target_chars=5000)
    rendered = panel.render()

    assert "提交本章正文 -> 提交正文并更新续写记忆" in rendered
    assert "调整字数后重写 -> 请确认章节长度与节奏" in rendered
    assert "修改章节梗概后重写 -> 请调整章节规划后重写" in rendered
    assert "作废本次草稿 -> 流程已暂停" in rendered
    assert "稍后再决定 -> 请决定当前章节草稿" in rendered
    assert panel.choose("2").workflow_action == "show_chapter_acceptance_form"
    assert panel.choose("2").payload == {"status": "revise_length"}
    assert panel.choose("3").workflow_action == "show_chapter_acceptance_form"
    assert panel.choose("3").payload == {"status": "replan_chapter"}


def test_prompt_writer_review_uses_public_status_copy_and_save_guidance(
    tmp_path: Path,
    monkeypatch,
    capsys,
) -> None:
    artifact_path = tmp_path / "chapter_execution_input.json"
    artifact_path.write_text(
        json.dumps(
            {
                "chapter_id": "chapter-001",
                "length_budget": {"target_chars": 2400},
                "forbidden_items": ["不得提前揭晓真相"],
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr("builtins.input", lambda _prompt: "n")

    confirmed = run_interactive._prompt_writer_review("freeze_d_review", str(artifact_path))  # noqa: SLF001
    output = capsys.readouterr().out

    assert confirmed is False
    assert "请确认本章写作材料" in output
    assert "保存只是保留修改" in output
    assert "保存不等于确认" in output
    for token in WriterStatusPresenter.FORBIDDEN_PUBLIC_TOKENS:
        assert token not in output


class _FakeFacade:
    def __init__(self, repo_root: Path) -> None:
        self.repo_root = repo_root
        self.steps: list[str] = []

    def modeling_status(self, *, book_id: str, db_path: Path | None = None):  # type: ignore[no-untyped-def]
        self.steps.append("status")
        return type(
            "Snapshot",
            (),
            {
                "close_read_ready": True,
                "ready_map": lambda _self: {"原文": True, "阅读记忆": True, "桥段 KB": True},
            },
        )()

    def start_writer(self, **_kwargs):  # type: ignore[no-untyped-def]
        self.steps.append("writer")
        return {"status": "waiting_for_review", "checkpoint": {"stage": "batch_review"}}


def test_tui_app_keeps_message_artifact_status_and_input_regions_separate(tmp_path: Path) -> None:
    facade = _FakeFacade(tmp_path)
    app = TuiApp(
        repo_root=tmp_path,
        config=TuiSessionConfig(project="Couple", book_id="couple", width=100),
        facade=facade,  # type: ignore[arg-type]
    )
    app.set_status("batch_review", technical_details={"run_id": "run-1"})
    artifact = tmp_path / "batch_plan.json"
    artifact.write_text(json.dumps({"stage_goal": "继续追查"}, ensure_ascii=False), encoding="utf-8")
    app.show_artifact(artifact, stage="batch_review")
    app.input_buffer.insert("开始续写")

    rendered = app.render(width=100)

    assert "[消息流]" in rendered
    assert "[产物审阅]" in rendered
    assert "[状态侧栏]" in rendered
    assert "[输入区 / 决策面板]" in rendered
    assert "开始续写" in rendered
    assert "请审阅本批剧情大纲" in rendered
    for token in StatusPresenter.FORBIDDEN_PUBLIC_TOKENS:
        assert token not in rendered.replace("技术详情", "")


def test_read_to_writer_minimal_path_in_one_tui_session(tmp_path: Path) -> None:
    facade = _FakeFacade(tmp_path)
    app = TuiApp(
        repo_root=tmp_path,
        config=TuiSessionConfig(project="Couple", book_id="couple"),
        facade=facade,  # type: ignore[arg-type]
    )

    snapshot = facade.modeling_status(book_id="couple")
    assert snapshot.ready_map()["阅读记忆"] is True
    writer_result = facade.start_writer(book_id="couple")
    app.set_status(writer_result["checkpoint"]["stage"])

    assert facade.steps == ["status", "writer"]
    assert app.current_status.step == "请审阅本批剧情大纲"

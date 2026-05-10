from __future__ import annotations

import asyncio
import json
import os
import threading
from pathlib import Path

import pytest
from rich.align import Align
from rich.panel import Panel
from textual.widgets import Static, TextArea

from novel_agent.app.cli import (
    ArtifactEditorPane,
    CommandPalette,
    DecisionPanel,
    DecisionPanelWidget,
    MessageFlow,
    PromptInput,
    ScopedRevisionFeedbackWidget,
    StatusOverlay,
    TextualNovelAgentApp,
    TuiApp,
    TuiSessionConfig,
    WorkbenchScreen,
)
from novel_agent.app.cli.events import RunEvent


class _TextualFakeFacade:
    def __init__(self, repo_root: Path) -> None:
        self.repo_root = repo_root
        self.calls: list[str] = []
        self.call_records: list[dict[str, object]] = []
        self.read_runs: list[dict[str, object]] = []
        self.benchmark_runs: list[dict[str, object]] = []
        self.creative_kb_benchmark_runs: list[dict[str, object]] = []
        self.failures: dict[str, Exception] = {}
        self.last_read_kwargs: dict[str, object] = {}
        self.scoped_revision_requests: list[dict[str, object]] = []
        self.scoped_revision_applies: list[dict[str, object]] = []
        self.next_scoped_revision_result: dict[str, object] | None = None

    def fail_next(self, operation: str, exc: Exception) -> None:
        self.failures[operation] = exc

    def _record(self, operation: str, **payload: object) -> None:
        self.call_records.append({"operation": operation, **payload})

    def _raise_if_configured(self, *keys: str) -> None:
        for key in keys:
            exc = self.failures.pop(key, None)
            if exc is not None:
                raise exc

    def db_path_for_book(self, book_id: str) -> Path:
        return self.repo_root / ".indexes" / f"{book_id}.db"

    def ensure_task(self, *, book_id: str, source_path: str = ""):  # type: ignore[no-untyped-def]
        return type(
            "Task",
            (),
            {
                "book_id": book_id,
                "source_path": source_path,
                "render_status_line": lambda _self, active=False: f"{'* ' if active else '  '}{book_id} · source={source_path}",
            },
        )()

    def render_task_list(self, *, active_book_id: str = "") -> str:
        return f"当前任务：\n* {active_book_id or 'couple'} · documents=2 · chapters=1 · 精读完成"

    def reset_close_read_task(self, *, book_id: str):  # type: ignore[no-untyped-def]
        self.calls.append("reset_close_read")
        return {
            "book_id": book_id,
            "deleted": {
                "chapters": 1,
                "character_profiles": 1,
                "close_read_progress": 1,
                "files": 1,
            },
        }

    def query_close_read(
        self,
        *,
        book_id: str,
        query_type: str,
        character_name: str = "",
        document_title_index: int | None = None,
        doc_id: int | None = None,
        summary_scope: str = "all",
        output_format: str = "markdown",
    ) -> str:
        self.calls.append(
            f"query:{book_id}:{query_type}:{character_name}:{document_title_index}:{doc_id}:{summary_scope}:{output_format}"
        )
        if query_type == "character":
            return f"# 人物档案：{book_id}\n\n## {character_name or '沈青'}\n\n已建档人物。"
        if summary_scope == "total":
            return f"# 当前精读总览：{book_id}\n\n- chapter_count: 2"
        if document_title_index is not None:
            return f"# 剧情概括：document {document_title_index}：{book_id}\n\n## [{document_title_index}] 第二章 旧楼"
        return f"# 剧情概括：{book_id}\n\n## [1] 第一章 雨夜\n\n旧案开始。"

    def start_read_pipeline(self, **kwargs):  # type: ignore[no-untyped-def]
        self.calls.append("read")
        self.last_read_kwargs = dict(kwargs)
        self.read_runs.append(dict(kwargs))
        run_mode = str(kwargs.get("run_mode") or "new")
        self._record(f"read:{run_mode}", kwargs=dict(kwargs))
        return {
            "inserted_documents": 2,
            "segmentation_batches": 1,
            "close_read_batches": 1,
            "segmentation_progress_chars": 1200,
            "close_read_progress_chars": 800,
        }

    def build_creative_kb(self, **_kwargs):  # type: ignore[no-untyped-def]
        self.calls.append("kb")
        self._record("kb")
        return {"fragment_cards": 3, "clusters": 1, "representatives": 1}

    def start_writer(self, **_kwargs):  # type: ignore[no-untyped-def]
        self.calls.append("writer")
        self._record("writer")
        artifact_path = self.repo_root / "runs" / "writer" / "batch_plan.json"
        artifact_path.parent.mkdir(parents=True, exist_ok=True)
        artifact_path.write_text(json.dumps({"stage_goal": "继续追查"}, ensure_ascii=False), encoding="utf-8")
        return {
            "status": "waiting_for_review",
            "checkpoint": {
                "stage": "batch_review",
                "checkpoint_id": "ck-1",
                "artifact_path": str(artifact_path),
            },
        }

    def writer_action(self, **_kwargs):  # type: ignore[no-untyped-def]
        self.calls.append("writer_action")
        self._record("writer_action")
        return {"status": "chapter_review", "checkpoint": {"stage": "chapter_review"}}

    def request_scoped_artifact_revision(self, **kwargs):  # type: ignore[no-untyped-def]
        self.calls.append("request_scoped_artifact_revision")
        self._record("request_scoped_artifact_revision", kwargs=dict(kwargs))
        self.scoped_revision_requests.append(dict(kwargs))
        if self.next_scoped_revision_result is not None:
            return dict(self.next_scoped_revision_result)
        return {
            "status": "candidate",
            "request_id": "req-1",
            "revision_id": "rev-1",
            "change_summary": "把反派登场提前，并保留当前主线。",
            "diff": "- 反派第三章登场\n+ 反派第二章登场",
            "validation": {"ok": True, "checks": ["schema", "scope"]},
        }

    def apply_scoped_artifact_revision(self, **kwargs):  # type: ignore[no-untyped-def]
        self.calls.append("apply_scoped_artifact_revision")
        self._record("apply_scoped_artifact_revision", kwargs=dict(kwargs))
        self.scoped_revision_applies.append(dict(kwargs))
        artifact_path = self.scoped_revision_requests[-1]["target_artifact_path"]
        return {
            "status": "applied",
            "request_id": kwargs["request_id"],
            "revision_id": "rev-1",
            "artifact_path": str(artifact_path),
            "change_summary": "把反派登场提前，并保留当前主线。",
            "diff": "- 反派第三章登场\n+ 反派第二章登场",
            "validation": {"ok": True, "applied": True},
            "workflow_state": {
                "current_stage": "batch_review",
                "pending_checkpoint": {"stage": "batch_review", "artifact_path": str(artifact_path)},
            },
        }

    def run_smoke_benchmark(self, **kwargs):  # type: ignore[no-untyped-def]
        self.calls.append("benchmark")
        self.benchmark_runs.append(dict(kwargs))
        target = str(kwargs.get("target") or "")
        self._record("benchmark", target=target, kwargs=dict(kwargs))
        self._raise_if_configured(f"benchmark:{target}", "benchmark")
        if target not in {"", "longzu-32kb"}:
            raise ValueError(f"未知 benchmark 目标：{target}")
        return {
            "summary_text": (
                "梗概层 Reviewer：CLI 梗概链路通过 (pass, 0.80)\n"
                "扩写层 Reviewer：CLI 正文链路通过 (pass, 0.82)\n"
                "综合 Reviewer：CLI 端到端链路通过 (pass, 0.81)\n"
                f"产物目录：{self.repo_root / 'runs' / 'benchmarks' / 'cli-smoke'}"
            )
        }

    def run_creative_kb_benchmark(self, **kwargs):  # type: ignore[no-untyped-def]
        self.calls.append("creative_kb_benchmark")
        self.creative_kb_benchmark_runs.append(dict(kwargs))
        target = str(kwargs.get("target") or "longzu-32kb")
        self._record("creative_kb_benchmark", target=target, kwargs=dict(kwargs))
        self._raise_if_configured(f"creative_kb_benchmark:{target}", "creative_kb_benchmark")
        return {
            "summary_text": (
                "Creative KB Benchmark\n"
                "建卡质量：pass / 0.72\n"
                "检索与 rerank：pass / 0.68\n"
                f"artifact_dir：{self.repo_root / 'runs' / 'creative_kb_benchmarks' / 'cli-smoke'}"
            )
        }


def _run(coro) -> None:  # type: ignore[no-untyped-def]
    asyncio.run(coro)


def _app(tmp_path: Path) -> TextualNovelAgentApp:
    session = TuiApp(
        repo_root=tmp_path,
        config=TuiSessionConfig(project="Couple", book_id="couple"),
        facade=_TextualFakeFacade(tmp_path),  # type: ignore[arg-type]
    )
    return TextualNovelAgentApp(repo_root=tmp_path, session=session)


class TuiSmokeHarness:
    def __init__(self, app: TextualNovelAgentApp, pilot) -> None:  # type: ignore[no-untyped-def]
        self.app = app
        self.pilot = pilot

    @property
    def prompt(self) -> PromptInput:
        return self.app.screen.query_one("#workbench-prompt", PromptInput)

    async def submit_command(self, command: str, *, wait_pauses: int = 24) -> str:
        self.prompt.value = command
        self.prompt.query_one("#prompt-text", TextArea).focus()
        await self.pilot.press("enter")
        await self.pilot.pause()
        assert self.prompt.value == ""
        rendered = self.app.session.messages.render(limit=100)
        assert f"你 · {command}" in rendered
        await self.wait_for_worker(wait_pauses=wait_pauses)
        return self.app.session.messages.render(limit=120)

    async def wait_for_worker(self, *, wait_pauses: int = 24) -> None:
        for _ in range(wait_pauses):
            await self.pilot.pause()
            if not getattr(self.app.screen, "running_worker_name", ""):
                return
        pytest.fail(f"worker still running: {getattr(self.app.screen, 'running_worker_name', '')}")

    async def assert_prompt_editable(self, value: str = "失败后仍可继续编辑") -> None:
        self.prompt.value = value
        self.prompt.query_one("#prompt-text", TextArea).focus()
        await self.pilot.pause()
        assert self.prompt.value == value

    def rendered(self, *, limit: int = 120) -> str:
        return self.app.session.messages.render(limit=limit)


def test_home_screen_is_prompt_first_and_actions_are_split_by_line(tmp_path: Path) -> None:
    async def scenario() -> None:
        app = _app(tmp_path)
        async with app.run_test(size=(100, 30)) as pilot:
            await pilot.pause()
            assert type(app.screen).__name__ == "HomeScreen"
            actions = str(app.screen.query_one("#home-actions-text", Static).render())
            assert "1  选择或创建任务\n2  继续上次会话" in actions
            assert "6  查看精读产物" in actions
            assert "8  运行最小续写回归" in actions
            assert "9  开始或恢复 Writer" in actions
            assert app.screen.query_one("#home-prompt", PromptInput).value == ""

    _run(scenario())


def test_workbench_wide_layout_and_background_events_keep_prompt_stable(tmp_path: Path) -> None:
    async def scenario() -> None:
        app = _app(tmp_path)
        async with app.run_test(size=(120, 36)) as pilot:
            app.open_workbench(initial_status="batch_review")
            await pilot.pause()
            screen = app.screen
            assert isinstance(screen, WorkbenchScreen)
            assert screen.query_one("#message-flow")
            assert screen.query_one("#artifact-review")
            assert screen.query_one("#status-sidebar")
            prompt = screen.query_one("#workbench-prompt", PromptInput)
            assert prompt.query_one("#prompt-text", TextArea).size.height >= 5
            prompt.value = "用户仍在编辑"
            app.session.event_stream.emit("进度", "正在精读章节", payload={"stage": "close_reading"})
            screen.refresh_all()
            await pilot.pause()
            assert prompt.value == "用户仍在编辑"

    _run(scenario())


def test_prompt_enter_submits_clears_and_records_command_as_chat(tmp_path: Path) -> None:
    async def scenario() -> None:
        app = _app(tmp_path)
        async with app.run_test(size=(120, 36)) as pilot:
            app.open_workbench()
            await pilot.pause()
            prompt = app.screen.query_one("#workbench-prompt", PromptInput)
            prompt.value = "/status"
            prompt.query_one("#prompt-text", TextArea).focus()
            await pilot.press("enter")
            await pilot.pause()
            rendered = app.session.messages.render(limit=20)
            assert prompt.value == ""
            assert "你 · /status" in rendered
            assert "当前项目" in rendered

    _run(scenario())


def test_message_flow_renders_user_messages_as_right_aligned_bubble() -> None:
    rendered = MessageFlow.render_event(RunEvent("你", "/status"))

    assert isinstance(rendered, Align)
    assert rendered.align == "right"
    assert isinstance(rendered.renderable, Panel)


def test_prompt_shift_enter_keeps_multiline_editing(tmp_path: Path) -> None:
    async def scenario() -> None:
        app = _app(tmp_path)
        async with app.run_test(size=(120, 36)) as pilot:
            app.open_workbench()
            await pilot.pause()
            prompt = app.screen.query_one("#workbench-prompt", PromptInput)
            prompt.value = "第一行"
            prompt.query_one("#prompt-text", TextArea).focus()
            await pilot.press("shift+enter")
            await pilot.pause()
            assert prompt.value == "第一行\n"

    _run(scenario())


def test_invalid_prompt_command_shows_chat_style_error_guidance(tmp_path: Path) -> None:
    async def scenario() -> None:
        app = _app(tmp_path)
        async with app.run_test(size=(120, 36)) as pilot:
            app.open_workbench()
            await pilot.pause()
            prompt = app.screen.query_one("#workbench-prompt", PromptInput)
            prompt.value = "/wat"
            prompt.query_one("#prompt-text", TextArea).focus()
            await pilot.press("enter")
            await pilot.pause()
            rendered = app.session.messages.render(limit=20)
            assert prompt.value == ""
            assert "你 · /wat" in rendered
            assert "错误 · 未知或当前不可用的命令：/wat" in rendered
            assert "建议 · 输入 /help 查看当前可用命令" in rendered

    _run(scenario())


def test_task_commands_list_create_and_select_active_task(tmp_path: Path) -> None:
    async def scenario() -> None:
        app = _app(tmp_path)
        source_path = tmp_path / "source.txt"
        source_path.write_text("第一章\n旧案开始。", encoding="utf-8")
        async with app.run_test(size=(120, 36)) as pilot:
            app.open_workbench()
            await pilot.pause()
            screen = app.screen
            assert isinstance(screen, WorkbenchScreen)
            screen.handle_command("/tasks")
            await pilot.pause()
            assert "当前任务" in app.session.messages.render(limit=20)
            screen.handle_command(f"/new-task fresh {source_path}")
            await pilot.pause()
            assert app.session.config.book_id == "fresh"
            assert app.session.config.source_path == str(source_path)
            screen.handle_command("/task couple")
            await pilot.pause()
            assert app.session.config.book_id == "couple"

    _run(scenario())


def test_reset_close_read_command_targets_current_task(tmp_path: Path) -> None:
    async def scenario() -> None:
        app = _app(tmp_path)
        async with app.run_test(size=(120, 36)) as pilot:
            app.open_workbench()
            await pilot.pause()
            screen = app.screen
            assert isinstance(screen, WorkbenchScreen)
            screen.handle_command("/reset-close-read")
            await pilot.pause()
            assert "请先选择 task id" not in app.session.messages.render(limit=20)
            assert "已清空任务 couple 的精读进度" in app.session.messages.render(limit=20)
            assert "reset_close_read" in app.session.facade.calls  # type: ignore[attr-defined]

    _run(scenario())


def test_close_read_without_task_shows_usage_guidance(tmp_path: Path) -> None:
    async def scenario() -> None:
        app = _app(tmp_path)
        app.session.config.book_id = ""
        async with app.run_test(size=(120, 36)) as pilot:
            app.open_workbench()
            await pilot.pause()
            screen = app.screen
            assert isinstance(screen, WorkbenchScreen)
            screen.handle_command("/close-read")
            await pilot.pause()
            rendered = app.session.messages.render(limit=20)
            assert "请先选择 task id" in rendered
            assert "用法：先 /task <task_id> 或 /new-task <task_id> <source_path>，再执行 /close-read [source_path] [--batches N]" in rendered
            assert "默认 N=1" in rendered

    _run(scenario())


def test_close_read_batches_option_controls_work_amount_and_announces_default_budget(tmp_path: Path) -> None:
    async def scenario() -> None:
        app = _app(tmp_path)
        async with app.run_test(size=(120, 36)) as pilot:
            app.open_workbench()
            await pilot.pause()
            screen = app.screen
            assert isinstance(screen, WorkbenchScreen)
            screen.handle_command("/close-read --batches 3")
            await pilot.pause()
            rendered = app.session.messages.render(limit=20)
            assert "最多 3 个精读 batch" in rendered
            assert "约 20000 字文档预算" in rendered
            assert app.session.facade.last_read_kwargs["max_close_batches"] == 3  # type: ignore[attr-defined]
            assert app.session.facade.last_read_kwargs["close_step_batches"] == 1  # type: ignore[attr-defined]
            assert app.session.facade.last_read_kwargs["build_creative_kb"] is True  # type: ignore[attr-defined]

    _run(scenario())


def test_query_close_read_command_renders_current_task_outputs(tmp_path: Path) -> None:
    async def scenario() -> None:
        app = _app(tmp_path)
        async with app.run_test(size=(120, 36)) as pilot:
            app.open_workbench()
            await pilot.pause()
            screen = app.screen
            assert isinstance(screen, WorkbenchScreen)
            screen.handle_command("/query character 沈青")
            await pilot.pause()
            rendered = app.session.messages.render(limit=20)
            assert "# 人物档案：couple" in rendered
            assert "## 沈青" in rendered
            assert "query:couple:character:沈青:None:None:all:markdown" in app.session.facade.calls  # type: ignore[attr-defined]

    _run(scenario())


def test_query_summary_command_supports_document_and_total_selectors(tmp_path: Path) -> None:
    async def scenario() -> None:
        app = _app(tmp_path)
        async with app.run_test(size=(120, 36)) as pilot:
            app.open_workbench()
            await pilot.pause()
            screen = app.screen
            assert isinstance(screen, WorkbenchScreen)
            screen.handle_command("/query summary 2")
            screen.handle_command("/query summary total")
            await pilot.pause()
            rendered = app.session.messages.render(limit=20)
            assert "# 剧情概括：document 2：couple" in rendered
            assert "# 当前精读总览：couple" in rendered
            assert "query:couple:summary::2:None:document:markdown" in app.session.facade.calls  # type: ignore[attr-defined]
            assert "query:couple:summary::None:None:total:markdown" in app.session.facade.calls  # type: ignore[attr-defined]

    _run(scenario())


def test_narrow_layout_opens_status_overlay_without_removing_prompt(tmp_path: Path) -> None:
    async def scenario() -> None:
        app = _app(tmp_path)
        async with app.run_test(size=(60, 28)) as pilot:
            app.open_workbench(initial_status="batch_review")
            await pilot.pause()
            app.action_toggle_details()
            await pilot.pause()
            assert isinstance(app.screen, StatusOverlay)
            await pilot.press("escape")
            await pilot.pause()
            assert app._screen_stack[-1].query_one("#workbench-prompt", PromptInput)  # noqa: SLF001

    _run(scenario())


def test_slash_autocomplete_and_command_palette_filtering(tmp_path: Path) -> None:
    async def scenario() -> None:
        app = _app(tmp_path)
        async with app.run_test(size=(100, 32)) as pilot:
            app.open_workbench(initial_status="batch_review")
            await pilot.pause()
            prompt = app.screen.query_one("#workbench-prompt", PromptInput)
            prompt.value = "/"
            await pilot.pause()
            assert "/status" in str(app.screen.query_one("#slash-autocomplete", Static).render())
            app.action_command_palette()
            await pilot.pause()
            palette = app.screen
            assert isinstance(palette, CommandPalette)
            palette.refresh_commands("续写")
            assert "/writer" in str(palette.query_one("#command-list", Static).render())
            palette.refresh_commands("保存")
            assert "当前不可用" in str(palette.query_one("#command-list", Static).render())

    _run(scenario())


def test_artifact_reference_autocomplete_uses_virtual_token(tmp_path: Path) -> None:
    async def scenario() -> None:
        app = _app(tmp_path)
        artifact_path = tmp_path / "batch_plan.json"
        artifact_path.write_text(json.dumps({"stage_goal": "继续追查"}, ensure_ascii=False), encoding="utf-8")
        async with app.run_test(size=(110, 34)) as pilot:
            app.open_workbench(initial_status="batch_review")
            await pilot.pause()
            screen = app.screen
            assert isinstance(screen, WorkbenchScreen)
            screen.show_artifact(artifact_path, stage="batch_review")
            await pilot.pause()
            prompt = screen.query_one("#workbench-prompt", PromptInput)
            prompt.value = "参考 @batch"
            await pilot.pause()
            rendered = str(screen.query_one("#artifact-autocomplete", Static).render())
            assert "[Artifact: batch_plan.json]" in rendered
            assert str(artifact_path) not in prompt.value

    _run(scenario())


def test_artifact_editor_save_success_and_validation_failure(tmp_path: Path) -> None:
    async def scenario() -> None:
        app = _app(tmp_path)
        artifact_path = tmp_path / "chapter_length_plan.json"
        artifact_path.write_text(json.dumps({"budgets": []}, ensure_ascii=False), encoding="utf-8")
        async with app.run_test(size=(110, 34)) as pilot:
            app.open_workbench(initial_status="wait_length_review")
            await pilot.pause()
            screen = app.screen
            assert isinstance(screen, WorkbenchScreen)
            screen.show_artifact(artifact_path, stage="wait_length_review")
            editor = screen.query_one("#artifact-editor", ArtifactEditorPane)
            editor.query_one("#artifact-editor-text", TextArea).load_text('{"budgets": {}}')
            failed = editor.save_current()
            assert failed.saved is False
            assert "budgets 必须是列表" in failed.validation_error
            editor.query_one("#artifact-editor-text", TextArea).load_text('{"budgets": []}')
            saved = editor.save_current()
            assert saved.saved is True
            assert saved.message == "已保存你的修改"

    _run(scenario())


def test_textual_worker_e2e_read_kb_writer_minimal_path(tmp_path: Path) -> None:
    async def scenario() -> None:
        app = _app(tmp_path)
        source_path = tmp_path / "source.txt"
        source_path.write_text("第一章\n旧案开始。", encoding="utf-8")
        async with app.run_test(size=(120, 40)) as pilot:
            app.open_workbench()
            await pilot.pause()
            screen = app.screen
            assert isinstance(screen, WorkbenchScreen)
            screen.handle_command(f"/read {source_path}")
            await pilot.pause()
            screen.handle_command("/kb")
            await pilot.pause()
            screen.handle_command("/writer")
            for _ in range(5):
                await pilot.pause()
            assert app.session.facade.calls == ["read", "kb", "writer"]  # type: ignore[attr-defined]
            assert app.session.current_status.step == "请审阅本批剧情大纲"
            assert app.session.current_artifact is not None
            assert app.session.current_artifact.path.name == "batch_plan.json"
            assert "artifact saved" not in app.session.messages.render()
            assert "batch_review" not in app.session.messages.render()

    _run(scenario())


def test_textual_close_read_worker_streams_document_progress_before_completion(tmp_path: Path) -> None:
    async def scenario() -> None:
        app = _app(tmp_path)
        progress_emitted = threading.Event()
        allow_finish = threading.Event()

        def start_read_pipeline(**_kwargs):  # type: ignore[no-untyped-def]
            app.session.event_stream.progress_callback(
                {
                    "stage": "close_reading",
                    "event": "batch_start",
                    "batch_index": 3,
                    "chapter_title": "旧楼追踪",
                    "first_doc_id": 7,
                    "last_doc_id": 9,
                    "completed_documents": 6,
                    "total_documents": 20,
                }
            )
            progress_emitted.set()
            allow_finish.wait(timeout=2)
            return {
                "inserted_documents": 0,
                "segmentation_batches": 0,
                "close_read_batches": 1,
                "segmentation_progress_chars": 2400,
                "close_read_progress_chars": 1800,
            }

        app.session.facade.start_read_pipeline = start_read_pipeline  # type: ignore[method-assign]
        async with app.run_test(size=(120, 40)) as pilot:
            app.open_workbench()
            await pilot.pause()
            prompt = app.screen.query_one("#workbench-prompt", PromptInput)
            prompt.value = "/close-read --batches 1"
            prompt.query_one("#prompt-text", TextArea).focus()
            await pilot.press("enter")

            for _ in range(20):
                await pilot.pause()
                rendered = app.session.messages.render(limit=80)
                if progress_emitted.is_set() and "正在精读：旧楼追踪（doc 7-9）" in rendered:
                    break
            else:
                raise AssertionError(app.session.messages.render(limit=80))

            assert getattr(app.screen, "running_worker_name", "") == "精读建模"
            assert "已完成 6/20 documents" in app.session.messages.render(limit=80)
            allow_finish.set()
            for _ in range(20):
                await pilot.pause()
                if not getattr(app.screen, "running_worker_name", ""):
                    break

    _run(scenario())


def test_textual_cli_scripted_smoke_covers_read_close_read_queries_and_benchmarks(tmp_path: Path) -> None:
    async def scenario() -> None:
        app = _app(tmp_path)
        source_path = tmp_path / "source.txt"
        source_path.write_text("第一章\n雨夜旧案开始。\n第二章\n人物关系出现裂痕。", encoding="utf-8")

        async with app.run_test(size=(120, 40)) as pilot:
            app.open_workbench()
            await pilot.pause()
            harness = TuiSmokeHarness(app, pilot)

            await harness.submit_command(f"/new-task smoke {source_path}")
            await harness.submit_command("/read")
            await harness.submit_command("/close-read --batches 2")
            await harness.submit_command("/query character 沈青")
            await harness.submit_command("/query summary total")
            await harness.submit_command("/benchmark longzu-32kb")
            await harness.submit_command("/creative-kb-benchmark longzu-32kb --writer-ab --dry-run-model")

            rendered = harness.rendered()
            facade = app.session.facade
            assert app.session.config.book_id == "smoke"
            assert app.session.config.source_path == str(source_path)
            assert facade.calls[:2] == ["read", "read"]  # type: ignore[attr-defined]
            assert "query:smoke:character:沈青:None:None:all:markdown" in facade.calls  # type: ignore[attr-defined]
            assert "query:smoke:summary::None:None:total:markdown" in facade.calls  # type: ignore[attr-defined]
            assert facade.calls[-2:] == ["benchmark", "creative_kb_benchmark"]  # type: ignore[attr-defined]
            assert [item["operation"] for item in facade.call_records if str(item["operation"]).startswith("read:")] == [  # type: ignore[attr-defined]
                "read:new",
                "read:resume",
            ]
            assert facade.read_runs[0]["run_mode"] == "new"  # type: ignore[attr-defined]
            assert facade.read_runs[0]["max_read_kb"] == 64  # type: ignore[attr-defined]
            assert facade.read_runs[1]["run_mode"] == "resume"  # type: ignore[attr-defined]
            assert facade.read_runs[1]["max_read_kb"] == 0  # type: ignore[attr-defined]
            assert facade.read_runs[1]["max_close_batches"] == 2  # type: ignore[attr-defined]
            assert facade.read_runs[1]["build_creative_kb"] is True  # type: ignore[attr-defined]
            assert facade.benchmark_runs[-1]["target"] == "longzu-32kb"  # type: ignore[attr-defined]
            assert facade.creative_kb_benchmark_runs[-1]["enable_writer_ab"] is True  # type: ignore[attr-defined]
            assert facade.creative_kb_benchmark_runs[-1]["dry_run_model"] is True  # type: ignore[attr-defined]
            assert "已创建并进入任务 smoke" in rendered
            assert "粗读/精读本轮已完成" in rendered
            assert "精读建模本轮已完成" in rendered
            assert "# 人物档案：smoke" in rendered
            assert "# 当前精读总览：smoke" in rendered
            assert "综合 Reviewer：CLI 端到端链路通过" in rendered
            assert "Creative KB Benchmark" in rendered
            assert "artifact_dir" in rendered
            assert "artifact saved" not in rendered

    _run(scenario())


def test_textual_cli_benchmark_failures_show_recovery_and_keep_prompt_editable(tmp_path: Path) -> None:
    async def scenario() -> None:
        app = _app(tmp_path)

        async with app.run_test(size=(120, 40)) as pilot:
            app.open_workbench()
            await pilot.pause()
            harness = TuiSmokeHarness(app, pilot)

            rendered = await harness.submit_command("/benchmark unknown-target")
            assert "你 · /benchmark unknown-target" in rendered
            assert "错误 · MVP smoke benchmark遇到问题：未知 benchmark 目标：unknown-target" in rendered
            assert "恢复建议" in rendered
            await harness.assert_prompt_editable()

            rendered = await harness.submit_command("/benchmark --case-count nope")
            assert "你 · /benchmark --case-count nope" in rendered
            assert "错误 · 未知 /benchmark 参数：--case-count" in rendered
            assert "/benchmark longzu-32kb" in rendered
            await harness.assert_prompt_editable()

            rendered = await harness.submit_command("/creative-kb-benchmark longzu-32kb")
            assert "你 · /creative-kb-benchmark longzu-32kb" in rendered
            assert "错误 · 请显式选择模型模式" in rendered
            assert "--dry-run-model" in rendered
            await harness.assert_prompt_editable()

            facade = app.session.facade
            facade.fail_next(  # type: ignore[attr-defined]
                "creative_kb_benchmark",
                FileExistsError(f"产物写入失败：artifact_dir {tmp_path / 'not-a-directory'} 已存在且不是目录"),
            )
            rendered = await harness.submit_command(
                f"/creative-kb-benchmark longzu-32kb --dry-run-model --artifact-dir {tmp_path / 'not-a-directory'}"
            )
            assert "产物写入失败" in rendered
            assert "恢复建议" in rendered
            await harness.assert_prompt_editable()

            facade.fail_next("creative_kb_benchmark", RuntimeError("Reviewer 失败：无法解析评分 JSON"))  # type: ignore[attr-defined]
            rendered = await harness.submit_command("/creative-kb-benchmark longzu-32kb --dry-run-model")
            assert "Reviewer 失败" in rendered
            assert "恢复建议" in rendered
            await harness.assert_prompt_editable()

    _run(scenario())


@pytest.mark.slow
@pytest.mark.timeout(900)
def test_real_llm_cli_tui_benchmark_smoke_is_explicitly_gated() -> None:
    if not os.getenv("NOVEL_AGENT_RUN_REAL_CLI_TUI_SMOKE"):
        pytest.skip("set NOVEL_AGENT_RUN_REAL_CLI_TUI_SMOKE=1 to run the real LLM CLI TUI smoke")

    async def scenario() -> None:
        repo_root = Path.cwd()
        session = TuiApp(repo_root=repo_root, config=TuiSessionConfig(project="Couple", book_id="real-smoke"))
        app = TextualNovelAgentApp(repo_root=repo_root, session=session)

        async with app.run_test(size=(120, 40)) as pilot:
            app.open_workbench()
            await pilot.pause()
            harness = TuiSmokeHarness(app, pilot)
            await harness.submit_command("/benchmark longzu-32kb --real", wait_pauses=900)
            rendered = harness.rendered(limit=160)
            has_reviewer_decision = any(token in rendered for token in ("pass", "fail", "borderline"))
            if not all(fragment in rendered for fragment in ("Reviewer", "产物目录", "综合 Reviewer")) or not has_reviewer_decision:
                runs_dir = repo_root / "runs" / "benchmarks"
                recent = sorted(runs_dir.glob("*"), key=lambda path: path.stat().st_mtime)[-3:] if runs_dir.exists() else []
                pytest.fail(
                    "真实 CLI TUI smoke 没有回流完整 Reviewer 摘要。\n"
                    f"最近产物：{[str(path) for path in recent]}\n"
                    "恢复建议：检查 DEEPSEEK_API_KEY、最近 runs/benchmarks 产物和 TUI 消息流错误。\n"
                    f"消息流：\n{rendered}"
                )

    _run(scenario())


def test_decision_panel_widget_chapter_acceptance_options() -> None:
    panel = DecisionPanel.chapter_acceptance(draft_path="/tmp/draft.md", draft_chars=4820, target_chars=5000)
    widget = DecisionPanelWidget(panel)
    rendered = widget.render_panel()

    assert "接受本章 -> 请确认写回续写记忆" in rendered
    assert "调整字数后重写 -> 请确认章节长度与节奏" in rendered
    assert "修改章节梗概后重写 -> 请调整章节规划后重写" in rendered
    assert "action=accept_chapter" in rendered


def test_planning_decision_panel_exposes_scoped_revision_and_manual_edit() -> None:
    panel = DecisionPanel.planning_review(
        artifact_path="/tmp/batch_plan.json",
        stage_label="请审阅本批剧情大纲",
        next_status="章节梗概已确认",
    )
    widget = DecisionPanelWidget(panel)
    rendered = widget.render_panel()

    assert "接受并继续 -> 章节梗概已确认 · action=confirm_current_step" in rendered
    assert "按我的反馈修改 -> 请审阅本批剧情大纲 · action=request_scoped_artifact_revision" in rendered
    assert "手动编辑 -> 请审阅本批剧情大纲 · action=manual_edit" in rendered
    assert panel.choose("2").workflow_action == "request_scoped_artifact_revision"
    assert panel.choose("3").workflow_action == "manual_edit"


def test_textual_scoped_revision_feedback_params_diff_apply_and_no_auto_confirm(tmp_path: Path) -> None:
    async def scenario() -> None:
        app = _app(tmp_path)
        artifact_path = tmp_path / "batch_plan.json"
        artifact_path.write_text(json.dumps({"stage_goal": "继续追查"}, ensure_ascii=False), encoding="utf-8")
        async with app.run_test(size=(120, 40)) as pilot:
            app.open_workbench()
            await pilot.pause()
            screen = app.screen
            assert isinstance(screen, WorkbenchScreen)
            screen.session.set_status("batch_review", technical_details={"run_id": "run-1"})
            screen.show_artifact(artifact_path, stage="batch_review")
            await pilot.pause()

            panel = screen.session.decision_panel
            assert panel is not None
            screen.on_decision_panel_widget_selected(DecisionPanelWidget.Selected(panel.choose("2")))
            await pilot.pause()
            feedback = screen.query_one("#scoped-revision-feedback", ScopedRevisionFeedbackWidget)
            feedback.value = "保留主线，但把反派登场提前到第二章。"
            feedback.submit()
            for _ in range(5):
                await pilot.pause()

            facade = app.session.facade
            assert facade.scoped_revision_requests[-1]["current_review_state"] == "batch_review"  # type: ignore[attr-defined]
            assert facade.scoped_revision_requests[-1]["target_artifact_path"] == str(artifact_path)  # type: ignore[attr-defined]
            assert facade.scoped_revision_requests[-1]["user_feedback"] == "保留主线，但把反派登场提前到第二章。"  # type: ignore[attr-defined]
            rendered = app.session.messages.render(limit=30)
            assert "修改摘要：把反派登场提前" in rendered
            assert "- 反派第三章登场" in rendered
            assert "校验结果：\n通过" in rendered
            assert "writer_action" not in facade.calls  # type: ignore[attr-defined]

            candidate_panel = screen.session.decision_panel
            assert candidate_panel is not None
            screen.on_decision_panel_widget_selected(DecisionPanelWidget.Selected(candidate_panel.choose("a")))
            for _ in range(5):
                await pilot.pause()

            assert facade.scoped_revision_applies[-1]["request_id"] == "req-1"  # type: ignore[attr-defined]
            assert "apply_scoped_artifact_revision" in facade.calls  # type: ignore[attr-defined]
            assert "writer_action" not in facade.calls  # type: ignore[attr-defined]
            assert app.session.current_status.step == "请审阅本批剧情大纲"
            assert "保存 · 已保存你的修改" in app.session.messages.render(limit=40)

    _run(scenario())


def test_textual_scoped_revision_validation_failure_shows_recovery_without_accepting(tmp_path: Path) -> None:
    async def scenario() -> None:
        app = _app(tmp_path)
        app.session.facade.next_scoped_revision_result = {  # type: ignore[attr-defined]
            "status": "validation_failed",
            "request_id": "req-bad",
            "revision_id": "rev-bad",
            "change_summary": "候选越过了当前产物边界。",
            "diff": "- 当前章节\n+ 其他章节",
            "validation": {"ok": False, "errors": ["target artifact is outside current review scope"]},
        }
        artifact_path = tmp_path / "batch_plan.json"
        artifact_path.write_text(json.dumps({"stage_goal": "继续追查"}, ensure_ascii=False), encoding="utf-8")
        async with app.run_test(size=(120, 40)) as pilot:
            app.open_workbench()
            await pilot.pause()
            screen = app.screen
            assert isinstance(screen, WorkbenchScreen)
            screen.session.set_status("batch_review", technical_details={"run_id": "run-1"})
            screen.show_artifact(artifact_path, stage="batch_review")
            await pilot.pause()

            panel = screen.session.decision_panel
            assert panel is not None
            screen.on_decision_panel_widget_selected(DecisionPanelWidget.Selected(panel.choose("2")))
            await pilot.pause()
            feedback = screen.query_one("#scoped-revision-feedback", ScopedRevisionFeedbackWidget)
            feedback.value = "顺便修改其他章节和 Memory。"
            feedback.submit()
            for _ in range(5):
                await pilot.pause()

            rendered = app.session.messages.render(limit=30)
            assert "校验结果：\n未通过" in rendered
            assert "target artifact is outside current review scope" in rendered
            assert "修改反馈后重试，或选择手动编辑当前产物。" in rendered
            assert app.session.facade.scoped_revision_applies == []  # type: ignore[attr-defined]
            assert screen.pending_scoped_revision is None
            assert app.session.current_status.step == "请审阅本批剧情大纲"

    _run(scenario())


def test_textual_scoped_revision_reject_returns_to_review_without_apply(tmp_path: Path) -> None:
    async def scenario() -> None:
        app = _app(tmp_path)
        artifact_path = tmp_path / "batch_plan.json"
        artifact_path.write_text(json.dumps({"stage_goal": "继续追查"}, ensure_ascii=False), encoding="utf-8")
        async with app.run_test(size=(120, 40)) as pilot:
            app.open_workbench()
            await pilot.pause()
            screen = app.screen
            assert isinstance(screen, WorkbenchScreen)
            screen.session.set_status("batch_review", technical_details={"run_id": "run-1"})
            screen.show_artifact(artifact_path, stage="batch_review")
            await pilot.pause()

            panel = screen.session.decision_panel
            assert panel is not None
            screen.on_decision_panel_widget_selected(DecisionPanelWidget.Selected(panel.choose("2")))
            await pilot.pause()
            feedback = screen.query_one("#scoped-revision-feedback", ScopedRevisionFeedbackWidget)
            feedback.value = "把第二章结尾改成悬疑钩子。"
            feedback.submit()
            for _ in range(5):
                await pilot.pause()

            candidate_panel = screen.session.decision_panel
            assert candidate_panel is not None
            screen.on_decision_panel_widget_selected(DecisionPanelWidget.Selected(candidate_panel.choose("r")))
            await pilot.pause()

            assert app.session.facade.scoped_revision_applies == []  # type: ignore[attr-defined]
            assert screen.pending_scoped_revision is None
            assert app.session.current_status.step == "请审阅本批剧情大纲"
            assert "当前产物未写入" in app.session.messages.render(limit=40)

    _run(scenario())

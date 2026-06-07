from __future__ import annotations

import asyncio
import json
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from fastapi.testclient import TestClient

from novel_agent.app.cli import facade as facade_module
from novel_agent.app.cli.facade import ModelingStatusSnapshot, TuiTaskSnapshot, WorkflowFacade
from novel_agent.app.cli.status import StatusPresenter
from novel_agent.app.repos.chapters_repo import ChaptersRepo
from novel_agent.app.repos.db import NovelAgentDB
from novel_agent.app.run_interactive import run_writer_workflow_action
from novel_agent.app.web.main import create_app
from novel_agent.app.web.schemas import JobSummary, WebActionRequest
from novel_agent.app.web.services.artifact_ids import decode_artifact_id
from novel_agent.app.web.services.artifact_view_service import ArtifactViewService
from novel_agent.app.web.services.job_manager import JobManager
from novel_agent.app.web.services.web_action_service import WebActionService
from novel_agent.app.web.services.web_session_service import WebSessionService


def test_web_task_message_action_and_command_contract(tmp_path: Path) -> None:
    client = TestClient(create_app(repo_root=tmp_path))

    created = client.post(
        "/api/tasks",
        json={"task_id": "book-one", "source_path": str(tmp_path / "source.txt")},
    )
    assert created.status_code == 200
    assert created.json()["task_id"] == "book-one"

    tasks = client.get("/api/tasks")
    assert tasks.status_code == 200
    assert [item["task_id"] for item in tasks.json()] == ["book-one"]

    selected = client.post(
        "/api/tasks/book-one/actions",
        json={"action": "select_task", "payload": {"task_id": "book-one"}},
    )
    assert selected.status_code == 200
    selected_payload = selected.json()
    assert selected_payload["action"] == "select_task"
    assert selected_payload["task_id"] == "book-one"

    message = client.post(
        "/api/tasks/book-one/messages",
        json={"content": "续写方向：保持慢热关系，不要跳过调查过程。"},
    )
    assert message.status_code == 200
    assert message.json()["role"] == "user"
    assert "续写方向" in message.json()["content"]

    action = client.post(
        "/api/tasks/book-one/actions",
        json={"action": "start_writer", "payload": {"intent": {"direction": "继续调查"}}},
    )
    assert action.status_code == 200
    action_payload = action.json()
    assert action_payload["job"]["type"] == "writer"
    assert action_payload["decision_cards"] == []
    assert "可审阅内容" in action_payload["message"]
    assert "/writer" not in json.dumps(action_payload, ensure_ascii=False)

    command = client.post("/api/tasks/book-one/commands", json={"command": "/status"})
    assert command.status_code == 200
    assert command.json()["action"] == "commands"
    assert command.json()["progress"]["task_id"] == "book-one"


def test_web_outline_analyzer_message_creates_job_and_does_not_submit_writer_action(tmp_path: Path) -> None:
    class _FakeFacade:
        def __init__(self) -> None:
            self.analyzer_calls: list[dict[str, Any]] = []
            self.writer_action_calls: list[dict[str, Any]] = []

        def analyze_outline(self, **kwargs):  # type: ignore[no-untyped-def]
            self.analyzer_calls.append(kwargs)
            recorder = kwargs.get("prompt_trace_recorder")
            if callable(recorder):
                recorder(
                    {
                        "stage": "loop",
                        "round_index": 1,
                        "attempt_index": 1,
                        "model": "fake-analyzer",
                        "system_prompt": "system prompt",
                        "user_prompt": "user prompt",
                        "timeout_seconds": 12,
                        "model_kwargs": {"thinking": "disabled"},
                    }
                )
            return {
                "status": "ok",
                "answer": "结论：旧案线索适合局部回收。事实依据：【故事大纲】【章节摘要】。风险：需要用户确认是否延迟幕后身份。",
                "sources": [{"label": "故事大纲"}, {"label": "章节摘要"}],
            }

        def start_writer(self, **kwargs):  # type: ignore[no-untyped-def]
            self.writer_action_calls.append(kwargs)
            raise AssertionError("Analyzer message must not start Writer")

    app = create_app(repo_root=tmp_path)
    fake_facade = _FakeFacade()
    session = WebSessionService(repo_root=tmp_path, facade=fake_facade)  # type: ignore[arg-type]
    session.analyzer_turn_service = app.state.analyzer_turn_service
    session.append_writer_question_message(
        "book-one",
        {
            "question_set_id": "outline-research-run-1-needs-answer",
            "run_id": "run-1",
            "stage": "outline_research_user_input",
            "status": "pending",
            "questions": [{"question_id": "q1", "prompt": "是否新增人物？", "required": True}],
            "actions": {"submit": "continue_after_outline_research_input"},
        },
    )
    app.state.web_session_service = session
    with TestClient(app) as client:
        response = client.post(
            "/api/tasks/book-one/messages",
            json={
                "content": "当前未解之谜哪条最适合下一阶段回收？",
                "payload": {"channel": "outline_analyzer"},
            },
        )

        assert response.status_code == 200
        response_payload = response.json()
        assert response_payload["role"] == "user"
        assert response_payload["payload"]["job_id"]
        assert response_payload["payload"]["turn_id"]
        assert fake_facade.writer_action_calls == []
        summary = asyncio.run(app.state.job_manager.wait(response_payload["payload"]["job_id"], timeout=2.0))
        assert summary.status == "succeeded"
        assert fake_facade.analyzer_calls[0]["book_id"] == "book-one"
        assert "未解之谜" in fake_facade.analyzer_calls[0]["question"]
        assert callable(fake_facade.analyzer_calls[0]["prompt_trace_recorder"])
        prompt_path = tmp_path / ".memory" / "analyzer" / "book-one" / "turns" / f"{response_payload['payload']['turn_id']}.last_prompt.json"
        prompt_payload = json.loads(prompt_path.read_text(encoding="utf-8"))
        assert prompt_payload["job_id"] == response_payload["payload"]["job_id"]
        assert prompt_payload["stage"] == "loop"
        assert prompt_payload["system_prompt"] == "system prompt"
        messages = session._messages["book-one"]  # noqa: SLF001 - inspect raw stream without unrelated sync hooks.
        assert messages[-1].role == "assistant"
        assert messages[-1].payload["channel"] == "outline_analyzer"
        assert messages[-1].payload["job_id"] == response_payload["payload"]["job_id"]
        assert messages[-1].payload["turn_id"] == response_payload["payload"]["turn_id"]
        assert messages[-1].payload["sources"] == [{"label": "故事大纲"}, {"label": "章节摘要"}]
    rendered = json.dumps(
        [message.model_dump() if hasattr(message, "model_dump") else message.dict() for message in messages],
        ensure_ascii=False,
        default=str,
    )
    assert "supplement_text" not in rendered
    assert "revision_feedback" not in rendered
    assert "answer_text" not in rendered


def test_outline_analyzer_model_omits_reasoning_effort_when_thinking_disabled(tmp_path: Path, monkeypatch: Any) -> None:
    captured: dict[str, Any] = {}

    class _FakeJsonModelClient:
        def __init__(self, settings: Any) -> None:
            captured["settings"] = settings

    monkeypatch.setattr(facade_module, "JsonModelClient", _FakeJsonModelClient)
    monkeypatch.setenv("DEEPSEEK_API_KEY", "test-key")
    monkeypatch.setenv("NOVEL_AGENT_ANALYZER_THINKING", "disabled")
    monkeypatch.setenv("NOVEL_AGENT_ANALYZER_REASONING_EFFORT", "low")

    client = WorkflowFacade(repo_root=tmp_path)._build_outline_analyzer_model()  # noqa: SLF001 - model settings boundary.

    assert client is not None
    settings = captured["settings"]
    assert settings.thinking == "disabled"
    assert settings.reasoning_effort is None
    assert settings.include_reasoning_content is False


def test_web_outline_analyzer_job_failure_appends_error_message(tmp_path: Path) -> None:
    class _FakeFacade:
        def analyze_outline(self, **kwargs):  # type: ignore[no-untyped-def]
            raise RuntimeError("model request timed out")

    app = create_app(repo_root=tmp_path)
    session = WebSessionService(repo_root=tmp_path, facade=_FakeFacade())  # type: ignore[arg-type]
    session.analyzer_turn_service = app.state.analyzer_turn_service
    app.state.web_session_service = session
    with TestClient(app) as client:
        response = client.post(
            "/api/tasks/book-one/messages",
            json={"content": "帮我分析下一阶段风险", "payload": {"channel": "outline_analyzer"}},
        )

        assert response.status_code == 200
        job_id = response.json()["payload"]["job_id"]
        summary = asyncio.run(app.state.job_manager.wait(job_id, timeout=2.0))
        assert summary.status == "failed"
        messages = session._messages["book-one"]  # noqa: SLF001 - inspect raw stream without unrelated sync hooks.
        assert messages[-1].role == "error"
        assert messages[-1].payload["channel"] == "outline_analyzer"
        assert messages[-1].payload["status"] == "failed"
        assert messages[-1].payload["job_id"] == job_id


def test_web_outline_analyzer_job_timeout_appends_error_message(tmp_path: Path, monkeypatch: Any) -> None:
    monkeypatch.setenv("NOVEL_AGENT_WEB_ANALYZER_JOB_TIMEOUT_SECONDS", "0.05")
    monkeypatch.setenv("NOVEL_AGENT_WEB_ANALYZER_JOB_HEARTBEAT_SECONDS", "0.01")

    class _FakeFacade:
        def analyze_outline(self, **kwargs):  # type: ignore[no-untyped-def]
            time.sleep(0.2)
            return {"status": "ok", "answer": "不应该在超时后追加。", "sources": []}

    app = create_app(repo_root=tmp_path)
    session = WebSessionService(repo_root=tmp_path, facade=_FakeFacade())  # type: ignore[arg-type]
    session.analyzer_turn_service = app.state.analyzer_turn_service
    app.state.web_session_service = session
    with TestClient(app) as client:
        response = client.post(
            "/api/tasks/book-one/messages",
            json={"content": "帮我分析下一阶段风险", "payload": {"channel": "outline_analyzer"}},
        )

        assert response.status_code == 200
        payload = response.json()["payload"]
        summary = asyncio.run(app.state.job_manager.wait(payload["job_id"], timeout=1.0))
        assert summary.status == "failed"
        messages = session._messages["book-one"]  # noqa: SLF001 - inspect raw stream without unrelated sync hooks.
        assert messages[-1].role == "error"
        assert "超时" in messages[-1].content
        assert messages[-1].payload["status"] == "failed"
        turn = app.state.analyzer_turn_service.require_turn("book-one", payload["turn_id"])
        assert turn.status == "failed"
        assert turn.error["error_type"] == "model_timeout"


def test_web_outline_analyzer_cancel_marks_turn_cancelled(tmp_path: Path) -> None:
    class _FakeFacade:
        def analyze_outline(self, **kwargs):  # type: ignore[no-untyped-def]
            time.sleep(0.5)
            return {"status": "ok", "answer": "不应该在取消后追加。", "sources": []}

    app = create_app(repo_root=tmp_path)
    session = WebSessionService(repo_root=tmp_path, facade=_FakeFacade())  # type: ignore[arg-type]
    session.analyzer_turn_service = app.state.analyzer_turn_service
    app.state.web_session_service = session
    with TestClient(app) as client:
        response = client.post(
            "/api/tasks/book-one/messages",
            json={"content": "帮我分析下一阶段风险", "payload": {"channel": "outline_analyzer"}},
        )

        assert response.status_code == 200
        payload = response.json()["payload"]
        cancel = client.post(f"/api/jobs/{payload['job_id']}/cancel")
        assert cancel.status_code == 200
        assert cancel.json()["status"] == "cancelled"

        deadline = time.monotonic() + 1.0
        turn = app.state.analyzer_turn_service.require_turn("book-one", payload["turn_id"])
        while turn.status != "cancelled" and time.monotonic() < deadline:
            time.sleep(0.02)
            turn = app.state.analyzer_turn_service.require_turn("book-one", payload["turn_id"])

        assert turn.status == "cancelled"
        messages = session._messages["book-one"]  # noqa: SLF001 - inspect raw stream without unrelated sync hooks.
        assert messages[-1].role == "error"
        assert messages[-1].payload["status"] == "cancelled"


def test_web_outline_analyzer_need_user_input_keeps_turn_open(tmp_path: Path) -> None:
    class _FakeFacade:
        def __init__(self) -> None:
            self.calls: list[dict[str, Any]] = []

        def analyze_outline(self, **kwargs):  # type: ignore[no-untyped-def]
            self.calls.append(kwargs)
            if len(self.calls) == 1:
                return {
                    "status": "needs_user_preference",
                    "answer": "需要你确认：是否允许把关键秘密提前揭开？",
                    "sources": [{"label": "故事大纲"}],
                }
            return {
                "status": "ok",
                "answer": "结论：可以延后揭开秘密，先回收外层线索。",
                "sources": [{"label": "故事大纲"}],
            }

    app = create_app(repo_root=tmp_path)
    fake_facade = _FakeFacade()
    session = WebSessionService(repo_root=tmp_path, facade=fake_facade)  # type: ignore[arg-type]
    session.analyzer_turn_service = app.state.analyzer_turn_service
    app.state.web_session_service = session
    with TestClient(app) as client:
        first = client.post(
            "/api/tasks/book-one/messages",
            json={"content": "下一阶段是否适合揭开秘密？", "payload": {"channel": "outline_analyzer"}},
        )
        assert first.status_code == 200
        first_payload = first.json()["payload"]
        asyncio.run(app.state.job_manager.wait(first_payload["job_id"], timeout=2.0))
        messages = session._messages["book-one"]  # noqa: SLF001 - inspect raw stream without unrelated sync hooks.
        assert messages[-1].role == "assistant"
        assert messages[-1].payload["status"] == "need_user_input"

        second = client.post(
            "/api/tasks/book-one/messages",
            json={
                "content": "先不要揭开，只回收外层线索。",
                "payload": {"channel": "outline_analyzer", "turn_id": first_payload["turn_id"]},
            },
        )

        assert second.status_code == 200
        second_payload = second.json()["payload"]
        assert second_payload["turn_id"] == first_payload["turn_id"]
        asyncio.run(app.state.job_manager.wait(second_payload["job_id"], timeout=2.0))
        assert len(fake_facade.calls) == 2
        assert "用户补充" in fake_facade.calls[1]["question"]
        assert "先不要揭开" in fake_facade.calls[1]["question"]
        assert session._messages["book-one"][-1].payload["status"] == "ok"  # noqa: SLF001


def test_openapi_exposes_writer_question_contract(tmp_path: Path) -> None:
    client = TestClient(create_app(repo_root=tmp_path))

    schema = client.get("/openapi.json").json()["components"]["schemas"]

    assert "WriterQuestionSet" in schema
    question_set_schema = schema["WriterQuestionSet"]
    assert "question_set_id" in question_set_schema["properties"]
    assert "questions" in question_set_schema["properties"]
    assert "submit_action" in question_set_schema["properties"]
    assert "WriterQuestionAnswerMessage" in schema
    assert "WriterArtifactReview" in schema
    artifact_review_schema = schema["WriterArtifactReview"]
    assert "review_id" in artifact_review_schema["properties"]
    assert "artifact_kind" in artifact_review_schema["properties"]
    assert "technical_details" in artifact_review_schema["properties"]
    assert "WriterDraftReview" in schema
    draft_review_schema = schema["WriterDraftReview"]
    assert "draft_id" in draft_review_schema["properties"]
    assert "actions" in draft_review_schema["properties"]


def test_public_status_hides_internal_writer_stage_tokens(tmp_path: Path) -> None:
    client = TestClient(create_app(repo_root=tmp_path))
    client.post("/api/tasks", json={"task_id": "book-one", "source_path": ""})
    run_dir = tmp_path / "runs" / "writer" / "run-1"
    run_dir.mkdir(parents=True)
    (run_dir / "workflow_state.json").write_text(
        json.dumps(
            {
                "data": {
                    "run_id": "run-1",
                    "book_id": "book-one",
                    "current_stage": "freeze_d_review",
                    "pending_checkpoint": {
                        "stage": "freeze_d_review",
                        "artifact_path": str(run_dir / "chapter_execution_input.json"),
                    },
                }
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    response = client.get("/api/tasks/book-one/status")
    assert response.status_code == 200
    payload = response.json()
    rendered = json.dumps(payload, ensure_ascii=False)
    assert "旧写作材料确认待迁移" in rendered
    assert "直接进入正文生成准备" in rendered
    for token in StatusPresenter.FORBIDDEN_PUBLIC_TOKENS:
        assert token not in rendered
    assert "internal_stage" not in rendered


def test_task_status_shows_active_close_read_job_instead_of_paused_checkpoint(tmp_path: Path) -> None:
    class _FakeJobManager:
        def active_jobs(self, *, task_id: str | None = None, job_type: str | None = None) -> list[JobSummary]:
            return [
                JobSummary(
                    job_id="job-close-read",
                    task_id=task_id or "book-one",
                    type="close_read",
                    status="running",
                    message="后台任务正在运行",
                    created_at=datetime.now(timezone.utc),
                    updated_at=datetime.now(timezone.utc),
                    events_url="/api/jobs/job-close-read/events",
                )
            ]

    client = TestClient(create_app(repo_root=tmp_path, job_manager=_FakeJobManager()))  # type: ignore[arg-type]
    client.post("/api/tasks", json={"task_id": "book-one", "source_path": str(tmp_path / "source.txt")})

    status = client.get("/api/tasks/book-one/status")

    assert status.status_code == 200
    payload = status.json()
    assert payload["flow"] == "阅读"
    assert payload["step"] == "正在阅读章节"
    assert payload["next_action"] == "整理人物、世界观与大纲"

    tasks = client.get("/api/tasks")

    assert tasks.status_code == 200
    assert tasks.json()[0]["active_job"]["job_id"] == "job-close-read"


def test_task_status_shows_active_outline_analyzer_job_before_close_read(tmp_path: Path) -> None:
    class _FakeJobManager:
        def active_jobs(self, *, task_id: str | None = None, job_type: str | None = None) -> list[JobSummary]:
            now = datetime.now(timezone.utc)
            return [
                JobSummary(
                    job_id="job-close-read",
                    task_id=task_id or "book-one",
                    type="close_read",
                    status="running",
                    message="后台任务正在运行",
                    created_at=now,
                    updated_at=now,
                    events_url="/api/jobs/job-close-read/events",
                ),
                JobSummary(
                    job_id="job-outline",
                    task_id=task_id or "book-one",
                    type="outline_analyzer",
                    status="running",
                    message="后台任务正在运行",
                    created_at=now,
                    updated_at=now,
                    events_url="/api/jobs/job-outline/events",
                ),
            ]

    client = TestClient(create_app(repo_root=tmp_path, job_manager=_FakeJobManager()))  # type: ignore[arg-type]
    client.post("/api/tasks", json={"task_id": "book-one", "source_path": str(tmp_path / "source.txt")})

    status = client.get("/api/tasks/book-one/status")

    assert status.status_code == 200
    payload = status.json()
    assert payload["flow"] == "小说专家意见"
    assert payload["step"] == "小说专家正在分析剧情"
    assert payload["message"] == "小说专家正在分析剧情。"


def test_task_status_shows_recent_failed_close_read_job_instead_of_paused_checkpoint(tmp_path: Path) -> None:
    class _FakeJobManager:
        def active_jobs(self, *, task_id: str | None = None, job_type: str | None = None) -> list[JobSummary]:
            return []

        def jobs(
            self,
            *,
            task_id: str | None = None,
            job_type: str | None = None,
            statuses: set[str] | None = None,
        ) -> list[JobSummary]:
            assert statuses == {"failed"}
            return [
                JobSummary(
                    job_id="job-close-read-failed",
                    task_id=task_id or "book-one",
                    type="close_read",
                    status="failed",
                    message="后台任务遇到问题：missing chapter_summary_md plot synopsis",
                    created_at=datetime.now(timezone.utc),
                    updated_at=datetime.now(timezone.utc),
                    events_url="/api/jobs/job-close-read-failed/events",
                )
            ]

    client = TestClient(create_app(repo_root=tmp_path, job_manager=_FakeJobManager()))  # type: ignore[arg-type]
    client.post("/api/tasks", json={"task_id": "book-one", "source_path": str(tmp_path / "source.txt")})

    status = client.get("/api/tasks/book-one/status")

    assert status.status_code == 200
    payload = status.json()
    assert payload["flow"] == "阅读"
    assert payload["step"] == "阅读遇到问题"
    assert payload["next_action"] == "查看错误并从最近 checkpoint 重试"
    assert "missing chapter_summary_md plot synopsis" in payload["message"]


def test_task_status_counts_narrative_scene_index_cards(tmp_path: Path) -> None:
    client = TestClient(create_app(repo_root=tmp_path))
    client.post("/api/tasks", json={"task_id": "book-one", "source_path": ""})
    scene_cards_path = tmp_path / ".memory" / "index_cards" / "book-one.scene_cards.json"
    scene_cards_path.parent.mkdir(parents=True)
    scene_cards_path.write_text(
        json.dumps(
            {
                "scene_cards": [
                    {"card_id": "scene-1", "card_type": "narrative_scene", "source_doc_ids": ["1", "2"]},
                    {"card_id": "scene-2", "card_type": "narrative_scene", "source_doc_ids": ["2", "3"]},
                ]
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    status = client.get("/api/tasks/book-one/status")

    assert status.status_code == 200
    counts = status.json()["counts"]
    assert counts["narrative_scene_cards"] == 2
    assert counts["narrative_scene_card_docs"] == 3


def test_writer_start_preflight_allows_missing_creative_kb_advisory(tmp_path: Path) -> None:
    class _FakeFacade:
        def writer_start_preflight(self, *, book_id: str) -> dict[str, object]:
            return {
                "book_id": book_id,
                "can_start": True,
                "missing_modeling_steps": [],
                "modeling_advisories": ["creative_kb.fragment_cards"],
                "missing_guidance": [],
                "advisory_guidance": ["运行 Creative KB 构建，生成 fragment_cards / fragment_clusters。"],
                "modeling_status": {"ready_for_continuation": True},
            }

    session = WebSessionService(repo_root=tmp_path, facade=_FakeFacade())  # type: ignore[arg-type]
    app = create_app(repo_root=tmp_path)
    app.state.web_session_service = session
    client = TestClient(app)

    response = client.get("/api/tasks/book-one/writer-preflight")

    assert response.status_code == 200
    payload = response.json()
    assert payload["can_start"] is True
    assert payload["missing_modeling_steps"] == []
    assert payload["modeling_advisories"] == ["creative_kb.fragment_cards"]


def test_writer_start_preflight_blocks_hard_modeling_missing(tmp_path: Path) -> None:
    class _FakeFacade:
        def writer_start_preflight(self, *, book_id: str) -> dict[str, object]:
            return {
                "book_id": book_id,
                "can_start": False,
                "missing_modeling_steps": ["memory.character_profiles"],
                "modeling_advisories": [],
                "missing_guidance": ["先运行阅读/记忆流程，生成角色档案。"],
                "advisory_guidance": [],
                "modeling_status": {"ready_for_continuation": False},
            }

    session = WebSessionService(repo_root=tmp_path, facade=_FakeFacade())  # type: ignore[arg-type]
    app = create_app(repo_root=tmp_path)
    app.state.web_session_service = session
    client = TestClient(app)

    response = client.get("/api/tasks/book-one/writer-preflight")

    assert response.status_code == 200
    payload = response.json()
    assert payload["can_start"] is False
    assert payload["missing_modeling_steps"] == ["memory.character_profiles"]
    assert "人物档案" in payload["message"]


def test_chapter_artifact_uses_intermediate_summaries_before_chapter_is_complete(tmp_path: Path) -> None:
    client = TestClient(create_app(repo_root=tmp_path))
    client.post("/api/tasks", json={"task_id": "book-one", "source_path": str(tmp_path / "source.txt")})
    db = NovelAgentDB(tmp_path / ".indexes" / "book-one.db")
    with db.connect() as conn:
        db.init_schema(conn)
        ChaptersRepo().upsert(
            conn,
            {
                "book_id": "book-one",
                "document_title_index": 8,
                "chapter_title": "第八章",
                "source_doc_start_id": 52,
                "source_doc_end_id": 60,
                "source_doc_count": 9,
                "source_total_chars": 18000,
                "summary_intermediate": ["## 剧情事件链\n第一段拆批摘要。", "## 剧情事件链\n第二段拆批摘要。"],
                "summary_md": "",
                "summary_short": "第八章短摘要。",
                "importance_score": 70,
                "importance_reason": "关键转折。",
                "mentioned_characters": ["林澈"],
                "world_update": {"should_update": False, "changes": []},
                "outline_update": {"chapter_line": "[8] 第八章: 第八章短摘要。"},
                "close_read_run_id": "run-1",
                "created_at": "2026-05-15T00:00:00+00:00",
                "updated_at": "2026-05-15T00:10:00+00:00",
            },
        )
        conn.commit()

    tree = client.get("/api/tasks/book-one/artifact-tree?surface=close-read")
    assert tree.status_code == 200
    chapter_id = _find_artifact_id(tree.json(), "8. 第八章")

    view = client.get(f"/api/artifacts/{chapter_id}/view")
    chapters_view = client.get(f"/api/artifacts/{_find_artifact_id(tree.json(), '章节摘要')}/view")

    assert view.status_code == 200
    payload = view.json()
    assert "第一段拆批摘要" in payload["markdown"]
    assert "第二段拆批摘要" in payload["markdown"]
    assert "summary_intermediate_json" not in json.dumps(payload, ensure_ascii=False)
    assert chapters_view.status_code == 200
    assert "第八章短摘要" in json.dumps(chapters_view.json(), ensure_ascii=False)


def test_delete_task_defaults_to_dry_run(tmp_path: Path) -> None:
    client = TestClient(create_app(repo_root=tmp_path))
    client.post("/api/tasks", json={"task_id": "book-one", "source_path": ""})

    preview = client.delete("/api/tasks/book-one")
    assert preview.status_code == 200
    assert preview.json()["confirmed"] is False

    assert client.get("/api/tasks").json()[0]["task_id"] == "book-one"


def test_delete_latest_writer_run_previews_and_confirms(tmp_path: Path) -> None:
    client = TestClient(create_app(repo_root=tmp_path))
    client.post("/api/tasks", json={"task_id": "book-one", "source_path": ""})
    _write_writer_state(tmp_path=tmp_path, task_id="book-one", run_id="run-old", stage="initialized")
    _write_writer_state(tmp_path=tmp_path, task_id="book-one", run_id="run-new", stage="batch_review")
    _write_writer_state(tmp_path=tmp_path, task_id="other-book", run_id="run-other", stage="batch_review")
    run_new_dir = tmp_path / "runs" / "writer" / "run-new"
    run_other_dir = tmp_path / "runs" / "writer" / "run-other"

    preview = client.delete("/api/tasks/book-one/writer-runs/latest")

    assert preview.status_code == 200
    preview_payload = preview.json()
    assert preview_payload["confirmed"] is False
    assert preview_payload["run_id"] == "run-new"
    assert str(run_new_dir) in preview_payload["candidate_paths"]
    assert run_new_dir.exists()

    confirmed = client.delete("/api/tasks/book-one/writer-runs/latest?confirm=true")

    assert confirmed.status_code == 200
    confirmed_payload = confirmed.json()
    assert confirmed_payload["confirmed"] is True
    assert confirmed_payload["run_id"] == "run-new"
    assert str(run_new_dir) in confirmed_payload["deleted_paths"]
    assert not run_new_dir.exists()
    assert run_other_dir.exists()
    assert client.get("/api/tasks").json()[0]["task_id"] == "book-one"


def test_delete_writer_runs_removes_all_runs_for_task(tmp_path: Path) -> None:
    client = TestClient(create_app(repo_root=tmp_path))
    client.post("/api/tasks", json={"task_id": "book-one", "source_path": ""})
    _write_writer_state(tmp_path=tmp_path, task_id="book-one", run_id="run-old", stage="batch_review")
    _write_writer_state(tmp_path=tmp_path, task_id="book-one", run_id="run-new", stage="chapter_review")
    _write_writer_state(tmp_path=tmp_path, task_id="other-book", run_id="run-other", stage="batch_review")
    run_old_dir = tmp_path / "runs" / "writer" / "run-old"
    run_new_dir = tmp_path / "runs" / "writer" / "run-new"
    run_other_dir = tmp_path / "runs" / "writer" / "run-other"

    preview = client.delete("/api/tasks/book-one/writer-runs")

    assert preview.status_code == 200
    preview_payload = preview.json()
    assert preview_payload["confirmed"] is False
    assert set(preview_payload["run_ids"]) == {"run-old", "run-new"}
    assert str(run_old_dir) in preview_payload["candidate_paths"]
    assert str(run_new_dir) in preview_payload["candidate_paths"]
    assert run_old_dir.exists()
    assert run_new_dir.exists()

    confirmed = client.delete("/api/tasks/book-one/writer-runs?confirm=true")

    assert confirmed.status_code == 200
    confirmed_payload = confirmed.json()
    assert confirmed_payload["confirmed"] is True
    assert set(confirmed_payload["run_ids"]) == {"run-old", "run-new"}
    assert str(run_old_dir) in confirmed_payload["deleted_paths"]
    assert str(run_new_dir) in confirmed_payload["deleted_paths"]
    assert not run_old_dir.exists()
    assert not run_new_dir.exists()
    assert run_other_dir.exists()
    assert client.get("/api/tasks").json()[0]["task_id"] == "book-one"


def test_delete_task_with_runs_removes_writer_runs_by_book_id(tmp_path: Path) -> None:
    client = TestClient(create_app(repo_root=tmp_path))
    client.post("/api/tasks", json={"task_id": "book-one", "source_path": ""})
    _write_writer_state(tmp_path=tmp_path, task_id="book-one", run_id="run-random", stage="batch_review")
    _write_writer_state(tmp_path=tmp_path, task_id="other-book", run_id="run-other", stage="batch_review")
    writer_run_dir = tmp_path / "runs" / "writer" / "run-random"
    other_run_dir = tmp_path / "runs" / "writer" / "run-other"

    preview = client.delete("/api/tasks/book-one?include_runs=true")
    assert str(writer_run_dir) in preview.json()["candidate_paths"]

    confirmed = client.delete("/api/tasks/book-one?confirm=true&include_runs=true")

    assert confirmed.status_code == 200
    assert not writer_run_dir.exists()
    assert other_run_dir.exists()


def test_start_read_action_runs_real_facade_pipeline(tmp_path: Path, monkeypatch) -> None:  # type: ignore[no-untyped-def]
    source_path = tmp_path / "source.txt"
    source_path.write_text("第一章\n\n一个可供导入的段落。", encoding="utf-8")
    calls: list[dict[str, object]] = []

    class _FakeFacade:
        def __init__(self, *, repo_root: Path) -> None:
            self.repo_root = repo_root
            from novel_agent.app.cli.events import RunEventStream

            self.event_stream = RunEventStream()

        def ensure_task(self, *, book_id: str, source_path: str = "") -> TuiTaskSnapshot:
            return self.task_snapshot(book_id=book_id, source_path=source_path)

        def task_snapshot(self, *, book_id: str, source_path: str = "") -> TuiTaskSnapshot:
            return TuiTaskSnapshot(
                book_id=book_id,
                source_path=source_path or str(source_path_file),
                db_path=tmp_path / ".indexes" / f"{book_id}.db",
            )

        def list_tasks(self) -> list[TuiTaskSnapshot]:
            return [self.task_snapshot(book_id="book-one")]

        def modeling_status(self, *, book_id: str, db_path: Path | None = None) -> ModelingStatusSnapshot:
            return ModelingStatusSnapshot(
                book_id=book_id,
                documents_ready=False,
                close_read_ready=False,
                character_profiles_ready=False,
                world_summary_ready=False,
                story_outline_ready=False,
                creative_kb_ready=False,
                source_arc_map_ready=False,
                counts={"documents": 0, "chapters": 0, "character_profiles": 0, "fragment_cards": 0},
            )

        def start_read_pipeline(self, **kwargs):  # type: ignore[no-untyped-def]
            calls.append(kwargs)
            self.event_stream.emit("系统", "导入原文/阅读本轮已完成", payload={"inserted_documents": 1})
            return {"inserted_documents": 1, "segmentation_batches": 1}

    source_path_file = source_path
    monkeypatch.setenv("DEEPSEEK_API_KEY", "test-key")
    fake_facade = _FakeFacade(repo_root=tmp_path)
    session = WebSessionService(repo_root=tmp_path, facade=fake_facade)
    job_manager = JobManager(repo_root=tmp_path)
    action_service = WebActionService(
        session_service=session,
        job_manager=job_manager,
        artifact_view_service=ArtifactViewService(repo_root=tmp_path, facade=fake_facade),
    )

    async def run_action() -> None:
        session.create_task(task_id="book-one", source_path=str(source_path))
        result = await action_service.execute(
            task_id="book-one",
            request=WebActionRequest(action="start_read", payload={"max_read_kb": 2}),
        )
        assert result.job is not None
        summary = await job_manager.wait(result.job.job_id, timeout=2.0)
        assert summary.status == "succeeded"
        events = job_manager.events(result.job.job_id)
        rendered = json.dumps(
            [event.model_dump() if hasattr(event, "model_dump") else event.dict() for event in events],
            ensure_ascii=False,
            default=str,
        )
        assert "导入原文/阅读本轮已完成" in rendered
        assert "inserted_documents" in rendered

    asyncio.run(run_action())

    assert calls
    call = calls[0]
    assert call["book_id"] == "book-one"
    assert call["source_path"] == source_path
    assert call["max_read_kb"] == 2
    assert call["max_close_batches"] == 0
    assert call["build_creative_kb"] is False


def test_start_read_action_reads_entire_source_by_default(tmp_path: Path, monkeypatch) -> None:  # type: ignore[no-untyped-def]
    source_path = tmp_path / "source.txt"
    source_path.write_text("第一章\n\n一个需要完整导入的段落。", encoding="utf-8")
    calls: list[dict[str, object]] = []

    class _FakeFacade:
        def __init__(self, *, repo_root: Path) -> None:
            self.repo_root = repo_root
            from novel_agent.app.cli.events import RunEventStream

            self.event_stream = RunEventStream()

        def task_snapshot(self, *, book_id: str, source_path: str = "") -> TuiTaskSnapshot:
            return TuiTaskSnapshot(
                book_id=book_id,
                source_path=str(source_path_file),
                db_path=tmp_path / ".indexes" / f"{book_id}.db",
            )

        def modeling_status(self, *, book_id: str, db_path: Path | None = None) -> ModelingStatusSnapshot:
            return ModelingStatusSnapshot(
                book_id=book_id,
                documents_ready=False,
                close_read_ready=False,
                character_profiles_ready=False,
                world_summary_ready=False,
                story_outline_ready=False,
                creative_kb_ready=False,
                source_arc_map_ready=False,
                counts={"documents": 0, "chapters": 0, "character_profiles": 0, "fragment_cards": 0},
            )

        def start_read_pipeline(self, **kwargs):  # type: ignore[no-untyped-def]
            calls.append(kwargs)
            return {"inserted_documents": 1, "segmentation_batches": 1}

    source_path_file = source_path
    monkeypatch.setenv("DEEPSEEK_API_KEY", "test-key")
    monkeypatch.delenv("NOVEL_AGENT_WEB_MAX_READ_KB", raising=False)
    fake_facade = _FakeFacade(repo_root=tmp_path)
    session = WebSessionService(repo_root=tmp_path, facade=fake_facade)
    job_manager = JobManager(repo_root=tmp_path)
    action_service = WebActionService(
        session_service=session,
        job_manager=job_manager,
        artifact_view_service=ArtifactViewService(repo_root=tmp_path, facade=fake_facade),
    )

    async def run_action() -> None:
        result = await action_service.execute(
            task_id="book-one",
            request=WebActionRequest(action="start_read", payload={}),
        )
        assert result.job is not None
        summary = await job_manager.wait(result.job.job_id, timeout=2.0)
        assert summary.status == "succeeded"

    asyncio.run(run_action())

    assert calls
    call = calls[0]
    assert call["max_read_kb"] is None
    assert call["max_close_batches"] == 0
    assert call["build_creative_kb"] is False


def test_start_close_read_action_runs_all_remaining_by_default(tmp_path: Path, monkeypatch) -> None:  # type: ignore[no-untyped-def]
    source_path = tmp_path / "source.txt"
    source_path.write_text("第一章\n\n一个可供阅读的段落。", encoding="utf-8")
    calls: list[dict[str, object]] = []
    scene_calls: list[dict[str, object]] = []

    class _FakeFacade:
        def __init__(self, *, repo_root: Path) -> None:
            self.repo_root = repo_root
            from novel_agent.app.cli.events import RunEventStream

            self.event_stream = RunEventStream()

        def task_snapshot(self, *, book_id: str, source_path: str = "") -> TuiTaskSnapshot:
            return TuiTaskSnapshot(
                book_id=book_id,
                source_path=str(source_path_file),
                db_path=tmp_path / ".indexes" / f"{book_id}.db",
            )

        def modeling_status(self, *, book_id: str, db_path: Path | None = None) -> ModelingStatusSnapshot:
            return ModelingStatusSnapshot(
                book_id=book_id,
                documents_ready=True,
                close_read_ready=False,
                character_profiles_ready=False,
                world_summary_ready=False,
                story_outline_ready=False,
                creative_kb_ready=False,
                source_arc_map_ready=False,
                counts={"documents": 1, "chapters": 0, "character_profiles": 0, "fragment_cards": 0},
            )

        def start_read_pipeline(self, **kwargs):  # type: ignore[no-untyped-def]
            calls.append(kwargs)
            return {"close_read_batches": 1}

        def build_narrative_scene_index(self, **kwargs):  # type: ignore[no-untyped-def]
            scene_calls.append(kwargs)
            return {"scene_card_count": 2, "artifact_path": str(tmp_path / ".memory" / "index_cards" / "book-one.scene_cards.json")}

    source_path_file = source_path
    monkeypatch.setenv("DEEPSEEK_API_KEY", "test-key")
    fake_facade = _FakeFacade(repo_root=tmp_path)
    session = WebSessionService(repo_root=tmp_path, facade=fake_facade)
    job_manager = JobManager(repo_root=tmp_path)
    action_service = WebActionService(
        session_service=session,
        job_manager=job_manager,
        artifact_view_service=ArtifactViewService(repo_root=tmp_path, facade=fake_facade),
    )

    async def run_action() -> None:
        result = await action_service.execute(
            task_id="book-one",
            request=WebActionRequest(action="start_close_read", payload={}),
        )
        assert result.job is not None
        summary = await job_manager.wait(result.job.job_id, timeout=2.0)
        assert summary.status == "succeeded"

    asyncio.run(run_action())

    assert calls
    call = calls[0]
    assert call["max_read_kb"] == 0
    assert call["max_close_batches"] is None
    assert call["close_document_chars_budget"] == 20000
    assert scene_calls
    assert scene_calls[0]["book_id"] == "book-one"
    assert scene_calls[0]["api_key"] == "test-key"
    assert scene_calls[0]["dry_run"] is False


def test_build_narrative_scene_index_action_runs_explicit_job(tmp_path: Path, monkeypatch) -> None:  # type: ignore[no-untyped-def]
    db_path = tmp_path / ".indexes" / "book-one.db"
    db_path.parent.mkdir(parents=True, exist_ok=True)
    db_path.write_text("", encoding="utf-8")
    calls: list[dict[str, object]] = []

    class _FakeFacade:
        def __init__(self, *, repo_root: Path) -> None:
            self.repo_root = repo_root
            from novel_agent.app.cli.events import RunEventStream

            self.event_stream = RunEventStream()

        def task_snapshot(self, *, book_id: str) -> TuiTaskSnapshot:
            return TuiTaskSnapshot(book_id=book_id, db_path=db_path)

        def modeling_status(self, *, book_id: str, db_path: Path | None = None) -> ModelingStatusSnapshot:
            return ModelingStatusSnapshot(
                book_id=book_id,
                documents_ready=True,
                close_read_ready=True,
                character_profiles_ready=True,
                world_summary_ready=True,
                story_outline_ready=True,
                creative_kb_ready=False,
                source_arc_map_ready=False,
                counts={"documents": 1, "chapters": 1, "character_profiles": 1},
            )

        def build_narrative_scene_index(self, **kwargs):  # type: ignore[no-untyped-def]
            calls.append(kwargs)
            return {"scene_card_count": 3, "artifact_path": str(tmp_path / ".memory" / "index_cards" / "book-one.scene_cards.json")}

    monkeypatch.setenv("DEEPSEEK_API_KEY", "test-key")
    fake_facade = _FakeFacade(repo_root=tmp_path)
    session = WebSessionService(repo_root=tmp_path, facade=fake_facade)
    job_manager = JobManager(repo_root=tmp_path)
    action_service = WebActionService(
        session_service=session,
        job_manager=job_manager,
        artifact_view_service=ArtifactViewService(repo_root=tmp_path, facade=fake_facade),
    )

    async def run_action() -> None:
        result = await action_service.execute(
            task_id="book-one",
            request=WebActionRequest(
                action="build_narrative_scene_index",
                payload={"window_chars": 12000, "overlap_docs": 2},
            ),
        )
        assert result.job is not None
        assert result.job.type == "narrative_scene_index"
        summary = await job_manager.wait(result.job.job_id, timeout=2.0)
        assert summary.status == "succeeded"

    asyncio.run(run_action())

    assert calls == [
        {
            "db_path": db_path,
            "book_id": "book-one",
            "api_key": "test-key",
            "dry_run": False,
            "window_chars_budget": 12000,
            "overlap_docs": 2,
        }
    ]


def test_start_writer_action_maps_web_payload_to_writer_contract(tmp_path: Path, monkeypatch) -> None:  # type: ignore[no-untyped-def]
    calls: list[dict[str, object]] = []
    fake_facade = _FakeWriterFacade(tmp_path=tmp_path, calls=calls)
    action_service, job_manager = _writer_action_service(tmp_path=tmp_path, fake_facade=fake_facade)
    monkeypatch.setenv("DEEPSEEK_API_KEY", "test-key")
    monkeypatch.delenv("NOVEL_AGENT_WEB_ALLOW_WRITER_DRY_RUN", raising=False)

    async def run_action() -> None:
        result = await action_service.execute(
            task_id="book-one",
            request=WebActionRequest(
                action="start_writer",
                payload={
                    "continuation_goal": "进入新地点并揭露线索。",
                    "target_chapter_count": 4,
                    "target_total_chars": 16000,
                    "default_chapter_chars": 4000,
                    "pacing_preference": "更紧张",
                    "length_distribution_notes": "高潮章稍长。",
                    "constraints": "不要跳过调查过程。",
                    "climax_plan": {
                        "conflict_climax": "旧案证人当面翻供。",
                        "emotional_climax": "主角确认有限合作。",
                        "target_chapter_position": "第 3 章",
                        "setup_requirements": "旧钥匙；匿名电话",
                        "forbidden_early_resolution": "幕后黑手",
                    },
                },
            ),
        )
        assert result.job is not None
        summary = await job_manager.wait(result.job.job_id, timeout=2.0)
        assert summary.status == "succeeded"

    asyncio.run(run_action())

    assert calls
    call = calls[0]
    assert call["dry_run"] is False
    assert call["api_key"] == "test-key"
    assert call["target_chapter_count"] == 4
    intent_payload = call["intent_payload"]  # type: ignore[index]
    assert intent_payload["desired_actions"] == ["进入新地点并揭露线索。"]  # type: ignore[index]
    assert intent_payload["notes"] == "不要跳过调查过程。"  # type: ignore[index]
    assert intent_payload["story_scale"]["default_chapter_target_chars"] == 4000  # type: ignore[index]
    assert intent_payload["story_scale"]["pacing_profile"] == "更紧张"  # type: ignore[index]
    assert intent_payload["climax_plan"]["target_chapter_index"] == 3  # type: ignore[index]
    assert intent_payload["climax_plan"]["must_foreshadow"] == ["旧钥匙", "匿名电话"]  # type: ignore[index]
    assert intent_payload["climax_plan"]["must_not_resolve_before"] == ["幕后黑手"]  # type: ignore[index]


def test_start_writer_action_does_not_silently_enable_dry_run_when_key_missing(tmp_path: Path, monkeypatch) -> None:  # type: ignore[no-untyped-def]
    calls: list[dict[str, object]] = []
    fake_facade = _FakeWriterFacade(tmp_path=tmp_path, calls=calls)
    action_service, job_manager = _writer_action_service(tmp_path=tmp_path, fake_facade=fake_facade)
    monkeypatch.delenv("DEEPSEEK_API_KEY", raising=False)
    monkeypatch.delenv("NOVEL_AGENT_WEB_ALLOW_WRITER_DRY_RUN", raising=False)

    async def run_action() -> None:
        result = await action_service.execute(
            task_id="book-one",
            request=WebActionRequest(action="start_writer", payload={"continuation_goal": "继续调查。"}),
        )
        assert result.job is not None
        summary = await job_manager.wait(result.job.job_id, timeout=2.0)
        assert summary.status == "succeeded"

    asyncio.run(run_action())

    assert calls
    assert calls[0]["dry_run"] is False
    assert calls[0]["api_key"] is None


def test_start_writer_action_rejects_web_dry_run_without_dev_flag(tmp_path: Path, monkeypatch) -> None:  # type: ignore[no-untyped-def]
    calls: list[dict[str, object]] = []
    fake_facade = _FakeWriterFacade(tmp_path=tmp_path, calls=calls)
    action_service, job_manager = _writer_action_service(tmp_path=tmp_path, fake_facade=fake_facade)
    monkeypatch.setenv("DEEPSEEK_API_KEY", "test-key")
    monkeypatch.delenv("NOVEL_AGENT_WEB_ALLOW_WRITER_DRY_RUN", raising=False)

    async def run_action() -> None:
        result = await action_service.execute(
            task_id="book-one",
            request=WebActionRequest(
                action="start_writer",
                payload={"continuation_goal": "继续调查。", "dry_run": True},
            ),
        )
        assert result.job is not None
        summary = await job_manager.wait(result.job.job_id, timeout=2.0)
        assert summary.status == "failed"
        events = job_manager.events(result.job.job_id)
        rendered = json.dumps(
            [event.model_dump() if hasattr(event, "model_dump") else event.dict() for event in events],
            ensure_ascii=False,
            default=str,
        )
        assert "不允许 dry-run" in rendered

    asyncio.run(run_action())

    assert calls == []


def test_confirm_current_step_runs_real_writer_workflow_action(tmp_path: Path) -> None:
    calls: list[dict[str, object]] = []
    fake_facade = _FakeWriterFacade(tmp_path=tmp_path, calls=calls)
    _write_writer_state(
        tmp_path=tmp_path,
        task_id="book-one",
        run_id="run-1",
        stage="freeze_a_review",
        artifact_path=str(tmp_path / "runs" / "writer" / "run-1" / "book_plan.json"),
    )
    action_service, job_manager = _writer_action_service(tmp_path=tmp_path, fake_facade=fake_facade)

    async def run_action() -> None:
        result = await action_service.execute(
            task_id="book-one",
            request=WebActionRequest(action="confirm_current_step", payload={}),
        )
        assert result.job is not None
        summary = await job_manager.wait(result.job.job_id, timeout=2.0)
        assert summary.status == "succeeded"

    asyncio.run(run_action())

    assert calls
    assert calls[0]["action"] == "continue_after_planning_review"
    assert calls[0]["run_id"] == "run-1"


def test_chapter_acceptance_action_runs_writer_workflow_action(tmp_path: Path) -> None:
    calls: list[dict[str, object]] = []
    fake_facade = _FakeWriterFacade(tmp_path=tmp_path, calls=calls)
    _write_writer_state(
        tmp_path=tmp_path,
        task_id="book-one",
        run_id="run-1",
        stage="wait_chapter_acceptance",
        artifact_path=str(tmp_path / "runs" / "writer" / "run-1" / "draft.md"),
    )
    action_service, job_manager = _writer_action_service(tmp_path=tmp_path, fake_facade=fake_facade)

    async def run_action() -> None:
        result = await action_service.execute(
            task_id="book-one",
            request=WebActionRequest(action="accept_chapter", payload={"feedback": "这一章可以接受。"}),
        )
        assert result.job is not None
        summary = await job_manager.wait(result.job.job_id, timeout=2.0)
        assert summary.status == "succeeded"

    asyncio.run(run_action())

    assert [call["action"] for call in calls] == ["accept_chapter", "approve_writeback"]
    assert calls[0]["payload"]["user_feedback"] == "这一章可以接受。"  # type: ignore[index]


def test_chapter_acceptance_surfaces_next_chapter_draft_research_questions(tmp_path: Path) -> None:
    calls: list[dict[str, object]] = []

    class _DraftQuestionFacade(_FakeWriterFacade):
        def writer_action(self, **kwargs: Any) -> dict[str, Any]:
            self.calls.append(kwargs)
            action = str(kwargs.get("action") or "")
            run_dir = self.tmp_path / "runs" / "writer" / "run-1"
            if action == "prepare_execution":
                _write_writer_state(
                    tmp_path=self.tmp_path,
                    task_id="book-one",
                    run_id="run-1",
                    stage="freeze_d",
                    pending_checkpoint=False,
                )
                state_path = run_dir / "workflow_state.json"
                state_doc = json.loads(state_path.read_text(encoding="utf-8"))
                state_doc["data"]["current_chapter_id"] = "batch01-ch02"
                state_doc["data"]["terminal_stage"] = None
                state_path.write_text(json.dumps(state_doc, ensure_ascii=False), encoding="utf-8")
                return {"status": "prepared", "chapter_id": "batch01-ch02"}
            if action == "execute_current_chapter":
                question_path = run_dir / "draft_research_question_set.json"
                question_path.write_text(
                    json.dumps(
                        {
                            "data": {
                                "schema_version": "1.0",
                                "question_set_id": "draft-research-run-1-questions",
                                "run_id": "run-1",
                                "stage": "draft_research_user_input",
                                "status": "pending",
                                "artifact_path": str(question_path),
                                "questions": [{"question_id": "q1", "prompt": "是否需要读取上一章原文？", "required": True}],
                                "actions": {
                                    "submit": "submit_draft_research_answers",
                                    "defer": "defer_draft_research_answers",
                                },
                            }
                        },
                        ensure_ascii=False,
                    ),
                    encoding="utf-8",
                )
                _write_writer_state(
                    tmp_path=self.tmp_path,
                    task_id="book-one",
                    run_id="run-1",
                    stage="draft_research_user_input",
                    artifact_path=str(question_path),
                )
                state_path = run_dir / "workflow_state.json"
                state_doc = json.loads(state_path.read_text(encoding="utf-8"))
                state_doc["data"]["current_chapter_id"] = "batch01-ch02"
                state_path.write_text(json.dumps(state_doc, ensure_ascii=False), encoding="utf-8")
                return {
                    "status": "draft_research_not_ready",
                    "draft_research_status": "needs_user_input",
                    "draft_research_decision": {
                        "status": "needs_user_input",
                        "question_set_id": "draft-research-run-1-questions",
                        "next_action": "ask_user",
                    },
                }
            return {"status": "waiting_for_review", "run_id": kwargs.get("run_id", "")}

    fake_facade = _DraftQuestionFacade(tmp_path=tmp_path, calls=calls)
    run_dir = tmp_path / "runs" / "writer" / "run-1"
    _write_writer_state(
        tmp_path=tmp_path,
        task_id="book-one",
        run_id="run-1",
        stage="wait_chapter_acceptance",
        artifact_path=str(run_dir / "draft.md"),
        pending_checkpoint=True,
    )
    state_path = run_dir / "workflow_state.json"
    state_doc = json.loads(state_path.read_text(encoding="utf-8"))
    state_doc["data"]["current_chapter_id"] = "batch01-ch01"
    state_path.write_text(json.dumps(state_doc, ensure_ascii=False), encoding="utf-8")
    (run_dir / "chapter_package.json").write_text(
        json.dumps(
            {
                "data": {
                    "chapters": [
                        {"chapter_id": "batch01-ch01", "title": "第一章"},
                        {"chapter_id": "batch01-ch02", "title": "第二章"},
                    ]
                }
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    action_service, job_manager = _writer_action_service(tmp_path=tmp_path, fake_facade=fake_facade)

    async def run_action() -> None:
        result = await action_service.execute(
            task_id="book-one",
            request=WebActionRequest(action="accept_chapter", payload={"feedback": "这一章可以接受。"}),
        )
        assert result.job is not None
        summary = await job_manager.wait(result.job.job_id, timeout=4.0)
        assert summary.status == "succeeded"

    asyncio.run(run_action())

    assert [call["action"] for call in calls] == [
        "accept_chapter",
        "approve_writeback",
        "prepare_execution",
        "execute_current_chapter",
    ]
    messages = action_service.session_service.messages("book-one")
    rendered = json.dumps(
        [message.model_dump() if hasattr(message, "model_dump") else message.dict() for message in messages],
        ensure_ascii=False,
        default=str,
    )
    assert "正文研究需要你补充几个关键问题。" in rendered
    assert "writer_completion_next_step" not in rendered


def test_writeback_artifact_approval_maps_to_writeback_action(tmp_path: Path) -> None:
    calls: list[dict[str, object]] = []
    fake_facade = _FakeWriterFacade(tmp_path=tmp_path, calls=calls)
    artifact_path = tmp_path / "runs" / "writer" / "run-1" / "memory_writeback.json"
    _write_writer_state(
        tmp_path=tmp_path,
        task_id="book-one",
        run_id="run-1",
        stage="writeback_review",
        artifact_path=str(artifact_path),
    )
    action_service, job_manager = _writer_action_service(tmp_path=tmp_path, fake_facade=fake_facade)

    async def run_action() -> None:
        result = await action_service.execute(
            task_id="book-one",
            request=WebActionRequest(action="approve_writer_artifact", payload={"run_id": "run-1"}),
        )
        assert result.message == "已提交本章正文并更新续写记忆。"
        assert result.job is not None
        summary = await job_manager.wait(result.job.job_id, timeout=2.0)
        assert summary.status == "succeeded"

    asyncio.run(run_action())

    assert calls
    assert calls[0]["action"] == "approve_writeback"


def test_writeback_approval_continues_next_chapter_when_batch_has_more(tmp_path: Path) -> None:
    calls: list[dict[str, object]] = []
    fake_facade = _FakeWriterFacade(tmp_path=tmp_path, calls=calls)
    run_dir = tmp_path / "runs" / "writer" / "run-1"
    artifact_path = run_dir / "memory_writeback.json"
    run_dir.mkdir(parents=True, exist_ok=True)
    (run_dir / "workflow_state.json").write_text(
        json.dumps(
            {
                "data": {
                    "run_id": "run-1",
                    "book_id": "book-one",
                    "current_stage": "writeback_review",
                    "current_chapter_id": "chapter-10",
                    "pending_checkpoint": {
                        "stage": "writeback_review",
                        "artifact_path": str(artifact_path),
                    },
                }
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    (run_dir / "chapter_package.json").write_text(
        json.dumps(
            {
                "data": {
                    "chapters": [
                        {"chapter_id": "chapter-10", "title": "已写回章节"},
                        {"chapter_id": "chapter-11", "title": "下一章"},
                    ]
                }
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    action_service, job_manager = _writer_action_service(tmp_path=tmp_path, fake_facade=fake_facade)

    async def run_action() -> None:
        result = await action_service.execute(
            task_id="book-one",
            request=WebActionRequest(action="approve_writer_artifact", payload={"run_id": "run-1"}),
        )
        assert result.job is not None
        summary = await job_manager.wait(result.job.job_id, timeout=2.0)
        assert summary.status == "succeeded"

    asyncio.run(run_action())

    assert [call["action"] for call in calls] == ["approve_writeback", "prepare_execution", "execute_current_chapter"]
    assert calls[1]["payload"] == {"chapter_id": "chapter-11"}


def test_start_writer_action_can_use_completion_card_feedback_as_next_intent(tmp_path: Path) -> None:
    calls: list[dict[str, object]] = []
    fake_facade = _FakeWriterFacade(tmp_path=tmp_path, calls=calls)
    action_service, job_manager = _writer_action_service(tmp_path=tmp_path, fake_facade=fake_facade)

    async def run_action() -> None:
        result = await action_service.execute(
            task_id="book-one",
            request=WebActionRequest(
                action="start_writer",
                payload={
                    "requested_from": "writer_completion",
                    "previous_run_id": "run-1",
                    "feedback_text": "下一章继续写码头线索，但不要跳过人物关系确认。",
                    "target_chapter_count": 1,
                    "chapter_count": 1,
                },
            ),
        )
        assert result.job is not None
        summary = await job_manager.wait(result.job.job_id, timeout=2.0)
        assert summary.status == "succeeded"

    asyncio.run(run_action())

    assert calls
    intent_payload = calls[0]["intent_payload"]  # type: ignore[index]
    assert intent_payload["desired_actions"] == ["下一章继续写码头线索，但不要跳过人物关系确认。"]
    assert calls[0]["target_chapter_count"] == 1
    assert calls[0]["chapter_count"] == 1


def test_completion_continue_without_new_direction_reuses_previous_plan_next_chapter(tmp_path: Path) -> None:
    calls: list[dict[str, object]] = []
    fake_facade = _FakeWriterFacade(tmp_path=tmp_path, calls=calls)
    run_dir = tmp_path / "runs" / "writer" / "run-1"
    run_dir.mkdir(parents=True, exist_ok=True)
    (run_dir / "workflow_state.json").write_text(
        json.dumps(
            {
                "data": {
                    "run_id": "run-1",
                    "book_id": "book-one",
                    "current_stage": "completed",
                    "current_state": "completed",
                    "current_chapter_id": "chapter-10",
                    "pending_checkpoint": None,
                }
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    (run_dir / "chapter_package.json").write_text(
        json.dumps(
            {
                "data": {
                    "chapters": [
                        {"chapter_id": "chapter-10", "title": "已完成"},
                        {"chapter_id": "chapter-11", "title": "下一章"},
                    ]
                }
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    action_service, job_manager = _writer_action_service(tmp_path=tmp_path, fake_facade=fake_facade)

    async def run_action() -> None:
        result = await action_service.execute(
            task_id="book-one",
            request=WebActionRequest(
                action="start_writer",
                payload={
                    "requested_from": "writer_completion",
                    "previous_run_id": "run-1",
                    "continuation_goal": (
                        "继续最新已写回章节之后的剧情；必须以 Writer Memory 中 "
                        "document_title_index 最大的已写回章节作为 continuation anchor，"
                        "不得重写已写回章节或回退到更早剧情。"
                    ),
                    "target_chapter_count": 1,
                    "chapter_count": 1,
                },
            ),
        )
        assert result.job is not None
        summary = await job_manager.wait(result.job.job_id, timeout=2.0)
        assert summary.status == "succeeded"

    asyncio.run(run_action())

    assert [call["action"] for call in calls] == ["prepare_execution", "execute_current_chapter"]
    assert calls[0]["run_id"] == "run-1"
    assert calls[0]["payload"] == {"chapter_id": "chapter-11"}


def test_completion_continue_without_next_chapter_requires_new_direction(tmp_path: Path) -> None:
    calls: list[dict[str, object]] = []
    fake_facade = _FakeWriterFacade(tmp_path=tmp_path, calls=calls)
    run_dir = tmp_path / "runs" / "writer" / "run-1"
    run_dir.mkdir(parents=True, exist_ok=True)
    (run_dir / "workflow_state.json").write_text(
        json.dumps(
            {
                "data": {
                    "run_id": "run-1",
                    "book_id": "book-one",
                    "current_stage": "completed",
                    "current_chapter_id": "chapter-11",
                    "pending_checkpoint": None,
                }
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    (run_dir / "chapter_package.json").write_text(
        json.dumps(
            {
                "data": {
                    "chapters": [
                        {"chapter_id": "chapter-10", "title": "上一章"},
                        {"chapter_id": "chapter-11", "title": "最后一章"},
                    ]
                }
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    action_service, job_manager = _writer_action_service(tmp_path=tmp_path, fake_facade=fake_facade)

    async def run_action() -> None:
        result = await action_service.execute(
            task_id="book-one",
            request=WebActionRequest(
                action="start_writer",
                payload={
                    "requested_from": "writer_completion",
                    "previous_run_id": "run-1",
                    "continuation_goal": "继续最新已写回章节之后的剧情。",
                    "target_chapter_count": 1,
                    "chapter_count": 1,
                },
            ),
        )
        assert result.job is not None
        summary = await job_manager.wait(result.job.job_id, timeout=2.0)
        assert summary.status == "succeeded"

    asyncio.run(run_action())

    assert calls == []


def test_submit_outline_research_answers_runs_structured_writer_bridge(tmp_path: Path) -> None:
    calls: list[dict[str, object]] = []
    fake_facade = _FakeWriterFacade(tmp_path=tmp_path, calls=calls)
    run_dir = tmp_path / "runs" / "writer" / "run-1"
    artifact_path = run_dir / "outline_research_question_set.json"
    _write_writer_state(
        tmp_path=tmp_path,
        task_id="book-one",
        run_id="run-1",
        stage="outline_research_user_input",
        artifact_path=str(artifact_path),
    )
    artifact_path.write_text(
        json.dumps(
            {
                "data": {
                    "schema_version": "1.0",
                    "question_set_id": "outline-research-run-1-needs-answer",
                    "run_id": "run-1",
                    "stage": "outline_research_user_input",
                    "status": "pending",
                    "questions": [{"question_id": "q1", "prompt": "顾迟是否为新增人物？", "required": True}],
                    "actions": {
                        "submit": "continue_after_outline_research_input",
                        "defer": "defer_outline_research_answers",
                    },
                    "created_at": "2026-05-03T12:10:00Z",
                }
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    action_service, job_manager = _writer_action_service(tmp_path=tmp_path, fake_facade=fake_facade)

    async def run_action() -> None:
        result = await action_service.execute(
            task_id="book-one",
            request=WebActionRequest(
                action="submit_outline_research_answers",
                payload={
                    "run_id": "run-1",
                    "question_set_id": "outline-research-run-1-needs-answer",
                    "source_message_id": "message-123",
                    "answer_text": "不是新增人物，本轮不加入。",
                    "user_answers": [{"question_id": "q1", "answer_text": "不是新增人物，本轮不加入。"}],
                },
            ),
        )
        assert result.job is not None
        summary = await job_manager.wait(result.job.job_id, timeout=2.0)
        assert summary.status == "succeeded"

    asyncio.run(run_action())

    assert calls
    assert calls[0]["action"] == "continue_after_outline_research_input"
    payload = calls[0]["payload"]
    assert payload["question_set_id"] == "outline-research-run-1-needs-answer"  # type: ignore[index]
    assert payload["source_message_id"] == "message-123"  # type: ignore[index]
    assert payload["answer_text"] == "不是新增人物，本轮不加入。"  # type: ignore[index]
    assert payload["user_answers"] == [{"question_id": "q1", "answer_text": "不是新增人物，本轮不加入。"}]  # type: ignore[index]


def test_submit_draft_research_answers_runs_structured_writer_bridge(tmp_path: Path) -> None:
    calls: list[dict[str, object]] = []
    fake_facade = _FakeWriterFacade(tmp_path=tmp_path, calls=calls)
    run_dir = tmp_path / "runs" / "writer" / "run-1"
    artifact_path = run_dir / "draft_research_question_set.json"
    _write_writer_state(
        tmp_path=tmp_path,
        task_id="book-one",
        run_id="run-1",
        stage="draft_research_user_input",
        artifact_path=str(artifact_path),
    )
    artifact_path.write_text(
        json.dumps(
            {
                "data": {
                    "schema_version": "1.0",
                    "question_set_id": "draft-research-run-1-questions",
                    "run_id": "run-1",
                    "stage": "draft_research_user_input",
                    "status": "pending",
                    "questions": [{"question_id": "q1", "prompt": "是否需要读取上一章原文？", "required": True}],
                    "actions": {
                        "submit": "submit_draft_research_answers",
                        "defer": "defer_draft_research_answers",
                    },
                }
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    action_service, job_manager = _writer_action_service(tmp_path=tmp_path, fake_facade=fake_facade)

    async def run_action() -> None:
        result = await action_service.execute(
            task_id="book-one",
            request=WebActionRequest(
                action="submit_draft_research_answers",
                payload={
                    "run_id": "run-1",
                    "question_set_id": "draft-research-run-1-questions",
                    "source_message_id": "message-123",
                    "answer_text": "请读取上一章正文，重点确认人物语气。",
                    "user_answers": [{"question_id": "q1", "answer_text": "请读取上一章正文，重点确认人物语气。"}],
                },
            ),
        )
        assert result.job is not None
        summary = await job_manager.wait(result.job.job_id, timeout=2.0)
        assert summary.status == "succeeded"

    asyncio.run(run_action())

    assert calls
    assert calls[0]["action"] == "continue_after_draft_research_input"
    payload = calls[0]["payload"]
    assert payload["question_set_id"] == "draft-research-run-1-questions"  # type: ignore[index]
    assert payload["source_message_id"] == "message-123"  # type: ignore[index]
    assert payload["answer_text"] == "请读取上一章正文，重点确认人物语气。"  # type: ignore[index]


def test_defer_outline_research_answers_keeps_waiting_without_writer_action(tmp_path: Path) -> None:
    calls: list[dict[str, object]] = []
    fake_facade = _FakeWriterFacade(tmp_path=tmp_path, calls=calls)
    _write_writer_state(
        tmp_path=tmp_path,
        task_id="book-one",
        run_id="run-1",
        stage="outline_research_user_input",
        artifact_path=str(tmp_path / "runs" / "writer" / "run-1" / "outline_research_question_set.json"),
    )
    action_service, _job_manager = _writer_action_service(tmp_path=tmp_path, fake_facade=fake_facade)

    async def run_action() -> None:
        result = await action_service.execute(
            task_id="book-one",
            request=WebActionRequest(
                action="defer_outline_research_answers",
                payload={"run_id": "run-1", "question_set_id": "outline-research-run-1-needs-answer"},
            ),
        )
        assert result.job is None
        assert result.message == "已保留当前大纲研究问题，稍后可以继续回答。"

    asyncio.run(run_action())

    assert calls == []


def test_writer_question_answer_message_does_not_continue_workflow(tmp_path: Path) -> None:
    calls: list[dict[str, object]] = []
    fake_facade = _FakeWriterFacade(tmp_path=tmp_path, calls=calls)
    session = WebSessionService(repo_root=tmp_path, facade=fake_facade)

    message = session.append_user_message(
        "book-one",
        "不是新增人物，本轮不加入。",
        payload={
            "channel": "writer_question_answer",
            "run_id": "run-1",
            "question_set_id": "outline-research-run-1-needs-answer",
            "answer_text": "不是新增人物，本轮不加入。",
        },
    )

    assert message.payload["question_set_id"] == "outline-research-run-1-needs-answer"
    assert calls == []


def test_web_session_replays_pending_outline_research_question_card(tmp_path: Path) -> None:
    fake_facade = _FakeWriterFacade(tmp_path=tmp_path, calls=[])
    _write_writer_state(
        tmp_path=tmp_path,
        task_id="book-one",
        run_id="run-1",
        stage="outline_research_user_input",
        artifact_path=str(tmp_path / "runs" / "writer" / "run-1" / "outline_research_question_set.json"),
    )
    question_path = tmp_path / "runs" / "writer" / "run-1" / "outline_research_question_set.json"
    question_path.write_text(
        json.dumps(
            {
                "data": {
                    "schema_version": "1.0",
                    "question_set_id": "outline-research-run-1-needs-answer",
                    "run_id": "run-1",
                    "stage": "outline_research_user_input",
                    "status": "pending",
                    "source_artifact_id": "writer:run-1:sufficiency-decision",
                    "artifact_path": str(question_path),
                    "questions": [{"question_id": "q1", "prompt": "顾迟是否为新增人物？", "required": True}],
                    "actions": {
                        "submit": "continue_after_outline_research_input",
                        "defer": "defer_outline_research_answers",
                    },
                    "created_at": "2026-05-03T12:10:00Z",
                }
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    session = WebSessionService(repo_root=tmp_path, facade=fake_facade)

    messages = session.messages("book-one")

    assert len(messages) == 1
    assert messages[0].writer_question_set is not None
    assert messages[0].writer_question_set.question_set_id == "outline-research-run-1-needs-answer"
    assert messages[0].writer_question_set.submit_action == "submit_outline_research_answers"
    assert messages[0].writer_question_set.defer_action == "defer_outline_research_answers"
    assert messages[0].content == "大纲研究需要你补充几个关键问题。"


def test_web_session_replays_pending_draft_research_question_card(tmp_path: Path) -> None:
    fake_facade = _FakeWriterFacade(tmp_path=tmp_path, calls=[])
    _write_writer_state(
        tmp_path=tmp_path,
        task_id="book-one",
        run_id="run-1",
        stage="draft_research_user_input",
        artifact_path=str(tmp_path / "runs" / "writer" / "run-1" / "draft_research_question_set.json"),
    )
    question_path = tmp_path / "runs" / "writer" / "run-1" / "draft_research_question_set.json"
    question_path.write_text(
        json.dumps(
            {
                "data": {
                    "schema_version": "1.0",
                    "question_set_id": "draft-research-run-1-questions",
                    "run_id": "run-1",
                    "stage": "draft_research_user_input",
                    "status": "pending",
                    "source_artifact_id": "writer:run-1:draft-research",
                    "artifact_path": str(question_path),
                    "questions": [{"question_id": "q1", "prompt": "是否需要展开前章正文？", "required": True}],
                    "actions": {
                        "submit": "submit_draft_research_answers",
                        "defer": "defer_draft_research_answers",
                    },
                }
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    session = WebSessionService(repo_root=tmp_path, facade=fake_facade)

    messages = session.messages("book-one")

    assert len(messages) == 1
    assert messages[0].writer_question_set is not None
    assert messages[0].writer_question_set.question_set_id == "draft-research-run-1-questions"
    assert messages[0].writer_question_set.submit_action == "submit_draft_research_answers"
    assert messages[0].content == "正文研究需要你补充几个关键问题。"


def test_web_session_replays_writer_artifact_review_card(tmp_path: Path) -> None:
    fake_facade = _FakeWriterFacade(tmp_path=tmp_path, calls=[])
    artifact_path = tmp_path / "runs" / "writer" / "run-1" / "batch_plan.json"
    _write_writer_state(
        tmp_path=tmp_path,
        task_id="book-one",
        run_id="run-1",
        stage="batch_review",
        artifact_path=str(artifact_path),
    )
    artifact_path.write_text(
        json.dumps({"data": {"stage_goal": "把旧案线索推到新地点。"}}, ensure_ascii=False),
        encoding="utf-8",
    )
    session = WebSessionService(repo_root=tmp_path, facade=fake_facade)

    messages = session.messages("book-one")

    assert len(messages) == 1
    review = messages[0].writer_artifact_review
    assert review is not None
    assert review.artifact_kind == "batch_plan"
    assert review.title == "本批剧情大纲"
    assert "旧案线索" in review.summary
    assert [action.action for action in review.actions] == [
        "run_reviewer",
        "approve_writer_artifact",
        "request_writer_artifact_revision",
        "defer_writer_artifact_review",
    ]
    reviewer_action = review.actions[0]
    assert reviewer_action.payload["reviewer_id"] == "outline_plot_development"
    assert reviewer_action.payload["target_type"] == "outline"


def test_web_session_replays_chapter_package_content_in_review_message(tmp_path: Path) -> None:
    fake_facade = _FakeWriterFacade(tmp_path=tmp_path, calls=[])
    artifact_path = tmp_path / "runs" / "writer" / "run-1" / "chapter_package.json"
    _write_writer_state(
        tmp_path=tmp_path,
        task_id="book-one",
        run_id="run-1",
        stage="chapter_review",
        artifact_path=str(artifact_path),
    )
    artifact_path.write_text(
        json.dumps(
            {
                "data": {
                    "chapters": [
                        {
                            "title": "雨夜接应",
                            "goal": "主角救出关键证人，并确认下一处调查地点。",
                            "chapter_role": "线索推进章",
                            "structure_hint": {"beats": ["抵达旧码头", "遭遇外部阻拦", "带走证人"]},
                            "ending_hook": "证人说出新地址。",
                        }
                    ],
                    "review_notes": ["可微调 ChapterBrief，但不得突破 BatchPlan 上限。"],
                }
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    session = WebSessionService(repo_root=tmp_path, facade=fake_facade)

    messages = session.messages("book-one")

    assert len(messages) == 1
    assert messages[0].content == "我整理好了章节标题与梗概，请看下面这版是否按这个方向写。"
    review = messages[0].writer_artifact_review
    assert review is not None
    assert review.title == "章节标题与梗概"
    assert "1. 雨夜接应" in review.summary
    assert "章节梗概：主角救出关键证人" in review.summary
    assert "关键节拍：抵达旧码头；遭遇外部阻拦；带走证人" in review.summary
    assert "章节梗概" in review.summary
    assert "ChapterBrief" not in review.summary
    assert "BatchPlan" not in review.summary
    reviewer_actions = [action for action in review.actions if action.action == "run_reviewer"]
    assert len(reviewer_actions) == 1
    assert reviewer_actions[0].payload["reviewer_id"] == "chapter_synopsis_plot_character"
    assert reviewer_actions[0].payload["target_type"] == "chapter_brief"


def test_web_session_replays_writer_draft_review_card(tmp_path: Path) -> None:
    fake_facade = _FakeWriterFacade(tmp_path=tmp_path, calls=[])
    draft_path = tmp_path / "runs" / "writer" / "run-1" / "draft.md"
    _write_writer_state(
        tmp_path=tmp_path,
        task_id="book-one",
        run_id="run-1",
        stage="wait_chapter_acceptance",
        artifact_path=str(draft_path),
    )
    draft_path.write_text("雨落下来，巷口的灯忽明忽暗。", encoding="utf-8")
    (draft_path.parent / "generation_review_decision.json").write_text(
        json.dumps(
            {
                "data": {
                    "decision_id": "draft-review-1",
                    "chapter_id": "ch-1",
                    "draft_id": "draft-1",
                }
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    session = WebSessionService(repo_root=tmp_path, facade=fake_facade)

    messages = session.messages("book-one")

    assert len(messages) == 1
    review = messages[0].writer_draft_review
    assert review is not None
    assert review.chapter_id == "ch-1"
    assert review.draft_id == "draft-1"
    assert "雨落下来" in review.preview
    assert [action.action for action in review.actions] == [
        "run_reviewer",
        "run_reviewer",
        "run_reviewer",
        "accept_chapter",
        "rewrite_chapter",
        "replan_chapter",
        "discard_chapter",
        "defer_chapter_acceptance",
    ]
    reviewer_ids = [action.payload["reviewer_id"] for action in review.actions if action.action == "run_reviewer"]
    assert reviewer_ids == [
        "local_draft_continuity",
        "memory_draft_consistency",
        "kb_draft_style_atmosphere",
    ]


def test_web_session_recovers_orphan_writer_draft_as_review_card(tmp_path: Path) -> None:
    fake_facade = _FakeWriterFacade(tmp_path=tmp_path, calls=[])
    draft_path = tmp_path / "runs" / "writer" / "run-1" / "draft.md"
    _write_writer_state(
        tmp_path=tmp_path,
        task_id="book-one",
        run_id="run-1",
        stage="freeze_c",
        pending_checkpoint=False,
    )
    draft_path.write_text("雨落下来，巷口的灯忽明忽暗。", encoding="utf-8")
    (draft_path.parent / "continuity_report.json").write_text(
        json.dumps(
            {
                "data": {
                    "blocked": True,
                    "issues": [{"message": "关系推进缺少桥接事件"}],
                }
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    session = WebSessionService(repo_root=tmp_path, facade=fake_facade)

    messages = session.messages("book-one")

    assert len(messages) == 1
    review = messages[0].writer_draft_review
    assert review is not None
    assert review.chapter_id == ""
    assert review.draft_id == "draft-001"
    assert "关系推进缺少桥接事件" in review.continuity_summary
    assert "没有可恢复的问题或审阅卡" not in messages[0].content


def test_web_session_does_not_recover_orphan_draft_while_generating(tmp_path: Path) -> None:
    fake_facade = _FakeWriterFacade(tmp_path=tmp_path, calls=[])
    run_dir = tmp_path / "runs" / "writer" / "run-1"
    draft_path = run_dir / "draft.md"
    _write_writer_state(
        tmp_path=tmp_path,
        task_id="book-one",
        run_id="run-1",
        stage="freeze_d",
        pending_checkpoint=False,
    )
    state_path = run_dir / "workflow_state.json"
    state_doc = json.loads(state_path.read_text(encoding="utf-8"))
    state_doc["data"]["agent_state"] = "generating_draft"
    state_doc["data"]["current_state"] = "generating_draft"
    state_path.write_text(json.dumps(state_doc, ensure_ascii=False), encoding="utf-8")
    draft_path.write_text("上一版草稿仍在等待新版覆盖。", encoding="utf-8")
    session = WebSessionService(repo_root=tmp_path, facade=fake_facade)

    messages = session.messages("book-one")

    rendered = json.dumps(
        [message.model_dump() if hasattr(message, "model_dump") else message.dict() for message in messages],
        ensure_ascii=False,
        default=str,
    )
    assert "请决定当前章节草稿" not in rendered
    assert all(message.writer_draft_review is None for message in messages)


def test_web_session_does_not_recover_stale_previous_chapter_draft(tmp_path: Path) -> None:
    fake_facade = _FakeWriterFacade(tmp_path=tmp_path, calls=[])
    run_dir = tmp_path / "runs" / "writer" / "run-1"
    draft_path = run_dir / "draft.md"
    _write_writer_state(
        tmp_path=tmp_path,
        task_id="book-one",
        run_id="run-1",
        stage="freeze_d",
        pending_checkpoint=False,
    )
    state_path = run_dir / "workflow_state.json"
    state_doc = json.loads(state_path.read_text(encoding="utf-8"))
    state_doc["data"]["current_chapter_id"] = "ch-2"
    state_path.write_text(json.dumps(state_doc, ensure_ascii=False), encoding="utf-8")
    draft_path.write_text("上一章旧草稿。", encoding="utf-8")
    (run_dir / "continuity_report.json").write_text(
        json.dumps({"data": {"state_delta": {"chapter_id": "ch-1"}}}, ensure_ascii=False),
        encoding="utf-8",
    )
    session = WebSessionService(repo_root=tmp_path, facade=fake_facade)

    messages = session.messages("book-one")

    rendered = json.dumps(
        [message.model_dump() if hasattr(message, "model_dump") else message.dict() for message in messages],
        ensure_ascii=False,
        default=str,
    )
    assert "上一章旧草稿" not in rendered
    assert "章节草稿决策" not in rendered


def test_web_session_recovers_incomplete_writer_run_without_gate(tmp_path: Path) -> None:
    fake_facade = _FakeWriterFacade(tmp_path=tmp_path, calls=[])
    _write_writer_state(
        tmp_path=tmp_path,
        task_id="book-one",
        run_id="run-1",
        stage="initialized",
    )
    session = WebSessionService(repo_root=tmp_path, facade=fake_facade)

    messages = session.messages("book-one")

    assert len(messages) == 1
    assert "还没有生成可审阅的大纲或问题卡" in messages[0].content
    assert messages[0].decision_cards[0].title == "续写任务未生成可审阅内容"
    assert messages[0].decision_cards[0].actions == []


def test_web_session_offers_next_writer_round_after_writeback_completion(tmp_path: Path) -> None:
    fake_facade = _FakeWriterFacade(tmp_path=tmp_path, calls=[])
    run_dir = tmp_path / "runs" / "writer" / "run-1"
    _write_writer_state(
        tmp_path=tmp_path,
        task_id="book-one",
        run_id="run-1",
        stage="completed",
        pending_checkpoint=False,
    )
    (run_dir / "workflow_state.json").write_text(
        json.dumps(
            {
                "data": {
                    "run_id": "run-1",
                    "book_id": "book-one",
                    "current_stage": "completed",
                    "current_chapter_id": "chapter-10",
                    "pending_checkpoint": None,
                }
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    (run_dir / "chapter_package.json").write_text(
        json.dumps(
            {
                "data": {
                    "chapters": [
                        {"chapter_id": "chapter-10", "title": "当前章"},
                        {"chapter_id": "chapter-11", "title": "下一章"},
                    ]
                }
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    session = WebSessionService(repo_root=tmp_path, facade=fake_facade)

    messages = session.messages("book-one")

    assert len(messages) == 1
    assert "本章已经写回续写记忆" in messages[0].content
    card = messages[0].decision_cards[0]
    assert card.title == "本章已写回"
    assert card.actions[0]["action"] == "start_writer"
    assert card.actions[0]["label"] == "继续下一章"
    assert card.actions[0]["payload"]["previous_run_id"] == "run-1"
    assert "最新已写回章节" in card.actions[0]["payload"]["continuation_goal"]

    assert session.messages("book-one") == messages


def test_web_session_starts_new_batch_after_last_chapter_completion(tmp_path: Path) -> None:
    fake_facade = _FakeWriterFacade(tmp_path=tmp_path, calls=[])
    run_dir = tmp_path / "runs" / "writer" / "run-1"
    _write_writer_state(
        tmp_path=tmp_path,
        task_id="book-one",
        run_id="run-1",
        stage="completed",
        pending_checkpoint=False,
    )
    (run_dir / "workflow_state.json").write_text(
        json.dumps(
            {
                "data": {
                    "run_id": "run-1",
                    "book_id": "book-one",
                    "current_stage": "completed",
                    "current_chapter_id": "chapter-11",
                    "pending_checkpoint": None,
                }
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    (run_dir / "chapter_package.json").write_text(
        json.dumps(
            {
                "data": {
                    "chapters": [
                        {"chapter_id": "chapter-10", "title": "上一章"},
                        {"chapter_id": "chapter-11", "title": "最后一章"},
                    ]
                }
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    session = WebSessionService(repo_root=tmp_path, facade=fake_facade)

    messages = session.messages("book-one")

    assert "本批次章节已经全部写回续写记忆" in messages[0].content
    card = messages[0].decision_cards[0]
    assert card.title == "本批次已写完"
    assert card.actions[0]["action"] == "start_writer"
    assert card.actions[0]["label"] == "提交下一批续写规划"
    assert card.actions[0]["requires_input"] is True
    assert card.actions[0]["payload"]["requested_from"] == "writer_new_batch"


def test_task_progress_after_last_batch_prompts_new_plan_submission(tmp_path: Path) -> None:
    fake_facade = _FakeWriterFacade(tmp_path=tmp_path, calls=[])
    run_dir = tmp_path / "runs" / "writer" / "run-1"
    _write_writer_state(
        tmp_path=tmp_path,
        task_id="book-one",
        run_id="run-1",
        stage="completed",
        pending_checkpoint=False,
    )
    (run_dir / "workflow_state.json").write_text(
        json.dumps(
            {
                "data": {
                    "run_id": "run-1",
                    "book_id": "book-one",
                    "current_stage": "completed",
                    "current_chapter_id": "chapter-11",
                    "pending_checkpoint": None,
                }
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    (run_dir / "chapter_package.json").write_text(
        json.dumps(
            {
                "data": {
                    "chapters": [
                        {"chapter_id": "chapter-10", "title": "上一章"},
                        {"chapter_id": "chapter-11", "title": "最后一章"},
                    ]
                }
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    session = WebSessionService(repo_root=tmp_path, facade=fake_facade)

    progress = session.task_progress("book-one")

    assert progress.step == "继续提交下一批章节的续写规划"
    assert progress.next_action == "在输入框补充下一批方向后开始新一轮规划"


def test_writer_question_answer_message_offers_submit_action(tmp_path: Path) -> None:
    fake_facade = _FakeWriterFacade(tmp_path=tmp_path, calls=[])
    session = WebSessionService(repo_root=tmp_path, facade=fake_facade)

    user_message = session.append_user_message(
        "book-one",
        "下一批先写过渡日常，再引出新的邀请。",
        payload={
            "channel": "writer_question_answer",
            "run_id": "run-1",
            "question_set_id": "outline-research-run-1-needs-user-input",
            "answer_text": "下一批先写过渡日常，再引出新的邀请。",
        },
    )

    messages = session.messages("book-one")
    assert messages[-1].content.startswith("已收到你的回答")
    card = messages[-1].decision_cards[0]
    assert card.actions[0]["action"] == "submit_outline_research_answers"
    assert card.actions[0]["payload"]["source_message_id"] == user_message.message_id
    assert card.actions[0]["payload"]["answer_text"] == "下一批先写过渡日常，再引出新的邀请。"


def test_web_session_keeps_writeback_review_when_continuity_has_risk(tmp_path: Path) -> None:
    fake_facade = _FakeWriterFacade(tmp_path=tmp_path, calls=[])
    run_dir = tmp_path / "runs" / "writer" / "run-1"
    draft_path = run_dir / "draft.md"
    _write_writer_state(
        tmp_path=tmp_path,
        task_id="book-one",
        run_id="run-1",
        stage="writeback_review",
        artifact_path=str(run_dir / "continuity_report.json"),
    )
    draft_path.write_text("这一版还没有覆盖全部大纲必写点。", encoding="utf-8")
    (run_dir / "generation_review_decision.json").write_text(
        json.dumps(
            {"data": {"decision_id": "decision-1", "chapter_id": "ch-1", "draft_id": "draft-1", "status": "accepted"}},
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    (run_dir / "continuity_report.json").write_text(
        json.dumps(
            {
                "data": {
                    "blocked": True,
                    "canon_ready": False,
                    "writeback_blocked_reason": "",
                    "issues": [{"message": "必写点未出现：聚会场景"}],
                }
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    session = WebSessionService(repo_root=tmp_path, facade=fake_facade)

    messages = session.messages("book-one")

    assert len(messages) == 1
    assert messages[0].writer_draft_review is None
    review = messages[0].writer_artifact_review
    assert review is not None
    assert review.artifact_kind == "writeback_summary"


def test_web_session_offers_resume_for_confirmed_writer_stage(tmp_path: Path) -> None:
    fake_facade = _FakeWriterFacade(tmp_path=tmp_path, calls=[])
    _write_writer_state(
        tmp_path=tmp_path,
        task_id="book-one",
        run_id="run-1",
        stage="freeze_a",
        pending_checkpoint=False,
    )
    session = WebSessionService(repo_root=tmp_path, facade=fake_facade)

    messages = session.messages("book-one")
    progress = session.task_progress("book-one")

    assert progress.step == "全书续写规划已确认"
    assert messages[0].decision_cards[0].title == "全书续写规划已确认"
    assert messages[0].decision_cards[0].actions[0]["action"] == "resume"
    assert messages[0].decision_cards[0].actions[0]["label"] == "生成本批剧情大纲"


def test_web_session_offers_next_resume_after_previous_review_gate(tmp_path: Path) -> None:
    fake_facade = _FakeWriterFacade(tmp_path=tmp_path, calls=[])
    artifact_path = tmp_path / "runs" / "writer" / "run-1" / "batch_plan.json"
    _write_writer_state(
        tmp_path=tmp_path,
        task_id="book-one",
        run_id="run-1",
        stage="batch_review",
        artifact_path=str(artifact_path),
    )
    artifact_path.write_text(json.dumps({"data": {"batch_goal": "推进本批剧情。"}}, ensure_ascii=False), encoding="utf-8")
    session = WebSessionService(repo_root=tmp_path, facade=fake_facade)
    assert any(message.writer_artifact_review is not None for message in session.messages("book-one"))

    _write_writer_state(
        tmp_path=tmp_path,
        task_id="book-one",
        run_id="run-1",
        stage="freeze_b",
        pending_checkpoint=False,
    )
    messages = session.messages("book-one")

    assert messages[-1].decision_cards[0].title == "本批剧情大纲已确认"
    assert messages[-1].decision_cards[0].actions[0]["label"] == "生成章节标题与梗概"


def test_writer_replan_result_surfaces_generate_draft_resume_card(tmp_path: Path) -> None:
    calls: list[dict[str, object]] = []

    class _ReplanFacade(_FakeWriterFacade):
        def writer_action(self, **kwargs: Any) -> dict[str, Any]:
            self.calls.append(kwargs)
            if kwargs.get("action") == "replan_chapter":
                _write_writer_state(
                    tmp_path=self.tmp_path,
                    task_id="book-one",
                    run_id="run-1",
                    stage="freeze_d",
                    pending_checkpoint=False,
                )
                return {"status": "ready_for_execution", "run_id": "run-1"}
            return {"status": "waiting_for_review", "run_id": "run-1"}

    _write_writer_state(
        tmp_path=tmp_path,
        task_id="book-one",
        run_id="run-1",
        stage="wait_chapter_acceptance",
        pending_checkpoint=False,
    )
    fake_facade = _ReplanFacade(tmp_path=tmp_path, calls=calls)
    session = WebSessionService(repo_root=tmp_path, facade=fake_facade)
    job_manager = JobManager(repo_root=tmp_path)
    action_service = WebActionService(
        session_service=session,
        job_manager=job_manager,
        artifact_view_service=ArtifactViewService(repo_root=tmp_path, facade=fake_facade),
    )

    async def run_action() -> str:
        result = await action_service.execute(
            task_id="book-one",
            request=WebActionRequest(action="replan_chapter", payload={"feedback_text": "重写梗概后继续生成草稿。"}),
        )
        assert result.job is not None
        summary = await job_manager.wait(result.job.job_id, timeout=2.0)
        assert summary.status == "succeeded"
        return result.job.job_id

    job_id = asyncio.run(run_action())

    terminal_event = job_manager.events(job_id)[-1]
    assert terminal_event.kind == "succeeded"
    assert terminal_event.payload["decision_cards"][0]["actions"][0]["action"] == "resume"
    assert terminal_event.payload["decision_cards"][0]["actions"][0]["label"] == "生成当前章草稿"
    messages = session.messages("book-one")
    assert messages[-1].decision_cards[0].actions[0]["action"] == "resume"
    assert messages[-1].decision_cards[0].actions[0]["label"] == "生成当前章草稿"


def test_resume_action_replays_writer_review_card_without_workflow_call(tmp_path: Path) -> None:
    calls: list[dict[str, object]] = []
    fake_facade = _FakeWriterFacade(tmp_path=tmp_path, calls=calls)
    artifact_path = tmp_path / "runs" / "writer" / "run-1" / "batch_plan.json"
    _write_writer_state(
        tmp_path=tmp_path,
        task_id="book-one",
        run_id="run-1",
        stage="batch_review",
        artifact_path=str(artifact_path),
    )
    artifact_path.write_text(
        json.dumps({"data": {"stage_goal": "把旧案线索推到新地点。"}}, ensure_ascii=False),
        encoding="utf-8",
    )
    action_service, _job_manager = _writer_action_service(tmp_path=tmp_path, fake_facade=fake_facade)

    async def run_action() -> None:
        result = await action_service.execute(
            task_id="book-one",
            request=WebActionRequest(action="resume", payload={"run_id": "run-1"}),
        )
        assert result.job is None
        assert result.message == "已恢复到上一次等待点，请在会话卡片中继续。"

    asyncio.run(run_action())

    assert calls == []
    messages = action_service.session_service.messages("book-one")
    assert any(message.writer_artifact_review is not None for message in messages)


def test_resume_action_continues_confirmed_writer_stage(tmp_path: Path) -> None:
    calls: list[dict[str, object]] = []
    fake_facade = _FakeWriterFacade(tmp_path=tmp_path, calls=calls)
    _write_writer_state(
        tmp_path=tmp_path,
        task_id="book-one",
        run_id="run-1",
        stage="freeze_a",
        pending_checkpoint=False,
    )
    action_service, job_manager = _writer_action_service(tmp_path=tmp_path, fake_facade=fake_facade)

    async def run_action() -> None:
        result = await action_service.execute(
            task_id="book-one",
            request=WebActionRequest(action="resume", payload={"run_id": "run-1"}),
        )
        assert result.job is not None
        await job_manager.wait(result.job.job_id, timeout=1.0)

    asyncio.run(run_action())

    assert len(calls) == 1
    assert calls[0]["action"] == "prepare_batch_plan"
    assert calls[0]["run_id"] == "run-1"


def test_resume_action_explains_initialized_run_blocked_by_modeling(tmp_path: Path) -> None:
    calls: list[dict[str, object]] = []
    fake_facade = _FakeWriterFacade(tmp_path=tmp_path, calls=calls)
    run_dir = tmp_path / "runs" / "writer" / "run-1"
    run_dir.mkdir(parents=True, exist_ok=True)
    (run_dir / "workflow_state.json").write_text(
        json.dumps(
            {
                "data": {
                    "run_id": "run-1",
                    "book_id": "book-one",
                    "current_stage": "initialized",
                    "pending_checkpoint": None,
                }
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    (run_dir / "modeling_status.json").write_text(
        json.dumps(
            {
                "data": {
                    "book_id": "book-one",
                    "ready_for_continuation": False,
                    "missing_modeling_steps": ["memory.character_profiles"],
                }
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    action_service, _job_manager = _writer_action_service(tmp_path=tmp_path, fake_facade=fake_facade)

    async def run_action() -> None:
        result = await action_service.execute(
            task_id="book-one",
            request=WebActionRequest(action="resume", payload={"run_id": "run-1"}),
        )
        assert result.job is None
        assert "建模检查" in result.message
        assert result.decision_cards[0].actions[0]["action"] == "start_close_read"

    asyncio.run(run_action())

    assert calls == []
    messages = action_service.session_service.messages("book-one")
    assert messages[-1].decision_cards[0].title == "续写前还需要建模"


def test_resume_action_does_not_reoffer_creative_kb_when_current_db_is_ready(tmp_path: Path) -> None:
    calls: list[dict[str, object]] = []
    current_status = ModelingStatusSnapshot(
        book_id="book-one",
        documents_ready=True,
        close_read_ready=True,
        character_profiles_ready=True,
        world_summary_ready=True,
        story_outline_ready=True,
        creative_kb_ready=True,
        source_arc_map_ready=True,
        counts={
            "documents": 4,
            "chapters": 4,
            "character_profiles": 3,
            "fragment_cards": 4,
            "fragment_card_docs": 4,
            "fragment_clusters": 2,
        },
    )
    fake_facade = _FakeWriterFacade(tmp_path=tmp_path, calls=calls, modeling_status=current_status)
    run_dir = tmp_path / "runs" / "writer" / "run-1"
    run_dir.mkdir(parents=True, exist_ok=True)
    (run_dir / "workflow_state.json").write_text(
        json.dumps(
            {
                "data": {
                    "run_id": "run-1",
                    "book_id": "book-one",
                    "current_stage": "initialized",
                    "pending_checkpoint": None,
                }
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    (run_dir / "modeling_status.json").write_text(
        json.dumps(
            {
                "data": {
                    "book_id": "book-one",
                    "ready_for_continuation": False,
                    "missing_modeling_steps": ["creative_kb.fragment_cards"],
                }
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    action_service, _job_manager = _writer_action_service(tmp_path=tmp_path, fake_facade=fake_facade)

    async def run_action() -> None:
        result = await action_service.execute(
            task_id="book-one",
            request=WebActionRequest(action="resume", payload={"run_id": "run-1"}),
        )
        assert result.job is None
        assert "Creative KB" not in result.message
        assert not result.decision_cards[0].actions

    asyncio.run(run_action())

    assert calls == []
    messages = action_service.session_service.messages("book-one")
    assert messages[-1].decision_cards[0].title == "续写任务未生成可审阅内容"


def test_resume_action_ignores_optional_modeling_checks_when_missing_steps_empty(tmp_path: Path) -> None:
    calls: list[dict[str, object]] = []
    fake_facade = _FakeWriterFacade(tmp_path=tmp_path, calls=calls)
    run_dir = tmp_path / "runs" / "writer" / "run-optional"
    run_dir.mkdir(parents=True, exist_ok=True)
    (run_dir / "workflow_state.json").write_text(
        json.dumps(
            {
                "data": {
                    "run_id": "run-optional",
                    "book_id": "book-one",
                    "current_stage": "freeze_a",
                    "pending_checkpoint": None,
                }
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    (run_dir / "modeling_status.json").write_text(
        json.dumps(
            {
                "data": {
                    "book_id": "book-one",
                    "ready_for_continuation": True,
                    "missing_modeling_steps": [],
                    "checks": [
                        {"name": "documents_index", "ready": True},
                        {"name": "character_profiles", "ready": True},
                        {"name": "story_outline", "ready": True},
                        {"name": "world_summary", "ready": True},
                        {"name": "creative_kb", "ready": True},
                        {"name": "source_arc_map", "ready": False},
                        {"name": "narrative_structure_patterns", "ready": False},
                    ],
                }
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    action_service, job_manager = _writer_action_service(tmp_path=tmp_path, fake_facade=fake_facade)

    async def run_action() -> None:
        result = await action_service.execute(
            task_id="book-one",
            request=WebActionRequest(action="resume", payload={"run_id": "run-optional"}),
        )
        assert result.job is not None
        summary = await job_manager.wait(result.job.job_id, timeout=2.0)
        assert summary.status == "succeeded"

    asyncio.run(run_action())

    assert calls
    assert calls[0]["action"] == "prepare_batch_plan"
    messages = action_service.session_service.messages("book-one")
    assert all("源作品篇章地图" not in message.content for message in messages)


def test_latest_writer_state_ignores_cancelled_start_writer_run(tmp_path: Path) -> None:
    fake_facade = _FakeWriterFacade(tmp_path=tmp_path, calls=[])
    _write_writer_state(
        tmp_path=tmp_path,
        task_id="book-one",
        run_id="good-run",
        stage="freeze_a",
        pending_checkpoint=False,
    )
    _write_writer_state(
        tmp_path=tmp_path,
        task_id="book-one",
        run_id="cancelled-run",
        stage="freeze_a_review",
    )
    events_path = tmp_path / "runs" / "web_jobs" / "job-1" / "events.jsonl"
    events_path.parent.mkdir(parents=True, exist_ok=True)
    events = [
        {"event_id": "000001", "kind": "queued", "payload": {"type": "writer"}},
        {"event_id": "000002", "kind": "progress", "payload": {"run_id": "cancelled-run"}},
        {"event_id": "000003", "kind": "cancelled", "payload": {}},
    ]
    events_path.write_text("\n".join(json.dumps(event) for event in events), encoding="utf-8")
    session = WebSessionService(repo_root=tmp_path, facade=fake_facade)

    assert session.latest_writer_state("book-one")["run_id"] == "good-run"


def test_latest_writer_state_skips_dry_run_planning_artifacts(tmp_path: Path) -> None:
    fake_facade = _FakeWriterFacade(tmp_path=tmp_path, calls=[])
    _write_writer_state(
        tmp_path=tmp_path,
        task_id="book-one",
        run_id="real-run",
        stage="freeze_a_review",
    )
    _write_writer_state(
        tmp_path=tmp_path,
        task_id="book-one",
        run_id="dry-run",
        stage="freeze_c",
        pending_checkpoint=False,
    )
    _write_dry_run_writer_artifacts(tmp_path / "runs" / "writer" / "dry-run")
    session = WebSessionService(repo_root=tmp_path, facade=fake_facade)

    assert session.latest_writer_state("book-one")["run_id"] == "real-run"


def test_writer_artifact_tree_uses_filtered_latest_writer_run(tmp_path: Path) -> None:
    client = TestClient(create_app(repo_root=tmp_path))
    client.post("/api/tasks", json={"task_id": "book-one", "source_path": ""})
    real_run_dir = tmp_path / "runs" / "writer" / "real-run"
    real_artifact_path = real_run_dir / "book_continuation_plan.json"
    _write_writer_state(
        tmp_path=tmp_path,
        task_id="book-one",
        run_id="real-run",
        stage="freeze_a_review",
        artifact_path=str(real_artifact_path),
    )
    real_artifact_path.write_text(
        json.dumps({"data": {"continuation_goal": "真实模型大纲"}}, ensure_ascii=False),
        encoding="utf-8",
    )
    (real_run_dir / "model_reasoning_debug.json").write_text(
        json.dumps({"data": {"items": [{"raw_visible_output": "{\"continuation_goal\":\"真实模型大纲\"}"}]}}, ensure_ascii=False),
        encoding="utf-8",
    )
    _write_writer_state(
        tmp_path=tmp_path,
        task_id="book-one",
        run_id="dry-run",
        stage="freeze_c",
        pending_checkpoint=False,
    )
    _write_dry_run_writer_artifacts(tmp_path / "runs" / "writer" / "dry-run")

    tree = client.get("/api/tasks/book-one/artifact-tree?surface=writer")

    assert tree.status_code == 200
    descriptors = [decode_artifact_id(node["id"]) for node in tree.json()]
    assert {descriptor.get("run_id") for descriptor in descriptors} == {"real-run"}


def test_latest_writer_state_keeps_cancelled_run_when_review_artifact_exists(tmp_path: Path) -> None:
    fake_facade = _FakeWriterFacade(tmp_path=tmp_path, calls=[])
    run_dir = tmp_path / "runs" / "writer" / "cancelled-but-reviewable"
    artifact_path = run_dir / "book_continuation_plan.json"
    _write_writer_state(
        tmp_path=tmp_path,
        task_id="book-one",
        run_id="cancelled-but-reviewable",
        stage="freeze_a_review",
        artifact_path=str(artifact_path),
    )
    artifact_path.write_text(
        json.dumps({"data": {"continuation_goal": "真实模型大纲"}}, ensure_ascii=False),
        encoding="utf-8",
    )
    (run_dir / "model_reasoning_debug.json").write_text(
        json.dumps({"data": {"items": [{"raw_visible_output": "{\"continuation_goal\":\"真实模型大纲\"}"}]}}, ensure_ascii=False),
        encoding="utf-8",
    )
    events_path = tmp_path / "runs" / "web_jobs" / "job-1" / "events.jsonl"
    events_path.parent.mkdir(parents=True, exist_ok=True)
    events = [
        {"event_id": "000001", "kind": "queued", "payload": {"type": "writer"}},
        {"event_id": "000002", "kind": "progress", "payload": {"run_id": "cancelled-but-reviewable"}},
        {"event_id": "000003", "kind": "cancelled", "payload": {}},
    ]
    events_path.write_text("\n".join(json.dumps(event) for event in events), encoding="utf-8")
    _write_writer_state(
        tmp_path=tmp_path,
        task_id="book-one",
        run_id="dry-run",
        stage="freeze_c",
        pending_checkpoint=False,
    )
    _write_dry_run_writer_artifacts(tmp_path / "runs" / "writer" / "dry-run")
    session = WebSessionService(repo_root=tmp_path, facade=fake_facade)

    assert session.latest_writer_state("book-one")["run_id"] == "cancelled-but-reviewable"


def test_scoped_revision_action_uses_current_writer_artifact(tmp_path: Path) -> None:
    calls: list[dict[str, object]] = []
    fake_facade = _FakeWriterFacade(tmp_path=tmp_path, calls=calls)
    artifact_path = tmp_path / "runs" / "writer" / "run-1" / "batch_plan.json"
    _write_writer_state(
        tmp_path=tmp_path,
        task_id="book-one",
        run_id="run-1",
        stage="batch_review",
        artifact_path=str(artifact_path),
    )
    action_service, job_manager = _writer_action_service(tmp_path=tmp_path, fake_facade=fake_facade)

    async def run_action() -> None:
        result = await action_service.execute(
            task_id="book-one",
            request=WebActionRequest(action="request_scoped_artifact_revision", payload={"feedback": "把节奏放慢一点。"}),
        )
        assert result.job is not None
        summary = await job_manager.wait(result.job.job_id, timeout=2.0)
        assert summary.status == "succeeded"

    asyncio.run(run_action())

    assert calls
    call_payload = calls[0]["payload"]
    assert calls[0]["action"] == "request_scoped_artifact_revision"
    assert call_payload["user_feedback"] == "把节奏放慢一点。"  # type: ignore[index]
    assert call_payload["target_stage"] == "batch_review"  # type: ignore[index]
    assert call_payload["target_artifact_path"] == str(artifact_path)  # type: ignore[index]


def test_web_artifact_review_actions_map_to_writer_contract(tmp_path: Path) -> None:
    calls: list[dict[str, object]] = []
    fake_facade = _FakeWriterFacade(tmp_path=tmp_path, calls=calls)
    artifact_path = tmp_path / "runs" / "writer" / "run-1" / "chapter_package.json"
    _write_writer_state(
        tmp_path=tmp_path,
        task_id="book-one",
        run_id="run-1",
        stage="chapter_review",
        artifact_path=str(artifact_path),
    )
    action_service, job_manager = _writer_action_service(tmp_path=tmp_path, fake_facade=fake_facade)

    async def run_action() -> None:
        result = await action_service.execute(
            task_id="book-one",
            request=WebActionRequest(
                action="approve_writer_artifact",
                payload={
                    "supplement_text": "本章控制在三千字左右，动作段更紧。",
                    "source_message_id": "message-1",
                },
            ),
        )
        assert result.job is not None
        summary = await job_manager.wait(result.job.job_id, timeout=2.0)
        assert summary.status == "succeeded"

    asyncio.run(run_action())

    assert calls
    assert calls[0]["action"] == "approve_writer_artifact"
    payload = calls[0]["payload"]
    assert payload["supplement_text"] == "本章控制在三千字左右，动作段更紧。"  # type: ignore[index]
    assert payload["artifact_path"] == str(artifact_path)  # type: ignore[index]
    assert payload["source_message_id"] == "message-1"  # type: ignore[index]


def test_web_revision_action_preserves_revision_feedback(tmp_path: Path) -> None:
    calls: list[dict[str, object]] = []
    fake_facade = _FakeWriterFacade(tmp_path=tmp_path, calls=calls)
    artifact_path = tmp_path / "runs" / "writer" / "run-1" / "chapter_package.json"
    _write_writer_state(
        tmp_path=tmp_path,
        task_id="book-one",
        run_id="run-1",
        stage="chapter_review",
        artifact_path=str(artifact_path),
    )
    action_service, job_manager = _writer_action_service(tmp_path=tmp_path, fake_facade=fake_facade)

    async def run_action() -> None:
        result = await action_service.execute(
            task_id="book-one",
            request=WebActionRequest(
                action="request_writer_artifact_revision",
                payload={"revision_feedback": "把结尾悬念后移，不要提前解释。"},
            ),
        )
        assert result.job is not None
        summary = await job_manager.wait(result.job.job_id, timeout=2.0)
        assert summary.status == "succeeded"

    asyncio.run(run_action())

    assert calls
    assert calls[0]["action"] == "request_writer_artifact_revision"
    payload = calls[0]["payload"]
    assert payload["revision_feedback"] == "把结尾悬念后移，不要提前解释。"  # type: ignore[index]
    assert payload["artifact_path"] == str(artifact_path)  # type: ignore[index]


def test_web_artifact_defer_action_preserves_review_gate(tmp_path: Path) -> None:
    calls: list[dict[str, object]] = []
    fake_facade = _FakeWriterFacade(tmp_path=tmp_path, calls=calls)
    artifact_path = tmp_path / "runs" / "writer" / "run-1" / "chapter_package.json"
    _write_writer_state(
        tmp_path=tmp_path,
        task_id="book-one",
        run_id="run-1",
        stage="chapter_review",
        artifact_path=str(artifact_path),
    )
    action_service, job_manager = _writer_action_service(tmp_path=tmp_path, fake_facade=fake_facade)

    async def run_action() -> None:
        result = await action_service.execute(
            task_id="book-one",
            request=WebActionRequest(action="defer_writer_artifact_review", payload={}),
        )
        assert result.job is not None
        summary = await job_manager.wait(result.job.job_id, timeout=2.0)
        assert summary.status == "succeeded"

    asyncio.run(run_action())

    assert calls
    assert calls[0]["action"] == "defer_writer_artifact_review"
    assert calls[0]["payload"]["artifact_path"] == str(artifact_path)  # type: ignore[index]


def test_plain_chat_message_does_not_advance_writer_needs_user_input(tmp_path: Path) -> None:
    calls: list[dict[str, object]] = []
    fake_facade = _FakeWriterFacade(tmp_path=tmp_path, calls=calls)
    run_dir = tmp_path / "runs" / "writer" / "run-1"
    run_dir.mkdir(parents=True, exist_ok=True)
    (run_dir / "workflow_state.json").write_text(
        json.dumps(
            {
                "data": {
                    "run_id": "run-1",
                    "book_id": "book-one",
                    "current_stage": "outline_research_user_input",
                    "agent_state": "needs_user_input",
                    "pending_checkpoint": {"stage": "outline_research_user_input"},
                }
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    session = WebSessionService(repo_root=tmp_path, facade=fake_facade)

    session.append_user_message("book-one", "我觉得可以先让新角色只在传闻中出现。")

    state_after = session.latest_writer_state("book-one")
    assert state_after["current_stage"] == "outline_research_user_input"
    assert state_after["agent_state"] == "needs_user_input"
    assert calls == []


def test_run_writer_workflow_action_accepts_chapter_review_actions(tmp_path: Path) -> None:
    workflow = _FakeWriterWorkflow(tmp_path)

    result = run_writer_workflow_action(
        workflow=workflow,  # type: ignore[arg-type]
        conn=object(),  # type: ignore[arg-type]
        action="accept_chapter",
        run_id="run-1",
        book_id="book-one",
        product_mode="assist",
        payload={"feedback": "当前稿可以进入写回。"},
    )

    assert result == {"stage": "writeback_review"}
    assert workflow.review_decision["status"] == "accepted"
    assert workflow.review_decision["next_action"] == "writeback_review"


def test_chapter_rewrite_replan_discard_and_defer_actions(tmp_path: Path) -> None:
    calls: list[dict[str, object]] = []
    fake_facade = _FakeWriterFacade(tmp_path=tmp_path, calls=calls)
    draft_path = tmp_path / "runs" / "writer" / "run-1" / "draft.md"
    _write_writer_state(
        tmp_path=tmp_path,
        task_id="book-one",
        run_id="run-1",
        stage="wait_chapter_acceptance",
        artifact_path=str(draft_path),
    )
    action_service, job_manager = _writer_action_service(tmp_path=tmp_path, fake_facade=fake_facade)

    async def run_action(action: str, payload: dict[str, object]) -> None:
        result = await action_service.execute(task_id="book-one", request=WebActionRequest(action=action, payload=payload))
        assert result.job is not None
        summary = await job_manager.wait(result.job.job_id, timeout=2.0)
        assert summary.status == "succeeded"

    asyncio.run(run_action("rewrite_chapter", {"feedback_text": "节奏太慢，冲突提前。", "source_message_id": "m1"}))
    asyncio.run(run_action("replan_chapter", {"feedback_text": "先补人物动机再进入冲突。", "source_message_id": "m2"}))
    asyncio.run(run_action("discard_chapter", {"feedback_text": "本次方向作废。", "source_message_id": "m3"}))

    async def defer_action() -> None:
        result = await action_service.execute(
            task_id="book-one",
            request=WebActionRequest(action="defer_chapter_acceptance", payload={"note": "稍后看"}),
        )
        assert result.job is None

    asyncio.run(defer_action())

    assert [call["action"] for call in calls] == ["rewrite_chapter", "replan_chapter", "discard_chapter"]
    assert calls[0]["payload"]["feedback_text"] == "节奏太慢，冲突提前。"  # type: ignore[index]
    assert calls[1]["payload"]["feedback_text"] == "先补人物动机再进入冲突。"  # type: ignore[index]
    assert calls[2]["payload"]["feedback_text"] == "本次方向作废。"  # type: ignore[index]


class _FakeWriterFacade:
    def __init__(
        self,
        *,
        tmp_path: Path,
        calls: list[dict[str, object]],
        modeling_status: ModelingStatusSnapshot | None = None,
    ) -> None:
        self.tmp_path = tmp_path
        self.calls = calls
        self._modeling_status = modeling_status
        from novel_agent.app.cli.events import RunEventStream

        self.event_stream = RunEventStream()

    def task_snapshot(self, *, book_id: str, source_path: str = "") -> TuiTaskSnapshot:
        return TuiTaskSnapshot(
            book_id=book_id,
            source_path=source_path,
            db_path=self.tmp_path / ".indexes" / f"{book_id}.db",
        )

    def list_tasks(self) -> list[TuiTaskSnapshot]:
        return [self.task_snapshot(book_id="book-one")]

    def modeling_status(self, *, book_id: str, db_path: Path | None = None) -> ModelingStatusSnapshot:
        if self._modeling_status is not None:
            return self._modeling_status
        return ModelingStatusSnapshot(
            book_id=book_id,
            documents_ready=False,
            close_read_ready=False,
            character_profiles_ready=False,
            world_summary_ready=False,
            story_outline_ready=False,
            creative_kb_ready=False,
            source_arc_map_ready=False,
            counts={"documents": 0, "chapters": 0, "character_profiles": 0, "fragment_cards": 0},
        )

    def writer_action(self, **kwargs: Any) -> dict[str, Any]:
        self.calls.append(kwargs)
        self.event_stream.emit("系统", "Writer 状态已更新", payload={"action": kwargs.get("action")})
        return {"status": "waiting_for_review", "run_id": kwargs.get("run_id", "")}

    def start_writer(self, **kwargs: Any) -> dict[str, Any]:
        self.calls.append(kwargs)
        self.event_stream.emit("系统", "Writer 已到达可审阅节点", payload={"run_id": kwargs.get("run_id", "")})
        return {"status": "waiting_for_review", "run_id": kwargs.get("run_id", "")}


def _writer_action_service(
    *,
    tmp_path: Path,
    fake_facade: _FakeWriterFacade,
) -> tuple[WebActionService, JobManager]:
    session = WebSessionService(repo_root=tmp_path, facade=fake_facade)
    job_manager = JobManager(repo_root=tmp_path)
    return (
        WebActionService(
            session_service=session,
            job_manager=job_manager,
            artifact_view_service=ArtifactViewService(repo_root=tmp_path, facade=fake_facade),
        ),
        job_manager,
    )


def _find_artifact_id(nodes: list[dict[str, Any]], label: str) -> str:
    for node in nodes:
        if node.get("label") == label:
            return str(node["id"])
        found = _find_artifact_id(node.get("children", []), label)
        if found:
            return found
    return ""


def _write_writer_state(
    *,
    tmp_path: Path,
    task_id: str,
    run_id: str,
    stage: str,
    artifact_path: str = "",
    pending_checkpoint: bool = True,
) -> None:
    run_dir = tmp_path / "runs" / "writer" / run_id
    run_dir.mkdir(parents=True, exist_ok=True)
    (run_dir / "workflow_state.json").write_text(
        json.dumps(
            {
                "data": {
                    "run_id": run_id,
                    "book_id": task_id,
                    "current_stage": stage,
                    "pending_checkpoint": (
                        {
                            "stage": stage,
                            "artifact_path": artifact_path,
                        }
                        if pending_checkpoint
                        else None
                    ),
                }
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )


def _write_dry_run_writer_artifacts(run_dir: Path) -> None:
    run_dir.mkdir(parents=True, exist_ok=True)
    (run_dir / "model_reasoning_debug.json").write_text(
        json.dumps(
            {
                "data": {
                    "items": [
                        {
                            "source": "structured_decision_trace",
                            "note": "Model provider did not return a separate visible reasoning/debug field.",
                        }
                    ]
                }
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    (run_dir / "book_continuation_plan.json").write_text(
        json.dumps({"data": {"continuation_goal": "承接原作大纲推进后续主线。"}}, ensure_ascii=False),
        encoding="utf-8",
    )
    (run_dir / "batch_plan.json").write_text(
        json.dumps(
            {
                "data": {
                    "batch_goal": "承接原作大纲推进后续主线。",
                    "must_resolve": ["承接现有主线并推进一个阶段冲突"],
                }
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    (run_dir / "chapter_package.json").write_text(
        json.dumps(
            {
                "data": {
                    "chapters": [{"title": "第1章 批次推进"}],
                    "review_notes": ["可逐章微调 ChapterBrief，但不得突破 BatchPlan 上限。"],
                }
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )


class _FakeWriterWorkflow:
    def __init__(self, tmp_path: Path) -> None:
        self.run_writer = _FakeRunWriter(tmp_path, self)
        self.review_decision: dict[str, Any] = {}

    def load_workflow_state(self, *, run_id: str) -> dict[str, Any]:
        return {
            "run_id": run_id,
            "book_id": "book-one",
            "current_chapter_id": "chapter-1",
            "current_draft_id": "draft-001",
        }

    def continue_after_chapter_acceptance(self, *, run_id: str) -> dict[str, str]:
        return {"stage": "writeback_review"}


class _FakeRunWriter:
    def __init__(self, tmp_path: Path, workflow: _FakeWriterWorkflow) -> None:
        self.layout = _FakeRunLayout(tmp_path)
        self.workflow = workflow

    def write_generation_review_decision(self, run_id: str, payload: dict[str, Any]) -> None:
        self.workflow.review_decision = payload


class _FakeRunLayout:
    def __init__(self, tmp_path: Path) -> None:
        self.tmp_path = tmp_path

    def run_dir(self, run_id: str) -> Path:
        path = self.tmp_path / "runs" / "writer" / run_id
        path.mkdir(parents=True, exist_ok=True)
        return path

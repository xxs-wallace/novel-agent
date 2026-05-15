from __future__ import annotations

import asyncio
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from fastapi.testclient import TestClient

from novel_agent.app.cli.facade import ModelingStatusSnapshot, TuiTaskSnapshot
from novel_agent.app.cli.status import StatusPresenter
from novel_agent.app.repos.chapters_repo import ChaptersRepo
from novel_agent.app.repos.db import NovelAgentDB
from novel_agent.app.run_interactive import run_writer_workflow_action
from novel_agent.app.web.main import create_app
from novel_agent.app.web.schemas import JobSummary, WebActionRequest
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
    assert action_payload["decision_cards"]
    assert "/writer" not in json.dumps(action_payload, ensure_ascii=False)

    command = client.post("/api/tasks/book-one/commands", json={"command": "/status"})
    assert command.status_code == 200
    assert command.json()["action"] == "commands"
    assert command.json()["progress"]["task_id"] == "book-one"


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
    assert "请确认本章写作材料" in rendered
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
    assert payload["flow"] == "精读"
    assert payload["step"] == "正在精读章节"
    assert payload["next_action"] == "整理人物、世界观与大纲"

    tasks = client.get("/api/tasks")

    assert tasks.status_code == 200
    assert tasks.json()[0]["active_job"]["job_id"] == "job-close-read"


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


def test_start_read_action_runs_real_facade_pipeline(tmp_path: Path, monkeypatch) -> None:  # type: ignore[no-untyped-def]
    source_path = tmp_path / "source.txt"
    source_path.write_text("第一章\n\n一个可供粗读的段落。", encoding="utf-8")
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
            self.event_stream.emit("系统", "粗读/精读本轮已完成", payload={"inserted_documents": 1})
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
        assert "粗读/精读本轮已完成" in rendered
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
    source_path.write_text("第一章\n\n一个需要完整粗读的段落。", encoding="utf-8")
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
    source_path.write_text("第一章\n\n一个可供精读的段落。", encoding="utf-8")
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

    assert calls
    assert calls[0]["action"] == "accept_chapter"
    assert calls[0]["payload"]["user_feedback"] == "这一章可以接受。"  # type: ignore[index]


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


def test_run_writer_workflow_action_accepts_chapter_review_actions(tmp_path: Path) -> None:
    workflow = _FakeWriterWorkflow(tmp_path)

    result = run_writer_workflow_action(
        workflow=workflow,  # type: ignore[arg-type]
        conn=object(),  # type: ignore[arg-type]
        action="revise_chapter_length",
        run_id="run-1",
        book_id="book-one",
        product_mode="assist",
        payload={"feedback": "压缩到 1200 字，减少内心独白。", "target_chars": 1200},
    )

    assert result == {"stage": "wait_length_review"}
    assert workflow.review_decision["status"] == "revise_length"
    assert workflow.review_decision["feedback_text"] == "压缩到 1200 字，减少内心独白。"
    assert workflow.review_decision["length_plan_update"]["target_chars"] == 1200


class _FakeWriterFacade:
    def __init__(self, *, tmp_path: Path, calls: list[dict[str, object]]) -> None:
        self.tmp_path = tmp_path
        self.calls = calls
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
    artifact_path: str,
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
                    "pending_checkpoint": {
                        "stage": stage,
                        "artifact_path": artifact_path,
                    },
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
        return {"stage": "wait_length_review"}


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

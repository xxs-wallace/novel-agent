from __future__ import annotations

import asyncio
import json
from datetime import datetime, timezone
from pathlib import Path

from fastapi.testclient import TestClient

from novel_agent.app.web.main import create_app
from novel_agent.app.web.services.job_manager import JobContext, JobManager


def test_job_manager_fake_runner_emits_and_replays_events(tmp_path: Path) -> None:
    async def run() -> None:
        manager = JobManager(repo_root=tmp_path)

        async def fake_runner(context: JobContext) -> dict[str, object]:
            context.emit("progress", "第一步完成", payload={"step": 1})
            context.emit("progress", "第二步完成", payload={"step": 2})
            return {"ok": True}

        summary = await manager.create_job(task_id="book-one", job_type="fake", runner=fake_runner)
        done = await manager.wait(summary.job_id)
        assert done.status == "succeeded"
        events = manager.events(summary.job_id)
        assert [event.kind for event in events] == ["queued", "running", "progress", "progress", "succeeded"]
        replay = manager.events(summary.job_id, after_event_id="000002")
        assert [event.message for event in replay] == ["第一步完成", "第二步完成", "后台任务已完成"]

    asyncio.run(run())


def test_job_manager_cancel_marks_running_job_cancelled(tmp_path: Path) -> None:
    async def run() -> None:
        manager = JobManager(repo_root=tmp_path)

        async def slow_runner(context: JobContext) -> dict[str, object]:
            for index in range(20):
                if context.should_cancel():
                    return {"cancelled_at": index}
                await asyncio.sleep(0.01)
            return {"ok": True}

        summary = await manager.create_job(task_id="book-one", job_type="fake", runner=slow_runner)
        await asyncio.sleep(0.02)
        cancelled = await manager.cancel_job(summary.job_id)
        assert cancelled.status == "cancelled"
        assert any(event.kind == "cancelled" for event in manager.events(summary.job_id))

    asyncio.run(run())


def test_job_manager_reuses_active_job_for_same_task_and_type(tmp_path: Path) -> None:
    async def run() -> None:
        manager = JobManager(repo_root=tmp_path)
        calls = 0

        async def slow_runner(_context: JobContext) -> dict[str, object]:
            nonlocal calls
            calls += 1
            await asyncio.sleep(0.05)
            return {"ok": True}

        first = await manager.create_job(task_id="book-one", job_type="read", runner=slow_runner)
        second = await manager.create_job(task_id="book-one", job_type="read", runner=slow_runner)

        assert second.job_id == first.job_id
        assert second.message == "已有后台任务正在运行"
        assert calls == 0
        events = manager.events(first.job_id)
        assert any(event.payload.get("deduplicated") is True for event in events)

        done = await manager.wait(first.job_id)
        assert done.status == "succeeded"
        assert calls == 1

    asyncio.run(run())


def test_job_manager_reuses_conflicting_task_job(tmp_path: Path) -> None:
    async def run() -> None:
        manager = JobManager(repo_root=tmp_path)
        calls: list[str] = []

        async def slow_read(_context: JobContext) -> dict[str, object]:
            calls.append("read")
            await asyncio.sleep(0.05)
            return {"ok": True}

        async def close_read(_context: JobContext) -> dict[str, object]:
            calls.append("close_read")
            return {"ok": True}

        first = await manager.create_job(task_id="book-one", job_type="read", runner=slow_read)
        second = await manager.create_job(
            task_id="book-one",
            job_type="close_read",
            runner=close_read,
            conflict_job_types={"read", "close_read"},
        )

        assert second.job_id == first.job_id
        assert second.type == "read"
        assert second.message == "已有后台任务正在运行"
        assert any(event.payload.get("requested_type") == "close_read" for event in manager.events(first.job_id))

        done = await manager.wait(first.job_id)
        assert done.status == "succeeded"
        assert calls == ["read"]

    asyncio.run(run())


def test_job_manager_failure_event_preserves_traceback_for_task_details(tmp_path: Path) -> None:
    async def run() -> None:
        manager = JobManager(repo_root=tmp_path)

        async def failing_runner(_context: JobContext) -> dict[str, object]:
            raise RuntimeError("boom")

        summary = await manager.create_job(task_id="book-one", job_type="fake", runner=failing_runner)
        done = await manager.wait(summary.job_id)
        assert done.status == "failed"
        error_event = [event for event in manager.events(summary.job_id) if event.kind == "error"][0]
        assert error_event.payload["recovery_suggestion"]
        assert "已保留错误栈" in error_event.message
        assert error_event.payload["error"] == "boom"
        assert error_event.payload["error_type"] == "RuntimeError"
        assert "Traceback" in error_event.payload["traceback"]
        assert manager._records[summary.job_id].result["traceback"] == error_event.payload["traceback"]  # noqa: SLF001

    asyncio.run(run())


def test_job_manager_recovers_interrupted_persisted_job_as_failed(tmp_path: Path) -> None:
    job_dir = tmp_path / "runs" / "web_jobs" / "job-interrupted"
    job_dir.mkdir(parents=True)
    now = datetime.now(timezone.utc).isoformat()
    (job_dir / "job.json").write_text(
        json.dumps(
            {
                "schema_version": "1.0",
                "job_id": "job-interrupted",
                "task_id": "book-one",
                "type": "close_read",
                "status": "running",
                "payload": {"action": "start_close_read"},
                "message": "后台任务正在运行",
                "cancel_requested": False,
                "created_at": now,
                "updated_at": now,
                "result": {},
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    (job_dir / "events.jsonl").write_text(
        "\n".join(
            [
                json.dumps(
                    {
                        "event_id": "000001",
                        "job_id": "job-interrupted",
                        "kind": "queued",
                        "message": "任务已加入后台队列",
                        "payload": {"task_id": "book-one", "type": "close_read"},
                        "created_at": now,
                    },
                    ensure_ascii=False,
                ),
                json.dumps(
                    {
                        "event_id": "000002",
                        "job_id": "job-interrupted",
                        "kind": "running",
                        "message": "后台任务正在运行",
                        "payload": {},
                        "created_at": now,
                    },
                    ensure_ascii=False,
                ),
            ]
        )
        + "\n",
        encoding="utf-8",
    )

    manager = JobManager(repo_root=tmp_path)

    summary = manager.summary("job-interrupted")
    assert summary.status == "failed"
    assert summary.task_id == "book-one"
    assert summary.type == "close_read"
    error_events = [event for event in manager.events("job-interrupted") if event.kind == "error"]
    assert len(error_events) == 1
    assert error_events[0].payload["error_type"] == "ServiceInterrupted"
    assert "web_launcher.log" in error_events[0].payload["recovery_suggestion"]

    reloaded = JobManager(repo_root=tmp_path)
    assert reloaded.summary("job-interrupted").status == "failed"
    assert len([event for event in reloaded.events("job-interrupted") if event.kind == "error"]) == 1


def test_job_manager_recovers_legacy_close_read_event_log_as_failed(tmp_path: Path) -> None:
    job_dir = tmp_path / "runs" / "web_jobs" / "legacy-job"
    job_dir.mkdir(parents=True)
    pipeline_dir = tmp_path / "runs" / "web_pipeline" / "book-one"
    pipeline_dir.mkdir(parents=True)
    (pipeline_dir / "read_legacy-job.md").write_text("# debug\n", encoding="utf-8")
    now = datetime.now(timezone.utc).isoformat()
    (job_dir / "events.jsonl").write_text(
        "\n".join(
            [
                json.dumps(
                    {
                        "event_id": "000001",
                        "job_id": "legacy-job",
                        "kind": "queued",
                        "message": "任务已加入后台队列",
                        "payload": {"type": "close_read", "request_payload": {"action": "start_close_read"}},
                        "created_at": now,
                    },
                    ensure_ascii=False,
                ),
                json.dumps(
                    {
                        "event_id": "000002",
                        "job_id": "legacy-job",
                        "kind": "progress",
                        "message": "正在调用模型：人物证据",
                        "payload": {"stage": "close_reading", "event": "prompt_start"},
                        "created_at": now,
                    },
                    ensure_ascii=False,
                ),
            ]
        )
        + "\n",
        encoding="utf-8",
    )

    manager = JobManager(repo_root=tmp_path)

    summary = manager.summary("legacy-job")
    assert summary.status == "failed"
    assert summary.task_id == "book-one"
    assert summary.type == "close_read"
    assert (job_dir / "job.json").exists()
    error_event = manager.events("legacy-job")[-1]
    assert error_event.kind == "error"
    assert error_event.payload["error_type"] == "ServiceInterrupted"


def test_job_events_endpoint_streams_sse_and_supports_replay(tmp_path: Path) -> None:
    client = TestClient(create_app(repo_root=tmp_path))
    created = client.post(
        "/api/tasks/book-one/jobs",
        json={"type": "fake", "payload": {"fake_events": ["准备材料", "生成摘要"]}},
    )
    assert created.status_code == 200
    job_id = created.json()["job_id"]

    for _ in range(50):
        summary = client.get(f"/api/jobs/{job_id}").json()
        if summary["status"] == "succeeded":
            break
    assert summary["status"] == "succeeded"

    streamed = client.get(f"/api/jobs/{job_id}/events")
    assert streamed.status_code == 200
    assert "text/event-stream" in streamed.headers["content-type"]
    assert "准备材料" in streamed.text
    assert "生成摘要" in streamed.text

    replay = client.get(f"/api/jobs/{job_id}/events?after_event_id=000002")
    assert replay.status_code == 200
    assert "任务已加入后台队列" not in replay.text
    assert "准备材料" in replay.text


def test_unknown_job_sse_returns_recovery_event_after_restart(tmp_path: Path) -> None:
    client = TestClient(create_app(repo_root=tmp_path))

    response = client.get("/api/jobs/missing-job/events")

    assert response.status_code == 200
    assert "后台任务不存在或服务已重启" in response.text
    assert "请重新触发对应动作" in response.text

from __future__ import annotations

import asyncio
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
        assert second.message == "已有同类后台任务正在运行"
        assert calls == 0
        events = manager.events(first.job_id)
        assert any(event.payload.get("deduplicated") is True for event in events)

        done = await manager.wait(first.job_id)
        assert done.status == "succeeded"
        assert calls == 1

    asyncio.run(run())


def test_job_manager_failure_event_has_recovery_suggestion_without_traceback(tmp_path: Path) -> None:
    async def run() -> None:
        manager = JobManager(repo_root=tmp_path)

        async def failing_runner(_context: JobContext) -> dict[str, object]:
            raise RuntimeError("boom")

        summary = await manager.create_job(task_id="book-one", job_type="fake", runner=failing_runner)
        done = await manager.wait(summary.job_id)
        assert done.status == "failed"
        error_event = [event for event in manager.events(summary.job_id) if event.kind == "error"][0]
        assert error_event.payload["recovery_suggestion"]
        assert "Traceback" not in error_event.message
        assert "Traceback" not in str(error_event.payload)

    asyncio.run(run())


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

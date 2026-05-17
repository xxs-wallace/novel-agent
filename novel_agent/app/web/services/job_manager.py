from __future__ import annotations

import asyncio
import json
import traceback
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Awaitable, Callable

from ..schemas import JobEventView, JobStatus, JobSummary


JobRunner = Callable[["JobContext"], Awaitable[dict[str, Any] | None]]


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _model_dump(model: Any) -> dict[str, Any]:
    if hasattr(model, "model_dump"):
        return model.model_dump()
    return model.dict()


@dataclass(slots=True)
class JobRecord:
    job_id: str
    task_id: str
    type: str
    status: JobStatus
    payload: dict[str, Any] = field(default_factory=dict)
    message: str = ""
    cancel_requested: bool = False
    created_at: datetime = field(default_factory=_utc_now)
    updated_at: datetime = field(default_factory=_utc_now)
    result: dict[str, Any] = field(default_factory=dict)


class JobContext:
    def __init__(self, manager: "JobManager", record: JobRecord) -> None:
        self._manager = manager
        self._record = record

    @property
    def job_id(self) -> str:
        return self._record.job_id

    @property
    def task_id(self) -> str:
        return self._record.task_id

    @property
    def job_type(self) -> str:
        return self._record.type

    @property
    def payload(self) -> dict[str, Any]:
        return dict(self._record.payload)

    def should_cancel(self) -> bool:
        return self._record.cancel_requested

    def emit(
        self,
        kind: str,
        message: str,
        *,
        payload: dict[str, Any] | None = None,
    ) -> JobEventView:
        return self._manager.emit_event(self.job_id, kind, message, payload=payload)


class JobManager:
    """Small in-process job runner with replayable event logs.

    The public contract is intentionally stable enough for the Web UI while
    leaving the actual read/close-read/writer work delegated to shared facade
    runners later.
    """

    TERMINAL_STATUSES: set[JobStatus] = {"succeeded", "failed", "cancelled"}

    def __init__(self, *, repo_root: Path) -> None:
        self.repo_root = repo_root.expanduser().resolve()
        self._records: dict[str, JobRecord] = {}
        self._events: dict[str, list[JobEventView]] = {}
        self._tasks: dict[str, asyncio.Task[None]] = {}
        self._condition = asyncio.Condition()

    async def create_job(
        self,
        *,
        task_id: str,
        job_type: str,
        payload: dict[str, Any] | None = None,
        runner: JobRunner | None = None,
        conflict_job_types: set[str] | None = None,
    ) -> JobSummary:
        active_record = self._active_record(task_id=task_id, job_type=job_type)
        if active_record is None and conflict_job_types is not None:
            active_record = self._active_record_for_task(task_id=task_id, job_types=conflict_job_types)
        if active_record is not None:
            active_record.message = "已有后台任务正在运行"
            active_record.updated_at = _utc_now()
            self.emit_event(
                active_record.job_id,
                "progress",
                "已有后台任务正在运行，本次点击已复用现有任务。",
                payload={"deduplicated": True, "type": active_record.type, "requested_type": job_type},
            )
            return self.summary(active_record.job_id)
        job_id = uuid.uuid4().hex
        record = JobRecord(
            job_id=job_id,
            task_id=task_id,
            type=job_type,
            status="queued",
            payload=dict(payload or {}),
            message="已加入后台队列",
        )
        self._records[job_id] = record
        self._events[job_id] = []
        self.emit_event(job_id, "queued", "任务已加入后台队列", payload={"type": job_type})
        task = asyncio.create_task(self._run_job(record, runner or self._default_runner))
        self._tasks[job_id] = task
        return self.summary(job_id)

    def _active_record(self, *, task_id: str, job_type: str) -> JobRecord | None:
        for record in self._records.values():
            if record.task_id != task_id or record.type != job_type:
                continue
            if record.status not in self.TERMINAL_STATUSES:
                return record
        return None

    def _active_record_for_task(self, *, task_id: str, job_types: set[str]) -> JobRecord | None:
        for record in self._records.values():
            if record.task_id != task_id or record.type not in job_types:
                continue
            if record.status not in self.TERMINAL_STATUSES:
                return record
        return None

    def summary(self, job_id: str) -> JobSummary:
        record = self._require_record(job_id)
        return JobSummary(
            job_id=record.job_id,
            task_id=record.task_id,
            type=record.type,
            status=record.status,
            message=record.message,
            cancel_requested=record.cancel_requested,
            created_at=record.created_at,
            updated_at=record.updated_at,
            events_url=f"/api/jobs/{record.job_id}/events",
        )

    def active_jobs(self, *, task_id: str | None = None, job_type: str | None = None) -> list[JobSummary]:
        jobs: list[JobSummary] = []
        for record in self._records.values():
            if record.status in self.TERMINAL_STATUSES:
                continue
            if task_id is not None and record.task_id != task_id:
                continue
            if job_type is not None and record.type != job_type:
                continue
            jobs.append(self.summary(record.job_id))
        return sorted(jobs, key=lambda job: job.created_at)

    def events(self, job_id: str, *, after_event_id: str = "") -> list[JobEventView]:
        self._require_record(job_id)
        events = list(self._events.get(job_id, []))
        if not after_event_id:
            return events
        return [event for event in events if self._event_index(event.event_id) > self._event_index(after_event_id)]

    def emit_event(
        self,
        job_id: str,
        kind: str,
        message: str,
        *,
        payload: dict[str, Any] | None = None,
    ) -> JobEventView:
        self._require_record(job_id)
        events = self._events.setdefault(job_id, [])
        event = JobEventView(
            event_id=f"{len(events) + 1:06d}",
            job_id=job_id,
            kind=kind,
            message=message,
            payload=dict(payload or {}),
            created_at=_utc_now(),
        )
        events.append(event)
        self._persist_event(event)
        self._notify_watchers()
        return event

    async def cancel_job(self, job_id: str) -> JobSummary:
        record = self._require_record(job_id)
        record.cancel_requested = True
        if record.status in self.TERMINAL_STATUSES:
            record.message = "后台任务已经结束"
            record.updated_at = _utc_now()
            return self.summary(job_id)
        record.status = "cancelled"
        record.message = "已取消后台任务"
        record.updated_at = _utc_now()
        self.emit_event(job_id, "cancelled", "已取消后台任务", payload={"recovery_suggestion": "需要时可重新启动同一动作。"})
        task = self._tasks.get(job_id)
        if task and not task.done():
            task.cancel()
        return self.summary(job_id)

    async def wait(self, job_id: str, *, timeout: float = 5.0) -> JobSummary:
        deadline = asyncio.get_running_loop().time() + timeout
        while True:
            summary = self.summary(job_id)
            if summary.status in self.TERMINAL_STATUSES:
                return summary
            remaining = deadline - asyncio.get_running_loop().time()
            if remaining <= 0:
                return summary
            await asyncio.sleep(min(0.02, remaining))

    async def sse_events(self, job_id: str, *, after_event_id: str = ""):
        if job_id not in self._records:
            yield self._format_sse(
                JobEventView(
                    event_id="000001",
                    job_id=job_id,
                    kind="error",
                    message="后台任务不存在或服务已重启。",
                    payload={"recovery_suggestion": "请重新触发对应动作。"},
                    created_at=_utc_now(),
                )
            )
            return
        last_event_id = after_event_id
        for event in self.events(job_id, after_event_id=last_event_id):
            last_event_id = event.event_id
            yield self._format_sse(event)

        while self.summary(job_id).status not in self.TERMINAL_STATUSES:
            async with self._condition:
                await self._condition.wait()
            for event in self.events(job_id, after_event_id=last_event_id):
                last_event_id = event.event_id
                yield self._format_sse(event)

        for event in self.events(job_id, after_event_id=last_event_id):
            yield self._format_sse(event)

    async def _run_job(self, record: JobRecord, runner: JobRunner) -> None:
        if record.cancel_requested:
            return
        record.status = "running"
        record.message = "后台任务正在运行"
        record.updated_at = _utc_now()
        self.emit_event(record.job_id, "running", "后台任务正在运行")
        context = JobContext(self, record)
        try:
            result = await runner(context)
        except asyncio.CancelledError:
            record.status = "cancelled"
            record.message = "已取消后台任务"
            record.updated_at = _utc_now()
            return
        except Exception as exc:  # noqa: BLE001 - errors are converted to safe user events.
            error_traceback = traceback.format_exc()
            record.status = "failed"
            record.message = "后台任务遇到问题"
            record.updated_at = _utc_now()
            record.result = {
                "status": "failed",
                "error": str(exc) or exc.__class__.__name__,
                "error_type": exc.__class__.__name__,
                "traceback": error_traceback,
            }
            self.emit_event(
                record.job_id,
                "error",
                "后台任务遇到问题，已保留错误栈。",
                payload={
                    "error": str(exc) or exc.__class__.__name__,
                    "error_type": exc.__class__.__name__,
                    "traceback": error_traceback,
                    "recovery_suggestion": "请检查输入参数后重试；如果问题持续，打开技术详情查看 job id。",
                },
            )
            return
        if record.cancel_requested:
            record.status = "cancelled"
            record.message = "已取消后台任务"
            record.updated_at = _utc_now()
            self.emit_event(
                record.job_id,
                "cancelled",
                "已取消后台任务",
                payload={"recovery_suggestion": "需要时可重新启动同一动作。"},
            )
            return
        record.result = dict(result or {})
        record.status = "succeeded"
        record.message = "后台任务已完成"
        record.updated_at = _utc_now()
        self.emit_event(record.job_id, "succeeded", "后台任务已完成", payload=record.result)

    async def _default_runner(self, context: JobContext) -> dict[str, Any]:
        payload = context.payload
        if payload.get("fail"):
            raise RuntimeError(str(payload.get("error") or "simulated failure"))
        messages = payload.get("fake_events") or payload.get("events") or []
        if isinstance(messages, list):
            for index, message in enumerate(messages, start=1):
                if context.should_cancel():
                    return {"cancelled_at": index}
                context.emit("progress", str(message), payload={"index": index})
                await asyncio.sleep(float(payload.get("delay_seconds") or 0))
        elif not context.should_cancel():
            context.emit("progress", f"{context.job_type} 已开始处理")
        return {"type": context.job_type, "task_id": context.task_id}

    def _require_record(self, job_id: str) -> JobRecord:
        record = self._records.get(job_id)
        if record is None:
            raise KeyError(f"unknown job_id: {job_id}")
        return record

    def _persist_event(self, event: JobEventView) -> None:
        path = self.repo_root / "runs" / "web_jobs" / event.job_id / "events.jsonl"
        path.parent.mkdir(parents=True, exist_ok=True)
        payload = _model_dump(event)
        path.open("a", encoding="utf-8").write(json.dumps(payload, ensure_ascii=False, default=str) + "\n")

    def _notify_watchers(self) -> None:
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            return
        loop.create_task(self._notify_watchers_async())

    async def _notify_watchers_async(self) -> None:
        async with self._condition:
            self._condition.notify_all()

    @staticmethod
    def _format_sse(event: JobEventView) -> str:
        data = json.dumps(_model_dump(event), ensure_ascii=False, default=str)
        return f"id: {event.event_id}\nevent: {event.kind}\ndata: {data}\n\n"

    @staticmethod
    def _event_index(event_id: str) -> int:
        try:
            return int(event_id)
        except ValueError:
            return 0

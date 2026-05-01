from __future__ import annotations

import contextlib
import io
import json
from dataclasses import dataclass, field
from typing import Any, Iterator, Mapping


@dataclass(frozen=True, slots=True)
class RunEvent:
    kind: str
    message: str
    payload: dict[str, Any] = field(default_factory=dict)
    technical_details: dict[str, Any] = field(default_factory=dict)


class MessageStream:
    """A message buffer separated from the editable input area."""

    def __init__(self, *, max_messages: int = 200) -> None:
        self.max_messages = max_messages
        self._messages: list[RunEvent] = []

    def append(self, kind: str, message: str, *, payload: Mapping[str, Any] | None = None) -> RunEvent:
        event = RunEvent(kind=kind, message=message, payload=dict(payload or {}))
        self._messages.append(event)
        if len(self._messages) > self.max_messages:
            self._messages = self._messages[-self.max_messages :]
        return event

    def extend(self, events: list[RunEvent]) -> None:
        for event in events:
            self._messages.append(event)
        if len(self._messages) > self.max_messages:
            self._messages = self._messages[-self.max_messages :]

    def messages(self) -> list[RunEvent]:
        return list(self._messages)

    def render(self, *, limit: int = 20) -> str:
        visible = self._messages[-limit:]
        return "\n".join(f"{event.kind} · {event.message}" for event in visible)


class RunEventStream:
    """Converts runner callbacks and stdout chunks into UI events."""

    def __init__(self) -> None:
        self._events: list[RunEvent] = []

    def emit(self, kind: str, message: str, *, payload: Mapping[str, Any] | None = None) -> RunEvent:
        event = RunEvent(kind=kind, message=message, payload=dict(payload or {}))
        self._events.append(event)
        return event

    def progress_callback(self, event: Mapping[str, Any]) -> None:
        stage = str(event.get("stage") or event.get("agent") or "runner").strip()
        if stage == "segmentation":
            message = "正在粗读并切分原文"
        elif stage == "close_reading":
            message = self._close_read_message(event)
        elif stage == "creative_kb":
            message = "正在构建 Creative KB"
        else:
            message = "后台任务正在运行"
        if not message:
            return
        self.emit("进度", message, payload=event)

    def events(self) -> list[RunEvent]:
        return list(self._events)

    def clear(self) -> None:
        self._events.clear()

    @contextlib.contextmanager
    def capture_stdout(self) -> Iterator[io.StringIO]:
        """Capture noisy legacy stdout/stderr so it can be summarized in the message flow."""

        stdout = io.StringIO()
        stderr = io.StringIO()
        with contextlib.redirect_stdout(stdout), contextlib.redirect_stderr(stderr):
            yield stdout
        self._ingest_captured_output(stdout.getvalue(), stderr.getvalue())

    def _ingest_captured_output(self, stdout: str, stderr: str) -> None:
        for line in stdout.splitlines():
            event = self._progress_event_from_json(line)
            if event:
                self.progress_callback(event)
        payload = {}
        if stdout.strip():
            payload["stdout"] = stdout.strip()
        if stderr.strip():
            payload["stderr"] = stderr.strip()
        if payload:
            self.emit("日志", "后台输出已收起到技术详情", payload=payload)

    @staticmethod
    def _progress_event_from_json(line: str) -> dict[str, Any] | None:
        try:
            payload = json.loads(line)
        except json.JSONDecodeError:
            return None
        if not isinstance(payload, dict):
            return None
        for key in ("prompt_timing", "creative_kb_progress"):
            value = payload.get(key)
            if isinstance(value, dict):
                return value
        if "creative_kb" in payload:
            return {"stage": "creative_kb", **dict(payload.get("creative_kb") or {})}
        return None

    @staticmethod
    def _close_read_message(event: Mapping[str, Any]) -> str:
        event_name = str(event.get("event") or "")
        completed = event.get("completed_documents")
        total = event.get("total_documents")
        progress = ""
        if completed is not None and total is not None:
            progress = f"已完成 {completed}/{total} documents"
        elif completed is not None:
            progress = f"已完成 {completed} documents"
        if event_name == "batch_start":
            doc_range = RunEventStream._doc_range(event)
            title = str(event.get("chapter_title") or "").strip()
            label = f"：{title}" if title else ""
            suffix = f" · {progress}" if progress else ""
            return f"正在精读{label}（doc {doc_range}）{suffix}"
        if event_name == "batch_done":
            batch_index = event.get("batch_index")
            doc_range = RunEventStream._doc_range(event)
            prefix = f"精读 batch {batch_index} 完成" if batch_index else "精读 batch 完成"
            suffix = f" · {progress}" if progress else ""
            return f"{prefix}（doc {doc_range}）{suffix}"
        if event_name == "cancelled":
            suffix = f" · {progress}" if progress else ""
            return f"已请求停止 close-read，将从最近 checkpoint 恢复{suffix}"
        return ""

    @staticmethod
    def _doc_range(event: Mapping[str, Any]) -> str:
        first_doc = event.get("first_doc_id")
        last_doc = event.get("last_doc_id")
        if first_doc is not None and last_doc is not None:
            return f"{first_doc}-{last_doc}" if first_doc != last_doc else str(first_doc)
        return "?"

from __future__ import annotations

import asyncio
import json
import os
import traceback
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping

from .job_manager import JobContext


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _timestamp(value: datetime | None = None) -> str:
    return (value or _utc_now()).isoformat().replace("+00:00", "Z")


def _read_json(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return {}
    return dict(payload) if isinstance(payload, Mapping) else {}


def _env_float(name: str, default: float) -> float:
    value = os.getenv(name)
    if value is None:
        return default
    try:
        return float(value.strip())
    except ValueError:
        return default


def _analyzer_job_timeout_seconds() -> float:
    return max(0.01, _env_float("NOVEL_AGENT_WEB_ANALYZER_JOB_TIMEOUT_SECONDS", 600.0))


def _analyzer_job_heartbeat_seconds() -> float:
    return max(0.01, _env_float("NOVEL_AGENT_WEB_ANALYZER_JOB_HEARTBEAT_SECONDS", 30.0))


@dataclass(slots=True)
class AnalyzerTurn:
    book_id: str
    turn_id: str
    status: str
    user_question: str
    user_message_id: str
    session_id: str = ""
    parent_turn_id: str = ""
    job_id: str = ""
    assistant_message_id: str = ""
    error_message_id: str = ""
    source_refs: list[dict[str, Any]] = field(default_factory=list)
    supplements: list[dict[str, str]] = field(default_factory=list)
    result: dict[str, Any] = field(default_factory=dict)
    error: dict[str, Any] = field(default_factory=dict)
    created_at: str = field(default_factory=_timestamp)
    updated_at: str = field(default_factory=_timestamp)

    @property
    def state_path(self) -> str:
        return f".memory/analyzer/{self.book_id}/turns/{self.turn_id}.md"

    @property
    def prompt_trace_path(self) -> str:
        return f".memory/analyzer/{self.book_id}/turns/{self.turn_id}.prompts.jsonl"

    @property
    def last_prompt_path(self) -> str:
        return f".memory/analyzer/{self.book_id}/turns/{self.turn_id}.last_prompt.json"

    def to_state_item(self) -> dict[str, Any]:
        return {
            "turn_id": self.turn_id,
            "job_id": self.job_id,
            "status": self.status,
            "session_id": self.session_id,
            "parent_turn_id": self.parent_turn_id,
            "user_message_id": self.user_message_id,
            "assistant_message_id": self.assistant_message_id,
            "error_message_id": self.error_message_id,
            "state_path": self.state_path,
            "prompt_trace_path": self.prompt_trace_path,
            "last_prompt_path": self.last_prompt_path,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
            "source_refs": list(self.source_refs),
        }

    def to_trace_payload(self) -> dict[str, Any]:
        return {
            "book_id": self.book_id,
            "turn_id": self.turn_id,
            "job_id": self.job_id,
            "status": self.status,
            "user_question": self.user_question,
            "user_message_id": self.user_message_id,
            "session_id": self.session_id,
            "parent_turn_id": self.parent_turn_id,
            "assistant_message_id": self.assistant_message_id,
            "error_message_id": self.error_message_id,
            "prompt_trace_path": self.prompt_trace_path,
            "last_prompt_path": self.last_prompt_path,
            "supplements": list(self.supplements),
            "source_refs": list(self.source_refs),
            "result": dict(self.result),
            "error": dict(self.error),
            "created_at": self.created_at,
            "updated_at": self.updated_at,
        }

    @classmethod
    def from_trace_payload(cls, payload: Mapping[str, Any]) -> "AnalyzerTurn":
        return cls(
            book_id=str(payload.get("book_id") or ""),
            turn_id=str(payload.get("turn_id") or ""),
            status=str(payload.get("status") or "queued"),
            user_question=str(payload.get("user_question") or ""),
            user_message_id=str(payload.get("user_message_id") or ""),
            session_id=str(payload.get("session_id") or ""),
            parent_turn_id=str(payload.get("parent_turn_id") or ""),
            job_id=str(payload.get("job_id") or ""),
            assistant_message_id=str(payload.get("assistant_message_id") or ""),
            error_message_id=str(payload.get("error_message_id") or ""),
            source_refs=[dict(item) for item in payload.get("source_refs") or [] if isinstance(item, Mapping)],
            supplements=[dict(item) for item in payload.get("supplements") or [] if isinstance(item, Mapping)],
            result=dict(payload.get("result") or {}) if isinstance(payload.get("result"), Mapping) else {},
            error=dict(payload.get("error") or {}) if isinstance(payload.get("error"), Mapping) else {},
            created_at=str(payload.get("created_at") or _timestamp()),
            updated_at=str(payload.get("updated_at") or _timestamp()),
        )


class AnalyzerTurnService:
    """Persists recoverable Outline Analyzer turns outside WebSessionService."""

    OPEN_STATUSES = {"queued", "running", "need_user_input", "interrupted_can_resume"}
    FAILURE_STATUSES = {"failed", "cancelled", "interrupted_can_resume"}

    def __init__(self, *, repo_root: Path) -> None:
        self.repo_root = repo_root.expanduser().resolve()
        self.root = self.repo_root / ".memory" / "analyzer"
        self._recover_interrupted_turns()

    def create_or_continue_turn(
        self,
        *,
        book_id: str,
        question: str,
        user_message_id: str,
        requested_turn_id: str = "",
        session_id: str = "",
        parent_turn_id: str = "",
    ) -> AnalyzerTurn:
        requested_turn_id = requested_turn_id.strip()
        active = self.load_turn(book_id, requested_turn_id) if requested_turn_id else self.active_turn(book_id)
        if active is not None and active.status == "need_user_input":
            active.status = "queued"
            active.updated_at = _timestamp()
            active.supplements.append(
                {
                    "user_message_id": user_message_id,
                    "content": question,
                    "created_at": active.updated_at,
                }
            )
            self._save_turn(active)
            return active
        turn = AnalyzerTurn(
            book_id=book_id,
            turn_id=uuid.uuid4().hex,
            status="queued",
            user_question=question,
            user_message_id=user_message_id,
            session_id=session_id,
            parent_turn_id=parent_turn_id,
        )
        self._save_turn(turn)
        return turn

    def bind_job(self, *, book_id: str, turn_id: str, job_id: str) -> AnalyzerTurn:
        turn = self.require_turn(book_id, turn_id)
        turn.job_id = job_id
        turn.updated_at = _timestamp()
        self._save_turn(turn)
        return turn

    def mark_running(self, *, book_id: str, turn_id: str, job_id: str) -> AnalyzerTurn:
        turn = self.require_turn(book_id, turn_id)
        turn.status = "running"
        turn.job_id = job_id
        turn.updated_at = _timestamp()
        self._save_turn(turn)
        return turn

    def mark_succeeded(
        self,
        *,
        book_id: str,
        turn_id: str,
        assistant_message_id: str,
        result: Mapping[str, Any],
    ) -> AnalyzerTurn:
        turn = self.require_turn(book_id, turn_id)
        turn.status = "succeeded"
        turn.assistant_message_id = assistant_message_id
        turn.result = dict(result)
        turn.source_refs = [dict(item) for item in result.get("sources") or [] if isinstance(item, Mapping)]
        turn.updated_at = _timestamp()
        self._save_turn(turn)
        self._append_conversation_memory(turn)
        return turn

    def mark_answer_may_be_incomplete(
        self,
        *,
        book_id: str,
        turn_id: str,
        assistant_message_id: str,
        result: Mapping[str, Any],
    ) -> AnalyzerTurn:
        turn = self.require_turn(book_id, turn_id)
        turn.status = "answer_may_be_incomplete"
        turn.assistant_message_id = assistant_message_id
        turn.result = dict(result)
        turn.source_refs = [dict(item) for item in result.get("sources") or [] if isinstance(item, Mapping)]
        turn.updated_at = _timestamp()
        self._save_turn(turn)
        self._append_conversation_memory(turn)
        return turn

    def mark_need_user_input(
        self,
        *,
        book_id: str,
        turn_id: str,
        assistant_message_id: str,
        result: Mapping[str, Any],
    ) -> AnalyzerTurn:
        turn = self.require_turn(book_id, turn_id)
        turn.status = "need_user_input"
        turn.assistant_message_id = assistant_message_id
        turn.result = dict(result)
        turn.source_refs = [dict(item) for item in result.get("sources") or [] if isinstance(item, Mapping)]
        turn.updated_at = _timestamp()
        self._save_turn(turn)
        return turn

    def mark_failed(
        self,
        *,
        book_id: str,
        turn_id: str,
        error: Mapping[str, Any],
        error_message_id: str = "",
    ) -> AnalyzerTurn:
        turn = self.require_turn(book_id, turn_id)
        turn.status = "failed"
        turn.error = dict(error)
        turn.error_message_id = error_message_id or turn.error_message_id
        turn.updated_at = _timestamp()
        self._save_turn(turn)
        return turn

    def mark_cancelled(
        self,
        *,
        book_id: str,
        turn_id: str,
        error: Mapping[str, Any],
        error_message_id: str = "",
    ) -> AnalyzerTurn:
        turn = self.require_turn(book_id, turn_id)
        turn.status = "cancelled"
        turn.error = dict(error)
        turn.error_message_id = error_message_id or turn.error_message_id
        turn.updated_at = _timestamp()
        self._save_turn(turn)
        return turn

    async def run_job(self, context: JobContext, *, session_service: Any) -> dict[str, Any]:
        payload = context.payload
        turn_id = str(payload.get("turn_id") or "")
        if not turn_id:
            raise ValueError("outline_analyzer job missing turn_id")
        turn = self.mark_running(book_id=context.task_id, turn_id=turn_id, job_id=context.job_id)
        context.emit(
            "progress",
            "小说专家正在分析剧情。",
            payload={"channel": "outline_analyzer", "turn_id": turn.turn_id},
        )
        model_task = asyncio.create_task(
            asyncio.to_thread(
                session_service.facade.analyze_outline,
                book_id=context.task_id,
                question=self.question_for_model(turn),
                conversation_history=self.conversation_history_for_model(turn, session_service=session_service),
                prompt_trace_recorder=self.prompt_trace_recorder(
                    book_id=context.task_id,
                    turn_id=turn.turn_id,
                    job_id=context.job_id,
                ),
            )
        )
        try:
            result = await self._await_analyzer_result(context=context, turn=turn, model_task=model_task)
        except asyncio.CancelledError:
            model_task.cancel()
            trace_paths = self._trace_paths_payload(context.task_id, turn.turn_id)
            error_payload = {
                "status": "cancelled",
                "error": "Analyzer job was cancelled before completion.",
                "error_type": "CancelledError",
                **trace_paths,
            }
            message = session_service.append_message(
                context.task_id,
                role="error",
                content="小说专家分析已取消。需要时可以重新发送问题。",
                payload={
                    "channel": "outline_analyzer",
                    "status": "cancelled",
                    "job_id": context.job_id,
                    "turn_id": turn.turn_id,
                    "analyzer_session_id": turn.session_id,
                    "error_type": "CancelledError",
                    **trace_paths,
                },
            )
            self.mark_cancelled(
                book_id=context.task_id,
                turn_id=turn.turn_id,
                error=error_payload,
                error_message_id=message.message_id,
            )
            raise
        except TimeoutError as exc:
            model_task.cancel()
            trace_paths = self._trace_paths_payload(context.task_id, turn.turn_id)
            error_payload = {
                "status": "failed",
                "error": str(exc) or exc.__class__.__name__,
                "error_type": "model_timeout",
                "traceback": traceback.format_exc(),
                **trace_paths,
            }
            message = session_service.append_message(
                context.task_id,
                role="error",
                content=f"小说专家分析超时：{error_payload['error']}",
                payload={
                    "channel": "outline_analyzer",
                    "status": "failed",
                    "job_id": context.job_id,
                    "turn_id": turn.turn_id,
                    "analyzer_session_id": turn.session_id,
                    "error_type": "model_timeout",
                    **trace_paths,
                },
            )
            self.mark_failed(
                book_id=context.task_id,
                turn_id=turn.turn_id,
                error=error_payload,
                error_message_id=message.message_id,
            )
            raise RuntimeError(str(exc) or "Analyzer job timed out") from exc
        except Exception as exc:
            model_task.cancel()
            trace_paths = self._trace_paths_payload(context.task_id, turn.turn_id)
            error_payload = {
                "status": "failed",
                "error": str(exc) or exc.__class__.__name__,
                "error_type": exc.__class__.__name__,
                "traceback": traceback.format_exc(),
                **trace_paths,
            }
            message = session_service.append_message(
                context.task_id,
                role="error",
                content=f"小说专家暂时无法完成分析：{error_payload['error']}",
                payload={
                    "channel": "outline_analyzer",
                    "status": "failed",
                    "job_id": context.job_id,
                    "turn_id": turn.turn_id,
                    "analyzer_session_id": turn.session_id,
                    "error_type": exc.__class__.__name__,
                    **trace_paths,
                },
            )
            self.mark_failed(
                book_id=context.task_id,
                turn_id=turn.turn_id,
                error=error_payload,
                error_message_id=message.message_id,
            )
            raise

        status = str(result.get("status") or "")
        trace_paths = self._trace_paths_payload(context.task_id, turn.turn_id)
        if status == "needs_user_preference":
            message = session_service.append_message(
                context.task_id,
                role="assistant",
                content=str(result.get("answer") or "还需要你补充偏好或授权边界后，我才能继续分析。"),
                payload={
                    "channel": "outline_analyzer",
                    "status": "need_user_input",
                    "job_id": context.job_id,
                    "turn_id": turn.turn_id,
                    "analyzer_session_id": turn.session_id,
                    "sources": result.get("sources") or [],
                    **trace_paths,
                },
            )
            self.mark_need_user_input(
                book_id=context.task_id,
                turn_id=turn.turn_id,
                assistant_message_id=message.message_id,
                result=result,
            )
            return {"status": "need_user_input", "turn_id": turn.turn_id, "assistant_message_id": message.message_id}

        if status == "answer_may_be_incomplete":
            message = session_service.append_message(
                context.task_id,
                role="assistant",
                content=(
                    str(result.get("answer") or "")
                    + "\n\n> 提示：本次回答可能因达到输出长度上限而未完成，建议你让 Analyzer 继续补齐或重新生成。"
                ),
                payload={
                    "channel": "outline_analyzer",
                    "status": "answer_may_be_incomplete",
                    "warning_code": "model_output_length",
                    "job_id": context.job_id,
                    "turn_id": turn.turn_id,
                    "analyzer_session_id": turn.session_id,
                    "sources": result.get("sources") or [],
                    "final_model_response": (result.get("trace") or {}).get("final_model_response", {}),
                    **trace_paths,
                },
            )
            self.mark_answer_may_be_incomplete(
                book_id=context.task_id,
                turn_id=turn.turn_id,
                assistant_message_id=message.message_id,
                result=result,
            )
            return {
                "status": "answer_may_be_incomplete",
                "turn_id": turn.turn_id,
                "assistant_message_id": message.message_id,
            }

        if status in {"needs_model", "failed", "blocked"}:
            message = session_service.append_message(
                context.task_id,
                role="error",
                content=str(result.get("answer") or "小说专家暂时无法完成分析。"),
                payload={
                    "channel": "outline_analyzer",
                    "status": status or "failed",
                    "job_id": context.job_id,
                    "turn_id": turn.turn_id,
                    "analyzer_session_id": turn.session_id,
                    "sources": result.get("sources") or [],
                    **trace_paths,
                },
            )
            error_payload = {"status": status or "failed", "error": str(result.get("answer") or status), "result": dict(result)}
            error_payload.update(trace_paths)
            self.mark_failed(
                book_id=context.task_id,
                turn_id=turn.turn_id,
                error=error_payload,
                error_message_id=message.message_id,
            )
            raise RuntimeError(str(result.get("answer") or status or "Analyzer failed"))

        message = session_service.append_message(
            context.task_id,
            role="assistant",
            content=str(result.get("answer") or ""),
            payload={
                "channel": "outline_analyzer",
                "status": status or "ok",
                "job_id": context.job_id,
                "turn_id": turn.turn_id,
                "analyzer_session_id": turn.session_id,
                "sources": result.get("sources") or [],
                **trace_paths,
            },
        )
        self.mark_succeeded(
            book_id=context.task_id,
            turn_id=turn.turn_id,
            assistant_message_id=message.message_id,
            result=result,
        )
        return {"status": status or "ok", "turn_id": turn.turn_id, "assistant_message_id": message.message_id}

    def prompt_trace_recorder(self, *, book_id: str, turn_id: str, job_id: str):
        last_prompt_payload: dict[str, Any] = {}

        def record(snapshot: Mapping[str, Any]) -> None:
            payload = {
                "created_at": _timestamp(),
                "book_id": book_id,
                "turn_id": turn_id,
                "job_id": job_id,
                **dict(snapshot),
            }
            if snapshot.get("event") == "model_response":
                merged = dict(last_prompt_payload)
                merged["response"] = dict(snapshot.get("response") or {})
                merged["response_event"] = {
                    "stage": snapshot.get("stage"),
                    "response": dict(snapshot.get("response") or {}),
                }
                payload = {
                    "created_at": _timestamp(),
                    "book_id": book_id,
                    "turn_id": turn_id,
                    "job_id": job_id,
                    **merged,
                }
            else:
                last_prompt_payload.clear()
                last_prompt_payload.update(payload)
            trace_path = self._prompt_trace_path(book_id, turn_id)
            trace_path.parent.mkdir(parents=True, exist_ok=True)
            trace_path.open("a", encoding="utf-8").write(json.dumps(payload, ensure_ascii=False) + "\n")
            last_path = self._last_prompt_path(book_id, turn_id)
            last_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")

        return record

    async def _await_analyzer_result(
        self,
        *,
        context: JobContext,
        turn: AnalyzerTurn,
        model_task: asyncio.Task[dict[str, Any]],
    ) -> dict[str, Any]:
        loop = asyncio.get_running_loop()
        timeout_seconds = _analyzer_job_timeout_seconds()
        heartbeat_seconds = _analyzer_job_heartbeat_seconds()
        deadline = loop.time() + timeout_seconds
        while True:
            remaining = deadline - loop.time()
            if remaining <= 0:
                raise TimeoutError(
                    f"模型请求超过 {timeout_seconds:g}s 未返回。请稍后重试，或调整 Analyzer 模型/超时配置。"
                )
            done, _pending = await asyncio.wait({model_task}, timeout=min(heartbeat_seconds, remaining))
            if model_task in done:
                return model_task.result()
            context.emit(
                "progress",
                "小说专家仍在分析剧情。",
                payload={
                    "channel": "outline_analyzer",
                    "turn_id": turn.turn_id,
                    "elapsed_seconds": round(timeout_seconds - max(0.0, deadline - loop.time()), 1),
                },
            )

    def question_for_model(self, turn: AnalyzerTurn) -> str:
        if not turn.supplements:
            return turn.user_question
        supplements = "\n".join(f"- {item.get('content', '')}" for item in turn.supplements)
        return f"{turn.user_question}\n\n用户补充：\n{supplements}"

    def conversation_history_for_model(self, turn: AnalyzerTurn, *, session_service: Any) -> list[dict[str, str]]:
        session_history_method = getattr(getattr(session_service, "analyzer_session_service", None), "conversation_history_for_model", None)
        if turn.session_id and callable(session_history_method):
            history = session_history_method(book_id=turn.book_id, session_id=turn.session_id, exclude_turn_id=turn.turn_id)
        else:
            history = []
        history_method = getattr(session_service, "_conversation_history_for_analyzer", None)
        if not history and callable(history_method):
            history = history_method(turn.book_id)
        turn_context = self._turn_context_for_model(turn)
        if turn_context:
            history.append({"role": "system", "content": turn_context})
        return history

    def sync_messages(self, *, book_id: str, session_service: Any) -> None:
        for turn in self.turns(book_id):
            self._sync_user_message(turn, session_service=session_service)
            if turn.status in {"succeeded", "answer_may_be_incomplete", "need_user_input"}:
                self._sync_result_message(turn, session_service=session_service)
                continue
            if turn.status in self.FAILURE_STATUSES:
                self._sync_error_message(turn, session_service=session_service)

    def _sync_user_message(self, turn: AnalyzerTurn, *, session_service: Any) -> None:
        if not turn.user_question or self._has_synced_message(
            turn.book_id,
            session_service=session_service,
            turn_id=turn.turn_id,
            role="user",
        ):
            return
        self._append_recovered_message(
            session_service,
            turn.book_id,
            role="user",
            content=turn.user_question,
            payload={
                "channel": "outline_analyzer",
                "job_id": turn.job_id,
                "turn_id": turn.turn_id,
                "analyzer_session_id": turn.session_id,
                "recovered_from": turn.state_path,
                "original_message_id": turn.user_message_id,
            },
            created_at=turn.created_at,
        )

    def _sync_result_message(self, turn: AnalyzerTurn, *, session_service: Any) -> None:
        if self._has_synced_message(
            turn.book_id,
            session_service=session_service,
            turn_id=turn.turn_id,
            role="assistant",
        ):
            return
        answer = str(turn.result.get("answer") or "").strip()
        if not answer:
            return
        status = "need_user_input" if turn.status == "need_user_input" else str(turn.result.get("status") or "ok")
        message = self._append_recovered_message(
            session_service,
            turn.book_id,
            role="assistant",
            content=answer,
            payload={
                "channel": "outline_analyzer",
                "status": status,
                "job_id": turn.job_id,
                "turn_id": turn.turn_id,
                "analyzer_session_id": turn.session_id,
                "sources": turn.result.get("sources") or [],
                "recovered_from": turn.state_path,
                "original_message_id": turn.assistant_message_id,
                **self._trace_paths_payload(turn.book_id, turn.turn_id),
            },
            created_at=turn.updated_at,
        )
        if not turn.assistant_message_id:
            turn.assistant_message_id = message.message_id
            turn.updated_at = _timestamp()
            self._save_turn(turn)

    def _sync_error_message(self, turn: AnalyzerTurn, *, session_service: Any) -> None:
        if self._has_synced_message(
            turn.book_id,
            session_service=session_service,
            turn_id=turn.turn_id,
            role="error",
        ):
            return
        content = "上一次小说专家分析被中断，请重新发送问题或补充上下文后再试。"
        if turn.status == "failed" and turn.error.get("error"):
            content = f"小说专家上一次分析失败：{turn.error['error']}"
        message = self._append_recovered_message(
            session_service,
            turn.book_id,
            role="error",
            content=content,
            payload={
                "channel": "outline_analyzer",
                "status": turn.status,
                "job_id": turn.job_id,
                "turn_id": turn.turn_id,
                "analyzer_session_id": turn.session_id,
                "recovered_from": turn.state_path,
                "original_message_id": turn.error_message_id,
                **self._trace_paths_payload(turn.book_id, turn.turn_id),
            },
            created_at=turn.updated_at,
        )
        if not turn.error_message_id:
            turn.error_message_id = message.message_id
            turn.updated_at = _timestamp()
            self._save_turn(turn)

    def _has_synced_message(self, book_id: str, *, session_service: Any, turn_id: str, role: str) -> bool:
        messages = getattr(session_service, "_messages", {}).get(book_id, [])
        for message in messages:
            if message.role != role:
                continue
            if message.payload.get("channel") == "outline_analyzer" and message.payload.get("turn_id") == turn_id:
                return True
        return False

    def _append_recovered_message(
        self,
        session_service: Any,
        book_id: str,
        *,
        role: str,
        content: str,
        payload: Mapping[str, Any],
        created_at: str,
    ) -> Any:
        message = session_service.append_message(book_id, role=role, content=content, payload=payload)
        message.created_at = self._parse_timestamp(created_at)
        return message

    def _parse_timestamp(self, value: str) -> datetime:
        if not value:
            return _utc_now()
        try:
            return datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError:
            return _utc_now()

    def active_turn(self, book_id: str) -> AnalyzerTurn | None:
        state = self._state(book_id)
        active_turn_id = str(state.get("active_turn_id") or "")
        if active_turn_id:
            turn = self.load_turn(book_id, active_turn_id)
            if turn is not None and turn.status in self.OPEN_STATUSES:
                return turn
        for turn in reversed(self.turns(book_id)):
            if turn.status in self.OPEN_STATUSES:
                return turn
        return None

    def turns(self, book_id: str) -> list[AnalyzerTurn]:
        state = self._state(book_id)
        turns = []
        for item in state.get("turns") or []:
            if not isinstance(item, Mapping):
                continue
            turn_id = str(item.get("turn_id") or "")
            turn = self.load_turn(book_id, turn_id)
            if turn is not None:
                turns.append(turn)
        return turns

    def load_turn(self, book_id: str, turn_id: str) -> AnalyzerTurn | None:
        if not turn_id:
            return None
        path = self._turn_path(book_id, turn_id)
        payload = self._read_turn_payload(path)
        if not payload:
            return None
        return AnalyzerTurn.from_trace_payload(payload)

    def require_turn(self, book_id: str, turn_id: str) -> AnalyzerTurn:
        turn = self.load_turn(book_id, turn_id)
        if turn is None:
            raise KeyError(f"unknown analyzer turn_id: {turn_id}")
        return turn

    def _state(self, book_id: str) -> dict[str, Any]:
        return _read_json(self._state_path(book_id))

    def _save_turn(self, turn: AnalyzerTurn) -> None:
        turn_path = self._turn_path(turn.book_id, turn.turn_id)
        turn_path.parent.mkdir(parents=True, exist_ok=True)
        turn_path.write_text(self._render_turn_markdown(turn), encoding="utf-8")
        state = self._state(turn.book_id)
        items = [dict(item) for item in state.get("turns") or [] if isinstance(item, Mapping)]
        replacement = turn.to_state_item()
        for index, item in enumerate(items):
            if str(item.get("turn_id") or "") == turn.turn_id:
                items[index] = replacement
                break
        else:
            items.append(replacement)
        active_turn_id = turn.turn_id if turn.status in self.OPEN_STATUSES else ""
        if not active_turn_id:
            active_turn_id = str(state.get("active_turn_id") or "")
            if active_turn_id == turn.turn_id:
                active_turn_id = ""
        payload = {
            "schema_version": "1.0",
            "book_id": turn.book_id,
            "active_turn_id": active_turn_id,
            "turns": items,
        }
        state_path = self._state_path(turn.book_id)
        state_path.parent.mkdir(parents=True, exist_ok=True)
        state_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")

    def _append_conversation_memory(self, turn: AnalyzerTurn) -> None:
        path = self._conversation_path(turn.book_id)
        path.parent.mkdir(parents=True, exist_ok=True)
        if not path.exists():
            path.write_text("# Analyzer Conversation Memory\n\n本文件是 Analyzer 对话记忆，不是小说事实 Memory。\n\n", encoding="utf-8")
        answer = str(turn.result.get("answer") or "")
        sources = ", ".join(str(item.get("label") or item.get("path") or "") for item in turn.source_refs if item)
        entry = (
            f"## {turn.turn_id}\n\n"
            f"- 用户问题：{turn.user_question}\n"
            f"- 最终结论：{answer}\n"
            f"- 关键来源：{sources}\n\n"
        )
        path.open("a", encoding="utf-8").write(entry)

    def _turn_context_for_model(self, turn: AnalyzerTurn) -> str:
        if not turn.result and not turn.supplements:
            return ""
        result_status = str(turn.result.get("status") or "")
        trace = turn.result.get("trace") if isinstance(turn.result.get("trace"), Mapping) else {}
        notebook = turn.result.get("notebook") if isinstance(turn.result.get("notebook"), Mapping) else {}
        pause_context = trace.get("pause_context") if isinstance(trace, Mapping) else {}
        resume_context = {
            "kind": "analyzer_resume_context",
            "turn_id": turn.turn_id,
            "previous_status": result_status,
            "previous_answer_or_prompt": str(turn.result.get("answer") or "")[:1200],
            "pause_context": dict(pause_context) if isinstance(pause_context, Mapping) else {},
            "active_notebook": {
                "confirmed_facts": list(notebook.get("confirmed_facts") or [])[-6:],
                "reasonable_inferences": list(notebook.get("reasonable_inferences") or [])[-6:],
                "uncertain_gaps": list(notebook.get("uncertain_gaps") or [])[-6:],
                "candidate_directions": list(notebook.get("candidate_directions") or [])[-4:],
                "blocked_directions": list(notebook.get("blocked_directions") or [])[-4:],
                "user_preferences": list(notebook.get("user_preferences") or [])[-4:],
            },
            "user_supplements": list(turn.supplements),
            "resume_rules": [
                "这是同一个未完成 Analyzer turn 的恢复上下文，不是正式小说 Memory。",
                "只消费 pause_context、active_notebook、committed evidence 摘要和用户补充；不要把 debug trace 或未提交猜测当成事实。",
                "用户补充应作为 user preference / authorization candidate 处理，并重新判断是否可回答或是否需要补充 evidence。",
            ],
        }
        return json.dumps({"resume_context": resume_context}, ensure_ascii=False, indent=2)

    def _render_turn_markdown(self, turn: AnalyzerTurn) -> str:
        payload = json.dumps(turn.to_trace_payload(), ensure_ascii=False, indent=2)
        sources = json.dumps(turn.source_refs, ensure_ascii=False, indent=2)
        result = json.dumps(turn.result, ensure_ascii=False, indent=2)
        error = json.dumps(turn.error, ensure_ascii=False, indent=2)
        supplements = json.dumps(turn.supplements, ensure_ascii=False, indent=2)
        return (
            "# Analyzer Turn State\n\n"
            f"- book_id: {turn.book_id}\n"
            f"- turn_id: {turn.turn_id}\n"
            f"- job_id: {turn.job_id}\n"
            f"- status: {turn.status}\n"
            f"- session_id: {turn.session_id}\n"
            f"- parent_turn_id: {turn.parent_turn_id}\n"
            f"- user_message_id: {turn.user_message_id}\n"
            f"- assistant_message_id: {turn.assistant_message_id}\n"
            f"- error_message_id: {turn.error_message_id}\n"
            f"- created_at: {turn.created_at}\n"
            f"- updated_at: {turn.updated_at}\n\n"
            "## User Question\n\n"
            f"{turn.user_question}\n\n"
            "## Supplements\n\n"
            f"```json\n{supplements}\n```\n\n"
            "## Source Refs\n\n"
            f"```json\n{sources}\n```\n\n"
            "## Result Or Active Notebook\n\n"
            f"```json\n{result}\n```\n\n"
            "## Error\n\n"
            f"```json\n{error}\n```\n\n"
            "## Prompt Trace\n\n"
            f"- prompt_trace_jsonl: {self._relative_prompt_trace_path(turn.book_id, turn.turn_id)}\n"
            f"- last_prompt_json: {self._relative_last_prompt_path(turn.book_id, turn.turn_id)}\n\n"
            f"```json\n{payload}\n```\n"
        )

    def _read_turn_payload(self, path: Path) -> dict[str, Any]:
        if not path.exists():
            return {}
        text = path.read_text(encoding="utf-8", errors="replace")
        marker = "## Prompt Trace"
        index = text.find(marker)
        if index < 0:
            return {}
        fence_start = text.find("```json", index)
        fence_end = text.find("```", fence_start + len("```json"))
        if fence_start < 0 or fence_end < 0:
            return {}
        raw = text[fence_start + len("```json") : fence_end].strip()
        try:
            payload = json.loads(raw)
        except json.JSONDecodeError:
            return {}
        return dict(payload) if isinstance(payload, Mapping) else {}

    def _recover_interrupted_turns(self) -> None:
        if not self.root.exists():
            return
        for state_path in self.root.glob("*/analyzer_state.json"):
            book_id = state_path.parent.name
            for turn in self.turns(book_id):
                if turn.status not in {"queued", "running"}:
                    continue
                turn.status = "interrupted_can_resume"
                turn.updated_at = _timestamp()
                turn.error = {
                    "status": "interrupted_can_resume",
                    "error": "Analyzer job was interrupted before completion.",
                }
                self._save_turn(turn)

    def _state_path(self, book_id: str) -> Path:
        return self.root / book_id / "analyzer_state.json"

    def _conversation_path(self, book_id: str) -> Path:
        return self.root / book_id / "conversation.md"

    def _turn_path(self, book_id: str, turn_id: str) -> Path:
        return self.root / book_id / "turns" / f"{turn_id}.md"

    def _prompt_trace_path(self, book_id: str, turn_id: str) -> Path:
        return self.root / book_id / "turns" / f"{turn_id}.prompts.jsonl"

    def _last_prompt_path(self, book_id: str, turn_id: str) -> Path:
        return self.root / book_id / "turns" / f"{turn_id}.last_prompt.json"

    def _trace_paths_payload(self, book_id: str, turn_id: str) -> dict[str, str]:
        return {
            "prompt_trace_path": self._relative_prompt_trace_path(book_id, turn_id),
            "last_prompt_path": self._relative_last_prompt_path(book_id, turn_id),
        }

    def _relative_prompt_trace_path(self, book_id: str, turn_id: str) -> str:
        return f".memory/analyzer/{book_id}/turns/{turn_id}.prompts.jsonl"

    def _relative_last_prompt_path(self, book_id: str, turn_id: str) -> str:
        return f".memory/analyzer/{book_id}/turns/{turn_id}.last_prompt.json"

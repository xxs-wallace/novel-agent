from __future__ import annotations

import json
import re
import shutil
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping

from .analyzer_turn_service import AnalyzerTurn, AnalyzerTurnService

_MAX_CONTEXT_TURNS = 4
_MAX_HISTORY_QUESTION_CHARS = 4000
_MAX_HISTORY_ANSWER_CHARS = 6000


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


@dataclass(slots=True)
class AnalyzerSession:
    book_id: str
    session_id: str
    title: str
    source_task_id: str
    turn_ids: list[str] = field(default_factory=list)
    conversation_brief: str = ""
    created_at: str = field(default_factory=_timestamp)
    updated_at: str = field(default_factory=_timestamp)

    def to_payload(self) -> dict[str, Any]:
        return {
            "book_id": self.book_id,
            "session_id": self.session_id,
            "title": self.title,
            "source_task_id": self.source_task_id,
            "turn_ids": list(self.turn_ids),
            "conversation_brief": self.conversation_brief,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
        }

    @classmethod
    def from_payload(cls, payload: Mapping[str, Any]) -> "AnalyzerSession":
        return cls(
            book_id=str(payload.get("book_id") or ""),
            session_id=str(payload.get("session_id") or ""),
            title=str(payload.get("title") or "小说讨论"),
            source_task_id=str(payload.get("source_task_id") or payload.get("book_id") or ""),
            turn_ids=[str(item) for item in payload.get("turn_ids") or [] if str(item)],
            conversation_brief=str(payload.get("conversation_brief") or ""),
            created_at=str(payload.get("created_at") or _timestamp()),
            updated_at=str(payload.get("updated_at") or _timestamp()),
        )


class AnalyzerSessionService:
    """User-facing Analyzer discussion sessions attached to a source reading task."""

    def __init__(self, *, repo_root: Path, turn_service: AnalyzerTurnService) -> None:
        self.repo_root = repo_root.expanduser().resolve()
        self.root = self.repo_root / ".memory" / "analyzer"
        self.turn_service = turn_service

    def list_sessions(self, book_id: str) -> list[dict[str, Any]]:
        self.import_legacy_turns(book_id)
        sessions = self._sessions(book_id)
        turns_by_id = {turn.turn_id: turn for turn in self.turn_service.turns(book_id)}
        return [self._summary(session, turns_by_id=turns_by_id) for session in sessions]

    def create_session(self, *, book_id: str, title: str = "", initial_question: str = "") -> AnalyzerSession:
        now = _timestamp()
        session = AnalyzerSession(
            book_id=book_id,
            session_id=f"analyzer-session-{uuid.uuid4().hex}",
            title=self._title(title or initial_question),
            source_task_id=book_id,
            created_at=now,
            updated_at=now,
        )
        self._save_session(session)
        return session

    def ensure_session_for_question(self, *, book_id: str, session_id: str, question: str) -> AnalyzerSession:
        self.import_legacy_turns(book_id)
        session = self.load_session(book_id, session_id) if session_id else None
        if session is not None:
            return session
        return self.create_session(book_id=book_id, initial_question=question)

    def load_session(self, book_id: str, session_id: str) -> AnalyzerSession | None:
        if not session_id:
            return None
        for session in self._sessions(book_id):
            if session.session_id == session_id:
                return session
        return None

    def append_turn(self, *, book_id: str, session_id: str, turn_id: str) -> AnalyzerSession:
        session = self.load_session(book_id, session_id)
        if session is None:
            raise KeyError(f"unknown analyzer session_id: {session_id}")
        if turn_id not in session.turn_ids:
            session.turn_ids.append(turn_id)
        session.updated_at = _timestamp()
        self._save_session(session)
        return session

    def messages_for_session(self, *, book_id: str, session_id: str, messages: list[Any]) -> list[Any]:
        if not session_id:
            return messages
        return [
            message
            for message in messages
            if message.payload.get("channel") == "outline_analyzer"
            and message.payload.get("analyzer_session_id") == session_id
        ]

    def rollback_latest_turn(
        self,
        *,
        book_id: str,
        session_id: str,
        confirm: bool = False,
    ) -> dict[str, Any]:
        self.import_legacy_turns(book_id)
        session = self.load_session(book_id, session_id)
        if session is None:
            raise KeyError(f"unknown analyzer session_id: {session_id}")
        if not session.turn_ids:
            raise ValueError("这个讨论还没有可撤回的分析轮次。")
        turn_id = session.turn_ids[-1]
        turn = self.turn_service.load_turn(book_id, turn_id)
        if turn is None:
            raise ValueError(f"找不到最近一轮 Analyzer 记录：{turn_id}")
        if turn.status in {"queued", "running"}:
            raise ValueError("最近一轮 Analyzer 仍在运行，请先取消或等待它结束后再撤回。")

        candidate_paths = self._rollback_candidate_paths(book_id=book_id, turn=turn)
        preview = {
            "book_id": book_id,
            "session_id": session_id,
            "confirmed": bool(confirm),
            "turn_id": turn.turn_id,
            "job_id": turn.job_id,
            "previous_turn_id": session.turn_ids[-2] if len(session.turn_ids) >= 2 else "",
            "candidate_paths": [str(path) for path in candidate_paths],
            "moved_paths": [],
            "backup_path": "",
            "errors": [],
            "message": "将撤回最近一轮小说讨论，不影响更早的讨论上下文。",
        }
        if not confirm:
            return preview

        backup_dir = self.repo_root / ".backups" / f"analyzer-rollback-{_utc_now().strftime('%Y%m%d-%H%M%S')}-{turn.turn_id[:8]}"
        backup_dir.mkdir(parents=True, exist_ok=True)
        for path in [self._sessions_path(book_id), self._state_path(book_id), self._conversation_path(book_id)]:
            if path.exists():
                shutil.copy2(path, backup_dir / path.name)

        sessions = self._sessions(book_id)
        for item in sessions:
            if item.session_id != session_id:
                continue
            if not item.turn_ids or item.turn_ids[-1] != turn.turn_id:
                raise ValueError("最近一轮讨论已发生变化，请刷新后重试。")
            item.turn_ids = item.turn_ids[:-1]
            previous_turn = self.turn_service.load_turn(book_id, item.turn_ids[-1]) if item.turn_ids else None
            item.updated_at = previous_turn.updated_at if previous_turn is not None else item.created_at
            break
        self._write_sessions(book_id, sessions)

        state_path = self._state_path(book_id)
        state = _read_json(state_path)
        state["turns"] = [item for item in state.get("turns") or [] if not (isinstance(item, Mapping) and item.get("turn_id") == turn.turn_id)]
        if state.get("active_turn_id") == turn.turn_id:
            state["active_turn_id"] = ""
        state_path.write_text(json.dumps(state, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

        self._remove_conversation_section(book_id=book_id, turn_id=turn.turn_id)

        moved_paths: list[str] = []
        errors: list[str] = []
        for path in candidate_paths:
            if not path.exists():
                continue
            destination = backup_dir / path.name
            try:
                shutil.move(str(path), str(destination))
                moved_paths.append(str(path))
            except OSError as exc:
                errors.append(f"{path}: {exc}")

        preview.update(
            {
                "backup_path": str(backup_dir),
                "moved_paths": moved_paths,
                "errors": errors,
                "message": "已撤回最近一轮小说讨论，可以补充细节后重新发送。",
            }
        )
        return preview

    def conversation_history_for_model(
        self,
        *,
        book_id: str,
        session_id: str,
        exclude_turn_id: str = "",
    ) -> list[dict[str, str]]:
        session = self.load_session(book_id, session_id)
        if session is None:
            return []
        turns = [
            turn
            for turn_id in session.turn_ids
            if turn_id != exclude_turn_id and (turn := self.turn_service.load_turn(book_id, turn_id)) is not None
        ]
        prior = turns[-_MAX_CONTEXT_TURNS:]
        lines = [
            "这是同一个 Analyzer 讨论 session 的公开对话背景，不是小说 canon memory。",
            "这里只能包含用户可见对话：用户问题、用户提出的大纲/设定草案、Analyzer 已公开回答；不得包含模型思考、检索过程或内部证据包。",
            "历史中的用户大纲/设定属于 user_proposed_outline，Analyzer 已公开回答属于 discussion_recommendations，二者可作为后续讨论的直接背景。",
            "当本轮要求“基于上面/刚才/上一轮讨论”生成、重写、修改大纲或人物设定时，应优先改进历史里的用户提案；原作 Memory / outline / raw excerpt 只用于校准适配度、事实边界和风险，不能把讨论目标替换成 committed outline。",
            f"讨论主题：{session.title}",
        ]
        if session.conversation_brief:
            lines.append(f"会话摘要：{session.conversation_brief}")
        for index, turn in enumerate(prior, start=1):
            lines.append(f"## 历史 turn {index}")
            lines.append(f"turn_id: {turn.turn_id}")
            lines.append("user_proposed_question_or_outline:")
            lines.append(self._excerpt(turn.user_question, _MAX_HISTORY_QUESTION_CHARS))
            answer = str(turn.result.get("answer") or turn.error.get("error") or "").strip()
            if answer:
                lines.append("analyzer_public_answer:")
                lines.append(self._excerpt(answer, _MAX_HISTORY_ANSWER_CHARS))
        return [{"role": "system", "content": "\n".join(lines)}]

    def import_legacy_turns(self, book_id: str) -> None:
        sessions = {session.session_id: session for session in self._sessions(book_id)}
        changed = False
        for turn in self.turn_service.turns(book_id):
            if turn.session_id:
                if turn.session_id in sessions:
                    session = sessions[turn.session_id]
                    if turn.turn_id not in session.turn_ids:
                        session.turn_ids.append(turn.turn_id)
                        session.updated_at = max(session.updated_at, turn.updated_at)
                        changed = True
                continue
            session_id = f"analyzer-session-{turn.turn_id[:12]}"
            session = sessions.get(session_id)
            if session is None:
                session = AnalyzerSession(
                    book_id=book_id,
                    session_id=session_id,
                    title=self._title(turn.user_question),
                    source_task_id=book_id,
                    turn_ids=[turn.turn_id],
                    conversation_brief=self._brief(str(turn.result.get("answer") or "")),
                    created_at=turn.created_at,
                    updated_at=turn.updated_at,
                )
                sessions[session_id] = session
                changed = True
            turn.session_id = session_id
            self.turn_service._save_turn(turn)  # noqa: SLF001 - compatibility migration of Analyzer turn metadata.
        if changed:
            self._write_sessions(book_id, sorted(sessions.values(), key=lambda item: item.updated_at, reverse=True))

    def _summary(self, session: AnalyzerSession, *, turns_by_id: dict[str, AnalyzerTurn]) -> dict[str, Any]:
        turns = [turns_by_id[turn_id] for turn_id in session.turn_ids if turn_id in turns_by_id]
        latest = turns[-1] if turns else None
        status = self._session_status(latest)
        preview = ""
        if latest is not None:
            preview = self._brief(str(latest.result.get("answer") or latest.error.get("error") or latest.user_question))
        return {
            "book_id": session.book_id,
            "session_id": session.session_id,
            "title": session.title,
            "source_task_id": session.source_task_id,
            "status": status,
            "turn_count": len(session.turn_ids),
            "latest_turn_id": latest.turn_id if latest else "",
            "latest_preview": preview,
            "conversation_brief": session.conversation_brief,
            "created_at": session.created_at,
            "updated_at": latest.updated_at if latest else session.updated_at,
        }

    def _session_status(self, latest: AnalyzerTurn | None) -> str:
        if latest is None:
            return "idle"
        if latest.status in {"queued", "running"}:
            return "running"
        if latest.status == "need_user_input":
            return "waiting_user"
        if latest.status == "answer_may_be_incomplete":
            return "answer_may_be_incomplete"
        if latest.status in {"failed", "cancelled", "interrupted_can_resume"}:
            return "failed"
        return "idle"

    def _sessions(self, book_id: str) -> list[AnalyzerSession]:
        payload = _read_json(self._sessions_path(book_id))
        return [
            AnalyzerSession.from_payload(item)
            for item in payload.get("sessions") or []
            if isinstance(item, Mapping)
        ]

    def _save_session(self, session: AnalyzerSession) -> None:
        sessions = self._sessions(session.book_id)
        for index, existing in enumerate(sessions):
            if existing.session_id == session.session_id:
                sessions[index] = session
                break
        else:
            sessions.append(session)
        self._write_sessions(session.book_id, sessions)

    def _write_sessions(self, book_id: str, sessions: list[AnalyzerSession]) -> None:
        path = self._sessions_path(book_id)
        path.parent.mkdir(parents=True, exist_ok=True)
        payload = {
            "schema_version": "1.0",
            "book_id": book_id,
            "sessions": [session.to_payload() for session in sessions],
        }
        path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")

    def _sessions_path(self, book_id: str) -> Path:
        return self.root / book_id / "sessions.json"

    def _state_path(self, book_id: str) -> Path:
        return self.root / book_id / "analyzer_state.json"

    def _conversation_path(self, book_id: str) -> Path:
        return self.root / book_id / "conversation.md"

    def _turns_path(self, book_id: str) -> Path:
        return self.root / book_id / "turns"

    def _rollback_candidate_paths(self, *, book_id: str, turn: AnalyzerTurn) -> list[Path]:
        turns_path = self._turns_path(book_id)
        paths = [
            turns_path / f"{turn.turn_id}.md",
            turns_path / f"{turn.turn_id}.prompts.jsonl",
            turns_path / f"{turn.turn_id}.last_prompt.json",
        ]
        if turn.job_id:
            paths.append(self.repo_root / "runs" / "web_jobs" / turn.job_id)
        return paths

    def _remove_conversation_section(self, *, book_id: str, turn_id: str) -> None:
        path = self._conversation_path(book_id)
        if not path.exists():
            return
        text = path.read_text(encoding="utf-8", errors="replace")
        marker = f"\n## {turn_id}\n"
        index = text.find(marker)
        if index < 0:
            return
        next_index = text.find("\n## ", index + len(marker))
        if next_index < 0:
            updated = text[:index].rstrip() + "\n"
        else:
            updated = text[:index].rstrip() + "\n" + text[next_index:]
        path.write_text(updated, encoding="utf-8")

    def _title(self, text: str) -> str:
        stripped = re.sub(r"\s+", " ", text).strip()
        if "楚子航" in stripped and "抹除" in stripped:
            return "楚子航被抹除大纲评估"
        if "诺诺" in stripped and "路明非" in stripped and "关系" in stripped:
            return "诺诺与路明非关系分析"
        if "生日" in stripped and "歌词" in stripped:
            return "生日歌事实考证"
        return stripped[:28] or "小说讨论"

    def _brief(self, text: str) -> str:
        return self._excerpt(text, 220)

    def _excerpt(self, text: str, limit: int) -> str:
        stripped = re.sub(r"\s+", " ", text).strip()
        if limit <= 0 or len(stripped) <= limit:
            return stripped
        return f"{stripped[:limit]}..."

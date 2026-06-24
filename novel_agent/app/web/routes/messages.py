from __future__ import annotations

from fastapi import APIRouter, Depends, Query

from ..deps import get_analyzer_session_service, get_analyzer_turn_service, get_job_manager, get_session_service
from ..schemas import (
    AnalyzerSessionCreateRequest,
    AnalyzerSessionSummary,
    AnalyzerTurnRollbackPreview,
    ConversationMessage,
    MessageCreateRequest,
)
from ..services.analyzer_session_service import AnalyzerSessionService
from ..services.analyzer_turn_service import AnalyzerTurnService
from ..services.job_manager import JobManager
from ..services.web_session_service import WebSessionService


router = APIRouter(prefix="/api", tags=["messages"])


@router.get("/tasks/{task_id}/messages", response_model=list[ConversationMessage])
def list_messages(
    task_id: str,
    analyzer_session_id: str = Query(default=""),
    session: WebSessionService = Depends(get_session_service),
    analyzer_sessions: AnalyzerSessionService = Depends(get_analyzer_session_service),
) -> list[ConversationMessage]:
    if analyzer_session_id:
        analyzer_sessions.import_legacy_turns(task_id)
    messages = session.messages(task_id)
    if analyzer_session_id:
        return analyzer_sessions.messages_for_session(book_id=task_id, session_id=analyzer_session_id, messages=messages)
    return messages


@router.get("/tasks/{task_id}/analyzer-sessions", response_model=list[AnalyzerSessionSummary])
def list_analyzer_sessions(
    task_id: str,
    analyzer_sessions: AnalyzerSessionService = Depends(get_analyzer_session_service),
) -> list[dict]:
    return analyzer_sessions.list_sessions(task_id)


@router.post("/tasks/{task_id}/analyzer-sessions", response_model=AnalyzerSessionSummary)
def create_analyzer_session(
    task_id: str,
    request: AnalyzerSessionCreateRequest,
    analyzer_sessions: AnalyzerSessionService = Depends(get_analyzer_session_service),
) -> dict:
    session = analyzer_sessions.create_session(
        book_id=task_id,
        title=request.title,
        initial_question=request.initial_question,
    )
    for item in analyzer_sessions.list_sessions(task_id):
        if item["session_id"] == session.session_id:
            return item
    return {}


@router.delete("/tasks/{task_id}/analyzer-sessions/{session_id}/latest-turn", response_model=AnalyzerTurnRollbackPreview)
def rollback_latest_analyzer_turn(
    task_id: str,
    session_id: str,
    confirm: bool = Query(default=False),
    session: WebSessionService = Depends(get_session_service),
    analyzer_sessions: AnalyzerSessionService = Depends(get_analyzer_session_service),
) -> dict:
    result = analyzer_sessions.rollback_latest_turn(book_id=task_id, session_id=session_id, confirm=confirm)
    if confirm:
        result["removed_message_count"] = session.remove_analyzer_turn_messages(task_id, turn_id=str(result.get("turn_id") or ""))
    return result


@router.post("/tasks/{task_id}/messages", response_model=ConversationMessage)
async def create_message(
    task_id: str,
    request: MessageCreateRequest,
    session: WebSessionService = Depends(get_session_service),
    job_manager: JobManager = Depends(get_job_manager),
    analyzer_turns: AnalyzerTurnService = Depends(get_analyzer_turn_service),
    analyzer_sessions: AnalyzerSessionService = Depends(get_analyzer_session_service),
) -> ConversationMessage:
    payload = dict(request.payload or {})
    if request.writer_question_answer is not None:
        if hasattr(request.writer_question_answer, "model_dump"):
            answer_payload = request.writer_question_answer.model_dump()
        else:
            answer_payload = request.writer_question_answer.dict()
        payload.update(answer_payload)
    analyzer_question = session._outline_analyzer_question(content=request.content, payload=payload)
    message = session.append_user_message(task_id, request.content, payload=payload)
    if not analyzer_question:
        return message

    analyzer_session = analyzer_sessions.ensure_session_for_question(
        book_id=task_id,
        session_id=str(payload.get("analyzer_session_id") or payload.get("session_id") or ""),
        question=analyzer_question,
    )
    parent_turn_id = str(payload.get("parent_turn_id") or payload.get("reply_to_turn_id") or "")
    if not parent_turn_id and analyzer_session.turn_ids:
        parent_turn_id = analyzer_session.turn_ids[-1]
    turn = analyzer_turns.create_or_continue_turn(
        book_id=task_id,
        question=analyzer_question,
        user_message_id=message.message_id,
        requested_turn_id=str(payload.get("turn_id") or ""),
        session_id=analyzer_session.session_id,
        parent_turn_id=parent_turn_id,
    )
    analyzer_sessions.append_turn(book_id=task_id, session_id=analyzer_session.session_id, turn_id=turn.turn_id)
    job = await job_manager.create_job(
        task_id=task_id,
        job_type="outline_analyzer",
        payload={"turn_id": turn.turn_id, "user_message_id": message.message_id, "analyzer_session_id": analyzer_session.session_id},
        runner=lambda context: analyzer_turns.run_job(context, session_service=session),
        deduplicate_same_type=False,
    )
    analyzer_turns.bind_job(book_id=task_id, turn_id=turn.turn_id, job_id=job.job_id)
    message.payload.update(
        {
            "channel": "outline_analyzer",
            "job_id": job.job_id,
            "turn_id": turn.turn_id,
            "analyzer_session_id": analyzer_session.session_id,
        }
    )
    session.append_message(
        task_id,
        role="job",
        content="小说专家正在分析剧情。",
        payload={
            "channel": "outline_analyzer",
            "status": "queued",
            "job_id": job.job_id,
            "turn_id": turn.turn_id,
            "analyzer_session_id": analyzer_session.session_id,
            "events_url": job.events_url,
        },
    )
    return message

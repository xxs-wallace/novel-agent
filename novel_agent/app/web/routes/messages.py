from __future__ import annotations

from fastapi import APIRouter, Depends

from ..deps import get_analyzer_turn_service, get_job_manager, get_session_service
from ..schemas import ConversationMessage, MessageCreateRequest
from ..services.analyzer_turn_service import AnalyzerTurnService
from ..services.job_manager import JobManager
from ..services.web_session_service import WebSessionService


router = APIRouter(prefix="/api", tags=["messages"])


@router.get("/tasks/{task_id}/messages", response_model=list[ConversationMessage])
def list_messages(task_id: str, session: WebSessionService = Depends(get_session_service)) -> list[ConversationMessage]:
    return session.messages(task_id)


@router.post("/tasks/{task_id}/messages", response_model=ConversationMessage)
async def create_message(
    task_id: str,
    request: MessageCreateRequest,
    session: WebSessionService = Depends(get_session_service),
    job_manager: JobManager = Depends(get_job_manager),
    analyzer_turns: AnalyzerTurnService = Depends(get_analyzer_turn_service),
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

    turn = analyzer_turns.create_or_continue_turn(
        book_id=task_id,
        question=analyzer_question,
        user_message_id=message.message_id,
        requested_turn_id=str(payload.get("turn_id") or ""),
    )
    job = await job_manager.create_job(
        task_id=task_id,
        job_type="outline_analyzer",
        payload={"turn_id": turn.turn_id, "user_message_id": message.message_id},
        runner=lambda context: analyzer_turns.run_job(context, session_service=session),
        deduplicate_same_type=False,
    )
    analyzer_turns.bind_job(book_id=task_id, turn_id=turn.turn_id, job_id=job.job_id)
    message.payload.update({"channel": "outline_analyzer", "job_id": job.job_id, "turn_id": turn.turn_id})
    session.append_message(
        task_id,
        role="job",
        content="小说专家正在分析剧情。",
        payload={
            "channel": "outline_analyzer",
            "status": "queued",
            "job_id": job.job_id,
            "turn_id": turn.turn_id,
            "events_url": job.events_url,
        },
    )
    return message

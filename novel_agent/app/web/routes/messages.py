from __future__ import annotations

from fastapi import APIRouter, Depends

from ..deps import get_session_service
from ..schemas import ConversationMessage, MessageCreateRequest
from ..services.web_session_service import WebSessionService


router = APIRouter(prefix="/api", tags=["messages"])


@router.get("/tasks/{task_id}/messages", response_model=list[ConversationMessage])
def list_messages(task_id: str, session: WebSessionService = Depends(get_session_service)) -> list[ConversationMessage]:
    return session.messages(task_id)


@router.post("/tasks/{task_id}/messages", response_model=ConversationMessage)
def create_message(
    task_id: str,
    request: MessageCreateRequest,
    session: WebSessionService = Depends(get_session_service),
) -> ConversationMessage:
    payload = dict(request.payload or {})
    if request.writer_question_answer is not None:
        if hasattr(request.writer_question_answer, "model_dump"):
            answer_payload = request.writer_question_answer.model_dump()
        else:
            answer_payload = request.writer_question_answer.dict()
        payload.update(answer_payload)
    return session.append_user_message(task_id, request.content, payload=payload)

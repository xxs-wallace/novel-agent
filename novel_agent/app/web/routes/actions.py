from __future__ import annotations

from fastapi import APIRouter, Depends

from ..deps import get_action_service, get_session_service
from ..schemas import CommandRequest, WebActionRequest, WebActionResult
from ..services.web_action_service import WebActionService
from ..services.web_session_service import WebSessionService


router = APIRouter(prefix="/api", tags=["actions"])


@router.post("/tasks/{task_id}/actions", response_model=WebActionResult)
async def run_action(
    task_id: str,
    request: WebActionRequest,
    action_service: WebActionService = Depends(get_action_service),
) -> WebActionResult:
    return await action_service.execute(task_id=task_id, request=request)


@router.post("/tasks/{task_id}/commands", response_model=WebActionResult)
def run_command(
    task_id: str,
    request: CommandRequest,
    session: WebSessionService = Depends(get_session_service),
) -> WebActionResult:
    return session.run_advanced_command(task_id=task_id, command=request.command)

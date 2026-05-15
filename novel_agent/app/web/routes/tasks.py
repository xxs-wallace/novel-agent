from __future__ import annotations

from fastapi import APIRouter, Depends, Query

from ..deps import get_job_manager, get_session_service
from ..schemas import CreateTaskRequest, JobSummary, TaskProgress, TaskSummary, WebActionResult
from ..services.job_manager import JobManager
from ..services.web_session_service import WebSessionService


router = APIRouter(prefix="/api", tags=["tasks"])


@router.get("/tasks", response_model=list[TaskSummary])
def list_tasks(
    session: WebSessionService = Depends(get_session_service),
    job_manager: JobManager = Depends(get_job_manager),
) -> list[TaskSummary]:
    return [_with_active_job_status(summary, job_manager=job_manager) for summary in session.list_tasks()]


@router.post("/tasks", response_model=TaskSummary)
def create_task(
    request: CreateTaskRequest,
    session: WebSessionService = Depends(get_session_service),
) -> TaskSummary:
    return session.create_task(task_id=request.task_id, source_path=request.source_path)


@router.get("/tasks/{task_id}", response_model=TaskSummary)
def get_task(
    task_id: str,
    session: WebSessionService = Depends(get_session_service),
    job_manager: JobManager = Depends(get_job_manager),
) -> TaskSummary:
    return _with_active_job_status(session.task_summary(session.facade.task_snapshot(book_id=task_id)), job_manager=job_manager)


@router.delete("/tasks/{task_id}")
def delete_task(
    task_id: str,
    confirm: bool = Query(False),
    include_runs: bool = Query(False),
    session: WebSessionService = Depends(get_session_service),
) -> dict[str, object]:
    return session.delete_task(task_id=task_id, confirm=confirm, include_runs=include_runs)


@router.post("/tasks/{task_id}/reset-close-read", response_model=WebActionResult)
def reset_close_read(task_id: str, session: WebSessionService = Depends(get_session_service)) -> WebActionResult:
    return session.reset_close_read(task_id=task_id)


@router.get("/tasks/{task_id}/status", response_model=TaskProgress)
def get_status(
    task_id: str,
    session: WebSessionService = Depends(get_session_service),
    job_manager: JobManager = Depends(get_job_manager),
) -> TaskProgress:
    return _progress_with_active_job_status(session.task_progress(task_id), job_manager=job_manager)


def _with_active_job_status(summary: TaskSummary, *, job_manager: JobManager) -> TaskSummary:
    active_job = _most_relevant_active_job(job_manager.active_jobs(task_id=summary.task_id))
    summary.active_job = active_job
    if summary.progress is not None:
        summary.progress = _progress_with_active_job(summary.progress, active_job=active_job)
    return summary


def _progress_with_active_job_status(progress: TaskProgress, *, job_manager: JobManager) -> TaskProgress:
    active_jobs = job_manager.active_jobs(task_id=progress.task_id)
    active_job = _most_relevant_active_job(active_jobs)
    return _progress_with_active_job(progress, active_job=active_job)


def _progress_with_active_job(progress: TaskProgress, *, active_job: JobSummary | None) -> TaskProgress:
    if active_job is None:
        return progress
    override = _ACTIVE_JOB_PROGRESS.get(active_job.type)
    if override is None:
        return progress
    progress.flow = override["flow"]
    progress.step = override["step"]
    progress.next_action = override["next_action"]
    progress.message = active_job.message
    return progress


def _most_relevant_active_job(active_jobs: list[JobSummary]) -> JobSummary | None:
    if not active_jobs:
        return None
    priority = {"writer": 4, "writer_resume": 4, "kb": 3, "close_read": 2, "read": 1}
    return sorted(active_jobs, key=lambda job: (priority.get(job.type, 0), job.created_at))[-1]


_ACTIVE_JOB_PROGRESS = {
    "read": {
        "flow": "粗读",
        "step": "正在粗读并切分原文",
        "next_action": "完成后可进入精读",
    },
    "close_read": {
        "flow": "精读",
        "step": "正在精读章节",
        "next_action": "整理人物、世界观与大纲",
    },
    "kb": {
        "flow": "Creative KB",
        "step": "正在构建 Creative KB",
        "next_action": "完成后可开始续写或查看知识库",
    },
    "writer": {
        "flow": "Writer 分层生成",
        "step": "正在生成写作产物",
        "next_action": "完成后会出现审阅决策卡",
    },
    "writer_resume": {
        "flow": "Writer 分层生成",
        "step": "正在处理你的决策",
        "next_action": "完成后会刷新审阅入口",
    },
}

from __future__ import annotations

from fastapi import APIRouter, Depends, Header, Query
from fastapi.responses import StreamingResponse

from ..deps import get_job_manager
from ..schemas import JobCreateRequest, JobEventView, JobSummary
from ..services.job_manager import JobManager


router = APIRouter(prefix="/api", tags=["jobs"])


@router.post("/tasks/{task_id}/jobs", response_model=JobSummary)
async def create_job(
    task_id: str,
    request: JobCreateRequest,
    job_manager: JobManager = Depends(get_job_manager),
) -> JobSummary:
    return await job_manager.create_job(task_id=task_id, job_type=request.type, payload=request.payload)


@router.get("/jobs/{job_id}", response_model=JobSummary)
def get_job(job_id: str, job_manager: JobManager = Depends(get_job_manager)) -> JobSummary:
    return job_manager.summary(job_id)


@router.post("/jobs/{job_id}/cancel", response_model=JobSummary)
async def cancel_job(job_id: str, job_manager: JobManager = Depends(get_job_manager)) -> JobSummary:
    return await job_manager.cancel_job(job_id)


@router.get("/jobs/{job_id}/events")
async def stream_job_events(
    job_id: str,
    after_event_id: str = Query(""),
    last_event_id: str = Header("", alias="Last-Event-ID"),
    job_manager: JobManager = Depends(get_job_manager),
) -> StreamingResponse:
    replay_after = after_event_id or last_event_id
    return StreamingResponse(
        job_manager.sse_events(job_id, after_event_id=replay_after),
        media_type="text/event-stream",
    )


@router.get("/jobs/{job_id}/events/replay", response_model=list[JobEventView])
def replay_job_events(
    job_id: str,
    after_event_id: str = Query(""),
    job_manager: JobManager = Depends(get_job_manager),
) -> list[JobEventView]:
    return job_manager.events(job_id, after_event_id=after_event_id)

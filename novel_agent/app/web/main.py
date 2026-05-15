from __future__ import annotations

from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

from .deps import default_repo_root
from .routes import actions, artifacts, jobs, messages, tasks
from .schemas import ApiError
from .services.artifact_tree_service import ArtifactTreeService
from .services.artifact_view_service import ArtifactViewService
from .services.job_manager import JobManager
from .services.web_action_service import WebActionService
from .services.web_session_service import WebSessionService


def _model_dump(model):
    if hasattr(model, "model_dump"):
        return model.model_dump()
    return model.dict()


def create_app(*, repo_root: Path | None = None, job_manager: JobManager | None = None) -> FastAPI:
    root = (repo_root or default_repo_root()).expanduser().resolve()
    app = FastAPI(title="Novel Agent Web Backend", version="0.1.0")

    session_service = WebSessionService(repo_root=root)
    artifact_tree_service = ArtifactTreeService(repo_root=root, facade=session_service.facade)
    artifact_view_service = ArtifactViewService(repo_root=root, facade=session_service.facade)
    active_job_manager = job_manager or JobManager(repo_root=root)
    action_service = WebActionService(
        session_service=session_service,
        job_manager=active_job_manager,
        artifact_view_service=artifact_view_service,
    )

    app.state.repo_root = root
    app.state.web_session_service = session_service
    app.state.artifact_tree_service = artifact_tree_service
    app.state.artifact_view_service = artifact_view_service
    app.state.job_manager = active_job_manager
    app.state.web_action_service = action_service

    app.include_router(tasks.router)
    app.include_router(messages.router)
    app.include_router(actions.router)
    app.include_router(jobs.router)
    app.include_router(artifacts.router)

    @app.exception_handler(ValueError)
    async def value_error_handler(_request: Request, exc: ValueError) -> JSONResponse:
        error = ApiError(code="bad_request", message=str(exc), recovery_suggestion="请检查请求参数后重试。")
        return JSONResponse(status_code=400, content=_model_dump(error))

    @app.exception_handler(KeyError)
    async def key_error_handler(_request: Request, exc: KeyError) -> JSONResponse:
        error = ApiError(code="not_found", message=str(exc), recovery_suggestion="请刷新列表后重试。")
        return JSONResponse(status_code=404, content=_model_dump(error))

    return app


app = create_app()


def main() -> None:
    import uvicorn

    uvicorn.run("novel_agent.app.web.main:app", host="127.0.0.1", port=8000, reload=False)


if __name__ == "__main__":
    main()

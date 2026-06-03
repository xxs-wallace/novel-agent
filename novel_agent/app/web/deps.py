from __future__ import annotations

import os
from pathlib import Path

from fastapi import Request

from .services.analyzer_turn_service import AnalyzerTurnService
from .services.artifact_tree_service import ArtifactTreeService
from .services.artifact_view_service import ArtifactViewService
from .services.job_manager import JobManager
from .services.web_action_service import WebActionService
from .services.web_session_service import WebSessionService


def default_repo_root() -> Path:
    return Path(os.environ.get("NOVEL_AGENT_REPO_ROOT") or Path.cwd()).expanduser().resolve()


def get_session_service(request: Request) -> WebSessionService:
    return request.app.state.web_session_service


def get_action_service(request: Request) -> WebActionService:
    return request.app.state.web_action_service


def get_job_manager(request: Request) -> JobManager:
    return request.app.state.job_manager


def get_analyzer_turn_service(request: Request) -> AnalyzerTurnService:
    return request.app.state.analyzer_turn_service


def get_artifact_tree_service(request: Request) -> ArtifactTreeService:
    return request.app.state.artifact_tree_service


def get_artifact_view_service(request: Request) -> ArtifactViewService:
    return request.app.state.artifact_view_service

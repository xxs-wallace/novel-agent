from __future__ import annotations

from fastapi import APIRouter, Depends, Query

from ..deps import get_artifact_tree_service, get_artifact_view_service
from ..schemas import ArtifactTreeNode, ArtifactView
from ..services.artifact_tree_service import ArtifactTreeService
from ..services.artifact_view_service import ArtifactViewService


router = APIRouter(prefix="/api", tags=["artifacts"])


@router.get("/tasks/{task_id}/artifact-tree", response_model=list[ArtifactTreeNode])
def artifact_tree(
    task_id: str,
    surface: str = Query("close-read"),
    q: str = Query(""),
    service: ArtifactTreeService = Depends(get_artifact_tree_service),
) -> list[ArtifactTreeNode]:
    return service.tree(task_id=task_id, surface=surface, query=q)


@router.get("/artifacts/{artifact_id}/view", response_model=ArtifactView)
def artifact_view(
    artifact_id: str,
    service: ArtifactViewService = Depends(get_artifact_view_service),
) -> ArtifactView:
    return service.view(artifact_id)


@router.get("/artifacts/{artifact_id}/technical")
def artifact_technical(
    artifact_id: str,
    service: ArtifactViewService = Depends(get_artifact_view_service),
) -> dict[str, object]:
    return service.technical(artifact_id)

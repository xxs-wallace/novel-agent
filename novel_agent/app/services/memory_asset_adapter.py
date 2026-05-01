from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
import sqlite3

from ..repos.assets_repo import AssetsRepo
from .outline_service import OutlineService
from .world_state_service import WorldStateService


@dataclass(slots=True)
class ResolvedMemoryAssets:
    world_summary_path: Path
    story_outline_path: Path
    missing_context: list[str] = field(default_factory=list)


class MemoryAssetAdapter:
    def __init__(
        self,
        *,
        assets_repo: AssetsRepo,
        world_state_service: WorldStateService,
        outline_service: OutlineService,
    ) -> None:
        self.assets_repo = assets_repo
        self.world_state_service = world_state_service
        self.outline_service = outline_service

    def resolve(self, conn: sqlite3.Connection, *, book_id: str) -> ResolvedMemoryAssets:
        asset_row = self.assets_repo.get(conn, book_id=book_id)
        world_summary_path, outline_path = self._fallback_paths(book_id)
        missing_context: list[str] = []

        if asset_row is None:
            missing_context.append("book_assets.missing")
            return ResolvedMemoryAssets(
                world_summary_path=world_summary_path,
                story_outline_path=outline_path,
                missing_context=missing_context,
            )

        raw_world_summary_path = str(asset_row["world_summary_path"] or "").strip()
        raw_outline_path = str(asset_row["outline_markdown_path"] or "").strip()

        if raw_world_summary_path:
            candidate = Path(raw_world_summary_path)
            if candidate.exists():
                world_summary_path = candidate
            else:
                missing_context.append("book_assets.world_summary_path_missing")
        else:
            missing_context.append("book_assets.world_summary_path_empty")

        if raw_outline_path:
            candidate = Path(raw_outline_path)
            if candidate.exists():
                outline_path = candidate
            else:
                missing_context.append("book_assets.outline_markdown_path_missing")
        else:
            missing_context.append("book_assets.outline_markdown_path_empty")

        return ResolvedMemoryAssets(
            world_summary_path=world_summary_path,
            story_outline_path=outline_path,
            missing_context=missing_context,
        )

    def _fallback_paths(self, book_id: str) -> tuple[Path, Path]:
        _, world_summary_path = self.world_state_service.ensure_paths(book_id)
        outline_path = self.outline_service.ensure_path(book_id)
        return world_summary_path, outline_path

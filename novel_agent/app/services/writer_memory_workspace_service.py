from __future__ import annotations

import shutil
import sqlite3
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

from ..repos.assets_repo import AssetsRepo
from ..repos.creative_kb_storage import init_creative_kb_schema
from ..repos.db import NovelAgentDB


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


@dataclass(slots=True)
class WriterMemoryWorkspace:
    source_db_path: Path
    writer_db_path: Path
    memory_root: Path
    created: bool = False


class WriterMemoryWorkspaceService:
    def __init__(self, *, repo_root: Path) -> None:
        self.repo_root = repo_root

    def ensure_workspace(
        self,
        *,
        book_id: str,
        source_db_path: Path,
        reset: bool = False,
    ) -> WriterMemoryWorkspace:
        writer_db_path = self.repo_root / ".indexes" / "writer" / f"{book_id}.db"
        memory_root = self.repo_root / ".memory" / "writer" / book_id
        created = reset or not writer_db_path.exists()
        if created:
            self._reset_workspace(
                book_id=book_id,
                source_db_path=source_db_path,
                writer_db_path=writer_db_path,
                memory_root=memory_root,
            )
        else:
            self._ensure_writer_schema_and_assets(book_id=book_id, writer_db_path=writer_db_path, memory_root=memory_root)
        return WriterMemoryWorkspace(
            source_db_path=source_db_path,
            writer_db_path=writer_db_path,
            memory_root=memory_root,
            created=created,
        )

    def _reset_workspace(
        self,
        *,
        book_id: str,
        source_db_path: Path,
        writer_db_path: Path,
        memory_root: Path,
    ) -> None:
        if not source_db_path.exists():
            raise FileNotFoundError(f"source memory db not found: {source_db_path}")
        writer_db_path.parent.mkdir(parents=True, exist_ok=True)
        memory_root.mkdir(parents=True, exist_ok=True)
        self._copy_sqlite_database(source_db_path=source_db_path, target_db_path=writer_db_path)
        self._copy_memory_assets(book_id=book_id, writer_db_path=writer_db_path, memory_root=memory_root)

    def _copy_sqlite_database(self, *, source_db_path: Path, target_db_path: Path) -> None:
        if target_db_path.exists():
            target_db_path.unlink()
        for suffix in ("-wal", "-shm"):
            sidecar = Path(f"{target_db_path}{suffix}")
            if sidecar.exists():
                sidecar.unlink()
        with sqlite3.connect(str(source_db_path)) as source_conn:
            with sqlite3.connect(str(target_db_path)) as target_conn:
                source_conn.backup(target_conn)

    def _ensure_writer_schema_and_assets(self, *, book_id: str, writer_db_path: Path, memory_root: Path) -> None:
        db = NovelAgentDB(writer_db_path)
        with db.connect() as conn:
            db.init_schema(conn)
            init_creative_kb_schema(conn)
            asset_row = AssetsRepo().get(conn, book_id=book_id)
            if asset_row is None:
                conn.commit()
                return
            paths = self._writer_asset_paths(memory_root=memory_root, book_id=book_id)
            if not all(path.exists() for path in paths.values()):
                self._copy_memory_assets(book_id=book_id, writer_db_path=writer_db_path, memory_root=memory_root)
                return
            self._upsert_writer_assets(conn, book_id=book_id, asset_row=asset_row, paths=paths)
            conn.commit()

    def _copy_memory_assets(self, *, book_id: str, writer_db_path: Path, memory_root: Path) -> None:
        db = NovelAgentDB(writer_db_path)
        with db.connect() as conn:
            db.init_schema(conn)
            init_creative_kb_schema(conn)
            asset_row = AssetsRepo().get(conn, book_id=book_id)
            if asset_row is None:
                conn.commit()
                return
            paths = self._writer_asset_paths(memory_root=memory_root, book_id=book_id)
            self._copy_asset_file(Path(str(asset_row["world_markdown_path"] or "")), paths["world_markdown_path"])
            self._copy_asset_file(Path(str(asset_row["world_summary_path"] or "")), paths["world_summary_path"])
            self._copy_asset_file(Path(str(asset_row["outline_markdown_path"] or "")), paths["outline_markdown_path"])
            self._upsert_writer_assets(conn, book_id=book_id, asset_row=asset_row, paths=paths)
            conn.commit()

    def _writer_asset_paths(self, *, memory_root: Path, book_id: str) -> dict[str, Path]:
        return {
            "world_markdown_path": memory_root / "worlds" / f"{book_id}.world.md",
            "world_summary_path": memory_root / "worlds" / f"{book_id}.world_summary.md",
            "outline_markdown_path": memory_root / "outlines" / f"{book_id}.outline.md",
        }

    def _copy_asset_file(self, source_path: Path, target_path: Path) -> None:
        target_path.parent.mkdir(parents=True, exist_ok=True)
        if source_path.exists():
            shutil.copy2(source_path, target_path)
            return
        if not target_path.exists():
            target_path.write_text("", encoding="utf-8")

    def _upsert_writer_assets(
        self,
        conn: sqlite3.Connection,
        *,
        book_id: str,
        asset_row: sqlite3.Row,
        paths: dict[str, Path],
    ) -> None:
        AssetsRepo().upsert(
            conn,
            {
                "book_id": book_id,
                "source_root": str(asset_row["source_root"] or self.repo_root),
                "world_markdown_path": str(paths["world_markdown_path"]),
                "world_summary_path": str(paths["world_summary_path"]),
                "outline_markdown_path": str(paths["outline_markdown_path"]),
                "toc_markdown": str(asset_row["toc_markdown"] or ""),
                "toc_source_path": str(asset_row["toc_source_path"] or ""),
                "debug_export_path": str(asset_row["debug_export_path"] or ""),
                "created_at": str(asset_row["created_at"] or _utc_now()),
                "updated_at": _utc_now(),
            },
        )

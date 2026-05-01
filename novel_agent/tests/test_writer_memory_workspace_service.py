from __future__ import annotations

from pathlib import Path

from novel_agent.app.repos.assets_repo import AssetsRepo
from novel_agent.app.repos.db import NovelAgentDB
from novel_agent.app.services.writer_memory_workspace_service import WriterMemoryWorkspaceService


def test_writer_memory_workspace_copies_db_and_markdown_assets(tmp_path: Path) -> None:
    repo_root = tmp_path / "repo"
    repo_root.mkdir()
    source_db_path = repo_root / ".indexes" / "book-1.db"
    source_db = NovelAgentDB(source_db_path)
    memory_root = repo_root / ".memory"
    world_path = memory_root / "worlds" / "book-1.world.md"
    summary_path = memory_root / "worlds" / "book-1.world_summary.md"
    outline_path = memory_root / "outlines" / "book-1.outline.md"
    world_path.parent.mkdir(parents=True)
    outline_path.parent.mkdir(parents=True)
    world_path.write_text("source world", encoding="utf-8")
    summary_path.write_text("source summary", encoding="utf-8")
    outline_path.write_text("source outline", encoding="utf-8")

    with source_db.connect() as conn:
        source_db.init_schema(conn)
        AssetsRepo().upsert(
            conn,
            {
                "book_id": "book-1",
                "source_root": str(repo_root),
                "world_markdown_path": str(world_path),
                "world_summary_path": str(summary_path),
                "outline_markdown_path": str(outline_path),
                "created_at": "now",
                "updated_at": "now",
            },
        )
        conn.execute(
            "INSERT INTO documents(book_id, content, created_at, updated_at) VALUES (?, ?, ?, ?)",
            ("book-1", "source document", "now", "now"),
        )
        conn.commit()

    workspace = WriterMemoryWorkspaceService(repo_root=repo_root).ensure_workspace(
        book_id="book-1",
        source_db_path=source_db_path,
    )

    assert workspace.writer_db_path == repo_root / ".indexes" / "writer" / "book-1.db"
    assert workspace.created is True
    writer_db = NovelAgentDB(workspace.writer_db_path)
    with writer_db.connect() as conn:
        row = AssetsRepo().get(conn, book_id="book-1")
        assert row is not None
        assert Path(str(row["world_markdown_path"])).read_text(encoding="utf-8") == "source world"
        assert Path(str(row["outline_markdown_path"])).read_text(encoding="utf-8") == "source outline"
        assert conn.execute("SELECT COUNT(*) AS count FROM documents").fetchone()["count"] == 1

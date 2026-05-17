from __future__ import annotations

from pathlib import Path

from novel_agent.app.repos.assets_repo import AssetsRepo
from novel_agent.app.repos.creative_kb_storage import init_creative_kb_schema
from novel_agent.app.repos.db import NovelAgentDB
from novel_agent.app.repos.fragment_cards_repo import FragmentCardsRepo
from novel_agent.app.repos.fragment_clusters_repo import FragmentClustersRepo
from novel_agent.app.schemas.creative_kb_schema import FragmentCard, FragmentCluster
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


def test_writer_memory_workspace_syncs_late_creative_kb(tmp_path: Path) -> None:
    repo_root = tmp_path / "repo"
    repo_root.mkdir()
    source_db_path = repo_root / ".indexes" / "book-1.db"
    source_db = NovelAgentDB(source_db_path)
    memory_root = repo_root / ".memory"
    outline_path = memory_root / "outlines" / "book-1.outline.md"
    world_path = memory_root / "worlds" / "book-1.world.md"
    summary_path = memory_root / "worlds" / "book-1.world_summary.md"
    outline_path.parent.mkdir(parents=True)
    world_path.parent.mkdir(parents=True)
    outline_path.write_text("source outline", encoding="utf-8")
    world_path.write_text("source world", encoding="utf-8")
    summary_path.write_text("source summary", encoding="utf-8")

    with source_db.connect() as conn:
        source_db.init_schema(conn)
        init_creative_kb_schema(conn)
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
        conn.commit()

    service = WriterMemoryWorkspaceService(repo_root=repo_root)
    workspace = service.ensure_workspace(book_id="book-1", source_db_path=source_db_path)
    writer_db = NovelAgentDB(workspace.writer_db_path)
    with writer_db.connect() as conn:
        assert conn.execute("SELECT COUNT(*) AS count FROM fragment_cards").fetchone()["count"] == 0

    with source_db.connect() as conn:
        source_db.init_schema(conn)
        init_creative_kb_schema(conn)
        FragmentCardsRepo().upsert_cards(
            conn,
            [
                FragmentCard(
                    fragment_id="fragment-1",
                    doc_id="1",
                    document_title="第一章",
                    document_title_index="1",
                    cluster_id="cluster-1",
                    is_cluster_representative=True,
                    content_summary="一个可复用桥段。",
                    narrative_function_text="铺垫关系张力",
                    emotion_mechanism_text="通过克制对话推进",
                    character_relation_text="双方保持边界",
                    style_profile_text="短句与内心独白交替",
                    transferability_score=0.8,
                    context_dependency_level="low",
                )
            ],
        )
        FragmentClustersRepo().upsert_clusters(
            conn,
            [
                FragmentCluster(
                    cluster_id="cluster-1",
                    cluster_theme="关系张力铺垫",
                    representative_fragment_id="fragment-1",
                    member_count=1,
                    dedup_reason="single",
                )
            ],
        )
        conn.commit()

    workspace = service.ensure_workspace(book_id="book-1", source_db_path=source_db_path)

    assert workspace.created is False
    with writer_db.connect() as conn:
        assert conn.execute("SELECT COUNT(*) AS count FROM fragment_cards").fetchone()["count"] == 1
        assert conn.execute("SELECT COUNT(*) AS count FROM fragment_clusters").fetchone()["count"] == 1
        assert conn.execute("SELECT COUNT(*) AS count FROM fragment_cards_fts").fetchone()["count"] == 1

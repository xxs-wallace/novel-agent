from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from novel_agent.app.build_source_arc_map import build_source_arc_map, main
from novel_agent.app.repos.chapters_repo import ChaptersRepo
from novel_agent.app.repos.db import NovelAgentDB


class _FakeSourceArcModel:
    def __init__(self) -> None:
        self.calls: list[tuple[str, str]] = []

    def generate_json(self, **kwargs: Any) -> tuple[dict[str, Any], str]:
        self.calls.append((str(kwargs["system_prompt"]), str(kwargs["user_prompt"])))
        return {
            "arcs": [
                {
                    "source_arc_id": "source-arc-0001",
                    "source_arc_title": "日常到调查",
                    "start_document_title_index": 1,
                    "end_document_title_index": 2,
                    "source_arc_role": "主线推进",
                    "core_events": ["日常关系后进入旧案调查。"],
                    "main_character_threads": [],
                    "world_or_rule_reveals": ["组织规则被提及。"],
                    "transition_from_previous": "当前已读范围起点",
                    "setup_for_next": "旧案继续推进",
                    "pacing_notes": "2 个 chapter 完成铺垫与推进。",
                    "chapter_role_map": [],
                }
            ]
        }, "{}"


def test_build_source_arc_map_exports_existing_close_read_outputs_with_model(tmp_path: Path) -> None:
    db_path = _seed_chapter_summaries(tmp_path, book_id="demo-task")

    result = build_source_arc_map(
        repo_root=tmp_path,
        db_path=db_path,
        book_id="demo-task",
        model_client=_FakeSourceArcModel(),  # type: ignore[arg-type]
    )

    json_path = tmp_path / ".memory" / "arcs" / "demo-task.source_arc_map.json"
    markdown_path = tmp_path / ".memory" / "arcs" / "demo-task.source_arc_map.md"
    assert result["status"] == "built"
    assert json_path.exists()
    assert markdown_path.exists()
    payload = json.loads(json_path.read_text(encoding="utf-8"))
    assert payload["book_id"] == "demo-task"
    assert payload["source_summary_count"] == 2
    assert payload["arcs"]


def test_build_source_arc_map_cli_requires_model(tmp_path: Path, capsys) -> None:
    db_path = _seed_chapter_summaries(tmp_path, book_id="demo-task")

    assert main(["demo-task", "--repo-root", str(tmp_path), "--db", str(db_path), "--format", "json"]) == 1

    output = json.loads(capsys.readouterr().out)
    assert output["status"] == "failed"
    assert output["book_id"] == "demo-task"
    assert "requires --use-model" in output["reason"]


def test_build_source_arc_map_returns_skipped_without_chapter_summaries(tmp_path: Path) -> None:
    db_path = tmp_path / ".indexes" / "empty-task.db"
    db = NovelAgentDB(db_path)
    with db.connect() as conn:
        db.init_schema(conn)
        conn.commit()

    result = build_source_arc_map(repo_root=tmp_path, db_path=db_path, book_id="empty-task")

    assert result["status"] == "skipped"
    assert result["reason"] == "no_chapter_summaries"
    assert not (tmp_path / ".memory" / "arcs").exists()


def test_build_source_arc_map_cli_errors_for_missing_db(tmp_path: Path, capsys) -> None:
    assert main(["missing-task", "--repo-root", str(tmp_path)]) == 1

    captured = capsys.readouterr()
    assert "close-read sqlite not found" in captured.err


def _seed_chapter_summaries(repo_root: Path, *, book_id: str) -> Path:
    db_path = repo_root / ".indexes" / f"{book_id}.db"
    db = NovelAgentDB(db_path)
    with db.connect() as conn:
        db.init_schema(conn)
        chapters_repo = ChaptersRepo()
        for index, summary in [
            (1, "主角在日常生活中和朋友闲聊，关系出现细微变化。"),
            (2, "调查旧案时发现新的组织规则和能力设定。"),
        ]:
            chapters_repo.upsert(
                conn,
                {
                    "book_id": book_id,
                    "document_title_index": index,
                    "chapter_title": f"第{index}章",
                    "source_doc_start_id": index,
                    "source_doc_end_id": index,
                    "source_doc_count": 1,
                    "source_total_chars": len(summary),
                    "summary_intermediate": [],
                    "summary_md": summary,
                    "summary_short": summary,
                    "importance_score": 80,
                    "importance_reason": "测试",
                    "related_chapters": [],
                    "mentioned_characters": [],
                    "world_update": {},
                    "outline_update": {},
                    "close_read_run_id": "run-close",
                    "created_at": "now",
                    "updated_at": "now",
                },
            )
        conn.commit()
    return db_path

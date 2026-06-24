from __future__ import annotations

import json
from pathlib import Path

from novel_agent.app.repos.character_profiles_repo import CharacterProfilesRepo
from novel_agent.app.repos.db import NovelAgentDB
from novel_agent.app.services.one_shot_outline_summary_service import (
    OneShotOutlineConfig,
    OneShotOutlineSummaryService,
)


class FakeTextModel:
    def __init__(self) -> None:
        self.calls: list[dict[str, str]] = []

    def generate_text(
        self,
        *,
        system_prompt: str,
        user_prompt: str,
        fallback_text: str | None = None,
        timeout_seconds: int | None = None,
        thinking: str | None = None,
        reasoning_effort: str | None = None,
        include_reasoning_content: bool | None = None,
    ) -> str:
        self.calls.append({"system": system_prompt, "user": user_prompt})
        if "完整自然语言大纲" in user_prompt:
            return "最终大纲：沈青继续追查旧案，林白提供线索，二人发现旧楼背后仍有未解阴谋。"
        return "窗口梗概：沈青在新文档中行动，林白被提及，旧案线索继续推进。"


def test_one_shot_outline_summary_extracts_and_registers_without_sqlite(tmp_path: Path) -> None:
    source_path = tmp_path / "source.txt"
    source_path.write_text("第一行\n第二行\n第三行沈青\n第四行林白\n", encoding="utf-8")
    _seed_base_memory(tmp_path, book_id="base-task")

    model = FakeTextModel()
    service = OneShotOutlineSummaryService(repo_root=tmp_path, model_client=model)
    result = service.run(
        OneShotOutlineConfig(
            task_id="new-one-shot",
            base_task_id="base-task",
            source_path=source_path,
            start_after_line=2,
            output_dir=tmp_path / ".memory" / "one_shot" / "new-one-shot",
            chunk_chars=1000,
            reference_chars=4000,
            target_min_chars=20,
            target_max_chars=200,
        )
    )

    assert result.source_excerpt_path.read_text(encoding="utf-8") == "第三行沈青\n第四行林白\n"
    assert result.outline_path.read_text(encoding="utf-8").startswith("最终大纲")
    registry = json.loads((tmp_path / ".indexes" / "tasks.json").read_text(encoding="utf-8"))
    assert registry["new-one-shot"]["source_path"] == str(result.source_excerpt_path)
    assert not (tmp_path / ".indexes" / "new-one-shot.db").exists()
    assert len(model.calls) == 2


def test_reference_packet_selects_matching_characters_read_only(tmp_path: Path) -> None:
    _seed_base_memory(tmp_path, book_id="base-task")
    service = OneShotOutlineSummaryService(repo_root=tmp_path, model_client=FakeTextModel())

    packet = service.build_reference_packet(
        base_task_id="base-task",
        new_source_text="林白把沈青交给他的线索藏好。沈青再次出现。",
        max_chars=4000,
        character_limit=4,
    )

    assert "沈青" in packet["text"]
    assert "林白" in packet["text"]
    selected = packet["metadata"]["selected_characters"]
    assert selected[0]["canonical_name"] == "沈青"
    with NovelAgentDB(tmp_path / ".indexes" / "base-task.db").connect() as conn:
        count = conn.execute("SELECT COUNT(*) AS count FROM character_profiles WHERE book_id = ?", ("base-task",)).fetchone()
    assert int(count["count"]) == 2


def _seed_base_memory(repo_root: Path, *, book_id: str) -> None:
    outline_path = repo_root / ".memory" / "outlines" / f"{book_id}.outline.md"
    world_path = repo_root / ".memory" / "worlds" / f"{book_id}.world_summary.md"
    outline_path.parent.mkdir(parents=True, exist_ok=True)
    world_path.parent.mkdir(parents=True, exist_ok=True)
    outline_path.write_text(
        "# 故事大纲\n\n### base:outline-root-0001\n沈青和林白开始调查旧案。\n",
        encoding="utf-8",
    )
    world_path.write_text("# 世界观概要\n旧案发生在雨城。\n", encoding="utf-8")
    db = NovelAgentDB(repo_root / ".indexes" / f"{book_id}.db")
    with db.connect() as conn:
        db.init_schema(conn)
        repo = CharacterProfilesRepo()
        repo.upsert(
            conn,
            {
                "book_id": book_id,
                "canonical_name": "沈青",
                "aliases": ["阿青"],
                "profile_summary_md": "# 沈青\n\n旧案调查者。",
                "recent_activity": ["继续追查旧案"],
                "relationships": [{"target_name": "林白", "summary": "协作调查"}],
                "story_events": [],
                "chapter_indexes": [1],
                "mentioned_doc_ids": [1],
                "speaking_doc_ids": [1],
                "importance_score": 8,
                "created_at": "now",
                "updated_at": "now",
            },
        )
        repo.upsert(
            conn,
            {
                "book_id": book_id,
                "canonical_name": "林白",
                "aliases": [],
                "profile_summary_md": "# 林白\n\n掌握线索的人。",
                "recent_activity": ["向沈青提供证词"],
                "relationships": [],
                "story_events": [],
                "chapter_indexes": [1],
                "mentioned_doc_ids": [1],
                "speaking_doc_ids": [],
                "importance_score": 3,
                "created_at": "now",
                "updated_at": "now",
            },
        )
        conn.commit()

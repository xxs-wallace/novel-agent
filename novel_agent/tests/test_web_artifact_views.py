from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from fastapi.testclient import TestClient

from novel_agent.app.repos.db import NovelAgentDB
from novel_agent.app.web.main import create_app


def _find_node(nodes: list[dict[str, Any]], label: str) -> dict[str, Any]:
    for node in nodes:
        if node["label"] == label:
            return node
        found = _find_node(node.get("children", []), label)
        if found:
            return found
    return {}


def _seed_close_read_db(repo_root: Path, task_id: str) -> None:
    db = NovelAgentDB(repo_root / ".indexes" / f"{task_id}.db")
    with db.connect() as conn:
        db.init_schema(conn)
        conn.execute(
            """
            INSERT INTO chapters (
                book_id, document_title_index, chapter_title, source_doc_start_id, source_doc_end_id,
                source_doc_count, source_total_chars, summary_intermediate_json, summary_md, summary_short,
                mentioned_characters_json, world_update_json, outline_update_json, created_at, updated_at
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                task_id,
                1,
                "雨夜线索",
                1,
                2,
                2,
                3200,
                "[]",
                "主角在雨夜获得关键线索，并意识到旧案仍未结束。",
                "雨夜获得线索。",
                json.dumps(["沈青状态：开始主动追查"], ensure_ascii=False),
                json.dumps({"地点": "旧码头首次出现"}, ensure_ascii=False),
                json.dumps({"伏笔": "匿名信来源未明"}, ensure_ascii=False),
                "2026-01-01T00:00:00Z",
                "2026-01-01T00:00:00Z",
            ),
        )
        conn.execute(
            """
            INSERT INTO character_profiles (
                book_id, canonical_name, aliases_json, profile_summary_md, speaking_character_status,
                personhood_evidence_summary, personality_json, occupations_json, abilities_json,
                recent_activity_json, relationships_json, importance_score, created_at, updated_at
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                task_id,
                "沈青",
                json.dumps(["阿青"], ensure_ascii=False),
                "调查旧案的核心人物，行动谨慎。",
                "speaking",
                "有稳定出场与独立行动。",
                json.dumps([{"value": "克制、谨慎", "field_type": "inference"}], ensure_ascii=False),
                json.dumps([{"value": "调查者", "field_type": "fact"}], ensure_ascii=False),
                json.dumps([{"name": "线索整合", "summary": "擅长把碎片证据连起来"}], ensure_ascii=False),
                json.dumps([{"value": "正在追查匿名信来源"}], ensure_ascii=False),
                json.dumps(
                    [
                        {
                            "target_name": "顾迟",
                            "relation_type": "有限合作",
                            "status_summary": "信任仍未完全建立",
                        }
                    ],
                    ensure_ascii=False,
                ),
                95,
                "2026-01-01T00:00:00Z",
                "2026-01-01T00:00:00Z",
            ),
        )
        conn.commit()


def test_close_read_tree_and_person_encyclopedia_view(tmp_path: Path) -> None:
    task_id = "book-one"
    _seed_close_read_db(tmp_path, task_id)
    client = TestClient(create_app(repo_root=tmp_path))
    client.post("/api/tasks", json={"task_id": task_id, "source_path": ""})

    tree = client.get(f"/api/tasks/{task_id}/artifact-tree?surface=close-read")
    assert tree.status_code == 200
    labels = [node["label"] for node in tree.json()]
    assert labels == ["总览", "章节摘要", "人物百科", "世界观", "故事大纲", "源作品篇章地图"]

    person = _find_node(tree.json(), "沈青")
    assert person
    view = client.get(f"/api/artifacts/{person['id']}/view")
    assert view.status_code == 200
    payload = view.json()
    assert payload["kind"] == "person_encyclopedia"
    section_titles = [section["title"] for section in payload["sections"]]
    assert section_titles == ["基本信息", "当前目标", "关系网络", "性格与说话方式", "已知秘密", "禁止误写点", "最近变化"]
    rendered = json.dumps(payload, ensure_ascii=False)
    assert "调查旧案" in rendered
    assert "raw_json" not in payload
    assert "{" not in "".join(section["body"] for section in payload["sections"])


def test_chapter_view_is_user_readable_not_raw_json(tmp_path: Path) -> None:
    task_id = "book-one"
    _seed_close_read_db(tmp_path, task_id)
    client = TestClient(create_app(repo_root=tmp_path))
    client.post("/api/tasks", json={"task_id": task_id, "source_path": ""})

    tree = client.get(f"/api/tasks/{task_id}/artifact-tree?surface=close-read").json()
    chapter = _find_node(tree, "1. 雨夜线索")
    view = client.get(f"/api/artifacts/{chapter['id']}/view").json()

    rendered = json.dumps(view, ensure_ascii=False)
    assert "剧情概括" in rendered
    assert "匿名信来源未明" in rendered
    assert "raw_json" not in view
    assert "mentioned_characters_json" not in rendered


def test_writer_tree_and_views_convert_artifacts_without_raw_dump(tmp_path: Path) -> None:
    task_id = "book-one"
    run_dir = tmp_path / "runs" / "writer" / "run-1"
    run_dir.mkdir(parents=True)
    (run_dir / "workflow_state.json").write_text(
        json.dumps({"data": {"run_id": "run-1", "book_id": task_id, "current_stage": "batch_review"}}, ensure_ascii=False),
        encoding="utf-8",
    )
    (run_dir / "batch_plan.json").write_text(
        json.dumps(
            {
                "data": {
                    "start_state": "主角刚获得匿名信。",
                    "stage_goal": "把旧案线索推到新地点。",
                    "main_conflict": "主角组与外部压力正面碰撞。",
                    "emotional_pacing": "前半压抑，后半加速。",
                    "expected_closure": "确认下一处调查地点。",
                }
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    (run_dir / "chapter_package.json").write_text(
        json.dumps(
            {
                "data": {
                    "chapters": [
                        {
                            "chapter_title": "雨夜接应",
                            "chapter_goal": "救出关键证人。",
                            "forbidden_items": ["不得突然告白"],
                        }
                    ]
                }
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    (run_dir / "chapter_length_plan.json").write_text(
        json.dumps({"data": {"default_target_chars": 2400, "budgets": [{"chapter_id": "ch-1", "target_chars": 2600}]}}, ensure_ascii=False),
        encoding="utf-8",
    )
    (run_dir / "chapter_execution_input.json").write_text(
        json.dumps({"data": {"chapter_title": "雨夜接应", "fact_constraints": ["证人仍在危险中"], "forbidden_items": ["不得越权"]}}, ensure_ascii=False),
        encoding="utf-8",
    )
    (run_dir / "draft.md").write_text("雨落下来，巷口的灯忽明忽暗。", encoding="utf-8")
    (run_dir / "memory_writeback.json").write_text(
        json.dumps({"data": {"character_state_changes": ["主角确认新目标"], "new_hooks": ["匿名信来源"]}}, ensure_ascii=False),
        encoding="utf-8",
    )

    client = TestClient(create_app(repo_root=tmp_path))
    client.post("/api/tasks", json={"task_id": task_id, "source_path": ""})
    tree = client.get(f"/api/tasks/{task_id}/artifact-tree?surface=writer")
    assert tree.status_code == 200
    labels = [node["label"] for node in tree.json()]
    assert labels == ["Run 总览", "全书续写规划", "本批剧情大纲", "章节标题与梗概", "章节长度计划", "本章写作材料", "正文草稿", "写回确认"]

    batch_node = _find_node(tree.json(), "本批剧情大纲")
    batch_view = client.get(f"/api/artifacts/{batch_node['id']}/view")
    assert batch_view.status_code == 200
    payload = batch_view.json()
    rendered = json.dumps(payload, ensure_ascii=False)
    assert payload["kind"] == "writer_batch_plan"
    assert "主角组与外部压力正面碰撞" in rendered
    assert "raw_json" not in payload
    assert "stage_goal" not in rendered

    technical = client.get(f"/api/artifacts/{batch_node['id']}/technical")
    assert technical.status_code == 200
    assert "raw_json" in technical.json()

from __future__ import annotations

import json
import sqlite3
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


def _flatten_labels(nodes: list[dict[str, Any]]) -> list[str]:
    labels: list[str] = []
    for node in nodes:
        labels.append(str(node["label"]))
        labels.extend(_flatten_labels(node.get("children", [])))
    return labels


FULL_TIMELINE_SUMMARY = (
    "主角在雨夜收到匿名线索后回到旧码头，先确认信件来源与失踪证人的路径有关，"
    "再根据现场残留物把旧案重新串联起来。随后同伴补充新的目击证词，使调查方向"
    "从单一嫌疑人转向更大的利益网络，主角也意识到后续行动必须同时保护证人与追踪幕后联系人。"
)


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
                json.dumps(
                    {
                        "伏笔": "匿名信来源未明",
                        "chapter_line": "[1] 雨夜线索: 主角获得线索并重新串联旧案。",
                        "event_summary": FULL_TIMELINE_SUMMARY,
                        "timeline_events": [
                            {
                                "event_id": "chapter-1:event-01-rain-clue",
                                "label": "雨夜线索推进",
                                "participants": ["沈青", "顾迟"],
                                "summary": FULL_TIMELINE_SUMMARY,
                                "source_doc_ids": [1, 2],
                                "source_doc_range": "1-2",
                            }
                        ],
                    },
                    ensure_ascii=False,
                ),
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
                json.dumps(
                    [
                        {
                            "value": "正在追查匿名信来源",
                            "field_type": "fact",
                            "source_chapter_indexes": [1],
                            "source_doc_ids": [1, 2],
                        }
                    ],
                    ensure_ascii=False,
                ),
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
                "顾迟",
                "[]",
                "与沈青有限合作的关键人物，掌握旧案旁支线索。",
                "speaking",
                "多次参与调查对话。",
                json.dumps([{"value": "谨慎、保留", "field_type": "inference"}], ensure_ascii=False),
                json.dumps([{"value": "线索提供者", "field_type": "fact"}], ensure_ascii=False),
                "[]",
                json.dumps([{"value": "正在判断是否向沈青透露更多信息"}], ensure_ascii=False),
                json.dumps([{"target_name": "沈青", "relation_type": "有限合作", "status_summary": "信任未定"}], ensure_ascii=False),
                99,
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
                "林白",
                "[]",
                "只在边缘线索中出现的人物。",
                "mentioned",
                "目前证据较少。",
                "[]",
                "[]",
                "[]",
                json.dumps([{"value": "被匿名信间接提到"}], ensure_ascii=False),
                "[]",
                10,
                "2026-01-01T00:00:00Z",
                "2026-01-01T00:00:00Z",
            ),
        )
        conn.commit()


def _seed_writer_memory_character(repo_root: Path, task_id: str, name: str) -> None:
    source_db_path = repo_root / ".indexes" / f"{task_id}.db"
    writer_db_path = repo_root / ".indexes" / "writer" / f"{task_id}.db"
    writer_db_path.parent.mkdir(parents=True, exist_ok=True)
    with sqlite3.connect(str(source_db_path)) as source_conn, sqlite3.connect(str(writer_db_path)) as writer_conn:
        source_conn.backup(writer_conn)

    db = NovelAgentDB(writer_db_path)
    with db.connect() as conn:
        db.init_schema(conn)
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
                name,
                "[]",
                "Writer 写回中新出现的人物，已经进入人物档案。",
                "speaking",
                "由已写回章节提供出场证据。",
                json.dumps([{"value": "冷静", "field_type": "inference"}], ensure_ascii=False),
                json.dumps([{"value": "联络人", "field_type": "fact"}], ensure_ascii=False),
                "[]",
                json.dumps([{"value": "在 Writer 生成章节中首次承担行动功能"}], ensure_ascii=False),
                "[]",
                45,
                "2026-01-02T00:00:00Z",
                "2026-01-02T00:00:00Z",
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
    people = _find_node(tree.json(), "人物百科")
    assert [child["label"] for child in people["children"]] == ["沈青", "顾迟", "林白"]
    assert not _find_node(tree.json(), "主角")
    assert not _find_node(tree.json(), "配角")
    assert not _find_node(tree.json(), "未归类")
    view = client.get(f"/api/artifacts/{person['id']}/view")
    assert view.status_code == 200
    payload = view.json()
    assert payload["kind"] == "person_encyclopedia"
    section_titles = [section["title"] for section in payload["sections"]]
    assert section_titles == ["基本信息", "当前目标", "关系网络", "性格与说话方式", "已知秘密", "禁止误写点", "最近变化"]
    rendered = json.dumps(payload, ensure_ascii=False)
    assert "调查旧案" in rendered
    current_goal = next(section for section in payload["sections"] if section["title"] == "当前目标")["body"]
    assert "正在追查匿名信来源（章节：1；documents：1, 2）" in current_goal
    assert "value" not in current_goal
    assert "source_doc_ids" not in current_goal
    assert "raw_json" not in payload
    assert "{" not in "".join(section["body"] for section in payload["sections"])

    searched = client.get(f"/api/tasks/{task_id}/artifact-tree?surface=close-read&q=顾迟")
    assert searched.status_code == 200
    assert _find_node(searched.json(), "顾迟")
    assert not _find_node(searched.json(), "沈青")


def test_close_read_people_include_writer_generated_characters(tmp_path: Path) -> None:
    task_id = "book-one"
    generated_name = "林澈"
    _seed_close_read_db(tmp_path, task_id)
    _seed_writer_memory_character(tmp_path, task_id, generated_name)
    client = TestClient(create_app(repo_root=tmp_path))
    client.post("/api/tasks", json={"task_id": task_id, "source_path": ""})

    tree = client.get(f"/api/tasks/{task_id}/artifact-tree?surface=close-read").json()
    assert _find_node(tree, "沈青")
    generated_person = _find_node(tree, generated_name)
    assert generated_person

    view = client.get(f"/api/artifacts/{generated_person['id']}/view")
    assert view.status_code == 200
    rendered = json.dumps(view.json(), ensure_ascii=False)
    assert "Writer 写回中新出现的人物" in rendered
    assert "在 Writer 生成章节中首次承担行动功能" in rendered


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
    actions = view["actions"]
    assert [action["label"] for action in actions] == ["分析原文"]
    assert actions[0]["payload"]["reviewer_id"] == "source_chapter_literary_diagnostic"
    assert actions[0]["payload"]["target_type"] == "source_chapter"
    assert actions[0]["payload"]["document_ids"] == ["1", "2"]
    assert actions[0]["payload"]["target_raw_chars"] == 3200
    assert "raw_json" not in view
    assert "mentioned_characters_json" not in rendered


def test_outline_view_uses_structured_timeline_events_not_stale_markdown(tmp_path: Path) -> None:
    task_id = "book-one"
    _seed_close_read_db(tmp_path, task_id)
    outline_path = tmp_path / ".memory" / "outlines" / f"{task_id}.outline.md"
    outline_path.parent.mkdir(parents=True)
    outline_path.write_text(
        "# 故事大纲\n\n## 关键时间节点\n- 雨夜线索推进 | 人物：沈青 | 旧的截断摘要...\n",
        encoding="utf-8",
    )
    client = TestClient(create_app(repo_root=tmp_path))
    client.post("/api/tasks", json={"task_id": task_id, "source_path": ""})

    tree = client.get(f"/api/tasks/{task_id}/artifact-tree?surface=close-read").json()
    outline = _find_node(tree, "故事大纲")
    view = client.get(f"/api/artifacts/{outline['id']}/view").json()

    assert view["kind"] == "outline"
    assert "## 关键时间节点" in view["markdown"]
    assert FULL_TIMELINE_SUMMARY in view["markdown"]
    assert "旧的截断摘要..." not in view["markdown"]
    assert "chapter-1:event-01-rain-clue" in view["markdown"]


def test_writer_tree_and_views_convert_artifacts_without_raw_dump(tmp_path: Path) -> None:
    task_id = "book-one"
    run_dir = tmp_path / "runs" / "writer" / "run-1"
    run_dir.mkdir(parents=True)
    (run_dir / "workflow_state.json").write_text(
        json.dumps({"data": {"run_id": "run-1", "book_id": task_id, "current_stage": "chapter_review"}}, ensure_ascii=False),
        encoding="utf-8",
    )
    (run_dir / "continuation_intent.json").write_text(
        json.dumps(
            {
                "data": {
                    "desired_actions": ["让主角根据匿名信继续追查旧案。"],
                    "raw_user_prompt": "让主角根据匿名信继续追查旧案。",
                    "story_scale": {
                        "target_chapter_count": 3,
                        "target_total_chars": 9000,
                        "default_chapter_target_chars": 3000,
                    },
                    "climax_plan": {"conflict_climax": "在旧码头发现真正的幕后联系人。"},
                }
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    (run_dir / "outline_research_question_set.json").write_text(
        json.dumps(
            {
                "data": {
                    "question_set_id": "outline-research-run-1-needs-input",
                    "questions": [{"question_id": "q1", "prompt": "下一批的主要氛围是什么？", "required": True}],
                    "actions": {"submit": "continue_after_outline_research_input"},
                }
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    (run_dir / "outline_research_answer_submission.json").write_text(
        json.dumps(
            {
                "data": {
                    "question_set_id": "outline-research-run-1-needs-input",
                    "answer_text": "下一批先写过渡日常，再引出新的晚宴邀请。",
                    "user_answers": [],
                }
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    (run_dir / "book_continuation_plan.json").write_text(
        json.dumps({"data": {"continuation_goal": "围绕匿名信展开三章追查。"}}, ensure_ascii=False),
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
    (run_dir / "sufficiency_decision.json").write_text(
        json.dumps({"data": {"status": "needs_user_input", "blocking_gaps": ["新增人物授权"], "user_questions": ["顾迟是否新增？"]}}, ensure_ascii=False),
        encoding="utf-8",
    )
    (run_dir / "outline_research_question_set.json").write_text(
        json.dumps({"data": {"status": "pending", "questions": [{"prompt": "顾迟是否新增？", "required": True}]}}, ensure_ascii=False),
        encoding="utf-8",
    )
    (run_dir / "planning_notebook.json").write_text(
        json.dumps({"data": {"summary": "围绕旧案线索规划。", "evidence": [{"evidence_level": "user_authorized", "text": "顾迟不是新增人物"}]}}, ensure_ascii=False),
        encoding="utf-8",
    )
    (run_dir / "outline_research_trace.json").write_text(
        json.dumps({"data": {"requests": [{"type": "story_detail", "query": "旧案线索"}]}}, ensure_ascii=False),
        encoding="utf-8",
    )
    (run_dir / "chapter_writing_guidance.json").write_text(
        json.dumps({"data": {"chapter_title": "雨夜接应", "length_budget": {"target_chars": 2600}, "user_supplement": {"supplement_text": "动作段更紧。"}}}, ensure_ascii=False),
        encoding="utf-8",
    )
    (run_dir / "generation_review_decision.json").write_text(
        json.dumps({"data": {"status": "rewrite_requested", "feedback_text": "节奏太慢。", "next_action": "agent_loop_rewrite_draft"}}, ensure_ascii=False),
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
    tree_payload = tree.json()
    labels = _flatten_labels(tree_payload)
    assert tree_payload[0]["label"] == "续写任务"
    assert labels == [
        "续写任务",
        "用户原始输入",
        "生成出来的大纲",
        "接下来要写的梗概",
        "草稿正文",
    ]
    assert "续写概览" not in labels
    assert "写作目标" not in labels
    assert "章节长度计划" not in labels

    intent_node = _find_node(tree.json(), "用户原始输入")
    intent_view = client.get(f"/api/artifacts/{intent_node['id']}/view").json()
    intent_rendered = json.dumps(intent_view, ensure_ascii=False)
    assert intent_view["kind"] == "writer_continuation_intent"
    assert "完整提交上下文" in intent_rendered
    assert "让主角根据匿名信继续追查旧案" in intent_rendered
    assert "顾迟是否新增" in intent_rendered
    assert "下一批先写过渡日常" in intent_rendered
    assert "目标章节数：3" in intent_rendered
    assert "desired_actions" not in intent_rendered

    plan_node = _find_node(tree.json(), "生成出来的大纲")
    plan_view = client.get(f"/api/artifacts/{plan_node['id']}/view")
    assert plan_view.status_code == 200
    payload = plan_view.json()
    rendered = json.dumps(payload, ensure_ascii=False)
    assert payload["kind"] == "writer_book_plan"
    assert "围绕匿名信展开三章追查" in rendered
    assert "raw_json" not in payload
    assert "continuation_goal" not in rendered

    technical = client.get(f"/api/artifacts/{plan_node['id']}/technical")
    assert technical.status_code == 200
    assert "raw_json" in technical.json()

    draft_node = _find_node(tree.json(), "草稿正文")
    draft_view = client.get(f"/api/artifacts/{draft_node['id']}/view").json()
    assert draft_view["markdown"] == "雨落下来，巷口的灯忽明忽暗。"


def test_writer_tree_lists_multiple_writer_runs_as_history(tmp_path: Path) -> None:
    task_id = "book-one"
    for run_id, title in (("run-1", "第一章 雨夜接应"), ("run-2", "第二章 旧码头回声")):
        run_dir = tmp_path / "runs" / "writer" / run_id
        run_dir.mkdir(parents=True)
        (run_dir / "workflow_state.json").write_text(
            json.dumps({"data": {"run_id": run_id, "book_id": task_id, "current_stage": "wait_chapter_acceptance"}}, ensure_ascii=False),
            encoding="utf-8",
        )
        (run_dir / "chapter_brief.json").write_text(
            json.dumps({"data": {"chapter_id": run_id, "title": title}}, ensure_ascii=False),
            encoding="utf-8",
        )
        (run_dir / "draft.md").write_text(f"{title}正文。", encoding="utf-8")

    client = TestClient(create_app(repo_root=tmp_path))
    client.post("/api/tasks", json={"task_id": task_id, "source_path": ""})

    tree = client.get(f"/api/tasks/{task_id}/artifact-tree?surface=writer").json()
    top_labels = [node["label"] for node in tree]

    assert set(top_labels) == {"续写任务", "续写任务 2"}
    for node in tree:
        child_labels = [child["label"] for child in node["children"]]
        assert "草稿正文" in child_labels

from __future__ import annotations

from pathlib import Path

from novel_agent.app.services.outline_service import OutlineService
from novel_agent.app.services.world_state_service import WorldStateService


def test_world_state_service_merges_into_fixed_sections_and_logs_structured_updates(tmp_path: Path) -> None:
    service = WorldStateService(
        repo_root=tmp_path,
        model_client=None,
        now_factory=lambda: "2026-05-01T00:00:00+00:00",
    )

    service.apply_update(
        book_id="demo_book",
        world_update={
            "should_update": True,
            "changes": [
                {
                    "section": "超能力体系",
                    "summary": "言灵需要血统激活才能稳定释放",
                    "evidence": "原文写到血统越高，言灵越稳定。",
                },
                {
                    "section": "阵营与势力",
                    "summary": "卡塞尔学院作为核心组织介入事件",
                    "evidence": "学院派出专员介入。",
                },
            ],
        },
    )
    service.apply_update(
        book_id="demo_book",
        world_update={
            "should_update": True,
            "changes": [
                {
                    "section": "能力体系",
                    "summary": "言灵需要血统激活才能稳定释放",
                    "evidence": "后文再次提到相同规则。",
                }
            ],
        },
    )

    world_path = tmp_path / ".memory" / "worlds" / "demo_book.world.md"
    summary_path = tmp_path / ".memory" / "worlds" / "demo_book.world_summary.md"
    world_text = world_path.read_text(encoding="utf-8")
    summary_text = summary_path.read_text(encoding="utf-8")

    for heading in (
        "## 世界类型",
        "## 时代背景",
        "## 能力体系",
        "## 超自然要素",
        "## 阵营势力",
        "## 核心禁忌与规则",
        "## 结构化更新记录",
    ):
        assert heading in world_text

    assert world_text.count("言灵需要血统激活才能稳定释放") == 3
    assert "- 卡塞尔学院作为核心组织介入事件" in world_text
    assert "处理：新增" in world_text
    assert "处理：重复" in world_text
    assert "## 能力体系" in summary_text
    assert "- 言灵需要血统激活才能稳定释放" in summary_text
    assert "## 阵营势力" in summary_text


def test_outline_service_upserts_chapter_progress_and_dedupes_timeline_events(tmp_path: Path) -> None:
    service = OutlineService(repo_root=tmp_path, outline_max_chars=2_000)

    service.apply_update(
        book_id="demo_book",
        chapter_line="[12] 入学节点: 路明非进入卡塞尔学院。",
        importance_score=70,
        timeline_events=[
            {
                "label": "卡塞尔入学",
                "participants": ["路明非", "诺诺"],
                "summary": "路明非正式收到入学引导。",
            }
        ],
    )
    service.apply_update(
        book_id="demo_book",
        chapter_line="[12] 入学节点: 路明非正式进入卡塞尔学院，并第一次明确接触龙族真相。",
        importance_score=95,
        timeline_events=[
            {
                "label": "卡塞尔入学",
                "participants": ["诺诺", "路明非"],
                "summary": "路明非正式收到入学引导，并开始理解龙族世界的真实面貌。",
            }
        ],
    )

    outline_path = tmp_path / ".memory" / "outlines" / "demo_book.outline.md"
    outline_text = outline_path.read_text(encoding="utf-8")

    assert outline_text.count("[12]") == 1
    assert "第一次明确接触龙族真相" in outline_text
    assert outline_text.count("卡塞尔入学") == 1
    assert "人物：路明非,诺诺" in outline_text


def test_outline_service_prioritizes_mainline_entries_when_compressing(tmp_path: Path) -> None:
    service = OutlineService(repo_root=tmp_path, outline_max_chars=210)

    service.apply_update(
        book_id="compressed_book",
        chapter_line="[1] 日常插曲: 众人在食堂闲聊校内琐事，并延伸出一大段轻松对话。",
        importance_score=5,
        timeline_events=[],
    )
    service.apply_update(
        book_id="compressed_book",
        chapter_line="[2] 主线推进: 路明非确认自己与龙族冲突直接相关，并接下调查真相的任务。",
        importance_score=98,
        timeline_events=[],
    )
    service.apply_update(
        book_id="compressed_book",
        chapter_line="[3] 支线冒险: 众人临时绕路处理一场与主目标关系较弱的小规模风波。",
        importance_score=10,
        timeline_events=[],
    )

    outline_path = tmp_path / ".memory" / "outlines" / "compressed_book.outline.md"
    outline_text = outline_path.read_text(encoding="utf-8")

    assert "[2] 主线推进" in outline_text
    assert "[1] 日常插曲" not in outline_text

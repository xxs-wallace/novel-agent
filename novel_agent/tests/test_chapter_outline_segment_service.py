from __future__ import annotations

from types import SimpleNamespace

from novel_agent.app.prompts.chapter_outline_segment_prompt import build_chapter_outline_segment_prompt
from novel_agent.app.prompts.close_read_prompt import build_close_read_prompt
from novel_agent.app.services.chapter_outline_segment_service import ChapterOutlineSegmentService


def test_close_read_prompt_uses_chapter_line_only_outline_update() -> None:
    system_prompt, user_prompt = build_close_read_prompt(
        {
            "book_id": "book",
            "source_total_chars": 1000,
            "summary_target_chars_min": 120,
            "documents": [],
        }
    )

    combined = system_prompt + "\n" + user_prompt
    assert '"outline_update": {"chapter_line"' in combined
    assert "timeline_events" not in combined
    assert "event_ids" not in combined


def test_chapter_outline_segment_prompt_does_not_request_event_arrays() -> None:
    system_prompt, user_prompt = build_chapter_outline_segment_prompt(
        {
            "book_id": "book",
            "document_title_index": 3,
            "chapter_title": "第三章",
            "source_doc_range": "10-11",
            "chapter_summary_short": "调查线索被重新串联。",
            "summary_md": "## 剧情事件链\n- 调查员接到新线索。\n- 同伴补充关键证词。",
        }
    )

    combined = system_prompt + "\n" + user_prompt
    assert "outline_segment" in combined
    assert "timeline_events" not in combined
    assert "event_ids" not in combined


def test_chapter_outline_segment_prompt_uses_generic_salience_and_density_budget() -> None:
    system_prompt, _user_prompt = build_chapter_outline_segment_prompt(
        {
            "book_id": "book",
            "document_title_index": 3,
            "chapter_title": "第三章",
            "source_doc_range": "10-11",
            "chapter_summary_short": "调查线索被重新串联。",
            "summary_md": "## 剧情事件链\n- 调查员接到新线索。\n- 同伴补充关键证词。",
        }
    )

    assert "高显著事件优先保留" in system_prompt
    assert "人物性格、立场、能力或身体状况" in system_prompt
    assert "人物关系发生重大变化" in system_prompt
    assert "社会或世界规则造成显著影响" in system_prompt
    assert "揭示重大悬念" in system_prompt
    assert "颠覆或改写读者对过往剧情理解" in system_prompt
    assert "320-520" in system_prompt
    assert "不要为了满足长度而删除高显著事件" in system_prompt


def test_chapter_outline_segment_service_builds_continuous_outline_segment() -> None:
    class _Model:
        settings = SimpleNamespace(dry_run=False)

        def generate_json(self, *, system_prompt, user_prompt, fallback_factory, use_fallback_on_error=False):  # type: ignore[no-untyped-def]
            _ = fallback_factory, use_fallback_on_error
            assert "Chapter Outline Segment Agent" in system_prompt
            assert "summary_md" in user_prompt
            return (
                {
                    "chapter_line": "[3] 第三章: 调查线索被重新串联。",
                    "outline_segment": "调查员接到新线索后重启前夜行动梳理，同伴证词进一步确认事件并非偶然，调查线由零散怀疑转向可验证的核心冲突。",
                    "compression_notes": "保留线索、证词和调查方向变化。",
                },
                "",
            )

    outline_update = ChapterOutlineSegmentService(model_client=_Model()).build_outline_update(
        book_id="book",
        document_title_index=3,
        chapter_title="第三章",
        summary_md="## 剧情事件链\n- 起点：调查员接到新线索。\n- 触发：同伴补充关键证词。",
        chapter_summary_short="调查线索被重新串联。",
        source_doc_range="10-11",
    )

    assert outline_update["chapter_line"].startswith("[3]")
    assert outline_update["outline_segment"].startswith("调查员接到新线索")
    assert "timeline_events" not in outline_update

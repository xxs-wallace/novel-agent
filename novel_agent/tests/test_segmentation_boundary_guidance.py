from __future__ import annotations

from novel_agent.app.prompts.segmentation_prompt import build_segmentation_prompt
from novel_agent.app.schemas.prompt_io_schema import SegmentationInputSegment
from novel_agent.app.services.document_ingest_service import DocumentIngestService


def test_segmentation_prompt_discourages_scene_level_title_indexes() -> None:
    system_prompt, user_prompt = build_segmentation_prompt(
        batch_segments=[
            SegmentationInputSegment(segment_id=1, byte_length=12, text="十五\n"),
            SegmentationInputSegment(segment_id=2, byte_length=120, text="雨停以后，他们重新回到街口。"),
        ],
        file_context="couple.txt:0-132",
        chunk_min=20000,
        chunk_max=80000,
        doc_min=4096,
        doc_max=20480,
    )

    assert "document_title_index 表示章节/卷/幕级边界" in system_prompt
    assert "不要因为场景变化就频繁新建章节" in system_prompt
    assert "极短且含数字的独立 segment 往往是章节标题" in user_prompt
    assert "未命名章节-N" in system_prompt


def test_short_numbered_segments_are_treated_as_explicit_titles() -> None:
    service = object.__new__(DocumentIngestService)

    assert service._extract_explicit_title("十五\n雨声从窗外压下来。") == "十五"  # noqa: SLF001
    assert service._extract_explicit_title("第十五章 雨夜\n雨声从窗外压下来。") == "第十五章 雨夜"  # noqa: SLF001
    assert service._extract_explicit_title("3. 回声\n他们停在走廊尽头。") == "3. 回声"  # noqa: SLF001
    assert service._extract_explicit_title("三个人走进房间") is None  # noqa: SLF001

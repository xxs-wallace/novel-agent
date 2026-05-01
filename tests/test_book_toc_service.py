from __future__ import annotations

import sqlite3
from pathlib import Path

from novel_agent.app.runner.segmentation_runner import SegmentationRunner
from novel_agent.app.schemas.config_schema import SegmentationAgentConfig
from novel_agent.app.services.book_toc_service import BookTocService


def test_extract_toc_from_markdown_text() -> None:
    text = """
# longzu

## 目录（来自 PDF 书签）

- [序章 白帝城](#序章-白帝城) (p.8)
- [第一幕 卡塞尔之门](#第一幕-卡塞尔之门) (p.12)
- [第二幕 黄金瞳](#第二幕-黄金瞳) (p.82)

# 龙族Ⅰ·火之晨曦
"""
    snapshot = BookTocService().extract_from_text(text, source_path="/tmp/longzu.md")

    assert snapshot is not None
    assert snapshot.entry_count == 3
    assert "第一幕 卡塞尔之门" in snapshot.toc_markdown


def test_segmentation_runner_supports_single_file_and_persists_toc(tmp_path: Path) -> None:
    source_file = tmp_path / "single.md"
    source_file.write_text(
        "\n".join(
            [
                "# 示例小说",
                "",
                "## 目录",
                "",
                "- [开篇](#开篇) (p.1)",
                "- [序章 白帝城](#序章-白帝城) (p.2)",
                "- [第一幕 卡塞尔之门](#第一幕-卡塞尔之门) (p.3)",
                "",
                "## 开篇",
                "",
                "这是一段开篇正文，用于验证单文件输入也能完成粗读分段。"
                "路明非在潮湿的夜里醒来，窗外的雨水顺着玻璃流淌，像是无声的倒计时。"
                "他听见楼下电视机的杂音，听见婶婶喊他去买酱油，也听见自己心里那点不合时宜的幻想。"
                "这段内容故意写长一些，避免被粗读阶段当成纯目录或封面元数据直接跳过。",
                "",
                "## 序章 白帝城",
                "",
                "康斯坦丁在火焰里醒来，城市像巨大的祭坛。黑色的城墙在火中发亮，"
                "风从空旷的街道尽头吹来，像群龙的低语。男孩沿着白帝城的台阶向上，"
                "看见王座上孤独的影子，也看见命运像铁一样沉重地压下来。",
            ]
        ),
        encoding="utf-8",
    )
    db_path = tmp_path / "single.db"
    config = SegmentationAgentConfig.from_mapping(
        {
            "book": {"book_id": "single_file_book", "source_root": str(source_file)},
            "storage": {"sqlite_path": str(db_path)},
            "read_strategy": {"max_total_chars": 2_048, "preferred_document_chars_min": 120},
            "runtime": {"dry_run": True},
        }
    )

    result = SegmentationRunner(repo_root=tmp_path, db_path=db_path, config=config).run()

    assert result.batch_count >= 1
    with sqlite3.connect(db_path) as conn:
        row = conn.execute(
            "SELECT toc_markdown, toc_source_path FROM book_assets WHERE book_id = 'single_file_book'"
        ).fetchone()
    assert row is not None
    assert "序章 白帝城" in row[0]
    assert row[1].endswith("single.md")

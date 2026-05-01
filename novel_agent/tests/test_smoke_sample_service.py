from __future__ import annotations

import json
from pathlib import Path

from novel_agent.app.services.smoke_sample_service import SmokeSampleService


def test_smoke_sample_service_loads_text_artifacts_and_resolves_relative_paths(tmp_path: Path) -> None:
    sample_dir = tmp_path / "samples"
    sample_dir.mkdir(parents=True)
    anchor_path = sample_dir / "anchor.md"
    recent_1_path = sample_dir / "recent_1.md"
    recent_2_path = sample_dir / "recent_2.md"
    truth_path = sample_dir / "truth.md"
    sample_path = sample_dir / "sample.json"

    anchor_path.write_text("上一段停在雨夜对峙。", encoding="utf-8")
    recent_1_path.write_text("最近窗口 1：人物关系仍未和解。", encoding="utf-8")
    recent_2_path.write_text("最近窗口 2：场景保持克制。", encoding="utf-8")
    truth_path.write_text("真值文本。", encoding="utf-8")
    sample_path.write_text(
        json.dumps(
            {
                "sample_id": "sample-1",
                "book_id": "book-1",
                "target_chapter_id": "chapter-3",
                "mode": "chapter_authorized",
                "anchor_context_path": "anchor.md",
                "recent_window_refs": ["recent_1.md", "recent_2.md"],
                "documents_cutoff": {"max_document_title_index": "2"},
                "allowed_outline_scope": {
                    "chapter_range": ["第3章"],
                    "allow_future_outline": False,
                },
                "reference_truth_path": "truth.md",
                "metadata": {"target_length_chars": 1200},
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )

    loaded = SmokeSampleService().load(sample_path)

    assert loaded.config.sample_id == "sample-1"
    assert loaded.config.documents_cutoff.max_title_index_int == 2
    assert loaded.anchor_context.text == "上一段停在雨夜对峙。"
    assert loaded.recent_window_summary == "最近窗口 1：人物关系仍未和解。\n\n最近窗口 2：场景保持克制。"
    assert loaded.reference_truth.text == "真值文本。"
    assert loaded.anchor_context.path == str(anchor_path.resolve())
    assert loaded.reference_truth.path == str(truth_path.resolve())
    assert len(loaded.steps) == 1


def test_smoke_sample_service_loads_continuation_steps(tmp_path: Path) -> None:
    sample_dir = tmp_path / "samples"
    sample_dir.mkdir(parents=True)
    for name, content in {
        "anchor.md": "第一段锚点",
        "recent.md": "第一段最近窗口",
        "truth.md": "第一段真值",
        "anchor_2.md": "第二段锚点",
        "recent_2.md": "第二段最近窗口",
        "truth_2.md": "第二段真值",
    }.items():
        (sample_dir / name).write_text(content, encoding="utf-8")
    sample_path = sample_dir / "sample.json"
    sample_path.write_text(
        json.dumps(
            {
                "sample_id": "sample-2",
                "book_id": "book-1",
                "target_chapter_id": "chapter-3",
                "mode": "chapter_authorized",
                "anchor_context_path": "anchor.md",
                "recent_window_refs": ["recent.md"],
                "documents_cutoff": {"max_document_title_index": "2"},
                "allowed_outline_scope": {
                    "chapter_range": ["第3章"],
                    "allow_future_outline": False,
                },
                "reference_truth_path": "truth.md",
                "continuation_steps": [
                    {
                        "step_id": "step-1",
                        "target_segment_id": "opening",
                        "anchor_context_path": "anchor.md",
                        "recent_window_refs": ["recent.md"],
                        "reference_truth_path": "truth.md",
                    },
                    {
                        "step_id": "step-2",
                        "target_segment_id": "followup",
                        "anchor_context_path": "anchor_2.md",
                        "recent_window_refs": ["recent_2.md"],
                        "reference_truth_path": "truth_2.md",
                    },
                ],
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )

    loaded = SmokeSampleService().load(sample_path)

    assert len(loaded.steps) == 2
    assert loaded.steps[0].step_id == "step-1"
    assert loaded.steps[1].step_id == "step-2"
    assert loaded.steps[1].anchor_context.text == "第二段锚点"
    assert loaded.steps[1].reference_truth.text == "第二段真值"

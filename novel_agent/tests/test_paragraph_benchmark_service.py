from __future__ import annotations

import json
from pathlib import Path

from novel_agent.app.services.paragraph_benchmark_service import (
    ParagraphBenchmarkReviewer,
    ParagraphBenchmarkService,
    ParagraphSegmenter,
)


def test_paragraph_segmenter_prefers_blank_line_segments() -> None:
    text = "第一段。\n仍在第一段。\n\n第二段。\n\n第三段。"

    segments = ParagraphSegmenter().split(text)

    assert segments == ["第一段。\n仍在第一段。", "第二段。", "第三段。"]


def test_paragraph_benchmark_service_runs_text_only_regression(tmp_path: Path) -> None:
    source_path = tmp_path / "novel.txt"
    source_path.write_text(
        "\n\n".join(
            [
                "林清把旧钥匙放在桌上，雨声从窗外压进来。",
                "沈青没有立刻接，只问她是不是还在查旧案。",
                "林清点头，说线索就在雨夜的码头，沈青决定陪她过去。",
                "两人把伞撑开，沿着湿漉漉的街道往码头走。",
            ]
        ),
        encoding="utf-8",
    )
    outline_path = tmp_path / "outline.md"
    outline_path.write_text("林清和沈青继续调查旧案，线索指向雨夜码头。", encoding="utf-8")

    result = ParagraphBenchmarkService().run(
        source_path=source_path,
        prefix_count=2,
        recent_window_size=2,
        target_length_chars=120,
        outline_path=outline_path,
        character_names=["林清", "沈青"],
        runs_dir=tmp_path / "runs",
    )

    run_dir = Path(result.run_dir)
    assert result.sample.reference_truth.startswith("林清点头")
    assert result.generated_text
    assert result.reviewer_report.decision in {"pass", "borderline", "fail"}
    assert (run_dir / "benchmark_sample.json").exists()
    assert (run_dir / "generated.txt").exists()
    assert (run_dir / "reference_truth.txt").exists()
    report = json.loads((run_dir / "reviewer_report.json").read_text(encoding="utf-8"))
    assert "recent_window_coherence" in report["metrics"]


def test_paragraph_benchmark_reviewer_passes_obvious_continuation(tmp_path: Path) -> None:
    sample = ParagraphBenchmarkService().build_sample(
        source_path=_write_source(
            tmp_path,
            [
                "林清把旧钥匙放在桌上，雨声从窗外压进来。",
                "沈青没有立刻接，只问她是不是还在查旧案。",
                "林清点头，说线索就在雨夜的码头，沈青决定陪她过去。",
            ],
        ),
        prefix_count=2,
        recent_window_size=2,
        target_length_chars=120,
        outline_text="林清和沈青继续调查旧案，线索指向雨夜码头。",
        character_names=["林清", "沈青"],
    )

    report = ParagraphBenchmarkReviewer().review(
        sample=sample,
        generated_text="林清点头，说线索就在雨夜的码头。沈青没有打断她，只把钥匙收好，决定陪她继续查旧案。",
    )

    assert report.decision == "pass"
    assert report.score >= 0.6
    assert report.metrics["character_coverage"] == 1.0


def _write_source(tmp_path: Path, segments: list[str]) -> Path:
    path = tmp_path / "source.txt"
    path.write_text("\n\n".join(segments), encoding="utf-8")
    return path

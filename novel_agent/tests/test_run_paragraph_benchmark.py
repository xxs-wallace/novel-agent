from __future__ import annotations

import json
from pathlib import Path

from novel_agent.app.run_paragraph_benchmark import main


def test_run_paragraph_benchmark_cli_prints_summary(
    tmp_path: Path,
    monkeypatch,  # type: ignore[no-untyped-def]
    capsys,  # type: ignore[no-untyped-def]
) -> None:
    source_path = tmp_path / "novel.txt"
    source_path.write_text("第一段。\n\n第二段。", encoding="utf-8")

    class _FakeResult:
        def __init__(self) -> None:
            self.run_id = "bench-run-1"
            self.run_dir = str(tmp_path / "runs" / "bench-run-1")
            self.generated_text = "生成文本"
            self.sample = type(
                "SampleHolder",
                (),
                {
                    "source_path": str(source_path),
                    "prefix_count": 1,
                    "target_segment_index": 2,
                    "recent_window_size": 1,
                    "reference_truth": "原文第二段",
                },
            )()
            self.reviewer_report = type(
                "ReviewerHolder",
                (),
                {
                    "decision": "pass",
                    "score": 0.66,
                    "summary": "达到最小回归目标",
                },
            )()

    captured: dict[str, object] = {}

    class _FakeService:
        def __init__(self, *, generation_service) -> None:  # type: ignore[no-untyped-def]
            captured["generation_service"] = generation_service

        def run(self, **kwargs):  # type: ignore[no-untyped-def]
            captured.update(kwargs)
            return _FakeResult()

    monkeypatch.setattr("novel_agent.app.run_paragraph_benchmark.ParagraphBenchmarkService", _FakeService)

    exit_code = main(
        [
            "--source",
            str(source_path),
            "--prefix-count",
            "1",
            "--recent-window-size",
            "1",
            "--target-length-chars",
            "120",
            "--repo-root",
            str(tmp_path),
        ]
    )

    assert exit_code == 0
    assert captured["source_path"] == source_path
    assert captured["prefix_count"] == 1
    assert captured["recent_window_size"] == 1
    assert captured["target_length_chars"] == 120
    assert captured["generation_config"] is None
    output = json.loads(capsys.readouterr().out)
    assert output["run_id"] == "bench-run-1"
    assert output["decision"] == "pass"
    assert output["score"] == 0.66

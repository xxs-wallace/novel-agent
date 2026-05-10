from __future__ import annotations

from typing import Any


__all__ = [
    "CreativeKBBenchmarkRunConfig",
    "CreativeKBBenchmarkRunner",
    "CreativeKBBenchmarkSummaryPresenter",
    "SingleSampleSmokeRunResult",
    "SingleSampleSmokeRunner",
]


def __getattr__(name: str) -> Any:
    if name in {
        "CreativeKBBenchmarkRunConfig",
        "CreativeKBBenchmarkRunner",
        "CreativeKBBenchmarkSummaryPresenter",
    }:
        from .creative_kb_benchmark_runner import (
            CreativeKBBenchmarkRunConfig,
            CreativeKBBenchmarkRunner,
            CreativeKBBenchmarkSummaryPresenter,
        )

        values = {
            "CreativeKBBenchmarkRunConfig": CreativeKBBenchmarkRunConfig,
            "CreativeKBBenchmarkRunner": CreativeKBBenchmarkRunner,
            "CreativeKBBenchmarkSummaryPresenter": CreativeKBBenchmarkSummaryPresenter,
        }
        return values[name]
    if name in {"SingleSampleSmokeRunResult", "SingleSampleSmokeRunner"}:
        from .single_sample_smoke_runner import SingleSampleSmokeRunResult, SingleSampleSmokeRunner

        values = {
            "SingleSampleSmokeRunResult": SingleSampleSmokeRunResult,
            "SingleSampleSmokeRunner": SingleSampleSmokeRunner,
        }
        return values[name]
    raise AttributeError(name)

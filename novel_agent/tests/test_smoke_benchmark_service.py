from __future__ import annotations

from pathlib import Path

from novel_agent.app.services.smoke_benchmark_service import SmokeBenchmarkRunService, SmokeBenchmarkSampleService
from novel_agent.app.services.smoke_sample_service import SmokeSampleService


LONGZU_FIXTURE = Path(__file__).with_name("longzu_32kb.txt")


def test_longzu_32kb_fixture_is_stable() -> None:
    assert LONGZU_FIXTURE.exists()
    raw = LONGZU_FIXTURE.read_bytes()
    assert len(raw) <= 32 * 1024
    assert raw.endswith((b"\n", b"\r\n"))
    text = raw.decode("utf-8")
    assert text.strip()


def test_longzu_sample_builder_generates_non_empty_smoke_sample(tmp_path: Path) -> None:
    result = SmokeBenchmarkSampleService(repo_root=Path.cwd()).build_longzu_32kb_sample(
        source_path=LONGZU_FIXTURE,
        output_dir=tmp_path / "longzu_32kb",
    )
    sample = SmokeSampleService(repo_root=Path.cwd()).load(result.sample_path)

    assert result.sample_path.exists()
    assert result.db_path.exists()
    assert sample.anchor_context.text
    assert sample.recent_window
    assert sample.recent_window_summary
    assert sample.reference_truth.text
    assert result.anchor_context
    assert result.recent_window
    assert result.reference_truth


def test_smoke_benchmark_run_service_rejects_without_real_model(tmp_path: Path) -> None:
    build_result = SmokeBenchmarkSampleService(repo_root=Path.cwd()).build_longzu_32kb_sample(
        source_path=LONGZU_FIXTURE,
        output_dir=tmp_path / "longzu_32kb",
    )

    try:
        SmokeBenchmarkRunService(repo_root=Path.cwd()).run_existing_sample(
            sample_path=build_result.sample_path,
            db_path=build_result.db_path,
            runs_dir=tmp_path / "runs",
        )
    except ValueError as exc:
        assert "real LLM config" in str(exc)
    else:
        raise AssertionError("smoke benchmark should reject offline runs")

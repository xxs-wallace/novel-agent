from __future__ import annotations

import os
from pathlib import Path

import pytest

from novel_agent.app.run_creative_kb_benchmark import build_parser, config_from_args, main
from novel_agent.app.runner.creative_kb_benchmark_runner import CreativeKBBenchmarkSummaryPresenter
from novel_agent.app.schemas.creative_kb_benchmark_schema import CreativeKBBenchmarkResult


def _result(
    *,
    retrieval_issues: list[str] | None = None,
    errors: list[str] | None = None,
    writer_ab: bool = True,
) -> CreativeKBBenchmarkResult:
    return CreativeKBBenchmarkResult(
        run_id="run-1",
        artifact_dir="/tmp/runs/creative_kb_benchmarks/run-1",
        status="completed" if not errors and not retrieval_issues else "failed",
        build_summary={
            "fragment_card_count": 8,
            "quality_review": {
                "decision": "pass",
                "score": 0.72,
                "summary": "建卡忠实且可检索。",
            },
        },
        retrieval_review_summary={
            "decision": "borderline" if not retrieval_issues else "fail",
            "score": 0.58 if not retrieval_issues else 0.0,
            "summary": "高上下文依赖片段偶尔进入 top2。",
            "case_reports": [
                {
                    "case_id": "case-001",
                    "decision": "fail" if retrieval_issues else "borderline",
                    "score": 0.0 if retrieval_issues else 0.58,
                    "summary": "Retrieval case failed precheck.",
                    "issues": retrieval_issues or [],
                    "checks": {},
                }
            ],
        },
        writer_ab_summary=(
            {
                "enabled": True,
                "status": "completed",
                "decision": "pass",
                "score": 0.64,
                "winner": "kb_enabled",
                "variant_scores": {"kb_enabled": 0.70, "kb_disabled": 0.52, "kb_random": 0.38},
                "negative_transfer_issues": [],
                "summary": "kb_enabled 优于 kb_disabled，但优势不稳定。",
            }
            if writer_ab
            else None
        ),
        errors=errors or [],
        summary_path="/tmp/runs/creative_kb_benchmarks/run-1/summary.json",
    )


def test_creative_kb_benchmark_cli_parser_builds_runner_config(tmp_path: Path) -> None:
    args = build_parser().parse_args(
        [
            "--source",
            str(tmp_path / "novel.txt"),
            "--repo-root",
            str(tmp_path),
            "--run-id",
            "kb-run",
            "--artifact-dir",
            str(tmp_path / "runs" / "kb-run"),
            "--case-count",
            "5",
            "--writer-ab",
            "--use-real-model",
            "--model-type",
            "OpenAIModel",
            "--model-id",
            "deepseek-chat",
            "--api-base",
            "https://api.example.com/v1",
            "--api-key",
            "secret",
            "--thinking",
            "disabled",
            "--reasoning-effort",
            "high",
        ]
    )

    config = config_from_args(args)

    assert config.source_path == tmp_path / "novel.txt"
    assert config.fixture is None
    assert config.run_id == "kb-run"
    assert config.artifact_dir == tmp_path / "runs" / "kb-run"
    assert config.case_count == 5
    assert config.enable_writer_ab is True
    assert config.use_real_model is True
    assert config.model_type == "OpenAIModel"
    assert config.model_id == "deepseek-chat"
    assert config.api_base == "https://api.example.com/v1"
    assert config.api_key == "secret"
    assert config.thinking == "disabled"
    assert config.reasoning_effort == "high"


def test_creative_kb_benchmark_cli_requires_explicit_real_or_dry_run(tmp_path: Path) -> None:
    try:
        main(["--repo-root", str(tmp_path), "--quiet-progress"])
    except SystemExit as exc:
        assert "--use-real-model is required" in str(exc)
    else:
        raise AssertionError("Creative KB benchmark CLI should require explicit model mode")


def test_creative_kb_benchmark_cli_prints_summary_with_fake_runner(
    tmp_path: Path,
    monkeypatch,  # type: ignore[no-untyped-def]
    capsys,  # type: ignore[no-untyped-def]
) -> None:
    captured: dict[str, object] = {}

    class _FakeRunner:
        def __init__(self, *, repo_root, progress_callback=None):  # type: ignore[no-untyped-def]
            captured["repo_root"] = repo_root
            captured["progress_callback"] = progress_callback

        def run(self, config):  # type: ignore[no-untyped-def]
            captured["config"] = config
            return _result()

    monkeypatch.setattr("novel_agent.app.run_creative_kb_benchmark.CreativeKBBenchmarkRunner", _FakeRunner)

    exit_code = main(
        [
            "--repo-root",
            str(tmp_path),
            "--run-id",
            "run-1",
            "--dry-run-model",
            "--quiet-progress",
        ]
    )

    assert exit_code == 0
    output = capsys.readouterr().out
    assert "Creative KB Benchmark" in output
    assert "建卡质量：pass / 0.72" in output
    assert "检索与 rerank：borderline / 0.58" in output
    assert "Writer A/B：kb_enabled" in output
    assert "artifact_dir：/tmp/runs/creative_kb_benchmarks/run-1" in output
    assert captured["repo_root"] == tmp_path


def test_creative_kb_benchmark_summary_formats_required_fields() -> None:
    text = CreativeKBBenchmarkSummaryPresenter().to_text(_result())

    assert text.splitlines()[0] == "Creative KB Benchmark"
    assert "建卡质量：pass / 0.72" in text
    assert "检索与 rerank：borderline / 0.58" in text
    assert "主要问题：高上下文依赖片段偶尔进入 top2。" in text
    assert "Writer A/B：kb_enabled；pass / 0.64" in text
    assert "artifact_dir：" in text


@pytest.mark.parametrize(
    ("issues", "expected"),
    [
        (["empty_kb"], "空 KB：Creative KB 没有可评测的 fragment_cards"),
        (["empty_selected_references"], "空 references：检索与 rerank 没有选出参考片段"),
        (["selected_reference_trace_missing"], "references 无法回源"),
    ],
)
def test_creative_kb_benchmark_summary_explains_precheck_failures(
    issues: list[str],
    expected: str,
) -> None:
    text = CreativeKBBenchmarkSummaryPresenter().to_text(_result(retrieval_issues=issues))

    assert expected in text
    assert "检索与 rerank：fail / 0.00" in text


def test_creative_kb_benchmark_summary_explains_reviewer_and_llm_failures() -> None:
    presenter = CreativeKBBenchmarkSummaryPresenter()

    reviewer_text = presenter.to_text(_result(retrieval_issues=["reviewer_failed"]))
    llm_text = presenter.to_text(_result(errors=["LLM request failed after attempt 3/3: timeout"]))

    assert "Reviewer 失败" in reviewer_text
    assert "真实 LLM 调用失败" in llm_text


def test_creative_kb_benchmark_exception_summary_explains_artifact_write_failure(tmp_path: Path) -> None:
    artifact_file = tmp_path / "not-a-directory"
    artifact_file.write_text("occupied", encoding="utf-8")

    text = CreativeKBBenchmarkSummaryPresenter().exception_to_text(
        FileExistsError("artifact_dir points to an existing file"),
        artifact_dir=artifact_file,
    )

    assert "产物写入失败" in text
    assert f"artifact_dir：{artifact_file}" in text


def test_real_creative_kb_benchmark_smoke_is_explicitly_gated(tmp_path: Path) -> None:
    if not os.getenv("NOVEL_AGENT_RUN_REAL_CREATIVE_KB_BENCHMARK"):
        pytest.skip("set NOVEL_AGENT_RUN_REAL_CREATIVE_KB_BENCHMARK=1 to run real LLM smoke")

    exit_code = main(
        [
            "--repo-root",
            str(Path.cwd()),
            "--run-id",
            f"real-smoke-{tmp_path.name}",
            "--case-count",
            "3",
            "--use-real-model",
            "--quiet-progress",
        ]
    )

    assert exit_code in {0, 1}

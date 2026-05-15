from __future__ import annotations

import json
from pathlib import Path
from typing import cast

from novel_agent.app.run_single_sample_smoke import main
from novel_agent.schemas import RunConfig


def test_run_single_sample_smoke_cli_requires_real_model(
    tmp_path: Path,
) -> None:
    sample_path = tmp_path / "sample.json"
    sample_path.write_text("{}", encoding="utf-8")
    db_path = tmp_path / "novel.db"
    db_path.write_text("", encoding="utf-8")

    try:
        main(
            [
                "--sample",
                str(sample_path),
                "--repo-root",
                str(tmp_path),
                "--db",
                str(db_path),
                "--runs-dir",
                str(tmp_path / "runs"),
            ]
        )
    except SystemExit as exc:
        assert "--use-real-model is required" in str(exc)
    else:
        raise AssertionError("run_single_sample_smoke should require --use-real-model")


def test_run_single_sample_smoke_cli_builds_generation_config_when_real_model_enabled(
    tmp_path: Path,
    monkeypatch,  # type: ignore[no-untyped-def]
    capsys,  # type: ignore[no-untyped-def]
) -> None:
    sample_path = tmp_path / "sample.json"
    sample_path.write_text("{}", encoding="utf-8")
    db_path = tmp_path / "novel.db"
    db_path.write_text("", encoding="utf-8")

    class _FakeResult:
        def __init__(self) -> None:
            self.run_id = "run-2"
            self.run_dir = str(tmp_path / "runs" / "run-2")
            self.generated_text = "真实模型生成文本"
            self.compare_report = type(
                "CompareHolder",
                (),
                {"decision": "pass", "weighted_score": 0.91},
            )()
            self.sample = type(
                "SampleHolder",
                (),
                {
                    "config": type(
                        "ConfigHolder",
                        (),
                        {
                            "sample_id": "sample-2",
                            "mode": "bounded_future_hint",
                        },
                    )(),
                    "reference_truth": type(
                        "TruthHolder",
                        (),
                        {"text": "真值文本"},
                    )(),
                },
            )()
            self.retrieval_result = type(
                "RetrievalHolder",
                (),
                {
                    "rerank_result": type(
                        "RerankHolder",
                        (),
                        {"selected_fragment_ids": ["frag-2"]},
                    )()
                },
            )()

    captured: dict[str, object] = {}

    class _FakeRunner:
        def __init__(
            self,
            *,
            source_db_path,
            runs_dir,
            repo_root,
            generation_service,
            generation_config,
            include_coarse_result,
            reviewer_service=None,
        ) -> None:  # type: ignore[no-untyped-def]
            captured["source_db_path"] = source_db_path
            captured["runs_dir"] = runs_dir
            captured["repo_root"] = repo_root
            captured["generation_service"] = generation_service
            captured["generation_config"] = generation_config
            captured["include_coarse_result"] = include_coarse_result
            captured["reviewer_service"] = reviewer_service

        def run(self, *, sample_path):  # type: ignore[no-untyped-def]
            captured["sample_path"] = sample_path
            return _FakeResult()

    monkeypatch.setattr("novel_agent.app.run_single_sample_smoke.SingleSampleSmokeRunner", _FakeRunner)

    exit_code = main(
        [
            "--sample",
            str(sample_path),
            "--repo-root",
            str(tmp_path),
            "--db",
            str(db_path),
            "--runs-dir",
            str(tmp_path / "runs"),
            "--use-real-model",
            "--model-type",
            "OpenAIModel",
            "--model-id",
            "deepseek-chat",
            "--provider",
            "openai",
            "--api-base",
            "https://api.example.com/v1",
            "--api-key",
            "secret-key",
            "--thinking",
            "enabled",
            "--reasoning-effort",
            "high",
            "--save-reasoning",
            "--action-type",
            "tool_calling",
            "--tools",
            "python_interpreter",
            "final_answer",
            "--imports",
            "json",
            "pathlib",
            "--verbosity-level",
            "2",
        ]
    )

    assert exit_code == 0
    assert captured["sample_path"] == str(sample_path)
    assert captured["generation_service"] is not None
    assert captured["reviewer_service"] is not None
    generation_config = cast(RunConfig, captured["generation_config"])
    assert generation_config is not None
    assert generation_config.model_type == "OpenAIModel"
    assert generation_config.model_id == "deepseek-chat"
    assert generation_config.provider == "openai"
    assert generation_config.api_base == "https://api.example.com/v1"
    assert generation_config.api_key == "secret-key"
    assert generation_config.thinking == "enabled"
    assert generation_config.reasoning_effort == "high"
    assert generation_config.save_reasoning is True
    assert generation_config.action_type == "tool_calling"
    assert generation_config.tools == ["python_interpreter", "final_answer"]
    assert generation_config.imports == ["json", "pathlib"]
    assert generation_config.verbosity_level == 2
    output = json.loads(capsys.readouterr().out)
    assert output["run_id"] == "run-2"
    assert output["decision"] == "pass"
    assert output["weighted_score"] == 0.91


def test_run_single_sample_smoke_cli_uses_tool_calling_defaults_for_real_model(
    tmp_path: Path,
    monkeypatch,  # type: ignore[no-untyped-def]
    capsys,  # type: ignore[no-untyped-def]
) -> None:
    sample_path = tmp_path / "sample.json"
    sample_path.write_text("{}", encoding="utf-8")
    db_path = tmp_path / "novel.db"
    db_path.write_text("", encoding="utf-8")
    captured: dict[str, object] = {}

    class _FakeResult:
        def __init__(self) -> None:
            self.run_id = "run-3"
            self.run_dir = str(tmp_path / "runs" / "run-3")
            self.generated_text = "真实模型生成文本"
            self.compare_report = type(
                "CompareHolder",
                (),
                {"decision": "borderline", "weighted_score": 0.7},
            )()
            self.sample = type(
                "SampleHolder",
                (),
                {
                    "config": type(
                        "ConfigHolder",
                        (),
                        {
                            "sample_id": "sample-3",
                            "mode": "chapter_authorized",
                        },
                    )(),
                    "reference_truth": type(
                        "TruthHolder",
                        (),
                        {"text": "真值文本"},
                    )(),
                },
            )()
            self.retrieval_result = type(
                "RetrievalHolder",
                (),
                {
                    "rerank_result": type(
                        "RerankHolder",
                        (),
                        {"selected_fragment_ids": ["frag-3"]},
                    )()
                },
            )()

    class _FakeRunner:
        def __init__(
            self,
            *,
            source_db_path,
            runs_dir,
            repo_root,
            generation_service,
            generation_config,
            include_coarse_result,
            reviewer_service=None,
        ) -> None:  # type: ignore[no-untyped-def]
            captured["generation_service"] = generation_service
            captured["generation_config"] = generation_config
            captured["reviewer_service"] = reviewer_service

        def run(self, *, sample_path):  # type: ignore[no-untyped-def]
            return _FakeResult()

    monkeypatch.setattr("novel_agent.app.run_single_sample_smoke.SingleSampleSmokeRunner", _FakeRunner)

    exit_code = main(
        [
            "--sample",
            str(sample_path),
            "--repo-root",
            str(tmp_path),
            "--db",
            str(db_path),
            "--runs-dir",
            str(tmp_path / "runs"),
            "--use-real-model",
        ]
    )

    assert exit_code == 0
    generation_config = cast(RunConfig, captured["generation_config"])
    assert generation_config is not None
    assert captured["reviewer_service"] is not None
    assert generation_config.action_type == "tool_calling"
    assert generation_config.tools == []
    output = json.loads(capsys.readouterr().out)
    assert output["run_id"] == "run-3"


def test_run_single_sample_smoke_source_mode_reads_api_key_from_env(
    tmp_path: Path,
    monkeypatch,  # type: ignore[no-untyped-def]
    capsys,  # type: ignore[no-untyped-def]
) -> None:
    source_path = tmp_path / "source.txt"
    source_path.write_text("第一段。\n\n第二段。", encoding="utf-8")
    captured: dict[str, object] = {}

    class _FakeAgenticResult:
        run_id = "agentic-run"
        run_dir = str(tmp_path / "runs" / "agentic-run")
        generated_synopsis_path = str(tmp_path / "runs" / "agentic-run" / "generated_story_synopsis.json")
        reference_synopsis_path = str(tmp_path / "runs" / "agentic-run" / "reference_story_synopsis.json")
        draft_path = str(tmp_path / "runs" / "agentic-run" / "expansion" / "draft.md")
        reference_truth_path = str(tmp_path / "runs" / "agentic-run" / "reference_truth.txt")
        synopsis_summary = "梗概通过"
        synopsis_decision = "pass"
        synopsis_score = 0.88
        expansion_summary = "扩写通过"
        expansion_decision = "pass"
        expansion_score = 0.86
        reviewer_summary = "综合通过"
        reviewer_decision = "pass"
        reviewer_score = 0.87

        def to_dict(self) -> dict[str, object]:
            return {
                "run_id": self.run_id,
                "run_dir": self.run_dir,
                "generated_synopsis_path": self.generated_synopsis_path,
                "reference_synopsis_path": self.reference_synopsis_path,
                "draft_path": self.draft_path,
                "reference_truth_path": self.reference_truth_path,
                "generated_chars": 128,
                "reference_truth_chars": 256,
                "reviewer_decision": self.reviewer_decision,
                "reviewer_score": self.reviewer_score,
            }

    class _FakeAgenticSmokeBenchmarkService:
        def __init__(self, *, repo_root: Path) -> None:
            captured["repo_root"] = repo_root

        def run_from_source(self, **kwargs):  # type: ignore[no-untyped-def]
            captured.update(kwargs)
            return _FakeAgenticResult()

    monkeypatch.setenv("DEEPSEEK_API_KEY", "secret-from-env")
    monkeypatch.setattr(
        "novel_agent.app.run_single_sample_smoke.AgenticSmokeBenchmarkService",
        _FakeAgenticSmokeBenchmarkService,
    )

    exit_code = main(
        [
            "--source",
            str(source_path),
            "--repo-root",
            str(tmp_path),
            "--runs-dir",
            str(tmp_path / "runs"),
            "--use-real-model",
            "--api-key-env",
            "DEEPSEEK_API_KEY",
        ]
    )

    assert exit_code == 0
    assert captured["api_key"] == "secret-from-env"
    assert captured["source_path"] == source_path
    output = json.loads(capsys.readouterr().out)
    assert output["run_id"] == "agentic-run"
    assert "梗概层 Reviewer" in output["summary_text"]

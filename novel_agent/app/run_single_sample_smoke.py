from __future__ import annotations

import argparse
import json
from pathlib import Path

from .bootstrap import resolve_db_path, resolve_repo_root
from .runner import SingleSampleSmokeRunner
from .services.continuation_generation_service import ContinuationGenerationService
from .services.smoke_benchmark_service import AgenticSmokeBenchmarkService, SmokeBenchmarkSummaryPresenter
from .services.smoke_reviewer_service import SmokeReviewerService
from ..schemas import RunConfig


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Run a single-sample smoke continuation pipeline")
    parser.add_argument("--sample", type=str, default=None, help="Path to smoke sample JSON")
    parser.add_argument("--source", type=str, default=None, help="Build a smoke sample from a source text file")
    parser.add_argument("--repo-root", type=str, default=None, help="Repository root for resolving relative assets")
    parser.add_argument("--db", type=str, default=None, help="Source SQLite database path")
    parser.add_argument("--runs-dir", type=str, default="runs", help="Directory to write smoke run artifacts into")
    parser.add_argument(
        "--use-real-model",
        action="store_true",
        help="Required: enable real model generation and LLM reviewer scoring",
    )
    parser.add_argument(
        "--model-type",
        type=str,
        default="InferenceClientModel",
        help="Model type (InferenceClientModel, OpenAIModel, LiteLLMModel, TransformersModel)",
    )
    parser.add_argument("--model-id", type=str, default="Qwen/Qwen3-Next-80B-A3B-Thinking", help="Model id")
    parser.add_argument("--provider", type=str, default=None, help="Inference provider (for InferenceClientModel)")
    parser.add_argument("--api-base", type=str, default=None, help="API base url")
    parser.add_argument("--api-key", type=str, default=None, help="API key")
    parser.add_argument(
        "--thinking",
        type=str,
        default=None,
        choices=["enabled", "disabled"],
        help="OpenAI-compatible thinking mode. Only effective with --model-type OpenAIModel.",
    )
    parser.add_argument(
        "--reasoning-effort",
        type=str,
        default=None,
        choices=["high", "max"],
        help="OpenAI-compatible reasoning effort. Only effective with --model-type OpenAIModel.",
    )
    parser.add_argument(
        "--save-reasoning",
        action="store_true",
        help="Write reasoning.json and reasoning.md when the selected model returns reasoning content.",
    )
    parser.add_argument("--action-type", type=str, default="tool_calling", choices=["code", "tool_calling"])
    parser.add_argument("--tools", nargs="*", default=[])
    parser.add_argument("--imports", nargs="*", default=[])
    parser.add_argument("--verbosity-level", type=int, default=1)
    parser.add_argument(
        "--include-coarse-result",
        action="store_true",
        help="Include coarse_result in retrieval artifacts for QA/debug",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    repo_root = resolve_repo_root(args.repo_root)
    if not args.use_real_model:
        raise SystemExit("--use-real-model is required for smoke benchmark runs")
    sample_path = args.sample
    db_arg = args.db
    if args.source:
        result = AgenticSmokeBenchmarkService(repo_root=repo_root).run_from_source(
            source_path=Path(args.source),
            api_key=args.api_key or "",
            runs_dir=Path(args.runs_dir),
        )
        payload = result.to_dict()
        payload["summary_text"] = (
            f"Reviewer：{result.reviewer_summary} ({result.reviewer_decision}, {result.reviewer_score:.2f})\n"
            f"run_id：{result.run_id}\n"
            f"产物目录：{result.run_dir}\n"
            f"Writer 草稿：{result.draft_path}\n"
            f"Reference truth：{result.reference_truth_path}"
        )
        print(json.dumps(payload, ensure_ascii=False, indent=2))
        return 0
    if not sample_path:
        raise SystemExit("--sample is required unless --source is provided")
    db_path = resolve_db_path(repo_root, db_arg)
    generation_config = RunConfig(
        prompt=None,
        model_type=args.model_type,
        model_id=args.model_id,
        provider=args.provider,
        api_base=args.api_base,
        api_key=args.api_key,
        thinking=args.thinking,
        reasoning_effort=args.reasoning_effort,
        save_reasoning=bool(args.save_reasoning),
        action_type=args.action_type,
        tools=list(args.tools),
        imports=list(args.imports),
        verbosity_level=args.verbosity_level,
        dry_run=False,
    )
    reviewer_service = SmokeReviewerService(
        generation_service=ContinuationGenerationService(),
        generation_config=generation_config,
    )
    runner = SingleSampleSmokeRunner(
        source_db_path=db_path,
        runs_dir=Path(args.runs_dir),
        repo_root=repo_root,
        generation_service=ContinuationGenerationService() if generation_config is not None else None,
        generation_config=generation_config,
        include_coarse_result=bool(args.include_coarse_result),
        reviewer_service=reviewer_service,
    )
    result = runner.run(sample_path=sample_path)
    print(json.dumps(SmokeBenchmarkSummaryPresenter().to_json_summary(result), ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

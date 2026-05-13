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
    parser.add_argument("--prefix-count", type=int, default=1, help="Minimum prefix chunk count for agentic source mode")
    parser.add_argument(
        "--prefix-min-chars",
        type=int,
        default=4_000,
        help="Minimum prefix character count before selecting held-out reference truth",
    )
    parser.add_argument(
        "--recent-window-size",
        type=int,
        default=3,
        help="Recent prefix chunk count exposed to benchmark planning/review artifacts",
    )
    parser.add_argument(
        "--reference-min-chars",
        type=int,
        default=2_700,
        help="Minimum held-out reference truth characters for agentic source mode",
    )
    parser.add_argument(
        "--sequence-chapter-count",
        type=int,
        default=1,
        help="Run a multi-chapter agentic smoke sequence with Writer writeback between chapters",
    )
    parser.add_argument(
        "--benchmark-cache-dir",
        type=str,
        default=None,
        help="Directory for reusable rough-read/close-read/Creative KB modeling cache",
    )
    parser.add_argument(
        "--reuse-modeling-cache",
        action="store_true",
        help="Reuse cached modeling artifacts and rerun only Writer/Reviewer layers when available",
    )
    parser.add_argument(
        "--rebuild-modeling-cache",
        action="store_true",
        help="Rebuild modeling artifacts and refresh the cache for this source/window",
    )
    parser.add_argument(
        "--clear-modeling-cache",
        action="store_true",
        help="Delete the matching modeling cache entry before running",
    )
    parser.add_argument("--max-read-kb", type=int, default=64, help="Rough-read byte window passed to pipeline")
    parser.add_argument("--max-close-batches", type=int, default=12, help="Maximum close-read batches passed to pipeline")
    parser.add_argument("--segment-step-kb", type=int, default=32, help="Segmentation step size passed to pipeline")
    parser.add_argument("--close-step-batches", type=int, default=1, help="Close-read step size passed to pipeline")
    parser.add_argument(
        "--enable-outline-research-loop",
        action="store_true",
        help="Run the Writer Outline Research Loop benchmark path",
    )
    parser.add_argument(
        "--outline-research-author-brief",
        action="store_true",
        help="Run the author brief reconstruction smoke for Outline Research",
    )
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
            prefix_count=args.prefix_count,
            prefix_min_chars=args.prefix_min_chars,
            recent_window_size=args.recent_window_size,
            reference_min_chars=args.reference_min_chars,
            sequence_chapter_count=args.sequence_chapter_count,
            benchmark_cache_dir=Path(args.benchmark_cache_dir) if args.benchmark_cache_dir else None,
            reuse_modeling_cache=bool(args.reuse_modeling_cache),
            rebuild_modeling_cache=bool(args.rebuild_modeling_cache),
            clear_modeling_cache=bool(args.clear_modeling_cache),
            max_read_kb=args.max_read_kb,
            max_close_batches=args.max_close_batches,
            segment_step_kb=args.segment_step_kb,
            close_step_batches=args.close_step_batches,
            enable_outline_research_loop=bool(args.enable_outline_research_loop),
            outline_research_author_brief=bool(args.outline_research_author_brief),
            use_real_outline_research_reviewer=bool(args.outline_research_author_brief),
        )
        payload = result.to_dict()
        if args.outline_research_author_brief:
            payload["summary_text"] = (
                f"OutlineResearchReviewer：{result.reviewer_summary} ({result.reviewer_decision}, {result.reviewer_score:.2f})\n"
                f"flow_status：{result.outline_research_status}\n"
                f"artifact_dir：{result.outline_research_artifact_dir}\n"
                f"leakage_audit：{result.outline_research_leakage_audit_path}\n"
                f"major_failures：{', '.join(result.outline_research_major_failures or []) or 'none'}\n"
                f"next_steps：{'; '.join(result.outline_research_next_steps or [])}"
            )
        else:
            payload["summary_text"] = (
                f"梗概层 Reviewer：{result.synopsis_summary} ({result.synopsis_decision}, {result.synopsis_score:.2f})\n"
                f"扩写层 Reviewer：{result.expansion_summary} ({result.expansion_decision}, {result.expansion_score:.2f})\n"
                f"综合 Reviewer：{result.reviewer_summary} ({result.reviewer_decision}, {result.reviewer_score:.2f})\n"
                f"run_id：{result.run_id}\n"
                f"产物目录：{result.run_dir}\n"
                f"生成梗概：{result.generated_synopsis_path}\n"
                f"原文梗概：{result.reference_synopsis_path}\n"
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

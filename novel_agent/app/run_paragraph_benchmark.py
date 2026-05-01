from __future__ import annotations

import argparse
import json
from pathlib import Path

from ..schemas import RunConfig
from .bootstrap import resolve_repo_root
from .services.continuation_generation_service import ContinuationGenerationService
from .services.paragraph_benchmark_service import ParagraphBenchmarkService


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Run the minimal N -> N+1 paragraph continuation benchmark")
    parser.add_argument("--source", type=str, required=True, help="Novel source text file")
    parser.add_argument("--prefix-count", type=int, required=True, help="Use the first N segments as prefix")
    parser.add_argument(
        "--recent-window-size",
        type=int,
        default=3,
        help="Reviewer/generator recent window size M",
    )
    parser.add_argument("--target-length-chars", type=int, default=600, help="Short continuation target length")
    parser.add_argument("--outline", type=str, default=None, help="Optional outline file")
    parser.add_argument(
        "--characters",
        nargs="*",
        default=[],
        help="Optional character names to check, separated by spaces or commas",
    )
    parser.add_argument("--repo-root", type=str, default=None, help="Repository root for resolving run artifacts")
    parser.add_argument(
        "--runs-dir",
        type=str,
        default="runs/paragraph_benchmark",
        help="Directory to write benchmark run artifacts into",
    )
    parser.add_argument(
        "--use-real-model",
        action="store_true",
        help="Enable real model generation instead of the deterministic wiring fallback",
    )
    parser.add_argument(
        "--model-type",
        type=str,
        default="InferenceClientModel",
        help="Model type (InferenceClientModel, OpenAIModel, LiteLLMModel, TransformersModel)",
    )
    parser.add_argument("--model-id", type=str, default="Qwen/Qwen3-Next-80B-A3B-Thinking", help="Model id")
    parser.add_argument("--provider", type=str, default=None, help="Inference provider")
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
    parser.add_argument("--action-type", type=str, default="tool_calling", choices=["code", "tool_calling"])
    parser.add_argument("--tools", nargs="*", default=[])
    parser.add_argument("--imports", nargs="*", default=[])
    parser.add_argument("--verbosity-level", type=int, default=1)
    return parser


def _build_generation_config(args: argparse.Namespace) -> RunConfig | None:
    if not args.use_real_model:
        return None
    return RunConfig(
        prompt=None,
        model_type=args.model_type,
        model_id=args.model_id,
        provider=args.provider,
        api_base=args.api_base,
        api_key=args.api_key,
        thinking=args.thinking,
        reasoning_effort=args.reasoning_effort,
        action_type=args.action_type,
        tools=list(args.tools),
        imports=list(args.imports),
        verbosity_level=args.verbosity_level,
        dry_run=False,
    )


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    repo_root = resolve_repo_root(args.repo_root)
    outline_path = Path(args.outline).expanduser() if args.outline else None
    generation_config = _build_generation_config(args)
    service = ParagraphBenchmarkService(
        generation_service=ContinuationGenerationService(),
    )
    result = service.run(
        source_path=Path(args.source),
        prefix_count=args.prefix_count,
        recent_window_size=args.recent_window_size,
        target_length_chars=args.target_length_chars,
        outline_path=outline_path,
        character_names=list(args.characters),
        runs_dir=repo_root / args.runs_dir,
        generation_config=generation_config,
    )
    print(
        json.dumps(
            {
                "run_id": result.run_id,
                "run_dir": result.run_dir,
                "source_path": result.sample.source_path,
                "prefix_count": result.sample.prefix_count,
                "target_segment_index": result.sample.target_segment_index,
                "recent_window_size": result.sample.recent_window_size,
                "generated_chars": len(result.generated_text),
                "reference_truth_chars": len(result.sample.reference_truth),
                "decision": result.reviewer_report.decision,
                "score": result.reviewer_report.score,
                "summary": result.reviewer_report.summary,
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

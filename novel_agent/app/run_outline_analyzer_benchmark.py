from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from .bootstrap import resolve_repo_root
from .services.outline_analyzer_benchmark_service import (
    DEFAULT_ANALYZER_BENCHMARK_TIMEOUT_SECONDS,
    AnalyzerBenchmarkConfig,
    AnalyzerBenchmarkModelConfig,
    OutlineAnalyzerBenchmarkService,
    build_default_longzu_120kb_config,
)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Run Outline Analyzer full-text baseline smoke benchmark")
    parser.add_argument("target", nargs="?", default="longzu-120kb", help="Fixture target, currently longzu-120kb")
    parser.add_argument("--repo-root", type=str, default=None)
    parser.add_argument("--source", type=str, default=None, help="Source novel text path")
    parser.add_argument("--db", "--db-path", dest="db_path", type=str, default=None, help="Close-read sqlite path")
    parser.add_argument("--book-id", type=str, default=None)
    parser.add_argument("--run-id", type=str, default=None)
    parser.add_argument("--artifact-dir", type=str, default=None)
    parser.add_argument(
        "--prompt-id",
        action="append",
        default=[],
        help="Prompt id to run; may be provided multiple times. Default runs all benchmark prompts.",
    )
    parser.add_argument("--model-type", type=str, default="OpenAIModel")
    parser.add_argument("--model-id", type=str, default="deepseek-v4-pro")
    parser.add_argument("--provider", type=str, default="openai_compatible")
    parser.add_argument("--api-base", type=str, default="https://api.deepseek.com")
    parser.add_argument("--api-key", type=str, default=None)
    parser.add_argument("--api-key-env", type=str, default="DEEPSEEK_API_KEY")
    parser.add_argument("--temperature", type=float, default=0.2)
    parser.add_argument("--max-output-tokens", type=int, default=8192)
    parser.add_argument(
        "--timeout-seconds",
        type=int,
        default=DEFAULT_ANALYZER_BENCHMARK_TIMEOUT_SECONDS,
        help="Per model request timeout; default is intentionally long for full-text baseline prompts.",
    )
    parser.add_argument("--request-retry-attempts", type=int, default=3)
    parser.add_argument("--request-retry-backoff-seconds", type=float, default=1.0)
    parser.add_argument("--thinking", type=str, default="enabled", choices=["enabled", "disabled"])
    parser.add_argument("--reasoning-effort", type=str, default="high", choices=["low", "medium", "high", "max"])
    parser.add_argument("--include-reasoning-content", action="store_true")
    parser.add_argument(
        "--no-reuse-baseline",
        action="store_true",
        help="Force rerunning the full-text baseline even when a cached answer exists.",
    )
    parser.add_argument("--json", action="store_true", help="Print machine-readable result JSON")
    return parser


def config_from_args(args: argparse.Namespace) -> AnalyzerBenchmarkConfig:
    repo_root = resolve_repo_root(args.repo_root)
    model_config = AnalyzerBenchmarkModelConfig(
        model_type=args.model_type,
        model_name=args.model_id,
        provider=args.provider,
        base_url=args.api_base,
        api_key=args.api_key,
        api_key_env=args.api_key_env,
        temperature=args.temperature,
        max_output_tokens=args.max_output_tokens,
        timeout_seconds=args.timeout_seconds,
        request_retry_attempts=args.request_retry_attempts,
        request_retry_backoff_seconds=args.request_retry_backoff_seconds,
        thinking=args.thinking,
        reasoning_effort=args.reasoning_effort,
        include_reasoning_content=bool(args.include_reasoning_content),
    )
    if args.source or args.db_path or args.book_id or args.artifact_dir:
        if not args.source:
            raise SystemExit("--source is required when overriding benchmark paths")
        if not args.db_path:
            raise SystemExit("--db is required when overriding benchmark paths")
        if not args.book_id:
            raise SystemExit("--book-id is required when overriding benchmark paths")
        return AnalyzerBenchmarkConfig(
            source_path=Path(args.source).expanduser(),
            db_path=Path(args.db_path).expanduser(),
            book_id=args.book_id,
            artifact_dir=Path(args.artifact_dir).expanduser()
            if args.artifact_dir
            else repo_root / "runs" / "benchmarks" / "outline_analyzer",
            run_id=args.run_id or "",
            prompt_ids=[str(item) for item in args.prompt_id],
            model_config=model_config,
            reuse_baseline=not bool(args.no_reuse_baseline),
        )
    if args.target not in {"longzu-120kb", "longzu_120kb"}:
        raise SystemExit(f"unknown outline analyzer benchmark target: {args.target}")
    return build_default_longzu_120kb_config(
        repo_root=repo_root,
        run_id=args.run_id or "",
        prompt_ids=[str(item) for item in args.prompt_id],
        model_config=model_config,
        reuse_baseline=not bool(args.no_reuse_baseline),
    )


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    config = config_from_args(args)
    repo_root = resolve_repo_root(args.repo_root)
    result = OutlineAnalyzerBenchmarkService(repo_root=repo_root).run(config)
    payload = result.to_dict()
    if args.json:
        print(json.dumps(payload, ensure_ascii=False, indent=2))
        return 0
    print("Outline Analyzer Benchmark")
    print(f"状态：{payload['status']}")
    print(f"run_id：{payload['run_id']}")
    print(f"产物目录：{payload['artifact_dir']}")
    print(f"summary：{payload['summary_path']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))

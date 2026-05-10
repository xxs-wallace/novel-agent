from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any, Mapping

from .bootstrap import resolve_repo_root
from .runner.creative_kb_benchmark_runner import (
    CreativeKBBenchmarkRunConfig,
    CreativeKBBenchmarkRunner,
    CreativeKBBenchmarkSummaryPresenter,
)


FIXTURE_TARGETS = {
    "longzu-32kb": "longzu_32kb",
    "longzu_32kb": "longzu_32kb",
    "longzu-96kb": "longzu_96kb",
    "longzu_96kb": "longzu_96kb",
}


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Run Creative KB benchmark and print a human-readable summary")
    parser.add_argument("target", nargs="?", default="longzu-32kb", help="Fixture target, e.g. longzu-32kb")
    parser.add_argument("--source", type=str, default=None, help="Source text path; overrides fixture target")
    parser.add_argument("--fixture", type=str, default=None, help="Fixture name or path; overrides positional target")
    parser.add_argument("--repo-root", type=str, default=None, help="Repository root for resolving relative assets")
    parser.add_argument("--run-id", type=str, default=None, help="Stable run id for artifact directory")
    parser.add_argument("--artifact-dir", type=str, default=None, help="Artifact output directory")
    parser.add_argument("--case-count", type=int, default=3, help="Benchmark case count, clamped to 3-5")
    parser.add_argument("--seed", type=int, default=17, help="Stable seed for cases and decoys")
    parser.add_argument("--prefix-min-chars", type=int, default=1200, help="Minimum prefix character count")
    parser.add_argument("--recent-window-size", type=int, default=3, help="Recent prefix segment count")
    parser.add_argument("--writer-ab", "--enable-writer-ab", action="store_true", help="Enable Writer A/B diagnostic")
    parser.add_argument("--use-real-model", action="store_true", help="Enable real LLM calls")
    parser.add_argument(
        "--dry-run-model",
        action="store_true",
        help="Use model dry-run fallbacks for local shape checks without real LLM calls",
    )
    parser.add_argument("--model-type", type=str, default="InferenceClientModel")
    parser.add_argument("--model-id", type=str, default="Qwen/Qwen3-Next-80B-A3B-Thinking")
    parser.add_argument("--provider", type=str, default=None)
    parser.add_argument("--api-base", type=str, default=None)
    parser.add_argument("--api-key", type=str, default=None)
    parser.add_argument("--api-key-env", type=str, default="DEEPSEEK_API_KEY")
    parser.add_argument("--temperature", type=float, default=0.2)
    parser.add_argument("--max-output-tokens", type=int, default=8192)
    parser.add_argument("--timeout-seconds", type=int, default=120)
    parser.add_argument("--thinking", type=str, default=None, choices=["enabled", "disabled"])
    parser.add_argument("--reasoning-effort", type=str, default=None, choices=["low", "medium", "high", "max"])
    parser.add_argument("--json", action="store_true", help="Print machine-readable summary JSON")
    parser.add_argument("--quiet-progress", action="store_true", help="Do not print progress events to stderr")
    return parser


def config_from_args(args: argparse.Namespace) -> CreativeKBBenchmarkRunConfig:
    if args.source and args.fixture:
        raise SystemExit("--source and --fixture cannot be used together")
    if args.source and args.target != "longzu-32kb":
        raise SystemExit("positional target and --source cannot be used together")
    if args.use_real_model and args.dry_run_model:
        raise SystemExit("--use-real-model and --dry-run-model cannot both be set")
    fixture = _resolve_fixture(args)
    source_path = Path(args.source).expanduser() if args.source else None
    return CreativeKBBenchmarkRunConfig(
        source_path=source_path,
        fixture=None if source_path is not None else fixture,
        run_id=args.run_id,
        case_count=args.case_count,
        artifact_dir=Path(args.artifact_dir).expanduser() if args.artifact_dir else None,
        enable_writer_ab=bool(args.writer_ab),
        seed=args.seed,
        prefix_min_chars=args.prefix_min_chars,
        recent_window_size=args.recent_window_size,
        use_real_model=bool(args.use_real_model),
        dry_run_model=bool(args.dry_run_model),
        model_type=args.model_type,
        model_id=args.model_id,
        provider=args.provider,
        api_base=args.api_base,
        api_key=args.api_key,
        api_key_env=args.api_key_env,
        temperature=args.temperature,
        max_output_tokens=args.max_output_tokens,
        timeout_seconds=args.timeout_seconds,
        thinking=args.thinking,
        reasoning_effort=args.reasoning_effort,
    )


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if not args.use_real_model and not args.dry_run_model:
        raise SystemExit(
            "--use-real-model is required for real Creative KB benchmark runs; "
            "use --dry-run-model for local shape checks"
        )

    repo_root = resolve_repo_root(args.repo_root)
    presenter = CreativeKBBenchmarkSummaryPresenter()
    progress_callback = None if args.quiet_progress else _stderr_progress_callback
    runner = CreativeKBBenchmarkRunner(repo_root=repo_root, progress_callback=progress_callback)
    config = config_from_args(args)
    try:
        result = runner.run(config)
    except Exception as exc:  # noqa: BLE001 - CLI must turn runner failures into readable benchmark output.
        print(
            presenter.exception_to_text(
                exc,
                artifact_dir=config.artifact_dir,
            ),
            file=sys.stderr,
        )
        return 1

    if args.json:
        print(json.dumps(presenter.to_json_summary(result), ensure_ascii=False, indent=2))
    else:
        print(presenter.to_text(result))
    return 0 if result.status != "failed" else 1


def _resolve_fixture(args: argparse.Namespace) -> str | None:
    if args.fixture:
        return str(args.fixture)
    target = str(args.target or "longzu-32kb")
    return FIXTURE_TARGETS.get(target, target)


def _stderr_progress_callback(event: Mapping[str, Any]) -> None:
    stage = str(event.get("stage") or "runner")
    phase = str(event.get("phase") or event.get("event") or "progress")
    case_id = str(event.get("case_id") or "")
    suffix = f" {case_id}" if case_id else ""
    print(f"[{stage}] {phase}{suffix}", file=sys.stderr)


if __name__ == "__main__":
    raise SystemExit(main())

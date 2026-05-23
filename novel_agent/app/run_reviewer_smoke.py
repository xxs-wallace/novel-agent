from __future__ import annotations

import argparse
import json
from pathlib import Path

from .bootstrap import resolve_repo_root
from .services.reviewer_smoke_service import (
    ReviewerSmokeConfig,
    ReviewerSmokeModelConfig,
    ReviewerSmokeService,
)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Run the real-model Reviewer Agent smoke suite")
    parser.add_argument("--repo-root", type=str, default=None)
    parser.add_argument("--run-id", type=str, default=None)
    parser.add_argument("--output-root", type=str, default=None, help="Defaults to runs/reviewer_smoke")
    parser.add_argument("--source", type=str, default=None, help="Source novel text; defaults to novel_agent/tests/longzu_120kb.txt")
    parser.add_argument("--case-fixture", type=str, default=None, help="Reuse previously successful constructed smoke cases from this JSON fixture")
    parser.add_argument("--book-id", type=str, default=None)
    parser.add_argument("--source-tail-chars", type=int, default=48000)
    parser.add_argument("--heldout-ratio", type=float, default=0.1)
    parser.add_argument("--heldout-min-chars", type=int, default=3200)
    parser.add_argument("--max-read-chars", type=int, default=48000)
    parser.add_argument("--close-read-document-budget", type=int, default=48000)
    parser.add_argument("--close-read-max-chapters", type=int, default=None)
    parser.add_argument("--creative-kb-commit-batch-size", type=int, default=8)
    parser.add_argument("--reviewer-json-repair-attempts", type=int, default=0)
    parser.add_argument("--model-type", type=str, default="OpenAIModel")
    parser.add_argument("--model-name", type=str, default="deepseek-chat")
    parser.add_argument("--api-base", type=str, default="https://api.deepseek.com")
    parser.add_argument("--api-key", type=str, default=None)
    parser.add_argument("--api-key-file", type=str, default=None)
    parser.add_argument("--api-key-env", type=str, default="DEEPSEEK_API_KEY")
    parser.add_argument("--temperature", type=float, default=0.2)
    parser.add_argument("--max-output-tokens", type=int, default=8192)
    parser.add_argument("--timeout-seconds", type=int, default=180)
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
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if (args.thinking or args.reasoning_effort) and args.model_type != "OpenAIModel":
        raise SystemExit("--thinking/--reasoning-effort requires --model-type OpenAIModel")
    repo_root = resolve_repo_root(args.repo_root)
    model = ReviewerSmokeModelConfig(
        model_type=args.model_type,
        model_name=args.model_name,
        base_url=args.api_base,
        api_key=args.api_key,
        api_key_file=args.api_key_file,
        api_key_env=args.api_key_env,
        temperature=args.temperature,
        max_output_tokens=args.max_output_tokens,
        timeout_seconds=args.timeout_seconds,
        thinking=args.thinking,
        reasoning_effort=args.reasoning_effort,
        include_reasoning_content=bool(args.thinking or args.reasoning_effort),
    )
    config = ReviewerSmokeConfig(
        repo_root=repo_root,
        run_id=args.run_id,
        output_root=Path(args.output_root) if args.output_root else None,
        source_path=Path(args.source) if args.source else None,
        case_fixture_path=Path(args.case_fixture) if args.case_fixture else None,
        book_id=args.book_id,
        source_tail_chars=args.source_tail_chars,
        heldout_ratio=args.heldout_ratio,
        heldout_min_chars=args.heldout_min_chars,
        segmentation_max_read_chars=args.max_read_chars,
        close_read_document_chars_budget=args.close_read_document_budget,
        close_read_max_chapters=args.close_read_max_chapters,
        creative_kb_commit_batch_size=args.creative_kb_commit_batch_size,
        reviewer_json_repair_attempts=args.reviewer_json_repair_attempts,
        model=model,
    )
    summary = ReviewerSmokeService(repo_root=repo_root).run(config)
    print(json.dumps(summary, ensure_ascii=False, indent=2, sort_keys=True))
    return 0 if summary.get("status") == "success" else 1


if __name__ == "__main__":
    raise SystemExit(main())

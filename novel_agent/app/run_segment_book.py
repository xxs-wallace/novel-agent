from __future__ import annotations

import argparse
import json

from .bootstrap import resolve_db_path, resolve_repo_root
from .runner.segmentation_runner import SegmentationRunner
from .schemas.config_schema import SegmentationAgentConfig


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Segment novel source files into SQLite documents")
    parser.add_argument("--repo-root", type=str, default=None)
    parser.add_argument("--db", type=str, default=None)
    parser.add_argument("--config", type=str, default=None, help="Optional JSON/YAML config file")
    parser.add_argument("--book-id", type=str, default=None)
    parser.add_argument("--source-root", type=str, default=None)
    parser.add_argument("--model-type", type=str, default="OpenAIModel")
    parser.add_argument("--model-name", type=str, default="deepseek-chat")
    parser.add_argument("--api-base", type=str, default="https://api.deepseek.com")
    parser.add_argument("--api-key", type=str, default=None)
    parser.add_argument("--api-key-file", type=str, default=None)
    parser.add_argument("--api-key-env", type=str, default="DEEPSEEK_API_KEY")
    parser.add_argument(
        "--thinking",
        type=str,
        default=None,
        choices=["enabled", "disabled"],
        help="DeepSeek thinking mode (OpenAI-compatible via extra_body). Only effective when --model-type OpenAIModel.",
    )
    parser.add_argument(
        "--reasoning-effort",
        type=str,
        default=None,
        choices=["high", "max"],
        help="DeepSeek thinking effort. Only effective when --model-type OpenAIModel.",
    )
    parser.add_argument("--max-read-chars", type=int, default=None, help="Limit total source chars read before segmentation")
    parser.add_argument(
        "--preferred-document-chars-min",
        type=int,
        default=None,
        help="Preferred minimum chars per document; useful for smaller test fixtures",
    )
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--resume-from-checkpoint", action="store_true")
    return parser


def _build_config(args: argparse.Namespace, db_path: str) -> SegmentationAgentConfig:
    if args.config:
        config = SegmentationAgentConfig.from_file(args.config)
        config.storage.sqlite_path = db_path
        if args.max_read_chars is not None:
            config.read_strategy.max_total_chars = int(args.max_read_chars)
        if args.preferred_document_chars_min is not None:
            config.read_strategy.preferred_document_chars_min = int(args.preferred_document_chars_min)
        if (args.thinking or args.reasoning_effort) and config.model.model_type != "OpenAIModel":
            raise SystemExit("--thinking/--reasoning-effort requires --model-type OpenAIModel")
        if args.thinking is not None:
            config.model.thinking = args.thinking
        if args.reasoning_effort is not None:
            config.model.reasoning_effort = args.reasoning_effort
        if args.thinking or args.reasoning_effort:
            config.model.include_reasoning_content = True
        if args.dry_run:
            config.runtime.dry_run = True
        if args.resume_from_checkpoint:
            config.runtime.resume_from_checkpoint = True
        return config
    if not args.book_id or not args.source_root:
        raise SystemExit("--book-id and --source-root are required when --config is not provided")
    if (args.thinking or args.reasoning_effort) and args.model_type != "OpenAIModel":
        raise SystemExit("--thinking/--reasoning-effort requires --model-type OpenAIModel")
    read_strategy: dict[str, int] = {}
    if args.max_read_chars is not None:
        read_strategy["max_total_chars"] = int(args.max_read_chars)
    if args.preferred_document_chars_min is not None:
        read_strategy["preferred_document_chars_min"] = int(args.preferred_document_chars_min)
    return SegmentationAgentConfig.from_mapping(
        {
            "book": {"book_id": args.book_id, "source_root": args.source_root},
            "model": {
                "model_type": args.model_type,
                "model_name": args.model_name,
                "base_url": args.api_base,
                "api_key": args.api_key,
                "api_key_file": args.api_key_file,
                "api_key_env": args.api_key_env,
                "thinking": args.thinking,
                "reasoning_effort": args.reasoning_effort,
                "include_reasoning_content": bool(args.thinking or args.reasoning_effort),
            },
            "read_strategy": read_strategy,
            "storage": {"sqlite_path": db_path},
            "runtime": {
                "dry_run": bool(args.dry_run),
                "resume_from_checkpoint": bool(args.resume_from_checkpoint),
            },
        }
    )


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    repo_root = resolve_repo_root(args.repo_root)
    db_path = resolve_db_path(repo_root, args.db)
    config = _build_config(args, str(db_path))
    runner = SegmentationRunner(repo_root=repo_root, db_path=db_path, config=config)
    result = runner.run()
    print(
        json.dumps(
            {
                "book_id": result.book_id,
                "db_path": str(result.db_path),
                "inserted_documents": result.inserted_documents,
                "batch_count": result.batch_count,
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

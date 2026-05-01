from __future__ import annotations

import argparse
import json

from .bootstrap import resolve_db_path, resolve_repo_root
from .constants import DEFAULT_CLOSE_READ_DOC_BUDGET
from .runner.close_read_runner import CloseReadRunner
from .schemas.config_schema import CloseReadAgentConfig


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Run close reading on segmented novel documents")
    parser.add_argument("--repo-root", type=str, default=None)
    parser.add_argument("--db", type=str, default=None)
    parser.add_argument("--book-id", type=str, required=True)
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
    parser.add_argument("--document-budget", type=int, default=DEFAULT_CLOSE_READ_DOC_BUDGET)
    parser.add_argument("--max-chapters", type=int, default=None)
    parser.add_argument("--debug-markdown-path", type=str, default=None)
    parser.add_argument("--dry-run", action="store_true")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    repo_root = resolve_repo_root(args.repo_root)
    db_path = resolve_db_path(repo_root, args.db)
    config = CloseReadAgentConfig(
        book_id=args.book_id,
        sqlite_path=str(db_path),
    )
    config.model.model_type = args.model_type
    config.model.model_name = args.model_name
    config.model.base_url = args.api_base
    config.model.api_key = args.api_key
    config.model.api_key_file = args.api_key_file
    config.model.api_key_env = args.api_key_env
    if (args.thinking or args.reasoning_effort) and args.model_type != "OpenAIModel":
        raise SystemExit("--thinking/--reasoning-effort requires --model-type OpenAIModel")
    config.model.thinking = args.thinking
    config.model.reasoning_effort = args.reasoning_effort
    config.model.include_reasoning_content = bool(args.thinking or args.reasoning_effort)
    config.runtime.document_chars_budget = int(args.document_budget)
    config.runtime.max_chapters = args.max_chapters
    config.runtime.debug_markdown_path = args.debug_markdown_path
    config.runtime.dry_run = bool(args.dry_run)
    runner = CloseReadRunner(repo_root=repo_root, db_path=db_path, config=config)
    result = runner.run()
    print(
        json.dumps(
            {
                "book_id": result.book_id,
                "processed_batches": result.processed_batches,
                "exported_markdown": str(result.exported_markdown) if result.exported_markdown else None,
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

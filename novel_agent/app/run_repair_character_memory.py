from __future__ import annotations

import argparse
import json
from typing import Any

from .bootstrap import resolve_db_path, resolve_repo_root
from .constants import DEFAULT_CLOSE_READ_DOC_BUDGET
from .schemas.config_schema import CloseReadAgentConfig
from .services.character_memory_repair_service import CharacterMemoryRepairService


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Repair close-read character mentions and character profiles without regenerating chapter summaries",
    )
    parser.add_argument("--repo-root", type=str, default=None)
    parser.add_argument("--db", type=str, default=None)
    parser.add_argument("--book-id", type=str, required=True)
    parser.add_argument("--max-doc-id", type=int, default=None)
    parser.add_argument("--model-type", type=str, default="OpenAIModel")
    parser.add_argument("--model-name", type=str, default="deepseek-chat")
    parser.add_argument("--api-base", type=str, default="https://api.deepseek.com")
    parser.add_argument("--api-key", type=str, default=None)
    parser.add_argument("--api-key-file", type=str, default=None)
    parser.add_argument("--api-key-env", type=str, default="DEEPSEEK_API_KEY")
    parser.add_argument("--document-budget", type=int, default=DEFAULT_CLOSE_READ_DOC_BUDGET)
    parser.add_argument("--dry-run", action="store_true")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    repo_root = resolve_repo_root(args.repo_root)
    db_path = resolve_db_path(repo_root, args.db)
    config = CloseReadAgentConfig(book_id=args.book_id, sqlite_path=str(db_path))
    config.model.model_type = args.model_type
    config.model.model_name = args.model_name
    config.model.base_url = args.api_base
    config.model.api_key = args.api_key
    config.model.api_key_file = args.api_key_file
    config.model.api_key_env = args.api_key_env
    config.runtime.document_chars_budget = int(args.document_budget)
    config.runtime.dry_run = bool(args.dry_run)

    def emit(event: dict[str, Any]) -> None:
        print(json.dumps({"character_memory_repair": event}, ensure_ascii=False), flush=True)

    result = CharacterMemoryRepairService(
        repo_root=repo_root,
        db_path=db_path,
        config=config,
        progress_callback=emit,
    ).run(max_doc_id=args.max_doc_id)
    print(json.dumps(result.to_dict(), ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

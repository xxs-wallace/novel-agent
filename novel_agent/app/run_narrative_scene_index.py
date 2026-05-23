from __future__ import annotations

import argparse
import json

from .bootstrap import resolve_db_path, resolve_repo_root
from .cli.facade import WorkflowFacade


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Build NarrativeSceneCard index cards from close-read memory")
    parser.add_argument("--repo-root", type=str, default=None)
    parser.add_argument("--db", type=str, default=None)
    parser.add_argument("--book-id", type=str, required=True)
    parser.add_argument("--api-key", type=str, default=None)
    parser.add_argument("--window-chars", type=int, default=None)
    parser.add_argument("--overlap-docs", type=int, default=None)
    parser.add_argument("--dry-run", action="store_true")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    repo_root = resolve_repo_root(args.repo_root)
    db_path = resolve_db_path(repo_root, args.db)
    result = WorkflowFacade(repo_root=repo_root).build_narrative_scene_index(
        db_path=db_path,
        book_id=args.book_id,
        api_key=args.api_key,
        dry_run=bool(args.dry_run),
        window_chars_budget=args.window_chars,
        overlap_docs=args.overlap_docs,
    )
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

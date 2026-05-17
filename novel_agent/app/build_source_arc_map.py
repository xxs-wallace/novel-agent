from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

from .bootstrap import resolve_repo_root
from .llm import JsonModelClient, ModelSettings
from .repos.db import NovelAgentDB
from .services.source_arc_mapping_service import SourceArcMappingService


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Build SourceArcMap from existing close-read chapter summaries")
    parser.add_argument("task_id", help="Task/book id, usually the slug used by the pipeline")
    parser.add_argument("--repo-root", type=str, default=None)
    parser.add_argument("--db", type=str, default=None, help="Override sqlite database path")
    parser.add_argument("--format", choices=("markdown", "json"), default="markdown")
    parser.add_argument("--use-model", action="store_true", help="Use model prompts for compression and SourceArcMap generation")
    parser.add_argument("--model-type", type=str, default="OpenAIModel")
    parser.add_argument("--model-name", type=str, default="deepseek-chat")
    parser.add_argument("--api-base", type=str, default="https://api.deepseek.com")
    parser.add_argument("--api-key", type=str, default=None)
    parser.add_argument("--api-key-file", type=str, default=None)
    parser.add_argument("--api-key-env", type=str, default="DEEPSEEK_API_KEY")
    parser.add_argument("--thinking", type=str, default=None, choices=["enabled", "disabled"])
    parser.add_argument("--reasoning-effort", type=str, default=None, choices=["high", "max"])
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    repo_root = resolve_repo_root(args.repo_root)
    db_path = _resolve_task_db_path(repo_root=repo_root, task_id=args.task_id, db_path=args.db)
    if not db_path.exists():
        print(f"close-read sqlite not found: {db_path}", file=sys.stderr)
        return 1

    if (args.thinking or args.reasoning_effort) and args.model_type != "OpenAIModel":
        raise SystemExit("--thinking/--reasoning-effort requires --model-type OpenAIModel")
    model_client = (
        JsonModelClient(
            ModelSettings(
                model_type=args.model_type,
                model_name=args.model_name,
                base_url=args.api_base,
                api_key=args.api_key,
                api_key_file=args.api_key_file,
                api_key_env=args.api_key_env,
                thinking=args.thinking,
                reasoning_effort=args.reasoning_effort,
                include_reasoning_content=bool(args.thinking or args.reasoning_effort),
                max_output_tokens=12288,
            )
        )
        if args.use_model
        else None
    )
    try:
        payload = build_source_arc_map(repo_root=repo_root, db_path=db_path, book_id=args.task_id, model_client=model_client)
    except Exception as exc:
        payload = {
            "status": "failed",
            "reason": str(exc),
            "book_id": args.task_id,
            "db_path": db_path.as_posix(),
        }
    if payload["status"] != "built":
        print(json.dumps(payload, ensure_ascii=False, indent=2) if args.format == "json" else _format_markdown(payload))
        return 1

    if args.format == "json":
        print(json.dumps(payload, ensure_ascii=False, indent=2))
    else:
        print(_format_markdown(payload))
    return 0


def build_source_arc_map(
    *,
    repo_root: Path,
    db_path: Path,
    book_id: str,
    model_client: JsonModelClient | None = None,
) -> dict[str, Any]:
    db = NovelAgentDB(db_path)
    service = SourceArcMappingService(repo_root=repo_root, model_client=model_client)
    with db.connect() as conn:
        db.init_schema(conn)
        summaries = service.load_chapter_plot_summaries(conn, book_id=book_id)
        if not summaries:
            return {
                "status": "skipped",
                "reason": "no_chapter_summaries",
                "book_id": book_id,
                "db_path": db_path.as_posix(),
            }
        if model_client is None:
            raise RuntimeError("SourceArcMap generation requires --use-model and an available model")
        source_arc_map = service.build_from_chapters(conn, book_id=book_id)
        json_path, markdown_path = service.ensure_paths(book_id)
    return {
        "status": "built",
        "book_id": book_id,
        "db_path": db_path.as_posix(),
        "source_summary_count": source_arc_map.source_summary_count,
        "used_compression": source_arc_map.used_compression,
        "arc_count": len(source_arc_map.arcs),
        "json_path": json_path.as_posix(),
        "markdown_path": markdown_path.as_posix(),
    }


def _resolve_task_db_path(*, repo_root: Path, task_id: str, db_path: str | None) -> Path:
    if db_path:
        return Path(db_path).expanduser().resolve()
    return (repo_root / ".indexes" / f"{task_id}.db").resolve()


def _format_markdown(payload: dict[str, Any]) -> str:
    if payload.get("status") != "built":
        return "\n".join(
            [
                f"SourceArcMap 未生成：{payload.get('book_id', '')}",
                f"- status: {payload.get('status', '')}",
                f"- reason: {payload.get('reason', '')}",
                f"- db_path: {payload.get('db_path', '')}",
            ]
        )
    return "\n".join(
        [
            f"SourceArcMap 已生成：{payload.get('book_id', '')}",
            f"- source_summary_count: {payload.get('source_summary_count', 0)}",
            f"- used_compression: {payload.get('used_compression', False)}",
            f"- arc_count: {payload.get('arc_count', 0)}",
            f"- json_path: {payload.get('json_path', '')}",
            f"- markdown_path: {payload.get('markdown_path', '')}",
        ]
    )


if __name__ == "__main__":
    raise SystemExit(main())

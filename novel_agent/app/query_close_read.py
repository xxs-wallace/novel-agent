from __future__ import annotations

import argparse
import json
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .bootstrap import resolve_repo_root
from .repos.assets_repo import AssetsRepo
from .repos.chapters_repo import ChaptersRepo
from .repos.character_profiles_repo import CharacterProfilesRepo
from .repos.db import NovelAgentDB


QUERY_TYPES = ("character", "summary", "outline", "source_arc")
SUMMARY_SCOPES = ("all", "document", "total")


@dataclass(frozen=True, slots=True)
class CloseReadQueryResult:
    payload: dict[str, Any]
    rendered: str


class CloseReadQueryService:
    """Loads close-read outputs from the task database and memory artifacts."""

    def __init__(self, *, repo_root: Path) -> None:
        self.repo_root = repo_root.expanduser().resolve()

    def query(
        self,
        *,
        task_id: str,
        query_type: str,
        db_path: str | Path | None = None,
        character_name: str = "",
        document_title_index: int | None = None,
        doc_id: int | None = None,
        summary_scope: str = "all",
        output_format: str = "markdown",
    ) -> CloseReadQueryResult:
        if query_type not in QUERY_TYPES:
            raise ValueError(f"unsupported close-read query type: {query_type}")
        if summary_scope not in SUMMARY_SCOPES:
            raise ValueError(f"unsupported summary scope: {summary_scope}")
        resolved_db_path = _resolve_task_db_path(
            repo_root=self.repo_root,
            task_id=task_id,
            db_path=str(db_path) if db_path is not None else None,
        )
        if not resolved_db_path.exists():
            raise FileNotFoundError(f"close-read sqlite not found: {resolved_db_path}")

        db = NovelAgentDB(resolved_db_path)
        with db.connect() as conn:
            if query_type == "character":
                payload = _load_character_payload(conn, book_id=task_id, character_name=character_name)
            elif query_type == "summary":
                payload = _load_summary_payload(
                    conn,
                    book_id=task_id,
                    document_title_index=document_title_index,
                    doc_id=doc_id,
                    summary_scope=summary_scope,
                )
            elif query_type == "outline":
                payload = _load_outline_payload(conn, repo_root=self.repo_root, book_id=task_id)
            else:
                payload = _load_source_arc_payload(repo_root=self.repo_root, book_id=task_id)

        if output_format == "json":
            rendered = json.dumps(payload, ensure_ascii=False, indent=2)
        elif output_format == "markdown":
            rendered = _format_markdown(payload)
        else:
            raise ValueError(f"unsupported close-read output format: {output_format}")
        return CloseReadQueryResult(payload=payload, rendered=rendered)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Query close-read outputs for a novel task")
    parser.add_argument("task_id", help="Task/book id, usually the slug used by the pipeline")
    parser.add_argument("query_type", choices=QUERY_TYPES, help="Output type to print")
    parser.add_argument("--repo-root", type=str, default=None)
    parser.add_argument("--db", type=str, default=None, help="Override sqlite database path")
    parser.add_argument("--character-name", type=str, default="", help="Optional exact character name filter")
    parser.add_argument("--document-title-index", type=int, default=None, help="Only print summary for this document title index")
    parser.add_argument("--doc-id", type=int, default=None, help="Only print summary for the chapter containing this source doc id")
    parser.add_argument("--summary-scope", choices=SUMMARY_SCOPES, default="all", help="Summary view to print")
    parser.add_argument("--format", choices=("markdown", "json"), default="markdown")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    repo_root = resolve_repo_root(args.repo_root)
    service = CloseReadQueryService(repo_root=repo_root)
    try:
        result = service.query(
            task_id=args.task_id,
            query_type=args.query_type,
            db_path=args.db,
            character_name=args.character_name,
            document_title_index=args.document_title_index,
            doc_id=args.doc_id,
            summary_scope=args.summary_scope,
            output_format=args.format,
        )
    except FileNotFoundError as exc:
        print(str(exc), file=sys.stderr)
        return 1
    print(result.rendered)
    return 0


def _resolve_task_db_path(*, repo_root: Path, task_id: str, db_path: str | None) -> Path:
    if db_path:
        return Path(db_path).expanduser().resolve()
    return (repo_root / ".indexes" / f"{task_id}.db").resolve()


def _load_character_payload(conn, *, book_id: str, character_name: str = "") -> dict[str, Any]:
    repo = CharacterProfilesRepo()
    rows = (
        repo.list_by_names(conn, book_id=book_id, names=[character_name.strip()])
        if character_name.strip()
        else repo.list_by_book(conn, book_id=book_id)
    )
    return {
        "type": "character",
        "book_id": book_id,
        "characters": [_character_row_to_dict(row) for row in rows],
    }


def _load_summary_payload(
    conn,
    *,
    book_id: str,
    document_title_index: int | None = None,
    doc_id: int | None = None,
    summary_scope: str = "all",
) -> dict[str, Any]:
    rows = ChaptersRepo().list_by_book(conn, book_id=book_id)
    chapters = [_chapter_row_to_dict(row) for row in rows]
    if summary_scope == "total":
        return _build_total_summary_payload(book_id=book_id, chapters=chapters)
    if document_title_index is not None:
        chapters = [chapter for chapter in chapters if int(chapter["document_title_index"]) == int(document_title_index)]
        summary_scope = "document"
    if doc_id is not None:
        chapters = [
            chapter
            for chapter in chapters
            if int(chapter["source_doc_start_id"]) <= int(doc_id) <= int(chapter["source_doc_end_id"])
        ]
        summary_scope = "document"
    return {
        "type": "summary",
        "book_id": book_id,
        "scope": summary_scope,
        "document_title_index": document_title_index,
        "doc_id": doc_id,
        "chapters": chapters,
    }


def _chapter_row_to_dict(row) -> dict[str, Any]:
    return {
        "document_title_index": int(row["document_title_index"]),
        "chapter_title": str(row["chapter_title"]),
        "source_doc_start_id": int(row["source_doc_start_id"] or 0),
        "source_doc_end_id": int(row["source_doc_end_id"] or 0),
        "source_doc_count": int(row["source_doc_count"] or 0),
        "source_total_chars": int(row["source_total_chars"] or 0),
        "summary_short": str(row["summary_short"] or ""),
        "summary_md": str(row["summary_md"] or ""),
        "summary_status": _row_text(row, "summary_status", "provisional"),
        "summary_evidence_window": _row_text(row, "summary_evidence_window"),
        "summary_target_range": _row_text(row, "summary_target_range"),
        "importance_score": int(row["importance_score"] or 0),
        "importance_reason": str(row["importance_reason"] or ""),
        "outline_status": _row_text(row, "outline_status", "provisional"),
        "outline_evidence_window": _row_text(row, "outline_evidence_window"),
        "outline_target_range": _row_text(row, "outline_target_range"),
    }


def _build_total_summary_payload(*, book_id: str, chapters: list[dict[str, Any]]) -> dict[str, Any]:
    title_indexes = [int(chapter["document_title_index"]) for chapter in chapters]
    doc_starts = [int(chapter["source_doc_start_id"]) for chapter in chapters if int(chapter["source_doc_start_id"]) > 0]
    doc_ends = [int(chapter["source_doc_end_id"]) for chapter in chapters if int(chapter["source_doc_end_id"]) > 0]
    return {
        "type": "summary_total",
        "book_id": book_id,
        "chapter_count": len(chapters),
        "document_title_index_start": min(title_indexes) if title_indexes else None,
        "document_title_index_end": max(title_indexes) if title_indexes else None,
        "source_doc_start_id": min(doc_starts) if doc_starts else None,
        "source_doc_end_id": max(doc_ends) if doc_ends else None,
        "source_total_chars": sum(int(chapter["source_total_chars"]) for chapter in chapters),
        "importance_score_total": sum(int(chapter["importance_score"]) for chapter in chapters),
        "chapters": chapters,
    }


def _load_outline_payload(conn, *, repo_root: Path, book_id: str) -> dict[str, Any]:
    path = _resolve_outline_path(conn, repo_root=repo_root, book_id=book_id)
    content = path.read_text(encoding="utf-8", errors="replace") if path is not None and path.exists() else ""
    return {
        "type": "outline",
        "book_id": book_id,
        "path": str(path) if path is not None else "",
        "content": content,
    }


def _load_source_arc_payload(*, repo_root: Path, book_id: str) -> dict[str, Any]:
    json_path, markdown_path = _source_arc_paths(repo_root=repo_root, book_id=book_id)
    payload: dict[str, Any] = {}
    if json_path.exists():
        try:
            raw = json.loads(json_path.read_text(encoding="utf-8", errors="replace"))
        except json.JSONDecodeError:
            raw = {}
        payload = raw if isinstance(raw, dict) else {}
    markdown = markdown_path.read_text(encoding="utf-8", errors="replace") if markdown_path.exists() else ""
    return {
        "type": "source_arc",
        "book_id": book_id,
        "json_path": str(json_path),
        "markdown_path": str(markdown_path),
        "exists": bool(payload or markdown),
        "source_arc_map": payload,
        "markdown": markdown,
    }


def _source_arc_paths(*, repo_root: Path, book_id: str) -> tuple[Path, Path]:
    arcs_dir = repo_root / ".memory" / "arcs"
    return (
        arcs_dir / f"{book_id}.source_arc_map.json",
        arcs_dir / f"{book_id}.source_arc_map.md",
    )


def _resolve_outline_path(conn, *, repo_root: Path, book_id: str) -> Path | None:
    assets = AssetsRepo().get(conn, book_id=book_id)
    if assets is not None:
        raw_path = str(assets["outline_markdown_path"] or "").strip()
        if raw_path:
            path = Path(raw_path).expanduser()
            return path if path.is_absolute() else (repo_root / path).resolve()
    candidates = [
        repo_root / ".memory" / "outlines" / f"{book_id}.outline.md",
        repo_root / "memory" / "outlines" / f"{book_id}.outline.md",
    ]
    return next((path for path in candidates if path.exists()), candidates[0])


def _character_row_to_dict(row) -> dict[str, Any]:
    return {
        "canonical_name": str(row["canonical_name"]),
        "aliases": _json_list(row["aliases_json"]),
        "profile_summary_md": str(row["profile_summary_md"] or ""),
        "speaking_character_status": str(row["speaking_character_status"] or ""),
        "personhood_evidence_summary": str(row["personhood_evidence_summary"] or ""),
        "evidence_level": str(row["evidence_level"] or ""),
        "recent_activity": _json_list(row["recent_activity_json"]),
        "relationships": _json_list(row["relationships_json"]),
        "chapter_indexes": _json_list(row["chapter_indexes_json"]),
        "mentioned_doc_ids": _json_list(row["mentioned_doc_ids_json"]),
        "speaking_doc_ids": _json_list(row["speaking_doc_ids_json"]),
        "first_seen_doc_id": row["first_seen_doc_id"],
        "last_seen_doc_id": row["last_seen_doc_id"],
        "first_seen_title_index": row["first_seen_title_index"],
        "last_seen_title_index": row["last_seen_title_index"],
        "importance_score": int(row["importance_score"] or 0),
        "profile_version": int(row["profile_version"] or 1),
        "updated_at": str(row["updated_at"] or ""),
    }


def _json_list(value: object) -> list[Any]:
    try:
        loaded = json.loads(str(value or "[]"))
    except json.JSONDecodeError:
        return []
    return loaded if isinstance(loaded, list) else []


def _format_markdown(payload: dict[str, Any]) -> str:
    payload_type = payload.get("type")
    if payload_type == "character":
        return _format_character_markdown(payload)
    if payload_type == "summary":
        return _format_summary_markdown(payload)
    if payload_type == "summary_total":
        return _format_total_summary_markdown(payload)
    if payload_type == "outline":
        content = str(payload.get("content") or "").rstrip()
        if content:
            return content
        return f"# 大纲\n\n未找到大纲文件：{payload.get('path', '')}".rstrip()
    if payload_type == "source_arc":
        return _format_source_arc_markdown(payload)
    return json.dumps(payload, ensure_ascii=False, indent=2)


def _format_character_markdown(payload: dict[str, Any]) -> str:
    lines = [f"# 人物档案：{payload.get('book_id', '')}", ""]
    characters = [item for item in payload.get("characters", []) if isinstance(item, dict)]
    if not characters:
        return "\n".join([*lines, "未找到人物档案。"])
    for character in characters:
        lines.append(f"## {character.get('canonical_name', '')}")
        aliases = character.get("aliases") or []
        if aliases:
            lines.append(f"- aliases: {', '.join(str(item) for item in aliases)}")
        lines.append(f"- evidence_level: {character.get('evidence_level', '')}")
        lines.append(f"- importance_score: {character.get('importance_score', 0)}")
        lines.append(f"- doc_range: {character.get('first_seen_doc_id')} - {character.get('last_seen_doc_id')}")
        summary = str(character.get("profile_summary_md") or "").strip()
        if summary:
            lines.extend(["", summary])
        recent_activity = character.get("recent_activity") or []
        if recent_activity:
            lines.extend(["", "### Recent Activity"])
            lines.extend(f"- {item}" for item in recent_activity)
        relationships = character.get("relationships") or []
        if relationships:
            lines.extend(["", "### Relationships"])
            lines.append(json.dumps(relationships, ensure_ascii=False, indent=2))
        lines.append("")
    return "\n".join(lines).rstrip()


def _format_summary_markdown(payload: dict[str, Any]) -> str:
    scope = str(payload.get("scope") or "all")
    title = "剧情概括"
    if scope == "document":
        selector = payload.get("document_title_index") or payload.get("doc_id") or ""
        title = f"剧情概括：document {selector}".rstrip()
    lines = [f"# {title}：{payload.get('book_id', '')}", ""]
    chapters = [item for item in payload.get("chapters", []) if isinstance(item, dict)]
    if not chapters:
        return "\n".join([*lines, "未找到匹配的章节摘要。"])
    for chapter in chapters:
        title_index = chapter.get("document_title_index", "")
        title = chapter.get("chapter_title", "")
        lines.append(f"## [{title_index}] {title}")
        start_doc = chapter.get("source_doc_start_id")
        end_doc = chapter.get("source_doc_end_id")
        if start_doc or end_doc:
            lines.append(f"- source_doc_range: {start_doc}-{end_doc}")
        short = str(chapter.get("summary_short") or "").strip()
        if short:
            lines.extend(["", f"> {short}"])
        summary_md = str(chapter.get("summary_md") or "").strip()
        if summary_md:
            lines.extend(["", summary_md])
        reason = str(chapter.get("importance_reason") or "").strip()
        if reason:
            lines.extend(["", f"- importance_score: {chapter.get('importance_score', 0)}"])
            lines.append(f"- importance_reason: {reason}")
        lines.append("")
    return "\n".join(lines).rstrip()


def _format_total_summary_markdown(payload: dict[str, Any]) -> str:
    lines = [
        f"# 当前精读总览：{payload.get('book_id', '')}",
        "",
        f"- chapter_count: {payload.get('chapter_count', 0)}",
        f"- document_title_index_range: {payload.get('document_title_index_start')}-{payload.get('document_title_index_end')}",
        f"- source_doc_range: {payload.get('source_doc_start_id')}-{payload.get('source_doc_end_id')}",
        f"- source_total_chars: {payload.get('source_total_chars', 0)}",
        "",
    ]
    chapters = [item for item in payload.get("chapters", []) if isinstance(item, dict)]
    if not chapters:
        return "\n".join([*lines, "未找到章节摘要。"]).rstrip()
    lines.append("## 已精读章节摘要")
    for chapter in chapters:
        summary = str(chapter.get("summary_short") or chapter.get("summary_md") or "").strip()
        if not summary:
            continue
        lines.append(f"- [{chapter.get('document_title_index', '')}] {chapter.get('chapter_title', '')}: {summary}")
    return "\n".join(lines).rstrip()


def _format_source_arc_markdown(payload: dict[str, Any]) -> str:
    markdown = str(payload.get("markdown") or "").strip()
    if markdown:
        return markdown
    source_arc_map = payload.get("source_arc_map")
    if not isinstance(source_arc_map, dict) or not source_arc_map:
        return (
            f"# Source Arc Map: {payload.get('book_id', '')}\n\n"
            f"未找到 SourceArcMap：{payload.get('json_path', '')}"
        ).rstrip()
    lines = [
        f"# Source Arc Map: {source_arc_map.get('book_id') or payload.get('book_id', '')}",
        "",
        f"- generated_at: {source_arc_map.get('generated_at', '')}",
        f"- source_summary_count: {source_arc_map.get('source_summary_count', 0)}",
        f"- used_compression: {bool(source_arc_map.get('used_compression'))}",
        f"- plot_summary_units: {len(source_arc_map.get('plot_summary_units') or [])}",
        f"- arcs: {len(source_arc_map.get('arcs') or [])}",
    ]
    for arc in source_arc_map.get("arcs") or []:
        if not isinstance(arc, dict):
            continue
        lines.extend(
            [
                "",
                f"## {arc.get('source_arc_id', '')} {arc.get('source_arc_title', '')}".rstrip(),
                "",
                f"- range: {arc.get('start_document_title_index', '')}-{arc.get('end_document_title_index', '')}",
                f"- role: {arc.get('source_arc_role', '')}",
                f"- pacing_notes: {arc.get('pacing_notes', '')}",
            ]
        )
        core_events = [str(item) for item in (arc.get("core_events") or []) if str(item).strip()]
        if core_events:
            lines.extend(["", "### Core Events"])
            lines.extend(f"- {item}" for item in core_events)
    return "\n".join(lines).rstrip()


def _row_text(row, column: str, default: str = "") -> str:
    try:
        value = row[column]
    except (IndexError, KeyError):
        return default
    return str(value or default).strip()


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())

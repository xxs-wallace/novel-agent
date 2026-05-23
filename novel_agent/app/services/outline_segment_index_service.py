from __future__ import annotations

import json
import re
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping

from ..constants import DEFAULT_MEMORY_ROOT
from ..repos.chapters_repo import ChaptersRepo


DEFAULT_OUTLINE_ROOT_GROUP_SIZE = 16
DEFAULT_OUTLINE_ROOT_GROUP_CHARS = 120_000


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _text(value: object) -> str:
    return str(value or "").strip()


def _safe_excerpt(text: str, *, limit: int) -> str:
    normalized = re.sub(r"\s+", " ", _text(text))
    if len(normalized) <= limit:
        return normalized
    return normalized[:limit].rstrip() + "..."


def _json_dict(value: object) -> dict[str, Any]:
    if isinstance(value, Mapping):
        return dict(value)
    try:
        payload = json.loads(str(value or "{}"))
    except json.JSONDecodeError:
        return {}
    return dict(payload) if isinstance(payload, Mapping) else {}


def _int_list(value: object) -> list[int]:
    if not isinstance(value, list):
        return []
    result: set[int] = set()
    for item in value:
        try:
            number = int(item)
        except (TypeError, ValueError):
            continue
        if number > 0:
            result.add(number)
    return sorted(result)


def _range_text(values: list[int]) -> str:
    cleaned = sorted({int(value) for value in values if int(value) > 0})
    if not cleaned:
        return ""
    return str(cleaned[0]) if len(cleaned) == 1 else f"{cleaned[0]}-{cleaned[-1]}"


def _combined_status(statuses: list[str]) -> str:
    normalized = {_text(status).lower() or "provisional" for status in statuses}
    normalized = {status if status in {"provisional", "committed"} else "provisional" for status in normalized}
    if not normalized:
        return "provisional"
    if len(normalized) == 1:
        return next(iter(normalized))
    return "mixed"


class OutlineSegmentIndexService:
    """Builds outline_segment and outline_root index artifacts from chapters."""

    def __init__(
        self,
        *,
        repo_root: Path,
        chapters_repo: ChaptersRepo | None = None,
        root_group_size: int = DEFAULT_OUTLINE_ROOT_GROUP_SIZE,
        root_group_chars: int = DEFAULT_OUTLINE_ROOT_GROUP_CHARS,
    ) -> None:
        self.repo_root = repo_root
        self.chapters_repo = chapters_repo or ChaptersRepo()
        self.root_group_size = max(1, int(root_group_size or 1))
        self.root_group_chars = max(1, int(root_group_chars or 1))

    def artifact_path(self, book_id: str) -> Path:
        directory = self.repo_root / DEFAULT_MEMORY_ROOT / "outlines"
        directory.mkdir(parents=True, exist_ok=True)
        return directory / f"{book_id}.outline_segments.json"

    def refresh(self, conn: sqlite3.Connection, *, book_id: str) -> Path:
        payload = self.build_payload(conn, book_id=book_id)
        path = self.artifact_path(book_id)
        path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        return path

    def build_payload(self, conn: sqlite3.Connection, *, book_id: str) -> dict[str, Any]:
        segments = self._segments(conn, book_id=book_id)
        return {
            "book_id": book_id,
            "updated_at": _utc_now(),
            "segment_source": "chapters.outline_update.outline_segment",
            "segments": segments,
            "roots": self._roots(book_id=book_id, segments=segments),
        }

    def _segments(self, conn: sqlite3.Connection, *, book_id: str) -> list[dict[str, Any]]:
        segments: list[dict[str, Any]] = []
        for row in self.chapters_repo.list_by_book(conn, book_id=book_id):
            outline = _json_dict(row["outline_update_json"])
            summary = _text(outline.get("outline_segment"))
            if not summary:
                continue
            title_index = int(row["document_title_index"] or 0)
            doc_ids = _int_list(outline.get("source_doc_ids")) or self._source_doc_ids_from_row(row)
            title_indexes = _int_list(outline.get("source_title_indexes")) or ([title_index] if title_index else [])
            source_doc_range = _text(outline.get("source_doc_range")) or _range_text(doc_ids)
            segment_id = _text(outline.get("outline_segment_id")) or self._outline_segment_id(
                document_title_index=title_index,
                source_doc_range=source_doc_range,
            )
            segments.append(
                {
                    "outline_segment_id": segment_id,
                    "summary": summary,
                    "chapter_line": _text(outline.get("chapter_line")),
                    "source_title_indexes": title_indexes,
                    "source_doc_ids": doc_ids,
                    "source_doc_start_id": doc_ids[0] if doc_ids else int(row["source_doc_start_id"] or 0),
                    "source_doc_end_id": doc_ids[-1] if doc_ids else int(row["source_doc_end_id"] or 0),
                    "source_doc_range": source_doc_range,
                    "source_total_chars": int(row["source_total_chars"] or 0),
                    "status": _text(outline.get("status")) or str(row["outline_status"] or "provisional"),
                    "updated_at": str(row["updated_at"] or ""),
                    "metadata": {
                        "chapter_id": int(row["chapter_id"] or 0),
                        "document_title_index": title_index,
                        "chapter_title": str(row["chapter_title"] or ""),
                    },
                }
            )
        return segments

    def _roots(self, *, book_id: str, segments: list[dict[str, Any]]) -> list[dict[str, Any]]:
        groups: list[list[dict[str, Any]]] = []
        current: list[dict[str, Any]] = []
        current_chars = 0
        for segment in segments:
            current.append(segment)
            current_chars += int(segment.get("source_total_chars") or 0)
            if len(current) >= self.root_group_size or current_chars >= self.root_group_chars:
                groups.append(current)
                current = []
                current_chars = 0
        if current:
            groups.append(current)

        roots: list[dict[str, Any]] = []
        for index, group in enumerate(groups, start=1):
            doc_ids = sorted({doc_id for segment in group for doc_id in _int_list(segment.get("source_doc_ids"))})
            title_indexes = sorted({
                title_index
                for segment in group
                for title_index in _int_list(segment.get("source_title_indexes"))
            })
            segment_ids = [_text(segment.get("outline_segment_id")) for segment in group if _text(segment.get("outline_segment_id"))]
            roots.append(
                {
                    "outline_root_id": f"{book_id}:outline-root-{index:04d}",
                    "summary": _safe_excerpt("；".join(_text(segment.get("summary")) for segment in group), limit=700),
                    "outline_segment_ids": segment_ids,
                    "source_title_indexes": title_indexes,
                    "source_doc_ids": doc_ids,
                    "source_doc_range": _range_text(doc_ids),
                    "status": _combined_status([_text(segment.get("status")) for segment in group]),
                }
            )
        return roots

    @staticmethod
    def _source_doc_ids_from_row(row: sqlite3.Row) -> list[int]:
        start = int(row["source_doc_start_id"] or 0)
        end = int(row["source_doc_end_id"] or 0)
        if start <= 0 or end <= 0:
            return []
        if end < start:
            return [start]
        if end - start > 512:
            return [start, end]
        return list(range(start, end + 1))

    @staticmethod
    def _outline_segment_id(*, document_title_index: int, source_doc_range: str = "") -> str:
        source_suffix = re.sub(r"[^\w\u4e00-\u9fff]+", "-", str(source_doc_range or "")).strip("-").lower()
        if source_suffix:
            return f"outline-segment:chapter-{document_title_index}:docs-{source_suffix}"
        return f"outline-segment:chapter-{document_title_index}"

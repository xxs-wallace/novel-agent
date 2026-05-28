from __future__ import annotations

import json
import re
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping

from ..constants import DEFAULT_MEMORY_ROOT
from ..prompts.outline_root_summary_prompt import build_outline_root_summary_prompt
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
        model_client: Any | None = None,
        chapters_repo: ChaptersRepo | None = None,
        root_group_size: int = DEFAULT_OUTLINE_ROOT_GROUP_SIZE,
        root_group_chars: int = DEFAULT_OUTLINE_ROOT_GROUP_CHARS,
    ) -> None:
        self.repo_root = repo_root
        self.model_client = model_client
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
        self._write_outline_markdown_projection(book_id=book_id, payload=payload)
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
            root_id = f"{book_id}:outline-root-{index:04d}"
            root_summary = self._compress_root_summary(
                book_id=book_id,
                outline_root_id=root_id,
                group=group,
                source_doc_range=_range_text(doc_ids),
                source_title_indexes=title_indexes,
            )
            roots.append(
                {
                    "outline_root_id": root_id,
                    "summary": root_summary["root_summary"],
                    "compression_notes": root_summary.get("compression_notes", ""),
                    "outline_segment_ids": segment_ids,
                    "source_title_indexes": title_indexes,
                    "source_doc_ids": doc_ids,
                    "source_doc_range": _range_text(doc_ids),
                    "status": _combined_status([_text(segment.get("status")) for segment in group]),
                }
            )
        return roots

    def _compress_root_summary(
        self,
        *,
        book_id: str,
        outline_root_id: str,
        group: list[dict[str, Any]],
        source_doc_range: str,
        source_title_indexes: list[int],
    ) -> dict[str, str]:
        if not group:
            return {"root_summary": "", "compression_notes": ""}
        if self.model_client is None:
            raise RuntimeError("OutlineSegmentIndexService requires an available model_client for root summary compression")
        prompt_input = {
            "book_id": book_id,
            "outline_root_id": outline_root_id,
            "source_doc_range": source_doc_range,
            "source_title_indexes": source_title_indexes,
            "segments": group,
        }
        fallback = self._fallback_root_summary(group)
        system_prompt, user_prompt = build_outline_root_summary_prompt(prompt_input)
        payload, _raw = self.model_client.generate_json(
            system_prompt=system_prompt,
            user_prompt=user_prompt,
            fallback_factory=lambda: fallback,
            use_fallback_on_error=bool(getattr(getattr(self.model_client, "settings", None), "dry_run", False)),
        )
        if not isinstance(payload, Mapping):
            raise RuntimeError("Outline root summary model returned a non-object JSON payload")
        root_summary = _text(payload.get("root_summary"))
        if not root_summary:
            raise RuntimeError("Outline root summary model returned empty root_summary")
        return {
            "root_summary": _safe_excerpt(root_summary, limit=900),
            "compression_notes": _text(payload.get("compression_notes")),
        }

    @staticmethod
    def _fallback_root_summary(group: list[dict[str, Any]]) -> dict[str, str]:
        joined = "；".join(_text(segment.get("summary")) for segment in group if _text(segment.get("summary")))
        return {
            "root_summary": _safe_excerpt(joined, limit=700),
            "compression_notes": "dry_run_fallback",
        }

    def _write_outline_markdown_projection(self, *, book_id: str, payload: dict[str, Any]) -> Path:
        path = self.repo_root / DEFAULT_MEMORY_ROOT / "outlines" / f"{book_id}.outline.md"
        path.parent.mkdir(parents=True, exist_ok=True)
        roots = [item for item in payload.get("roots", []) if isinstance(item, Mapping)]
        segments = [item for item in payload.get("segments", []) if isinstance(item, Mapping)]
        segment_by_id = {
            _text(segment.get("outline_segment_id")): segment
            for segment in segments
            if _text(segment.get("outline_segment_id"))
        }
        lines = [
            "# 故事大纲",
            "",
            "## 连续剧情概览",
        ]
        if not roots:
            lines.append("- 暂无可用 outline root。")
        for root in roots:
            root_id = _text(root.get("outline_root_id"))
            source_range = _text(root.get("source_doc_range"))
            summary = _text(root.get("summary"))
            title_range = _range_text(_int_list(root.get("source_title_indexes")))
            heading_bits = [root_id or "outline-root"]
            if title_range:
                heading_bits.append(f"chapters {title_range}")
            if source_range:
                heading_bits.append(f"docs {source_range}")
            lines.extend(
                [
                    "",
                    f"### {' | '.join(heading_bits)}",
                    "",
                    summary or "暂无摘要。",
                ]
            )
        lines.extend(["", "## 分段索引"])
        if not segments:
            lines.append("- 暂无可用 outline segment。")
        for root in roots:
            root_id = _text(root.get("outline_root_id"))
            segment_ids = [str(item) for item in (root.get("outline_segment_ids") or []) if str(item)]
            if root_id:
                lines.extend(["", f"### {root_id}", ""])
            for segment_id in segment_ids:
                segment = segment_by_id.get(segment_id)
                if not segment:
                    continue
                chapter_line = _text(segment.get("chapter_line"))
                summary = _text(segment.get("summary"))
                source_range = _text(segment.get("source_doc_range"))
                title_range = _range_text(_int_list(segment.get("source_title_indexes")))
                source_hint = []
                if title_range:
                    source_hint.append(f"chapters {title_range}")
                if source_range:
                    source_hint.append(f"docs {source_range}")
                hint = f" ({'; '.join(source_hint)})" if source_hint else ""
                lines.append(f"- [{segment_id}]{hint} {chapter_line or summary}")
                if chapter_line and summary and summary != chapter_line:
                    lines.append(f"  {summary}")
        path.write_text("\n".join(lines).rstrip() + "\n", encoding="utf-8")
        return path

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

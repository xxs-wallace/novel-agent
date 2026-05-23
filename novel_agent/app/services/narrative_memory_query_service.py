from __future__ import annotations

import json
import re
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping, Sequence

from ..constants import DEFAULT_MEMORY_ROOT
from ..repos.chapters_repo import ChaptersRepo
from ..repos.documents_repo import DocumentsRepo
from ..repos.narrative_memory_pages_repo import NarrativeMemoryPagesRepo
from ..schemas.narrative_memory_schema import (
    MemoryEvidenceBundle,
    MemoryQueryBudget,
    MemoryQueryPathItem,
    MemoryQueryState,
    NarrativeMemoryPage,
)


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
    if isinstance(value, dict):
        return dict(value)
    try:
        payload = json.loads(str(value or "{}"))
    except json.JSONDecodeError:
        return {}
    return dict(payload) if isinstance(payload, dict) else {}


def _json_list(value: object) -> list[Any]:
    if isinstance(value, list):
        return value
    try:
        payload = json.loads(str(value or "[]"))
    except json.JSONDecodeError:
        return []
    return payload if isinstance(payload, list) else []


def _int_list(value: object) -> list[int]:
    items = value if isinstance(value, list) else []
    result: set[int] = set()
    for item in items:
        try:
            result.add(int(item))
        except (TypeError, ValueError):
            continue
    return sorted(result)


def _range_text(values: Sequence[int]) -> str:
    clean = sorted({int(value) for value in values if int(value) > 0})
    if not clean:
        return ""
    return str(clean[0]) if len(clean) == 1 else f"{clean[0]}-{clean[-1]}"


def _range_to_ints(value: object) -> list[int]:
    text = _text(value)
    if not text:
        return []
    if "-" not in text:
        try:
            return [int(text)]
        except ValueError:
            return []
    left, right = text.split("-", 1)
    try:
        start = int(left)
        end = int(right)
    except ValueError:
        return []
    if end < start:
        return [start]
    if end - start > 512:
        return [start, end]
    return list(range(start, end + 1))


def _combined_status(statuses: Sequence[str]) -> str:
    normalized = {_text(status).lower() or "provisional" for status in statuses}
    normalized = {status if status in {"provisional", "committed"} else "provisional" for status in normalized}
    if not normalized:
        return "provisional"
    if len(normalized) == 1:
        return next(iter(normalized))
    return "mixed"


class NarrativeMemoryQueryService:
    """BTree-like facade over prefix-authorized narrative memory.

    The service reads only the connected prefix DB and prefix `.memory` event
    summary artifacts. It never opens reference-only benchmark files.
    """

    LEVEL_ORDER = ("outline_root", "outline_segment", "chapter", "document")
    LEGACY_LEVEL_ORDER = ("event_summary", "event", "chapter", "document")

    def __init__(
        self,
        *,
        repo_root: Path,
        pages_repo: NarrativeMemoryPagesRepo | None = None,
        chapters_repo: ChaptersRepo | None = None,
        documents_repo: DocumentsRepo | None = None,
    ) -> None:
        self.repo_root = repo_root
        self.pages_repo = pages_repo or NarrativeMemoryPagesRepo()
        self.chapters_repo = chapters_repo or ChaptersRepo()
        self.documents_repo = documents_repo or DocumentsRepo()

    def root_scan(
        self,
        conn: sqlite3.Connection,
        *,
        book_id: str,
        query: str,
        budget: MemoryQueryBudget | None = None,
    ) -> MemoryQueryState:
        budget = budget or MemoryQueryBudget()
        root_pages = self._outline_root_pages(conn, book_id=book_id)
        if root_pages:
            root_level = "outline_root"
            fallback = False
        else:
            root_level = "event_summary"
            root_pages = self._event_summary_pages(conn, book_id=book_id)
            fallback = not bool(self._event_summary_artifact(book_id).exists())
        candidates = self._rank_pages(
            root_pages,
            query=query,
            limit=budget.max_root_candidates,
        )
        if not candidates:
            root_level = "event_summary"
            candidates = self._rank_pages(
                self._synthetic_event_summary_pages(conn, book_id=book_id),
                query=query,
                limit=budget.max_root_candidates,
            )
            fallback = True
        candidate_dicts = [self._candidate_dict(page, budget=budget) for page in candidates]
        trace = [
            {
                "operation": "root_scan",
                "level": root_level,
                "query": query,
                "candidate_ids": [item["id"] for item in candidate_dicts],
                "budget": budget.to_dict(),
                "source_scope": "prefix_memory_only",
                "fallback": fallback,
            }
        ]
        return MemoryQueryState(
            original_query=query,
            current_level=root_level,
            current_candidates=candidate_dicts,
            budget=budget,
            budget_used={"candidate_count": len(candidate_dicts)},
            trace=trace,
        )

    def root_map(
        self,
        conn: sqlite3.Connection,
        *,
        book_id: str,
        budget: MemoryQueryBudget | None = None,
    ) -> list[dict[str, Any]]:
        """Return the event-summary map without semantic ranking.

        This is the lightweight table-of-contents entry point for agents that
        need to plan retrieval before asking for specific story detail.
        """
        budget = budget or MemoryQueryBudget(max_root_candidates=128)
        pages = self._outline_root_pages(conn, book_id=book_id)
        if not pages:
            pages = self._event_summary_pages(conn, book_id=book_id) or self._synthetic_event_summary_pages(conn, book_id=book_id)
        return [self._candidate_dict(page, budget=budget) for page in pages[: budget.max_root_candidates]]

    def drill_down(
        self,
        conn: sqlite3.Connection,
        *,
        book_id: str,
        state: MemoryQueryState,
        selected_ids: Sequence[str],
        query_suffix: str = "",
        selection_reason: str = "",
        confidence: float = 0.0,
        need_sibling_scan: bool = False,
    ) -> MemoryQueryState:
        selected = [str(item) for item in selected_ids if str(item).strip()]
        current_level = state.current_level
        next_level = self._next_level(current_level)
        budget = state.budget
        selected_pages = self._pages_by_ids(conn, book_id=book_id, level=current_level, page_ids=selected)
        if need_sibling_scan or not selected_pages or confidence < 0.25:
            selected_pages = self._expand_with_siblings(conn, book_id=book_id, level=current_level, selected_pages=selected_pages, state=state)
        next_pages = self._children_for_pages(conn, book_id=book_id, pages=selected_pages, next_level=next_level)
        ranked_next = self._rank_pages(
            next_pages,
            query=" ".join([state.original_query, *state.query_suffix_chain, query_suffix]),
            limit=budget.max_child_candidates,
        )
        path_context = list(state.path_context)
        for page in selected_pages:
            path_context.append(
                MemoryQueryPathItem(
                    level=current_level,
                    selected_id=page.page_id,
                    summary=_safe_excerpt(page.summary, limit=360),
                    source_doc_range=page.source_doc_range,
                    source_event_range=self._source_event_range(page),
                    selection_reason=selection_reason,
                    confidence=confidence,
                    status=page.status,
                )
            )
        query_suffix_chain = list(state.query_suffix_chain)
        if _text(query_suffix):
            query_suffix_chain.append(_safe_excerpt(query_suffix, limit=180))
        trace = [
            *state.trace,
            {
                "operation": "drill_down",
                "from_level": current_level,
                "to_level": next_level,
                "selected_ids": selected,
                "expanded_selected_ids": [page.page_id for page in selected_pages],
                "candidate_ids": [page.page_id for page in ranked_next],
                "query_suffix": query_suffix,
                "selection_reason": selection_reason,
                "confidence": max(0.0, min(float(confidence or 0), 1.0)),
                "need_sibling_scan": bool(need_sibling_scan),
                "status": _combined_status([page.status for page in selected_pages + ranked_next]),
            },
        ]
        trace = trace[-budget.max_trace_items :]
        return MemoryQueryState(
            original_query=state.original_query,
            current_level=next_level,
            current_candidates=[self._candidate_dict(page, budget=budget) for page in ranked_next],
            query_suffix_chain=query_suffix_chain,
            path_context=path_context[-12:],
            budget=budget,
            budget_used={
                "candidate_count": len(ranked_next),
                "path_context_count": len(path_context),
            },
            trace=trace,
        )

    def resolve_event_ids(
        self,
        conn: sqlite3.Connection,
        *,
        book_id: str,
        event_ids: Sequence[str],
    ) -> MemoryEvidenceBundle:
        pages = self._pages_by_ids(conn, book_id=book_id, level="event", page_ids=list(event_ids))
        source_doc_ids = sorted({doc_id for page in pages for doc_id in page.source_doc_ids})
        chapter_refs = sorted({
            str(chapter)
            for page in pages
            for chapter in _int_list(page.metadata.get("source_chapter_indexes"))
        })
        return MemoryEvidenceBundle(
            evidence_items=[self._evidence_from_page(page) for page in pages],
            sources=[self._source_from_page(page) for page in pages],
            status=_combined_status([page.status for page in pages]),
            source_doc_ids=source_doc_ids,
            chapter_refs=chapter_refs,
            event_ids=[page.page_id for page in pages],
            trace=[
                {
                    "operation": "resolve_event_ids",
                    "event_ids": list(event_ids),
                    "resolved_ids": [page.page_id for page in pages],
                    "source_doc_ids": source_doc_ids,
                    "status": _combined_status([page.status for page in pages]),
                }
            ],
        )

    def resolve_chapter_refs(
        self,
        conn: sqlite3.Connection,
        *,
        book_id: str,
        chapter_refs: Sequence[str],
    ) -> MemoryEvidenceBundle:
        pages = self._pages_by_ids(conn, book_id=book_id, level="chapter", page_ids=[str(item) for item in chapter_refs])
        source_doc_ids = sorted({doc_id for page in pages for doc_id in page.source_doc_ids})
        return MemoryEvidenceBundle(
            evidence_items=[self._evidence_from_page(page) for page in pages],
            sources=[self._source_from_page(page) for page in pages],
            status=_combined_status([page.status for page in pages]),
            source_doc_ids=source_doc_ids,
            chapter_refs=[page.page_id for page in pages],
            trace=[
                {
                    "operation": "resolve_chapter_refs",
                    "chapter_refs": list(chapter_refs),
                    "resolved_refs": [page.page_id for page in pages],
                    "source_doc_ids": source_doc_ids,
                }
            ],
        )

    def resolve_outline_segment_refs(
        self,
        conn: sqlite3.Connection,
        *,
        book_id: str,
        segment_ids: Sequence[str],
    ) -> MemoryEvidenceBundle:
        pages = self._pages_by_ids(conn, book_id=book_id, level="outline_segment", page_ids=[str(item) for item in segment_ids])
        source_doc_ids = sorted({doc_id for page in pages for doc_id in page.source_doc_ids})
        chapter_refs = sorted({child for page in pages for child in page.child_refs})
        return MemoryEvidenceBundle(
            evidence_items=[self._evidence_from_page(page) for page in pages],
            sources=[self._source_from_page(page) for page in pages],
            status=_combined_status([page.status for page in pages]),
            source_doc_ids=source_doc_ids,
            chapter_refs=chapter_refs,
            trace=[
                {
                    "operation": "resolve_outline_segment_refs",
                    "segment_ids": list(segment_ids),
                    "resolved_refs": [page.page_id for page in pages],
                    "source_doc_ids": source_doc_ids,
                }
            ],
        )

    def resolve_document_refs(
        self,
        conn: sqlite3.Connection,
        *,
        book_id: str,
        doc_ids: Sequence[int],
        excerpt_budget: int,
    ) -> MemoryEvidenceBundle:
        clean_ids = sorted({int(item) for item in doc_ids if int(item) > 0})
        if not clean_ids:
            return MemoryEvidenceBundle(status="provisional")
        placeholders = ",".join("?" for _ in clean_ids)
        rows = conn.execute(
            f"""
            SELECT * FROM documents
            WHERE book_id = ? AND doc_id IN ({placeholders})
            ORDER BY doc_id
            """,
            (book_id, *clean_ids),
        ).fetchall()
        per_doc_budget = max(80, int(excerpt_budget or 80) // max(1, len(rows)))
        evidence_items = []
        sources = []
        excerpts = []
        for row in rows:
            excerpt = _safe_excerpt(str(row["content"] or ""), limit=per_doc_budget)
            item = {
                "doc_id": int(row["doc_id"]),
                "summary": excerpt,
                "source_doc_range": str(row["doc_id"]),
                "document_title_index": int(row["document_title_index"] or 0),
                "status": "provisional",
            }
            evidence_items.append(item)
            excerpts.append(
                {
                    "doc_id": int(row["doc_id"]),
                    "text": excerpt,
                    "source_start_offset": int(row["source_start_offset"] or 0),
                    "source_end_offset": int(row["source_end_offset"] or 0),
                }
            )
            sources.append(
                {
                    "type": "document",
                    "path": f"sqlite:documents:{row['doc_id']}",
                    "doc_id": int(row["doc_id"]),
                    "status": "provisional",
                }
            )
        return MemoryEvidenceBundle(
            evidence_items=evidence_items,
            sources=sources,
            status="provisional",
            source_doc_ids=[int(row["doc_id"]) for row in rows],
            excerpts=excerpts,
            trace=[
                {
                    "operation": "resolve_document_refs",
                    "doc_ids": clean_ids,
                    "resolved_doc_ids": [int(row["doc_id"]) for row in rows],
                    "excerpt_budget": int(excerpt_budget or 0),
                    "source_scope": "prefix_documents_only",
                }
            ],
        )

    def rebuild_pages(self, conn: sqlite3.Connection, *, book_id: str) -> list[NarrativeMemoryPage]:
        pages = [
            *self._document_pages(conn, book_id=book_id),
            *self._chapter_pages(conn, book_id=book_id),
            *self._outline_segment_pages(conn, book_id=book_id),
            *self._outline_root_pages(conn, book_id=book_id),
            *self._event_pages(conn, book_id=book_id),
            *self._event_summary_pages(conn, book_id=book_id),
        ]
        if any(page.page_type == "outline_segment" for page in pages) and not any(
            page.page_type == "outline_root" for page in pages
        ):
            pages.extend(self._synthetic_outline_root_pages(conn, book_id=book_id))
        if not any(page.page_type == "event_summary" for page in pages):
            pages.extend(self._synthetic_event_summary_pages(conn, book_id=book_id))
        self.pages_repo.clear_book(conn, book_id=book_id)
        for page in pages:
            self.pages_repo.upsert(conn, book_id=book_id, page=page)
        return pages

    def _event_summary_artifact(self, book_id: str) -> Path:
        return self.repo_root / DEFAULT_MEMORY_ROOT / "outlines" / f"{book_id}.event_summaries.json"

    def _outline_segments_artifact(self, book_id: str) -> Path:
        return self.repo_root / DEFAULT_MEMORY_ROOT / "outlines" / f"{book_id}.outline_segments.json"

    def _outline_root_pages(self, conn: sqlite3.Connection, *, book_id: str) -> list[NarrativeMemoryPage]:
        stored = self._stored_pages(conn, book_id=book_id, page_type="outline_root")
        if stored:
            return stored
        artifact_pages = self._outline_root_pages_from_artifact(conn, book_id=book_id)
        if artifact_pages:
            return artifact_pages
        return self._synthetic_outline_root_pages(conn, book_id=book_id)

    def _outline_segment_pages(self, conn: sqlite3.Connection, *, book_id: str) -> list[NarrativeMemoryPage]:
        stored = self._stored_pages(conn, book_id=book_id, page_type="outline_segment")
        if stored:
            return stored
        artifact_pages = self._outline_segment_pages_from_artifact(book_id=book_id)
        if artifact_pages:
            return artifact_pages
        return self._outline_segment_pages_from_chapters(conn, book_id=book_id)

    def _outline_root_pages_from_artifact(self, conn: sqlite3.Connection, *, book_id: str) -> list[NarrativeMemoryPage]:
        path = self._outline_segments_artifact(book_id)
        if not path.exists():
            return []
        payload = self._read_json_file(path)
        roots = payload.get("roots") or []
        segment_status = {page.page_id: page.status for page in self._outline_segment_pages(conn, book_id=book_id)}
        pages: list[NarrativeMemoryPage] = []
        for index, root in enumerate(roots if isinstance(roots, list) else [], start=1):
            if not isinstance(root, Mapping):
                continue
            segment_ids = [str(item) for item in (root.get("outline_segment_ids") or []) if str(item)]
            if not segment_ids:
                continue
            doc_ids = _int_list(root.get("source_doc_ids"))
            root_id = _text(root.get("outline_root_id")) or f"{book_id}:outline-root-{index:04d}"
            pages.append(
                NarrativeMemoryPage(
                    page_id=root_id,
                    page_type="outline_root",
                    summary=_safe_excerpt(str(root.get("summary") or ""), limit=700),
                    child_refs=segment_ids,
                    source_doc_ids=doc_ids,
                    source_doc_range=_text(root.get("source_doc_range")) or _range_text(doc_ids),
                    status=_text(root.get("status")) or _combined_status([segment_status.get(item, "provisional") for item in segment_ids]),
                    updated_at=str(payload.get("updated_at") or _utc_now()),
                    metadata={
                        "outline_segment_ids": segment_ids,
                        "source_title_indexes": _int_list(root.get("source_title_indexes")),
                    },
                )
            )
        return pages

    def _outline_segment_pages_from_artifact(self, *, book_id: str) -> list[NarrativeMemoryPage]:
        path = self._outline_segments_artifact(book_id)
        if not path.exists():
            return []
        payload = self._read_json_file(path)
        segments = payload.get("segments") or []
        pages: list[NarrativeMemoryPage] = []
        for index, segment in enumerate(segments if isinstance(segments, list) else [], start=1):
            if not isinstance(segment, Mapping):
                continue
            segment_id = _text(segment.get("outline_segment_id")) or f"{book_id}:outline-segment-{index:04d}"
            doc_ids = _int_list(segment.get("source_doc_ids"))
            title_indexes = _int_list(segment.get("source_title_indexes"))
            pages.append(
                NarrativeMemoryPage(
                    page_id=segment_id,
                    page_type="outline_segment",
                    summary=_text(segment.get("summary")),
                    child_refs=[f"chapter-{title_index}" for title_index in title_indexes],
                    source_doc_ids=doc_ids,
                    source_doc_range=_text(segment.get("source_doc_range")) or _range_text(doc_ids),
                    status=_text(segment.get("status")) or "provisional",
                    updated_at=str(segment.get("updated_at") or payload.get("updated_at") or _utc_now()),
                    metadata={
                        "outline_segment_id": segment_id,
                        "chapter_line": _text(segment.get("chapter_line")),
                        "source_title_indexes": title_indexes,
                        **(dict(segment.get("metadata")) if isinstance(segment.get("metadata"), Mapping) else {}),
                    },
                )
            )
        return pages

    def _outline_segment_pages_from_chapters(self, conn: sqlite3.Connection, *, book_id: str) -> list[NarrativeMemoryPage]:
        pages: list[NarrativeMemoryPage] = []
        for row in self._chapter_rows(conn, book_id=book_id):
            outline = _json_dict(row["outline_update_json"])
            summary = _text(outline.get("outline_segment"))
            if not summary:
                continue
            title_index = int(row["document_title_index"] or 0)
            doc_ids = _int_list(outline.get("source_doc_ids")) or self._source_doc_ids_from_chapter_row(row)
            title_indexes = _int_list(outline.get("source_title_indexes")) or ([title_index] if title_index else [])
            source_doc_range = _text(outline.get("source_doc_range")) or _range_text(doc_ids)
            segment_id = _text(outline.get("outline_segment_id")) or f"outline-segment:chapter-{title_index}"
            pages.append(
                NarrativeMemoryPage(
                    page_id=segment_id,
                    page_type="outline_segment",
                    summary=summary,
                    child_refs=[f"chapter-{item}" for item in title_indexes],
                    source_doc_ids=doc_ids,
                    source_doc_range=source_doc_range,
                    status=_text(outline.get("status")) or str(row["outline_status"] or "provisional"),
                    updated_at=str(row["updated_at"] or ""),
                    metadata={
                        "outline_segment_id": segment_id,
                        "chapter_line": _text(outline.get("chapter_line")),
                        "chapter_id": int(row["chapter_id"] or 0),
                        "document_title_index": title_index,
                        "chapter_title": str(row["chapter_title"] or ""),
                        "source_title_indexes": title_indexes,
                        "source_total_chars": int(row["source_total_chars"] or 0),
                    },
                )
            )
        return pages

    def _synthetic_outline_root_pages(self, conn: sqlite3.Connection, *, book_id: str) -> list[NarrativeMemoryPage]:
        segments = self._outline_segment_pages(conn, book_id=book_id)
        if not segments:
            return []
        groups: list[list[NarrativeMemoryPage]] = []
        current: list[NarrativeMemoryPage] = []
        current_chars = 0
        for segment in segments:
            current.append(segment)
            current_chars += int(segment.metadata.get("source_total_chars") or 0)
            if len(current) >= 16 or current_chars >= 120_000:
                groups.append(current)
                current = []
                current_chars = 0
        if current:
            groups.append(current)
        pages: list[NarrativeMemoryPage] = []
        for index, group in enumerate(groups, start=1):
            doc_ids = sorted({doc_id for page in group for doc_id in page.source_doc_ids})
            segment_ids = [page.page_id for page in group]
            pages.append(
                NarrativeMemoryPage(
                    page_id=f"{book_id}:outline-root-{index:04d}",
                    page_type="outline_root",
                    summary=_safe_excerpt("；".join(page.summary for page in group if page.summary), limit=700),
                    child_refs=segment_ids,
                    source_doc_ids=doc_ids,
                    source_doc_range=_range_text(doc_ids),
                    status=_combined_status([page.status for page in group]),
                    updated_at=_utc_now(),
                    metadata={
                        "outline_segment_ids": segment_ids,
                        "fallback_reason": "missing_outline_segments_artifact",
                    },
                )
            )
        return pages

    def _read_json_file(self, path: Path) -> dict[str, Any]:
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            return {}
        return dict(payload) if isinstance(payload, Mapping) else {}

    def _event_summary_pages(self, conn: sqlite3.Connection, *, book_id: str) -> list[NarrativeMemoryPage]:
        stored = self._stored_pages(conn, book_id=book_id, page_type="event_summary")
        if stored:
            return stored
        path = self._event_summary_artifact(book_id)
        if not path.exists():
            return []
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            return []
        segments = payload.get("segments") or []
        pages = []
        event_status = {page.page_id: page.status for page in self._event_pages(conn, book_id=book_id)}
        for index, segment in enumerate(segments if isinstance(segments, list) else [], start=1):
            if not isinstance(segment, Mapping):
                continue
            event_ids = [str(item) for item in (segment.get("event_ids") or []) if str(item)]
            if not event_ids:
                continue
            summary_id = _text(segment.get("summary_id")) or f"{book_id}:event-summary-{index:04d}"
            doc_ids = _int_list(segment.get("source_doc_ids"))
            source_range = _text(segment.get("source_doc_range")) or _range_text(doc_ids)
            pages.append(
                NarrativeMemoryPage(
                    page_id=summary_id,
                    page_type="event_summary",
                    summary=_safe_excerpt(str(segment.get("summary") or ""), limit=200),
                    child_refs=event_ids,
                    source_doc_ids=doc_ids,
                    source_doc_range=source_range,
                    status=_combined_status([event_status.get(event_id, "provisional") for event_id in event_ids]),
                    updated_at=str(payload.get("updated_at") or segment.get("created_at") or _utc_now()),
                    metadata={
                        "event_id_range": {
                            "start_event_id": event_ids[0],
                            "end_event_id": event_ids[-1],
                        },
                        "event_ids": event_ids,
                        "source_title_indexes": _int_list(segment.get("source_title_indexes")),
                        "summary_title": _text(segment.get("summary_title")),
                    },
                )
            )
        return pages

    def _synthetic_event_summary_pages(self, conn: sqlite3.Connection, *, book_id: str) -> list[NarrativeMemoryPage]:
        events = self._event_pages(conn, book_id=book_id)
        if not events:
            return []
        groups: list[list[NarrativeMemoryPage]] = []
        current: list[NarrativeMemoryPage] = []
        current_chars = 0
        for event in events:
            current.append(event)
            current_chars += int(event.metadata.get("source_total_chars") or 0)
            if len(current) >= 16 or current_chars >= 120_000:
                groups.append(current)
                current = []
                current_chars = 0
        if current:
            groups.append(current)
        pages = []
        for index, group in enumerate(groups, start=1):
            doc_ids = sorted({doc_id for page in group for doc_id in page.source_doc_ids})
            pages.append(
                NarrativeMemoryPage(
                    page_id=f"{book_id}:event-summary-{index:04d}",
                    page_type="event_summary",
                    summary=_safe_excerpt("；".join(page.summary for page in group if page.summary), limit=200),
                    child_refs=[page.page_id for page in group],
                    source_doc_ids=doc_ids,
                    source_doc_range=_range_text(doc_ids),
                    status=_combined_status([page.status for page in group]),
                    updated_at=_utc_now(),
                    metadata={
                        "event_id_range": {
                            "start_event_id": group[0].page_id,
                            "end_event_id": group[-1].page_id,
                        },
                        "event_ids": [page.page_id for page in group],
                        "fallback_reason": "missing_event_summary_artifact",
                    },
                )
            )
        return pages

    def _event_pages(self, conn: sqlite3.Connection, *, book_id: str) -> list[NarrativeMemoryPage]:
        stored = self._stored_pages(conn, book_id=book_id, page_type="event")
        if stored:
            return stored
        pages: list[NarrativeMemoryPage] = []
        for row in self._chapter_rows(conn, book_id=book_id):
            outline = _json_dict(row["outline_update_json"])
            status = _combined_status([str(row["summary_status"] or ""), str(row["outline_status"] or "")])
            chapter_ref = f"chapter-{int(row['document_title_index'])}"
            for index, item in enumerate(outline.get("timeline_events") or [], start=1):
                if not isinstance(item, Mapping):
                    continue
                event_id = _text(item.get("event_id")) or f"chapter-{row['document_title_index']}:event-{index:02d}"
                doc_ids = _int_list(item.get("source_doc_ids")) or self._source_doc_ids_from_chapter_row(row)
                title_indexes = _int_list(item.get("source_title_indexes")) or [int(row["document_title_index"] or 0)]
                pages.append(
                    NarrativeMemoryPage(
                        page_id=event_id,
                        page_type="event",
                        summary=_text(item.get("summary")) or _text(item.get("label")),
                        child_refs=[chapter_ref],
                        source_doc_ids=doc_ids,
                        source_doc_range=_text(item.get("source_doc_range")) or _range_text(doc_ids),
                        status=_text(item.get("status")) or status,
                        updated_at=str(row["updated_at"] or ""),
                        metadata={
                            "event_id": event_id,
                            "label": _text(item.get("label")) or _safe_excerpt(_text(item.get("summary")), limit=40),
                            "outcome": _text(item.get("outcome")) or _text(outline.get("outcome")),
                            "participants": [str(value) for value in (item.get("participants") or [])],
                            "source_chapter_id": int(row["chapter_id"] or 0),
                            "source_chapter_range": _range_text(title_indexes),
                            "source_chapter_indexes": title_indexes,
                            "source_doc_start_id": int(item.get("source_doc_start_id") or (doc_ids[0] if doc_ids else 0)),
                            "source_doc_end_id": int(item.get("source_doc_end_id") or (doc_ids[-1] if doc_ids else 0)),
                            "source_total_chars": int(row["source_total_chars"] or 0),
                        },
                    )
                )
        return pages

    def _chapter_pages(self, conn: sqlite3.Connection, *, book_id: str) -> list[NarrativeMemoryPage]:
        stored = self._stored_pages(conn, book_id=book_id, page_type="chapter")
        if stored:
            return stored
        pages = []
        for row in self._chapter_rows(conn, book_id=book_id):
            doc_ids = self._source_doc_ids_from_chapter_row(row)
            title_index = int(row["document_title_index"] or 0)
            summary = _text(row["summary_md"]) or _text(row["summary_short"])
            pages.append(
                NarrativeMemoryPage(
                    page_id=f"chapter-{title_index}",
                    page_type="chapter",
                    summary=summary,
                    child_refs=[f"document-{doc_id}" for doc_id in doc_ids],
                    source_doc_ids=doc_ids,
                    source_doc_range=_range_text(doc_ids),
                    status=str(row["summary_status"] or "provisional"),
                    updated_at=str(row["updated_at"] or ""),
                    metadata={
                        "chapter_id": int(row["chapter_id"]),
                        "document_title_index": title_index,
                        "chapter_title": str(row["chapter_title"] or ""),
                        "source_doc_start_id": int(row["source_doc_start_id"] or 0),
                        "source_doc_end_id": int(row["source_doc_end_id"] or 0),
                        "source_total_chars": int(row["source_total_chars"] or 0),
                        "compression_ratio": (len(summary) / max(1, int(row["source_total_chars"] or 1))),
                        "compression_warning": len(summary) > max(1, int(row["source_total_chars"] or 1)) / 10,
                    },
                )
            )
        return pages

    def _document_pages(self, conn: sqlite3.Connection, *, book_id: str) -> list[NarrativeMemoryPage]:
        stored = self._stored_pages(conn, book_id=book_id, page_type="document")
        if stored:
            return stored
        rows = conn.execute(
            "SELECT * FROM documents WHERE book_id = ? ORDER BY doc_id",
            (book_id,),
        ).fetchall()
        return [
            NarrativeMemoryPage(
                page_id=f"document-{int(row['doc_id'])}",
                page_type="document",
                summary=_safe_excerpt(str(row["content"] or ""), limit=420),
                child_refs=[str(row["doc_id"])],
                source_doc_ids=[int(row["doc_id"])],
                source_doc_range=str(row["doc_id"]),
                status="provisional",
                updated_at=str(row["updated_at"] or ""),
                metadata={
                    "doc_id": int(row["doc_id"]),
                    "document_title_index": int(row["document_title_index"] or 0),
                    "document_title": str(row["document_title"] or ""),
                    "source_path": str(row["source_path"] or row["path"] or ""),
                    "source_start_offset": int(row["source_start_offset"] or 0),
                    "source_end_offset": int(row["source_end_offset"] or 0),
                },
            )
            for row in rows
        ]

    def _stored_pages(
        self,
        conn: sqlite3.Connection,
        *,
        book_id: str,
        page_type: str,
    ) -> list[NarrativeMemoryPage]:
        try:
            return self.pages_repo.list_by_book(conn, book_id=book_id, page_type=page_type)
        except sqlite3.OperationalError:
            return []

    def _chapter_rows(self, conn: sqlite3.Connection, *, book_id: str) -> list[sqlite3.Row]:
        try:
            return self.chapters_repo.list_by_book(conn, book_id=book_id)
        except sqlite3.OperationalError:
            return []

    def _source_doc_ids_from_chapter_row(self, row: sqlite3.Row) -> list[int]:
        start = int(row["source_doc_start_id"] or 0)
        end = int(row["source_doc_end_id"] or 0)
        if start <= 0 or end <= 0:
            return []
        if end < start:
            return [start]
        if end - start > 512:
            return [start, end]
        return list(range(start, end + 1))

    def _pages_by_ids(
        self,
        conn: sqlite3.Connection,
        *,
        book_id: str,
        level: str,
        page_ids: Sequence[str],
    ) -> list[NarrativeMemoryPage]:
        if not page_ids:
            return []
        all_pages = {
            page.page_id: page
            for page in self._pages_for_level(conn, book_id=book_id, level=level)
        }
        resolved: list[NarrativeMemoryPage] = []
        for page_id in page_ids:
            page = all_pages.get(str(page_id))
            if page is not None:
                resolved.append(page)
                continue
            if level == "document" and str(page_id).isdigit():
                page = all_pages.get(f"document-{page_id}")
                if page is not None:
                    resolved.append(page)
        return resolved

    def _pages_for_level(self, conn: sqlite3.Connection, *, book_id: str, level: str) -> list[NarrativeMemoryPage]:
        if level == "outline_root":
            return self._outline_root_pages(conn, book_id=book_id)
        if level == "outline_segment":
            return self._outline_segment_pages(conn, book_id=book_id)
        if level == "event_summary":
            return self._event_summary_pages(conn, book_id=book_id) or self._synthetic_event_summary_pages(conn, book_id=book_id)
        if level == "event":
            return self._event_pages(conn, book_id=book_id)
        if level == "chapter":
            return self._chapter_pages(conn, book_id=book_id)
        return self._document_pages(conn, book_id=book_id)

    def _children_for_pages(
        self,
        conn: sqlite3.Connection,
        *,
        book_id: str,
        pages: Sequence[NarrativeMemoryPage],
        next_level: str,
    ) -> list[NarrativeMemoryPage]:
        child_ids = [child for page in pages for child in page.child_refs]
        if not child_ids and next_level == "document":
            child_ids = [str(doc_id) for page in pages for doc_id in page.source_doc_ids]
        return self._pages_by_ids(conn, book_id=book_id, level=next_level, page_ids=child_ids)

    def _expand_with_siblings(
        self,
        conn: sqlite3.Connection,
        *,
        book_id: str,
        level: str,
        selected_pages: Sequence[NarrativeMemoryPage],
        state: MemoryQueryState,
    ) -> list[NarrativeMemoryPage]:
        all_pages = self._pages_for_level(conn, book_id=book_id, level=level)
        if selected_pages:
            selected_ids = {page.page_id for page in selected_pages}
            indexes = [index for index, page in enumerate(all_pages) if page.page_id in selected_ids]
            expanded = list(selected_pages)
            for index in indexes:
                for sibling_index in (index - 1, index + 1):
                    if 0 <= sibling_index < len(all_pages):
                        sibling = all_pages[sibling_index]
                        if sibling.page_id not in {page.page_id for page in expanded}:
                            expanded.append(sibling)
            return expanded
        candidate_ids = [str(item.get("id") or item.get("page_id") or "") for item in state.current_candidates[:2]]
        return self._pages_by_ids(conn, book_id=book_id, level=level, page_ids=candidate_ids)

    def _next_level(self, current_level: str) -> str:
        level_order = self.LEVEL_ORDER if current_level in self.LEVEL_ORDER else self.LEGACY_LEVEL_ORDER
        try:
            index = level_order.index(current_level)
        except ValueError:
            return "outline_segment"
        return level_order[min(index + 1, len(level_order) - 1)]

    def _rank_pages(
        self,
        pages: Sequence[NarrativeMemoryPage],
        *,
        query: str,
        limit: int,
    ) -> list[NarrativeMemoryPage]:
        tokens = [token for token in re.findall(r"[\u4e00-\u9fff]{2,}|[A-Za-z0-9_]{2,}", query) if token]
        scored = []
        for order, page in enumerate(pages):
            haystack = json.dumps(page.to_dict(), ensure_ascii=False)
            score = sum(1.0 for token in tokens if token in haystack)
            score += 0.1 / (order + 1)
            scored.append((page, score))
        return [page for page, _score in sorted(scored, key=lambda item: item[1], reverse=True)[:limit]]

    def _candidate_dict(self, page: NarrativeMemoryPage, *, budget: MemoryQueryBudget) -> dict[str, Any]:
        payload = {
            "id": page.page_id,
            "page_id": page.page_id,
            "page_type": page.page_type,
            "summary": _safe_excerpt(page.summary, limit=min(700, budget.max_candidate_chars)),
            "child_refs": list(page.child_refs),
            "source_doc_ids": list(page.source_doc_ids),
            "source_doc_range": page.source_doc_range,
            "status": page.status,
            **self._candidate_metadata(page),
        }
        return payload

    def _candidate_metadata(self, page: NarrativeMemoryPage) -> dict[str, Any]:
        metadata = dict(page.metadata)
        if page.page_type == "event":
            return {
                "event_id": metadata.get("event_id") or page.page_id,
                "label": metadata.get("label") or "",
                "outcome": metadata.get("outcome") or "",
                "participants": metadata.get("participants") or [],
                "source_chapter_range": metadata.get("source_chapter_range") or "",
            }
        if page.page_type == "event_summary":
            event_range = metadata.get("event_id_range") if isinstance(metadata.get("event_id_range"), Mapping) else {}
            return {
                "event_id_range": dict(event_range),
                "start_event_id": event_range.get("start_event_id") if isinstance(event_range, Mapping) else "",
                "end_event_id": event_range.get("end_event_id") if isinstance(event_range, Mapping) else "",
            }
        if page.page_type == "outline_root":
            segment_ids = metadata.get("outline_segment_ids")
            segment_ids = segment_ids if isinstance(segment_ids, list) else list(page.child_refs)
            return {
                "outline_segment_ids": [str(item) for item in segment_ids],
                "start_outline_segment_id": str(segment_ids[0]) if segment_ids else "",
                "end_outline_segment_id": str(segment_ids[-1]) if segment_ids else "",
            }
        if page.page_type == "outline_segment":
            return {
                "outline_segment_id": metadata.get("outline_segment_id") or page.page_id,
                "chapter_line": metadata.get("chapter_line") or "",
                "source_title_indexes": metadata.get("source_title_indexes") or [],
                "document_title_index": metadata.get("document_title_index"),
                "chapter_title": metadata.get("chapter_title") or "",
            }
        if page.page_type == "chapter":
            return {
                "chapter_ref": page.page_id,
                "document_title_index": metadata.get("document_title_index"),
                "chapter_title": metadata.get("chapter_title") or "",
                "source_doc_start_id": metadata.get("source_doc_start_id"),
                "source_doc_end_id": metadata.get("source_doc_end_id"),
                "compression_warning": bool(metadata.get("compression_warning")),
            }
        return {
            "doc_id": metadata.get("doc_id") or (page.source_doc_ids[0] if page.source_doc_ids else None),
            "document_title_index": metadata.get("document_title_index"),
        }

    def _source_event_range(self, page: NarrativeMemoryPage) -> dict[str, str]:
        event_range = page.metadata.get("event_id_range")
        if isinstance(event_range, Mapping):
            return {str(key): str(value) for key, value in event_range.items()}
        return {}

    def _evidence_from_page(self, page: NarrativeMemoryPage) -> dict[str, Any]:
        payload = self._candidate_dict(page, budget=MemoryQueryBudget())
        payload["summary"] = page.summary
        return payload

    def _source_from_page(self, page: NarrativeMemoryPage) -> dict[str, Any]:
        source_path = f"memory:{page.page_type}:{page.page_id}"
        if page.page_type in {"event", "chapter"}:
            chapter_id = page.metadata.get("source_chapter_id") or page.metadata.get("chapter_id")
            if chapter_id:
                source_path = f"sqlite:chapters:{chapter_id}"
        if page.page_type == "outline_segment":
            chapter_id = page.metadata.get("chapter_id")
            if chapter_id:
                source_path = f"sqlite:chapters:{chapter_id}:outline_segment"
        if page.page_type == "document" and page.source_doc_ids:
            source_path = f"sqlite:documents:{page.source_doc_ids[0]}"
        return {
            "type": page.page_type,
            "path": source_path,
            "source_doc_ids": list(page.source_doc_ids),
            "source_doc_range": page.source_doc_range,
            "status": page.status,
        }

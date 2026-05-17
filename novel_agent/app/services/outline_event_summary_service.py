from __future__ import annotations

import json
import sqlite3
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping

from ..constants import DEFAULT_MEMORY_ROOT
from ..llm import JsonModelClient
from ..utils.text_utils import safe_excerpt


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


@dataclass(slots=True)
class OutlineEventCard:
    event_id: str
    label: str
    summary: str
    document_title_index: int
    source_doc_ids: list[int] = field(default_factory=list)
    source_doc_range: str = ""
    participants: list[str] = field(default_factory=list)

    def to_model_dict(self, *, queue_index: int) -> dict[str, Any]:
        return {
            "queue_index": queue_index,
            "event_id": self.event_id,
            "label": self.label,
            "summary": self.summary,
            "document_title_index": self.document_title_index,
            "source_doc_ids": list(self.source_doc_ids),
            "source_doc_range": self.source_doc_range,
            "participants": list(self.participants),
        }


class OutlineEventSummaryService:
    """Maintains rolling summaries over uncompressed outline events.

    The event list remains the index source of truth. This service only builds
    higher-level summaries over adjacent related events and preserves the tail
    that the model considers unrelated or too recent to compress.
    """

    def __init__(
        self,
        *,
        repo_root: Path,
        model_client: JsonModelClient | None = None,
        min_uncompressed_events: int = 8,
        max_events_per_pass: int = 24,
        fallback_tail_events: int = 2,
    ) -> None:
        self.repo_root = repo_root
        self.model_client = model_client
        self.min_uncompressed_events = max(2, int(min_uncompressed_events))
        self.max_events_per_pass = max(self.min_uncompressed_events, int(max_events_per_pass))
        self.fallback_tail_events = max(0, int(fallback_tail_events))

    def artifact_path(self, book_id: str) -> Path:
        path = self.repo_root / DEFAULT_MEMORY_ROOT / "outlines" / f"{book_id}.event_summaries.json"
        path.parent.mkdir(parents=True, exist_ok=True)
        return path

    def refresh(self, conn: sqlite3.Connection, *, book_id: str) -> dict[str, Any]:
        events = self._load_events(conn, book_id=book_id)
        state = self._load_state(book_id)
        segments = [item for item in state.get("segments", []) if isinstance(item, dict)]
        compressed_ids = {
            str(event_id)
            for segment in segments
            for event_id in (segment.get("event_ids") or [])
            if str(event_id)
        }
        pending = [event for event in events if event.event_id not in compressed_ids]
        new_segment: dict[str, Any] | None = None
        if len(pending) >= self.min_uncompressed_events:
            candidate_events = pending[: self.max_events_per_pass]
            decision = self._decide_compression(candidate_events)
            new_segment = self._segment_from_decision(
                book_id=book_id,
                events=candidate_events,
                decision=decision,
                sequence=len(segments) + 1,
            )
            if new_segment is not None:
                segments.append(new_segment)
                compressed_ids.update(str(event_id) for event_id in new_segment["event_ids"])
                pending = [event for event in events if event.event_id not in compressed_ids]

        payload = {
            "schema_version": 1,
            "book_id": book_id,
            "updated_at": _utc_now(),
            "all_event_count": len(events),
            "compressed_event_count": len(compressed_ids),
            "pending_event_ids": [event.event_id for event in pending],
            "segments": segments,
        }
        self.artifact_path(book_id).write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        return payload

    def _decide_compression(self, events: list[OutlineEventCard]) -> dict[str, Any]:
        if self.model_client is None:
            raise RuntimeError("OutlineEventSummaryService requires an available model_client")
        fallback = lambda: self._fallback_decision(events)
        payload, _raw = self.model_client.generate_json(
            system_prompt=(
                "你是故事记忆压缩器。你的任务是从按时间顺序排列的未压缩 event 队列中，"
                "选择前部关联性强、适合压缩为一个连续 event summary 的事件。"
                "如果队列尾部事件与前部主题不同、太新、或尚需等待后续上下文，必须把这些尾部事件的 queue_index "
                "放入 tail_uncompressed_event_indexes。不要改写 event_id，不要引用原文。只返回 JSON。"
            ),
            user_prompt=json.dumps(
                {
                    "instruction": (
                        "返回 JSON: {should_compress, summary_title, event_summary, "
                        "tail_uncompressed_event_indexes, reason}。tail_uncompressed_event_indexes 必须是队列尾部连续 index。"
                    ),
                    "events": [event.to_model_dict(queue_index=index) for index, event in enumerate(events, start=1)],
                },
                ensure_ascii=False,
                indent=2,
            ),
            fallback_factory=fallback,
            use_fallback_on_error=bool(self.model_client.settings.dry_run),
        )
        if not isinstance(payload, Mapping):
            raise RuntimeError("Outline event summary model returned a non-object JSON payload")
        return dict(payload)

    def _fallback_decision(self, events: list[OutlineEventCard]) -> dict[str, Any]:
        tail_count = min(self.fallback_tail_events, max(0, len(events) - 1))
        compressed = events[: len(events) - tail_count] if tail_count else list(events)
        return {
            "should_compress": bool(compressed),
            "summary_title": compressed[0].label if compressed else "",
            "event_summary": "；".join(safe_excerpt(event.summary or event.label, 80) for event in compressed),
            "tail_uncompressed_event_indexes": list(range(len(compressed) + 1, len(events) + 1)),
            "reason": "fallback_adjacent_prefix_compression",
        }

    def _segment_from_decision(
        self,
        *,
        book_id: str,
        events: list[OutlineEventCard],
        decision: Mapping[str, Any],
        sequence: int,
    ) -> dict[str, Any] | None:
        if not bool(decision.get("should_compress", True)):
            return None
        tail_indexes = self._valid_tail_indexes(decision.get("tail_uncompressed_event_indexes"), event_count=len(events))
        compressed_events = events[: len(events) - len(tail_indexes)]
        if not compressed_events:
            return None
        summary = str(decision.get("event_summary") or "").strip()
        if not summary:
            summary = "；".join(event.summary or event.label for event in compressed_events if event.summary or event.label)
        if not summary:
            return None
        doc_ids = self._merge_ints([doc_id for event in compressed_events for doc_id in event.source_doc_ids])
        title_indexes = self._merge_ints([event.document_title_index for event in compressed_events])
        return {
            "summary_id": f"{book_id}:event-summary-{sequence:04d}",
            "event_summary_level": "event_group",
            "summary_title": str(decision.get("summary_title") or compressed_events[0].label or f"事件组 {sequence}").strip(),
            "summary": safe_excerpt(summary, 200),
            "start_event_id": compressed_events[0].event_id,
            "end_event_id": compressed_events[-1].event_id,
            "event_ids": [event.event_id for event in compressed_events],
            "event_id_range": {
                "start_event_id": compressed_events[0].event_id,
                "end_event_id": compressed_events[-1].event_id,
            },
            "tail_uncompressed_event_ids": [events[index - 1].event_id for index in tail_indexes],
            "source_doc_ids": doc_ids,
            "source_doc_range": self._range_text(doc_ids),
            "source_title_indexes": title_indexes,
            "status": "provisional",
            "reason": str(decision.get("reason") or "").strip(),
            "created_at": _utc_now(),
        }

    def _valid_tail_indexes(self, value: object, *, event_count: int) -> list[int]:
        raw_indexes = self._merge_ints(value if isinstance(value, list) else [])
        raw_indexes = [index for index in raw_indexes if 1 <= index <= event_count]
        if not raw_indexes:
            return []
        expected = list(range(raw_indexes[0], event_count + 1))
        return raw_indexes if raw_indexes == expected else []

    def _load_events(self, conn: sqlite3.Connection, *, book_id: str) -> list[OutlineEventCard]:
        rows = conn.execute(
            """
            SELECT document_title_index, outline_update_json
            FROM chapters
            WHERE book_id = ?
            ORDER BY document_title_index ASC, chapter_id ASC
            """,
            (book_id,),
        ).fetchall()
        events: list[OutlineEventCard] = []
        seen: set[str] = set()
        for row in rows:
            payload = self._json_dict(row["outline_update_json"])
            for index, item in enumerate(payload.get("timeline_events") or [], start=1):
                if not isinstance(item, Mapping):
                    continue
                event_id = str(item.get("event_id") or f"chapter-{row['document_title_index']}:event-{index:02d}").strip()
                if not event_id or event_id in seen:
                    continue
                seen.add(event_id)
                source_doc_ids = self._merge_ints(item.get("source_doc_ids") if isinstance(item.get("source_doc_ids"), list) else [])
                events.append(
                    OutlineEventCard(
                        event_id=event_id,
                        label=str(item.get("label") or "").strip(),
                        summary=str(item.get("summary") or "").strip(),
                        document_title_index=int(item.get("document_title_index") or row["document_title_index"] or 0),
                        source_doc_ids=source_doc_ids,
                        source_doc_range=str(item.get("source_doc_range") or self._range_text(source_doc_ids)),
                        participants=[str(value) for value in item.get("participants") or []],
                    )
                )
        return events

    def _load_state(self, book_id: str) -> dict[str, Any]:
        path = self.artifact_path(book_id)
        if not path.exists():
            return {}
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            return {}
        return dict(payload) if isinstance(payload, dict) else {}

    @staticmethod
    def _json_dict(raw_value: object) -> dict[str, Any]:
        if not raw_value:
            return {}
        try:
            payload = json.loads(str(raw_value))
        except json.JSONDecodeError:
            return {}
        return dict(payload) if isinstance(payload, dict) else {}

    @staticmethod
    def _merge_ints(values: object) -> list[int]:
        if not isinstance(values, list):
            return []
        cleaned: set[int] = set()
        for value in values:
            try:
                cleaned.add(int(value))
            except (TypeError, ValueError):
                continue
        return sorted(cleaned)

    @staticmethod
    def _range_text(values: list[int]) -> str:
        if not values:
            return ""
        return str(values[0]) if len(values) == 1 else f"{values[0]}-{values[-1]}"

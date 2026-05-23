from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any, Mapping


MEMORY_PAGE_TYPES = {"document", "chapter", "event", "event_summary", "outline_segment", "outline_root"}
MEMORY_PAGE_STATUSES = {"provisional", "committed", "mixed"}


def _text(value: object) -> str:
    return str(value or "").strip()


def _string_list(value: object) -> list[str]:
    if not isinstance(value, list):
        return []
    result: list[str] = []
    seen: set[str] = set()
    for item in value:
        text = _text(item)
        if text and text not in seen:
            seen.add(text)
            result.append(text)
    return result


def _int_list(value: object) -> list[int]:
    if not isinstance(value, list):
        return []
    result: list[int] = []
    seen: set[int] = set()
    for item in value:
        try:
            number = int(item)
        except (TypeError, ValueError):
            continue
        if number not in seen:
            seen.add(number)
            result.append(number)
    return sorted(result)


def _status(value: object) -> str:
    normalized = _text(value).lower() or "provisional"
    return normalized if normalized in MEMORY_PAGE_STATUSES else "provisional"


def _page_type(value: object) -> str:
    normalized = _text(value).lower()
    if normalized not in MEMORY_PAGE_TYPES:
        raise ValueError("page_type must be document, chapter, event, event_summary, outline_segment, or outline_root")
    return normalized


@dataclass(slots=True)
class MemoryQueryBudget:
    max_root_candidates: int = 8
    max_child_candidates: int = 12
    max_path_context_chars: int = 1600
    max_candidate_chars: int = 2400
    max_trace_items: int = 80
    excerpt_budget: int = 1200

    def __post_init__(self) -> None:
        self.max_root_candidates = max(1, int(self.max_root_candidates or 1))
        self.max_child_candidates = max(1, int(self.max_child_candidates or 1))
        self.max_path_context_chars = max(200, int(self.max_path_context_chars or 200))
        self.max_candidate_chars = max(200, int(self.max_candidate_chars or 200))
        self.max_trace_items = max(10, int(self.max_trace_items or 10))
        self.excerpt_budget = max(80, int(self.excerpt_budget or 80))

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(slots=True)
class NarrativeMemoryPage:
    page_id: str
    page_type: str
    summary: str
    child_refs: list[str] = field(default_factory=list)
    source_doc_ids: list[int] = field(default_factory=list)
    source_doc_range: str = ""
    status: str = "provisional"
    updated_at: str = ""
    metadata: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        self.page_id = _text(self.page_id)
        self.page_type = _page_type(self.page_type)
        self.summary = _text(self.summary)
        self.child_refs = _string_list(self.child_refs)
        self.source_doc_ids = _int_list(self.source_doc_ids)
        self.source_doc_range = _text(self.source_doc_range)
        self.status = _status(self.status)
        self.updated_at = _text(self.updated_at)
        self.metadata = dict(self.metadata) if isinstance(self.metadata, Mapping) else {}
        if not self.page_id:
            raise ValueError("page_id is required")

    def to_dict(self) -> dict[str, Any]:
        return {
            "page_id": self.page_id,
            "page_type": self.page_type,
            "summary": self.summary,
            "child_refs": list(self.child_refs),
            "source_doc_ids": list(self.source_doc_ids),
            "source_doc_range": self.source_doc_range,
            "status": self.status,
            "updated_at": self.updated_at,
            "metadata": dict(self.metadata),
        }

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "NarrativeMemoryPage":
        return cls(
            page_id=str(data.get("page_id") or ""),
            page_type=str(data.get("page_type") or ""),
            summary=str(data.get("summary") or ""),
            child_refs=[str(item) for item in (data.get("child_refs") or [])],
            source_doc_ids=[int(item) for item in (data.get("source_doc_ids") or []) if str(item).isdigit()],
            source_doc_range=str(data.get("source_doc_range") or ""),
            status=str(data.get("status") or "provisional"),
            updated_at=str(data.get("updated_at") or ""),
            metadata=dict(data.get("metadata") or {}) if isinstance(data.get("metadata"), Mapping) else {},
        )


@dataclass(slots=True)
class MemoryQueryPathItem:
    level: str
    selected_id: str
    summary: str = ""
    source_doc_range: str = ""
    source_event_range: dict[str, str] = field(default_factory=dict)
    selection_reason: str = ""
    confidence: float = 0.0
    status: str = "provisional"

    def __post_init__(self) -> None:
        self.level = _text(self.level)
        self.selected_id = _text(self.selected_id)
        self.summary = _text(self.summary)
        self.source_doc_range = _text(self.source_doc_range)
        self.source_event_range = {
            str(key): str(value) for key, value in self.source_event_range.items()
        } if isinstance(self.source_event_range, Mapping) else {}
        self.selection_reason = _text(self.selection_reason)
        self.confidence = max(0.0, min(float(self.confidence or 0), 1.0))
        self.status = _status(self.status)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(slots=True)
class MemoryQueryState:
    original_query: str
    current_level: str
    current_candidates: list[dict[str, Any]] = field(default_factory=list)
    query_suffix_chain: list[str] = field(default_factory=list)
    path_context: list[MemoryQueryPathItem] = field(default_factory=list)
    budget: MemoryQueryBudget = field(default_factory=MemoryQueryBudget)
    budget_used: dict[str, Any] = field(default_factory=dict)
    trace: list[dict[str, Any]] = field(default_factory=list)

    def __post_init__(self) -> None:
        self.original_query = _text(self.original_query)
        self.current_level = _text(self.current_level)
        self.current_candidates = [
            dict(item) for item in self.current_candidates if isinstance(item, Mapping)
        ]
        self.query_suffix_chain = _string_list(self.query_suffix_chain)
        self.path_context = [
            item if isinstance(item, MemoryQueryPathItem) else MemoryQueryPathItem(**dict(item))
            for item in self.path_context
            if isinstance(item, (MemoryQueryPathItem, Mapping))
        ]
        self.budget_used = dict(self.budget_used) if isinstance(self.budget_used, Mapping) else {}
        self.trace = [dict(item) for item in self.trace if isinstance(item, Mapping)]

    def to_dict(self) -> dict[str, Any]:
        return {
            "original_query": self.original_query,
            "current_level": self.current_level,
            "current_candidates": [dict(item) for item in self.current_candidates],
            "query_suffix_chain": list(self.query_suffix_chain),
            "path_context": [item.to_dict() for item in self.path_context],
            "budget": self.budget.to_dict(),
            "budget_used": dict(self.budget_used),
            "trace": [dict(item) for item in self.trace],
        }


@dataclass(slots=True)
class MemoryEvidenceBundle:
    evidence_items: list[dict[str, Any]] = field(default_factory=list)
    sources: list[dict[str, Any]] = field(default_factory=list)
    status: str = "provisional"
    source_doc_ids: list[int] = field(default_factory=list)
    chapter_refs: list[str] = field(default_factory=list)
    event_ids: list[str] = field(default_factory=list)
    excerpts: list[dict[str, Any]] = field(default_factory=list)
    trace: list[dict[str, Any]] = field(default_factory=list)

    def __post_init__(self) -> None:
        self.evidence_items = [dict(item) for item in self.evidence_items if isinstance(item, Mapping)]
        self.sources = [dict(item) for item in self.sources if isinstance(item, Mapping)]
        self.status = _status(self.status)
        self.source_doc_ids = _int_list(self.source_doc_ids)
        self.chapter_refs = _string_list(self.chapter_refs)
        self.event_ids = _string_list(self.event_ids)
        self.excerpts = [dict(item) for item in self.excerpts if isinstance(item, Mapping)]
        self.trace = [dict(item) for item in self.trace if isinstance(item, Mapping)]

    def to_dict(self) -> dict[str, Any]:
        return {
            "evidence_items": [dict(item) for item in self.evidence_items],
            "sources": [dict(item) for item in self.sources],
            "status": self.status,
            "source_doc_ids": list(self.source_doc_ids),
            "chapter_refs": list(self.chapter_refs),
            "event_ids": list(self.event_ids),
            "excerpts": [dict(item) for item in self.excerpts],
            "trace": [dict(item) for item in self.trace],
        }


@dataclass(slots=True)
class MemoryCandidateSelection:
    need_drill_down: bool = True
    selected_ids: list[str] = field(default_factory=list)
    query_suffix: str = ""
    reason: str = ""
    confidence: float = 0.0
    need_sibling_scan: bool = False
    model_reasoning_debug: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        self.selected_ids = _string_list(self.selected_ids)
        self.query_suffix = _text(self.query_suffix)
        self.reason = _text(self.reason)
        self.confidence = max(0.0, min(float(self.confidence or 0), 1.0))
        self.model_reasoning_debug = (
            dict(self.model_reasoning_debug) if isinstance(self.model_reasoning_debug, Mapping) else {}
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "need_drill_down": bool(self.need_drill_down),
            "selected_ids": list(self.selected_ids),
            "query_suffix": self.query_suffix,
            "reason": self.reason,
            "confidence": self.confidence,
            "need_sibling_scan": bool(self.need_sibling_scan),
            "model_reasoning_debug": dict(self.model_reasoning_debug),
        }

    @classmethod
    def from_mapping(cls, data: Mapping[str, Any]) -> "MemoryCandidateSelection":
        return cls(
            need_drill_down=bool(data.get("need_drill_down", True)),
            selected_ids=[str(item) for item in (data.get("selected_ids") or [])],
            query_suffix=str(data.get("query_suffix") or ""),
            reason=str(data.get("reason") or ""),
            confidence=float(data.get("confidence") or 0),
            need_sibling_scan=bool(data.get("need_sibling_scan", False)),
            model_reasoning_debug=dict(data.get("model_reasoning_debug") or {})
            if isinstance(data.get("model_reasoning_debug"), Mapping)
            else {},
        )

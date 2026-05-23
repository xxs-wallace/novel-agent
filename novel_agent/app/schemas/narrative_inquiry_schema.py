from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any, Literal, Mapping, Sequence, cast


NarrativeInquiryRequestType = Literal[
    "story_detail",
    "fact_check",
    "related_documents",
    "chapter_summary",
    "character_profile",
    "world_concept",
    "source_arc",
    "open_threads",
    "raw_excerpt",
    "structure_pattern",
    "index_card_search",
    "factual_event_card_search",
    "narrative_scene_card_search",
    "character_state_card_search",
    "mystery_card_search",
    "theme_signal_card_search",
    "world_concept_card_search",
    "creative_reference_card_search",
]
NarrativeInquiryPriority = Literal["high", "medium", "low"]
EvidenceBundleStatus = Literal["found", "missing", "blocked", "budget_limited", "failed"]
EvidenceFactStatus = Literal["confirmed", "candidate", "missing", "conflicting", "insufficient_context"]
AnalyzerLoopStatus = Literal[
    "need_more_info",
    "ready_to_answer",
    "needs_user_preference",
    "insufficient_memory",
    "budget_exhausted",
    "needs_model",
    "failed",
    "blocked",
]


REQUEST_TYPES = {
    "story_detail",
    "fact_check",
    "related_documents",
    "chapter_summary",
    "character_profile",
    "world_concept",
    "source_arc",
    "open_threads",
    "raw_excerpt",
    "structure_pattern",
    "index_card_search",
    "factual_event_card_search",
    "narrative_scene_card_search",
    "character_state_card_search",
    "mystery_card_search",
    "theme_signal_card_search",
    "world_concept_card_search",
    "creative_reference_card_search",
}
PRIORITIES = {"high", "medium", "low"}
BUNDLE_STATUSES = {"found", "missing", "blocked", "budget_limited", "failed"}
FACT_STATUSES = {"confirmed", "candidate", "missing", "conflicting", "insufficient_context"}
LOOP_STATUSES = {
    "need_more_info",
    "ready_to_answer",
    "needs_user_preference",
    "insufficient_memory",
    "budget_exhausted",
    "needs_model",
    "failed",
    "blocked",
}


def _text(value: object) -> str:
    return str(value or "").strip()


def _string_list(value: object) -> list[str]:
    if not isinstance(value, Sequence) or isinstance(value, (str, bytes)):
        return []
    result: list[str] = []
    seen: set[str] = set()
    for item in value:
        text = _text(item)
        if text and text not in seen:
            seen.add(text)
            result.append(text)
    return result


def _dict_list(value: object) -> list[dict[str, Any]]:
    if not isinstance(value, Sequence) or isinstance(value, (str, bytes)):
        return []
    return [{str(key): item[key] for key in item} for item in value if isinstance(item, Mapping)]


def _int_list(value: object) -> list[int]:
    if not isinstance(value, Sequence) or isinstance(value, (str, bytes)):
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


@dataclass(slots=True)
class ChapterReadPlan:
    document_title_index: int = 0
    title: str = ""
    read_reason: str = ""
    expected_confirmation: str = ""
    priority: NarrativeInquiryPriority = "medium"
    excerpt_focus: list[str] = field(default_factory=list)

    def __post_init__(self) -> None:
        self.document_title_index = max(0, int(self.document_title_index or 0))
        self.title = _text(self.title)
        self.read_reason = _text(self.read_reason)
        self.expected_confirmation = _text(self.expected_confirmation)
        priority = _text(self.priority).lower() or "medium"
        self.priority = cast(NarrativeInquiryPriority, priority if priority in PRIORITIES else "medium")
        self.excerpt_focus = _string_list(self.excerpt_focus)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_mapping(cls, data: Mapping[str, Any]) -> "ChapterReadPlan":
        return cls(
            document_title_index=int(data.get("document_title_index") or 0),
            title=str(data.get("title") or ""),
            read_reason=str(data.get("read_reason") or data.get("reason") or ""),
            expected_confirmation=str(data.get("expected_confirmation") or ""),
            priority=cast(NarrativeInquiryPriority, str(data.get("priority") or "medium")),
            excerpt_focus=[str(item) for item in (data.get("excerpt_focus") or [])],
        )


@dataclass(slots=True)
class NarrativeInquiryRequest:
    request_id: str
    request_type: NarrativeInquiryRequestType
    query: str
    purpose: str
    priority: NarrativeInquiryPriority = "medium"
    expected_depth: str = ""
    name: str = ""
    concept: str = ""
    chapter_refs: list[str] = field(default_factory=list)
    document_ids: list[int] = field(default_factory=list)
    source_doc_ids: list[int] = field(default_factory=list)
    read_reason: str = ""
    expected_confirmation: str = ""
    affects_analysis: str = ""
    excerpt_focus: list[str] = field(default_factory=list)
    chapter_read_plan: list[ChapterReadPlan] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        self.request_id = _text(self.request_id)
        request_type = _text(self.request_type).lower()
        if request_type not in REQUEST_TYPES:
            raise ValueError("request_type must be a supported Narrative Inquiry type")
        self.request_type = cast(NarrativeInquiryRequestType, request_type)
        self.query = _text(self.query)
        self.purpose = _text(self.purpose)
        priority = _text(self.priority).lower() or "medium"
        if priority not in PRIORITIES:
            raise ValueError("priority must be high, medium, or low")
        self.priority = cast(NarrativeInquiryPriority, priority)
        self.expected_depth = _text(self.expected_depth)
        self.name = _text(self.name)
        self.concept = _text(self.concept)
        self.chapter_refs = _string_list(self.chapter_refs)
        self.document_ids = _int_list(self.document_ids)
        self.source_doc_ids = _int_list(self.source_doc_ids)
        self.read_reason = _text(self.read_reason)
        self.expected_confirmation = _text(self.expected_confirmation)
        self.affects_analysis = _text(self.affects_analysis)
        self.excerpt_focus = _string_list(self.excerpt_focus)
        self.chapter_read_plan = [
            item if isinstance(item, ChapterReadPlan) else ChapterReadPlan.from_mapping(item)
            for item in self.chapter_read_plan
            if isinstance(item, (ChapterReadPlan, Mapping))
        ]
        self.metadata = dict(self.metadata) if isinstance(self.metadata, Mapping) else {}
        if not self.request_id:
            self.request_id = f"{self.request_type}:{self.query or self.name or self.concept}"
        if not (self.query or self.name or self.concept or self.chapter_refs or self.document_ids or self.source_doc_ids):
            raise ValueError("Narrative Inquiry request requires query, name, concept, chapter_refs, or document ids")

    @property
    def dedupe_key(self) -> str:
        target = self.name or self.concept or self.query or ",".join(self.chapter_refs) or ",".join(map(str, self.document_ids))
        return f"{self.request_type}:{target.lower()}"

    def to_dict(self) -> dict[str, Any]:
        return {
            "request_id": self.request_id,
            "type": self.request_type,
            "request_type": self.request_type,
            "query": self.query,
            "purpose": self.purpose,
            "priority": self.priority,
            "expected_depth": self.expected_depth,
            "name": self.name,
            "concept": self.concept,
            "chapter_refs": list(self.chapter_refs),
            "document_ids": list(self.document_ids),
            "source_doc_ids": list(self.source_doc_ids),
            "read_reason": self.read_reason,
            "expected_confirmation": self.expected_confirmation,
            "affects_analysis": self.affects_analysis,
            "excerpt_focus": list(self.excerpt_focus),
            "chapter_read_plan": [item.to_dict() for item in self.chapter_read_plan],
            "metadata": dict(self.metadata),
        }

    @classmethod
    def from_mapping(cls, data: Mapping[str, Any], *, index: int = 1) -> "NarrativeInquiryRequest":
        request_type = str(data.get("request_type") or data.get("type") or "")
        return cls(
            request_id=str(data.get("request_id") or data.get("id") or f"req-{index:03d}"),
            request_type=cast(NarrativeInquiryRequestType, request_type),
            query=str(data.get("query") or ""),
            purpose=str(data.get("purpose") or ""),
            priority=cast(NarrativeInquiryPriority, str(data.get("priority") or "medium")),
            expected_depth=str(data.get("expected_depth") or ""),
            name=str(data.get("name") or ""),
            concept=str(data.get("concept") or ""),
            chapter_refs=[str(item) for item in (data.get("chapter_refs") or [])],
            document_ids=[int(item) for item in (data.get("document_ids") or []) if str(item).isdigit()],
            source_doc_ids=[int(item) for item in (data.get("source_doc_ids") or []) if str(item).isdigit()],
            read_reason=str(data.get("read_reason") or ""),
            expected_confirmation=str(data.get("expected_confirmation") or ""),
            affects_analysis=str(data.get("affects_analysis") or ""),
            excerpt_focus=[str(item) for item in (data.get("excerpt_focus") or [])],
            chapter_read_plan=[
                ChapterReadPlan.from_mapping(item)
                for item in (data.get("chapter_read_plan") or data.get("chapters") or [])
                if isinstance(item, Mapping)
            ],
            metadata=dict(data.get("metadata") or {}) if isinstance(data.get("metadata"), Mapping) else {},
        )


@dataclass(slots=True)
class EvidenceBundle:
    request_id: str
    request_type: NarrativeInquiryRequestType
    query: str
    status: EvidenceBundleStatus = "found"
    fact_status: EvidenceFactStatus = "candidate"
    evidence_items: list[dict[str, Any]] = field(default_factory=list)
    chapter_refs: list[str] = field(default_factory=list)
    source_doc_ids: list[int] = field(default_factory=list)
    excerpts: list[dict[str, Any]] = field(default_factory=list)
    sources: list[dict[str, Any]] = field(default_factory=list)
    missing_facets: list[str] = field(default_factory=list)
    trace: list[dict[str, Any]] = field(default_factory=list)

    def __post_init__(self) -> None:
        self.request_id = _text(self.request_id)
        request_type = _text(self.request_type).lower()
        if request_type not in REQUEST_TYPES:
            raise ValueError("request_type must be a supported Narrative Inquiry type")
        self.request_type = cast(NarrativeInquiryRequestType, request_type)
        self.query = _text(self.query)
        status = _text(self.status).lower() or "found"
        if status not in BUNDLE_STATUSES:
            raise ValueError("status must be found, missing, blocked, budget_limited, or failed")
        self.status = cast(EvidenceBundleStatus, status)
        fact_status = _text(self.fact_status).lower() or "candidate"
        if fact_status not in FACT_STATUSES:
            raise ValueError("fact_status must be confirmed, candidate, missing, conflicting, or insufficient_context")
        self.fact_status = cast(EvidenceFactStatus, fact_status)
        self.evidence_items = _dict_list(self.evidence_items)
        self.chapter_refs = _string_list(self.chapter_refs)
        self.source_doc_ids = _int_list(self.source_doc_ids)
        self.excerpts = _dict_list(self.excerpts)
        self.sources = _dict_list(self.sources)
        self.missing_facets = _string_list(self.missing_facets)
        self.trace = _dict_list(self.trace)

    def to_dict(self) -> dict[str, Any]:
        return {
            "request_id": self.request_id,
            "request_type": self.request_type,
            "query": self.query,
            "status": self.status,
            "fact_status": self.fact_status,
            "evidence_items": [dict(item) for item in self.evidence_items],
            "chapter_refs": list(self.chapter_refs),
            "source_doc_ids": list(self.source_doc_ids),
            "excerpts": [dict(item) for item in self.excerpts],
            "sources": [dict(item) for item in self.sources],
            "missing_facets": list(self.missing_facets),
            "trace": [dict(item) for item in self.trace],
        }

    @classmethod
    def missing(cls, request: NarrativeInquiryRequest, *missing_facets: str) -> "EvidenceBundle":
        return cls(
            request_id=request.request_id,
            request_type=request.request_type,
            query=request.query or request.name or request.concept,
            status="missing",
            fact_status="missing",
            missing_facets=[facet for facet in missing_facets if facet],
        )


@dataclass(slots=True)
class AnalyzerBudget:
    max_rounds: int = 8
    max_requests_per_round: int = 4
    max_total_requests: int = 24
    max_raw_excerpt_requests: int = 6
    max_raw_excerpt_chars_per_request: int = 3000
    max_evidence_chars_per_request: int = 2500
    max_prompt_bytes: int = 65536
    max_json_retries: int = 1

    def __post_init__(self) -> None:
        self.max_rounds = max(1, int(self.max_rounds or 1))
        self.max_requests_per_round = max(1, int(self.max_requests_per_round or 1))
        self.max_total_requests = max(1, int(self.max_total_requests or 1))
        self.max_raw_excerpt_requests = max(0, int(self.max_raw_excerpt_requests or 0))
        self.max_raw_excerpt_chars_per_request = max(1, int(self.max_raw_excerpt_chars_per_request or 1))
        self.max_evidence_chars_per_request = max(160, int(self.max_evidence_chars_per_request or 160))
        self.max_prompt_bytes = max(4096, int(self.max_prompt_bytes or 4096))
        self.max_json_retries = max(0, int(self.max_json_retries or 0))

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(slots=True)
class AnalyzerSeedPacket:
    book_id: str
    user_question: str
    conversation_brief: str = ""
    modeling_status: dict[str, bool] = field(default_factory=dict)
    story_overview: str = ""
    outline_index: list[dict[str, Any]] = field(default_factory=list)
    source_arc_index: list[dict[str, Any]] = field(default_factory=list)
    character_index: list[dict[str, Any]] = field(default_factory=list)
    world_concept_index: list[dict[str, Any]] = field(default_factory=list)
    chapter_index: list[dict[str, Any]] = field(default_factory=list)
    memory_page_roots: list[dict[str, Any]] = field(default_factory=list)
    sources: list[dict[str, Any]] = field(default_factory=list)

    def __post_init__(self) -> None:
        self.book_id = _text(self.book_id)
        self.user_question = _text(self.user_question)
        self.conversation_brief = _text(self.conversation_brief)
        self.modeling_status = {str(key): bool(value) for key, value in self.modeling_status.items()}
        self.story_overview = _text(self.story_overview)
        self.outline_index = _dict_list(self.outline_index)
        self.source_arc_index = _dict_list(self.source_arc_index)
        self.character_index = _dict_list(self.character_index)
        self.world_concept_index = _dict_list(self.world_concept_index)
        self.chapter_index = _dict_list(self.chapter_index)
        self.memory_page_roots = _dict_list(self.memory_page_roots)
        self.sources = _dict_list(self.sources)
        if not self.book_id or not self.user_question:
            raise ValueError("book_id and user_question are required")

    def to_dict(self) -> dict[str, Any]:
        return {
            "book_id": self.book_id,
            "user_question": self.user_question,
            "conversation_brief": self.conversation_brief,
            "modeling_status": dict(self.modeling_status),
            "story_overview": self.story_overview,
            "outline_index": [dict(item) for item in self.outline_index],
            "source_arc_index": [dict(item) for item in self.source_arc_index],
            "character_index": [dict(item) for item in self.character_index],
            "world_concept_index": [dict(item) for item in self.world_concept_index],
            "chapter_index": [dict(item) for item in self.chapter_index],
            "memory_page_roots": [dict(item) for item in self.memory_page_roots],
            "sources": [dict(item) for item in self.sources],
        }


@dataclass(slots=True)
class AnalyzerNotebook:
    confirmed_facts: list[str] = field(default_factory=list)
    reasonable_inferences: list[str] = field(default_factory=list)
    uncertain_gaps: list[str] = field(default_factory=list)
    open_threads: list[str] = field(default_factory=list)
    candidate_directions: list[str] = field(default_factory=list)
    blocked_directions: list[str] = field(default_factory=list)
    chapters_worth_raw_read: list[dict[str, Any]] = field(default_factory=list)
    user_preferences: list[str] = field(default_factory=list)
    evidence_bundles: list[EvidenceBundle] = field(default_factory=list)

    def apply_delta(self, delta: Mapping[str, Any] | None) -> None:
        if not isinstance(delta, Mapping):
            return
        for field_name in (
            "confirmed_facts",
            "reasonable_inferences",
            "uncertain_gaps",
            "open_threads",
            "candidate_directions",
            "blocked_directions",
            "user_preferences",
        ):
            values = _string_list(delta.get(field_name))
            target = getattr(self, field_name)
            for value in values:
                if value not in target:
                    target.append(value)
        for item in _dict_list(delta.get("chapters_worth_raw_read")):
            if item not in self.chapters_worth_raw_read:
                self.chapters_worth_raw_read.append(item)

    def add_evidence(self, bundles: Sequence[EvidenceBundle]) -> None:
        self.evidence_bundles.extend(bundles)
        for bundle in bundles:
            if bundle.fact_status in {"missing", "insufficient_context", "conflicting"}:
                gap = bundle.query or bundle.request_id
                if gap and gap not in self.uncertain_gaps:
                    self.uncertain_gaps.append(gap)
                continue
            snippets = []
            for item in bundle.evidence_items[:2]:
                summary = _text(item.get("summary") or item.get("title") or item)
                if summary:
                    snippets.append(summary)
            if snippets:
                target = self.confirmed_facts if bundle.fact_status == "confirmed" else self.reasonable_inferences
                claim = "；".join(snippets)
                if claim not in target:
                    target.append(claim)

    def to_dict(self) -> dict[str, Any]:
        return {
            "confirmed_facts": list(self.confirmed_facts),
            "reasonable_inferences": list(self.reasonable_inferences),
            "uncertain_gaps": list(self.uncertain_gaps),
            "open_threads": list(self.open_threads),
            "candidate_directions": list(self.candidate_directions),
            "blocked_directions": list(self.blocked_directions),
            "chapters_worth_raw_read": [dict(item) for item in self.chapters_worth_raw_read],
            "user_preferences": list(self.user_preferences),
            "evidence_bundles": [bundle.to_dict() for bundle in self.evidence_bundles],
        }


@dataclass(slots=True)
class AnalyzerLoopOutput:
    status: AnalyzerLoopStatus
    requests: list[NarrativeInquiryRequest] = field(default_factory=list)
    notebook_delta: dict[str, Any] = field(default_factory=dict)
    final_answer: str = ""
    message: str = ""

    def __post_init__(self) -> None:
        status = _text(self.status).lower()
        if status not in LOOP_STATUSES:
            raise ValueError("Analyzer loop status is unsupported")
        self.status = cast(AnalyzerLoopStatus, status)
        self.requests = [
            item if isinstance(item, NarrativeInquiryRequest) else NarrativeInquiryRequest.from_mapping(item, index=index)
            for index, item in enumerate(self.requests, start=1)
            if isinstance(item, (NarrativeInquiryRequest, Mapping))
        ]
        self.notebook_delta = dict(self.notebook_delta) if isinstance(self.notebook_delta, Mapping) else {}
        self.final_answer = _text(self.final_answer)
        self.message = _text(self.message)

    @classmethod
    def from_mapping(cls, data: Mapping[str, Any]) -> "AnalyzerLoopOutput":
        status = cast(AnalyzerLoopStatus, str(data.get("status") or ""))
        requests: list[NarrativeInquiryRequest] = []
        invalid_request_errors: list[str] = []
        raw_requests = data.get("requests") or []
        for index, item in enumerate(raw_requests, start=1):
            if not isinstance(item, Mapping):
                continue
            try:
                requests.append(NarrativeInquiryRequest.from_mapping(item, index=index))
            except ValueError as exc:
                invalid_request_errors.append(f"request {index}: {exc}")
        if str(status).lower() == "need_more_info" and not requests:
            detail = "; ".join(invalid_request_errors) or "requests is empty"
            raise ValueError(f"need_more_info requires at least one valid Narrative Inquiry request: {detail}")
        return cls(
            status=status,
            requests=requests,
            notebook_delta=dict(data.get("notebook_delta") or {}) if isinstance(data.get("notebook_delta"), Mapping) else {},
            final_answer=str(data.get("final_answer") or data.get("answer") or ""),
            message=str(data.get("message") or ""),
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "status": self.status,
            "requests": [request.to_dict() for request in self.requests],
            "notebook_delta": dict(self.notebook_delta),
            "final_answer": self.final_answer,
            "message": self.message,
        }

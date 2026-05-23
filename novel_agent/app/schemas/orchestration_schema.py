from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from typing import Any, Literal, Mapping, Sequence, cast

from .context_assembly_schema import ContextAssemblyPayload
from .creative_kb_schema import SceneBrief


EVIDENCE_LEVELS = {
    "original_fact",
    "confirmed_analysis",
    "structured_state",
    "reasonable_inference",
}
EVIDENCE_LEVEL_ALIASES = {
    "original": "original_fact",
    "fact": "original_fact",
    "source_fact": "original_fact",
    "text_fact": "original_fact",
    "原文事实": "original_fact",
    "原文证据": "original_fact",
    "confirmed": "confirmed_analysis",
    "analysis": "confirmed_analysis",
    "confirmed fact": "confirmed_analysis",
    "confirmed_fact": "confirmed_analysis",
    "confirmed analysis": "confirmed_analysis",
    "已确认分析": "confirmed_analysis",
    "确认分析": "confirmed_analysis",
    "structured": "structured_state",
    "state": "structured_state",
    "structured state": "structured_state",
    "memory_state": "structured_state",
    "结构化状态": "structured_state",
    "记忆状态": "structured_state",
    "inference": "reasonable_inference",
    "inferred": "reasonable_inference",
    "reasonable inference": "reasonable_inference",
    "reasonable-inference": "reasonable_inference",
    "合理推断": "reasonable_inference",
    "推断": "reasonable_inference",
}
FREEZE_STAGES = ("freeze_a", "freeze_b", "freeze_c", "freeze_d", "freeze_e")
FREEZE_STAGE_TO_DOWNSTREAM = {
    "freeze_a": ["freeze_b", "freeze_c", "freeze_d", "freeze_e"],
    "freeze_b": ["freeze_c", "freeze_d", "freeze_e"],
    "freeze_c": ["freeze_d", "freeze_e"],
    "freeze_d": ["freeze_e"],
    "freeze_e": [],
}
FREEZE_ARTIFACT_KINDS = {"json", "text", "markdown"}
FREEZE_RECORD_STATUSES = {"frozen", "invalidated"}
WRITER_AGENT_STATES = {
    "agent_running",
    "reviewing_artifact",
    "needs_user_input",
    "generating_draft",
    "reviewing_draft",
    "writeback_review",
    "completed",
    "halted",
    "error",
}
ARTIFACT_REVIEW_DECISIONS = {"approved", "revision_requested", "deferred"}
ARTIFACT_REVIEW_NEXT_ACTIONS = {
    "continue_agent_loop",
    "revise_artifact",
    "defer_review",
}
WRITER_LOOP_EVENT_KINDS = {
    "local_tool_call",
    "user_question",
    "artifact_generated",
    "artifact_review",
    "draft_review",
    "writeback_review",
}
WRITER_LOOP_STEP_STATUSES = {
    "started",
    "completed",
    "waiting",
    "failed",
}
GENERATION_REVIEW_STATUSES = {
    "accepted",
    "rewrite_requested",
    "replan_requested",
    "discarded",
}
LEGACY_GENERATION_REVIEW_STATUS_ALIASES = {
    "revise_length": "rewrite_requested",
    "replan_chapter": "replan_requested",
}
GENERATION_REVIEW_CHECKPOINTS = {
    "freeze_e",
    "wait_length_review",
    "wait_chapter_review",
    "halted",
}
GENERATION_REVIEW_NEXT_ACTIONS = {
    "writeback_review",
    "agent_loop_rewrite_draft",
    "agent_loop_replan_chapter",
    "halted",
}
LEGACY_GENERATION_REVIEW_CHECKPOINT_TO_ACTION = {
    "freeze_e": "writeback_review",
    "wait_length_review": "agent_loop_rewrite_draft",
    "wait_chapter_review": "agent_loop_replan_chapter",
    "halted": "halted",
}
CHAPTER_REPLAN_SCOPES = {"current_chapter"}
FACT_STATUSES = {
    "confirmed",
    "candidate",
    "assumption",
    "user_authorized",
    "missing",
}
RESEARCH_REQUEST_TYPES = {
    "story_detail",
    "character_profile",
    "world_concept",
    "structure_pattern",
}
RESEARCH_PRIORITIES = {"high", "medium", "low"}
CHARACTER_MENTION_STATUSES = {"resolved", "ambiguous", "missing"}
CHARACTER_MENTION_TYPES = {"name", "alias", "title", "new_character_hint"}
SUFFICIENCY_STATUSES = {
    "enough",
    "needs_user_input",
    "proceed_with_assumptions",
    "blocked",
}
OUTLINE_RESEARCH_QUESTION_SET_STATUSES = {"pending", "submitted", "deferred"}


def _normalize_text(value: object) -> str:
    return str(value).strip()


def _normalize_string_list(items: Sequence[object]) -> list[str]:
    normalized: list[str] = []
    seen: set[str] = set()
    for item in items:
        text = _normalize_text(item)
        if not text or text in seen:
            continue
        normalized.append(text)
        seen.add(text)
    return normalized


def _normalize_evidence_level(value: object) -> str:
    normalized_level = _normalize_text(value).lower()
    normalized_level = normalized_level.replace("-", "_")
    if normalized_level in EVIDENCE_LEVELS:
        return normalized_level
    alias_key = normalized_level.replace("_", " ")
    return EVIDENCE_LEVEL_ALIASES.get(normalized_level) or EVIDENCE_LEVEL_ALIASES.get(alias_key) or normalized_level


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


FreezeStage = Literal["freeze_a", "freeze_b", "freeze_c", "freeze_d", "freeze_e"]
WriterAgentState = Literal[
    "agent_running",
    "reviewing_artifact",
    "needs_user_input",
    "generating_draft",
    "reviewing_draft",
    "writeback_review",
    "completed",
    "halted",
    "error",
]
ArtifactReviewDecisionValue = Literal["approved", "revision_requested", "deferred"]
ArtifactReviewNextAction = Literal["continue_agent_loop", "revise_artifact", "defer_review"]
WriterLoopEventKind = Literal[
    "local_tool_call",
    "user_question",
    "artifact_generated",
    "artifact_review",
    "draft_review",
    "writeback_review",
]
WriterLoopStepStatus = Literal["started", "completed", "waiting", "failed"]
EvidenceLevel = Literal[
    "original_fact",
    "confirmed_analysis",
    "structured_state",
    "reasonable_inference",
]
FreezeArtifactKind = Literal["json", "text", "markdown"]
FreezeRecordStatus = Literal["frozen", "invalidated"]
GenerationReviewStatus = Literal[
    "accepted",
    "rewrite_requested",
    "replan_requested",
    "discarded",
]
GenerationReviewCheckpoint = Literal[
    "freeze_e",
    "wait_length_review",
    "wait_chapter_review",
    "halted",
]
ChapterReplanScope = Literal["current_chapter"]
FactStatus = Literal["confirmed", "candidate", "assumption", "user_authorized", "missing"]
ResearchRequestType = Literal["story_detail", "character_profile", "world_concept", "structure_pattern"]
ResearchPriority = Literal["high", "medium", "low"]
CharacterMentionStatus = Literal["resolved", "ambiguous", "missing"]
CharacterMentionType = Literal["name", "alias", "title", "new_character_hint"]
SufficiencyStatus = Literal["enough", "needs_user_input", "proceed_with_assumptions", "blocked"]
OutlineResearchQuestionSetStatus = Literal["pending", "submitted", "deferred"]


@dataclass(slots=True)
class TraceableSource:
    type: str
    path: str
    evidence_level: EvidenceLevel = "confirmed_analysis"
    snippet: str = ""
    note: str = ""

    def __post_init__(self) -> None:
        self.type = _normalize_text(self.type)
        self.path = _normalize_text(self.path)
        normalized_level = _normalize_evidence_level(self.evidence_level)
        if normalized_level not in EVIDENCE_LEVELS:
            raise ValueError("evidence_level must be a supported value")
        self.evidence_level = normalized_level  # type: ignore[assignment]
        self.snippet = _normalize_text(self.snippet)
        self.note = _normalize_text(self.note)

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["legacy_migration_only"] = True
        return payload


def _normalize_fact_status(value: object) -> str:
    normalized = _normalize_text(value).lower().replace("-", "_")
    aliases = {
        "confirmed_fact": "confirmed",
        "fact": "confirmed",
        "inferred": "candidate",
        "inference": "candidate",
        "user": "user_authorized",
        "authorized": "user_authorized",
        "user_authorised": "user_authorized",
        "unknown": "missing",
    }
    return aliases.get(normalized, normalized)


def _normalize_generation_review_status(value: object) -> tuple[str, str]:
    normalized = _normalize_text(value).lower().replace("-", "_")
    migrated = LEGACY_GENERATION_REVIEW_STATUS_ALIASES.get(normalized, normalized)
    return migrated, normalized if migrated != normalized else ""


def _coerce_sources(items: Sequence[object] | None) -> list[TraceableSource]:
    sources: list[TraceableSource] = []
    for item in items or []:
        if isinstance(item, TraceableSource):
            sources.append(item)
            continue
        if isinstance(item, Mapping):
            sources.append(
                TraceableSource(
                    type=str(item.get("type") or "unknown"),
                    path=str(item.get("path") or ""),
                    evidence_level=cast(EvidenceLevel, str(item.get("evidence_level") or "confirmed_analysis")),
                    snippet=str(item.get("snippet") or ""),
                    note=str(item.get("note") or ""),
                )
            )
    return sources


@dataclass(slots=True)
class ExtractedCharacterMention:
    text: str
    mention_type: CharacterMentionType = "name"
    source_text: str = ""
    confidence: float = 0.5
    possible_role_hint: str = ""

    def __post_init__(self) -> None:
        self.text = _normalize_text(self.text)
        normalized_type = _normalize_text(self.mention_type).lower()
        if normalized_type not in CHARACTER_MENTION_TYPES:
            raise ValueError("mention_type must be name, alias, title, or new_character_hint")
        self.mention_type = normalized_type  # type: ignore[assignment]
        self.source_text = _normalize_text(self.source_text)
        self.confidence = max(0.0, min(float(self.confidence or 0), 1.0))
        self.possible_role_hint = _normalize_text(self.possible_role_hint)
        if not self.text:
            raise ValueError("character mention text is required")

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["legacy_migration_only"] = True
        return payload

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "ExtractedCharacterMention":
        return cls(
            text=str(data.get("text") or ""),
            mention_type=cast(CharacterMentionType, str(data.get("mention_type") or "name")),
            source_text=str(data.get("source_text") or ""),
            confidence=float(data.get("confidence") or 0.5),
            possible_role_hint=str(data.get("possible_role_hint") or ""),
        )


@dataclass(slots=True)
class ExtractedCharacterMentions:
    mentions: list[ExtractedCharacterMention] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {"mentions": [item.to_dict() for item in self.mentions]}

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "ExtractedCharacterMentions":
        return cls(
            mentions=[
                ExtractedCharacterMention.from_dict(item)
                for item in (data.get("mentions") or [])
                if isinstance(item, Mapping)
            ]
        )


@dataclass(slots=True)
class CharacterMentionResolution:
    mention_text: str
    status: CharacterMentionStatus
    character_id: str = ""
    canonical_name: str = ""
    matched_by: list[str] = field(default_factory=list)
    candidate_matches: list[dict[str, Any]] = field(default_factory=list)
    user_question: str = ""
    confirmed_new_character: bool = False

    def __post_init__(self) -> None:
        self.mention_text = _normalize_text(self.mention_text)
        normalized_status = _normalize_text(self.status).lower()
        if normalized_status not in CHARACTER_MENTION_STATUSES:
            raise ValueError("status must be resolved, ambiguous, or missing")
        self.status = normalized_status  # type: ignore[assignment]
        self.character_id = _normalize_text(self.character_id)
        self.canonical_name = _normalize_text(self.canonical_name)
        self.matched_by = _normalize_string_list(self.matched_by)
        self.candidate_matches = [
            {str(key): value for key, value in item.items()}
            for item in self.candidate_matches
            if isinstance(item, Mapping)
        ]
        self.user_question = _normalize_text(self.user_question)
        if self.status == "resolved" and not self.character_id:
            raise ValueError("resolved character mention must include character_id")
        if self.status == "ambiguous" and not self.candidate_matches:
            raise ValueError("ambiguous character mention must include candidate_matches")

    def to_dict(self) -> dict[str, Any]:
        return {
            "mention_text": self.mention_text,
            "status": self.status,
            "character_id": self.character_id,
            "canonical_name": self.canonical_name,
            "matched_by": list(self.matched_by),
            "candidate_matches": [dict(item) for item in self.candidate_matches],
            "user_question": self.user_question,
            "confirmed_new_character": self.confirmed_new_character,
        }

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "CharacterMentionResolution":
        return cls(
            mention_text=str(data.get("mention_text") or data.get("text") or ""),
            status=cast(CharacterMentionStatus, str(data.get("status") or "missing")),
            character_id=str(data.get("character_id") or data.get("resolved_character_id") or ""),
            canonical_name=str(data.get("canonical_name") or ""),
            matched_by=[str(item) for item in (data.get("matched_by") or [])],
            candidate_matches=[
                dict(item) for item in (data.get("candidate_matches") or []) if isinstance(item, Mapping)
            ],
            user_question=str(data.get("user_question") or ""),
            confirmed_new_character=bool(data.get("confirmed_new_character", False)),
        )


@dataclass(slots=True)
class OutlineSeedPacket:
    packet_id: str
    book_id: str
    user_intent: dict[str, Any]
    story_scale: dict[str, Any] = field(default_factory=dict)
    climax_input: dict[str, Any] = field(default_factory=dict)
    extracted_character_mentions: list[ExtractedCharacterMention] = field(default_factory=list)
    character_resolutions: list[CharacterMentionResolution] = field(default_factory=list)
    character_index: list[dict[str, Any]] = field(default_factory=list)
    world_overview: str = ""
    world_concept_index: list[dict[str, Any]] = field(default_factory=list)
    historical_story_overview: list[dict[str, Any]] = field(default_factory=list)
    current_continuation_anchor: str = ""
    optional_open_thread_index: list[dict[str, Any]] = field(default_factory=list)
    source_arc_index: list[dict[str, Any]] = field(default_factory=list)
    structure_pattern_index: list[dict[str, Any]] = field(default_factory=list)
    sources: list[TraceableSource] = field(default_factory=list)

    def __post_init__(self) -> None:
        self.packet_id = _normalize_text(self.packet_id)
        self.book_id = _normalize_text(self.book_id)
        if not self.packet_id or not self.book_id:
            raise ValueError("packet_id and book_id are required")
        self.user_intent = dict(self.user_intent)
        self.story_scale = dict(self.story_scale)
        self.climax_input = dict(self.climax_input)
        self.character_index = self._normalize_index_list(self.character_index)
        self.world_overview = _normalize_text(self.world_overview)
        self.world_concept_index = self._normalize_index_list(self.world_concept_index)
        self.historical_story_overview = self._normalize_index_list(self.historical_story_overview)
        self.current_continuation_anchor = _normalize_text(self.current_continuation_anchor)
        self.optional_open_thread_index = self._normalize_index_list(self.optional_open_thread_index)
        self.source_arc_index = self._normalize_index_list(self.source_arc_index)
        self.structure_pattern_index = self._normalize_index_list(self.structure_pattern_index)

    @staticmethod
    def _normalize_index_list(items: Sequence[object]) -> list[dict[str, Any]]:
        return [
            {str(key): value for key, value in item.items()}
            for item in items
            if isinstance(item, Mapping)
        ]

    def to_dict(self) -> dict[str, Any]:
        return {
            "packet_id": self.packet_id,
            "book_id": self.book_id,
            "user_intent": dict(self.user_intent),
            "story_scale": dict(self.story_scale),
            "climax_input": dict(self.climax_input),
            "extracted_character_mentions": [item.to_dict() for item in self.extracted_character_mentions],
            "character_resolutions": [item.to_dict() for item in self.character_resolutions],
            "character_index": [dict(item) for item in self.character_index],
            "world_overview": self.world_overview,
            "world_concept_index": [dict(item) for item in self.world_concept_index],
            "historical_story_overview": [dict(item) for item in self.historical_story_overview],
            "current_continuation_anchor": self.current_continuation_anchor,
            "optional_open_thread_index": [dict(item) for item in self.optional_open_thread_index],
            "source_arc_index": [dict(item) for item in self.source_arc_index],
            "structure_pattern_index": [dict(item) for item in self.structure_pattern_index],
            "sources": [item.to_dict() for item in self.sources],
        }

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "OutlineSeedPacket":
        return cls(
            packet_id=str(data.get("packet_id") or ""),
            book_id=str(data.get("book_id") or ""),
            user_intent=dict(data.get("user_intent") or {}),
            story_scale=dict(data.get("story_scale") or {}),
            climax_input=dict(data.get("climax_input") or {}),
            extracted_character_mentions=[
                ExtractedCharacterMention.from_dict(item)
                for item in (data.get("extracted_character_mentions") or [])
                if isinstance(item, Mapping)
            ],
            character_resolutions=[
                CharacterMentionResolution.from_dict(item)
                for item in (data.get("character_resolutions") or [])
                if isinstance(item, Mapping)
            ],
            character_index=[dict(item) for item in (data.get("character_index") or []) if isinstance(item, Mapping)],
            world_overview=str(data.get("world_overview") or ""),
            world_concept_index=[
                dict(item) for item in (data.get("world_concept_index") or []) if isinstance(item, Mapping)
            ],
            historical_story_overview=[
                dict(item) for item in (data.get("historical_story_overview") or []) if isinstance(item, Mapping)
            ],
            current_continuation_anchor=str(data.get("current_continuation_anchor") or ""),
            optional_open_thread_index=[
                dict(item) for item in (data.get("optional_open_thread_index") or []) if isinstance(item, Mapping)
            ],
            source_arc_index=[dict(item) for item in (data.get("source_arc_index") or []) if isinstance(item, Mapping)],
            structure_pattern_index=[
                dict(item) for item in (data.get("structure_pattern_index") or []) if isinstance(item, Mapping)
            ],
            sources=_coerce_sources(cast(Sequence[object], data.get("sources") or [])),
        )


@dataclass(slots=True)
class ResearchRequest:
    request_id: str
    request_type: ResearchRequestType
    query: str
    purpose: str = ""
    priority: ResearchPriority = "medium"
    name: str = ""
    concept: str = ""
    facets_needed: list[str] = field(default_factory=list)

    def __post_init__(self) -> None:
        self.request_id = _normalize_text(self.request_id)
        normalized_type = _normalize_text(self.request_type).lower()
        if normalized_type not in RESEARCH_REQUEST_TYPES:
            raise ValueError("request_type must be story_detail, character_profile, world_concept, or structure_pattern")
        self.request_type = normalized_type  # type: ignore[assignment]
        self.query = _normalize_text(self.query)
        self.purpose = _normalize_text(self.purpose)
        normalized_priority = _normalize_text(self.priority).lower() or "medium"
        if normalized_priority not in RESEARCH_PRIORITIES:
            raise ValueError("priority must be high, medium, or low")
        self.priority = normalized_priority  # type: ignore[assignment]
        self.name = _normalize_text(self.name)
        self.concept = _normalize_text(self.concept)
        self.facets_needed = _normalize_string_list(self.facets_needed)
        if not self.request_id:
            self.request_id = f"{self.request_type}:{self.query or self.name or self.concept}"
        if not (self.query or self.name or self.concept):
            raise ValueError("research request requires query, name, or concept")

    @property
    def dedupe_key(self) -> str:
        target = self.name if self.request_type == "character_profile" else self.concept if self.request_type == "world_concept" else self.query
        return f"{self.request_type}:{_normalize_text(target).lower()}"

    def to_dict(self) -> dict[str, Any]:
        return {
            "request_id": self.request_id,
            "request_type": self.request_type,
            "query": self.query,
            "purpose": self.purpose,
            "priority": self.priority,
            "name": self.name,
            "concept": self.concept,
            "facets_needed": list(self.facets_needed),
        }

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "ResearchRequest":
        return cls(
            request_id=str(data.get("request_id") or data.get("id") or ""),
            request_type=cast(ResearchRequestType, str(data.get("request_type") or data.get("type") or "")),
            query=str(data.get("query") or ""),
            purpose=str(data.get("purpose") or ""),
            priority=cast(ResearchPriority, str(data.get("priority") or "medium")),
            name=str(data.get("name") or ""),
            concept=str(data.get("concept") or ""),
            facets_needed=[str(item) for item in (data.get("facets_needed") or [])],
        )


@dataclass(slots=True)
class ResearchBudget:
    max_rounds: int = 3
    max_requests_per_round: int = 4
    max_total_requests: int = 10
    max_return_tokens_per_request: int = 700

    def __post_init__(self) -> None:
        self.max_rounds = max(1, int(self.max_rounds or 1))
        self.max_requests_per_round = max(1, int(self.max_requests_per_round or 1))
        self.max_total_requests = max(1, int(self.max_total_requests or 1))
        self.max_return_tokens_per_request = max(64, int(self.max_return_tokens_per_request or 64))

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["legacy_migration_only"] = True
        return payload


@dataclass(slots=True)
class StoryDetailResult:
    request_id: str
    matches: list[dict[str, Any]] = field(default_factory=list)
    confidence: float = 0.0
    covered_facets: list[str] = field(default_factory=list)
    missing_facets: list[str] = field(default_factory=list)
    fact_status: FactStatus = "candidate"
    sources: list[TraceableSource] = field(default_factory=list)

    def __post_init__(self) -> None:
        self.request_id = _normalize_text(self.request_id)
        self.matches = [
            {str(key): value for key, value in item.items()}
            for item in self.matches
            if isinstance(item, Mapping)
        ]
        self.confidence = max(0.0, min(float(self.confidence or 0), 1.0))
        self.covered_facets = _normalize_string_list(self.covered_facets)
        self.missing_facets = _normalize_string_list(self.missing_facets)
        normalized_status = _normalize_fact_status(self.fact_status)
        if normalized_status not in FACT_STATUSES:
            raise ValueError("fact_status must be confirmed, candidate, assumption, user_authorized, or missing")
        self.fact_status = normalized_status  # type: ignore[assignment]

    def to_dict(self) -> dict[str, Any]:
        return {
            "request_id": self.request_id,
            "matches": [dict(item) for item in self.matches],
            "confidence": self.confidence,
            "covered_facets": list(self.covered_facets),
            "missing_facets": list(self.missing_facets),
            "fact_status": self.fact_status,
            "sources": [item.to_dict() for item in self.sources],
        }


@dataclass(slots=True)
class ResearchResult:
    request_id: str
    request_type: ResearchRequestType
    query: str
    results: list[dict[str, Any]] = field(default_factory=list)
    fact_status: FactStatus = "candidate"
    sources: list[TraceableSource] = field(default_factory=list)
    confidence: float = 0.0
    covered_facets: list[str] = field(default_factory=list)
    missing_facets: list[str] = field(default_factory=list)
    token_estimate: int = 0
    summary_size: int = 0
    downgraded: bool = False

    def __post_init__(self) -> None:
        self.request_id = _normalize_text(self.request_id)
        normalized_type = _normalize_text(self.request_type).lower()
        if normalized_type not in RESEARCH_REQUEST_TYPES:
            raise ValueError("request_type must be a supported research request type")
        self.request_type = normalized_type  # type: ignore[assignment]
        self.query = _normalize_text(self.query)
        self.results = [
            {str(key): value for key, value in item.items()}
            for item in self.results
            if isinstance(item, Mapping)
        ]
        normalized_status = _normalize_fact_status(self.fact_status)
        if normalized_status not in FACT_STATUSES:
            raise ValueError("fact_status must be confirmed, candidate, assumption, user_authorized, or missing")
        self.fact_status = normalized_status  # type: ignore[assignment]
        self.confidence = max(0.0, min(float(self.confidence or 0), 1.0))
        self.covered_facets = _normalize_string_list(self.covered_facets)
        self.missing_facets = _normalize_string_list(self.missing_facets)
        self.token_estimate = max(0, int(self.token_estimate or 0))
        self.summary_size = max(0, int(self.summary_size or 0))

    def to_dict(self) -> dict[str, Any]:
        return {
            "request_id": self.request_id,
            "request_type": self.request_type,
            "query": self.query,
            "results": [dict(item) for item in self.results],
            "fact_status": self.fact_status,
            "sources": [item.to_dict() for item in self.sources],
            "confidence": self.confidence,
            "covered_facets": list(self.covered_facets),
            "missing_facets": list(self.missing_facets),
            "token_estimate": self.token_estimate,
            "summary_size": self.summary_size,
            "downgraded": self.downgraded,
        }

    @classmethod
    def from_story_detail(cls, detail: StoryDetailResult, *, request_type: ResearchRequestType, query: str) -> "ResearchResult":
        return cls(
            request_id=detail.request_id,
            request_type=request_type,
            query=query,
            results=detail.matches,
            fact_status=detail.fact_status,
            sources=detail.sources,
            confidence=detail.confidence,
            covered_facets=detail.covered_facets,
            missing_facets=detail.missing_facets,
            summary_size=sum(len(str(item)) for item in detail.matches),
        )


@dataclass(slots=True)
class PlanningFact:
    claim: str
    fact_status: FactStatus
    sources: list[TraceableSource] = field(default_factory=list)
    confidence: float = 0.0
    note: str = ""

    def __post_init__(self) -> None:
        self.claim = _normalize_text(self.claim)
        normalized_status = _normalize_fact_status(self.fact_status)
        if normalized_status not in FACT_STATUSES:
            raise ValueError("fact_status must be confirmed, candidate, assumption, user_authorized, or missing")
        self.fact_status = normalized_status  # type: ignore[assignment]
        self.confidence = max(0.0, min(float(self.confidence or 0), 1.0))
        self.note = _normalize_text(self.note)

    def to_dict(self) -> dict[str, Any]:
        return {
            "claim": self.claim,
            "fact_status": self.fact_status,
            "sources": [item.to_dict() for item in self.sources],
            "confidence": self.confidence,
            "note": self.note,
        }

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "PlanningFact":
        return cls(
            claim=str(data.get("claim") or ""),
            fact_status=cast(FactStatus, str(data.get("fact_status") or "candidate")),
            sources=_coerce_sources(cast(Sequence[object], data.get("sources") or [])),
            confidence=float(data.get("confidence") or 0),
            note=str(data.get("note") or ""),
        )


@dataclass(slots=True)
class PlanningNotebook:
    notebook_id: str
    confirmed_facts: list[PlanningFact] = field(default_factory=list)
    candidate_facts: list[PlanningFact] = field(default_factory=list)
    constraints: list[PlanningFact] = field(default_factory=list)
    candidate_plot_moves: list[PlanningFact] = field(default_factory=list)
    blocked_plot_moves: list[PlanningFact] = field(default_factory=list)
    open_questions: list[str] = field(default_factory=list)
    assumptions: list[PlanningFact] = field(default_factory=list)

    def __post_init__(self) -> None:
        self.notebook_id = _normalize_text(self.notebook_id)
        if not self.notebook_id:
            raise ValueError("notebook_id is required")
        self.open_questions = _normalize_string_list(self.open_questions)

    def add_research_result(self, result: ResearchResult) -> None:
        if result.fact_status == "missing":
            for facet in result.missing_facets or [result.query]:
                if facet and facet not in self.open_questions:
                    self.open_questions.append(facet)
            return
        summary = "; ".join(str(item.get("summary") or item.get("claim") or item.get("title") or item) for item in result.results[:2])
        fact = PlanningFact(
            claim=summary or result.query,
            fact_status=result.fact_status,
            sources=result.sources,
            confidence=result.confidence,
            note=f"{result.request_type}:{result.request_id}",
        )
        if result.fact_status in {"confirmed", "user_authorized"}:
            self.confirmed_facts.append(fact)
            return
        if result.fact_status == "assumption":
            self.assumptions.append(fact)
            return
        self.candidate_facts.append(fact)

    def add_user_answer(self, *, question: str, answer: str, source_path: str = "interactive:outline_research_answer") -> None:
        question_text = _normalize_text(question)
        answer_text = _normalize_text(answer)
        if not answer_text:
            return
        self.confirmed_facts.append(
            PlanningFact(
                claim=f"{question_text}: {answer_text}" if question_text else answer_text,
                fact_status="user_authorized",
                sources=[
                    TraceableSource(
                        type="user_answer",
                        path=source_path,
                        evidence_level="structured_state",
                        snippet=answer_text[:240],
                    )
                ],
                confidence=1.0,
            )
        )
        self.open_questions = [item for item in self.open_questions if item != question_text]

    def to_dict(self) -> dict[str, Any]:
        return {
            "notebook_id": self.notebook_id,
            "confirmed_facts": [item.to_dict() for item in self.confirmed_facts],
            "candidate_facts": [item.to_dict() for item in self.candidate_facts],
            "constraints": [item.to_dict() for item in self.constraints],
            "candidate_plot_moves": [item.to_dict() for item in self.candidate_plot_moves],
            "blocked_plot_moves": [item.to_dict() for item in self.blocked_plot_moves],
            "open_questions": list(self.open_questions),
            "assumptions": [item.to_dict() for item in self.assumptions],
        }

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "PlanningNotebook":
        return cls(
            notebook_id=str(data.get("notebook_id") or "outline-research-notebook"),
            confirmed_facts=[
                PlanningFact.from_dict(item) for item in (data.get("confirmed_facts") or []) if isinstance(item, Mapping)
            ],
            candidate_facts=[
                PlanningFact.from_dict(item) for item in (data.get("candidate_facts") or []) if isinstance(item, Mapping)
            ],
            constraints=[
                PlanningFact.from_dict(item) for item in (data.get("constraints") or []) if isinstance(item, Mapping)
            ],
            candidate_plot_moves=[
                PlanningFact.from_dict(item)
                for item in (data.get("candidate_plot_moves") or [])
                if isinstance(item, Mapping)
            ],
            blocked_plot_moves=[
                PlanningFact.from_dict(item)
                for item in (data.get("blocked_plot_moves") or [])
                if isinstance(item, Mapping)
            ],
            open_questions=[str(item) for item in (data.get("open_questions") or [])],
            assumptions=[
                PlanningFact.from_dict(item) for item in (data.get("assumptions") or []) if isinstance(item, Mapping)
            ],
        )


@dataclass(slots=True)
class SufficiencyDecision:
    decision_id: str
    status: SufficiencyStatus
    known_enough: list[str] = field(default_factory=list)
    blocking_gaps: list[str] = field(default_factory=list)
    optional_gaps: list[str] = field(default_factory=list)
    user_questions: list[str] = field(default_factory=list)
    assumptions: list[PlanningFact] = field(default_factory=list)
    remaining_risks: list[str] = field(default_factory=list)
    required_actions: list[str] = field(default_factory=list)
    sources: list[TraceableSource] = field(default_factory=list)

    def __post_init__(self) -> None:
        self.decision_id = _normalize_text(self.decision_id)
        normalized_status = _normalize_text(self.status).lower()
        if normalized_status not in SUFFICIENCY_STATUSES:
            raise ValueError("status must be enough, needs_user_input, proceed_with_assumptions, or blocked")
        self.status = normalized_status  # type: ignore[assignment]
        self.known_enough = _normalize_string_list(self.known_enough)
        self.blocking_gaps = _normalize_string_list(self.blocking_gaps)
        self.optional_gaps = _normalize_string_list(self.optional_gaps)
        self.user_questions = _normalize_string_list(self.user_questions)[:3]
        self.remaining_risks = _normalize_string_list(self.remaining_risks)
        self.required_actions = _normalize_string_list(self.required_actions)
        if self.status == "needs_user_input" and not self.user_questions:
            raise ValueError("needs_user_input decisions must include user_questions")
        if self.status == "blocked" and not self.required_actions:
            raise ValueError("blocked decisions must include required_actions")

    def to_dict(self) -> dict[str, Any]:
        return {
            "decision_id": self.decision_id,
            "status": self.status,
            "known_enough": list(self.known_enough),
            "blocking_gaps": list(self.blocking_gaps),
            "optional_gaps": list(self.optional_gaps),
            "user_questions": list(self.user_questions),
            "assumptions": [item.to_dict() for item in self.assumptions],
            "remaining_risks": list(self.remaining_risks),
            "required_actions": list(self.required_actions),
            "sources": [item.to_dict() for item in self.sources],
        }

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "SufficiencyDecision":
        return cls(
            decision_id=str(data.get("decision_id") or ""),
            status=cast(SufficiencyStatus, str(data.get("status") or "")),
            known_enough=[str(item) for item in (data.get("known_enough") or [])],
            blocking_gaps=[str(item) for item in (data.get("blocking_gaps") or [])],
            optional_gaps=[str(item) for item in (data.get("optional_gaps") or [])],
            user_questions=[str(item) for item in (data.get("user_questions") or [])],
            assumptions=[
                PlanningFact.from_dict(item) for item in (data.get("assumptions") or []) if isinstance(item, Mapping)
            ],
            remaining_risks=[str(item) for item in (data.get("remaining_risks") or [])],
            required_actions=[str(item) for item in (data.get("required_actions") or [])],
            sources=_coerce_sources(cast(Sequence[object], data.get("sources") or [])),
        )


@dataclass(slots=True)
class OutlineResearchQuestion:
    question_id: str
    prompt: str
    required: bool = True
    hint: str = ""
    gap_id: str = ""
    risk_level: str = ""

    def __post_init__(self) -> None:
        self.question_id = _normalize_text(self.question_id)
        self.prompt = _normalize_text(self.prompt)
        self.hint = _normalize_text(self.hint)
        self.gap_id = _normalize_text(self.gap_id)
        self.risk_level = _normalize_text(self.risk_level)
        if not self.question_id:
            raise ValueError("question_id is required")
        if not self.prompt:
            raise ValueError("prompt is required")

    def to_dict(self) -> dict[str, Any]:
        return {
            "question_id": self.question_id,
            "prompt": self.prompt,
            "required": bool(self.required),
            "hint": self.hint,
            "gap_id": self.gap_id,
            "risk_level": self.risk_level,
        }

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "OutlineResearchQuestion":
        return cls(
            question_id=str(data.get("question_id") or ""),
            prompt=str(data.get("prompt") or data.get("question") or ""),
            required=bool(data.get("required", True)),
            hint=str(data.get("hint") or ""),
            gap_id=str(data.get("gap_id") or ""),
            risk_level=str(data.get("risk_level") or ""),
        )


@dataclass(slots=True)
class OutlineResearchQuestionSet:
    question_set_id: str
    run_id: str
    questions: list[OutlineResearchQuestion]
    schema_version: str = "1.0"
    stage: str = "outline_research_user_input"
    status: OutlineResearchQuestionSetStatus = "pending"
    source_artifact_id: str = ""
    artifact_path: str = ""
    actions: dict[str, str] = field(
        default_factory=lambda: {
            "submit": "continue_after_outline_research_input",
            "defer": "defer_outline_research_answers",
        }
    )
    created_at: str = field(default_factory=_utc_now_iso)

    def __post_init__(self) -> None:
        self.schema_version = _normalize_text(self.schema_version) or "1.0"
        self.question_set_id = _normalize_text(self.question_set_id)
        self.run_id = _normalize_text(self.run_id)
        self.stage = _normalize_text(self.stage) or "outline_research_user_input"
        normalized_status = _normalize_text(self.status).lower()
        if normalized_status not in OUTLINE_RESEARCH_QUESTION_SET_STATUSES:
            raise ValueError("status must be pending, submitted, or deferred")
        self.status = cast(OutlineResearchQuestionSetStatus, normalized_status)
        self.source_artifact_id = _normalize_text(self.source_artifact_id)
        self.artifact_path = _normalize_text(self.artifact_path)
        self.created_at = _normalize_text(self.created_at) or _utc_now_iso()
        self.questions = [
            item
            if isinstance(item, OutlineResearchQuestion)
            else OutlineResearchQuestion.from_dict(cast(Mapping[str, Any], item))
            for item in self.questions
            if isinstance(item, (OutlineResearchQuestion, Mapping))
        ]
        self.actions = {
            "submit": _normalize_text(
                (self.actions or {}).get("submit") or "continue_after_outline_research_input"
            ),
            "defer": _normalize_text((self.actions or {}).get("defer") or "defer_outline_research_answers"),
        }
        if not self.question_set_id:
            raise ValueError("question_set_id is required")
        if not self.run_id:
            raise ValueError("run_id is required")
        if not self.questions:
            raise ValueError("questions must include at least one item")

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "question_set_id": self.question_set_id,
            "run_id": self.run_id,
            "stage": self.stage,
            "status": self.status,
            "source_artifact_id": self.source_artifact_id,
            "artifact_path": self.artifact_path,
            "questions": [item.to_dict() for item in self.questions],
            "actions": dict(self.actions),
            "created_at": self.created_at,
        }

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "OutlineResearchQuestionSet":
        return cls(
            schema_version=str(data.get("schema_version") or "1.0"),
            question_set_id=str(data.get("question_set_id") or ""),
            run_id=str(data.get("run_id") or ""),
            stage=str(data.get("stage") or "outline_research_user_input"),
            status=cast(OutlineResearchQuestionSetStatus, str(data.get("status") or "pending")),
            source_artifact_id=str(data.get("source_artifact_id") or ""),
            artifact_path=str(data.get("artifact_path") or ""),
            questions=[
                OutlineResearchQuestion.from_dict(item)
                for item in (data.get("questions") or [])
                if isinstance(item, Mapping)
            ],
            actions=dict(data.get("actions") or {}),
            created_at=str(data.get("created_at") or ""),
        )

    @classmethod
    def from_sufficiency_decision(
        cls,
        *,
        run_id: str,
        decision: SufficiencyDecision,
        artifact_path: str = "",
        source_artifact_id: str = "",
    ) -> "OutlineResearchQuestionSet":
        safe_decision_id = _normalize_text(decision.decision_id).replace(" ", "-") or "needs-user-input"
        questions: list[OutlineResearchQuestion] = []
        for index, prompt in enumerate(decision.user_questions, start=1):
            gap = decision.blocking_gaps[index - 1] if index - 1 < len(decision.blocking_gaps) else ""
            questions.append(
                OutlineResearchQuestion(
                    question_id=f"q{index}",
                    prompt=prompt,
                    required=True,
                    hint=gap,
                    gap_id=f"gap-{index:03d}" if gap else "",
                    risk_level="high" if gap else "",
                )
            )
        return cls(
            question_set_id=f"outline-research-{run_id}-{safe_decision_id}",
            run_id=run_id,
            questions=questions,
            source_artifact_id=source_artifact_id,
            artifact_path=artifact_path,
        )


@dataclass(slots=True)
class OutlineResearchUserAnswer:
    question_id: str
    answer_text: str

    def __post_init__(self) -> None:
        self.question_id = _normalize_text(self.question_id)
        self.answer_text = _normalize_text(self.answer_text)
        if not self.question_id:
            raise ValueError("question_id is required")

    def to_dict(self) -> dict[str, Any]:
        return {"question_id": self.question_id, "answer_text": self.answer_text}

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "OutlineResearchUserAnswer":
        return cls(
            question_id=str(data.get("question_id") or ""),
            answer_text=str(data.get("answer_text") or ""),
        )


@dataclass(slots=True)
class OutlineResearchAnswerSubmission:
    submission_id: str
    question_set_id: str
    run_id: str
    answer_text: str
    user_answers: list[OutlineResearchUserAnswer] = field(default_factory=list)
    schema_version: str = "1.0"
    source_message_id: str = ""
    reviewer_type: str = "user"
    created_at: str = field(default_factory=_utc_now_iso)

    def __post_init__(self) -> None:
        self.schema_version = _normalize_text(self.schema_version) or "1.0"
        self.submission_id = _normalize_text(self.submission_id)
        self.question_set_id = _normalize_text(self.question_set_id)
        self.run_id = _normalize_text(self.run_id)
        self.answer_text = _normalize_text(self.answer_text)
        self.source_message_id = _normalize_text(self.source_message_id)
        self.reviewer_type = _normalize_text(self.reviewer_type) or "user"
        self.created_at = _normalize_text(self.created_at) or _utc_now_iso()
        self.user_answers = [
            item
            if isinstance(item, OutlineResearchUserAnswer)
            else OutlineResearchUserAnswer.from_dict(cast(Mapping[str, Any], item))
            for item in self.user_answers
            if isinstance(item, (OutlineResearchUserAnswer, Mapping))
        ]
        if not self.submission_id:
            raise ValueError("submission_id is required")
        if not self.question_set_id:
            raise ValueError("question_set_id is required")
        if not self.run_id:
            raise ValueError("run_id is required")
        if not self.answer_text:
            raise ValueError("answer_text is required")

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "submission_id": self.submission_id,
            "question_set_id": self.question_set_id,
            "run_id": self.run_id,
            "source_message_id": self.source_message_id,
            "answer_text": self.answer_text,
            "user_answers": [item.to_dict() for item in self.user_answers],
            "reviewer_type": self.reviewer_type,
            "created_at": self.created_at,
        }

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "OutlineResearchAnswerSubmission":
        return cls(
            schema_version=str(data.get("schema_version") or "1.0"),
            submission_id=str(data.get("submission_id") or ""),
            question_set_id=str(data.get("question_set_id") or ""),
            run_id=str(data.get("run_id") or ""),
            source_message_id=str(data.get("source_message_id") or ""),
            answer_text=str(data.get("answer_text") or ""),
            user_answers=[
                OutlineResearchUserAnswer.from_dict(item)
                for item in (data.get("user_answers") or [])
                if isinstance(item, Mapping)
            ],
            reviewer_type=str(data.get("reviewer_type") or "user"),
            created_at=str(data.get("created_at") or ""),
        )


@dataclass(slots=True)
class ChapterSummaryIndexEntry:
    chapter_id: str
    document_title_index: int
    title: str = ""
    characters: list[str] = field(default_factory=list)
    concepts: list[str] = field(default_factory=list)
    event_summary: str = ""
    outcome: str = ""
    outline_update: dict[str, Any] = field(default_factory=dict)
    source_doc_ids: list[int] = field(default_factory=list)
    source_doc_range: str = ""
    source_document: str = ""
    source_segment: str = ""
    summary_status: str = "provisional"

    def __post_init__(self) -> None:
        self.chapter_id = _normalize_text(self.chapter_id)
        self.document_title_index = int(self.document_title_index or 0)
        self.title = _normalize_text(self.title)
        self.characters = _normalize_string_list(self.characters)
        self.concepts = _normalize_string_list(self.concepts)
        self.event_summary = _normalize_text(self.event_summary)
        self.outcome = _normalize_text(self.outcome)
        self.outline_update = dict(self.outline_update) if isinstance(self.outline_update, Mapping) else {}
        self.source_doc_ids = [int(item) for item in self.source_doc_ids if str(item).strip().isdigit()]
        self.source_doc_range = _normalize_text(self.source_doc_range)
        self.source_document = _normalize_text(self.source_document)
        self.source_segment = _normalize_text(self.source_segment)
        self.summary_status = _normalize_text(self.summary_status) or "provisional"

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(slots=True)
class ChapterSummaryIndex:
    entries: list[ChapterSummaryIndexEntry] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {"entries": [item.to_dict() for item in self.entries]}


@dataclass(slots=True)
class HistoricalOutlineEventCard:
    event_id: str
    title: str
    characters: list[str] = field(default_factory=list)
    concepts: list[str] = field(default_factory=list)
    event_intent: str = ""
    outcome: str = ""
    time_hint: str = ""
    source_chapter_id: str = ""
    source_path: str = ""
    source_doc_ids: list[int] = field(default_factory=list)
    source_doc_range: str = ""
    event_summary_level: str = ""
    fact_status: FactStatus = "candidate"

    def __post_init__(self) -> None:
        self.event_id = _normalize_text(self.event_id)
        self.title = _normalize_text(self.title)
        self.characters = _normalize_string_list(self.characters)
        self.concepts = _normalize_string_list(self.concepts)
        self.event_intent = _normalize_text(self.event_intent)
        self.outcome = _normalize_text(self.outcome)
        self.time_hint = _normalize_text(self.time_hint)
        self.source_chapter_id = _normalize_text(self.source_chapter_id)
        self.source_path = _normalize_text(self.source_path)
        self.source_doc_ids = [int(item) for item in self.source_doc_ids if str(item).strip().isdigit()]
        self.source_doc_range = _normalize_text(self.source_doc_range)
        self.event_summary_level = _normalize_text(self.event_summary_level)
        normalized_status = _normalize_fact_status(self.fact_status)
        if normalized_status not in FACT_STATUSES:
            raise ValueError("fact_status must be a supported value")
        self.fact_status = normalized_status  # type: ignore[assignment]

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(slots=True)
class HistoricalOutlineEventIndex:
    events: list[HistoricalOutlineEventCard] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {"events": [item.to_dict() for item in self.events]}


@dataclass(slots=True)
class EvidenceItem:
    claim: str
    evidence_level: EvidenceLevel
    source_paths: list[str] = field(default_factory=list)
    note: str = ""

    def __post_init__(self) -> None:
        self.claim = _normalize_text(self.claim)
        normalized_level = _normalize_evidence_level(self.evidence_level)
        if normalized_level not in EVIDENCE_LEVELS:
            raise ValueError("evidence_level must be a supported value")
        self.evidence_level = normalized_level  # type: ignore[assignment]
        self.source_paths = _normalize_string_list(self.source_paths)
        self.note = _normalize_text(self.note)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(slots=True)
class ModelingCheckItem:
    name: str
    ready: bool = False
    detail: str = ""
    source_paths: list[str] = field(default_factory=list)

    def __post_init__(self) -> None:
        self.name = _normalize_text(self.name)
        self.detail = _normalize_text(self.detail)
        self.source_paths = _normalize_string_list(self.source_paths)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(slots=True)
class ModelingStatus:
    book_id: str
    ready_for_continuation: bool = False
    checks: list[ModelingCheckItem] = field(default_factory=list)
    missing_modeling_steps: list[str] = field(default_factory=list)
    sources: list[TraceableSource] = field(default_factory=list)

    def __post_init__(self) -> None:
        self.book_id = _normalize_text(self.book_id)
        self.missing_modeling_steps = _normalize_string_list(self.missing_modeling_steps)

    def to_dict(self) -> dict[str, Any]:
        return {
            "book_id": self.book_id,
            "ready_for_continuation": self.ready_for_continuation,
            "checks": [item.to_dict() for item in self.checks],
            "missing_modeling_steps": list(self.missing_modeling_steps),
            "sources": [item.to_dict() for item in self.sources],
        }


@dataclass(slots=True)
class ContinuationIntent:
    major_characters: list[str] = field(default_factory=list)
    desired_actions: list[str] = field(default_factory=list)
    avoidances: list[str] = field(default_factory=list)
    preferred_outcome: str = ""
    notes: str = ""
    story_scale: dict[str, Any] = field(default_factory=dict)
    climax_plan: dict[str, Any] = field(default_factory=dict)
    sources: list[TraceableSource] = field(default_factory=list)

    def __post_init__(self) -> None:
        self.major_characters = _normalize_string_list(self.major_characters)
        self.desired_actions = _normalize_string_list(self.desired_actions)
        self.avoidances = _normalize_string_list(self.avoidances)
        self.preferred_outcome = _normalize_text(self.preferred_outcome)
        self.notes = _normalize_text(self.notes)

    def to_dict(self) -> dict[str, Any]:
        return {
            "major_characters": list(self.major_characters),
            "desired_actions": list(self.desired_actions),
            "avoidances": list(self.avoidances),
            "preferred_outcome": self.preferred_outcome,
            "notes": self.notes,
            "story_scale": dict(self.story_scale),
            "climax_plan": dict(self.climax_plan),
            "sources": [item.to_dict() for item in self.sources],
        }


@dataclass(slots=True)
class BookContinuationPlan:
    plan_id: str
    book_id: str
    continuation_goal: str
    ending_direction: str = ""
    target_chapter_count: int = 0
    target_total_chars: int = 0
    default_chapter_target_chars: int = 0
    pacing_profile: str = ""
    length_distribution_notes: str = ""
    climax_plan: dict[str, Any] = field(default_factory=dict)
    chapter_outline_slots: list[dict[str, Any]] = field(default_factory=list)
    stage_highlights: list[str] = field(default_factory=list)
    character_arcs: list[str] = field(default_factory=list)
    relationship_guardrails: list[str] = field(default_factory=list)
    must_preserve: list[str] = field(default_factory=list)
    open_questions: list[str] = field(default_factory=list)
    assumptions: list[PlanningFact] = field(default_factory=list)
    evidence: list[EvidenceItem] = field(default_factory=list)
    sources: list[TraceableSource] = field(default_factory=list)

    def __post_init__(self) -> None:
        self.plan_id = _normalize_text(self.plan_id)
        self.book_id = _normalize_text(self.book_id)
        self.continuation_goal = _normalize_text(self.continuation_goal)
        self.ending_direction = _normalize_text(self.ending_direction)
        self.target_chapter_count = max(0, int(self.target_chapter_count or 0))
        self.target_total_chars = max(0, int(self.target_total_chars or 0))
        self.default_chapter_target_chars = max(0, int(self.default_chapter_target_chars or 0))
        self.pacing_profile = _normalize_text(self.pacing_profile)
        self.length_distribution_notes = _normalize_text(self.length_distribution_notes)
        self.climax_plan = dict(self.climax_plan)
        self.chapter_outline_slots = [dict(item) for item in self.chapter_outline_slots if isinstance(item, dict)]
        self.stage_highlights = _normalize_string_list(self.stage_highlights)
        self.character_arcs = _normalize_string_list(self.character_arcs)
        self.relationship_guardrails = _normalize_string_list(self.relationship_guardrails)
        self.must_preserve = _normalize_string_list(self.must_preserve)
        self.open_questions = _normalize_string_list(self.open_questions)

    def to_dict(self) -> dict[str, Any]:
        return {
            "plan_id": self.plan_id,
            "book_id": self.book_id,
            "continuation_goal": self.continuation_goal,
            "ending_direction": self.ending_direction,
            "target_chapter_count": self.target_chapter_count,
            "target_total_chars": self.target_total_chars,
            "default_chapter_target_chars": self.default_chapter_target_chars,
            "pacing_profile": self.pacing_profile,
            "length_distribution_notes": self.length_distribution_notes,
            "climax_plan": dict(self.climax_plan),
            "chapter_outline_slots": [dict(item) for item in self.chapter_outline_slots],
            "stage_highlights": list(self.stage_highlights),
            "character_arcs": list(self.character_arcs),
            "relationship_guardrails": list(self.relationship_guardrails),
            "must_preserve": list(self.must_preserve),
            "open_questions": list(self.open_questions),
            "assumptions": [item.to_dict() for item in self.assumptions],
            "evidence": [item.to_dict() for item in self.evidence],
            "sources": [item.to_dict() for item in self.sources],
        }


@dataclass(slots=True)
class WorldConstraintRule:
    topic: str
    rule: str
    why_needed: str = ""
    constrained_plots: list[str] = field(default_factory=list)
    conflict_note: str = ""

    def __post_init__(self) -> None:
        self.topic = _normalize_text(self.topic)
        self.rule = _normalize_text(self.rule)
        self.why_needed = _normalize_text(self.why_needed)
        self.constrained_plots = _normalize_string_list(self.constrained_plots)
        self.conflict_note = _normalize_text(self.conflict_note)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(slots=True)
class WorldExpansionPack:
    pack_id: str
    book_id: str
    required_for_plot: list[str] = field(default_factory=list)
    constraint_rules: list[WorldConstraintRule] = field(default_factory=list)
    open_items: list[str] = field(default_factory=list)
    evidence: list[EvidenceItem] = field(default_factory=list)
    sources: list[TraceableSource] = field(default_factory=list)

    def __post_init__(self) -> None:
        self.pack_id = _normalize_text(self.pack_id)
        self.book_id = _normalize_text(self.book_id)
        self.required_for_plot = _normalize_string_list(self.required_for_plot)
        self.open_items = _normalize_string_list(self.open_items)

    def to_dict(self) -> dict[str, Any]:
        return {
            "pack_id": self.pack_id,
            "book_id": self.book_id,
            "required_for_plot": list(self.required_for_plot),
            "constraint_rules": [item.to_dict() for item in self.constraint_rules],
            "open_items": list(self.open_items),
            "evidence": [item.to_dict() for item in self.evidence],
            "sources": [item.to_dict() for item in self.sources],
        }


@dataclass(slots=True)
class BatchPlan:
    batch_id: str
    book_id: str
    chapters: list[str]
    batch_goal: str
    emotional_arc: str = ""
    conflict_arc: str = ""
    must_resolve: list[str] = field(default_factory=list)
    must_not_consume: list[str] = field(default_factory=list)
    planned_character_beats: list[str] = field(default_factory=list)
    exit_hook: str = ""
    target_chapter_count: int = 0
    target_total_chars: int = 0
    default_chapter_target_chars: int = 0
    chapter_outline_slots: list[dict[str, Any]] = field(default_factory=list)
    evidence: list[EvidenceItem] = field(default_factory=list)
    sources: list[TraceableSource] = field(default_factory=list)

    def __post_init__(self) -> None:
        self.batch_id = _normalize_text(self.batch_id)
        self.book_id = _normalize_text(self.book_id)
        self.chapters = _normalize_string_list(self.chapters)
        self.batch_goal = _normalize_text(self.batch_goal)
        self.emotional_arc = _normalize_text(self.emotional_arc)
        self.conflict_arc = _normalize_text(self.conflict_arc)
        self.must_resolve = _normalize_string_list(self.must_resolve)
        self.must_not_consume = _normalize_string_list(self.must_not_consume)
        self.planned_character_beats = _normalize_string_list(self.planned_character_beats)
        self.exit_hook = _normalize_text(self.exit_hook)
        self.target_chapter_count = max(0, int(self.target_chapter_count or 0))
        if self.chapters:
            self.target_chapter_count = len(self.chapters)
        self.target_total_chars = max(0, int(self.target_total_chars or 0))
        self.default_chapter_target_chars = max(0, int(self.default_chapter_target_chars or 0))
        self.chapter_outline_slots = [dict(item) for item in self.chapter_outline_slots if isinstance(item, dict)]

    def to_dict(self) -> dict[str, Any]:
        return {
            "batch_id": self.batch_id,
            "book_id": self.book_id,
            "chapters": list(self.chapters),
            "batch_goal": self.batch_goal,
            "emotional_arc": self.emotional_arc,
            "conflict_arc": self.conflict_arc,
            "must_resolve": list(self.must_resolve),
            "must_not_consume": list(self.must_not_consume),
            "planned_character_beats": list(self.planned_character_beats),
            "exit_hook": self.exit_hook,
            "target_chapter_count": self.target_chapter_count,
            "target_total_chars": self.target_total_chars,
            "default_chapter_target_chars": self.default_chapter_target_chars,
            "chapter_outline_slots": [dict(item) for item in self.chapter_outline_slots],
            "evidence": [item.to_dict() for item in self.evidence],
            "sources": [item.to_dict() for item in self.sources],
        }


@dataclass(slots=True)
class RelationshipTarget:
    relation_type: str
    current_state: str
    target_state: str
    allowed: bool = True
    required_bridge: list[str] = field(default_factory=list)

    def __post_init__(self) -> None:
        self.relation_type = _normalize_text(self.relation_type)
        self.current_state = _normalize_text(self.current_state)
        self.target_state = _normalize_text(self.target_state)
        self.required_bridge = _normalize_string_list(self.required_bridge)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(slots=True)
class ChapterStructureHint:
    theory: str = ""
    beats: list[str] = field(default_factory=list)

    def __post_init__(self) -> None:
        self.theory = _normalize_text(self.theory)
        self.beats = _normalize_string_list(self.beats)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(slots=True)
class ChapterBrief:
    chapter_id: str
    title: str
    goal: str
    chapter_role: str = ""
    plot_function: str = ""
    emotional_goal: str = ""
    conflict_goal: str = ""
    relationship_targets: list[RelationshipTarget] = field(default_factory=list)
    must_include: list[str] = field(default_factory=list)
    forbidden: list[str] = field(default_factory=list)
    structure_hint: ChapterStructureHint = field(default_factory=ChapterStructureHint)
    ending_hook: str = ""
    target_word_count: int = 1200
    sources: list[TraceableSource] = field(default_factory=list)

    def __post_init__(self) -> None:
        self.chapter_id = _normalize_text(self.chapter_id)
        self.title = _normalize_text(self.title)
        self.goal = _normalize_text(self.goal)
        self.chapter_role = _normalize_text(self.chapter_role)
        self.plot_function = _normalize_text(self.plot_function)
        self.emotional_goal = _normalize_text(self.emotional_goal)
        self.conflict_goal = _normalize_text(self.conflict_goal)
        self.must_include = _normalize_string_list(self.must_include)
        self.forbidden = _normalize_string_list(self.forbidden)
        self.ending_hook = _normalize_text(self.ending_hook)
        self.target_word_count = max(1, int(self.target_word_count))

    def to_dict(self) -> dict[str, Any]:
        return {
            "chapter_id": self.chapter_id,
            "title": self.title,
            "goal": self.goal,
            "chapter_role": self.chapter_role,
            "plot_function": self.plot_function,
            "emotional_goal": self.emotional_goal,
            "conflict_goal": self.conflict_goal,
            "relationship_targets": [item.to_dict() for item in self.relationship_targets],
            "must_include": list(self.must_include),
            "forbidden": list(self.forbidden),
            "structure_hint": self.structure_hint.to_dict(),
            "ending_hook": self.ending_hook,
            "target_word_count": self.target_word_count,
            "sources": [item.to_dict() for item in self.sources],
        }


@dataclass(slots=True)
class ChapterPackage:
    package_id: str
    batch_id: str
    package_goal: str = ""
    chapters: list[ChapterBrief] = field(default_factory=list)
    review_notes: list[str] = field(default_factory=list)
    sources: list[TraceableSource] = field(default_factory=list)

    def __post_init__(self) -> None:
        self.package_id = _normalize_text(self.package_id)
        self.batch_id = _normalize_text(self.batch_id)
        self.package_goal = _normalize_text(self.package_goal)
        self.review_notes = _normalize_string_list(self.review_notes)

    def to_dict(self) -> dict[str, Any]:
        return {
            "package_id": self.package_id,
            "batch_id": self.batch_id,
            "package_goal": self.package_goal,
            "chapters": [item.to_dict() for item in self.chapters],
            "review_notes": list(self.review_notes),
            "sources": [item.to_dict() for item in self.sources],
        }


@dataclass(slots=True)
class ChapterLengthBudget:
    chapter_id: str
    target_chars: int
    min_chars: int
    max_chars: int
    is_focus_chapter: bool = False
    focus_reason: str = ""
    expansion_notes: list[str] = field(default_factory=list)
    source_chapter_target_word_count: int = 0

    def __post_init__(self) -> None:
        self.chapter_id = _normalize_text(self.chapter_id)
        self.target_chars = int(self.target_chars)
        self.min_chars = int(self.min_chars)
        self.max_chars = int(self.max_chars)
        if min(self.target_chars, self.min_chars, self.max_chars) <= 0:
            raise ValueError("target_chars, min_chars, and max_chars must be positive integers")
        if not self.min_chars <= self.target_chars <= self.max_chars:
            raise ValueError("min_chars must be <= target_chars <= max_chars")
        self.focus_reason = _normalize_text(self.focus_reason)
        self.expansion_notes = _normalize_string_list(self.expansion_notes)
        self.source_chapter_target_word_count = max(0, int(self.source_chapter_target_word_count))

    def to_dict(self) -> dict[str, Any]:
        return {
            "chapter_id": self.chapter_id,
            "target_chars": self.target_chars,
            "min_chars": self.min_chars,
            "max_chars": self.max_chars,
            "is_focus_chapter": self.is_focus_chapter,
            "focus_reason": self.focus_reason,
            "expansion_notes": list(self.expansion_notes),
            "source_chapter_target_word_count": self.source_chapter_target_word_count,
        }


@dataclass(slots=True)
class ChapterLengthPlan:
    plan_id: str
    batch_id: str
    default_target_chars: int
    default_min_chars: int
    default_max_chars: int
    budgets: list[ChapterLengthBudget] = field(default_factory=list)
    focus_chapter_ids: list[str] = field(default_factory=list)
    climax_chapter_ids: list[str] = field(default_factory=list)
    review_notes: list[str] = field(default_factory=list)
    sources: list[TraceableSource] = field(default_factory=list)

    def __post_init__(self) -> None:
        self.plan_id = _normalize_text(self.plan_id)
        self.batch_id = _normalize_text(self.batch_id)
        self.default_target_chars = int(self.default_target_chars)
        self.default_min_chars = int(self.default_min_chars)
        self.default_max_chars = int(self.default_max_chars)
        if min(self.default_target_chars, self.default_min_chars, self.default_max_chars) <= 0:
            raise ValueError("default length values must be positive integers")
        if not self.default_min_chars <= self.default_target_chars <= self.default_max_chars:
            raise ValueError("default_min_chars must be <= default_target_chars <= default_max_chars")
        self.focus_chapter_ids = _normalize_string_list(self.focus_chapter_ids)
        self.climax_chapter_ids = _normalize_string_list(self.climax_chapter_ids)
        self.review_notes = _normalize_string_list(self.review_notes)

    def to_dict(self) -> dict[str, Any]:
        return {
            "plan_id": self.plan_id,
            "batch_id": self.batch_id,
            "default_target_chars": self.default_target_chars,
            "default_min_chars": self.default_min_chars,
            "default_max_chars": self.default_max_chars,
            "budgets": [item.to_dict() for item in self.budgets],
            "focus_chapter_ids": list(self.focus_chapter_ids),
            "climax_chapter_ids": list(self.climax_chapter_ids),
            "review_notes": list(self.review_notes),
            "sources": [item.to_dict() for item in self.sources],
        }


@dataclass(slots=True)
class StateChange:
    subject: str
    from_state: str = ""
    to_state: str = ""
    reason: str = ""

    def __post_init__(self) -> None:
        self.subject = _normalize_text(self.subject)
        self.from_state = _normalize_text(self.from_state)
        self.to_state = _normalize_text(self.to_state)
        self.reason = _normalize_text(self.reason)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(slots=True)
class StateDelta:
    chapter_id: str
    character_state_changes: list[StateChange] = field(default_factory=list)
    relationship_state_changes: list[StateChange] = field(default_factory=list)
    timeline_events: list[str] = field(default_factory=list)
    world_state_changes: list[str] = field(default_factory=list)
    outline_progress: list[str] = field(default_factory=list)
    canon_ready: bool = False
    sources: list[TraceableSource] = field(default_factory=list)

    def __post_init__(self) -> None:
        self.chapter_id = _normalize_text(self.chapter_id)
        self.timeline_events = _normalize_string_list(self.timeline_events)
        self.world_state_changes = _normalize_string_list(self.world_state_changes)
        self.outline_progress = _normalize_string_list(self.outline_progress)

    def to_dict(self) -> dict[str, Any]:
        return {
            "chapter_id": self.chapter_id,
            "character_state_changes": [item.to_dict() for item in self.character_state_changes],
            "relationship_state_changes": [item.to_dict() for item in self.relationship_state_changes],
            "timeline_events": list(self.timeline_events),
            "world_state_changes": list(self.world_state_changes),
            "outline_progress": list(self.outline_progress),
            "canon_ready": self.canon_ready,
            "sources": [item.to_dict() for item in self.sources],
        }


@dataclass(slots=True)
class ArtifactReviewDecision:
    schema_version: str = "1.0"
    review_id: str = ""
    run_id: str = ""
    artifact_kind: str = ""
    decision: ArtifactReviewDecisionValue = "approved"
    reviewer_type: str = "user"
    next_action: ArtifactReviewNextAction = "continue_agent_loop"
    created_at: str = ""
    artifact_id: str = ""
    artifact_path: str = ""
    artifact_version: str = ""
    supplement_text: str = ""
    revision_feedback: str = ""
    source_message_id: str = ""

    def __post_init__(self) -> None:
        self.schema_version = _normalize_text(self.schema_version) or "1.0"
        self.review_id = _normalize_text(self.review_id)
        self.run_id = _normalize_text(self.run_id)
        self.artifact_kind = _normalize_text(self.artifact_kind)
        normalized_decision = _normalize_text(self.decision).lower()
        if normalized_decision not in ARTIFACT_REVIEW_DECISIONS:
            raise ValueError("decision must be approved, revision_requested, or deferred")
        self.decision = normalized_decision  # type: ignore[assignment]
        self.reviewer_type = _normalize_text(self.reviewer_type) or "user"
        normalized_action = _normalize_text(self.next_action).lower()
        if normalized_action not in ARTIFACT_REVIEW_NEXT_ACTIONS:
            raise ValueError("next_action must be continue_agent_loop, revise_artifact, or defer_review")
        self.next_action = normalized_action  # type: ignore[assignment]
        self.created_at = _normalize_text(self.created_at) or _utc_now_iso()
        self.artifact_id = _normalize_text(self.artifact_id)
        self.artifact_path = _normalize_text(self.artifact_path)
        self.artifact_version = _normalize_text(self.artifact_version)
        self.supplement_text = str(self.supplement_text or "")
        self.revision_feedback = str(self.revision_feedback or "")
        self.source_message_id = _normalize_text(self.source_message_id)
        missing = [
            name
            for name in ("schema_version", "review_id", "run_id", "artifact_kind", "decision", "reviewer_type", "next_action", "created_at")
            if not _normalize_text(getattr(self, name))
        ]
        if missing:
            raise ValueError(f"ArtifactReviewDecision missing required fields: {', '.join(missing)}")
        if self.decision == "approved":
            if self.revision_feedback.strip():
                raise ValueError("approved review decisions must not include revision_feedback")
            if self.next_action != "continue_agent_loop":
                raise ValueError("approved review decisions must continue the Agent Loop")
        elif self.decision == "revision_requested":
            if not self.revision_feedback.strip():
                raise ValueError("revision_requested decisions require revision_feedback")
            if self.supplement_text.strip():
                raise ValueError("revision_requested decisions must not include supplement_text")
            if self.next_action != "revise_artifact":
                raise ValueError("revision_requested decisions must request artifact revision")
        else:
            if self.next_action != "defer_review":
                raise ValueError("deferred review decisions must defer review")

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "review_id": self.review_id,
            "run_id": self.run_id,
            "artifact_kind": self.artifact_kind,
            "artifact_id": self.artifact_id,
            "artifact_path": self.artifact_path,
            "artifact_version": self.artifact_version,
            "decision": self.decision,
            "supplement_text": self.supplement_text,
            "revision_feedback": self.revision_feedback,
            "source_message_id": self.source_message_id,
            "reviewer_type": self.reviewer_type,
            "next_action": self.next_action,
            "created_at": self.created_at,
        }

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "ArtifactReviewDecision":
        return cls(
            schema_version=str(data.get("schema_version") or "1.0"),
            review_id=str(data.get("review_id") or ""),
            run_id=str(data.get("run_id") or ""),
            artifact_kind=str(data.get("artifact_kind") or ""),
            artifact_id=str(data.get("artifact_id") or ""),
            artifact_path=str(data.get("artifact_path") or ""),
            artifact_version=str(data.get("artifact_version") or ""),
            decision=cast(ArtifactReviewDecisionValue, str(data.get("decision") or "approved")),
            supplement_text=str(data.get("supplement_text") or ""),
            revision_feedback=str(data.get("revision_feedback") or ""),
            source_message_id=str(data.get("source_message_id") or ""),
            reviewer_type=str(data.get("reviewer_type") or "user"),
            next_action=cast(ArtifactReviewNextAction, str(data.get("next_action") or "continue_agent_loop")),
            created_at=str(data.get("created_at") or ""),
        )


@dataclass(slots=True)
class WriterLoopEvent:
    event_id: str
    run_id: str
    event_kind: WriterLoopEventKind
    agent_state: WriterAgentState
    technical_stage: str = ""
    summary: str = ""
    payload: dict[str, Any] = field(default_factory=dict)
    created_at: str = ""

    def __post_init__(self) -> None:
        self.event_id = _normalize_text(self.event_id)
        self.run_id = _normalize_text(self.run_id)
        normalized_kind = _normalize_text(self.event_kind).lower()
        if normalized_kind not in WRITER_LOOP_EVENT_KINDS:
            raise ValueError("event_kind must be a supported Writer loop event kind")
        self.event_kind = normalized_kind  # type: ignore[assignment]
        normalized_state = _normalize_text(self.agent_state).lower()
        if normalized_state not in WRITER_AGENT_STATES:
            raise ValueError("agent_state must be a supported Writer agent state")
        self.agent_state = normalized_state  # type: ignore[assignment]
        self.technical_stage = _normalize_text(self.technical_stage)
        self.summary = _normalize_text(self.summary)
        self.payload = {str(key): value for key, value in self.payload.items()}
        self.created_at = _normalize_text(self.created_at) or _utc_now_iso()
        if not self.event_id or not self.run_id:
            raise ValueError("event_id and run_id are required")

    def to_dict(self) -> dict[str, Any]:
        return {
            "event_id": self.event_id,
            "run_id": self.run_id,
            "event_kind": self.event_kind,
            "agent_state": self.agent_state,
            "technical_stage": self.technical_stage,
            "summary": self.summary,
            "payload": dict(self.payload),
            "created_at": self.created_at,
        }


@dataclass(slots=True)
class WriterLoopStep:
    step_id: str
    run_id: str
    status: WriterLoopStepStatus
    agent_state: WriterAgentState
    technical_stage: str = ""
    event_ids: list[str] = field(default_factory=list)
    prompt_input_path: str = ""
    output_artifact_path: str = ""
    created_at: str = ""
    completed_at: str = ""

    def __post_init__(self) -> None:
        self.step_id = _normalize_text(self.step_id)
        self.run_id = _normalize_text(self.run_id)
        normalized_status = _normalize_text(self.status).lower()
        if normalized_status not in WRITER_LOOP_STEP_STATUSES:
            raise ValueError("status must be started, completed, waiting, or failed")
        self.status = normalized_status  # type: ignore[assignment]
        normalized_state = _normalize_text(self.agent_state).lower()
        if normalized_state not in WRITER_AGENT_STATES:
            raise ValueError("agent_state must be a supported Writer agent state")
        self.agent_state = normalized_state  # type: ignore[assignment]
        self.technical_stage = _normalize_text(self.technical_stage)
        self.event_ids = _normalize_string_list(self.event_ids)
        self.prompt_input_path = _normalize_text(self.prompt_input_path)
        self.output_artifact_path = _normalize_text(self.output_artifact_path)
        self.created_at = _normalize_text(self.created_at) or _utc_now_iso()
        self.completed_at = _normalize_text(self.completed_at)
        if not self.step_id or not self.run_id:
            raise ValueError("step_id and run_id are required")

    def to_dict(self) -> dict[str, Any]:
        return {
            "step_id": self.step_id,
            "run_id": self.run_id,
            "status": self.status,
            "agent_state": self.agent_state,
            "technical_stage": self.technical_stage,
            "event_ids": list(self.event_ids),
            "prompt_input_path": self.prompt_input_path,
            "output_artifact_path": self.output_artifact_path,
            "created_at": self.created_at,
            "completed_at": self.completed_at,
        }


@dataclass(slots=True)
class LengthPlanUpdate:
    schema_version: str
    update_id: str
    decision_id: str
    chapter_id: str
    target_chars: int
    min_chars: int
    max_chars: int
    reason_code: str
    feedback_text: str
    preserve_story_direction: bool = True
    created_at: str = ""

    def __post_init__(self) -> None:
        self.schema_version = _normalize_text(self.schema_version)
        self.update_id = _normalize_text(self.update_id)
        self.decision_id = _normalize_text(self.decision_id)
        self.chapter_id = _normalize_text(self.chapter_id)
        self.target_chars = int(self.target_chars)
        self.min_chars = int(self.min_chars)
        self.max_chars = int(self.max_chars)
        if min(self.target_chars, self.min_chars, self.max_chars) <= 0:
            raise ValueError("target_chars, min_chars, and max_chars must be positive integers")
        if not self.min_chars <= self.target_chars <= self.max_chars:
            raise ValueError("min_chars must be <= target_chars <= max_chars")
        self.reason_code = _normalize_text(self.reason_code)
        self.feedback_text = _normalize_text(self.feedback_text)
        if not self.preserve_story_direction:
            raise ValueError("preserve_story_direction must be true")
        self.created_at = _normalize_text(self.created_at)

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["legacy_migration_only"] = True
        return payload


@dataclass(slots=True)
class ChapterReplanRequest:
    schema_version: str
    request_id: str
    decision_id: str
    chapter_id: str
    reason_code: str
    feedback_text: str
    replan_scope: ChapterReplanScope = "current_chapter"
    must_preserve: list[str] = field(default_factory=list)
    must_change: list[str] = field(default_factory=list)
    forbidden_carryover: list[str] = field(default_factory=list)
    requested_length_direction: dict[str, Any] | None = None
    created_at: str = ""

    def __post_init__(self) -> None:
        self.schema_version = _normalize_text(self.schema_version)
        self.request_id = _normalize_text(self.request_id)
        self.decision_id = _normalize_text(self.decision_id)
        self.chapter_id = _normalize_text(self.chapter_id)
        self.reason_code = _normalize_text(self.reason_code)
        self.feedback_text = _normalize_text(self.feedback_text)
        normalized_scope = _normalize_text(self.replan_scope).lower()
        if normalized_scope not in CHAPTER_REPLAN_SCOPES:
            raise ValueError("replan_scope must be current_chapter")
        self.replan_scope = normalized_scope  # type: ignore[assignment]
        self.must_preserve = _normalize_string_list(self.must_preserve)
        self.must_change = _normalize_string_list(self.must_change)
        self.forbidden_carryover = _normalize_string_list(self.forbidden_carryover)
        if not self.must_change:
            raise ValueError("must_change must contain at least one item")
        if self.requested_length_direction is not None:
            self.requested_length_direction = {
                _normalize_text(key): value
                for key, value in self.requested_length_direction.items()
                if _normalize_text(key)
            }
        self.created_at = _normalize_text(self.created_at)

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["requested_length_direction"] = (
            dict(self.requested_length_direction)
            if self.requested_length_direction is not None
            else None
        )
        payload["legacy_migration_only"] = True
        return payload


@dataclass(slots=True)
class GenerationReviewDecision:
    schema_version: str
    decision_id: str
    chapter_id: str
    draft_id: str
    status: GenerationReviewStatus
    reason_code: str
    feedback_text: str
    next_action_checkpoint: GenerationReviewCheckpoint | str = ""
    run_id: str = ""
    next_action: str = ""
    length_plan_update: LengthPlanUpdate | None = None
    chapter_replan_request: ChapterReplanRequest | None = None
    supersedes_draft_id: str = ""
    source_message_id: str = ""
    reviewer_type: str = "user"
    created_at: str = ""

    def __post_init__(self) -> None:
        self.schema_version = _normalize_text(self.schema_version)
        self.decision_id = _normalize_text(self.decision_id)
        self.chapter_id = _normalize_text(self.chapter_id)
        self.draft_id = _normalize_text(self.draft_id)
        normalized_status, legacy_status = _normalize_generation_review_status(self.status)
        if normalized_status not in GENERATION_REVIEW_STATUSES:
            raise ValueError(
                "status must be accepted, rewrite_requested, replan_requested, or discarded"
            )
        self.status = normalized_status  # type: ignore[assignment]
        legacy_rework_payload = self.length_plan_update is not None or self.chapter_replan_request is not None
        self.reason_code = _normalize_text(self.reason_code)
        self.feedback_text = _normalize_text(self.feedback_text)
        normalized_checkpoint = _normalize_text(self.next_action_checkpoint).lower()
        if normalized_checkpoint and normalized_checkpoint not in GENERATION_REVIEW_CHECKPOINTS:
            raise ValueError(
                "next_action_checkpoint must be freeze_e, wait_length_review, "
                "wait_chapter_review, or halted"
            )
        self.next_action_checkpoint = normalized_checkpoint  # type: ignore[assignment]
        self.run_id = _normalize_text(self.run_id)
        normalized_next_action = _normalize_text(self.next_action).lower()
        if not normalized_next_action and normalized_checkpoint:
            normalized_next_action = LEGACY_GENERATION_REVIEW_CHECKPOINT_TO_ACTION.get(normalized_checkpoint, "")
        if not normalized_next_action:
            normalized_next_action = {
                "accepted": "writeback_review",
                "rewrite_requested": "agent_loop_rewrite_draft",
                "replan_requested": "agent_loop_replan_chapter",
                "discarded": "halted",
            }.get(self.status, "")
        if normalized_next_action not in GENERATION_REVIEW_NEXT_ACTIONS:
            raise ValueError(
                "next_action must be writeback_review, agent_loop_rewrite_draft, "
                "agent_loop_replan_chapter, or halted"
            )
        self.next_action = normalized_next_action
        self.supersedes_draft_id = _normalize_text(self.supersedes_draft_id)
        self.source_message_id = _normalize_text(self.source_message_id)
        self.reviewer_type = _normalize_text(self.reviewer_type)
        self.created_at = _normalize_text(self.created_at)
        self._validate_status_rules(legacy_status=legacy_status, legacy_rework_payload=legacy_rework_payload)

    def _validate_status_rules(self, *, legacy_status: str = "", legacy_rework_payload: bool = False) -> None:
        if self.status == "accepted":
            if self.reason_code != "approved":
                raise ValueError("accepted decisions must use reason_code 'approved'")
            if self.next_action != "writeback_review":
                raise ValueError("accepted decisions must point to writeback_review")
            if self.length_plan_update is not None or self.chapter_replan_request is not None:
                raise ValueError("accepted decisions must not include rework payloads")
            return
        if self.status == "rewrite_requested":
            if self.next_action != "agent_loop_rewrite_draft":
                raise ValueError("rewrite_requested decisions must point to agent_loop_rewrite_draft")
            if not self.feedback_text:
                raise ValueError("rewrite_requested decisions require feedback_text")
            if not legacy_status and legacy_rework_payload:
                raise ValueError("rewrite_requested decisions must not include legacy rework payloads")
            return
        if self.status == "replan_requested":
            if self.next_action != "agent_loop_replan_chapter":
                raise ValueError("replan_requested decisions must point to agent_loop_replan_chapter")
            if not self.feedback_text:
                raise ValueError("replan_requested decisions require feedback_text")
            if not legacy_status and legacy_rework_payload:
                raise ValueError("replan_requested decisions must not include legacy rework payloads")
            return
        if self.next_action != "halted":
            raise ValueError("discarded decisions must halt")
        if self.length_plan_update is not None or self.chapter_replan_request is not None:
            raise ValueError("discarded decisions must not include rework payloads")

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "decision_id": self.decision_id,
            "run_id": self.run_id,
            "chapter_id": self.chapter_id,
            "draft_id": self.draft_id,
            "status": self.status,
            "reason_code": self.reason_code,
            "feedback_text": self.feedback_text,
            "next_action": self.next_action,
            "next_action_checkpoint": self.next_action_checkpoint,
            "length_plan_update": (
                self.length_plan_update.to_dict()
                if self.length_plan_update is not None
                else None
            ),
            "chapter_replan_request": (
                self.chapter_replan_request.to_dict()
                if self.chapter_replan_request is not None
                else None
            ),
            "supersedes_draft_id": self.supersedes_draft_id,
            "source_message_id": self.source_message_id,
            "reviewer_type": self.reviewer_type,
            "created_at": self.created_at,
            "legacy_migration_only": bool(
                self.next_action_checkpoint
                or self.length_plan_update is not None
                or self.chapter_replan_request is not None
            ),
        }


@dataclass(slots=True)
class FreezeArtifact:
    name: str
    path: str
    kind: FreezeArtifactKind = "json"

    def __post_init__(self) -> None:
        self.name = _normalize_text(self.name)
        self.path = _normalize_text(self.path)
        normalized_kind = _normalize_text(self.kind).lower()
        if normalized_kind not in FREEZE_ARTIFACT_KINDS:
            raise ValueError("kind must be json, text, or markdown")
        self.kind = normalized_kind  # type: ignore[assignment]

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "FreezeArtifact":
        return cls(
            name=str(data.get("name") or ""),
            path=str(data.get("path") or ""),
            kind=str(data.get("kind") or "json"),  # type: ignore[arg-type]
        )


@dataclass(slots=True)
class FreezeRecord:
    freeze_stage: FreezeStage
    summary: str = ""
    artifacts: list[FreezeArtifact] = field(default_factory=list)
    depends_on: list[str] = field(default_factory=list)
    invalidates_downstream: list[str] = field(default_factory=list)
    status: FreezeRecordStatus = "frozen"
    frozen_at: str = ""

    def __post_init__(self) -> None:
        normalized_stage = _normalize_text(self.freeze_stage).lower()
        if normalized_stage not in FREEZE_STAGES:
            raise ValueError("freeze_stage must be one of freeze_a..freeze_e")
        self.freeze_stage = normalized_stage  # type: ignore[assignment]
        self.summary = _normalize_text(self.summary)
        self.depends_on = _normalize_string_list(self.depends_on)
        self.invalidates_downstream = _normalize_string_list(
            self.invalidates_downstream or FREEZE_STAGE_TO_DOWNSTREAM[normalized_stage]
        )
        normalized_status = _normalize_text(self.status).lower()
        if normalized_status not in FREEZE_RECORD_STATUSES:
            raise ValueError("status must be frozen or invalidated")
        self.status = normalized_status  # type: ignore[assignment]
        self.frozen_at = _normalize_text(self.frozen_at)

    def to_dict(self) -> dict[str, Any]:
        return {
            "freeze_stage": self.freeze_stage,
            "summary": self.summary,
            "artifacts": [item.to_dict() for item in self.artifacts],
            "depends_on": list(self.depends_on),
            "invalidates_downstream": list(self.invalidates_downstream),
            "status": self.status,
            "frozen_at": self.frozen_at,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "FreezeRecord":
        artifacts: list[FreezeArtifact] = []
        raw_artifacts = data.get("artifacts") or []
        if isinstance(raw_artifacts, list):
            for item in raw_artifacts:
                if isinstance(item, dict):
                    artifacts.append(FreezeArtifact.from_dict(item))
        return cls(
            freeze_stage=cast(FreezeStage, str(data.get("freeze_stage") or "")),
            summary=str(data.get("summary") or ""),
            artifacts=artifacts,
            depends_on=[str(x) for x in (data.get("depends_on") or [])],
            invalidates_downstream=[str(x) for x in (data.get("invalidates_downstream") or [])],
            status=cast(FreezeRecordStatus, str(data.get("status") or "frozen")),
            frozen_at=str(data.get("frozen_at") or ""),
        )


@dataclass(slots=True)
class FreezeManifest:
    records: list[FreezeRecord] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {"records": [item.to_dict() for item in self.records]}

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "FreezeManifest":
        records: list[FreezeRecord] = []
        raw_records = data.get("records") or []
        if isinstance(raw_records, list):
            for item in raw_records:
                if isinstance(item, dict):
                    records.append(FreezeRecord.from_dict(item))
        return cls(records=records)


@dataclass(slots=True)
class RetrievalContext:
    character_hits: list[str] = field(default_factory=list)
    timeline_hits: list[str] = field(default_factory=list)
    lore_hits: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(slots=True)
class ScenePlanStyleReferenceQuery:
    narrative_function: list[str] = field(default_factory=list)
    emotion_mode: list[str] = field(default_factory=list)
    character_temperament: list[str] = field(default_factory=list)
    style_need: list[str] = field(default_factory=list)

    def __post_init__(self) -> None:
        self.narrative_function = _normalize_string_list(self.narrative_function)
        self.emotion_mode = _normalize_string_list(self.emotion_mode)
        self.character_temperament = _normalize_string_list(self.character_temperament)
        self.style_need = _normalize_string_list(self.style_need)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(slots=True)
class ScenePlanRetrievalHints:
    preferred_tags: list[str] = field(default_factory=list)

    def __post_init__(self) -> None:
        self.preferred_tags = _normalize_string_list(self.preferred_tags)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(slots=True)
class ScenePlanSubset:
    goal: str = ""
    emotional_goal: str = ""
    conflict_goal: str = ""
    current_relationship_state: list[str] = field(default_factory=list)
    forbidden: list[str] = field(default_factory=list)
    avoidance_items: list[str] = field(default_factory=list)
    style_reference_query: ScenePlanStyleReferenceQuery = field(default_factory=ScenePlanStyleReferenceQuery)
    retrieval_hints: ScenePlanRetrievalHints = field(default_factory=ScenePlanRetrievalHints)

    def __post_init__(self) -> None:
        self.goal = _normalize_text(self.goal)
        self.emotional_goal = _normalize_text(self.emotional_goal)
        self.conflict_goal = _normalize_text(self.conflict_goal)
        self.current_relationship_state = _normalize_string_list(self.current_relationship_state)
        self.forbidden = _normalize_string_list(self.forbidden)
        self.avoidance_items = _normalize_string_list(self.avoidance_items)

    def to_dict(self) -> dict[str, Any]:
        return {
            "goal": self.goal,
            "emotional_goal": self.emotional_goal,
            "conflict_goal": self.conflict_goal,
            "current_relationship_state": list(self.current_relationship_state),
            "forbidden": list(self.forbidden),
            "avoidance_items": list(self.avoidance_items),
            "style_reference_query": self.style_reference_query.to_dict(),
            "retrieval_hints": self.retrieval_hints.to_dict(),
        }


@dataclass(slots=True)
class SceneBriefInput:
    anchor_context: str
    recent_window_summary: str
    goal: str
    previous_generated_segment: str | None = None
    retrieval_context: RetrievalContext = field(default_factory=RetrievalContext)

    def __post_init__(self) -> None:
        self.anchor_context = _normalize_text(self.anchor_context)
        self.recent_window_summary = _normalize_text(self.recent_window_summary)
        self.goal = _normalize_text(self.goal)
        self.previous_generated_segment = (
            _normalize_text(self.previous_generated_segment)
            if self.previous_generated_segment is not None
            else None
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "anchor_context": self.anchor_context,
            "recent_window_summary": self.recent_window_summary,
            "goal": self.goal,
            "previous_generated_segment": self.previous_generated_segment,
            "retrieval_context": self.retrieval_context.to_dict(),
        }


@dataclass(slots=True)
class CreativeKBRetrievalInput:
    anchor_context: str
    recent_window_summary: str
    goal: str
    documents: list[dict[str, Any]] = field(default_factory=list)
    previous_generated_segment: str | None = None
    retrieval_context: RetrievalContext = field(default_factory=RetrievalContext)
    scene_plan: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["documents"] = [dict(item) for item in self.documents]
        payload["retrieval_context"] = self.retrieval_context.to_dict()
        return payload


@dataclass(slots=True)
class MemoryAssemblyBudget:
    chapter_context_chars: int = 12_000
    source_arc_context_chars: int = 4_000
    world_summary_chars: int = 1_024
    character_profiles_chars: int = 12_000
    story_outline_chars: int = 10_000

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(slots=True)
class MemoryAssemblyInput:
    book_id: str
    document_title_index: str | None = None
    related_character_names: list[str] = field(default_factory=list)
    token_budget: MemoryAssemblyBudget = field(default_factory=MemoryAssemblyBudget)

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["token_budget"] = self.token_budget.to_dict()
        return payload


@dataclass(slots=True)
class ReferenceFragment:
    fragment_id: str
    source_excerpt: str
    content_summary: str = ""
    style_profile_text: str = ""

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(slots=True)
class WriterSource:
    path: str
    snippet: str

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(slots=True)
class WriterInputBundle:
    anchor_context: str
    recent_window_summary: str
    scene_brief: SceneBrief
    reference_fragments: list[ReferenceFragment] = field(default_factory=list)
    context_payload: ContextAssemblyPayload = field(default_factory=ContextAssemblyPayload)
    sources: list[WriterSource] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "anchor_context": self.anchor_context,
            "recent_window_summary": self.recent_window_summary,
            "scene_brief": self.scene_brief.to_dict(),
            "reference_fragments": [item.to_dict() for item in self.reference_fragments],
            "context_payload": self.context_payload.to_dict(),
            "sources": [item.to_dict() for item in self.sources],
        }

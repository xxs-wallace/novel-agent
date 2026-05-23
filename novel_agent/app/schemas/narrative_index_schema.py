from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any, Literal, Mapping, Sequence, cast


IndexCardType = Literal[
    "factual_event",
    "narrative_scene",
    "character_state",
    "world_concept",
    "mystery_foreshadow",
    "theme_signal",
    "creative_reference",
    "arc_pattern",
]
IndexConsumer = Literal["analyzer", "writer", "outline_research", "reviewer"]
SummarySufficiency = Literal[
    "sufficient",
    "needs_raw",
    "needs_model_review",
    "needs_raw_for_dialogue",
    "needs_raw_for_emotional_texture",
    "needs_raw_for_author_statement",
]
IndexCardStatus = Literal["provisional", "committed", "mixed", "fallback", "failed"]
NarrativeSceneType = Literal[
    "daily_baseline",
    "relationship_setup",
    "relationship_turning_point",
    "emotional_climax",
    "plot_turning_point",
    "world_reveal",
    "mystery_setup",
    "transition_bridge",
    "aftermath",
    "resolution",
]

CARD_TYPES = {
    "factual_event",
    "narrative_scene",
    "character_state",
    "world_concept",
    "mystery_foreshadow",
    "theme_signal",
    "creative_reference",
    "arc_pattern",
}
CONSUMERS = {"analyzer", "writer", "outline_research", "reviewer"}
SUMMARY_SUFFICIENCIES = {"sufficient", "needs_raw", "needs_model_review"}
SCENE_SUMMARY_SUFFICIENCIES = {
    "needs_raw_for_dialogue",
    "needs_raw_for_emotional_texture",
    "needs_raw_for_author_statement",
}
CARD_STATUSES = {"provisional", "committed", "mixed", "fallback", "failed"}
NARRATIVE_SCENE_TYPES = {
    "daily_baseline",
    "relationship_setup",
    "relationship_turning_point",
    "emotional_climax",
    "plot_turning_point",
    "world_reveal",
    "mystery_setup",
    "transition_bridge",
    "aftermath",
    "resolution",
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


def _int_list(value: object) -> list[int]:
    if not isinstance(value, Sequence) or isinstance(value, (str, bytes)):
        return []
    result: set[int] = set()
    for item in value:
        try:
            result.add(int(item))
        except (TypeError, ValueError):
            continue
    return sorted(result)


def _card_type(value: object) -> IndexCardType:
    normalized = _text(value).lower()
    if normalized not in CARD_TYPES:
        raise ValueError("card_type must be a supported Narrative Index card type")
    return cast(IndexCardType, normalized)


def _consumer(value: object) -> IndexConsumer:
    normalized = _text(value).lower() or "analyzer"
    if normalized not in CONSUMERS:
        return "analyzer"
    return cast(IndexConsumer, normalized)


def _summary_sufficiency(value: object) -> SummarySufficiency:
    normalized = _text(value).lower() or "sufficient"
    if normalized not in SUMMARY_SUFFICIENCIES and normalized not in SCENE_SUMMARY_SUFFICIENCIES:
        return "sufficient"
    return cast(SummarySufficiency, normalized)


def _status(value: object) -> IndexCardStatus:
    normalized = _text(value).lower() or "provisional"
    if normalized not in CARD_STATUSES:
        return "provisional"
    return cast(IndexCardStatus, normalized)


def _payload(value: object) -> dict[str, Any]:
    return dict(value) if isinstance(value, Mapping) else {}


def _scene_type(value: object) -> NarrativeSceneType:
    normalized = _text(value).lower() or "transition_bridge"
    if normalized not in NARRATIVE_SCENE_TYPES:
        return "transition_bridge"
    return cast(NarrativeSceneType, normalized)


@dataclass(slots=True)
class IndexCard:
    card_id: str
    card_type: IndexCardType
    book_id: str
    summary: str
    source_doc_ids: list[str] = field(default_factory=list)
    source_title_indexes: list[int] = field(default_factory=list)
    source_doc_range: str = ""
    outline_segment_ids: list[str] = field(default_factory=list)
    query_facets: list[str] = field(default_factory=list)
    importance_facets: list[str] = field(default_factory=list)
    consumer_hints: list[IndexConsumer] = field(default_factory=list)
    summary_sufficiency: SummarySufficiency = "sufficient"
    raw_read_reason: str = ""
    status: IndexCardStatus = "provisional"
    confidence: float = 0.0
    payload: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        self.card_id = _text(self.card_id)
        self.card_type = _card_type(self.card_type)
        self.book_id = _text(self.book_id)
        self.summary = _text(self.summary)
        self.source_doc_ids = _string_list(self.source_doc_ids)
        self.source_title_indexes = _int_list(self.source_title_indexes)
        self.source_doc_range = _text(self.source_doc_range)
        self.outline_segment_ids = _string_list(self.outline_segment_ids)
        self.query_facets = _string_list(self.query_facets)
        self.importance_facets = _string_list(self.importance_facets)
        self.consumer_hints = [
            _consumer(item)
            for item in self.consumer_hints
            if _text(item).lower() in CONSUMERS
        ]
        self.summary_sufficiency = _summary_sufficiency(self.summary_sufficiency)
        self.raw_read_reason = _text(self.raw_read_reason)
        self.status = _status(self.status)
        self.confidence = max(0.0, min(1.0, float(self.confidence or 0.0)))
        self.payload = _payload(self.payload)
        if not self.card_id:
            raise ValueError("card_id is required")
        if not self.book_id:
            raise ValueError("book_id is required")
        if not self.summary and self.status not in {"failed", "fallback"}:
            raise ValueError("summary is required for non-failed IndexCard")

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_mapping(cls, data: Mapping[str, Any]) -> "IndexCard":
        return cls(
            card_id=str(data.get("card_id") or ""),
            card_type=cast(IndexCardType, str(data.get("card_type") or "")),
            book_id=str(data.get("book_id") or ""),
            summary=str(data.get("summary") or ""),
            source_doc_ids=_string_list(data.get("source_doc_ids")),
            source_title_indexes=_int_list(data.get("source_title_indexes")),
            source_doc_range=str(data.get("source_doc_range") or ""),
            outline_segment_ids=_string_list(data.get("outline_segment_ids")),
            query_facets=_string_list(data.get("query_facets")),
            importance_facets=_string_list(data.get("importance_facets")),
            consumer_hints=[_consumer(item) for item in _string_list(data.get("consumer_hints"))],
            summary_sufficiency=cast(SummarySufficiency, str(data.get("summary_sufficiency") or "sufficient")),
            raw_read_reason=str(data.get("raw_read_reason") or ""),
            status=cast(IndexCardStatus, str(data.get("status") or "provisional")),
            confidence=float(data.get("confidence") or 0.0),
            payload=_payload(data.get("payload")),
        )


@dataclass(slots=True)
class NarrativeSceneBoundary:
    start_doc_id: str = ""
    end_doc_id: str = ""
    boundary_confidence: float = 0.0
    overlap_window_id: str = ""

    def __post_init__(self) -> None:
        self.start_doc_id = _text(self.start_doc_id)
        self.end_doc_id = _text(self.end_doc_id)
        self.boundary_confidence = max(0.0, min(1.0, float(self.boundary_confidence or 0.0)))
        self.overlap_window_id = _text(self.overlap_window_id)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_mapping(cls, data: Mapping[str, Any]) -> "NarrativeSceneBoundary":
        return cls(
            start_doc_id=str(data.get("start_doc_id") or ""),
            end_doc_id=str(data.get("end_doc_id") or ""),
            boundary_confidence=float(data.get("boundary_confidence") or 0.0),
            overlap_window_id=str(data.get("overlap_window_id") or ""),
        )


@dataclass(slots=True)
class NarrativeScenePayload:
    scene_type: NarrativeSceneType = "transition_bridge"
    label: str = ""
    participants: list[str] = field(default_factory=list)
    scene_boundary: NarrativeSceneBoundary = field(default_factory=NarrativeSceneBoundary)
    trigger: str = ""
    turning_point: str = ""
    outcome: str = ""
    character_pressure: list[str] = field(default_factory=list)
    relationship_movements: list[str] = field(default_factory=list)
    world_or_mystery_signals: list[str] = field(default_factory=list)
    future_consequence: str = ""

    def __post_init__(self) -> None:
        self.scene_type = _scene_type(self.scene_type)
        self.label = _text(self.label)
        self.participants = _string_list(self.participants)
        if isinstance(self.scene_boundary, Mapping):
            self.scene_boundary = NarrativeSceneBoundary.from_mapping(self.scene_boundary)
        self.trigger = _text(self.trigger)
        self.turning_point = _text(self.turning_point)
        self.outcome = _text(self.outcome)
        self.character_pressure = _string_list(self.character_pressure)
        self.relationship_movements = _string_list(self.relationship_movements)
        self.world_or_mystery_signals = _string_list(self.world_or_mystery_signals)
        self.future_consequence = _text(self.future_consequence)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_mapping(cls, data: Mapping[str, Any]) -> "NarrativeScenePayload":
        return cls(
            scene_type=cast(NarrativeSceneType, str(data.get("scene_type") or "transition_bridge")),
            label=str(data.get("label") or ""),
            participants=_string_list(data.get("participants")),
            scene_boundary=NarrativeSceneBoundary.from_mapping(_payload(data.get("scene_boundary"))),
            trigger=str(data.get("trigger") or ""),
            turning_point=str(data.get("turning_point") or ""),
            outcome=str(data.get("outcome") or ""),
            character_pressure=_string_list(data.get("character_pressure")),
            relationship_movements=_string_list(data.get("relationship_movements")),
            world_or_mystery_signals=_string_list(data.get("world_or_mystery_signals")),
            future_consequence=str(data.get("future_consequence") or ""),
        )


@dataclass(slots=True)
class NarrativeSceneCard:
    card: IndexCard
    scene: NarrativeScenePayload

    def __post_init__(self) -> None:
        if self.card.card_type != "narrative_scene":
            raise ValueError("NarrativeSceneCard requires card_type='narrative_scene'")
        if isinstance(self.scene, Mapping):
            self.scene = NarrativeScenePayload.from_mapping(self.scene)

    def to_index_card(self) -> IndexCard:
        payload = dict(self.card.payload)
        payload.update(self.scene.to_dict())
        return IndexCard(
            card_id=self.card.card_id,
            card_type="narrative_scene",
            book_id=self.card.book_id,
            summary=self.card.summary,
            source_doc_ids=list(self.card.source_doc_ids),
            source_title_indexes=list(self.card.source_title_indexes),
            source_doc_range=self.card.source_doc_range,
            outline_segment_ids=list(self.card.outline_segment_ids),
            query_facets=list(self.card.query_facets),
            importance_facets=list(self.card.importance_facets),
            consumer_hints=list(self.card.consumer_hints),
            summary_sufficiency=self.card.summary_sufficiency,
            raw_read_reason=self.card.raw_read_reason,
            status=self.card.status,
            confidence=self.card.confidence,
            payload=payload,
        )

    def to_dict(self) -> dict[str, Any]:
        return self.to_index_card().to_dict()

    @classmethod
    def from_mapping(cls, data: Mapping[str, Any]) -> "NarrativeSceneCard":
        card = IndexCard.from_mapping({**dict(data), "card_type": "narrative_scene"})
        return cls(card=card, scene=NarrativeScenePayload.from_mapping(card.payload))


@dataclass(slots=True)
class IndexQueryIntent:
    original_query: str
    consumer: IndexConsumer = "analyzer"
    target_card_types: list[IndexCardType] = field(default_factory=list)
    query_facets: list[str] = field(default_factory=list)
    must_include_characters: list[str] = field(default_factory=list)
    time_scope: str = "current_book"
    raw_read_policy: str = "avoid_unless_needed"

    def __post_init__(self) -> None:
        self.original_query = _text(self.original_query)
        self.consumer = _consumer(self.consumer)
        self.target_card_types = [
            _card_type(item)
            for item in self.target_card_types
            if _text(item).lower() in CARD_TYPES
        ]
        self.query_facets = _string_list(self.query_facets)
        self.must_include_characters = _string_list(self.must_include_characters)
        self.time_scope = _text(self.time_scope) or "current_book"
        self.raw_read_policy = _text(self.raw_read_policy) or "avoid_unless_needed"

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_mapping(cls, data: Mapping[str, Any]) -> "IndexQueryIntent":
        return cls(
            original_query=str(data.get("original_query") or data.get("query") or ""),
            consumer=cast(IndexConsumer, str(data.get("consumer") or "analyzer")),
            target_card_types=[
                cast(IndexCardType, str(item))
                for item in _string_list(data.get("target_card_types"))
            ],
            query_facets=_string_list(data.get("query_facets")),
            must_include_characters=_string_list(data.get("must_include_characters")),
            time_scope=str(data.get("time_scope") or "current_book"),
            raw_read_policy=str(data.get("raw_read_policy") or "avoid_unless_needed"),
        )


@dataclass(slots=True)
class IndexQueryBudget:
    max_candidate_cards: int = 24
    max_card_summary_chars: int = 600
    max_trace_items: int = 80

    def __post_init__(self) -> None:
        self.max_candidate_cards = max(1, int(self.max_candidate_cards or 1))
        self.max_card_summary_chars = max(80, int(self.max_card_summary_chars or 80))
        self.max_trace_items = max(10, int(self.max_trace_items or 10))

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(slots=True)
class IndexCardHit:
    card: IndexCard
    score: float = 0.0
    matched_by: list[str] = field(default_factory=list)

    def __post_init__(self) -> None:
        self.score = float(self.score or 0.0)
        self.matched_by = _string_list(self.matched_by)

    def to_dict(self) -> dict[str, Any]:
        return {
            "card": self.card.to_dict(),
            "score": self.score,
            "matched_by": list(self.matched_by),
        }


@dataclass(slots=True)
class IndexQueryResult:
    intent: IndexQueryIntent
    candidate_cards: list[IndexCardHit] = field(default_factory=list)
    raw_read_recommendations: list[dict[str, Any]] = field(default_factory=list)
    trace: list[dict[str, Any]] = field(default_factory=list)

    def __post_init__(self) -> None:
        self.raw_read_recommendations = [
            dict(item) for item in self.raw_read_recommendations if isinstance(item, Mapping)
        ]
        self.trace = [dict(item) for item in self.trace if isinstance(item, Mapping)]

    @property
    def cards(self) -> list[IndexCard]:
        return [hit.card for hit in self.candidate_cards]

    def to_dict(self) -> dict[str, Any]:
        return {
            "intent": self.intent.to_dict(),
            "candidate_cards": [hit.to_dict() for hit in self.candidate_cards],
            "raw_read_recommendations": [dict(item) for item in self.raw_read_recommendations],
            "trace": [dict(item) for item in self.trace],
        }


@dataclass(slots=True)
class IndexEvidenceBundle:
    cards: list[IndexCard] = field(default_factory=list)
    source_doc_ids: list[int] = field(default_factory=list)
    chapter_refs: list[str] = field(default_factory=list)
    sources: list[dict[str, Any]] = field(default_factory=list)
    trace: list[dict[str, Any]] = field(default_factory=list)

    def __post_init__(self) -> None:
        self.source_doc_ids = _int_list(self.source_doc_ids)
        self.chapter_refs = _string_list(self.chapter_refs)
        self.sources = [dict(item) for item in self.sources if isinstance(item, Mapping)]
        self.trace = [dict(item) for item in self.trace if isinstance(item, Mapping)]

    def to_dict(self) -> dict[str, Any]:
        return {
            "cards": [card.to_dict() for card in self.cards],
            "source_doc_ids": list(self.source_doc_ids),
            "chapter_refs": list(self.chapter_refs),
            "sources": [dict(item) for item in self.sources],
            "trace": [dict(item) for item in self.trace],
        }

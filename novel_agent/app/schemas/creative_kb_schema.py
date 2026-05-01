from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any, Literal, Sequence


CONTEXT_DEPENDENCY_LEVELS = {"low", "medium", "high"}
BUILD_RESULT_STATUSES = {"success", "fallback_success", "failed"}
BUILD_FAILURE_STAGES = {"", "json_parse", "schema_validate", "postprocess", "persist"}


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


@dataclass(slots=True)
class StyleFeatures:
    sentence_rhythm: str
    dialogue_density: str
    interiority_density: str
    imagery_density: str

    def __post_init__(self) -> None:
        self.sentence_rhythm = _normalize_text(self.sentence_rhythm)
        self.dialogue_density = _normalize_text(self.dialogue_density)
        self.interiority_density = _normalize_text(self.interiority_density)
        self.imagery_density = _normalize_text(self.imagery_density)


@dataclass(slots=True)
class FragmentCard:
    fragment_id: str
    doc_id: str
    document_title: str
    document_title_index: str
    cluster_id: str | None = None
    is_cluster_representative: bool = False
    source_path: str = ""
    source_offsets: tuple[int, int] = (0, 0)
    source_excerpt: str = ""
    content_summary: str = ""
    narrative_function: list[str] = field(default_factory=list)
    narrative_function_text: str = ""
    scene_space_tags: list[str] = field(default_factory=list)
    event_tags: list[str] = field(default_factory=list)
    emotion_tags: list[str] = field(default_factory=list)
    emotion_mechanism_text: str = ""
    expression_mode_tags: list[str] = field(default_factory=list)
    preferred_tags: list[str] = field(default_factory=list)
    pov_mode: str = ""
    character_focus: list[str] = field(default_factory=list)
    character_temperament: list[str] = field(default_factory=list)
    character_relation_text: str = ""
    relationship_state: list[str] = field(default_factory=list)
    continuity_phase: str = ""
    style_features: StyleFeatures = field(
        default_factory=lambda: StyleFeatures(
            sentence_rhythm="",
            dialogue_density="",
            interiority_density="",
            imagery_density="",
        )
    )
    style_profile_text: str = ""
    transferability_score: float = 0.0
    context_dependency_level: Literal["low", "medium", "high"] = "medium"

    def __post_init__(self) -> None:
        self.fragment_id = _normalize_text(self.fragment_id)
        self.doc_id = _normalize_text(self.doc_id)
        self.document_title = _normalize_text(self.document_title)
        self.document_title_index = _normalize_text(self.document_title_index)
        self.cluster_id = _normalize_text(self.cluster_id) if self.cluster_id is not None else None
        self.source_path = _normalize_text(self.source_path)
        self.source_excerpt = _normalize_text(self.source_excerpt)
        self.content_summary = _normalize_text(self.content_summary)
        self.narrative_function_text = _normalize_text(self.narrative_function_text)
        self.emotion_mechanism_text = _normalize_text(self.emotion_mechanism_text)
        self.pov_mode = _normalize_text(self.pov_mode)
        self.character_relation_text = _normalize_text(self.character_relation_text)
        self.continuity_phase = _normalize_text(self.continuity_phase)
        self.style_profile_text = _normalize_text(self.style_profile_text)
        self.narrative_function = _normalize_string_list(self.narrative_function)
        self.scene_space_tags = _normalize_string_list(self.scene_space_tags)
        self.event_tags = _normalize_string_list(self.event_tags)
        self.emotion_tags = _normalize_string_list(self.emotion_tags)
        self.expression_mode_tags = _normalize_string_list(self.expression_mode_tags)
        self.preferred_tags = _normalize_string_list(self.preferred_tags)
        self.character_focus = _normalize_string_list(self.character_focus)
        self.character_temperament = _normalize_string_list(self.character_temperament)
        self.relationship_state = _normalize_string_list(self.relationship_state)
        if len(self.source_offsets) != 2:
            raise ValueError("source_offsets must contain exactly two integers")
        start_offset = int(self.source_offsets[0])
        end_offset = int(self.source_offsets[1])
        if start_offset < 0 or end_offset < start_offset:
            raise ValueError("source_offsets must be an ordered non-negative range")
        self.source_offsets = (start_offset, end_offset)
        self.transferability_score = float(self.transferability_score)
        if not 0.0 <= self.transferability_score <= 1.0:
            raise ValueError("transferability_score must be within [0.0, 1.0]")
        normalized_dependency = _normalize_text(self.context_dependency_level).lower()
        if normalized_dependency not in CONTEXT_DEPENDENCY_LEVELS:
            raise ValueError("context_dependency_level must be one of low, medium, high")
        self.context_dependency_level = normalized_dependency  # type: ignore[assignment]

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(slots=True)
class FragmentCluster:
    cluster_id: str
    cluster_theme: str = ""
    representative_fragment_id: str = ""
    member_count: int = 0
    dedup_reason: str = ""

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(slots=True)
class SceneBrief:
    scene_objective: str
    emotional_goal: str = ""
    conflict_goal: str = ""
    narrative_function: list[str] = field(default_factory=list)
    emotion_mode: list[str] = field(default_factory=list)
    character_temperament: list[str] = field(default_factory=list)
    relationship_state: list[str] = field(default_factory=list)
    style_need: list[str] = field(default_factory=list)
    must_avoid: list[str] = field(default_factory=list)
    preferred_tags: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(slots=True)
class CoarseRetrievalResult:
    candidate_fragment_ids: list[str] = field(default_factory=list)
    matched_by: dict[str, list[str]] = field(default_factory=dict)
    filtered_cluster_ids: list[str] = field(default_factory=list)
    coarse_scores: dict[str, float] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(slots=True)
class RerankScore:
    candidate_id: str
    cluster_id: str | None = None
    continuity_fit: int = 0
    scene_function_fit: int = 0
    character_temperament_fit: int = 0
    relationship_state_fit: int = 0
    emotion_expression_fit: int = 0
    style_fit: int = 0
    transferability: int = 0
    context_dependency_penalty: int = 0
    final_score: float = 0.0
    reason: str = ""

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(slots=True)
class RerankResult:
    scores: list[RerankScore] = field(default_factory=list)
    selected_fragment_ids: list[str] = field(default_factory=list)
    selection_notes: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "scores": [score.to_dict() for score in self.scores],
            "selected_fragment_ids": list(self.selected_fragment_ids),
            "selection_notes": self.selection_notes,
        }


BuildStatus = Literal["success", "fallback_success", "failed"]
FailureStage = Literal["", "json_parse", "schema_validate", "postprocess", "persist"]


@dataclass(slots=True)
class FragmentCardBuildResult:
    status: BuildStatus
    fragment_card: FragmentCard | None = None
    retry_count: int = 0
    used_fallback: bool = False
    failure_stage: FailureStage = ""
    failure_reason: str = ""
    warnings: list[str] = field(default_factory=list)

    def __post_init__(self) -> None:
        normalized_status = _normalize_text(self.status).lower()
        if normalized_status not in BUILD_RESULT_STATUSES:
            raise ValueError("status must be success, fallback_success, or failed")
        self.status = normalized_status  # type: ignore[assignment]
        self.retry_count = max(0, int(self.retry_count))
        normalized_stage = _normalize_text(self.failure_stage).lower()
        if normalized_stage not in BUILD_FAILURE_STAGES:
            raise ValueError("failure_stage must be json_parse, schema_validate, postprocess, persist, or empty")
        self.failure_stage = normalized_stage  # type: ignore[assignment]
        self.failure_reason = _normalize_text(self.failure_reason)
        self.warnings = _normalize_string_list(self.warnings)

    def to_dict(self) -> dict[str, Any]:
        return {
            "status": self.status,
            "fragment_card": self.fragment_card.to_dict() if self.fragment_card is not None else None,
            "retry_count": self.retry_count,
            "used_fallback": self.used_fallback,
            "failure_stage": self.failure_stage,
            "failure_reason": self.failure_reason,
            "warnings": list(self.warnings),
        }


@dataclass(slots=True)
class SemanticAlias:
    book_id: str
    canonical_key: str
    aliases: list[str] = field(default_factory=list)
    category: str = "requirement_coverage"
    source: str = "model_extraction"
    evidence_doc_ids: list[str] = field(default_factory=list)
    confidence: float = 0.0
    extraction_run_id: str = ""

    def __post_init__(self) -> None:
        self.book_id = _normalize_text(self.book_id)
        self.canonical_key = _normalize_text(self.canonical_key)
        self.aliases = _normalize_string_list(self.aliases)
        self.category = _normalize_text(self.category) or "requirement_coverage"
        self.source = _normalize_text(self.source) or "model_extraction"
        self.evidence_doc_ids = _normalize_string_list(self.evidence_doc_ids)
        self.confidence = max(0.0, min(1.0, float(self.confidence)))
        self.extraction_run_id = _normalize_text(self.extraction_run_id)
        if not self.book_id:
            raise ValueError("book_id is required")
        if not self.canonical_key:
            raise ValueError("canonical_key is required")

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(slots=True)
class CreativeKBBuildResult:
    built_fragment_count: int = 0
    built_cluster_count: int = 0
    representative_count: int = 0
    fragment_ids: list[str] = field(default_factory=list)
    cluster_ids: list[str] = field(default_factory=list)
    failed_doc_ids: list[str] = field(default_factory=list)
    skipped_doc_ids: list[str] = field(default_factory=list)
    semantic_alias_count: int = 0
    semantic_alias_sampled_doc_ids: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)

    def __post_init__(self) -> None:
        self.built_fragment_count = max(0, int(self.built_fragment_count))
        self.built_cluster_count = max(0, int(self.built_cluster_count))
        self.representative_count = max(0, int(self.representative_count))
        self.fragment_ids = _normalize_string_list(self.fragment_ids)
        self.cluster_ids = _normalize_string_list(self.cluster_ids)
        self.failed_doc_ids = _normalize_string_list(self.failed_doc_ids)
        self.skipped_doc_ids = _normalize_string_list(self.skipped_doc_ids)
        self.semantic_alias_count = max(0, int(self.semantic_alias_count))
        self.semantic_alias_sampled_doc_ids = _normalize_string_list(self.semantic_alias_sampled_doc_ids)
        self.warnings = _normalize_string_list(self.warnings)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(slots=True)
class ExpandedReferenceFragment:
    fragment_id: str
    doc_id: str
    source_path: str
    source_excerpt: str
    content_summary: str = ""
    style_profile_text: str = ""

    def __post_init__(self) -> None:
        self.fragment_id = _normalize_text(self.fragment_id)
        self.doc_id = _normalize_text(self.doc_id)
        self.source_path = _normalize_text(self.source_path)
        self.source_excerpt = _normalize_text(self.source_excerpt)
        self.content_summary = _normalize_text(self.content_summary)
        self.style_profile_text = _normalize_text(self.style_profile_text)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(slots=True)
class CreativeKBRetrievalResult:
    scene_brief: SceneBrief | None = None
    rerank_result: RerankResult = field(default_factory=RerankResult)
    coarse_result: CoarseRetrievalResult | None = None
    reference_fragments: list[ExpandedReferenceFragment] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "scene_brief": self.scene_brief.to_dict() if self.scene_brief is not None else None,
            "rerank_result": self.rerank_result.to_dict(),
        }
        if self.coarse_result is not None:
            payload["coarse_result"] = self.coarse_result.to_dict()
        if self.reference_fragments:
            payload["reference_fragments"] = [item.to_dict() for item in self.reference_fragments]
        return payload

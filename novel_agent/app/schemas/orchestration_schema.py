from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any, Literal, Sequence, cast

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
GENERATION_REVIEW_STATUSES = {
    "accepted",
    "revise_length",
    "replan_chapter",
    "discarded",
}
GENERATION_REVIEW_CHECKPOINTS = {
    "freeze_e",
    "wait_length_review",
    "wait_chapter_review",
    "halted",
}
CHAPTER_REPLAN_SCOPES = {"current_chapter"}


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


FreezeStage = Literal["freeze_a", "freeze_b", "freeze_c", "freeze_d", "freeze_e"]
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
    "revise_length",
    "replan_chapter",
    "discarded",
]
GenerationReviewCheckpoint = Literal[
    "freeze_e",
    "wait_length_review",
    "wait_chapter_review",
    "halted",
]
ChapterReplanScope = Literal["current_chapter"]


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
        return asdict(self)


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
            "sources": [item.to_dict() for item in self.sources],
        }


@dataclass(slots=True)
class BookContinuationPlan:
    plan_id: str
    book_id: str
    continuation_goal: str
    ending_direction: str = ""
    stage_highlights: list[str] = field(default_factory=list)
    character_arcs: list[str] = field(default_factory=list)
    relationship_guardrails: list[str] = field(default_factory=list)
    must_preserve: list[str] = field(default_factory=list)
    open_questions: list[str] = field(default_factory=list)
    evidence: list[EvidenceItem] = field(default_factory=list)
    sources: list[TraceableSource] = field(default_factory=list)

    def __post_init__(self) -> None:
        self.plan_id = _normalize_text(self.plan_id)
        self.book_id = _normalize_text(self.book_id)
        self.continuation_goal = _normalize_text(self.continuation_goal)
        self.ending_direction = _normalize_text(self.ending_direction)
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
            "stage_highlights": list(self.stage_highlights),
            "character_arcs": list(self.character_arcs),
            "relationship_guardrails": list(self.relationship_guardrails),
            "must_preserve": list(self.must_preserve),
            "open_questions": list(self.open_questions),
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
    scope_start: str
    scope_end: str
    batch_goal: str
    emotional_arc: str = ""
    conflict_arc: str = ""
    must_resolve: list[str] = field(default_factory=list)
    must_not_consume: list[str] = field(default_factory=list)
    planned_character_beats: list[str] = field(default_factory=list)
    exit_hook: str = ""
    evidence: list[EvidenceItem] = field(default_factory=list)
    sources: list[TraceableSource] = field(default_factory=list)

    def __post_init__(self) -> None:
        self.batch_id = _normalize_text(self.batch_id)
        self.book_id = _normalize_text(self.book_id)
        self.scope_start = _normalize_text(self.scope_start)
        self.scope_end = _normalize_text(self.scope_end)
        self.batch_goal = _normalize_text(self.batch_goal)
        self.emotional_arc = _normalize_text(self.emotional_arc)
        self.conflict_arc = _normalize_text(self.conflict_arc)
        self.must_resolve = _normalize_string_list(self.must_resolve)
        self.must_not_consume = _normalize_string_list(self.must_not_consume)
        self.planned_character_beats = _normalize_string_list(self.planned_character_beats)
        self.exit_hook = _normalize_text(self.exit_hook)

    def to_dict(self) -> dict[str, Any]:
        return {
            "batch_id": self.batch_id,
            "book_id": self.book_id,
            "scope_start": self.scope_start,
            "scope_end": self.scope_end,
            "batch_goal": self.batch_goal,
            "emotional_arc": self.emotional_arc,
            "conflict_arc": self.conflict_arc,
            "must_resolve": list(self.must_resolve),
            "must_not_consume": list(self.must_not_consume),
            "planned_character_beats": list(self.planned_character_beats),
            "exit_hook": self.exit_hook,
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
        return asdict(self)


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
    next_action_checkpoint: GenerationReviewCheckpoint
    run_id: str = ""
    length_plan_update: LengthPlanUpdate | None = None
    chapter_replan_request: ChapterReplanRequest | None = None
    supersedes_draft_id: str = ""
    reviewer_type: str = "user"
    created_at: str = ""

    def __post_init__(self) -> None:
        self.schema_version = _normalize_text(self.schema_version)
        self.decision_id = _normalize_text(self.decision_id)
        self.chapter_id = _normalize_text(self.chapter_id)
        self.draft_id = _normalize_text(self.draft_id)
        normalized_status = _normalize_text(self.status).lower()
        if normalized_status not in GENERATION_REVIEW_STATUSES:
            raise ValueError(
                "status must be accepted, revise_length, replan_chapter, or discarded"
            )
        self.status = normalized_status  # type: ignore[assignment]
        self.reason_code = _normalize_text(self.reason_code)
        self.feedback_text = _normalize_text(self.feedback_text)
        normalized_checkpoint = _normalize_text(self.next_action_checkpoint).lower()
        if normalized_checkpoint not in GENERATION_REVIEW_CHECKPOINTS:
            raise ValueError(
                "next_action_checkpoint must be freeze_e, wait_length_review, "
                "wait_chapter_review, or halted"
            )
        self.next_action_checkpoint = normalized_checkpoint  # type: ignore[assignment]
        self.run_id = _normalize_text(self.run_id)
        self.supersedes_draft_id = _normalize_text(self.supersedes_draft_id)
        self.reviewer_type = _normalize_text(self.reviewer_type)
        self.created_at = _normalize_text(self.created_at)
        self._validate_status_rules()

    def _validate_status_rules(self) -> None:
        if self.status == "accepted":
            if self.reason_code != "approved":
                raise ValueError("accepted decisions must use reason_code 'approved'")
            if self.next_action_checkpoint != "freeze_e":
                raise ValueError("accepted decisions must point to freeze_e")
            if self.length_plan_update is not None or self.chapter_replan_request is not None:
                raise ValueError("accepted decisions must not include rework payloads")
            return
        if self.status == "revise_length":
            if self.next_action_checkpoint != "wait_length_review":
                raise ValueError("revise_length decisions must point to wait_length_review")
            if self.length_plan_update is None:
                raise ValueError("revise_length decisions require length_plan_update")
            if self.chapter_replan_request is not None:
                raise ValueError("revise_length decisions must not include chapter_replan_request")
            return
        if self.status == "replan_chapter":
            if self.next_action_checkpoint != "wait_chapter_review":
                raise ValueError("replan_chapter decisions must point to wait_chapter_review")
            if self.chapter_replan_request is None:
                raise ValueError("replan_chapter decisions require chapter_replan_request")
            return
        if self.next_action_checkpoint != "halted":
            raise ValueError("discarded decisions must point to halted")
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
            "reviewer_type": self.reviewer_type,
            "created_at": self.created_at,
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

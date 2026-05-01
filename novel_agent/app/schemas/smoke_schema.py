from __future__ import annotations

from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Literal


def _normalize_text(value: object) -> str:
    return str(value).strip()


def _normalize_optional_text(value: object | None) -> str | None:
    if value is None:
        return None
    text = _normalize_text(value)
    return text or None


def _normalize_string_list(items: object) -> list[str]:
    if items is None:
        return []
    if isinstance(items, str):
        text = items.strip()
        return [text] if text else []
    if not isinstance(items, list):
        return []
    normalized: list[str] = []
    seen: set[str] = set()
    for item in items:
        text = _normalize_text(item)
        if not text or text in seen:
            continue
        normalized.append(text)
        seen.add(text)
    return normalized


def _normalize_metadata(value: object) -> dict[str, Any]:
    if not isinstance(value, dict):
        return {}
    return {str(key): item for key, item in value.items()}


SmokeMode = Literal["blind_prefix", "chapter_authorized", "bounded_future_hint"]


@dataclass(slots=True)
class DocumentsCutoff:
    max_document_title_index: str

    def __post_init__(self) -> None:
        self.max_document_title_index = _normalize_text(self.max_document_title_index)
        if not self.max_document_title_index:
            raise ValueError("max_document_title_index is required")

    @property
    def max_title_index_int(self) -> int:
        return int(self.max_document_title_index)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(slots=True)
class AllowedOutlineScope:
    chapter_range: list[str] = field(default_factory=list)
    allow_future_outline: bool = False

    def __post_init__(self) -> None:
        self.chapter_range = _normalize_string_list(self.chapter_range)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(slots=True)
class ForwardGuidance:
    guidance_version: str = "v1"
    segment_objective: str = ""
    required_emotional_direction: str = ""
    must_preserve_tension: bool = False
    must_not_reveal: list[str] = field(default_factory=list)
    next_turn_hint: str = ""
    allowed_future_scope: dict[str, Any] = field(default_factory=dict)
    continuity_watch_items: list[str] = field(default_factory=list)
    forbidden_shortcuts: list[str] = field(default_factory=list)
    target_length_chars: int = 0

    def __post_init__(self) -> None:
        self.guidance_version = _normalize_text(self.guidance_version) or "v1"
        self.segment_objective = _normalize_text(self.segment_objective)
        self.required_emotional_direction = _normalize_text(self.required_emotional_direction)
        self.must_not_reveal = _normalize_string_list(self.must_not_reveal)
        self.next_turn_hint = _normalize_text(self.next_turn_hint)
        self.allowed_future_scope = _normalize_metadata(self.allowed_future_scope)
        self.continuity_watch_items = _normalize_string_list(self.continuity_watch_items)
        self.forbidden_shortcuts = _normalize_string_list(self.forbidden_shortcuts)
        self.target_length_chars = max(0, int(self.target_length_chars or 0))

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(slots=True)
class SmokeContinuationStepConfig:
    step_id: str
    target_segment_id: str | None = None
    anchor_context_path: str = ""
    recent_window_refs: list[str] = field(default_factory=list)
    reference_truth_path: str = ""
    metadata: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        self.step_id = _normalize_text(self.step_id)
        self.target_segment_id = _normalize_optional_text(self.target_segment_id)
        self.anchor_context_path = _normalize_text(self.anchor_context_path)
        self.recent_window_refs = _normalize_string_list(self.recent_window_refs)
        self.reference_truth_path = _normalize_text(self.reference_truth_path)
        self.metadata = _normalize_metadata(self.metadata)
        if not self.step_id:
            raise ValueError("step_id is required")
        if not self.anchor_context_path:
            raise ValueError("anchor_context_path is required")
        if not self.reference_truth_path:
            raise ValueError("reference_truth_path is required")

    def to_dict(self) -> dict[str, Any]:
        return {
            "step_id": self.step_id,
            "target_segment_id": self.target_segment_id,
            "anchor_context_path": self.anchor_context_path,
            "recent_window_refs": list(self.recent_window_refs),
            "reference_truth_path": self.reference_truth_path,
            "metadata": dict(self.metadata),
        }


@dataclass(slots=True)
class SmokeSampleConfig:
    sample_id: str
    book_id: str
    target_chapter_id: str
    target_segment_id: str | None = None
    mode: SmokeMode = "chapter_authorized"
    anchor_context_path: str = ""
    recent_window_refs: list[str] = field(default_factory=list)
    documents_cutoff: DocumentsCutoff = field(default_factory=lambda: DocumentsCutoff(max_document_title_index="0"))
    allowed_outline_scope: AllowedOutlineScope = field(default_factory=AllowedOutlineScope)
    forward_guidance: ForwardGuidance | None = None
    reference_truth_path: str = ""
    metadata: dict[str, Any] = field(default_factory=dict)
    continuation_steps: list[SmokeContinuationStepConfig] = field(default_factory=list)

    def __post_init__(self) -> None:
        self.sample_id = _normalize_text(self.sample_id)
        self.book_id = _normalize_text(self.book_id)
        self.target_chapter_id = _normalize_text(self.target_chapter_id)
        self.target_segment_id = _normalize_optional_text(self.target_segment_id)
        normalized_mode = _normalize_text(self.mode)
        if normalized_mode not in {"blind_prefix", "chapter_authorized", "bounded_future_hint"}:
            raise ValueError("mode must be blind_prefix, chapter_authorized, or bounded_future_hint")
        self.mode = normalized_mode  # type: ignore[assignment]
        self.anchor_context_path = _normalize_text(self.anchor_context_path)
        self.recent_window_refs = _normalize_string_list(self.recent_window_refs)
        self.reference_truth_path = _normalize_text(self.reference_truth_path)
        self.metadata = _normalize_metadata(self.metadata)
        self.continuation_steps = [
            item if isinstance(item, SmokeContinuationStepConfig) else SmokeContinuationStepConfig(**item)
            for item in self.continuation_steps
        ]
        if not self.sample_id:
            raise ValueError("sample_id is required")
        if not self.book_id:
            raise ValueError("book_id is required")
        if not self.target_chapter_id:
            raise ValueError("target_chapter_id is required")
        if not self.anchor_context_path:
            raise ValueError("anchor_context_path is required")
        if not self.reference_truth_path:
            raise ValueError("reference_truth_path is required")
        if self.mode == "bounded_future_hint" and self.forward_guidance is None:
            raise ValueError("forward_guidance is required when mode is bounded_future_hint")

    def to_dict(self) -> dict[str, Any]:
        return {
            "sample_id": self.sample_id,
            "book_id": self.book_id,
            "target_chapter_id": self.target_chapter_id,
            "target_segment_id": self.target_segment_id,
            "mode": self.mode,
            "anchor_context_path": self.anchor_context_path,
            "recent_window_refs": list(self.recent_window_refs),
            "documents_cutoff": self.documents_cutoff.to_dict(),
            "allowed_outline_scope": self.allowed_outline_scope.to_dict(),
            "forward_guidance": self.forward_guidance.to_dict() if self.forward_guidance is not None else None,
            "reference_truth_path": self.reference_truth_path,
            "metadata": dict(self.metadata),
            "continuation_steps": [item.to_dict() for item in self.continuation_steps],
        }


@dataclass(slots=True)
class SmokeTextArtifact:
    path: str
    text: str

    def __post_init__(self) -> None:
        self.path = _normalize_text(self.path)
        self.text = str(self.text).strip()

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(slots=True)
class LoadedSmokeStep:
    step_id: str
    target_segment_id: str | None = None
    anchor_context: SmokeTextArtifact = field(default_factory=lambda: SmokeTextArtifact(path="", text=""))
    recent_window: list[SmokeTextArtifact] = field(default_factory=list)
    reference_truth: SmokeTextArtifact = field(
        default_factory=lambda: SmokeTextArtifact(path="", text="")
    )
    metadata: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        self.step_id = _normalize_text(self.step_id)
        self.target_segment_id = _normalize_optional_text(self.target_segment_id)
        self.metadata = _normalize_metadata(self.metadata)
        if not self.step_id:
            raise ValueError("step_id is required")

    @property
    def recent_window_summary(self) -> str:
        return "\n\n".join(item.text for item in self.recent_window if item.text).strip()

    def to_dict(self) -> dict[str, Any]:
        return {
            "step_id": self.step_id,
            "target_segment_id": self.target_segment_id,
            "anchor_context": self.anchor_context.to_dict(),
            "recent_window": [item.to_dict() for item in self.recent_window],
            "reference_truth": self.reference_truth.to_dict(),
            "metadata": dict(self.metadata),
        }


@dataclass(slots=True)
class LoadedSmokeSample:
    config: SmokeSampleConfig
    sample_path: str
    steps: list[LoadedSmokeStep] = field(default_factory=list)

    def __post_init__(self) -> None:
        self.sample_path = _normalize_text(self.sample_path)
        if not self.steps:
            raise ValueError("steps is required")

    @property
    def first_step(self) -> LoadedSmokeStep:
        return self.steps[0]

    @property
    def anchor_context(self) -> SmokeTextArtifact:
        return self.first_step.anchor_context

    @property
    def recent_window(self) -> list[SmokeTextArtifact]:
        return self.first_step.recent_window

    @property
    def recent_window_summary(self) -> str:
        return self.first_step.recent_window_summary

    @property
    def reference_truth(self) -> SmokeTextArtifact:
        return self.first_step.reference_truth

    def to_dict(self) -> dict[str, Any]:
        return {
            "config": self.config.to_dict(),
            "sample_path": self.sample_path,
            "steps": [item.to_dict() for item in self.steps],
        }


@dataclass(slots=True)
class AuthorizedInputs:
    prefix_facts: dict[str, Any] = field(default_factory=dict)
    current_unit_plan: dict[str, Any] = field(default_factory=dict)
    bounded_future_hint: dict[str, Any] | None = None
    scene_plan_seed: dict[str, Any] = field(default_factory=dict)
    scene_brief_seed: dict[str, Any] = field(default_factory=dict)
    related_character_names: list[str] = field(default_factory=list)
    target_length_chars: int = 0

    def __post_init__(self) -> None:
        self.prefix_facts = _normalize_metadata(self.prefix_facts)
        self.current_unit_plan = _normalize_metadata(self.current_unit_plan)
        self.bounded_future_hint = (
            _normalize_metadata(self.bounded_future_hint)
            if self.bounded_future_hint is not None
            else None
        )
        self.scene_plan_seed = _normalize_metadata(self.scene_plan_seed)
        self.scene_brief_seed = _normalize_metadata(self.scene_brief_seed)
        self.related_character_names = _normalize_string_list(self.related_character_names)
        self.target_length_chars = max(0, int(self.target_length_chars or 0))

    def to_dict(self) -> dict[str, Any]:
        return {
            "prefix_facts": dict(self.prefix_facts),
            "current_unit_plan": dict(self.current_unit_plan),
            "bounded_future_hint": (
                dict(self.bounded_future_hint) if self.bounded_future_hint is not None else None
            ),
            "scene_plan_seed": dict(self.scene_plan_seed),
            "scene_brief_seed": dict(self.scene_brief_seed),
            "related_character_names": list(self.related_character_names),
            "target_length_chars": self.target_length_chars,
        }


@dataclass(slots=True)
class PrefixRuntimeSnapshot:
    sample_id: str
    snapshot_root: str
    db_path: str
    assets_root: str
    max_document_title_index: str
    copied_doc_count: int = 0
    copied_chapter_count: int = 0
    copied_character_profile_count: int = 0
    asset_paths: dict[str, str] = field(default_factory=dict)
    warnings: list[str] = field(default_factory=list)

    def __post_init__(self) -> None:
        self.sample_id = _normalize_text(self.sample_id)
        self.snapshot_root = _normalize_text(self.snapshot_root)
        self.db_path = _normalize_text(self.db_path)
        self.assets_root = _normalize_text(self.assets_root)
        self.max_document_title_index = _normalize_text(self.max_document_title_index)
        self.asset_paths = {
            str(key): _normalize_text(value)
            for key, value in self.asset_paths.items()
            if _normalize_text(key) and _normalize_text(value)
        }
        self.warnings = _normalize_string_list(self.warnings)

    @property
    def snapshot_root_path(self) -> Path:
        return Path(self.snapshot_root)

    @property
    def db_path_obj(self) -> Path:
        return Path(self.db_path)

    def to_dict(self) -> dict[str, Any]:
        return {
            "sample_id": self.sample_id,
            "snapshot_root": self.snapshot_root,
            "db_path": self.db_path,
            "assets_root": self.assets_root,
            "max_document_title_index": self.max_document_title_index,
            "copied_doc_count": self.copied_doc_count,
            "copied_chapter_count": self.copied_chapter_count,
            "copied_character_profile_count": self.copied_character_profile_count,
            "asset_paths": dict(self.asset_paths),
            "warnings": list(self.warnings),
        }


SmokeDecision = Literal["pass", "borderline", "fail"]


@dataclass(slots=True)
class SmokeCompareIssue:
    type: str
    severity: str
    message: str
    evidence: str = ""

    def __post_init__(self) -> None:
        self.type = _normalize_text(self.type)
        self.severity = _normalize_text(self.severity)
        self.message = _normalize_text(self.message)
        self.evidence = _normalize_text(self.evidence)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(slots=True)
class SmokeHardGate:
    passed: bool = True
    fatal_issues: list[SmokeCompareIssue] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "passed": self.passed,
            "fatal_issues": [item.to_dict() for item in self.fatal_issues],
        }


@dataclass(slots=True)
class SmokeScoreExplanation:
    metric: str
    summary: str

    def __post_init__(self) -> None:
        self.metric = _normalize_text(self.metric)
        self.summary = _normalize_text(self.summary)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(slots=True)
class SmokeEvidenceRef:
    type: str
    ref: str

    def __post_init__(self) -> None:
        self.type = _normalize_text(self.type)
        self.ref = _normalize_text(self.ref)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(slots=True)
class SmokeCompareScores:
    hard_consistency: float = 0.0
    recent_window_coherence: float | None = None
    chapter_outline_fulfillment: float | None = None
    forward_guidance_adherence: float | None = None
    character_consistency: float | None = None
    relationship_transition_legality: float | None = None
    world_rule_compliance: float | None = None
    style_alignment: float | None = None
    retrieval_effectiveness: float | None = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(slots=True)
class SmokeCompareReport:
    sample_id: str
    mode: SmokeMode
    step_id: str = ""
    hard_gate: SmokeHardGate = field(default_factory=SmokeHardGate)
    scores: SmokeCompareScores = field(default_factory=SmokeCompareScores)
    weighted_score: float = 0.0
    decision: SmokeDecision = "fail"
    explanations: list[SmokeScoreExplanation] = field(default_factory=list)
    evidence_refs: list[SmokeEvidenceRef] = field(default_factory=list)
    generated_chars: int = 0
    reference_truth_chars: int = 0

    def __post_init__(self) -> None:
        self.sample_id = _normalize_text(self.sample_id)
        normalized_mode = _normalize_text(self.mode)
        if normalized_mode not in {"blind_prefix", "chapter_authorized", "bounded_future_hint"}:
            raise ValueError("mode must be blind_prefix, chapter_authorized, or bounded_future_hint")
        self.mode = normalized_mode  # type: ignore[assignment]
        self.step_id = _normalize_text(self.step_id)
        self.weighted_score = max(0.0, min(1.0, float(self.weighted_score)))
        normalized_decision = _normalize_text(self.decision)
        if normalized_decision not in {"pass", "borderline", "fail"}:
            raise ValueError("decision must be pass, borderline, or fail")
        self.decision = normalized_decision  # type: ignore[assignment]
        self.generated_chars = max(0, int(self.generated_chars))
        self.reference_truth_chars = max(0, int(self.reference_truth_chars))

    def to_dict(self) -> dict[str, Any]:
        return {
            "sample_id": self.sample_id,
            "mode": self.mode,
            "step_id": self.step_id,
            "hard_gate": self.hard_gate.to_dict(),
            "scores": self.scores.to_dict(),
            "weighted_score": self.weighted_score,
            "decision": self.decision,
            "explanations": [item.to_dict() for item in self.explanations],
            "evidence_refs": [item.to_dict() for item in self.evidence_refs],
            "generated_chars": self.generated_chars,
            "reference_truth_chars": self.reference_truth_chars,
        }


SmokeReviewerDecision = Literal["pass", "borderline", "fail"]


@dataclass(slots=True)
class SmokeReviewerIssue:
    type: str
    severity: str
    message: str
    evidence: str = ""

    def __post_init__(self) -> None:
        self.type = _normalize_text(self.type)
        self.severity = _normalize_text(self.severity)
        self.message = _normalize_text(self.message)
        self.evidence = _normalize_text(self.evidence)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(slots=True)
class SmokeReviewerCheck:
    name: str
    status: SmokeReviewerDecision
    score: float
    summary: str

    def __post_init__(self) -> None:
        self.name = _normalize_text(self.name)
        normalized_status = _normalize_text(self.status)
        if normalized_status not in {"pass", "borderline", "fail"}:
            raise ValueError("status must be pass, borderline, or fail")
        self.status = normalized_status  # type: ignore[assignment]
        self.score = round(max(0.0, min(1.0, float(self.score))), 4)
        self.summary = _normalize_text(self.summary)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(slots=True)
class SmokeReviewerReport:
    decision: SmokeReviewerDecision
    score: float
    summary: str
    checks: dict[str, SmokeReviewerCheck] = field(default_factory=dict)
    issues: list[SmokeReviewerIssue] = field(default_factory=list)
    generated_chars: int = 0
    reference_truth_chars: int = 0

    def __post_init__(self) -> None:
        normalized_decision = _normalize_text(self.decision)
        if normalized_decision not in {"pass", "borderline", "fail"}:
            raise ValueError("decision must be pass, borderline, or fail")
        self.decision = normalized_decision  # type: ignore[assignment]
        self.score = round(max(0.0, min(1.0, float(self.score))), 4)
        self.summary = _normalize_text(self.summary)
        self.checks = {
            str(key): value if isinstance(value, SmokeReviewerCheck) else SmokeReviewerCheck(**value)
            for key, value in self.checks.items()
        }
        self.issues = [
            issue if isinstance(issue, SmokeReviewerIssue) else SmokeReviewerIssue(**issue)
            for issue in self.issues
        ]
        self.generated_chars = max(0, int(self.generated_chars))
        self.reference_truth_chars = max(0, int(self.reference_truth_chars))

    def to_dict(self) -> dict[str, Any]:
        return {
            "decision": self.decision,
            "score": self.score,
            "summary": self.summary,
            "checks": {key: value.to_dict() for key, value in self.checks.items()},
            "issues": [item.to_dict() for item in self.issues],
            "generated_chars": self.generated_chars,
            "reference_truth_chars": self.reference_truth_chars,
        }
